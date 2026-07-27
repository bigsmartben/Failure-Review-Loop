import path from "node:path";
import { contentHash, issueClusterId, problemFingerprint } from "./hash.js";
import { metricCore } from "./metrics.js";
import { buildTrend } from "./trend.js";
import { MIN_TREND_TASKS, THRESHOLD } from "./constants.js";
import { validateSchema } from "./schema.js";
import {
  CONTRACT_REVISION,
  contractBundleHash,
  loadIssueSignatureRegistry
} from "./contract.js";

const issue = (code, pathValue, message) => ({ code, path: pathValue, message });
const hasDuplicates = (items) => new Set(items).size !== items.length;
const sorted = (items) => [...items].sort();
const sameItems = (left, right) => JSON.stringify(sorted(left)) === JSON.stringify(sorted(right));
const pathIdentity = (value) => {
  const resolved = path.resolve(value);
  return process.platform === "win32" ? resolved.toLowerCase() : resolved;
};

export async function validateArtifact(kind, data, context, rootDir) {
  const schema = await validateSchema(kind, data, rootDir);
  if (!schema.valid) return schema;
  const errors = [];

  if (context?.run) {
    if (data.run_id !== context.run.run_id) {
      errors.push(issue("RUN_ID_MISMATCH", "/run_id", "Artifact run_id differs from run.json."));
    }
    if (data.project_id && data.project_id !== context.run.parameters.project_id) {
      errors.push(issue("PROJECT_ID_MISMATCH", "/project_id", "Artifact project_id differs from run.json."));
    }
    if (data.contract_revision !== context.run.parameters.contract_revision ||
        data.contract_bundle_hash !== context.run.parameters.contract_bundle_hash) {
      errors.push(issue("CONTRACT_SCOPE_MISMATCH", "/", "Artifact contract identity differs from run.json."));
    }
  }

  if (kind === "run") {
    const expectedContractHash = await contractBundleHash(rootDir);
    validateRun(data, expectedContractHash, errors);
  }
  if (kind === "evidence") validateEvidence(data, context, errors);
  if (kind === "findings") {
    const signatureRegistry = await loadIssueSignatureRegistry(rootDir);
    validateFindings(data, context, signatureRegistry, errors);
  }
  if (kind === "metrics") validateMetrics(data, context, errors);
  if (kind === "trend") validateTrend(data, context, errors);
  if (kind === "proposal") validateProposal(data, context, errors);
  return { valid: errors.length === 0, errors };
}

function validateRun(run, expectedContractHash, errors) {
  if (Date.parse(run.parameters.window_start) >= Date.parse(run.parameters.window_end)) {
    errors.push(issue("INVALID_TIME_WINDOW", "/parameters", "window_start must precede window_end."));
  }
  const targets = run.parameters.improvement_targets;
  const targetIds = targets.map((target) => target.id);
  if (hasDuplicates(targetIds)) {
    errors.push(issue("DUPLICATE_IMPROVEMENT_TARGET_ID", "/parameters/improvement_targets", "Improvement target IDs must be unique."));
  }
  if (hasDuplicates(targets.map((target) => pathIdentity(target.path)))) {
    errors.push(issue("DUPLICATE_IMPROVEMENT_TARGET_PATH", "/parameters/improvement_targets", "Improvement target paths must be unique."));
  }
  if (!sameItems(run.parameters.improvement_target_ids, targetIds)) {
    errors.push(issue("IMPROVEMENT_TARGET_IDS_MISMATCH", "/parameters/improvement_target_ids", "Target IDs must exactly match improvement_targets."));
  }
  if (run.parameters.contract_revision !== CONTRACT_REVISION ||
      run.parameters.contract_bundle_hash !== expectedContractHash) {
    errors.push(issue("CONTRACT_BUNDLE_MISMATCH", "/parameters", "Run contract identity does not match the current contract bundle."));
  }
}

