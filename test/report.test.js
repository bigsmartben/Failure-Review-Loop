import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { renderFindingsSection } from "../src/findings-report.js";
import { ROOT } from "./helpers.js";

const FIXTURE = path.join(ROOT, "fixtures", "report", "actionable-findings.json");
const GOLDEN = path.join(ROOT, "fixtures", "report", "actionable-findings.expected.md");
const normalizedLines = (value) => value.replace(/\r\n/g, "\n").trimEnd();

test("actionable findings match the shared golden contract", async () => {
  const data = JSON.parse(await readFile(FIXTURE, "utf8"));

  const rendered = renderFindingsSection(data.findings, data.evidence);

  assert.equal(normalizedLines(rendered), normalizedLines(await readFile(GOLDEN, "utf8")));
  assert(!rendered.includes("sk-live-super-secret"));
  assert(!rendered.includes("C:\\Users\\Alice"));
  assert.match(rendered, /报告对象识别错误（已解决）/);
  assert.match(rendered, /优化对象：Prompt/);
  assert.match(rendered, /未发现有证据支持的分歧/);
  assert(!rendered.includes("task_target_report"));
  assert(!rendered.includes("ev_user_report"));
});
