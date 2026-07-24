import { writeText } from "./io.js";

const LABELS = {
  COMPLETED_NO_TASKS: "本周期没有可分析任务",
  COMPLETED_WITH_METRICS: "已生成效能与达成率报告",
  COMPLETED_WITH_FINDINGS: "已生成高频问题报告，未生成可执行提案",
  COMPLETED_WITH_PROPOSAL: "已生成改进提案"
};

const METRIC_LABELS = {
  turn_count: "任务轮次",
  clarification_count: "澄清次数",
  repeated_clarification_count: "重复澄清次数",
  execution_attempt_count: "执行尝试次数",
  rework_count: "返工次数"
};

const PATTERN_LABELS = {
  repeated_clarification: "重复澄清",
  repeated_execution: "重复执行",
  unmet_expectation: "最终未达预期"
};

function percent(value) {
  return value === null ? "无有效样本" : `${(value * 100).toFixed(1)}%`;
}

function number(value) {
  return value === null ? "无有效样本" : String(value);
}

function signed(value) {
  if (value === null) return "样本不足";
  return `${value > 0 ? "+" : ""}${value}`;
}

function signedPercent(value) {
  if (value === null) return "样本不足";
  const points = value * 100;
  return `${points > 0 ? "+" : ""}${points.toFixed(1)} 个百分点`;
}

export async function writeReport(file, run, artifacts = {}) {
  const { findings = null, metrics = null, trend = null, proposal = null } = artifacts;
  const failed = run.status.startsWith("FAILED_");
  const headline = failed ? "运行失败" : (LABELS[run.status] ?? run.status);
  const lines = [
    "# Failure Review Report",
    "",
    `- 运行 ID：\`${run.run_id}\``,
    `- 项目：\`${run.parameters.project_id}\``,
    `- 时间窗口：\`${run.parameters.window_start}\` 至 \`${run.parameters.window_end}\``,
    `- 时区：\`${run.parameters.timezone}\``,
    `- 结果：${headline}`,
    ""
  ];

  if (failed) {
    lines.push(
      "## 失败",
      "",
      `- 阶段：${run.failure.stage}`,
      `- 代码：\`${run.failure.code}\``,
      `- 原因：${run.failure.message}`,
      ""
    );
  }

  if (metrics) {
    lines.push(
      "## 达成率",
      "",
      `- 任务总数：${metrics.task_counts.total}`,
      `- 已达成 / 未达成 / 未知：${metrics.task_counts.achieved} / ${metrics.task_counts.not_achieved} / ${metrics.task_counts.unknown}`,
      `- 目标达成率：${percent(metrics.attainment_rate)}`,
      `- 结果覆盖率：${percent(metrics.outcome_coverage)}`,
      "",
      "## 执行效能",
      ""
    );
    for (const [key, label] of Object.entries(METRIC_LABELS)) {
      const value = metrics.efficiency[key];
      lines.push(`- ${label}：平均 ${number(value.average)}；中位数 ${number(value.median)}；样本 ${value.sample_count}`);
    }
    lines.push("", "## 问题模式发生率", "");
    for (const [pattern, label] of Object.entries(PATTERN_LABELS)) {
      lines.push(`- ${label}：${percent(metrics.pattern_rates[pattern])}（${metrics.pattern_task_counts[pattern]} 个任务）`);
    }
    lines.push("");
  }

  if (trend) {
    lines.push("## 历史趋势", "");
    if (trend.status === "insufficient_data") {
      lines.push(`有效样本不足：当前 ${trend.current_valid_task_count} 个，历史基线 ${trend.baseline_valid_task_count} 个。`, "");
    } else {
      lines.push(
        `- 基线运行：${trend.baseline_run_ids.map((id) => `\`${id}\``).join("、")}`,
        `- 目标文件发生变化：${trend.target_change_detected ? "是" : "否"}`,
        `- 达成率变化：${signedPercent(trend.deltas.attainment_rate)}`,
        `- 结果覆盖率变化：${signedPercent(trend.deltas.outcome_coverage)}`,
        `- 轮次中位数变化：${signed(trend.deltas.turn_count_median)}`,
        `- 澄清中位数变化：${signed(trend.deltas.clarification_count_median)}`,
        `- 重复澄清中位数变化：${signed(trend.deltas.repeated_clarification_count_median)}`,
        `- 执行尝试中位数变化：${signed(trend.deltas.execution_attempt_count_median)}`,
        `- 返工中位数变化：${signed(trend.deltas.rework_count_median)}`,
        `- 重复澄清任务发生率变化：${signedPercent(trend.deltas.repeated_clarification_rate)}`,
        `- 重复执行任务发生率变化：${signedPercent(trend.deltas.repeated_execution_rate)}`,
        `- 未达预期任务发生率变化：${signedPercent(trend.deltas.unmet_expectation_rate)}`,
        "",
        "以上仅为观察趋势，不表示改进载体变化与结果之间存在确定因果关系。",
        ""
      );
    }
  }

  if (findings) {
    lines.push("## 高频问题与根因", "");
    if (!findings.issue_clusters.length) {
      lines.push("没有识别到问题实例。");
    } else {
      for (const cluster of findings.issue_clusters) {
        const eligible = findings.optimizer_eligible_cluster_ids.includes(cluster.issue_cluster_id);
        lines.push(
          `- \`${cluster.issue_cluster_id}\` ${PATTERN_LABELS[cluster.pattern]} / \`${cluster.issue_signature}\`：` +
          `${cluster.instance_count} 个独立任务；根因 \`${cluster.root_cause_category}\`；` +
          `达到门槛：${eligible ? "是" : "否"}`
        );
      }
    }
    lines.push("");
  }

  if (run.status === "COMPLETED_WITH_FINDINGS" && !proposal) {
    lines.push("## 改进载体", "", "未配置项目可用的改进载体，本次未生成修改提案。", "");
  }
  if (proposal) {
    lines.push("## 改进提案", "");
    for (const disposition of proposal.dispositions) {
      if (disposition.status === "no_supported_target") {
        lines.push(`- \`${disposition.issue_cluster_id}\`：没有证据支持的允许目标；${disposition.reason}`);
      }
    }
    for (const item of proposal.proposals) {
      lines.push(
        `- \`${item.proposal_id}\` → 问题簇 \`${item.issue_cluster_id}\` → ` +
        `\`${item.target_id}\` / ${item.target_file} / ${item.target_location}`
      );
    }
    lines.push("", "提案仅供人工确认；本次运行未修改任何改进载体。", "");
  }

  lines.push(
    "## 回溯文件",
    "",
    "- `evidence.json`：按角色和顺序保存的对话证据",
    "- `findings.json`：任务结果、问题实例和问题簇",
    "- `metrics.json`：确定性效能与达成率指标",
    "- `trend.json`：最近七次有效运行的观察趋势",
    "- `improvement-targets.json`：本次锁定的改进载体及内容哈希"
  );
  if (proposal) lines.push("- `proposal.json`：问题簇处置、最小修改建议与回归测试");
  lines.push("");
  await writeText(file, `${lines.join("\n")}\n`);
}