function validateEvidence(data, context, errors) {
  const conversationIds = new Set();
  for (const [index, conversation] of data.conversations.entries()) {
    if (conversationIds.has(conversation.conversation_id)) {
      errors.push(issue("DUPLICATE_CONVERSATION", `/conversations/${index}/conversation_id`, "Conversation metadata must be unique."));
    }
    conversationIds.add(conversation.conversation_id);
  }

  const ids = new Set();
  const recordsById = new Map();
  const sequenceKeys = new Set();
  const toolCalls = new Set();
  for (const [index, record] of data.records.entries()) {
    const base = `/records/${index}`;
    if (ids.has(record.evidence_id)) {
      errors.push(issue("DUPLICATE_EVIDENCE_ID", `${base}/evidence_id`, "evidence_id must be unique."));
    }
    ids.add(record.evidence_id);
    recordsById.set(record.evidence_id, record);
    if (!conversationIds.has(record.conversation_id)) {
      errors.push(issue("MISSING_CONVERSATION_METADATA", `${base}/conversation_id`, "Record conversation metadata is missing."));
    }
    const sequenceKey = `${record.conversation_id}:${record.sequence}`;
    if (sequenceKeys.has(sequenceKey)) {
      errors.push(issue("DUPLICATE_CONVERSATION_SEQUENCE", `${base}/sequence`, "Sequence must be unique inside a conversation."));
    }
    sequenceKeys.add(sequenceKey);
    if (record.project_id !== data.project_id) {
      errors.push(issue("EVIDENCE_PROJECT_MISMATCH", `${base}/project_id`, "Record is outside the artifact project."));
    }
    const ts = Date.parse(record.timestamp);
    if (ts < Date.parse(data.window_start) || ts >= Date.parse(data.window_end)) {
      errors.push(issue("EVIDENCE_OUTSIDE_WINDOW", `${base}/timestamp`, "Evidence timestamp is outside [window_start, window_end)."));
    }
    if (contentHash(record) !== record.content_hash) {
      errors.push(issue("CONTENT_HASH_MISMATCH", `${base}/content_hash`, "content_hash does not match canonical evidence content."));
    }
    if (record.event_type === "message" && record.actor === "tool") {
      errors.push(issue("INVALID_EVENT_ACTOR", `${base}/actor`, "Message events cannot use the tool actor."));
    }
    if (record.event_type !== "message" && record.actor !== "tool") {
      errors.push(issue("INVALID_EVENT_ACTOR", `${base}/actor`, "Tool and artifact events must use the tool actor."));
    }
    if (record.event_type === "tool_call") {
      if (record.call_id) toolCalls.add(`${record.conversation_id}:${record.call_id}`);
    }
  }
  for (const [index, record] of data.records.entries()) {
    if (record.duplicate_of) {
      const target = recordsById.get(record.duplicate_of);
      if (!target) {
        errors.push(issue("MISSING_DUPLICATE_TARGET", `/records/${index}/duplicate_of`, "duplicate_of must reference an evidence record."));
      } else if (target.duplicate_of) {
        errors.push(issue("DUPLICATE_CHAIN", `/records/${index}/duplicate_of`, "Duplicates must point directly to a canonical record."));
      }
    }
    if (["tool_result", "execution_error"].includes(record.event_type) && record.call_id &&
        !toolCalls.has(`${record.conversation_id}:${record.call_id}`)) {
      errors.push(issue("MISSING_TOOL_CALL", `/records/${index}/call_id`, "Tool result call_id must reference a collected tool call."));
    }
  }
  for (const conversationId of conversationIds) {
    if (!data.records.some((record) => record.conversation_id === conversationId)) {
      errors.push(issue("EMPTY_CONVERSATION_METADATA", "/conversations", `Conversation ${conversationId} has no evidence records.`));
    }
  }
  if (context?.run && (Date.parse(data.window_start) !== Date.parse(context.run.parameters.window_start) ||
      Date.parse(data.window_end) !== Date.parse(context.run.parameters.window_end))) {
    errors.push(issue("WINDOW_MISMATCH", "/", "Evidence window differs from locked run window."));
  }
  if (context?.source) validateEvidenceSourceParity(data, context.source, errors);
}

function validateEvidenceSourceParity(data, source, errors) {
  const sourceRecords = source.conversations.flatMap((conversation) => conversation.records);
  const identity = (record) => `${record.content_hash}:${record.collection_status}`;
  if (!sameItems(data.records.map(identity), sourceRecords.map(identity))) {
    errors.push(issue("SOURCE_RECORD_PARITY_MISMATCH", "/records", "Evidence must preserve every source record exactly once."));
  }
  const expectedConversations = source.conversations.map((conversation) => JSON.stringify({
    conversation_id: conversation.conversation_id,
    has_events_before_window: conversation.has_events_before_window,
    has_events_after_window: conversation.has_events_after_window
  }));
  const actualConversations = data.conversations.map((conversation) => JSON.stringify(conversation));
  if (!sameItems(actualConversations, expectedConversations)) {
    errors.push(issue("CONVERSATION_BOUNDARY_MISMATCH", "/conversations", "Conversation boundary metadata differs from source records."));
  }
}

