from __future__ import annotations

import json
from pathlib import Path

import pytest

from sdd_frl.errors import SddFrlError
from sdd_frl.workspace import init_workspace, load_workspace


def test_init_creates_workspace_contract_and_is_idempotent(tmp_path: Path) -> None:
    project = tmp_path / "My Product"
    project.mkdir()

    first = init_workspace(project, timezone_name="Asia/Shanghai")
    second = init_workspace(project, timezone_name="Asia/Shanghai")

    assert first["status"] == "initialized"
    assert first["project_id"] == "my-product"
    assert second["status"] == "already_initialized"
    assert json.loads((project / "failure-review.project.json").read_text("utf-8"))[
        "project_id"
    ] == "my-product"
    assert (project / ".sdd-frl/config.json").is_file()
    assert (project / ".sdd-frl/automation/task-prompt.md").is_file()
    assert (project / "docs/failure-review").is_dir()
    ignore = (project / ".gitignore").read_text("utf-8")
    assert ".sdd-frl/runs/" in ignore
    assert load_workspace(project).project_id == "my-product"


def test_init_rejects_marker_conflict(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "failure-review.project.json").write_text(
        json.dumps({"schema_version": "1.0.0", "project_id": "existing"}),
        encoding="utf-8",
    )

    with pytest.raises(SddFrlError, match="INIT_CONFLICT"):
        init_workspace(
            project,
            project_id="different",
            timezone_name="Asia/Shanghai",
        )


def test_workspace_rejects_output_escape(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    init_workspace(project, timezone_name="Asia/Shanghai")
    config_file = project / ".sdd-frl/config.json"
    config = json.loads(config_file.read_text("utf-8"))
    config["reports_dir"] = "../outside"
    config_file.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(SddFrlError, match="WORKSPACE_PATH_ESCAPE"):
        load_workspace(project)


def test_init_imports_only_local_legacy_targets(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "AGENTS.md").write_text("rules", encoding="utf-8")
    (project / "failure-review.project.json").write_text(
        json.dumps({"schema_version": "1.0.0", "project_id": "project"}),
        encoding="utf-8",
    )
    legacy = {
        "project_bindings": [{
            "project_id": "project",
            "roots": ["."],
            "improvement_target_ids": ["local", "external"],
            "conversation_ids": [],
        }],
        "improvement_targets": [
            {"id": "local", "type": "agents", "path": "AGENTS.md"},
            {"id": "external", "type": "prompt", "path": str(tmp_path / "outside.md")},
        ],
    }
    (project / "failure-review.config.json").write_text(
        json.dumps(legacy),
        encoding="utf-8",
    )

    result = init_workspace(project, timezone_name="Asia/Shanghai")
    config = json.loads((project / ".sdd-frl/config.json").read_text("utf-8"))

    assert [item["id"] for item in config["improvement_targets"]] == ["local"]
    assert result["warnings"] == ["未导入工作区外改进载体：external"]
