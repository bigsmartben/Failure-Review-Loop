import test from "node:test";
import assert from "node:assert/strict";
import { validateArtifact } from "../src/validation.js";
import { buildMetrics } from "../src/metrics.js";
import { buildTrend } from "../src/trend.js";
import {
  ROOT,
  CONTRACT_BUNDLE_HASH,
  evidenceArtifact,
  evidenceRecord,
  findings,
  instance,
  taskEpisode
} from "./helpers.js";
import { CONTRACT_REVISION } from "../src/contract.js";

const run = {
  run_id: "20260724T140000Z_test-project_a1b2c3",
  parameters: {
    project_id: "test-project",
    target_root: "C:/work/test-project",
    window_start: "2026-07-24T00:00:00Z",
    window_end: "2026-07-25T00:00:00Z",
    timezone: "UTC",
    contract_revision: CONTRACT_REVISION,
    contract_bundle_hash: CONTRACT_BUNDLE_HASH,
    improvement_target_ids: ["test-skill"],
    improvement_targets: [
      { id: "test-skill", type: "skill", path: "C:/skills/test/SKILL.md" }
    ],
    target_set_hash: `sha256:${"0".repeat(64)}`
  }
};

test("resolved task divergence requires user-agent evidence and linked alignment", async () => {
  const records = [
    evidenceRecord("ev_user", "conv-detail", "2026-07-24T01:00:00Z", "目标项目报告", {
      sequence: 0,
      actor: "user"
    }),
    evidenceRecord("ev_agent", "conv-detail", "2026-07-24T01:01:00Z", "E2E 验收报告", {
      sequence: 1,
      actor: "assistant"
    }),
    evidenceRecord("ev_alignment", "conv-detail", "2026-07-24T01:02:00Z", "重新生成目标报告", {
      sequence: 2,
      actor: "user"
    })
  ];
  const task = taskEpisode("detail", "conv-detail", records.map((item) => item.evidence_id), {
    startSequence: 0,
    endSequence: 2,
    outcomeEvidenceIds: ["ev_alignment"],
    counts: {
      turn_count: 3,
      clarification_count: 0,
      repeated_clarification_count: 0,
      execution_attempt_count: 1,
      rework_count: 0
    }
  });
  task.divergences = [{
    divergence_id: "divergence_report_subject",
    summary: "报告对象识别错误",
    user_expectation: "分析目标项目",
    agent_behavior: "分析了 E2E 验收",
    status: "resolved",
    root_cause: "Prompt 未区分目标与运行过程。",
    optimization_target: "prompt",
    optimization_direction: "固定使用运行参数中的目标。",
    acceptance_check: "报告正文只描述目标项目。",
    evidence_ids: ["ev_user", "ev_agent"]
  }];
  task.alignments = [{
    alignment_id: "alignment_report_subject",
    divergence_id: "divergence_report_subject",
    summary: "重新确认分析目标项目。",
    resulting_action: "重新生成报告。",
    evidence_ids: ["ev_alignment"]
  }];
  const artifact = findings(run.run_id, [task]);
  const evidence = evidenceArtifact(run.run_id, records);

  const valid = await validateArtifact("findings", artifact, { run, evidence }, ROOT);
  assert.equal(valid.valid, true, JSON.stringify(valid.errors));

  task.alignments = [];
  const invalid = await validateArtifact("findings", artifact, { run, evidence }, ROOT);
  assert.equal(invalid.valid, false);
  assert(invalid.errors.some((error) =>
    error.code === "RESOLVED_DIVERGENCE_WITHOUT_ALIGNMENT"));
});