function validateFindings(data, context, signatureRegistry, errors) {
  const evidence = context?.evidence?.records ?? [];
  const evidenceById = new Map(evidence.map((record) => [record.evidence_id, record]));
  const canonicalIds = new Set(evidence.filter((record) => !record.duplicate_of).map((record) => record.evidence_id));
  const conversationMetadata = new Map((context?.evidence?.conversations ?? [])
    .map((conversation) => [conversation.conversation_id, conversation]));
  const tasks = new Map();
  const assignedEvidenceIds = new Set();

  for (const [index, task] of data.task_episodes.entries()) {
    const base = `/task_episodes/${index}`;
    if (tasks.has(task.task_episode_id)) {
      errors.push(issue("DUPLICATE_TASK_EPISODE_ID", `${base}/task_episode_id`, "task_episode_id must be unique."));
    }
    tasks.set(task.task_episode_id, task);
    if (task.start_sequence > task.end_sequence) {
      errors.push(issue("INVALID_TASK_RANGE", base, "start_sequence must not exceed end_sequence."));
    }
    if (task.counts.repeated_clarification_count > task.counts.clarification_count) {
      errors.push(issue("INVALID_CLARIFICATION_COUNT", `${base}/counts`, "Repeated clarification count cannot exceed clarification count."));
    }
    if (task.counts.rework_count > task.counts.execution_attempt_count) {
      errors.push(issue("INVALID_REWORK_COUNT", `${base}/counts`, "Rework count cannot exceed execution attempts."));
    }
    validateOutcome(task, base, errors);
    validateEvidenceReferences(task.evidence_ids, evidenceById, canonicalIds, `${base}/evidence_ids`, errors);
    if (!task.evidence_ids.some((id) => canonicalIds.has(id))) {
      errors.push(issue("ONLY_DUPLICATE_EVIDENCE", `${base}/evidence_ids`, "A task must cite canonical evidence."));
    }
    for (const id of task.evidence_ids) {
      if (assignedEvidenceIds.has(id)) {
        errors.push(issue("EVIDENCE_IN_MULTIPLE_TASKS", `${base}/evidence_ids`, `Evidence ${id} is assigned to multiple tasks.`));
      }
      assignedEvidenceIds.add(id);
      const record = evidenceById.get(id);
      if (!record) continue;
      if (record.conversation_id !== task.conversation_id) {
        errors.push(issue("TASK_CONVERSATION_MISMATCH", `${base}/evidence_ids`, "Task evidence must come from its conversation."));
      }
      if (record.sequence < task.start_sequence || record.sequence > task.end_sequence) {
        errors.push(issue("TASK_SEQUENCE_MISMATCH", `${base}/evidence_ids`, "Task evidence must fall inside its sequence range."));
      }
    }
    const rangeEvidenceIds = evidence
      .filter((record) => record.conversation_id === task.conversation_id &&
        record.sequence >= task.start_sequence && record.sequence <= task.end_sequence)
      .map((record) => record.evidence_id);
    if (!sameItems(task.evidence_ids, rangeEvidenceIds)) {
      errors.push(issue("TASK_EVIDENCE_RANGE_MISMATCH", `${base}/evidence_ids`, "Task evidence must exactly cover its conversation sequence range."));
    }
    const startRecord = evidence.find((record) =>
      record.conversation_id === task.conversation_id &&
      record.sequence === task.start_sequence);
    if (!startRecord || startRecord.event_type !== "message" || startRecord.actor !== "user") {
      errors.push(issue("TASK_MUST_START_WITH_USER_GOAL", `${base}/start_sequence`, "A task must start with a user message."));
    }
    const expectedTurnCount = task.evidence_ids
      .map((id) => evidenceById.get(id))
      .filter((record) => record?.event_type === "message" &&
        ["user", "assistant"].includes(record.actor))
      .length;
    if (task.counts.turn_count !== expectedTurnCount) {
      errors.push(issue("TURN_COUNT_MISMATCH", `${base}/counts/turn_count`, "turn_count must equal user and assistant messages in task evidence."));
    }
    if (!task.outcome_evidence_ids.every((id) => task.evidence_ids.includes(id))) {
      errors.push(issue("OUTCOME_EVIDENCE_OUTSIDE_TASK", `${base}/outcome_evidence_ids`, "Outcome evidence must also be task evidence."));
    }
    validateContextBasis(task, conversationMetadata.get(task.conversation_id), base, errors);
    validateAcceptanceCriteria(task, evidenceById, base, errors);
    validateInteractionEvents(task, evidenceById, canonicalIds, base, errors);
    if (["explicit_user_acceptance", "explicit_user_rejection"].includes(task.outcome_basis) &&
        !task.outcome_evidence_ids.some((id) => {
          const record = evidenceById.get(id);
          return record?.event_type === "message" && record.actor === "user";
        })) {
      errors.push(issue("EXPLICIT_OUTCOME_MISSING_USER_MESSAGE", `${base}/outcome_evidence_ids`, "Explicit user outcomes require user-message evidence."));
    }
  }

  const excludedIds = new Set();
  for (const [index, excluded] of data.excluded_evidence.entries()) {
    const base = `/excluded_evidence/${index}`;
    if (excludedIds.has(excluded.evidence_id)) {
      errors.push(issue("DUPLICATE_EXCLUDED_EVIDENCE", `${base}/evidence_id`, "Excluded evidence IDs must be unique."));
    }
    excludedIds.add(excluded.evidence_id);
    const record = evidenceById.get(excluded.evidence_id);
    if (!record) {
      errors.push(issue("MISSING_EVIDENCE_REFERENCE", `${base}/evidence_id`, `Unknown evidence_id: ${excluded.evidence_id}`));
    } else if (record.duplicate_of || record.event_type !== "message" || record.actor !== "user") {
      errors.push(issue("INVALID_EXCLUDED_EVIDENCE", `${base}/evidence_id`, "Only canonical user messages can be excluded from task coverage."));
    }
    if (assignedEvidenceIds.has(excluded.evidence_id)) {
      errors.push(issue("EXCLUDED_EVIDENCE_IN_TASK", `${base}/evidence_id`, "Evidence cannot be both task-assigned and excluded."));
    }
  }
  const canonicalUserMessageIds = evidence
    .filter((record) => !record.duplicate_of && record.event_type === "message" && record.actor === "user")
    .map((record) => record.evidence_id);
  const coveredUserMessageIds = canonicalUserMessageIds
    .filter((id) => assignedEvidenceIds.has(id) || excludedIds.has(id));
  if (!sameItems(canonicalUserMessageIds, coveredUserMessageIds)) {
    errors.push(issue("USER_MESSAGE_COVERAGE_MISMATCH", "/task_episodes", "Every canonical user message must be assigned to one task or explicitly excluded."));
  }
  const tasksByConversation = new Map();
  for (const task of data.task_episodes) {
    if (!tasksByConversation.has(task.conversation_id)) tasksByConversation.set(task.conversation_id, []);
    tasksByConversation.get(task.conversation_id).push(task);
  }
  for (const conversationTasks of tasksByConversation.values()) {
    const ordered = [...conversationTasks].sort((left, right) => left.start_sequence - right.start_sequence);
    for (let index = 1; index < ordered.length; index += 1) {
      if (ordered[index].start_sequence <= ordered[index - 1].end_sequence) {
        errors.push(issue("OVERLAPPING_TASK_EPISODES", "/task_episodes", "Task sequence ranges cannot overlap inside a conversation."));
      }
    }
  }

  const instances = new Map();
  const fingerprints = new Set();
  for (const [index, instance] of data.problem_instances.entries()) {
    const base = `/problem_instances/${index}`;
    if (instances.has(instance.problem_instance_id)) {
      errors.push(issue("DUPLICATE_PROBLEM_INSTANCE_ID", `${base}/problem_instance_id`, "problem_instance_id must be unique."));
    }
    instances.set(instance.problem_instance_id, instance);
    if (fingerprints.has(instance.fingerprint)) {
      errors.push(issue("DUPLICATE_PROBLEM_INSTANCE", `${base}/fingerprint`, "One task can contribute at most one instance to an issue signature."));
    }
    fingerprints.add(instance.fingerprint);
    if (problemFingerprint(instance) !== instance.fingerprint) {
      errors.push(issue("PROBLEM_FINGERPRINT_MISMATCH", `${base}/fingerprint`, "fingerprint does not match task and issue identity."));
    }
    const registeredSignature = signatureRegistry.has(`${instance.pattern}:${instance.issue_signature}`);
    const expectedSignatureStatus = registeredSignature ? "registered" : "candidate";
    if (instance.signature_status !== expectedSignatureStatus) {
      errors.push(issue("SIGNATURE_STATUS_MISMATCH", `${base}/signature_status`, "Signature status must derive from the issue signature registry."));
    }
    const task = tasks.get(instance.task_episode_id);
    if (!task) {
      errors.push(issue("MISSING_TASK_REFERENCE", `${base}/task_episode_id`, "Problem instance references an unknown task."));
    } else {
      if (task.conversation_id !== instance.conversation_id) {
        errors.push(issue("INSTANCE_CONVERSATION_MISMATCH", `${base}/conversation_id`, "Problem instance conversation differs from its task."));
      }
      if (!instance.evidence_ids.every((id) => task.evidence_ids.includes(id))) {
        errors.push(issue("INSTANCE_EVIDENCE_OUTSIDE_TASK", `${base}/evidence_ids`, "Problem evidence must also be task evidence."));
      }
      validateSeverity(instance, task, base, errors);
    }
    validateEvidenceReferences(instance.evidence_ids, evidenceById, canonicalIds, `${base}/evidence_ids`, errors);
    if (!instance.evidence_ids.some((id) => canonicalIds.has(id))) {
      errors.push(issue("ONLY_DUPLICATE_EVIDENCE", `${base}/evidence_ids`, "An instance must cite canonical evidence."));
    }
  }

  const clusters = new Map();
  const includedInstances = new Set();
  for (const [index, cluster] of data.issue_clusters.entries()) {
    const base = `/issue_clusters/${index}`;
    if (clusters.has(cluster.issue_cluster_id)) {
      errors.push(issue("DUPLICATE_ISSUE_CLUSTER_ID", `${base}/issue_cluster_id`, "issue_cluster_id must be unique."));
    }
    clusters.set(cluster.issue_cluster_id, cluster);
    if (issueClusterId(cluster) !== cluster.issue_cluster_id) {
      errors.push(issue("ISSUE_CLUSTER_ID_MISMATCH", `${base}/issue_cluster_id`, "issue_cluster_id does not match the cluster identity."));
    }
    const matching = data.problem_instances.filter((instance) =>
      instance.pattern === cluster.pattern &&
      instance.issue_signature === cluster.issue_signature &&
      instance.root_cause_category === cluster.root_cause_category);
    const registeredSignature = signatureRegistry.has(`${cluster.pattern}:${cluster.issue_signature}`);
    const expectedSignatureStatus = registeredSignature ? "registered" : "candidate";
    if (cluster.signature_status !== expectedSignatureStatus ||
        matching.some((instance) => instance.signature_status !== cluster.signature_status)) {
      errors.push(issue("CLUSTER_SIGNATURE_STATUS_MISMATCH", `${base}/signature_status`, "Cluster signature status must match the registry and all instances."));
    }
    const matchingIds = matching.map((instance) => instance.problem_instance_id);
    const matchingTaskIds = [...new Set(matching.map((instance) => instance.task_episode_id))];
    const matchingEvidenceIds = [...new Set(matching.flatMap((instance) => instance.evidence_ids))];
    if (!sameItems(cluster.problem_instance_ids, matchingIds) ||
        !sameItems(cluster.task_episode_ids, matchingTaskIds) ||
        cluster.instance_count !== matching.length ||
        cluster.severity_total !== matching.reduce((sum, instance) => sum + instance.severity, 0) ||
        !sameItems(cluster.evidence_ids, matchingEvidenceIds)) {
      errors.push(issue("ISSUE_CLUSTER_MISMATCH", base, "Cluster counts and references must exactly match its problem instances."));
    }
    for (const id of cluster.problem_instance_ids) {
      if (includedInstances.has(id)) {
        errors.push(issue("INSTANCE_IN_MULTIPLE_CLUSTERS", `${base}/problem_instance_ids`, "Problem instance can belong to only one cluster."));
      }
      includedInstances.add(id);
    }
  }
  for (const instance of data.problem_instances) {
    if (!includedInstances.has(instance.problem_instance_id)) {
      errors.push(issue("MISSING_ISSUE_CLUSTER", "/issue_clusters", `Missing cluster for ${instance.problem_instance_id}.`));
    }
  }

  const expectedEligible = [...clusters.values()]
    .filter((cluster) => cluster.task_episode_ids.length >= THRESHOLD &&
      cluster.root_cause_category !== "environment_issue" &&
      cluster.signature_status === "registered")
    .map((cluster) => cluster.issue_cluster_id);
  if (!sameItems(data.optimizer_eligible_cluster_ids, expectedEligible)) {
    errors.push(issue("ELIGIBILITY_MISMATCH", "/optimizer_eligible_cluster_ids", "Eligible clusters must derive from unique task count and root cause category."));
  }
}

