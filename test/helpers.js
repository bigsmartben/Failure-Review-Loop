import { mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { contentHash, issueClusterId, problemFingerprint } from "../src/hash.js";
import { writeJson } from "../src/io.js";
import { CONTRACT_REVISION, contractBundleHash } from "../src/contract.js";

export const ROOT = path.dirname(path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Z]:)/, "$1")));
export const CONTRACT_BUNDLE_HASH = await contractBundleHash(ROOT);

export function evidenceRecord(
  id,
  conversationId,
  timestamp,
  content = `failure ${id}`,
  {
    actor = "user",
    sequence = Number(String(id).match(/\d+/)?.[0] ?? 0),
    eventType = "message",
    callId = null
  } = {}
) {
  const record = {
    evidence_id: id,
    conversation_id: conversationId,
    project_id: "test-project",
    timestamp,
    actor,
    sequence,
    event_type: eventType,
    call_id: callId,
    source_location: `${conversationId}:${sequence}`,
    content_or_reference: content,
    collection_status: "collected",
    duplicate_of: null
  };
  return { ...record, content_hash: contentHash(record) };
}

export function evidenceArtifact(runId, records) {
  const conversationIds = [...new Set(records.map((record) => record.conversation_id))];
  return {
    schema_version: "1.0.0",
    contract_revision: CONTRACT_REVISION,
    contract_bundle_hash: CONTRACT_BUNDLE_HASH,
    run_id: runId,
    project_id: "test-project",
    window_start: OPTIONS.windowStart,
    window_end: OPTIONS.windowEnd,
    conversations: conversationIds.map((conversationId) => ({
      conversation_id: conversationId,
      has_events_before_window: false,
      has_events_after_window: false
    })),
    records
  };
}

export function taskEpisode(
  id,
  conversationId,
  evidenceIds,
  {
    startSequence = Number(String(id).match(/\d+/)?.[0] ?? 0),
    endSequence = startSequence,
    contextStatus = "complete",
    outcomeStatus = "not_achieved",
    outcomeBasis = outcomeStatus === "achieved"
      ? "explicit_user_acceptance"
      : outcomeStatus === "not_achieved"
        ? "explicit_user_rejection"
        : "insufficient_evidence",
    outcomeEvidenceIds = outcomeStatus === "unknown" ? [] : [evidenceIds.at(-1)],
    acceptanceCriteria = [],
    counts = {
      turn_count: 1,
      clarification_count: 0,
      repeated_clarification_count: 0,
      execution_attempt_count: outcomeStatus === "not_achieved" ? 1 : 0,
      rework_count: 0
    }
  } = {}
) {
  const interactionEvents = [];
  for (let index = 0; index < counts.clarification_count; index += 1) {
    interactionEvents.push({
      interaction_id: `interaction_${id}_clarification_${index}`,
      kind: "clarification",
      repeated: index < counts.repeated_clarification_count,
      evidence_ids: [evidenceIds[Math.min(index, evidenceIds.length - 1)]]
    });
  }
  for (let index = 0; index < counts.execution_attempt_count; index += 1) {
    interactionEvents.push({
      interaction_id: `interaction_${id}_execution_${index}`,
      kind: "execution_attempt",
      rework: index >= counts.execution_attempt_count - counts.rework_count,
      evidence_ids: [evidenceIds[Math.min(index, evidenceIds.length - 1)]]
    });
  }
  const contextBasis = {
    complete: "fully_observed",
    left_truncated: "left_boundary_continuation",
    right_truncated: "right_boundary_continuation",
    both_truncated: "both_boundary_continuation"
  }[contextStatus];
  return {
    task_episode_id: `task_${id}`,
    conversation_id: conversationId,
    goal: `Goal ${id}`,
    expected_outcome: `Expected ${id}`,
    start_sequence: startSequence,
    end_sequence: endSequence,
    context_status: contextStatus,
    context_basis: contextBasis,
    boundary_evidence_ids: contextStatus === "complete" ? [] : [evidenceIds[0]],
    outcome_status: outcomeStatus,
    outcome_basis: outcomeBasis,
    acceptance_criteria: acceptanceCriteria,
    evidence_ids: evidenceIds,
    outcome_evidence_ids: outcomeEvidenceIds,
    interaction_events: interactionEvents,
    counts,
    facts: ["Observed task evidence."],
    inferences: [],
    unknowns: outcomeStatus === "unknown" ? ["Outcome is not evidenced."] : []
  };
}