test("five repetitions inside one task do not pass the high-frequency gate", async () => {
  const records = Array.from({ length: 6 }, (_, index) =>
    evidenceRecord(`ev_${index}`, "conv-1", `2026-07-24T01:0${index}:00Z`, `turn ${index}`, {
      sequence: index,
      actor: index % 2 === 0 || index === 5 ? "user" : "assistant"
    }));
  const evidenceIds = records.map((record) => record.evidence_id);
  const task = taskEpisode("1", "conv-1", evidenceIds, {
    startSequence: 0,
    endSequence: 5,
    outcomeEvidenceIds: ["ev_5"],
    counts: {
      turn_count: 6,
      clarification_count: 5,
      repeated_clarification_count: 5,
      execution_attempt_count: 1,
      rework_count: 0
    }
  });
  const problem = instance("1", task, records.at(-1).timestamp, evidenceIds, {
    pattern: "repeated_clarification",
    signature: "asks_for_already_provided_output_path",
    severity: 5
  });
  const artifact = findings(run.run_id, [task], [problem]);
  const result = await validateArtifact(
    "findings",
    artifact,
    { run, evidence: evidenceArtifact(run.run_id, records) },
    ROOT
  );
  assert.equal(result.valid, true, JSON.stringify(result.errors));
  assert.deepEqual(artifact.optimizer_eligible_cluster_ids, []);
});

test("the same issue signature across three tasks passes the gate", async () => {
  const records = [0, 1, 2].map((n) =>
    evidenceRecord(`ev_${n}`, `conv-${n}`, `2026-07-24T0${n + 1}:00:00Z`, `rejected ${n}`, { sequence: 0 }));
  const tasks = records.map((record, n) =>
    taskEpisode(String(n), record.conversation_id, [record.evidence_id], { startSequence: 0 }));
  const instances = tasks.map((task, n) =>
    instance(String(n), task, records[n].timestamp, [records[n].evidence_id]));
  const artifact = findings(run.run_id, tasks, instances);
  const result = await validateArtifact(
    "findings",
    artifact,
    { run, evidence: evidenceArtifact(run.run_id, records) },
    ROOT
  );
  assert.equal(result.valid, true, JSON.stringify(result.errors));
  assert.equal(artifact.optimizer_eligible_cluster_ids.length, 1);
});

test("different issue signatures do not merge through a broad root-cause category", async () => {
  const records = [0, 1, 2].map((n) =>
    evidenceRecord(`ev_${n}`, `conv-${n}`, `2026-07-24T0${n + 1}:00:00Z`, `rejected ${n}`, { sequence: 0 }));
  const tasks = records.map((record, n) =>
    taskEpisode(String(n), record.conversation_id, [record.evidence_id], { startSequence: 0 }));
  const signatures = ["owner_missing", "test_not_run", "format_ignored"];
  const instances = tasks.map((task, n) =>
    instance(String(n), task, records[n].timestamp, [records[n].evidence_id], {
      signature: signatures[n],
      rootCauseCategory: "workflow_gap"
    }));
  const artifact = findings(run.run_id, tasks, instances);
  assert.equal(artifact.issue_clusters.length, 3);
  assert.deepEqual(artifact.optimizer_eligible_cluster_ids, []);
  const result = await validateArtifact(
    "findings",
    artifact,
    { run, evidence: evidenceArtifact(run.run_id, records) },
    ROOT
  );
  assert.equal(result.valid, true, JSON.stringify(result.errors));
});

test("one task cannot contribute twice to the same issue signature", async () => {
  const records = [
    evidenceRecord("ev_0", "conv", "2026-07-24T01:00:00Z", "first", { sequence: 0 }),
    evidenceRecord("ev_1", "conv", "2026-07-24T01:01:00Z", "second", { sequence: 1 })
  ];
  const task = taskEpisode("1", "conv", ["ev_0", "ev_1"], {
    startSequence: 0,
    endSequence: 1,
    outcomeEvidenceIds: ["ev_1"],
    counts: {
      turn_count: 2,
      clarification_count: 0,
      repeated_clarification_count: 0,
      execution_attempt_count: 1,
      rework_count: 0
    }
  });
  const first = instance("1", task, records[0].timestamp, ["ev_0"]);
  const second = instance("2", task, records[1].timestamp, ["ev_1"]);
  const artifact = findings(run.run_id, [task], [first, second]);
  const result = await validateArtifact(
    "findings",
    artifact,
    { run, evidence: evidenceArtifact(run.run_id, records) },
    ROOT
  );
  assert.equal(result.valid, false);
  assert(result.errors.some((error) => error.code === "DUPLICATE_PROBLEM_INSTANCE"));
});

