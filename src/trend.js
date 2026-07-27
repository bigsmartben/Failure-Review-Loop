import { readdir } from "node:fs/promises";
import path from "node:path";
import { readJson } from "./io.js";
import { validateSchema } from "./schema.js";
import { median, PATTERNS } from "./metrics.js";
import { MIN_TREND_TASKS } from "./constants.js";

const BASELINE_RUN_LIMIT = 7;

function rounded(value) {
  return Math.round(value * 1_000_000) / 1_000_000;
}

function sameIds(left, right) {
  return JSON.stringify([...left].sort()) === JSON.stringify([...right].sort());
}

export async function collectBaselineMetrics({
  runsDir,
  currentRunId,
  projectId,
  improvementTargetIds,
  contractRevision,
  contractBundleHash,
  before,
  rootDir
}) {
  const entries = await readdir(runsDir, { withFileTypes: true });
  const candidates = entries
    .filter((entry) => entry.isDirectory() && entry.name !== currentRunId && !entry.name.startsWith("."))
    .map((entry) => entry.name)
    .sort()
    .reverse();
  const baseline = [];
  for (const runId of candidates) {
    try {
      const run = await readJson(path.join(runsDir, runId, "run.json"));
      const source = await readJson(path.join(runsDir, runId, "source-records.json"));
      const evidence = await readJson(path.join(runsDir, runId, "evidence.json"));
      const findings = await readJson(path.join(runsDir, runId, "findings.json"));
      const metrics = await readJson(path.join(runsDir, runId, "metrics.json"));
      const schema = await validateSchema("metrics", metrics, rootDir);
      if (!schema.valid || metrics.project_id !== projectId ||
          !run.status.startsWith("COMPLETED_")) continue;
      if (!sameIds(metrics.target_scope.improvement_target_ids, improvementTargetIds)) continue;
      if (metrics.target_scope.contract_revision !== contractRevision ||
          metrics.target_scope.contract_bundle_hash !== contractBundleHash) continue;
      if (before && Date.parse(metrics.generated_at) >= Date.parse(before)) continue;
      const { validateArtifact } = await import("./validation.js");
      const validations = [
        await validateArtifact("run", run, {}, rootDir),
        await validateArtifact("evidence", evidence, { run, source }, rootDir),
        await validateArtifact("findings", findings, { run, evidence }, rootDir),
        await validateArtifact("metrics", metrics, { run, findings }, rootDir)
      ];
      if (validations.some((result) => !result.valid)) continue;
      baseline.push(metrics);
    } catch (error) {
      if (error instanceof SyntaxError) continue;
      if (!["ENOENT", "ENOTDIR"].includes(error.code)) throw error;
    }
  }
  return baseline
    .sort((left, right) =>
      Date.parse(right.generated_at) - Date.parse(left.generated_at) ||
      right.run_id.localeCompare(left.run_id))
    .slice(0, BASELINE_RUN_LIMIT);
}

function aggregateBaseline(metrics) {
  const taskCounts = metrics.reduce((result, item) => {
    for (const key of Object.keys(result)) result[key] += item.task_counts[key];
    return result;
  }, {
    total: 0,
    complete: 0,
    truncated: 0,
    achieved: 0,
    not_achieved: 0,
    unknown: 0,
    known_outcome: 0
  });
  const efficiencyValues = {};
  for (const key of Object.keys(metrics[0]?.efficiency ?? {})) {
    efficiencyValues[key] = metrics.flatMap((item) => item.efficiency[key].values);
  }
  const patternTaskCounts = Object.fromEntries(PATTERNS.map((pattern) => [
    pattern,
    metrics.reduce((sum, item) => sum + item.pattern_task_counts[pattern], 0)
  ]));
  return { taskCounts, efficiencyValues, patternTaskCounts };
}

function rate(numerator, denominator) {
  return denominator ? rounded(numerator / denominator) : null;
}

function delta(current, baseline, available) {
  return available && current !== null && baseline !== null
    ? rounded(current - baseline)
    : null;
}

export function buildTrend({ run, metrics, baselineMetrics, generatedAt }) {
  const baseline = aggregateBaseline(baselineMetrics);
  const available = metrics.task_counts.complete >= MIN_TREND_TASKS &&
    baseline.taskCounts.complete >= MIN_TREND_TASKS;
  const baselineAttainment = rate(baseline.taskCounts.achieved, baseline.taskCounts.known_outcome);
  const baselineCoverage = rate(baseline.taskCounts.known_outcome, baseline.taskCounts.total);
  const enoughKnownOutcomes = metrics.task_counts.known_outcome >= MIN_TREND_TASKS &&
    baseline.taskCounts.known_outcome >= MIN_TREND_TASKS;
  const deltas = {
    attainment_rate: delta(metrics.attainment_rate, baselineAttainment, available && enoughKnownOutcomes),
    outcome_coverage: delta(metrics.outcome_coverage, baselineCoverage, available),
    turn_count_median: delta(metrics.efficiency.turn_count.median, median(baseline.efficiencyValues.turn_count ?? []), available),
    clarification_count_median: delta(metrics.efficiency.clarification_count.median, median(baseline.efficiencyValues.clarification_count ?? []), available),
    repeated_clarification_count_median: delta(metrics.efficiency.repeated_clarification_count.median, median(baseline.efficiencyValues.repeated_clarification_count ?? []), available),
    execution_attempt_count_median: delta(metrics.efficiency.execution_attempt_count.median, median(baseline.efficiencyValues.execution_attempt_count ?? []), available),
    rework_count_median: delta(metrics.efficiency.rework_count.median, median(baseline.efficiencyValues.rework_count ?? []), available),
    repeated_clarification_rate: delta(
      metrics.pattern_rates.repeated_clarification,
      rate(baseline.patternTaskCounts.repeated_clarification, baseline.taskCounts.complete),
      available
    ),
    repeated_execution_rate: delta(
      metrics.pattern_rates.repeated_execution,
      rate(baseline.patternTaskCounts.repeated_execution, baseline.taskCounts.complete),
      available
    ),
    unmet_expectation_rate: delta(
      metrics.pattern_rates.unmet_expectation,
      rate(baseline.patternTaskCounts.unmet_expectation, baseline.taskCounts.complete),
      available
    )
  };
  return {
    schema_version: "1.0.0",
    contract_revision: run.parameters.contract_revision,
    contract_bundle_hash: run.parameters.contract_bundle_hash,
    run_id: run.run_id,
    project_id: run.parameters.project_id,
    generated_at: generatedAt,
    status: available ? "available" : "insufficient_data",
    interpretation: "observational_only",
    target_scope: metrics.target_scope,
    baseline_run_ids: baselineMetrics.map((item) => item.run_id),
    current_valid_task_count: metrics.task_counts.complete,
    baseline_valid_task_count: baseline.taskCounts.complete,
    target_change_detected: baselineMetrics.some((item) =>
      item.target_scope.target_set_hash !== metrics.target_scope.target_set_hash),
    deltas
  };
}

export { BASELINE_RUN_LIMIT };
