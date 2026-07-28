from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .errors import SddFrlError
from .io import hash_json
from .resources import asset_path
from .source import EMPTY_REASONS, SUMMARY_FIELDS, parse_datetime


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


def validate_source_records(source: dict[str, Any]) -> None:
    validate_schema("source-records", source)
    window_start = parse_datetime(source["window_start"])
    window_end = parse_datetime(source["window_end"])
    if window_start >= window_end:
        raise SddFrlError(
            "SOURCE_RECORDS_INVALID_WINDOW",
            "window_start 必须早于 window_end。",
        )
    summary = source["collection_summary"]
    if set(summary) != set(SUMMARY_FIELDS):
        raise SddFrlError(
            "SOURCE_RECORDS_SUMMARY_INVALID",
            "collection_summary 字段与冻结契约不一致。",
        )
    record_count = sum(
        len(conversation["records"])
        for conversation in source["conversations"]
    )
    if summary["records_in_window"] != record_count:
        raise SddFrlError(
            "SOURCE_RECORDS_COUNT_MISMATCH",
            "records_in_window 必须等于 conversations 中的记录总数。",
        )
    if summary["target_conversations_matched"] != len(source["conversations"]):
        raise SddFrlError(
            "SOURCE_RECORDS_COUNT_MISMATCH",
            "target_conversations_matched 必须等于 conversations 数量。",
        )
    reason = source["empty_reason"]
    if reason is not None and reason not in EMPTY_REASONS:
        raise SddFrlError("SOURCE_RECORDS_EMPTY_REASON_INVALID", str(reason))
    if record_count:
        if reason is not None:
            raise SddFrlError(
                "SOURCE_RECORDS_EMPTY_REASON_INVALID",
                "窗口内存在记录时 empty_reason 必须为 null。",
            )
    elif summary["target_conversations_matched"] == 0:
        if reason != "ANALYSIS_TARGET_CONVERSATIONS_NOT_FOUND":
            raise SddFrlError(
                "SOURCE_RECORDS_EMPTY_REASON_INVALID",
                "未匹配目标对话时必须使用 ANALYSIS_TARGET_CONVERSATIONS_NOT_FOUND。",
            )
    elif reason not in {
        "NO_EVENTS_IN_WINDOW",
        "EVENTS_IN_WINDOW_UNCOLLECTABLE",
    }:
        raise SddFrlError(
            "SOURCE_RECORDS_EMPTY_REASON_INVALID",
            "窗口空结果缺少确定性 empty_reason。",
        )

    conversation_ids: set[str] = set()
    for conversation in source["conversations"]:
        conversation_id = conversation["conversation_id"]
        if conversation_id in conversation_ids:
            raise SddFrlError(
                "SOURCE_RECORDS_CONVERSATION_DUPLICATE",
                f"对话 ID 重复：{conversation_id}。",
            )
        conversation_ids.add(conversation_id)
        if conversation["project_id"] != source["project_id"]:
            raise SddFrlError(
                "SOURCE_RECORDS_PROJECT_MISMATCH",
                f"对话 {conversation_id} 的 project_id 与采集包不一致。",
            )

        sequences: set[int] = set()
        previous_sequence: int | None = None
        tool_calls: set[str] = set()
        for record in conversation["records"]:
            if record["conversation_id"] != conversation_id:
                raise SddFrlError(
                    "SOURCE_RECORDS_CONVERSATION_MISMATCH",
                    "记录 conversation_id 与所属对话不一致。",
                )
            sequence = record["sequence"]
            if (
                sequence in sequences
                or previous_sequence is not None
                and sequence <= previous_sequence
            ):
                raise SddFrlError(
                    "SOURCE_RECORDS_SEQUENCE_INVALID",
                    f"对话 {conversation_id} 的 sequence 必须唯一且严格递增。",
                )
            sequences.add(sequence)
            previous_sequence = sequence

            timestamp = parse_datetime(record["timestamp"])
            if timestamp < window_start or timestamp >= window_end:
                raise SddFrlError(
                    "SOURCE_RECORDS_TIMESTAMP_OUTSIDE_WINDOW",
                    "记录 timestamp 位于半开窗口之外。",
                )
            hash_input = {
                key: record[key]
                for key in (
                    "conversation_id",
                    "timestamp",
                    "actor",
                    "sequence",
                    "event_type",
                    "call_id",
                    "source_location",
                    "content_or_reference",
                )
            }
            if hash_json(hash_input) != record["content_hash"]:
                raise SddFrlError(
                    "SOURCE_RECORDS_CONTENT_HASH_MISMATCH",
                    "content_hash 与规范记录内容不一致。",
                )

            event_type = record["event_type"]
            call_id = record["call_id"]
            if event_type == "message":
                if record["actor"] == "tool":
                    raise SddFrlError(
                        "SOURCE_RECORDS_EVENT_ACTOR_INVALID",
                        "message 事件不能使用 tool 角色。",
                    )
                if call_id is not None:
                    raise SddFrlError(
                        "SOURCE_RECORDS_CALL_ID_INVALID",
                        "message 事件不能包含 call_id。",
                    )
                continue
            if record["actor"] != "tool":
                raise SddFrlError(
                    "SOURCE_RECORDS_EVENT_ACTOR_INVALID",
                    "工具与产物事件必须使用 tool 角色。",
                )
            if not call_id:
                raise SddFrlError(
                    "SOURCE_RECORDS_CALL_ID_INVALID",
                    "工具与产物事件必须包含 call_id。",
                )
            if event_type == "tool_call":
                if call_id in tool_calls:
                    raise SddFrlError(
                        "SOURCE_RECORDS_TOOL_CALL_DUPLICATE",
                        f"工具调用 ID 重复：{call_id}。",
                    )
                tool_calls.add(call_id)
            elif call_id not in tool_calls:
                raise SddFrlError(
                    "SOURCE_RECORDS_TOOL_CALL_MISSING",
                    f"工具结果未关联更早的工具调用：{call_id}。",
                )


