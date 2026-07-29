import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

async function readProjectFile(relativePath) {
  return readFile(path.join(rootDir, relativePath), "utf8");
}

test("quickstart contains only the fixed three user steps", async () => {
  const quickstart = await readProjectFile("quickstart.md");

  assert.equal((quickstart.match(/^## /gm) ?? []).length, 3);
  assert.match(quickstart, /uv tool install/);
  assert.match(quickstart, /sdd-frl init \./);
  assert.match(
    quickstart,
    /请读取 `.sdd-frl\/automation\/task-prompt\.md`，为以下分析目标创建一个独立的 FRL 定时任务。/
  );
  assert.match(quickstart, /分析目标：<目标项目绝对路径>/);
  assert.equal((quickstart.match(/```text/g) ?? []).length, 1);
  assert.doesNotMatch(quickstart, /运行状态机|手工|内部|权限|确认卡/);
});

test("scheduled task contract uses one runtime target with stable defaults", async () => {
  const readme = await readProjectFile("README.md");
  const prompt = await readProjectFile(path.join("automation", "task-prompt.md"));
  const guide = await readProjectFile(path.join("automation", "README.md"));

  assert.match(readme, /目标路径不写入 `.sdd-frl\/config\.json`/);
  assert.match(readme, /sdd-frl prepare \. --target/);
  assert.match(prompt, /缺失时只询问分析目标，不猜测、不扫描/);
  assert.match(prompt, /多个目标不能合并到一个任务/);
  assert.match(prompt, /运行频率默认每天，运行时间默认 `22:00`/);
  assert.match(prompt, /当前目录是内部固定运行目录，不询问/);
  assert.match(prompt, /确认卡和完成回复只包含分析目标、运行频率、运行时间及启用状态/);
  assert.match(guide, /各任务分别保存自己的目标、运行频率和运行时间，\s*互不影响/);
  assert.match(guide, /目标路径只进入对应任务及该任务产生的 `run\.json`/);
});
