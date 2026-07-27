const PATTERN_LABELS = {
  repeated_clarification: "重复澄清",
  repeated_execution: "重复执行",
  unmet_expectation: "最终未达预期"
};

const ROOT_CAUSE_LABELS = {
  trigger_failure: "触发失败",
  workflow_gap: "工作流缺口",
  ambiguous_rule: "规则歧义",
  script_bug: "脚本缺陷",
  reference_gap: "参考资料缺口",
  template_issue: "模板问题",
  environment_issue: "环境问题",
  unclear_expectation: "预期不清"
};

const OUTCOME_LABELS = {
  achieved: "已达成",
  not_achieved: "未达成",
  unknown: "未知"
};

const CONFIDENCE_LABELS = {
  high: "高",
  medium: "中",
  low: "低",
  unknown: "未知"
};

const SIGNATURE_STATUS_LABELS = {
  registered: "已注册",
  candidate: "候选"
};

const OPTIMIZER_THRESHOLD = 3;

function plain(value) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function unique(values) {
  return [...new Set(values.filter(Boolean))];
}

function humanSummary(value) {
  const summary = plain(value);
  return /^[a-z0-9_]+$/.test(summary) ? summary.replaceAll("_", " ") : summary;
}

function gateStatus(cluster, taskCount, eligible) {
  if (eligible) return "达到";
  const reasons = [];
  if (taskCount < OPTIMIZER_THRESHOLD) {
    reasons.push(`独立任务数 ${taskCount} < ${OPTIMIZER_THRESHOLD}`);
  }
  if (cluster.signature_status !== "registered") {
    reasons.push("问题签名尚未注册");
  }
  if (cluster.root_cause_category === "environment_issue") {
    reasons.push("环境问题不进入自动优化");
  }
  if (!reasons.length) reasons.push("ELIGIBILITY_MISMATCH");
  return `未达到（${reasons.join("；")}）`;
}

function impact(cluster, tasks) {
  const counts = Object.fromEntries(
    Object.keys(OUTCOME_LABELS).map((status) => [
      status,
      tasks.filter((task) => task.outcome_status === status).length
    ])
  );
  const outcomes = ["achieved", "not_achieved", "unknown"]
    .map((status) => `${OUTCOME_LABELS[status]} ${counts[status]}`)
    .join(" / ");
  const focus = {
    repeated_clarification: "沟通效率，产生了重复澄清",
    repeated_execution: "执行效率，产生了重复执行或返工",
    unmet_expectation: "交付结果，出现了未满足预期的结果"
  }[cluster.pattern] ?? "任务结果";
  return `基于问题模式与结果状态的影响推断：影响 ${tasks.length} 个独立任务的${focus}；任务结果为 ${outcomes}。`;
}

