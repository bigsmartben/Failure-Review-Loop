from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .io import utc_now, write_text_atomic
from .workspace import Workspace

LABELS = {
    "COMPLETED_NO_TASKS": "本周期没有可分析任务",
    "COMPLETED_WITH_METRICS": "已生成效能与达成率报告",
    "COMPLETED_WITH_FINDINGS": "已生成高频问题报告，未生成可执行提案",
    "COMPLETED_WITH_PROPOSAL": "已生成改进提案",
}
METRIC_LABELS = {
    "turn_count": "任务轮次",
    "clarification_count": "澄清次数",
    "repeated_clarification_count": "重复澄清次数",
    "execution_attempt_count": "执行尝试次数",
    "rework_count": "返工次数",
}
PATTERN_LABELS = {
    "repeated_clarification": "重复澄清",
    "repeated_execution": "重复执行",
    "unmet_expectation": "最终未达预期",
}


def _percent(value: float | None) -> str:
    return "无有效样本" if value is None else f"{value * 100:.1f}%"


def _number(value: int | float | None) -> str:
    return "无有效样本" if value is None else str(value)


def render_report(
    *,
    run: dict[str, Any],
    review_date: str,
    metrics: dict[str, Any] | None = None,
    findings: dict[str, Any] | None = None,
    trend: dict[str, Any] | None = None,
    proposal: dict[str, Any] | None = None,
) -> str:
    status = run["status"]
    failed = status.startswith("FAILED_")
    headline = "运行失败" if failed else LABELS.get(status, status)
    params = run["parameters"]
    lines = [
        "---",
        f"project_id: {params['project_id']}",
        f"review_date: {review_date}",
        f"run_id: {run['run_id']}",
        f"status: {status}",
        f"generated_at: {utc_now()}",
        "---",
        "",
        "# Failure Review Report",
        "",
        f"- 项目：`{params['project_id']}`",
        f"- 复盘日期：`{review_date}`",
        f"- 时间窗口：`{params['window_start']}` 至 `{params['window_end']}`",
        f"- 时区：`{params['timezone']}`",
        f"- 结果：{headline}",
        "",
    ]
    if failed:
        failure = run.get("failure") or {}
        lines.extend([
            "## 失败",
            "",
            f"- 阶段：{failure.get('stage', 'orchestrator')}",
            f"- 代码：`{failure.get('code', 'UNKNOWN')}`",
            f"- 原因：{failure.get('message', '未知错误')}",
            "",
        ])
    if metrics:
        counts = metrics["task_counts"]
        lines.extend([
            "## 达成率",
            "",
            f"- 任务总数：{counts['total']}",
            (
                "- 已达成 / 未达成 / 未知："
                f"{counts['achieved']} / {counts['not_achieved']} / {counts['unknown']}"
            ),
            f"- 目标达成率：{_percent(metrics['attainment_rate'])}",
            f"- 结果覆盖率：{_percent(metrics['outcome_coverage'])}",
            "",
            "## 执行效能",
            "",
        ])
        for key, label in METRIC_LABELS.items():
            value = metrics["efficiency"][key]
            lines.append(
                f"- {label}：平均 {_number(value['average'])}；"
                f"中位数 {_number(value['median'])}；样本 {value['sample_count']}"
            )
        lines.extend(["", "## 问题模式发生率", ""])
        for pattern, label in PATTERN_LABELS.items():
            lines.append(
                f"- {label}：{_percent(metrics['pattern_rates'][pattern])}"
                f"（{metrics['pattern_task_counts'][pattern]} 个任务）"
            )
        lines.append("")
    if trend:
        lines.extend(["## 历史趋势", ""])
        if trend["status"] == "insufficient_data":
            lines.extend([
                (
                    f"有效样本不足：当前 {trend['current_valid_task_count']} 个，"
                    f"历史基线 {trend['baseline_valid_task_count']} 个。"
                ),
                "",
            ])
        else:
            lines.extend([
                f"- 基线运行：{'、'.join(trend['baseline_run_ids'])}",
                "- 解释：仅表示观察趋势，不代表确定因果关系。",
                "",
            ])
    if findings:
        lines.extend(["## 高频问题与根因", ""])
        if not findings["issue_clusters"]:
            lines.append("没有识别到问题实例。")
        for cluster in findings["issue_clusters"]:
            lines.append(
                f"- `{cluster['issue_cluster_id']}` "
                f"{PATTERN_LABELS[cluster['pattern']]} / "
                f"`{cluster['issue_signature']}`：{cluster['instance_count']} 个独立任务"
            )
        lines.append("")
    if proposal:
        lines.extend(["## 改进提案", ""])
        for item in proposal["proposals"]:
            lines.append(
                f"- `{item['proposal_id']}` → `{item['issue_cluster_id']}` → "
                f"`{item['target_id']}` / {item['target_file']}"
            )
        lines.extend(["", "提案仅供人工确认；本次运行未修改任何改进载体。", ""])
    lines.extend([
        "## 回溯文件",
        "",
        f"- `.sdd-frl/runs/{run['run_id']}/`：本次运行的结构化证据、指标与日志",
        "",
    ])
    return "\n".join(lines)


def _existing_status(path: Path) -> str | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    match = re.search(r"^status:\s*(\S+)\s*$", text, re.MULTILINE)
    return match.group(1) if match else None


def publish_report(
    *,
    workspace: Workspace,
    raw_report: Path,
    review_date: str,
    status: str,
) -> tuple[Path, bool]:
    destination = workspace.reports_dir / f"{review_date}.md"
    existing = _existing_status(destination)
    if status.startswith("FAILED_") and existing and existing.startswith("COMPLETED_"):
        return destination, False
    write_text_atomic(destination, raw_report.read_text(encoding="utf-8"))
    return destination, True
