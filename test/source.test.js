import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { collectSourcePacket } from "../src/source.js";

function row(timestamp, type, payload) {
  return JSON.stringify({ timestamp, type, payload });
}

async function sessionFile(base, day, name, cwd, id, records) {
  const dir = path.join(base, "sessions", day);
  await mkdir(dir, { recursive: true });
  const lines = [
    row("2026-07-24T00:00:00Z", "session_meta", { id, session_id: id, cwd }),
    ...records
  ];
  await writeFile(path.join(dir, name), `${lines.join("\n")}\n`, "utf8");
}

test("Codex source adapter requires project marker and filters [start,end)", async () => {
  const temp = await mkdtemp(path.join(os.tmpdir(), "failure-source-test-"));
  const project = path.join(temp, "project");
  const other = path.join(temp, "other");
  const codexHome = path.join(temp, "codex");
  await mkdir(project);
  await mkdir(other);
  await writeFile(path.join(project, "failure-review.project.json"), JSON.stringify({ project_id: "target" }));
  const records = [
    row("2026-07-23T23:59:59Z", "response_item", { type: "message", role: "user", content: [{ type: "input_text", text: "outside" }] }),
    row("2026-07-24T01:00:00Z", "response_item", { type: "message", role: "user", content: [{ type: "input_text", text: "do work sk-abcdefghijklmnop" }] }),
    row("2026-07-24T01:01:00Z", "response_item", { type: "message", role: "assistant", content: [{ type: "output_text", text: "done" }] }),
    row("2026-07-24T01:02:00Z", "response_item", { type: "message", role: "user", content: [{ type: "input_text", text: "you missed the owner" }] }),
    row("2026-07-24T01:02:30Z", "response_item", { type: "function_call", call_id: "1", name: "write", arguments: "{}" }),
    row("2026-07-24T01:03:00Z", "response_item", { type: "function_call_output", call_id: "1", output: "wrote runs/report.md" }),
    row("2026-07-25T00:00:00Z", "response_item", { type: "message", role: "user", content: [{ type: "input_text", text: "end excluded" }] })
  ];
  await sessionFile(codexHome, "2026/07/24", "accepted.jsonl", project, "accepted", records);
  await sessionFile(codexHome, "2026/07/24", "rejected.jsonl", other, "rejected", records);
  const config = {
    codex_home: codexHome,
    project_bindings: [{ project_id: "target", roots: [project], marker_file: "failure-review.project.json", conversation_ids: [] }],
    privacy: { content_mode: "redact_secrets" }
  };
  const packet = await collectSourcePacket({
    config, configDir: temp, projectId: "target",
    windowStart: "2026-07-24T00:00:00Z", windowEnd: "2026-07-25T00:00:00Z"
  });
  assert.equal(packet.conversations.length, 1);
  assert.equal(packet.conversations[0].conversation_id, "accepted");
  assert.equal(packet.conversations[0].has_events_before_window, true);
  assert.equal(packet.conversations[0].has_events_after_window, true);
  assert(packet.conversations[0].records.some((item) =>
    item.actor === "user" && item.event_type === "message" && item.sequence === 3));
  assert(packet.conversations[0].records.some((item) =>
    item.actor === "tool" && item.event_type === "tool_call" && item.call_id === "1"));
  assert(packet.conversations[0].records.some((item) =>
    item.event_type === "artifact_reference" && item.content_or_reference === "runs/report.md"));
  assert(packet.conversations[0].records.some((item) => item.collection_status === "redacted"));
  assert(packet.conversations[0].records.some((item) =>
    item.event_type === "artifact_reference" && item.collection_status === "referenced"));
  assert.equal(
    new Set(packet.conversations[0].records.map((item) => item.sequence)).size,
    packet.conversations[0].records.length
  );
  assert(!JSON.stringify(packet).includes("sk-abcdefghijklmnop"));
  assert(!JSON.stringify(packet).includes("outside"));
  assert(!JSON.stringify(packet).includes("end excluded"));
});