test("environment issue clusters never become optimizer eligible", async () => {
  const records = [0, 1, 2].map((n) =>
    evidenceRecord(`ev_${n}`, `conv-${n}`, `2026-07-24T0${n + 1}:00:00Z`, "permission denied", { sequence: 0 }));
  const tasks = records.map((record, n) =>
    taskEpisode(String(n), record.conversation_id, [record.evidence_id], { startSequence: 0 }));
  const instances = tasks.map((task, n) =>
    instance(String(n), task, records[n].timestamp, [records[n].evidence_id], {
      rootCauseCategory: "environment_issue"
    }));
  const artifact = findings(run.run_id, tasks, instances);
  assert.deepEqual(artifact.optimizer_eligible_cluster_ids, []);
  assert.equal((await validateArtifact(
    "findings",
    artifact,
    { run, evidence: evidenceArtifact(run.run_id, records) },
    ROOT
  )).valid, true);
});

test("deterministic metrics exclude unknown outcomes and truncated efficiency samples", async () => {
  const records = [0, 1, 2, 3].map((n) =>
    evidenceRecord(`ev_${n}`, `conv-${n}`, `2026-07-24T0${n + 1}:00:00Z`, `task ${n}`, { sequence: 0 }));
  const tasks = [
    taskEpisode("0", "conv-0", ["ev_0"], {
      startSequence: 0,
      outcomeStatus: "achieved",
      counts: { turn_count: 2, clarification_count: 0, repeated_clarification_count: 0, execution_attempt_count: 1, rework_count: 0 }
    }),
    taskEpisode("1", "conv-1", ["ev_1"], {
      startSequence: 0,
      counts: { turn_count: 4, clarification_count: 1, repeated_clarification_count: 0, execution_attempt_count: 2, rework_count: 1 }
    }),
    taskEpisode("2", "conv-2", ["ev_2"], {
      startSequence: 0,
      outcomeStatus: "unknown",
      counts: { turn_count: 3, clarification_count: 1, repeated_clarification_count: 1, execution_attempt_count: 0, rework_count: 0 }
    }),
    taskEpisode("3", "conv-3", ["ev_3"], {
      startSequence: 0,
      contextStatus: "right_truncated",
      outcomeStatus: "unknown",
      counts: { turn_count: 9, clarification_count: 4, repeated_clarification_count: 2, execution_attempt_count: 3, rework_count: 2 }
    })
  ];
  const artifact = findings(run.run_id, tasks);
  const metrics = buildMetrics({ run, findings: artifact, generatedAt: "2026-07-24T12:00:00Z" });
  const result = await validateArtifact("metrics", metrics, { run, findings: artifact }, ROOT);
  assert.equal(result.valid, true, JSON.stringify(result.errors));
  assert.equal(metrics.attainment_rate, 0.5);
  assert.equal(metrics.outcome_coverage, 0.5);
  assert.equal(metrics.efficiency.turn_count.sample_count, 3);
  assert.deepEqual(metrics.efficiency.turn_count.values, [2, 3, 4]);
});

test("truncated tasks cannot claim a known outcome", async () => {
  const record = evidenceRecord("ev_0", "conv", "2026-07-24T01:00:00Z", "accepted", { sequence: 0 });
  const task = taskEpisode("1", "conv", ["ev_0"], {
    startSequence: 0,
    contextStatus: "right_truncated",
    outcomeStatus: "achieved"
  });
  const artifact = findings(run.run_id, [task]);
  const result = await validateArtifact(
    "findings",
    artifact,
    { run, evidence: evidenceArtifact(run.run_id, [record]) },
    ROOT
  );
  assert.equal(result.valid, false);
  assert(result.errors.some((error) => error.code === "TRUNCATED_TASK_HAS_KNOWN_OUTCOME"));
});

