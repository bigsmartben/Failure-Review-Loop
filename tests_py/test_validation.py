from __future__ import annotations

import json

from sdd_frl.validation import schema_errors


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