function validateContextBasis(task, conversation, base, errors) {
  const expectedBasis = {
    complete: "fully_observed",
    left_truncated: "left_boundary_continuation",
    right_truncated: "right_boundary_continuation",
    both_truncated: "both_boundary_continuation"
  }[task.context_status];
  if (task.context_basis !== expectedBasis) {
    errors.push(issue("CONTEXT_BASIS_MISMATCH", `${base}/context_basis`, "context_basis must derive from context_status."));
  }
  if (task.context_status === "complete" && task.boundary_evidence_ids.length !== 0) {
    errors.push(issue("COMPLETE_TASK_HAS_BOUNDARY_EVIDENCE", `${base}/boundary_evidence_ids`, "Complete tasks cannot claim boundary evidence."));
  }
  if (task.context_status !== "complete" && task.boundary_evidence_ids.length === 0) {
    errors.push(issue("TRUNCATED_TASK_MISSING_BOUNDARY_EVIDENCE", `${base}/boundary_evidence_ids`, "Truncated tasks require boundary evidence."));
  }
  if (!task.boundary_evidence_ids.every((id) => task.evidence_ids.includes(id))) {
    errors.push(issue("BOUNDARY_EVIDENCE_OUTSIDE_TASK", `${base}/boundary_evidence_ids`, "Boundary evidence must also be task evidence."));
  }
  const needsBefore = ["left_truncated", "both_truncated"].includes(task.context_status);
  const needsAfter = ["right_truncated", "both_truncated"].includes(task.context_status);
  if (needsBefore && !conversation?.has_events_before_window) {
    errors.push(issue("MISSING_LEFT_WINDOW_CONTEXT", `${base}/context_status`, "Left-truncated tasks require events before the window."));
  }
  if (needsAfter && !conversation?.has_events_after_window) {
    errors.push(issue("MISSING_RIGHT_WINDOW_CONTEXT", `${base}/context_status`, "Right-truncated tasks require events after the window."));
  }
}

