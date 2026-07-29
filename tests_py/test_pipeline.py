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


def configure_target_session(
    project: Path,
    *,
    timestamps: tuple[str, ...] = ("2026-07-25T23:00:00+08:00",),
) -> Path:
    workspace = load_workspace(project)
    target = project.parent / "product"
    target.mkdir(exist_ok=True)
    codex_home = project.parent / f"{project.name}-codex-home"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    config = json.loads(workspace.config_file.read_text("utf-8"))
    config["codex_home"] = str(codex_home)
    workspace.config_file.write_text(json.dumps(config), encoding="utf-8")
    rows = [{
        "type": "session_meta",
        "payload": {
            "id": f"{project.name}-target-conversation",
            "cwd": str(target),
            "projectId": None,
        },
    }]
    rows.extend({
        "type": "response_item",
        "timestamp": timestamp,
        "payload": {
            "type": "message",
            "role": "user",
            "content": "fixture event",
        },
    } for timestamp in timestamps)
    (sessions / "target.jsonl").write_text(
        "".join(f"{json.dumps(row)}\n" for row in rows),
        encoding="utf-8",
    )
    return target


def test_review_window_uses_previous_complete_local_day() -> None:
    start, end, selected = review_window(
        "Asia/Shanghai",
        now=datetime(2026, 7, 27, 2, 0, tzinfo=timezone.utc),
    )
    assert selected == "2026-07-26"
    assert start == "2026-07-26T00:00:00+08:00"
    assert end == "2026-07-27T00:00:00+08:00"


def test_two_runtime_targets_create_isolated_runs_and_reports(tmp_path: Path) -> None:
    project = tmp_path / "runner"
    target_a = tmp_path / "product-a"
    target_b = tmp_path / "product-b"
    codex_home = tmp_path / "codex-home"
    sessions = codex_home / "sessions"
    project.mkdir()
    target_a.mkdir()
    target_b.mkdir()
    sessions.mkdir(parents=True)
    init_workspace(project, timezone_name="Asia/Shanghai")
    config_file = project / ".sdd-frl/config.json"
    config = json.loads(config_file.read_text("utf-8"))
    config["codex_home"] = str(codex_home)
    config_file.write_text(json.dumps(config), encoding="utf-8")
    for name, target in (("a", target_a), ("b", target_b)):
        rows = [
            {
                "type": "session_meta",
                "payload": {"id": f"conversation-{name}", "cwd": str(target)},
            },
            {
                "type": "response_item",
                "timestamp": "2026-07-25T23:00:00+08:00",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": f"message-{name}",
                },
            },
        ]
        (sessions / f"{name}.jsonl").write_text(
            "".join(f"{json.dumps(row)}\n" for row in rows),
            encoding="utf-8",
        )

    prepared_a = prepare_review(project, target=target_a, review_date="2026-07-26")
    prepared_b = prepare_review(project, target=target_b, review_date="2026-07-26")
    final_a = finalize_review(project, run_id=prepared_a["run_id"])
    final_b = finalize_review(project, run_id=prepared_b["run_id"])
    run_a = json.loads(
        (project / ".sdd-frl/runs" / prepared_a["run_id"] / "run.json").read_text("utf-8")
    )
    run_b = json.loads(
        (project / ".sdd-frl/runs" / prepared_b["run_id"] / "run.json").read_text("utf-8")
    )

    assert run_a["parameters"]["target_root"] == str(target_a.resolve())
    assert run_b["parameters"]["target_root"] == str(target_b.resolve())
    assert final_a["report"] != final_b["report"]
    assert Path(final_a["report"]).parent.name == "product-a"
    assert Path(final_b["report"]).parent.name == "product-b"
    assert set(json.loads(config_file.read_text("utf-8"))) == {
        "schema_version",
        "timezone",
        "runs_dir",
        "reports_dir",
        "codex_home",
    }


