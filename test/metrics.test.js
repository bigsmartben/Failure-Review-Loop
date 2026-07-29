import test from "node:test";
import assert from "node:assert/strict";
import { mkdir, mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { buildMetrics } from "../src/metrics.js";
import { buildTrend, collectBaselineMetrics } from "../src/trend.js";
import { writeJson } from "../src/io.js";
import {
  CONTRACT_BUNDLE_HASH,
  evidenceArtifact,
  evidenceRecord,
  findings,
  OPTIONS,
  ROOT,
  taskEpisode
} from "./helpers.js";
import { CONTRACT_REVISION } from "../src/contract.js";

function run(id = "20260724T140000Z_test-project_a1b2c3", hash = "0") {
  return {
    run_id: id,
    parameters: {
      project_id: "test-project",
      target_root: "C:/work/test-project",
      contract_revision: CONTRACT_REVISION,
      contract_bundle_hash: CONTRACT_BUNDLE_HASH,
      improvement_target_ids: ["target"],
      target_set_hash: `sha256:${hash.repeat(64)}`
    }
  };
}

function task(id, outcomeStatus, counts = {}) {
  return taskEpisode(id, `conv-${id}`, [`ev_${id}`], {
    startSequence: 0,
    outcomeStatus,
    counts: {
      turn_count: 1,
      clarification_count: 0,
      repeated_clarification_count: 0,
      execution_attempt_count: 1,
      rework_count: 0,
      ...counts
    }
  });
}

function metricsFor(runValue, tasks) {
  return buildMetrics({
    run: runValue,
    findings: findings(runValue.run_id, tasks),
    generatedAt: "2026-07-24T12:00:00Z"
  });
}

test("trend is insufficient when either period has fewer than three complete tasks", () => {
  const currentRun = run();
  const current = metricsFor(currentRun, [task("1", "achieved"), task("2", "not_achieved")]);
  const baselineRun = run("20260723T140000Z_test-project_a1b2c3");
  const baseline = metricsFor(baselineRun, [
    task("3", "achieved"),
    task("4", "achieved"),
    task("5", "not_achieved")
  ]);
  const trend = buildTrend({
    run: currentRun,
    metrics: current,
    baselineMetrics: [baseline],
    generatedAt: "2026-07-24T12:00:00Z"
  });
  assert.equal(trend.status, "insufficient_data");
  assert(Object.values(trend.deltas).every((value) => value === null));
});

test("trend aggregates historical samples and marks target content changes", () => {
  const currentRun = run();
  const current = metricsFor(currentRun, [
    task("1", "achieved", { turn_count: 2 }),
    task("2", "achieved", { turn_count: 2 }),
    task("3", "not_achieved", { turn_count: 4 })
  ]);
  const oldRun = run("20260723T140000Z_test-project_a1b2c3", "1");
  const baseline = metricsFor(oldRun, [
    task("4", "achieved", { turn_count: 6 }),
    task("5", "not_achieved", { turn_count: 6 }),
    task("6", "not_achieved", { turn_count: 8 })
  ]);
  const trend = buildTrend({
    run: currentRun,
    metrics: current,
    baselineMetrics: [baseline],
    generatedAt: "2026-07-24T12:00:00Z"
  });
  assert.equal(trend.status, "available");
  assert.equal(trend.target_change_detected, true);
  assert.equal(trend.deltas.attainment_rate, 0.333334);
  assert.equal(trend.deltas.turn_count_median, -4);
});

test("metrics use task-level execution attempts rather than raw tool-call count", () => {
  const currentRun = run();
  const metrics = metricsFor(currentRun, [
    task("1", "achieved", { execution_attempt_count: 1 })
  ]);
  assert.equal(metrics.efficiency.execution_attempt_count.total, 1);
  assert.deepEqual(metrics.efficiency.execution_attempt_count.values, [1]);
});

test("baseline discovery keeps only the seven most recent comparable metrics", async () => {
  const runsDir = await mkdtemp(path.join(os.tmpdir(), "failure-trend-test-"));
  for (let index = 0; index < 9; index += 1) {
    const runId = `202607${String(index + 1).padStart(2, "0")}T120000Z_test-project_a1b2c3`;
    const runValue = {
      schema_version: "1.0.0",
      run_id: runId,
      attempt: 1,
      status: "COMPLETED_WITH_METRICS",
      parameters: {
        ...run(runId).parameters,
        window_start: OPTIONS.windowStart,
        window_end: OPTIONS.windowEnd,
        timezone: OPTIONS.timezone,
        improvement_targets: [{ id: "target", type: "skill", path: "C:/target/SKILL.md" }]
      },
      created_at: "2026-07-24T10:00:00Z",
      updated_at: "2026-07-24T12:00:00Z",
      stages: Object.fromEntries(["collector", "analyst", "metrics", "trend", "optimizer"].map((stage) => [
        stage,
        { status: stage === "optimizer" ? "skipped" : "succeeded", started_at: null, completed_at: null, artifact: null }
      ])),
      failure: null
    };
    const taskIds = [`${index}-1`, `${index}-2`, `${index}-3`];
    const records = taskIds.map((id, taskIndex) => evidenceRecord(
      `ev_${id}`,
      `conv-${id}`,
      `2026-07-24T0${taskIndex + 1}:00:00Z`,
      taskIndex === 2 ? "rejected" : "accepted",
      { sequence: 0 }
    ));
    const tasks = [
      task(taskIds[0], "achieved"),
      task(taskIds[1], "achieved"),
      task(taskIds[2], "not_achieved")
    ];
    const findingsValue = findings(runId, tasks);
    const evidenceValue = evidenceArtifact(runId, records);
    const value = metricsFor(runValue, tasks);
    const source = {
      schema_version: "1.0.0",
      project_id: "test-project",
      window_start: OPTIONS.windowStart,
      window_end: OPTIONS.windowEnd,
      conversations: records.map((record) => ({
        conversation_id: record.conversation_id,
        project_id: "test-project",
        match_method: "target_cwd",
        has_events_before_window: false,
        has_events_after_window: false,
        records: [{
          conversation_id: record.conversation_id,
          timestamp: record.timestamp,
          actor: record.actor,
          sequence: record.sequence,
          event_type: record.event_type,
          call_id: record.call_id,
          source_location: record.source_location,
          content_or_reference: record.content_or_reference,
          collection_status: record.collection_status,
          content_hash: record.content_hash
        }]
      }))
    };
    await mkdir(path.join(runsDir, runId));
    await writeJson(path.join(runsDir, runId, "run.json"), runValue);
    await writeJson(path.join(runsDir, runId, "source-records.json"), source);
    await writeJson(path.join(runsDir, runId, "evidence.json"), evidenceValue);
    await writeJson(path.join(runsDir, runId, "findings.json"), findingsValue);
    await writeJson(path.join(runsDir, runId, "metrics.json"), value);
  }
  const tamperedRunId = "20260710T120000Z_test-project_a1b2c3";
  await mkdir(path.join(runsDir, tamperedRunId));
  await writeJson(
    path.join(runsDir, tamperedRunId, "metrics.json"),
    metricsFor(run(tamperedRunId), [
      task("tampered-1", "achieved"),
      task("tampered-2", "achieved"),
      task("tampered-3", "achieved")
    ])
  );
  const baseline = await collectBaselineMetrics({
    runsDir,
    currentRunId: "current",
    projectId: "test-project",
    improvementTargetIds: ["target"],
    contractRevision: CONTRACT_REVISION,
    contractBundleHash: CONTRACT_BUNDLE_HASH,
    before: "2026-07-25T00:00:00Z",
    rootDir: ROOT
  });
  assert.equal(baseline.length, 7);
  assert.equal(baseline[0].run_id, "20260709T120000Z_test-project_a1b2c3");
  assert.equal(baseline.at(-1).run_id, "20260703T120000Z_test-project_a1b2c3");
});