function validateAcceptanceCriteria(task, evidenceById, base, errors) {
  const criterionIds = task.acceptance_criteria.map((criterion) => criterion.criterion_id);
  if (hasDuplicates(criterionIds)) {
    errors.push(issue("DUPLICATE_ACCEPTANCE_CRITERION", `${base}/acceptance_criteria`, "Acceptance criterion IDs must be unique inside a task."));
  }
  for (const [index, criterion] of task.acceptance_criteria.entries()) {
    const criterionBase = `${base}/acceptance_criteria/${index}`;
    if (!criterion.verification_evidence_ids.every((id) => task.evidence_ids.includes(id))) {
      errors.push(issue("CRITERION_EVIDENCE_OUTSIDE_TASK", `${criterionBase}/verification_evidence_ids`, "Criterion evidence must also be task evidence."));
    }
    if (criterion.status !== "unknown" && criterion.verification_evidence_ids.length === 0) {
      errors.push(issue("DECIDED_CRITERION_MISSING_EVIDENCE", `${criterionBase}/verification_evidence_ids`, "Passed or failed criteria require verification evidence."));
    }
    validateEvidenceReferences(
      criterion.verification_evidence_ids,
      evidenceById,
      new Set(),
      `${criterionBase}/verification_evidence_ids`,
      errors
    );
  }
  const decidedEvidenceIds = [...new Set(task.acceptance_criteria
    .filter((criterion) => criterion.status !== "unknown")
    .flatMap((criterion) => criterion.verification_evidence_ids))];
  if (task.outcome_basis === "verified_acceptance_criteria") {
    if (task.acceptance_criteria.length === 0 ||
        task.acceptance_criteria.some((criterion) => criterion.status !== "passed")) {
      errors.push(issue("ACCEPTANCE_CRITERIA_NOT_ALL_PASSED", `${base}/acceptance_criteria`, "Verified achievement requires at least one criterion and all criteria passed."));
    }
    if (!sameItems(task.outcome_evidence_ids, decidedEvidenceIds)) {
      errors.push(issue("OUTCOME_CRITERIA_EVIDENCE_MISMATCH", `${base}/outcome_evidence_ids`, "Verified outcome evidence must equal decided criterion evidence."));
    }
  }
  if (task.outcome_basis === "verified_expectation_mismatch") {
    if (!task.acceptance_criteria.some((criterion) => criterion.status === "failed")) {
      errors.push(issue("EXPECTATION_MISMATCH_WITHOUT_FAILED_CRITERION", `${base}/acceptance_criteria`, "Verified mismatch requires at least one failed criterion."));
    }
    if (!sameItems(task.outcome_evidence_ids, decidedEvidenceIds)) {
      errors.push(issue("OUTCOME_CRITERIA_EVIDENCE_MISMATCH", `${base}/outcome_evidence_ids`, "Verified outcome evidence must equal decided criterion evidence."));
    }
  }
  if (task.outcome_basis === "insufficient_evidence" &&
      task.acceptance_criteria.some((criterion) => criterion.status === "failed")) {
    errors.push(issue("UNKNOWN_OUTCOME_HAS_FAILED_CRITERION", `${base}/acceptance_criteria`, "A failed criterion proves a known expectation mismatch."));
  }
}

