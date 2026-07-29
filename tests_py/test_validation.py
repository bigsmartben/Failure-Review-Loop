from __future__ import annotations

import json

import pytest

from sdd_frl.errors import COLLECTION_BLOCKER_CODES, SddFrlError
from sdd_frl.validation import (
    schema_errors,
    validate_findings,
    validate_source_records,
)


def test_packaged_schemas_are_available() -> None:
    valid = {
        "schema_version": "1.0.0",
        "run_id": "20260727T010000Z_test-project_a1b2c3",
        "attempt": 1,
        "status": "PENDING",
            "parameters": {
                "project_id": "test-project",
                "target_root": "C:/work/test-project",
            "window_start": "2026-07-26T00:00:00+08:00",
            "window_end": "2026-07-27T00:00:00+08:00",
            "timezone": "Asia/Shanghai",
            "contract_revision": "2026-07-24.contract-first.1",
            "contract_bundle_hash": f"sha256:{'0' * 64}",
            "improvement_target_ids": [],
            "improvement_targets": [],
            "target_set_hash": f"sha256:{'0' * 64}",
        },
        "created_at": "2026-07-27T01:00:00Z",
        "updated_at": "2026-07-27T01:00:00Z",
        "stages": {
            name: {
                "status": "pending",
                "started_at": None,
                "completed_at": None,
                "artifact": None,
            }
            for name in ("collector", "analyst", "metrics", "trend", "optimizer")
        },
        "failure": None,
    }
    assert schema_errors("run", json.loads(json.dumps(valid))) == []


def test_handoff_schema_requires_structured_agent_packet() -> None:
    valid = {
        "schema_version": "1.0.0",
        "run_id": "run-1",
        "status": "ANALYZING",
        "next_action": "SPAWN_ANALYST",
        "input_packet": {
            "stage": "analyst",
            "agent": "sdd_frl_analyst",
            "prompt": "C:/project/.sdd-frl/contracts/analyst.md",
            "input_files": {"run": "C:/project/.sdd-frl/runs/run-1/run.json"},
            "output_file": "C:/project/.sdd-frl/runs/run-1/agent-output/analyst.json",
        },
        "output_schema": "C:/project/.sdd-frl/contracts/findings.schema.json",
        "blocker_codes": [],
        "report": None,
    }
    invalid = {**valid, "input_packet": None}

    assert schema_errors("handoff", valid) == []
    assert schema_errors("handoff", invalid)


def test_resolved_divergence_requires_linked_alignment() -> None:
    run = {
        "run_id": "run-detail",
        "parameters": {"project_id": "project-detail"},
    }
    evidence = {
        "records": [
            {"evidence_id": "ev_user", "actor": "user"},
            {"evidence_id": "ev_agent", "actor": "assistant"},
            {"evidence_id": "ev_alignment", "actor": "user"},
        ]
    }
    task = {
        "task_episode_id": "task_detail",
        "conversation_id": "conversation-detail",
        "goal": "生成目标项目报告",
        "expected_outcome": "报告只分析目标项目",
        "start_sequence": 0,
        "end_sequence": 2,
        "context_status": "complete",
        "context_basis": "fully_observed",
        "boundary_evidence_ids": [],
        "outcome_status": "achieved",
        "outcome_basis": "verified_acceptance_criteria",
        "acceptance_criteria": [{
            "criterion_id": "criterion_report",
            "description": "报告对象是目标项目",
            "status": "passed",
            "verification_evidence_ids": ["ev_alignment"],
        }],
        "evidence_ids": ["ev_user", "ev_agent", "ev_alignment"],
        "outcome_evidence_ids": ["ev_alignment"],
        "interaction_events": [],
        "counts": {
            "turn_count": 3,
            "clarification_count": 0,
            "repeated_clarification_count": 0,
            "execution_attempt_count": 0,
            "rework_count": 0,
        },
        "execution_summary": ["首次报告对象错误，纠正后重新生成。"],
        "divergences": [{
            "divergence_id": "divergence_report_subject",
            "summary": "报告对象识别错误",
            "user_expectation": "分析目标项目",
            "agent_behavior": "分析了 E2E 验收",
            "status": "resolved",
            "root_cause": "Prompt 未区分目标与运行过程。",
            "optimization_target": "prompt",
            "optimization_direction": "固定使用运行参数中的目标。",
            "acceptance_check": "报告正文只描述目标项目。",
            "evidence_ids": ["ev_user", "ev_agent"],
        }],
        "alignments": [{
            "alignment_id": "alignment_report_subject",
            "divergence_id": "divergence_report_subject",
            "summary": "重新确认分析目标项目。",
            "resulting_action": "重新生成报告。",
            "evidence_ids": ["ev_alignment"],
        }],
        "facts": [],
        "inferences": [],
        "unknowns": [],
    }
    findings = {
        "schema_version": "1.0.0",
        "contract_revision": "2026-07-24.contract-first.1",
        "contract_bundle_hash": f"sha256:{'0' * 64}",
        "run_id": "run-detail",
        "project_id": "project-detail",
        "task_episodes": [task],
        "excluded_evidence": [],
        "problem_instances": [],
        "issue_clusters": [],
        "optimizer_eligible_cluster_ids": [],
    }

    validate_findings(findings, run=run, evidence=evidence)

    task["alignments"] = []
    with pytest.raises(SddFrlError) as caught:
        validate_findings(findings, run=run, evidence=evidence)
    assert caught.value.code == "FINDINGS_RESOLVED_WITHOUT_ALIGNMENT"


def test_source_records_schema_and_semantic_counts_are_frozen() -> None:
    valid = {
        "schema_version": "1.0.0",
        "source_kind": "local_codex_sessions_jsonl",
        "project_id": "harness",
        "window_start": "2026-07-26T00:00:00+08:00",
        "window_end": "2026-07-27T00:00:00+08:00",
        "empty_reason": "NO_EVENTS_IN_WINDOW",
        "collection_summary": {
            "session_files_scanned": 1,
            "target_conversations_matched": 1,
            "records_before_window": 1,
            "records_in_window": 0,
            "records_after_window": 0,
            "skipped_missing_meta": 0,
            "skipped_outside_target": 0,
            "skipped_uncollectable": 0,
        },
        "conversations": [{
            "conversation_id": "conversation-1",
            "project_id": "harness",
            "match_method": "target_cwd",
            "has_events_before_window": True,
            "has_events_after_window": False,
            "records": [],
        }],
    }
    invalid = json.loads(json.dumps(valid))
    invalid["collection_summary"]["records_in_window"] = 1

    assert schema_errors("source-records", valid) == []
    validate_source_records(valid)
    with pytest.raises(SddFrlError) as caught:
        validate_source_records(invalid)
    assert caught.value.code == "SOURCE_RECORDS_COUNT_MISMATCH"


def test_collection_blocker_registry_is_stable() -> None:
    assert COLLECTION_BLOCKER_CODES == {
        "CODEX_SOURCE_UNAVAILABLE",
        "TARGET_CONVERSATIONS_NOT_FOUND",
    }
