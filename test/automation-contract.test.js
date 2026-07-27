import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

async function readProjectFile(relativePath) {
  return readFile(path.join(rootDir, relativePath), "utf8");
}

test("quickstart binds the scheduled task to the runner and requires prompt contents", async () => {
  const quickstart = await readProjectFile("quickstart.md");

  assert.match(quickstart, /运行器项目（runner project）/);
  assert.match(quickstart, /已安排任务必须绑定到 `Failure-Review-Loop`/);
  assert.match(quickstart, /不要只填写文件路径/);
  assert.match(quickstart, /目标 project_id: <配置中的项目 ID>/);
  assert.match(quickstart, /npm run configure:project/);
  assert.match(quickstart, /--project-id pre-sdd/);
  assert.match(quickstart, /--project-root "C:\\Users\\24598\\Documents\\github\\psp"/);
  assert.match(quickstart, /重复执行是幂等的/);
});
