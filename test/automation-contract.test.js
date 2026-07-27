import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

async function readProjectFile(relativePath) {
  return readFile(path.join(rootDir, relativePath), "utf8");
}

test("quickstart binds each scheduled task to its target workspace", async () => {
  const quickstart = await readProjectFile("quickstart.md");
  const prompt = await readProjectFile(path.join("automation", "task-prompt.md"));

  assert.match(quickstart, /sdd-frl init \./);
  assert.match(quickstart, /sdd-frl run \./);
  assert.match(quickstart, /docs\/failure-review\/YYYY-MM-DD\.md/);
  assert.match(quickstart, /任务不能绑定到中央 `Failure-Review-Loop` 运行器/);
  assert.doesNotMatch(quickstart, /## 4\./);
  assert.match(prompt, /只复盘它所绑定的当前工作区/);
  assert.match(prompt, /所有中间产物、锁和最终文档必须留在当前工作区内/);
});

test("automation onboarding exposes only the three user operations", async () => {
  const guide = await readProjectFile(path.join("automation", "README.md"));

  assert.match(guide, /用户只有三步操作/);
  assert.match(guide, /uv tool install/);
  assert.match(guide, /sdd-frl init \./);
  assert.match(guide, /Codex App/);
  assert.doesNotMatch(guide, /手工运行一次/);
});
