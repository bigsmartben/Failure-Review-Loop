import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {
  buildAnalysisOnlyConfig,
  ensureProductConfig
} from "../src/init-product.js";

function exampleConfig() {
  return {
    schema_version: "1.0.0",
    runs_dir: "runs",
    codex_home: null,
    project_bindings: [{
      project_id: "failure-review-loop",
      roots: ["."],
      marker_file: "failure-review.project.json",
      conversation_ids: [],
      improvement_target_ids: ["placeholder"]
    }],
    improvement_targets: [{
      id: "placeholder",
      type: "skill",
      path: "C:/replace/with/SKILL.md"
    }],
    models: {
      collector: { model: "collector-model", reasoning_effort: "low" },
      analyst: { model: "analyst-model", reasoning_effort: "high" },
      optimizer: { model: "optimizer-model", reasoning_effort: "xhigh" }
    },
    privacy: { content_mode: "redact_secrets" }
  };
}

test("analysis-only initialization removes placeholder targets", () => {
  const result = buildAnalysisOnlyConfig(exampleConfig());
  assert.deepEqual(result.project_bindings[0].improvement_target_ids, []);
  assert.deepEqual(result.improvement_targets, []);
  assert.equal(result.models.analyst.model, "analyst-model");
});

test("initialization creates a safe config when none exists", async () => {
  const temp = await mkdtemp(path.join(os.tmpdir(), "failure-init-test-"));
  const exampleFile = path.join(temp, "example.json");
  const configFile = path.join(temp, "config.json");
  await writeFile(exampleFile, JSON.stringify(exampleConfig()), "utf8");

  const result = await ensureProductConfig({ exampleFile, configFile });
  const config = JSON.parse(await readFile(configFile, "utf8"));

  assert.equal(result.created, true);
  assert.deepEqual(config.project_bindings[0].improvement_target_ids, []);
  assert.deepEqual(config.improvement_targets, []);
});

test("initialization never overwrites an existing config", async () => {
  const temp = await mkdtemp(path.join(os.tmpdir(), "failure-init-test-"));
  const exampleFile = path.join(temp, "example.json");
  const configFile = path.join(temp, "config.json");
  const existing = { custom: "keep-me" };
  await writeFile(exampleFile, JSON.stringify(exampleConfig()), "utf8");
  await writeFile(configFile, JSON.stringify(existing), "utf8");

  const result = await ensureProductConfig({ exampleFile, configFile });

  assert.equal(result.created, false);
  assert.deepEqual(JSON.parse(await readFile(configFile, "utf8")), existing);
});
