from __future__ import annotations

import re
from typing import Any

OUTCOME_LABELS = {
    "achieved": "已达成",
    "not_achieved": "未达成",
    "unknown": "未知",
}
OPTIMIZATION_LABELS = {
    "prompt": "Prompt",
    "skill": "Skill",
    "agent": "Agent",
    "unknown": "暂无法确定",
}


def _plain(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _linked_alignments(
    task: dict[str, Any],
    divergence_id: str,
) -> list[dict[str, Any]]:
    return [
        item
        for item in task.get("alignments", [])
        if item.get("divergence_id") == divergence_id
    ]


def render_findings_section(
    findings: dict[str, Any],
    evidence: dict[str, Any] | None = None,
) -> str:
    """Render a human-readable task review without exposing raw evidence."""
    del evidence
    tasks = findings.get("task_episodes", [])
    lines = ["## 任务分析", ""]
    if not tasks:
        lines.append("本周期没有形成可分析任务。")
        return "\n".join(lines)

    all_divergences: list[dict[str, Any]] = []
    for index, task in enumerate(tasks, start=1):
        lines.extend([
            f"### {index}. {_plain(task.get('goal')) or '未命名任务'}",
            "",
            f"**结果：{OUTCOME_LABELS.get(task.get('outcome_status'), '未知')}**",
            "",
            "**用户目标**",
            "",
            _plain(task.get("expected_outcome")) or "未记录明确预期。",
            "",
            "**过程**",
            "",
        ])
        summaries = [
            _plain(item) for item in task.get("execution_summary", []) if _plain(item)
        ]
        lines.extend(f"- {item}" for item in summaries)
        if not summaries:
            lines.append("- 未记录关键过程。")

        lines.extend(["", "**分歧与对齐**", ""])
        divergences = task.get("divergences", [])
        if not divergences:
            lines.append("未发现有证据支持的分歧。")
        for divergence in divergences:
            all_divergences.append(divergence)
            status = "已解决" if divergence["status"] == "resolved" else "未解决"
            lines.extend([
                f"**分歧：{_plain(divergence['summary'])}（{status}）**",
                "",
                f"- 用户期望：{_plain(divergence['user_expectation'])}",
                f"- Agent 实际行为：{_plain(divergence['agent_behavior'])}",
            ])
            alignments = _linked_alignments(task, divergence["divergence_id"])
            if alignments:
                lines.append(
                    "- 对齐结果："
                    + "；".join(_plain(item["summary"]) for item in alignments)
                )
                lines.append(
                    "- 后续动作："
                    + "；".join(_plain(item["resulting_action"]) for item in alignments)
                )
            else:
                lines.append("- 对齐结果：尚未完成对齐。")
            lines.extend([
                f"- 根因：{_plain(divergence['root_cause'])}",
                (
                    "- 优化对象："
                    f"{OPTIMIZATION_LABELS.get(divergence['optimization_target'], '暂无法确定')}"
                ),
                f"- 优化方向：{_plain(divergence['optimization_direction'])}",
                f"- 验收方式：{_plain(divergence['acceptance_check'])}",
                "",
            ])

        independent_alignments = [
            item
            for item in task.get("alignments", [])
            if item.get("divergence_id") is None
        ]
        for alignment in independent_alignments:
            lines.extend([
                f"- 对齐：{_plain(alignment['summary'])}",
                f"- 后续动作：{_plain(alignment['resulting_action'])}",
            ])
        if lines[-1] != "":
            lines.append("")

    lines.extend(["## 优化清单", ""])
    if not all_divergences:
        lines.append("本周期没有发现需要修改 Prompt、Skill 或 Agent 的分歧。")
    else:
        for divergence in sorted(
            all_divergences,
            key=lambda item: item["status"] == "resolved",
        ):
            target = OPTIMIZATION_LABELS.get(
                divergence["optimization_target"],
                "暂无法确定",
            )
            lines.append(
                f"- **{target}**：{_plain(divergence['optimization_direction'])}"
                f"（{_plain(divergence['summary'])}）"
            )
    return "\n".join(lines).rstrip()