def validate_evidence(
    evidence: dict[str, Any],
    *,
    run: dict[str, Any],
    source: dict[str, Any],
) -> None:
    validate_source_records(source)
    validate_schema("evidence", evidence)
    params = run["parameters"]
    if evidence["run_id"] != run["run_id"] or evidence["project_id"] != params["project_id"]:
        raise SddFrlError("EVIDENCE_SCOPE_MISMATCH", "evidence 与 run 的运行范围不一致。")
    if (
        evidence["window_start"] != params["window_start"]
        or evidence["window_end"] != params["window_end"]
        or evidence["contract_revision"] != params["contract_revision"]
        or evidence["contract_bundle_hash"] != params["contract_bundle_hash"]
    ):
        raise SddFrlError("EVIDENCE_SCOPE_MISMATCH", "evidence 与 run 的契约或时间窗口不一致。")
    expected_conversations = [
        {
            "conversation_id": conversation["conversation_id"],
            "has_events_before_window": conversation["has_events_before_window"],
            "has_events_after_window": conversation["has_events_after_window"],
        }
        for conversation in source["conversations"]
    ]
    if evidence["conversations"] != expected_conversations:
        raise SddFrlError(
            "EVIDENCE_SOURCE_MISMATCH",
            "evidence 对话边界元数据与 source-records 不一致。",
        )
    source_records = [
        record
        for conversation in source["conversations"]
        for record in conversation["records"]
    ]
    if len(source_records) != len(evidence["records"]):
        raise SddFrlError("EVIDENCE_SOURCE_MISMATCH", "evidence 没有一对一覆盖原始记录。")
    evidence_ids: set[str] = set()
    canonical_by_hash: dict[str, str] = {}
    for expected, actual in zip(source_records, evidence["records"], strict=True):
        if actual["evidence_id"] in evidence_ids:
            raise SddFrlError("EVIDENCE_SOURCE_MISMATCH", "evidence_id 必须唯一。")
        evidence_ids.add(actual["evidence_id"])
        if actual["project_id"] != source["project_id"]:
            raise SddFrlError("EVIDENCE_SOURCE_MISMATCH", "evidence 记录项目不一致。")
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
        expected_duplicate = canonical_by_hash.get(actual["content_hash"])
        if actual["duplicate_of"] != expected_duplicate:
            raise SddFrlError(
                "EVIDENCE_SOURCE_MISMATCH",
                "duplicate_of 必须指向更早的同哈希规范记录。",
            )
        canonical_by_hash.setdefault(actual["content_hash"], actual["evidence_id"])


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

    tasks = {item["task_episode_id"]: item for item in findings["task_episodes"]}
    instances = {item["problem_instance_id"]: item for item in findings["problem_instances"]}
    for instance in findings["problem_instances"]:
        task = tasks.get(instance["task_episode_id"])
        if task is None:
            raise SddFrlError(
                "FINDINGS_TASK_REFERENCE_UNKNOWN",
                f"问题实例 {instance['problem_instance_id']} 引用了不存在的任务。",
            )
        if not set(instance["evidence_ids"]) <= valid_ids:
            raise SddFrlError(
                "FINDINGS_EVIDENCE_UNKNOWN",
                f"问题实例 {instance['problem_instance_id']} 引用了不存在的 evidence_id。",
            )
    eligible = set(findings["optimizer_eligible_cluster_ids"])
    for cluster in findings["issue_clusters"]:
        missing_ids = [
            item for item in cluster["problem_instance_ids"] if item not in instances
        ]
        if missing_ids:
            raise SddFrlError(
                "FINDINGS_CLUSTER_REFERENCE_UNKNOWN",
                f"问题簇 {cluster['issue_cluster_id']} 引用了不存在的问题实例。",
            )
        cluster_instances = [instances[item] for item in cluster["problem_instance_ids"]]
        task_ids = {item["task_episode_id"] for item in cluster_instances}
        evidence_ids = {
            evidence_id
            for item in cluster_instances
            for evidence_id in item["evidence_ids"]
        }
        if (
            set(cluster["task_episode_ids"]) != task_ids
            or cluster["instance_count"] != len(cluster_instances)
            or cluster["severity_total"] != sum(
                item["severity"] for item in cluster_instances
            )
            or set(cluster["evidence_ids"]) != evidence_ids
        ):
            raise SddFrlError(
                "FINDINGS_CLUSTER_MISMATCH",
                f"问题簇 {cluster['issue_cluster_id']} 的计数或引用与问题实例不一致。",
            )
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