function validateInteractionEvents(task, evidenceById, canonicalIds, base, errors) {
  const interactionIds = task.interaction_events.map((event) => event.interaction_id);
  if (hasDuplicates(interactionIds)) {
    errors.push(issue("DUPLICATE_INTERACTION_ID", `${base}/interaction_events`, "Interaction IDs must be unique inside a task."));
  }
  for (const [index, event] of task.interaction_events.entries()) {
    const eventBase = `${base}/interaction_events/${index}`;
    if (!event.evidence_ids.every((id) => task.evidence_ids.includes(id))) {
      errors.push(issue("INTERACTION_EVIDENCE_OUTSIDE_TASK", `${eventBase}/evidence_ids`, "Interaction evidence must also be task evidence."));
    }
    validateEvidenceReferences(event.evidence_ids, evidenceById, canonicalIds, `${eventBase}/evidence_ids`, errors);
    if (!event.evidence_ids.some((id) => canonicalIds.has(id))) {
      errors.push(issue("ONLY_DUPLICATE_EVIDENCE", `${eventBase}/evidence_ids`, "An interaction must cite canonical evidence."));
    }
  }
  const clarificationEvents = task.interaction_events
    .filter((event) => event.kind === "clarification");
  const executionEvents = task.interaction_events
    .filter((event) => event.kind === "execution_attempt");
  const expectedCounts = {
    clarification_count: clarificationEvents.length,
    repeated_clarification_count: clarificationEvents.filter((event) => event.repeated).length,
    execution_attempt_count: executionEvents.length,
    rework_count: executionEvents.filter((event) => event.rework).length
  };
  for (const [key, expected] of Object.entries(expectedCounts)) {
    if (task.counts[key] !== expected) {
      errors.push(issue("INTERACTION_COUNT_MISMATCH", `${base}/counts/${key}`, `${key} must derive from interaction_events.`));
    }
  }
}