test("every canonical user message must be task-assigned or explicitly excluded", async () => {
  const records = [
    evidenceRecord("ev_0", "conv", "2026-07-24T01:00:00Z", "first goal", { sequence: 0 }),
    evidenceRecord("ev_1", "conv", "2026-07-24T01:01:00Z", "omitted failed goal", { sequence: 1 })
  ];
  const task = taskEpisode("1", "conv", ["ev_0"], {
    startSequence: 0,
    outcomeEvidenceIds: ["ev_0"]
  });
  const artifact = findings(run.run_id, [task]);
  const result = await validateArtifact(
    "findings",
    artifact,
    { run, evidence: evidenceArtifact(run.run_id, records) },
    ROOT
  );
  assert.equal(result.valid, false);
  assert(result.errors.some((error) => error.code === "USER_MESSAGE_COVERAGE_MISMATCH"));
});

test("interaction counts must derive from evidence-linked interaction events", async () => {
  const record = evidenceRecord("ev_0", "conv", "2026-07-24T01:00:00Z", "rejected", { sequence: 0 });
  const task = taskEpisode("1", "conv", ["ev_0"], {
    startSequence: 0,
    outcomeEvidenceIds: ["ev_0"]
  });
  task.counts.execution_attempt_count = 2;
  const artifact = findings(run.run_id, [task]);
  const result = await validateArtifact(
    "findings",
    artifact,
    { run, evidence: evidenceArtifact(run.run_id, [record]) },
    ROOT
  );
  assert.equal(result.valid, false);
  assert(result.errors.some((error) => error.code === "INTERACTION_COUNT_MISMATCH"));
});

test("verified achievement requires all structured acceptance criteria to pass", async () => {
  const records = [
    evidenceRecord("ev_0", "conv", "2026-07-24T01:00:00Z", "build it", { sequence: 0 }),
    evidenceRecord("ev_1", "conv", "2026-07-24T01:01:00Z", "test failed", {
      sequence: 1,
      actor: "tool",
      eventType: "execution_error"
    })
  ];
  const task = taskEpisode("1", "conv", ["ev_0", "ev_1"], {
    startSequence: 0,
    endSequence: 1,
    outcomeStatus: "achieved",
    outcomeBasis: "verified_acceptance_criteria",
    outcomeEvidenceIds: ["ev_1"],
    acceptanceCriteria: [{
      criterion_id: "criterion_tests",
      description: "Tests pass",
      status: "failed",
      verification_evidence_ids: ["ev_1"]
    }],
    counts: {
      turn_count: 1,
      clarification_count: 0,
      repeated_clarification_count: 0,
      execution_attempt_count: 1,
      rework_count: 0
    }
  });
  const artifact = findings(run.run_id, [task]);
  const result = await validateArtifact(
    "findings",
    artifact,
    { run, evidence: evidenceArtifact(run.run_id, records) },
    ROOT
  );
  assert.equal(result.valid, false);
  assert(result.errors.some((error) => error.code === "ACCEPTANCE_CRITERIA_NOT_ALL_PASSED"));
});

test("three tasks with the same unregistered signature remain below the optimizer gate", async () => {
  const records = [0, 1, 2].map((n) =>
    evidenceRecord(`ev_${n}`, `conv-${n}`, `2026-07-24T0${n + 1}:00:00Z`, "rejected", { sequence: 0 }));
  const tasks = records.map((record, n) =>
    taskEpisode(String(n), record.conversation_id, [record.evidence_id], { startSequence: 0 }));
  const instances = tasks.map((task, n) =>
    instance(String(n), task, records[n].timestamp, [records[n].evidence_id], {
      signature: "new_unregistered_failure_shape"
    }));
  const artifact = findings(run.run_id, tasks, instances);
  const result = await validateArtifact(
    "findings",
    artifact,
    { run, evidence: evidenceArtifact(run.run_id, records) },
    ROOT
  );
  assert.equal(result.valid, true, JSON.stringify(result.errors));
  assert.deepEqual(artifact.optimizer_eligible_cluster_ids, []);
});

