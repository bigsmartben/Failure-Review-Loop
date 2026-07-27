from __future__ import annotations

import json

import pytest

from sdd_frl.errors import COLLECTION_BLOCKER_CODES, SddFrlError
from sdd_frl.validation import schema_errors, validate_source_records


def test_packaged_schemas_are_available() -> None:
    valid = {
        "schema_version": "1.0.0",
        "run_id": "20260727T010000Z_test-project_a1b2c3",
        "attempt": 1,
        "status": "PENDING",
        "parameters": {
            "project_id": "test-project",
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
            "binding_method": "analysis_target_workspace_root",
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
        "ANALYSIS_TARGET_CONVERSATIONS_NOT_FOUND",
    }