function validateOutcome(task, base, errors) {
  const basisByStatus = {
    achieved: new Set(["explicit_user_acceptance", "verified_acceptance_criteria"]),
    not_achieved: new Set(["explicit_user_rejection", "verified_expectation_mismatch"]),
    unknown: new Set(["insufficient_evidence"])
  };
  if (!basisByStatus[task.outcome_status].has(task.outcome_basis)) {
    errors.push(issue("OUTCOME_BASIS_MISMATCH", `${base}/outcome_basis`, "Outcome basis does not support outcome status."));
  }
  if (task.context_status !== "complete" && task.outcome_status !== "unknown") {
    errors.push(issue("TRUNCATED_TASK_HAS_KNOWN_OUTCOME", `${base}/outcome_status`, "Truncated tasks must use unknown outcome."));
  }
  if (task.outcome_status === "unknown" && task.outcome_evidence_ids.length !== 0) {
    errors.push(issue("UNKNOWN_OUTCOME_HAS_EVIDENCE", `${base}/outcome_evidence_ids`, "Unknown outcomes cannot claim outcome evidence."));
  }
  if (task.outcome_status !== "unknown" && task.outcome_evidence_ids.length === 0) {
    errors.push(issue("MISSING_OUTCOME_EVIDENCE", `${base}/outcome_evidence_ids`, "Known outcomes require outcome evidence."));
  }
}

function validateSeverity(instance, task, base, errors) {
  let expected;
  if (instance.pattern === "repeated_clarification") {
    expected = task.counts.repeated_clarification_count;
  } else if (instance.pattern === "repeated_execution") {
    expected = Math.max(0, task.counts.execution_attempt_count - 1);
  } else {
    expected = task.outcome_status === "not_achieved" ? 1 : 0;
  }
  if (expected < 1 || instance.severity !== expected) {
    errors.push(issue("PATTERN_SEVERITY_MISMATCH", `${base}/severity`, "Severity must match the task-level pattern count."));
  }
}

function validateEvidenceReferences(ids, evidenceById, canonicalIds, pathValue, errors) {
  if (hasDuplicates(ids)) {
    errors.push(issue("DUPLICATE_REFERENCE", pathValue, "Evidence references must be unique."));
  }
  for (const id of ids) {
    if (!evidenceById.has(id)) {
      errors.push(issue("MISSING_EVIDENCE_REFERENCE", pathValue, `Unknown evidence_id: ${id}`));
    }
  }
  void canonicalIds;
}

function validateMetrics(data, context, errors) {
  if (!context?.run || !context?.findings) return;
  const expected = metricCore(context.findings, {
    improvement_target_ids: context.run.parameters.improvement_target_ids,
    target_set_hash: context.run.parameters.target_set_hash,
    contract_revision: context.run.parameters.contract_revision,
    contract_bundle_hash: context.run.parameters.contract_bundle_hash
  });
  for (const key of Object.keys(expected)) {
    if (JSON.stringify(data[key]) !== JSON.stringify(expected[key])) {
      errors.push(issue("METRICS_MISMATCH", `/${key}`, `${key} does not match deterministic findings aggregation.`));
    }
  }
}

function validateTrend(data, context, errors) {
  if (!context?.run || !context?.metrics || !context?.baselineMetrics) {
    errors.push(issue("TREND_BASELINE_CONTEXT_REQUIRED", "/", "Trend validation requires current run, metrics, and validated baseline metrics."));
    return;
  }
  if (!sameItems(data.target_scope.improvement_target_ids, context.run.parameters.improvement_target_ids) ||
      data.target_scope.target_set_hash !== context.run.parameters.target_set_hash) {
    errors.push(issue("TREND_SCOPE_MISMATCH", "/target_scope", "Trend target scope differs from the locked run."));
  }
  if (data.current_valid_task_count !== context.metrics.task_counts.complete) {
    errors.push(issue("TREND_CURRENT_COUNT_MISMATCH", "/current_valid_task_count", "Trend current task count differs from metrics."));
  }
  const available = data.current_valid_task_count >= MIN_TREND_TASKS &&
    data.baseline_valid_task_count >= MIN_TREND_TASKS;
  if ((data.status === "available") !== available) {
    errors.push(issue("TREND_STATUS_MISMATCH", "/status", "Trend status must derive from current and baseline sample sizes."));
  }
  if (!available && Object.values(data.deltas).some((value) => value !== null)) {
    errors.push(issue("INSUFFICIENT_TREND_HAS_DELTAS", "/deltas", "Insufficient trends must not report deltas."));
  }
  const expected = buildTrend({
    run: context.run,
    metrics: context.metrics,
    baselineMetrics: context.baselineMetrics,
    generatedAt: data.generated_at
  });
  if (JSON.stringify(data) !== JSON.stringify(expected)) {
    errors.push(issue("TREND_MISMATCH", "/", "Trend must equal deterministic aggregation of the validated baseline metrics."));
  }
}

