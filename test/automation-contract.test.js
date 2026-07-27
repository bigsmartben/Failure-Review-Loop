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
  const readme = await readProjectFile("README.md");
  const quickstart = await readProjectFile("quickstart.md");
  const prompt = await readProjectFile(path.join("automation", "task-prompt.md"));

  assert.match(readme, /维护者（maintainer）/);
  assert.match(readme, /sdd-frl probe \./);
  assert.match(readme, /\.sdd-frl\/runs\/<run_id>\//);
  assert.doesNotMatch(readme, /请读取当前项目的 `.sdd-frl\/automation\/task-prompt\.md`/);
  assert.match(quickstart, /使用者快速开始/);
  assert.match(quickstart, /sdd-frl init \./);
  assert.match(quickstart, /复制、粘贴、发送/);
  assert.match(quickstart, /请读取当前项目的 `.sdd-frl\/automation\/task-prompt\.md`/);
  assert.match(quickstart, /docs\/failure-review\/YYYY-MM-DD\.md/);
  assert.doesNotMatch(quickstart, /sdd-frl probe \./);
  assert.doesNotMatch(quickstart, /\.sdd-frl\/runs\/<run_id>\//);
  assert.equal((quickstart.match(/```text/g) ?? []).length, 1);
  assert.match(prompt, /只复盘它所绑定的当前工作区/);
  assert.match(prompt, /所有中间产物、锁和最终文档必须留在当前工作区内/);
});

test("automation onboarding exposes only the three user operations", async () => {
  const guide = await readProjectFile(path.join("automation", "README.md"));

  assert.match(guide, /用户只有三步操作/);
  assert.match(guide, /uv tool install/);
  assert.match(guide, /sdd-frl init \./);
  assert.match(guide, /根目录 `quickstart\.md`/);
  assert.doesNotMatch(guide, /手工运行一次/);
});
