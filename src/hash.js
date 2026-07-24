import { createHash } from "node:crypto";

export function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) =>
      `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

export function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

export function contentHash(record) {
  return `sha256:${sha256(canonicalJson({
    conversation_id: record.conversation_id,
    timestamp: record.timestamp,
    actor: record.actor,
    sequence: record.sequence,
    event_type: record.event_type,
    call_id: record.call_id,
    source_location: record.source_location,
    content_or_reference: record.content_or_reference
  }))}`;
}

export function problemFingerprint(instance) {
  return `sha256:${sha256(canonicalJson({
    task_episode_id: instance.task_episode_id,
    conversation_id: instance.conversation_id,
    pattern: instance.pattern,
    issue_signature: instance.issue_signature
  }))}`;
}

export function issueClusterId(value) {
  return `ic_${sha256(canonicalJson({
    pattern: value.pattern,
    issue_signature: value.issue_signature,
    root_cause_category: value.root_cause_category
  })).slice(0, 16)}`;
}

export function targetSetHash(targets) {
  const normalized = [...targets]
    .map((target) => ({
      id: target.id,
      type: target.type,
      path: target.path,
      content_hash: target.content_hash
    }))
    .sort((left, right) => left.id.localeCompare(right.id));
  return `sha256:${sha256(canonicalJson(normalized))}`;
}
