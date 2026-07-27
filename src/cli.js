#!/usr/bin/env node
import path from "node:path";
import { fileURLToPath } from "node:url";
import { readdir } from "node:fs/promises";
import { executeRun } from "./orchestrator.js";
import { readJson } from "./io.js";
import { validateArtifact } from "./validation.js";
import { validateSchema } from "./schema.js";
import { captureCommand } from "./process.js";

const rootDir = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

function parse(argv) {
  const result = { _: [] };
  for (let i = 0; i < argv.length; i += 1) {
    const item = argv[i];
    if (!item.startsWith("--")) result._.push(item);
    else {
      const key = item.slice(2).replace(/-([a-z])/g, (_, char) => char.toUpperCase());
      const next = argv[i + 1];
      result[key] = next && !next.startsWith("--") ? argv[++i] : true;
    }
  }
  return result;
}

function required(args, names) {
  for (const name of names) {
    if (!args[name]) throw new Error(`Missing required option --${name.replace(/[A-Z]/g, (char) => `-${char.toLowerCase()}`)}.`);
  }
}

async function validateCommand(args) {
  required(args, ["kind", "file"]);
  const data = await readJson(path.resolve(args.file));
  const context = {};
  if (args.run) context.run = await readJson(path.resolve(args.run));
  if (args.evidence) context.evidence = await readJson(path.resolve(args.evidence));
  if (args.findings) context.findings = await readJson(path.resolve(args.findings));
  if (args.metrics) context.metrics = await readJson(path.resolve(args.metrics));
  if (args.baselineMetrics) context.baselineMetrics = await readJson(path.resolve(args.baselineMetrics));
  const result = await validateArtifact(args.kind, data, context, rootDir);
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  if (!result.valid) process.exitCode = 1;
}

async function validateExamples() {
  const examplesDir = path.join(rootDir, "examples");
  const files = (await readdir(examplesDir)).filter((name) => name.endsWith(".json"));
  let failed = false;
  for (const file of files.sort()) {
    const match = /^(run|evidence|findings|metrics|trend|proposal)\.(valid|invalid)\./.exec(file);
    if (!match) continue;
    const [, kind, expectation] = match;
    const result = await validateSchema(kind, await readJson(path.join(examplesDir, file)), rootDir);
    const passed = result.valid === (expectation === "valid");
    process.stdout.write(`${passed ? "PASS" : "FAIL"} ${file}\n`);
    failed ||= !passed;
  }
  if (failed) process.exitCode = 1;
}

async function probe(args) {
  const config = await readJson(path.resolve(args.config ?? path.join(rootDir, "failure-review.config.example.json")));
  const [{ stdout: version }, { stdout: help }] = await Promise.all([
    captureCommand("codex", ["--version"]),
    captureCommand("codex", ["exec", "--help"])
  ]);
  const efforts = new Set(["low", "medium", "high", "xhigh", "max", "ultra"]);
  const stages = Object.entries(config.models).map(([stage, value]) => ({
    stage,
    planned_name: value.planned_name,
    model: value.model,
    reasoning_effort: value.reasoning_effort,
    effort_syntax_valid: efforts.has(value.reasoning_effort)
  }));
  process.stdout.write(`${JSON.stringify({
    codex_version: version.trim(),
    capabilities: {
      output_schema: help.includes("--output-schema"),
      output_last_message: help.includes("--output-last-message"),
      model_flag: help.includes("--model"),
      reasoning_config: help.includes("--config")
    },
    model_mapping: stages,
    note: "CLI has no supported list-models command; account availability is verified by the first real stage invocation."
  }, null, 2)}\n`);
}

function usage() {
  return `Failure Review Loop

Commands:
  run --config FILE --project-id ID --window-start ISO --window-end ISO --timezone TZ [--target-skill FILE] [--run-id ID]
  validate --kind run|evidence|findings|metrics|trend|proposal --file FILE [--run FILE] [--evidence FILE] [--findings FILE] [--metrics FILE] [--baseline-metrics FILE]
  validate-examples
  probe [--config FILE]
`;
}

async function main() {
  const args = parse(process.argv.slice(2));
  const command = args._[0];
  if (command === "run") {
    required(args, ["config", "projectId", "windowStart", "windowEnd", "timezone"]);
    const run = await executeRun({ ...args, configFile: args.config, rootDir });
    process.stdout.write(`${JSON.stringify({ run_id: run.run_id, status: run.status }, null, 2)}\n`);
    if (run.status.startsWith("FAILED_")) process.exitCode = 1;
  } else if (command === "validate") await validateCommand(args);
  else if (command === "validate-examples") await validateExamples();
  else if (command === "probe") await probe(args);
  else {
    process.stdout.write(usage());
    if (command && command !== "help") process.exitCode = 1;
  }
}

main().catch((error) => {
  process.stderr.write(`${error.stack ?? error.message}\n`);
  process.exitCode = 1;
});
