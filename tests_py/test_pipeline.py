from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sdd_frl.pipeline import review_window, run_review
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

    result = run_review(project, review_date="2026-07-26")

    assert result["status"] == "COMPLETED_NO_TASKS"
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
