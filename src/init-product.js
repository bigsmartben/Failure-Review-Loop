#!/usr/bin/env node
import { readFile, writeFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

export function buildAnalysisOnlyConfig(example) {
  return {
    ...example,
    project_bindings: example.project_bindings.map((binding) => ({
      ...binding,
      improvement_target_ids: []
    })),
    improvement_targets: []
  };
}

export async function ensureProductConfig({
  exampleFile = path.join(rootDir, "failure-review.config.example.json"),
  configFile = path.join(rootDir, "failure-review.config.json")
} = {}) {
  try {
    JSON.parse(await readFile(configFile, "utf8"));
    return { created: false, configFile };
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }

  const example = JSON.parse(await readFile(exampleFile, "utf8"));
  const config = buildAnalysisOnlyConfig(example);
  try {
    await writeFile(configFile, `${JSON.stringify(config, null, 2)}\n`, {
      encoding: "utf8",
      flag: "wx"
    });
    return { created: true, configFile };
  } catch (error) {
    if (error.code !== "EEXIST") throw error;
    JSON.parse(await readFile(configFile, "utf8"));
    return { created: false, configFile };
  }
}

async function runNodeStep(label, args) {
  process.stdout.write(`\n${label}\n`);
  await new Promise((resolve, reject) => {
    const child = spawn(process.execPath, args, {
      cwd: rootDir,
      stdio: "inherit",
      shell: false
    });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) resolve();
      else reject(new Error(`${label}失败，退出码 ${code}。`));
    });
  });
}

async function main() {
  const nodeMajor = Number.parseInt(process.versions.node.split(".")[0], 10);
  if (nodeMajor < 20) {
    throw new Error(`需要 Node.js 20 或更高版本；当前为 ${process.version}。`);
  }

  const config = await ensureProductConfig();
  process.stdout.write(
    config.created
      ? `已创建仅分析配置：${config.configFile}\n`
      : `已保留现有配置：${config.configFile}\n`
  );

  await runNodeStep("检查 1/3：仓库测试", ["--test"]);
  await runNodeStep("检查 2/3：Schema 示例", [
    path.join(rootDir, "src", "cli.js"),
    "validate-examples"
  ]);
  await runNodeStep("检查 3/3：Codex CLI 与模型配置", [
    path.join(rootDir, "src", "cli.js"),
    "probe",
    "--config",
    config.configFile
  ]);

  process.stdout.write("\n初始化完成，可以创建已安排任务。\n");
}

const isMain = process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (isMain) {
  main().catch((error) => {
    process.stderr.write(`\n初始化失败：${error.message}\n`);
    process.exitCode = 1;
  });
}