export function renderFindingsSection(findings, evidence = null) {
  const lines = ["## 高频问题与根因", ""];
  const clusters = findings.issue_clusters ?? [];
  if (!clusters.length) {
    lines.push("没有识别到问题实例。");
    return lines.join("\n");
  }

  const instancesById = new Map(
    (findings.problem_instances ?? []).map((item) => [item.problem_instance_id, item])
  );
  const tasksById = new Map(
    (findings.task_episodes ?? []).map((item) => [item.task_episode_id, item])
  );
  const evidenceIndexes = new Map(
    (evidence?.records ?? []).map((item, index) => [item.evidence_id, index])
  );
  const eligibleIds = new Set(findings.optimizer_eligible_cluster_ids ?? []);
  const taskClusters = new Map();
  for (const cluster of clusters) {
    for (const taskId of cluster.task_episode_ids ?? []) {
      if (!taskClusters.has(taskId)) taskClusters.set(taskId, []);
      taskClusters.get(taskId).push(cluster.issue_cluster_id);
    }
  }

  for (const cluster of clusters) {
    const referencedIds = cluster.problem_instance_ids ?? [];
    const referencedInstances = referencedIds.map((itemId) => instancesById.get(itemId));
    const missingInstances = referencedIds.filter((itemId) => !instancesById.has(itemId));
    const instances = referencedInstances.filter(Boolean);
    let summaries = unique(
      instances.map((item) => plain(item.summary) || "DESCRIPTION_MISSING")
    );
    if (!summaries.length) summaries = ["DESCRIPTION_MISSING"];
    const patternLabel = PATTERN_LABELS[cluster.pattern] ?? cluster.pattern ?? "未知模式";
    const title = `${patternLabel}：${humanSummary(summaries[0])}`;
    let taskIds = unique(instances.map((item) => item.task_episode_id));
    if (!taskIds.length) taskIds = unique(cluster.task_episode_ids ?? []);
    const tasks = taskIds
      .filter((taskId) => tasksById.has(taskId))
      .map((taskId) => tasksById.get(taskId));
    const missingTasks = taskIds.filter((taskId) => !tasksById.has(taskId));
    const rootCategory = cluster.root_cause_category ?? "unknown";
    const eligible = eligibleIds.has(cluster.issue_cluster_id);

    lines.push(
      `### ${title}`,
      "",
      `- Cluster：\`${cluster.issue_cluster_id}\``,
      `- 模式 / 根因类别：${patternLabel}（\`${cluster.pattern}\`）/ ` +
        `${ROOT_CAUSE_LABELS[rootCategory] ?? rootCategory}（\`${rootCategory}\`）`,
      `- 问题签名：\`${cluster.issue_signature ?? "UNKNOWN"}\`（${SIGNATURE_STATUS_LABELS[cluster.signature_status] ?? "未知"}）`,
      `- 影响任务：${taskIds.length} 个独立任务；问题实例：${instances.length} 个`,
      `- 严重度：总计 ${cluster.severity_total ?? "未知"}`,
      `- Optimizer 就绪门（optimizer eligibility gate）：${gateStatus(cluster, taskIds.length, eligible)}`
    );
    if (missingInstances.length) {
      lines.push(
        "- 报告警告：REPORT_CLUSTER_REFERENCE_INVALID：缺少问题实例 " +
        missingInstances.map((itemId) => `\`${itemId}\``).join("、")
      );
    }
    if (missingTasks.length) {
      lines.push(
        "- 报告警告：TASK_EPISODE_MISSING：缺少任务 " +
        missingTasks.map((taskId) => `\`${taskId}\``).join("、")
      );
    }

    lines.push("", "#### 问题描述", "");
    if (summaries.length === 1) lines.push(summaries[0]);
    else lines.push(...summaries.map((summary) => `- ${summary}`));

    const expected = unique(tasks.map((task) => plain(task.expected_outcome)));
    const outcomeCounts = Object.fromEntries(
      Object.keys(OUTCOME_LABELS).map((status) => [
        status,
        tasks.filter((task) => task.outcome_status === status).length
      ])
    );
    const outcomeSummary = ["achieved", "not_achieved", "unknown"]
      .map((status) => `${OUTCOME_LABELS[status]} ${outcomeCounts[status]}`)
      .join(" / ");
    lines.push(
      "",
      "#### 预期与实际",
      "",
      `- 预期：${expected.length ? expected.join("；") : "EXPECTED_OUTCOME_MISSING"}`,
      `- 实际：${outcomeSummary}；已记录的问题：${summaries.join("；")}`,
      "",
      "#### 任务实例",
      ""
    );
    if (!tasks.length) lines.push("1. TASK_EPISODE_MISSING");
    for (const [index, task] of tasks.entries()) {
      const taskSummaries = unique(
        instances
          .filter((item) => item.task_episode_id === task.task_episode_id)
          .map((item) => plain(item.summary) || "DESCRIPTION_MISSING")
      );
      const associations = taskClusters.get(task.task_episode_id) ?? [];
      const associationNote = associations.length > 1
        ? `（同一任务关联 ${associations.length} 个问题簇）`
        : "";
      lines.push(
        `${index + 1}. ${plain(task.goal) || "TASK_GOAL_MISSING"}（\`${task.task_episode_id}\`）`,
        `   - 预期：${plain(task.expected_outcome) || "EXPECTED_OUTCOME_MISSING"}`,
        `   - 实际：${OUTCOME_LABELS[task.outcome_status] ?? "未知"}（\`${task.outcome_basis ?? "UNKNOWN"}\`）`,
        `   - 问题：${taskSummaries.length ? taskSummaries.join("；") : "DESCRIPTION_MISSING"}`,
        `   - 关联问题簇：${associations.map((item) => `\`${item}\``).join("、")}${associationNote}`
      );
    }

    const facts = unique(
      [...tasks, ...instances].flatMap((item) => item.facts ?? []).map(plain)
    );
    const inferences = unique(
      [...tasks, ...instances].flatMap((item) => item.inferences ?? []).map(plain)
    );
    const unknowns = unique(
      [...tasks, ...instances].flatMap((item) => item.unknowns ?? []).map(plain)
    );
    for (const [heading, values, empty] of [
      ["已验证事实", facts, "未记录已验证事实。"],
      ["推断", inferences, "未记录额外推断。"],
      ["未知项", unknowns, "未记录未知项。"]
    ]) {
      lines.push("", `#### ${heading}`, "");
      if (values.length) lines.push(...values.map((value) => `- ${value}`));
      else lines.push(`- ${empty}`);
    }

    const confidence = cluster.root_cause_confidence ?? "unknown";
    lines.push(
      "",
      "#### 根因",
      "",
      `${plain(cluster.root_cause) || "ROOT_CAUSE_UNKNOWN"}（根因判断：推断；置信度：` +
        `${CONFIDENCE_LABELS[confidence] ?? "未知"} / \`${confidence}\`）`
    );
    if (confidence === "unknown") lines.push("", "证据不足，根因尚未确认。");

    lines.push("", "#### 影响", "", impact(cluster, tasks));
    lines.push("", "#### 证据", "");
    const evidenceIds = unique(cluster.evidence_ids ?? []);
    for (const evidenceId of evidenceIds) {
      if (!evidenceIndexes.has(evidenceId)) {
        lines.push(`- \`${evidenceId}\` → \`EVIDENCE_POINTER_UNRESOLVED\``);
      } else {
        lines.push(`- \`${evidenceId}\` → \`evidence.json#/records/${evidenceIndexes.get(evidenceId)}\``);
      }
    }
    if (!evidenceIds.length) lines.push("- `EVIDENCE_POINTER_UNRESOLVED`");

    let criteria = unique(
      tasks
        .flatMap((task) => task.acceptance_criteria ?? [])
        .map((criterion) => plain(criterion.description))
    );
    if (!criteria.length) {
      criteria = unique([
        ...expected.map((value) => `在同类场景中满足预期：“${value}”。`),
        ...summaries.map((summary) => `回归验证不再出现：“${summary}”。`)
      ]);
    }
    lines.push("", "#### 建议验收标准", "");
    if (criteria.length) {
      lines.push(...criteria.map((criterion) => `- [ ] ${criterion}`));
    } else {
      lines.push("- [ ] 补充可验证的验收标准。");
    }
    lines.push("");
  }

  return lines.join("\n").trimEnd();
}
