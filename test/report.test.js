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
  assert.match(rendered, /EVIDENCE_POINTER_UNRESOLVED/);
  assert.match(rendered, /同一任务关联 2 个问题簇/);
  assert.match(rendered, /证据不足，根因尚未确认/);
});
