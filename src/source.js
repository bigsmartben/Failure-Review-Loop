import { createReadStream } from "node:fs";
import { access, readdir, readFile } from "node:fs/promises";
import path from "node:path";
import readline from "node:readline";
import { redact } from "./redact.js";
import { resolveFrom } from "./io.js";
import { contentHash } from "./hash.js";

async function exists(file) {
  try { await access(file); return true; } catch { return false; }
}

async function listJsonl(dir) {
  const result = [];
  if (!await exists(dir)) return result;
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const file = path.join(dir, entry.name);
    if (entry.isDirectory()) result.push(...await listJsonl(file));
    else if (entry.isFile() && entry.name.endsWith(".jsonl")) result.push(file);
  }
  return result;
}

function textContent(content) {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return JSON.stringify(content);
  return content.map((item) =>
    item?.text ?? item?.input_text ?? item?.output_text ?? JSON.stringify(item)).join("\n");
}

function artifactReferences(text) {
  const matches = text.match(/(?:[A-Za-z]:[\\/][^\s"'<>|]+|(?:\.{0,2}[\\/])?[A-Za-z0-9_.-]+(?:[\\/][A-Za-z0-9_.-]+)*\.(?:md|json|ya?ml|toml|js|ts|py|log|txt))/g) ?? [];
  return [...new Set(matches)];
}

function classifyResponse(payload) {
  if (payload.type === "message") {
    const actor = ["user", "assistant", "system"].includes(payload.role) ? payload.role : "system";
    return [{
      actor,
      event_type: "message",
      call_id: null,
      content: textContent(payload.content),
      location: `response_item:${actor}`
    }];
  }
  if (["function_call", "custom_tool_call"].includes(payload.type)) {
    return [{
      actor: "tool",
      event_type: "tool_call",
      call_id: payload.call_id ?? null,
      content: JSON.stringify({
        name: payload.name,
        arguments: payload.arguments ?? payload.input,
        call_id: payload.call_id ?? null
      }),
      location: `response_item:${payload.type}`
    }];
  }
  if (["function_call_output", "custom_tool_call_output"].includes(payload.type)) {
    const output = textContent(payload.output);
    const failed = /exit code:\s*[1-9]|process exited with code [1-9]|isError["']?\s*:\s*true/i.test(output);
    const items = [{
      actor: "tool",
      event_type: failed ? "execution_error" : "tool_result",
      call_id: payload.call_id ?? null,
      content: output,
      location: `response_item:${payload.type}`
    }];
    if (!failed) {
      for (const reference of artifactReferences(output)) {
        items.push({
          actor: "tool",
          event_type: "artifact_reference",
          call_id: payload.call_id ?? null,
          content: reference,
          location: "derived-artifact-reference"
        });
      }
    }
    return items;
  }
  return [];
}

async function readSessionMeta(file) {
  const stream = createReadStream(file, { encoding: "utf8" });
  const lines = readline.createInterface({ input: stream, crlfDelay: Infinity });
  for await (const line of lines) {
    if (!line.trim()) continue;
    const row = JSON.parse(line);
    if (row.type === "session_meta") {
      lines.close();
      stream.destroy();
      return row.payload;
    }
  }
  return null;
}

function inside(candidate, root) {
  const relative = path.relative(path.resolve(root), path.resolve(candidate));
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
}

async function bindingAccepts(meta, binding, configDir) {
  const conversationId = meta.id ?? meta.session_id;
  if ((binding.conversation_ids ?? []).includes(conversationId)) {
    return { accepted: true, method: "explicit_conversation_id" };
  }
  for (const configuredRoot of binding.roots ?? []) {
    const root = resolveFrom(configDir, configuredRoot);
    if (!inside(meta.cwd, root)) continue;
    const marker = path.join(root, binding.marker_file ?? "failure-review.project.json");
    if (!await exists(marker)) continue;
    const markerData = JSON.parse(await readFile(marker, "utf8"));
    if (markerData.project_id === binding.project_id) {
      return { accepted: true, method: "project_marker_plus_workspace_root" };
    }
  }
  return { accepted: false, method: null };
}

export async function collectSourcePacket({ config, configDir, projectId, windowStart, windowEnd }) {
  const binding = config.project_bindings.find((item) => item.project_id === projectId);
  if (!binding) throw new Error(`No project binding for ${projectId}.`);
  const codexHome = config.codex_home
    ? resolveFrom(configDir, config.codex_home)
    : path.join(process.env.CODEX_HOME || path.join(process.env.USERPROFILE || process.env.HOME, ".codex"));
  const files = await listJsonl(path.join(codexHome, "sessions"));
  const start = Date.parse(windowStart);
  const end = Date.parse(windowEnd);
  const conversations = [];
  const summary = {
    session_files_scanned: files.length,
    target_conversations_matched: 0,
    records_before_window: 0,
    records_in_window: 0,
    records_after_window: 0,
    skipped_missing_meta: 0,
    skipped_outside_target: 0,
    skipped_uncollectable: 0
  };
  let rawEventsInWindow = 0;

  for (const file of files) {
    const meta = await readSessionMeta(file);
    if (!meta?.cwd) {
      summary.skipped_missing_meta += 1;
      continue;
    }
    const decision = await bindingAccepts(meta, binding, configDir);
    if (!decision.accepted) {
      summary.skipped_outside_target += 1;
      continue;
    }
    summary.target_conversations_matched += 1;
    const conversationId = meta.id ?? meta.session_id;
    const records = [];
    let sequence = 0;
    let hasEventsBeforeWindow = false;
    let hasEventsAfterWindow = false;
    let lineNumber = 0;
    const lines = readline.createInterface({
      input: createReadStream(file, { encoding: "utf8" }),
      crlfDelay: Infinity
    });

    for await (const line of lines) {
      lineNumber += 1;
      if (!line.trim()) continue;
      const row = JSON.parse(line);
      if (row.type !== "response_item") continue;
      const timestamp = Date.parse(row.timestamp);
      if (!Number.isFinite(timestamp) || !row.payload || typeof row.payload !== "object") {
        summary.skipped_uncollectable += 1;
        continue;
      }
      if (timestamp >= start && timestamp < end) rawEventsInWindow += 1;
      const items = classifyResponse(row.payload);
      if (!items.length) {
        summary.skipped_uncollectable += 1;
        continue;
      }
      for (const item of items) {
        const itemSequence = sequence++;
        if (timestamp < start) {
          hasEventsBeforeWindow = true;
          summary.records_before_window += 1;
          continue;
        }
        if (timestamp >= end) {
          hasEventsAfterWindow = true;
          summary.records_after_window += 1;
          continue;
        }
        if (!item.content) {
          summary.skipped_uncollectable += 1;
          continue;
        }
        const content = config.privacy?.content_mode === "redact_secrets"
          ? redact(item.content)
          : item.content;
        const sourceRecord = {
          conversation_id: conversationId,
          timestamp: row.timestamp,
          actor: item.actor,
          sequence: itemSequence,
          event_type: item.event_type,
          call_id: item.call_id,
          source_location: `${path.basename(file)}:${lineNumber}:${item.location}`,
          content_or_reference: content,
          collection_status: item.event_type === "artifact_reference"
            ? "referenced"
            : content !== item.content
              ? "redacted"
              : "collected"
        };
        records.push({ ...sourceRecord, content_hash: contentHash(sourceRecord) });
        summary.records_in_window += 1;
      }
    }

    conversations.push({
      conversation_id: conversationId,
      project_id: projectId,
      binding_method: decision.method,
      has_events_before_window: hasEventsBeforeWindow,
      has_events_after_window: hasEventsAfterWindow,
      records
    });
  }

  const emptyReason = summary.target_conversations_matched === 0
    ? "ANALYSIS_TARGET_CONVERSATIONS_NOT_FOUND"
    : summary.records_in_window > 0
      ? null
      : rawEventsInWindow > 0
        ? "EVENTS_IN_WINDOW_UNCOLLECTABLE"
        : "NO_EVENTS_IN_WINDOW";
  return {
    schema_version: "1.0.0",
    source_kind: "local_codex_sessions_jsonl",
    project_id: projectId,
    window_start: windowStart,
    window_end: windowEnd,
    empty_reason: emptyReason,
    collection_summary: summary,
    conversations
  };
}
