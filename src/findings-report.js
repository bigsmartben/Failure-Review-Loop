const OUTCOME_LABELS = {
  achieved: "已达成",
  not_achieved: "未达成",
  unknown: "未知"
};

const OPTIMIZATION_LABELS = {
  prompt: "Prompt",
  skill: "Skill",
  agent: "Agent",
  unknown: "暂无法确定"
};

function plain(value) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function linkedAlignments(task, divergenceId) {
  return (task.alignments ?? []).filter(
    (item) => item.divergence_id === divergenceId
  );
}

export function renderFindingsSection(findings, evidence = null) {
  void evidence;
  const tasks = findings.task_episodes ?? [];
  const lines = ["## 任务分析", ""];
  if (!tasks.length) {
    lines.push("本周期没有形成可分析任务。");
    return lines.join("\n");
  }

  const allDivergences = [];
  for (const [index, task] of tasks.entries()) {
    lines.push(
      `### ${index + 1}. ${plain(task.goal) || "未命名任务"}`,
      "",
      `**结果：${OUTCOME_LABELS[task.outcome_status] ?? "未知"}**`,
      "",
      "**用户目标**",
      "",
      plain(task.expected_outcome) || "未记录明确预期。",
      "",
      "**过程**",
      ""
    );
    const summaries = (task.execution_summary ?? []).map(plain).filter(Boolean);
    if (summaries.length) lines.push(...summaries.map((item) => `- ${item}`));
    else lines.push("- 未记录关键过程。");

    lines.push("", "**分歧与对齐**", "");
    const divergences = task.divergences ?? [];
    if (!divergences.length) lines.push("未发现有证据支持的分歧。");
    for (const divergence of divergences) {
      allDivergences.push(divergence);
      const status = divergence.status === "resolved" ? "已解决" : "未解决";
      lines.push(
        `**分歧：${plain(divergence.summary)}（${status}）**`,
        "",
        `- 用户期望：${plain(divergence.user_expectation)}`,
        `- Agent 实际行为：${plain(divergence.agent_behavior)}`
      );
      const alignments = linkedAlignments(task, divergence.divergence_id);
      if (alignments.length) {
        lines.push(
          `- 对齐结果：${alignments.map((item) => plain(item.summary)).join("；")}`,
          `- 后续动作：${alignments.map((item) => plain(item.resulting_action)).join("；")}`
        );
      } else {
        lines.push("- 对齐结果：尚未完成对齐。");
      }
      lines.push(
        `- 根因：${plain(divergence.root_cause)}`,
        `- 优化对象：${OPTIMIZATION_LABELS[divergence.optimization_target] ?? "暂无法确定"}`,
        `- 优化方向：${plain(divergence.optimization_direction)}`,
        `- 验收方式：${plain(divergence.acceptance_check)}`,
        ""
      );
    }

    const independentAlignments = (task.alignments ?? []).filter(
      (item) => item.divergence_id === null
    );
    for (const alignment of independentAlignments) {
      lines.push(
        `- 对齐：${plain(alignment.summary)}`,
        `- 后续动作：${plain(alignment.resulting_action)}`
      );
    }
    if (lines.at(-1) !== "") lines.push("");
  }

  lines.push("## 优化清单", "");
  if (!allDivergences.length) {
    lines.push("本周期没有发现需要修改 Prompt、Skill 或 Agent 的分歧。");
  } else {
    allDivergences
      .sort((left, right) => Number(left.status === "resolved") - Number(right.status === "resolved"))
      .forEach((divergence) => {
        const target = OPTIMIZATION_LABELS[divergence.optimization_target] ?? "暂无法确定";
        lines.push(
          `- **${target}**：${plain(divergence.optimization_direction)}` +
          `（${plain(divergence.summary)}）`
        );
      });
  }
  return lines.join("\n").trimEnd();
}
