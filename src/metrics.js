const PATTERNS = Object.freeze([
  "repeated_clarification",
  "repeated_execution",
  "unmet_expectation"
]);

const EFFICIENCY_KEYS = Object.freeze([
  "turn_count",
  "clarification_count",
  "repeated_clarification_count",
  "execution_attempt_count",
  "rework_count"
]);

function rounded(value) {
  return Math.round(value * 1_000_000) / 1_000_000;
}

export function median(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2
    ? sorted[middle]
    : rounded((sorted[middle - 1] + sorted[middle]) / 2);
}

export function distribution(values) {
  const sorted = [...values].sort((left, right) => left - right);
  const total = sorted.reduce((sum, value) => sum + value, 0);
  return {
    sample_count: sorted.length,
    total,
    average: sorted.length ? rounded(total / sorted.length) : null,
    median: median(sorted),
    values: sorted
  };
}

function rate(numerator, denominator) {
  return denominator ? rounded(numerator / denominator) : null;
}

export function metricCore(findings, targetScope) {
  const tasks = findings.task_episodes;
  const completeTasks = tasks.filter((task) => task.context_status === "complete");
  const taskCounts = {
    total: tasks.length,
    complete: completeTasks.length,
    truncated: tasks.length - completeTasks.length,
    achieved: tasks.filter((task) => task.outcome_status === "achieved").length,
    not_achieved: tasks.filter((task) => task.outcome_status === "not_achieved").length,
    unknown: tasks.filter((task) => task.outcome_status === "unknown").length,
    known_outcome: tasks.filter((task) => task.outcome_status !== "unknown").length
  };
  const efficiency = Object.fromEntries(EFFICIENCY_KEYS.map((key) => [
    key,
    distribution(completeTasks.map((task) => task.counts[key]))
  ]));
  const completeTaskIds = new Set(completeTasks.map((task) => task.task_episode_id));
  const patternTaskCounts = Object.fromEntries(PATTERNS.map((pattern) => {
    const taskIds = new Set(findings.problem_instances
      .filter((instance) => instance.pattern === pattern && completeTaskIds.has(instance.task_episode_id))
      .map((instance) => instance.task_episode_id));
    return [pattern, taskIds.size];
  }));
  const patternRates = Object.fromEntries(PATTERNS.map((pattern) => [
    pattern,
    rate(patternTaskCounts[pattern], completeTasks.length)
  ]));

  return {
    target_scope: targetScope,
    task_counts: taskCounts,
    attainment_rate: rate(taskCounts.achieved, taskCounts.known_outcome),
    outcome_coverage: rate(taskCounts.known_outcome, taskCounts.total),
    efficiency,
    pattern_task_counts: patternTaskCounts,
    pattern_rates: patternRates
  };
}

export function buildMetrics({ run, findings, generatedAt }) {
  return {
    schema_version: "1.0.0",
    contract_revision: run.parameters.contract_revision,
    contract_bundle_hash: run.parameters.contract_bundle_hash,
    run_id: run.run_id,
    project_id: run.parameters.project_id,
    generated_at: generatedAt,
    ...metricCore(findings, {
      improvement_target_ids: run.parameters.improvement_target_ids,
      target_set_hash: run.parameters.target_set_hash,
      contract_revision: run.parameters.contract_revision,
      contract_bundle_hash: run.parameters.contract_bundle_hash
    })
  };
}

export { EFFICIENCY_KEYS, PATTERNS };
