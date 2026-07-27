import { readFile } from "node:fs/promises";
import path from "node:path";
import { writeText } from "./io.js";
import { spawnCommand } from "./process.js";

function configValue(value) {
  return `model_reasoning_effort=${JSON.stringify(value)}`;
}

export async function runCodexStage({
  stage, model, reasoningEffort, promptFile, schemaFile, inputFiles,
  outputFile, logFile, rootDir
}) {
  const basePrompt = await readFile(promptFile, "utf8");
  const runtime = [
    "",
    "## 本次运行的只读文件",
    ...Object.entries(inputFiles).map(([name, file]) => `- ${name}: ${path.resolve(file)}`),
    "",
    `阶段：${stage}`,
    "读取上述文件后直接返回契约 JSON。不要写入或修改任何文件。"
  ].join("\n");
  const prompt = `${basePrompt}\n${runtime}\n`;
  const tempOutput = `${outputFile}.${process.pid}.agent-output.tmp`;
  const args = [
    "--ask-for-approval", "never", "exec",
    "--ephemeral", "--ignore-user-config", "--ignore-rules",
    "--sandbox", "read-only",
    "--model", model, "--config", configValue(reasoningEffort),
    "--output-schema", schemaFile, "--output-last-message", tempOutput,
    "--json", "--cd", rootDir, "-"
  ];

  const result = await new Promise((resolve, reject) => {
    const child = spawnCommand("codex", args, { cwd: rootDir, stdio: ["pipe", "pipe", "pipe"] });
    const stdout = [];
    const stderr = [];
    child.stdout.on("data", (chunk) => stdout.push(chunk));
    child.stderr.on("data", (chunk) => stderr.push(chunk));
    child.on("error", reject);
    child.on("close", (code) => resolve({
      code,
      stdout: Buffer.concat(stdout).toString("utf8"),
      stderr: Buffer.concat(stderr).toString("utf8")
    }));
    child.stdin.end(prompt);
  });

  await writeText(logFile, [
    JSON.stringify({ stage, model, reasoning_effort: reasoningEffort }),
    result.stdout,
    result.stderr
  ].filter(Boolean).join("\n"));
  if (result.code !== 0) throw new Error(`${stage} Codex process exited with ${result.code}. See ${logFile}.`);
  const text = await readFile(tempOutput, "utf8");
  await writeText(outputFile, text.endsWith("\n") ? text : `${text}\n`);
  return JSON.parse(text);
}