function validateProposal(data, context, errors) {
  const findings = context?.findings;
  const evidenceIds = new Set((context?.evidence?.records ?? []).map((record) => record.evidence_id));
  const eligibleIds = findings?.optimizer_eligible_cluster_ids ?? [];
  const clusters = new Map((findings?.issue_clusters ?? []).map((cluster) => [cluster.issue_cluster_id, cluster]));
  const lockedTargets = context?.run?.parameters?.improvement_targets ?? [];
  const lockedTargetIds = context?.run?.parameters?.improvement_target_ids ?? [];
  const targets = new Map(lockedTargets.map((target) => [target.id, target]));
  const proposalIds = new Set();
  const proposalsByCluster = new Map();

  if (context?.run && !sameItems(data.improvement_target_ids, lockedTargetIds)) {
    errors.push(issue("IMPROVEMENT_TARGET_IDS_MISMATCH", "/improvement_target_ids", "Proposal target IDs differ from the locked run targets."));
  }
  for (const [index, proposal] of data.proposals.entries()) {
    const base = `/proposals/${index}`;
    if (proposalIds.has(proposal.proposal_id)) {
      errors.push(issue("DUPLICATE_PROPOSAL_ID", `${base}/proposal_id`, "proposal_id must be unique."));
    }
    proposalIds.add(proposal.proposal_id);
    if (!proposalsByCluster.has(proposal.issue_cluster_id)) proposalsByCluster.set(proposal.issue_cluster_id, []);
    proposalsByCluster.get(proposal.issue_cluster_id).push(proposal);
    if (!eligibleIds.includes(proposal.issue_cluster_id)) {
      errors.push(issue("CLUSTER_NOT_ELIGIBLE", `${base}/issue_cluster_id`, "Proposal cluster did not pass the readiness gate."));
    }
    const cluster = clusters.get(proposal.issue_cluster_id);
    if (cluster && (!sameItems(proposal.problem_instance_ids, cluster.problem_instance_ids) ||
        proposal.instance_count !== cluster.instance_count ||
        !proposal.evidence_ids.every((id) => cluster.evidence_ids.includes(id)) ||
        proposal.root_cause !== cluster.root_cause)) {
      errors.push(issue("PROPOSAL_CLUSTER_MISMATCH", base, "Proposal must match its complete eligible cluster and root cause."));
    }
    const target = targets.get(proposal.target_id);
    if (!target) {
      errors.push(issue("IMPROVEMENT_TARGET_NOT_ALLOWED", `${base}/target_id`, "Proposal target_id is not allowed."));
    } else if (!path.isAbsolute(proposal.target_file) ||
        pathIdentity(proposal.target_file) !== pathIdentity(target.path)) {
      errors.push(issue("TARGET_FILE_MISMATCH", `${base}/target_file`, "Proposal target_file must exactly match the locked target path."));
    }
    for (const id of proposal.evidence_ids) {
      if (!evidenceIds.has(id)) {
        errors.push(issue("MISSING_EVIDENCE_REFERENCE", `${base}/evidence_ids`, `Unknown evidence_id: ${id}`));
      }
    }
    for (const effect of proposal.expected_metric_effects) {
      const expectedDirection = effect.metric === "attainment_rate" ? "increase" : "decrease";
      if (effect.direction !== expectedDirection) {
        errors.push(issue("METRIC_EFFECT_DIRECTION_MISMATCH", `${base}/expected_metric_effects`, `${effect.metric} must ${expectedDirection}.`));
      }
    }
    if (!proposal.regression_tests.some((test) => test.kind === "adjacent_case")) {
      errors.push(issue("MISSING_ADJACENT_TEST", `${base}/regression_tests`, "At least one adjacent-case test is required."));
    }
    if (!proposal.regression_tests.some((test) => test.kind === "original_failure")) {
      errors.push(issue("MISSING_ORIGINAL_FAILURE_TEST", `${base}/regression_tests`, "At least one original-failure test is required."));
    }
  }

  const dispositionClusters = data.dispositions.map((item) => item.issue_cluster_id);
  if (hasDuplicates(dispositionClusters) || !sameItems(dispositionClusters, eligibleIds)) {
    errors.push(issue("DISPOSITION_COVERAGE_MISMATCH", "/dispositions", "Every eligible cluster requires exactly one disposition."));
  }
  const referencedProposalIds = [];
  for (const [index, disposition] of data.dispositions.entries()) {
    const clusterProposals = proposalsByCluster.get(disposition.issue_cluster_id) ?? [];
    const actualIds = clusterProposals.map((proposal) => proposal.proposal_id);
    if (!sameItems(disposition.proposal_ids, actualIds)) {
      errors.push(issue("DISPOSITION_PROPOSAL_MISMATCH", `/dispositions/${index}/proposal_ids`, "Disposition proposal IDs must exactly match cluster proposals."));
    }
    if (disposition.status === "proposed" && actualIds.length === 0) {
      errors.push(issue("EMPTY_PROPOSED_DISPOSITION", `/dispositions/${index}`, "Proposed disposition requires a proposal."));
    }
    if (disposition.status === "no_supported_target" && actualIds.length !== 0) {
      errors.push(issue("UNSUPPORTED_DISPOSITION_HAS_PROPOSAL", `/dispositions/${index}`, "No-supported-target disposition cannot contain proposals."));
    }
    referencedProposalIds.push(...disposition.proposal_ids);
  }
  if (!sameItems(referencedProposalIds, [...proposalIds])) {
    errors.push(issue("UNREFERENCED_PROPOSAL", "/dispositions", "Every proposal must be referenced by one disposition."));
  }
}
