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
  assert.match(prompt, /只复盘它所绑定的当前工作区/);
  assert.match(prompt, /所有中间产物、锁和最终文档必须留在当前工作区内/);
});
