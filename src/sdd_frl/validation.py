from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .errors import SddFrlError
from .resources import asset_path


def schema_errors(kind: str, value: Any) -> list[dict[str, str]]:
    schema = json.loads(asset_path("schemas", f"{kind}.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = []
    for error in sorted(validator.iter_errors(value), key=lambda item: list(item.absolute_path)):
        pointer = "/" + "/".join(str(item) for item in error.absolute_path)
        errors.append({"path": pointer, "message": error.message})
    return errors


def validate_schema(kind: str, value: Any) -> None:
    errors = schema_errors(kind, value)
    if errors:
        raise SddFrlError(
            f"{kind.upper()}_SCHEMA_INVALID",
            json.dumps(errors, ensure_ascii=False),
        )


def validate_evidence(
    evidence: dict[str, Any],
    *,
    run: dict[str, Any],
    source: dict[str, Any],
) -> None:
    validate_schema("evidence", evidence)
    params = run["parameters"]
    if evidence["run_id"] != run["run_id"] or evidence["project_id"] != params["project_id"]:
        raise SddFrlError("EVIDENCE_SCOPE_MISMATCH", "evidence 与 run 的运行范围不一致。")
    source_records = [
        record
        for conversation in source["conversations"]
        for record in conversation["records"]
    ]
    if len(source_records) != len(evidence["records"]):
        raise SddFrlError("EVIDENCE_SOURCE_MISMATCH", "evidence 没有一对一覆盖原始记录。")
    for expected, actual in zip(source_records, evidence["records"], strict=True):
        for key in (
            "conversation_id",
            "timestamp",
            "actor",
            "sequence",
            "event_type",
            "call_id",
            "source_location",
            "content_or_reference",
            "content_hash",
            "collection_status",
        ):
            if actual[key] != expected[key]:
                raise SddFrlError(
                    "EVIDENCE_SOURCE_MISMATCH",
                    f"evidence 字段 {key} 与确定性采集结果不一致。",
                )


def validate_findings(
    findings: dict[str, Any],
    *,
    run: dict[str, Any],
    evidence: dict[str, Any],
) -> None:
    validate_schema("findings", findings)
    if findings["run_id"] != run["run_id"]:
        raise SddFrlError("FINDINGS_SCOPE_MISMATCH", "findings.run_id 与 run 不一致。")
    if findings["project_id"] != run["parameters"]["project_id"]:
        raise SddFrlError("FINDINGS_SCOPE_MISMATCH", "findings.project_id 与 run 不一致。")
    valid_ids = {item["evidence_id"] for item in evidence["records"]}
    covered_user_ids = set()
    for task in findings["task_episodes"]:
        referenced = set(task["evidence_ids"])
        if not referenced <= valid_ids:
            raise SddFrlError("FINDINGS_EVIDENCE_UNKNOWN", "任务引用了不存在的 evidence_id。")
        covered_user_ids |= {
            item["evidence_id"]
            for item in evidence["records"]
            if item["actor"] == "user" and item["evidence_id"] in referenced
        }
        clarifications = [
            item for item in task["interaction_events"]
            if item["kind"] == "clarification"
        ]
        executions = [
            item for item in task["interaction_events"]
            if item["kind"] == "execution_attempt"
        ]
        expected_counts = {
            "clarification_count": len(clarifications),
            "repeated_clarification_count": sum(item["repeated"] for item in clarifications),
            "execution_attempt_count": len(executions),
            "rework_count": sum(item["rework"] for item in executions),
        }
        for key, value in expected_counts.items():
            if task["counts"][key] != value:
                raise SddFrlError("FINDINGS_COUNT_MISMATCH", f"{key} 与 interaction_events 不一致。")
    excluded = {item["evidence_id"] for item in findings["excluded_evidence"]}
    user_ids = {
        item["evidence_id"] for item in evidence["records"] if item["actor"] == "user"
    }
    if covered_user_ids | excluded != user_ids:
        raise SddFrlError("FINDINGS_USER_COVERAGE", "每条用户消息必须被任务覆盖或显式排除。")

    instances = {item["problem_instance_id"]: item for item in findings["problem_instances"]}
    eligible = set(findings["optimizer_eligible_cluster_ids"])
    for cluster in findings["issue_clusters"]:
        cluster_instances = [instances[item] for item in cluster["problem_instance_ids"]]
        task_ids = {item["task_episode_id"] for item in cluster_instances}
        is_eligible = (
            cluster["signature_status"] == "registered"
            and len(task_ids) >= 3
            and cluster["root_cause_category"] != "environment_issue"
        )
        if (cluster["issue_cluster_id"] in eligible) != is_eligible:
            raise SddFrlError(
                "FINDINGS_THRESHOLD_MISMATCH",
                f"问题簇 {cluster['issue_cluster_id']} 的就绪门判定错误。",
            )


def validate_metrics(metrics: dict[str, Any], expected: dict[str, Any]) -> None:
    validate_schema("metrics", metrics)
    if metrics != expected:
        raise SddFrlError("METRICS_MISMATCH", "metrics 必须等于确定性重算结果。")


def validate_trend(trend: dict[str, Any], expected: dict[str, Any]) -> None:
    validate_schema("trend", trend)
    if trend != expected:
        raise SddFrlError("TREND_MISMATCH", "trend 必须等于确定性重算结果。")


def validate_proposal(
    proposal: dict[str, Any],
    *,
    run: dict[str, Any],
    findings: dict[str, Any],
) -> None:
    validate_schema("proposal", proposal)
    if proposal["run_id"] != run["run_id"]:
        raise SddFrlError("PROPOSAL_SCOPE_MISMATCH", "proposal.run_id 与 run 不一致。")
    eligible = set(findings["optimizer_eligible_cluster_ids"])
    disposed = [item["issue_cluster_id"] for item in proposal["dispositions"]]
    if set(disposed) != eligible or len(disposed) != len(eligible):
        raise SddFrlError("PROPOSAL_DISPOSITION_MISMATCH", "每个合格问题簇必须恰好处置一次。")


def load_and_validate_file(kind: str, file: str | Path) -> dict[str, Any]:
    path = Path(file).resolve()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SddFrlError("FILE_NOT_FOUND", f"找不到文件：{path}") from exc
    validate_schema(kind, value)
    return value