test("multiple tool calls and results can form one evidence-linked execution attempt", async () => {
  const records = [
    evidenceRecord("ev_0", "conv", "2026-07-24T01:00:00Z", "implement", { sequence: 0 }),
    evidenceRecord("ev_1", "conv", "2026-07-24T01:01:00Z", "read", {
      sequence: 1, actor: "tool", eventType: "tool_call", callId: "read-1"
    }),
    evidenceRecord("ev_2", "conv", "2026-07-24T01:02:00Z", "source", {
      sequence: 2, actor: "tool", eventType: "tool_result", callId: "read-1"
    }),
    evidenceRecord("ev_3", "conv", "2026-07-24T01:03:00Z", "test", {
      sequence: 3, actor: "tool", eventType: "tool_call", callId: "test-1"
    }),
    evidenceRecord("ev_4", "conv", "2026-07-24T01:04:00Z", "passed", {
      sequence: 4, actor: "tool", eventType: "tool_result", callId: "test-1"
    }),
    evidenceRecord("ev_5", "conv", "2026-07-24T01:05:00Z", "done", {
      sequence: 5, actor: "user", eventType: "message"
    })
  ];
  const task = taskEpisode("1", "conv", records.map((record) => record.evidence_id), {
    startSequence: 0,
    endSequence: 5,
    outcomeStatus: "achieved",
    outcomeEvidenceIds: ["ev_5"],
    counts: {
      turn_count: 2,
      clarification_count: 0,
      repeated_clarification_count: 0,
      execution_attempt_count: 1,
      rework_count: 0
    }
  });
  task.interaction_events[0].evidence_ids = ["ev_1", "ev_2", "ev_3", "ev_4", "ev_5"];
  const artifact = findings(run.run_id, [task]);
  const evidence = evidenceArtifact(run.run_id, records);
  const result = await validateArtifact("findings", artifact, { run, evidence }, ROOT);
  assert.equal(result.valid, true, JSON.stringify(result.errors));
  const metrics = buildMetrics({ run, findings: artifact, generatedAt: "2026-07-24T12:00:00Z" });
  assert.equal(metrics.efficiency.execution_attempt_count.total, 1);
});

test("trend validation rejects deltas not derived from supplied baseline metrics", async () => {
  const currentFindings = findings(run.run_id, [
    taskEpisode("1", "conv-1", ["ev_1"], { startSequence: 0, outcomeStatus: "achieved" }),
    taskEpisode("2", "conv-2", ["ev_2"], { startSequence: 0, outcomeStatus: "achieved" }),
    taskEpisode("3", "conv-3", ["ev_3"], { startSequence: 0 })
  ]);
  const current = buildMetrics({ run, findings: currentFindings, generatedAt: "2026-07-24T12:00:00Z" });
  const baseline = structuredClone(current);
  baseline.run_id = "20260723T140000Z_test-project_a1b2c3";
  const trend = buildTrend({
    run,
    metrics: current,
    baselineMetrics: [baseline],
    generatedAt: "2026-07-24T13:00:00Z"
  });
  trend.deltas.turn_count_median = 99;
  const result = await validateArtifact(
    "trend",
    trend,
    { run, metrics: current, baselineMetrics: [baseline] },
    ROOT
  );
  assert.equal(result.valid, false);
  assert(result.errors.some((error) => error.code === "TREND_MISMATCH"));
});

test("proposal below threshold remains structurally invalid", async () => {
  const invalid = await import("../examples/proposal.invalid.below-threshold.json", { with: { type: "json" } });
  const result = await validateArtifact("proposal", invalid.default, {}, ROOT);
  assert.equal(result.valid, false);
});