def test_empty_run_stays_in_workspace_and_publishes_date(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "runner"
    codex_home = tmp_path / "codex-home"
    (codex_home / "sessions").mkdir(parents=True)
    project.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    init_workspace(project, timezone_name="Asia/Shanghai")
    target = configure_target_session(
        project,
        timestamps=(
            "2026-07-25T23:00:00+08:00",
            "2026-07-27T01:00:00+08:00",
        ),
    )

    prepared = prepare_review(project, target=target, review_date="2026-07-26")
    assert prepared["next_action"] == "FINALIZE"
    assert prepared["report"] is None

    result = finalize_review(project, run_id=prepared["run_id"])

    assert result["status"] == "COMPLETED_NO_TASKS"
    assert result["next_action"] == "STOP"
    final_report = project / "docs/failure-review/product/2026-07-26.md"
    assert Path(result["report"]) == final_report
    assert final_report.is_file()
    assert "project_id: product" in final_report.read_text("utf-8")
    report_text = final_report.read_text("utf-8")
    assert "目标对话存在，但该窗口无可分析事件" in report_text
    assert "窗口前 / 窗口内 / 窗口后记录：1 / 0 / 1" in report_text
    assert "结束时刻及之后" in report_text
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


def test_collection_failure_is_not_reported_as_no_tasks(tmp_path: Path) -> None:
    project = tmp_path / "runner"
    codex_home = tmp_path / "codex-home"
    (codex_home / "sessions").mkdir(parents=True)
    project.mkdir()
    init_workspace(project, timezone_name="Asia/Shanghai")
    config_file = project / ".sdd-frl/config.json"
    config = json.loads(config_file.read_text("utf-8"))
    config["codex_home"] = str(codex_home)
    config_file.write_text(json.dumps(config), encoding="utf-8")
    target = tmp_path / "product"
    target.mkdir()

    result = prepare_review(project, target=target, review_date="2026-07-26")

    assert result["status"] == "FAILED_COLLECTION"
    assert result["next_action"] == "STOP"
    assert result["blocker_codes"] == [
        "TARGET_CONVERSATIONS_NOT_FOUND"
    ]
    run_dir = project / ".sdd-frl/runs" / result["run_id"]
    source = json.loads((run_dir / "source-records.json").read_text("utf-8"))
    assert source["empty_reason"] == "TARGET_CONVERSATIONS_NOT_FOUND"
    assert "运行失败" in (run_dir / "report.md").read_text("utf-8")


def test_unavailable_source_returns_stable_collection_blocker(
    tmp_path: Path,
) -> None:
    project = tmp_path / "runner"
    project.mkdir()
    init_workspace(project, timezone_name="Asia/Shanghai")
    config_file = project / ".sdd-frl/config.json"
    config = json.loads(config_file.read_text("utf-8"))
    config["codex_home"] = str(tmp_path / "missing-codex-home")
    config_file.write_text(json.dumps(config), encoding="utf-8")
    target = tmp_path / "product"
    target.mkdir()

    result = prepare_review(project, target=target, review_date="2026-07-26")

    assert result["status"] == "FAILED_COLLECTION"
    assert result["blocker_codes"] == ["CODEX_SOURCE_UNAVAILABLE"]
    assert not (
        project
        / ".sdd-frl/runs"
        / result["run_id"]
        / "source-records.json"
    ).exists()


def test_native_analyst_handoff_validates_output_and_finalizes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "runner"
    project.mkdir()
    init_workspace(project, timezone_name="Asia/Shanghai")
    target = configure_target_session(project)

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

    prepared = prepare_review(project, target=target, review_date="2026-07-26")

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
    project = tmp_path / "runner"
    project.mkdir()
    init_workspace(project, timezone_name="Asia/Shanghai")
    target = configure_target_session(project)
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
    prepared = prepare_review(project, target=target, review_date="2026-07-26")
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
    project = tmp_path / "runner"
    project.mkdir()
    init_workspace(project, timezone_name="Asia/Shanghai")
    target = configure_target_session(project)
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
    prepared = prepare_review(project, target=target, review_date="2026-07-26")
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
    project = tmp_path / "runner"
    project.mkdir()
    init_workspace(project, timezone_name="Asia/Shanghai")
    workspace = load_workspace(project)
    destination = workspace.reports_dir / "product" / "2026-07-26.md"
    destination.parent.mkdir(parents=True)
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
        project_id="product",
        review_date="2026-07-26",
        status="FAILED_ANALYSIS",
    )

    assert path == destination
    assert published is False
    assert "success" in destination.read_text("utf-8")
