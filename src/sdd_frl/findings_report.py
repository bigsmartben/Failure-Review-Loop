from __future__ import annotations

import re
from typing import Any

PATTERN_LABELS = {
    "repeated_clarification": "重复澄清",
    "repeated_execution": "重复执行",
    "unmet_expectation": "最终未达预期",
}
ROOT_CAUSE_LABELS = {
    "trigger_failure": "触发失败",
    "workflow_gap": "工作流缺口",
    "ambiguous_rule": "规则歧义",
    "script_bug": "脚本缺陷",
    "reference_gap": "参考资料缺口",
    "template_issue": "模板问题",
    "environment_issue": "环境问题",
    "unclear_expectation": "预期不清",
}
OUTCOME_LABELS = {
    "achieved": "已达成",
    "not_achieved": "未达成",
    "unknown": "未知",
}
CONFIDENCE_LABELS = {
    "high": "高",
    "medium": "中",
    "low": "低",
    "unknown": "未知",
}
SIGNATURE_STATUS_LABELS = {
    "registered": "已注册",
    "candidate": "候选",
}
OPTIMIZER_THRESHOLD = 3


def _plain(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _human_summary(value: str) -> str:
    summary = _plain(value)
    if re.fullmatch(r"[a-z0-9_]+", summary):
        return summary.replace("_", " ")
    return summary


def _gate_status(cluster: dict[str, Any], task_count: int, eligible: bool) -> str:
    if eligible:
        return "达到"
    reasons = []
    if task_count < OPTIMIZER_THRESHOLD:
        reasons.append(f"独立任务数 {task_count} < {OPTIMIZER_THRESHOLD}")
    if cluster.get("signature_status") != "registered":
        reasons.append("问题签名尚未注册")
    if cluster.get("root_cause_category") == "environment_issue":
        reasons.append("环境问题不进入自动优化")
    if not reasons:
        reasons.append("ELIGIBILITY_MISMATCH")
    return f"未达到（{'；'.join(reasons)}）"


def _impact(cluster: dict[str, Any], tasks: list[dict[str, Any]]) -> str:
    counts = {
        status: sum(task.get("outcome_status") == status for task in tasks)
        for status in OUTCOME_LABELS
    }
    outcomes = " / ".join(
        f"{OUTCOME_LABELS[status]} {counts[status]}"
        for status in ("achieved", "not_achieved", "unknown")
    )
    focus = {
        "repeated_clarification": "沟通效率，产生了重复澄清",
        "repeated_execution": "执行效率，产生了重复执行或返工",
        "unmet_expectation": "交付结果，出现了未满足预期的结果",
    }.get(cluster.get("pattern"), "任务结果")
    return (
        f"基于问题模式与结果状态的影响推断：影响 {len(tasks)} 个独立任务的"
        f"{focus}；任务结果为 {outcomes}。"
    )


def render_findings_section(
    findings: dict[str, Any],
    evidence: dict[str, Any] | None = None,
) -> str:
    """Render issue-ready findings without copying raw evidence content."""
    lines = ["## 高频问题与根因", ""]
    clusters = findings.get("issue_clusters", [])
    if not clusters:
        lines.append("没有识别到问题实例。")
        return "\n".join(lines)

    instances_by_id = {
        item["problem_instance_id"]: item
        for item in findings.get("problem_instances", [])
    }
    tasks_by_id = {
        item["task_episode_id"]: item
        for item in findings.get("task_episodes", [])
    }
    evidence_indexes = {
        item.get("evidence_id"): index
        for index, item in enumerate((evidence or {}).get("records", []))
    }
    eligible_ids = set(findings.get("optimizer_eligible_cluster_ids", []))
    task_clusters: dict[str, list[str]] = {}
    for item in clusters:
        for task_id in item.get("task_episode_ids", []):
            task_clusters.setdefault(task_id, []).append(item["issue_cluster_id"])

    for cluster in clusters:
        referenced_ids = cluster.get("problem_instance_ids", [])
        referenced_instances = [
            instances_by_id.get(item_id) for item_id in referenced_ids
        ]
        missing_instances = [
            item_id
            for item_id, instance in zip(
                referenced_ids, referenced_instances, strict=False
            )
            if instance is None
        ]
        instances = [item for item in referenced_instances if item is not None]
        summaries = _unique([
            _plain(item.get("summary")) or "DESCRIPTION_MISSING"
            for item in instances
        ])
        if not summaries:
            summaries = ["DESCRIPTION_MISSING"]
        pattern = cluster.get("pattern", "unknown")
        pattern_label = PATTERN_LABELS.get(pattern, pattern)
        title = f"{pattern_label}：{_human_summary(summaries[0])}"
        task_ids = _unique([
            item.get("task_episode_id", "") for item in instances
        ])
        if not task_ids:
            task_ids = _unique(cluster.get("task_episode_ids", []))
        tasks = [
            tasks_by_id[task_id]
            for task_id in task_ids
            if task_id in tasks_by_id
        ]
        missing_tasks = [
            task_id for task_id in task_ids if task_id not in tasks_by_id
        ]
        root_category = cluster.get("root_cause_category", "unknown")
        eligible = cluster["issue_cluster_id"] in eligible_ids

        lines.extend([
            f"### {title}",
            "",
            f"- Cluster：`{cluster['issue_cluster_id']}`",
            (
                f"- 模式 / 根因类别：{pattern_label}（`{pattern}`）/ "
                f"{ROOT_CAUSE_LABELS.get(root_category, root_category)}"
                f"（`{root_category}`）"
            ),
            (
                f"- 问题签名：`{cluster.get('issue_signature', 'UNKNOWN')}`"
                f"（{SIGNATURE_STATUS_LABELS.get(cluster.get('signature_status'), '未知')}）"
            ),
            f"- 影响任务：{len(task_ids)} 个独立任务；问题实例：{len(instances)} 个",
            f"- 严重度：总计 {cluster.get('severity_total', '未知')}",
            (
                "- Optimizer 就绪门（optimizer eligibility gate）："
                f"{_gate_status(cluster, len(task_ids), eligible)}"
            ),
        ])
        if missing_instances:
            lines.append(
                "- 报告警告：REPORT_CLUSTER_REFERENCE_INVALID：缺少问题实例 "
                + "、".join(f"`{item_id}`" for item_id in missing_instances)
            )
        if missing_tasks:
            lines.append(
                "- 报告警告：TASK_EPISODE_MISSING：缺少任务 "
                + "、".join(f"`{task_id}`" for task_id in missing_tasks)
            )

        lines.extend(["", "#### 问题描述", ""])
        if len(summaries) == 1:
            lines.append(summaries[0])
        else:
            lines.extend(f"- {summary}" for summary in summaries)

        expected = _unique([_plain(task.get("expected_outcome")) for task in tasks])
        outcome_counts = {
            status: sum(task.get("outcome_status") == status for task in tasks)
            for status in OUTCOME_LABELS
        }
        outcome_summary = " / ".join(
            f"{OUTCOME_LABELS[status]} {outcome_counts[status]}"
            for status in ("achieved", "not_achieved", "unknown")
        )
        lines.extend([
            "",
            "#### 预期与实际",
            "",
            f"- 预期：{'；'.join(expected) if expected else 'EXPECTED_OUTCOME_MISSING'}",
            f"- 实际：{outcome_summary}；已记录的问题：{'；'.join(summaries)}",
            "",
            "#### 任务实例",
            "",
        ])
        if not tasks:
            lines.append("1. TASK_EPISODE_MISSING")
        for index, task in enumerate(tasks, start=1):
            task_id = task["task_episode_id"]
            task_summaries = _unique([
                _plain(item.get("summary")) or "DESCRIPTION_MISSING"
                for item in instances
                if item.get("task_episode_id") == task_id
            ])
            associations = task_clusters.get(task_id, [])
            association_note = (
                f"（同一任务关联 {len(associations)} 个问题簇）"
                if len(associations) > 1
                else ""
            )
            lines.extend([
                f"{index}. {_plain(task.get('goal')) or 'TASK_GOAL_MISSING'}（`{task_id}`）",
                f"   - 预期：{_plain(task.get('expected_outcome')) or 'EXPECTED_OUTCOME_MISSING'}",
                (
                    "   - 实际："
                    f"{OUTCOME_LABELS.get(task.get('outcome_status'), '未知')}"
                    f"（`{task.get('outcome_basis', 'UNKNOWN')}`）"
                ),
                (
                    "   - 问题："
                    f"{'；'.join(task_summaries) if task_summaries else 'DESCRIPTION_MISSING'}"
                ),
                (
                    "   - 关联问题簇："
                    f"{'、'.join(f'`{item}`' for item in associations)}{association_note}"
                ),
            ])

        facts = _unique([
            _plain(value)
            for item in [*tasks, *instances]
            for value in item.get("facts", [])
        ])
        inferences = _unique([
            _plain(value)
            for item in [*tasks, *instances]
            for value in item.get("inferences", [])
        ])
        unknowns = _unique([
            _plain(value)
            for item in [*tasks, *instances]
            for value in item.get("unknowns", [])
        ])
        for heading, values, empty in (
            ("已验证事实", facts, "未记录已验证事实。"),
            ("推断", inferences, "未记录额外推断。"),
            ("未知项", unknowns, "未记录未知项。"),
        ):
            lines.extend(["", f"#### {heading}", ""])
            lines.extend(f"- {value}" for value in values)
            if not values:
                lines.append(f"- {empty}")

        confidence = cluster.get("root_cause_confidence", "unknown")
        lines.extend([
            "",
            "#### 根因",
            "",
            (
                f"{_plain(cluster.get('root_cause')) or 'ROOT_CAUSE_UNKNOWN'}"
                "（根因判断：推断；置信度："
                f"{CONFIDENCE_LABELS.get(confidence, '未知')} / `{confidence}`）"
            ),
        ])
        if confidence == "unknown":
            lines.extend(["", "证据不足，根因尚未确认。"])

        lines.extend(["", "#### 影响", "", _impact(cluster, tasks)])
        lines.extend(["", "#### 证据", ""])
        evidence_ids = _unique(cluster.get("evidence_ids", []))
        for evidence_id in evidence_ids:
            evidence_index = evidence_indexes.get(evidence_id)
            if evidence_index is None:
                lines.append(
                    f"- `{evidence_id}` → `EVIDENCE_POINTER_UNRESOLVED`"
                )
            else:
                lines.append(
                    f"- `{evidence_id}` → `evidence.json#/records/{evidence_index}`"
                )
        if not evidence_ids:
            lines.append("- `EVIDENCE_POINTER_UNRESOLVED`")

        criteria = _unique([
            _plain(criterion.get("description"))
            for task in tasks
            for criterion in task.get("acceptance_criteria", [])
        ])
        if not criteria:
            criteria.extend(
                f"在同类场景中满足预期：“{value}”。" for value in expected
            )
            criteria.extend(
                f"回归验证不再出现：“{summary}”。" for summary in summaries
            )
            criteria = _unique(criteria)
        lines.extend(["", "#### 建议验收标准", ""])
        lines.extend(f"- [ ] {criterion}" for criterion in criteria)
        if not criteria:
            lines.append("- [ ] 补充可验证的验收标准。")
        lines.append("")

    return "\n".join(lines).rstrip()