export function instance(
  id,
  task,
  occurredAt,
  evidenceIds,
  {
    pattern = "unmet_expectation",
    signature = "result_does_not_match_requested_output",
    rootCauseCategory = "workflow_gap",
    severity = pattern === "repeated_clarification"
      ? task.counts.repeated_clarification_count
      : pattern === "repeated_execution"
        ? Math.max(1, task.counts.execution_attempt_count - 1)
        : 1
  } = {}
) {
  const value = {
    problem_instance_id: `pi_${id}`,
    task_episode_id: task.task_episode_id,
    conversation_id: task.conversation_id,
    occurred_at: occurredAt,
    pattern,
    issue_signature: signature,
    signature_status: new Set([
      "repeated_clarification:asks_for_already_provided_output_path",
      "unmet_expectation:result_does_not_match_requested_output"
    ]).has(`${pattern}:${signature}`) ? "registered" : "candidate",
    root_cause_category: rootCauseCategory,
    severity,
    summary: signature,
    evidence_ids: evidenceIds,
    facts: ["Observed failure."],
    inferences: [],
    unknowns: []
  };
  return { ...value, fingerprint: problemFingerprint(value) };
}

export function findings(runId, tasks, instances = [], excludedEvidence = []) {
  const groups = new Map();
  for (const item of instances) {
    const key = `${item.pattern}:${item.issue_signature}:${item.root_cause_category}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(item);
  }
  const issueClusters = [...groups.values()].map((items) => {
    const first = items[0];
    const cluster = {
      pattern: first.pattern,
      issue_signature: first.issue_signature,
      signature_status: first.signature_status,
      root_cause_category: first.root_cause_category,
      instance_count: items.length,
      problem_instance_ids: items.map((item) => item.problem_instance_id),
      task_episode_ids: [...new Set(items.map((item) => item.task_episode_id))],
      severity_total: items.reduce((sum, item) => sum + item.severity, 0),
      root_cause: "Required behavior is absent from the workflow.",
      root_cause_confidence: "high",
      evidence_ids: [...new Set(items.flatMap((item) => item.evidence_ids))]
    };
    return { issue_cluster_id: issueClusterId(cluster), ...cluster };
  });
  return {
    schema_version: "1.0.0",
    contract_revision: CONTRACT_REVISION,
    contract_bundle_hash: CONTRACT_BUNDLE_HASH,
    run_id: runId,
    project_id: "test-project",
    task_episodes: tasks,
    excluded_evidence: excludedEvidence,
    problem_instances: instances,
    issue_clusters: issueClusters,
    optimizer_eligible_cluster_ids: issueClusters
      .filter((item) => item.task_episode_ids.length >= 3 &&
        item.root_cause_category !== "environment_issue" &&
        item.signature_status === "registered")
      .map((item) => item.issue_cluster_id)
  };
}

export async function tempSetup({ useLegacyTargets = true, improvementTargets } = {}) {
  const temp = await mkdtemp(path.join(os.tmpdir(), "failure-review-test-"));
  const target = path.join(temp, "SKILL.md");
  const agents = path.join(temp, "AGENTS.md");
  await writeFile(target, "# Test skill\n", "utf8");
  await writeFile(agents, "# Test instructions\n", "utf8");
  const configFile = path.join(temp, "config.json");
  const config = {
    schema_version: "1.0.0",
    runs_dir: path.join(temp, "runs"),
    codex_home: null,
    project_bindings: [{
      project_id: "test-project",
      roots: [],
      conversation_ids: [],
      improvement_target_ids: improvementTargets?.map((item) => item.id)
    }],
    models: {
      collector: { planned_name: "Luna", model: "fake", reasoning_effort: "low" },
      analyst: { planned_name: "Sol", model: "fake", reasoning_effort: "high" },
      optimizer: { planned_name: "Sol", model: "fake", reasoning_effort: "xhigh" }
    },
    privacy: { content_mode: "redact_secrets", retention_days: null, copy_raw_conversations: false }
  };
  if (useLegacyTargets) {
    config.target_skill_allowlist = [target];
    delete config.project_bindings[0].improvement_target_ids;
  }
  if (improvementTargets !== undefined) config.improvement_targets = improvementTargets;
  await writeJson(configFile, config);
  return { temp, target, agents, configFile, runsDir: path.join(temp, "runs") };
}

export const OPTIONS = {
  projectId: "test-project",
  windowStart: "2026-07-24T00:00:00Z",
  windowEnd: "2026-07-25T00:00:00Z",
  timezone: "UTC"
};
