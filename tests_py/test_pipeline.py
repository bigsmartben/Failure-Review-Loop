from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from sdd_frl.errors import SddFrlError
from sdd_frl.pipeline import (
    continue_review,
    finalize_review,
    prepare_review,
    review_window,
)
from sdd_frl.report import publish_report
from sdd_frl.workspace import init_workspace, load_workspace


def test_review_window_uses_previous_complete_local_day() -> None:
    start, end, selected = review_window(
        "Asia/Shanghai",
        now=datetime(2026, 7, 27, 2, 0, tzinfo=timezone.utc),
    )
    assert selected == "2026-07-26"
    assert start == "2026-07-26T00:00:00+08:00"
    assert end == "2026-07-27T00:00:00+08:00"


def test_empty_run_stays_in_workspace_and_publishes_date(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "product"
    codex_home = tmp_path / "codex-home"
    (codex_home / "sessions").mkdir(parents=True)
    project.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    init_workspace(project, timezone_name="Asia/Shanghai")

    prepared = prepare_review(project, review_date="2026-07-26")
    assert prepared["next_action"] == "FINALIZE"
    assert prepared["report"] is None

    result = finalize_review(project, run_id=prepared["run_id"])

    assert result["status"] == "COMPLETED_NO_TASKS"
    assert result["next_action"] == "STOP"
    final_report = project / "docs/failure-review/2026-07-26.md"
    assert Path(result["report"]) == final_report
    assert final_report.is_file()
    assert "project_id: product" in final_report.read_text("utf-8")
    run_dir = project / ".sdd-frl/runs" / result["run_id"]
    for name in (
        "run.json",
        "source-records.json",
        "evidence.json",
        "findings.json",
        "metrics.json",
        "trend.json",
        "report.md",
    ):
        assert (run_dir / name).is_file()
    assert json.loads((run_dir / "run.json").read_text("utf-8"))["status"] == (
        "COMPLETED_NO_TASKS"
    )


def test_native_analyst_handoff_validates_output_and_finalizes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "product"
    project.mkdir()
    init_workspace(project, timezone_name="Asia/Shanghai")

    def evidence_packet(source, *, run_id, contract_revision, contract_hash):
        del source
        return {
            "schema_version": "1.0.0",
            "contract_revision": contract_revision,
            "contract_bundle_hash": contract_hash,
            "run_id": run_id,
            "project_id": "product",
            "window_start": "2026-07-26T00:00:00+08:00",
            "window_end": "2026-07-27T00:00:00+08:00",
            "conversations": [],
            "records": [{
                "evidence_id": "ev_assistant_1",
                "conversation_id": "conversation-1",
                "project_id": "product",
                "timestamp": "2026-07-26T01:00:00+08:00",
                "actor": "assistant",
                "sequence": 1,
                "event_type": "message",
                "call_id": None,
                "source_location": "fixture",
                "content_or_reference": "done",
                "content_hash": f"sha256:{'0' * 64}",
                "collection_status": "collected",
                "duplicate_of": None,
            }],
        }

    monkeypatch.setattr("sdd_frl.pipeline.build_evidence", evidence_packet)
    monkeypatch.setattr("sdd_frl.pipeline.validate_evidence", lambda *args, **kwargs: None)

    prepared = prepare_review(project, review_date="2026-07-26")

    assert prepared["next_action"] == "SPAWN_ANALYST"
    assert prepared["input_packet"]["agent"] == "sdd_frl_analyst"
    output = Path(prepared["input_packet"]["output_file"])
    run = json.loads(
        (project / ".sdd-frl/runs" / prepared["run_id"] / "run.json").read_text("utf-8")
    )
    findings = {
        "schema_version": "1.0.0",
        "contract_revision": run["parameters"]["contract_revision"],
        "contract_bundle_hash": run["parameters"]["contract_bundle_hash"],
        "run_id": run["run_id"],
        "project_id": "product",
        "task_episodes": [],
        "excluded_evidence": [],
        "problem_instances": [],
        "issue_clusters": [],
        "optimizer_eligible_cluster_ids": [],
    }
    output.write_text(json.dumps(findings), encoding="utf-8")

    continued = continue_review(
        project,
        run_id=prepared["run_id"],
        stage="analyst",
        input_file=output,
    )
    final = finalize_review(project, run_id=prepared["run_id"])

    assert continued["next_action"] == "FINALIZE"
    assert continued["status"] == "COMPLETED_NO_TASKS"
    assert final["next_action"] == "STOP"
    assert Path(final["report"]).is_file()


def test_continue_rejects_out_of_order_stage(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "product"
    project.mkdir()
    init_workspace(project, timezone_name="Asia/Shanghai")
    monkeypatch.setattr(
        "sdd_frl.pipeline.build_evidence",
        lambda source, *, run_id, contract_revision, contract_hash: {
            "schema_version": "1.0.0",
            "contract_revision": contract_revision,
            "contract_bundle_hash": contract_hash,
            "run_id": run_id,
            "project_id": "product",
            "window_start": "2026-07-26T00:00:00+08:00",
            "window_end": "2026-07-27T00:00:00+08:00",
            "conversations": [],
            "records": [{"actor": "assistant"}],
        },
    )
    monkeypatch.setattr("sdd_frl.pipeline.validate_evidence", lambda *args, **kwargs: None)
    prepared = prepare_review(project, review_date="2026-07-26")
    wrong_output = (
        project / ".sdd-frl/runs" / prepared["run_id"] / "agent-output/optimizer.json"
    )
    wrong_output.write_text("{}", encoding="utf-8")

    with pytest.raises(SddFrlError) as caught:
        continue_review(
            project,
            run_id=prepared["run_id"],
            stage="optimizer",
            input_file=wrong_output,
        )

    assert caught.value.code == "STAGE_ORDER_INVALID"


def test_continue_stops_on_agent_run_identity_mismatch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "product"
    project.mkdir()
    init_workspace(project, timezone_name="Asia/Shanghai")
    monkeypatch.setattr(
        "sdd_frl.pipeline.build_evidence",
        lambda source, *, run_id, contract_revision, contract_hash: {
            "schema_version": "1.0.0",
            "contract_revision": contract_revision,
            "contract_bundle_hash": contract_hash,
            "run_id": run_id,
            "project_id": "product",
            "window_start": "2026-07-26T00:00:00+08:00",
            "window_end": "2026-07-27T00:00:00+08:00",
            "conversations": [],
            "records": [{"actor": "assistant"}],
        },
    )
    monkeypatch.setattr("sdd_frl.pipeline.validate_evidence", lambda *args, **kwargs: None)
    prepared = prepare_review(project, review_date="2026-07-26")
    output = Path(prepared["input_packet"]["output_file"])
    output.write_text(
        json.dumps({"run_id": "another-run", "project_id": "product"}),
        encoding="utf-8",
    )

    result = continue_review(
        project,
        run_id=prepared["run_id"],
        stage="analyst",
        input_file=output,
    )

    assert result["next_action"] == "STOP"
    assert result["blocker_codes"] == ["RUN_IDENTITY_MISMATCH"]
    assert result["status"] == "FAILED_FINDINGS_VALIDATION"


def test_failed_report_does_not_replace_success(tmp_path: Path) -> None:
    project = tmp_path / "product"
    project.mkdir()
    init_workspace(project, timezone_name="Asia/Shanghai")
    workspace = load_workspace(project)
    destination = workspace.reports_dir / "2026-07-26.md"
    destination.write_text(
        "---\nstatus: COMPLETED_WITH_METRICS\n---\n\nsuccess\n",
        encoding="utf-8",
    )
    failed = project / ".sdd-frl/runs/failure/report.md"
    failed.parent.mkdir(parents=True)
    failed.write_text("---\nstatus: FAILED_ANALYSIS\n---\n\nfailure\n", encoding="utf-8")

    path, published = publish_report(
        workspace=workspace,
        raw_report=failed,
        review_date="2026-07-26",
        status="FAILED_ANALYSIS",
    )

    assert path == destination
    assert published is False
    assert "success" in destination.read_text("utf-8")
