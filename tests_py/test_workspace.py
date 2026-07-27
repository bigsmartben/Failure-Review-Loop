from __future__ import annotations

import json
from pathlib import Path

import pytest

from sdd_frl.errors import SddFrlError
from sdd_frl.workspace import (
    _legacy_quickstart,
    _legacy_workspace_readme,
    init_workspace,
    load_workspace,
)


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
    config = json.loads((project / ".sdd-frl/config.json").read_text("utf-8"))
    assert config["models"]["optimizer"] == {
        "planned_name": "Sol",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "medium",
    }
    assert (project / "README.md").is_file()
    assert (project / "quickstart.md").is_file()
    assert not (project / ".sdd-frl/README.md").exists()
    assert not (project / ".sdd-frl/quickstart.md").exists()
    assert (project / ".sdd-frl/automation/task-prompt.md").is_file()
    readme = (project / "README.md").read_text("utf-8")
    assert "维护者（maintainer）" in readme
    assert "sdd-frl probe ." in readme
    assert "Asia/Shanghai" in readme
    assert "请读取当前项目的 `.sdd-frl/automation/task-prompt.md`" not in readme
    quickstart = (project / "quickstart.md").read_text("utf-8")
    assert "使用者第三步" in quickstart
    assert "复制、粘贴、发送" in quickstart
    assert "请读取当前项目的 `.sdd-frl/automation/task-prompt.md`" in quickstart
    assert "sdd-frl probe ." not in quickstart
    assert ".sdd-frl/runs/<run_id>/" not in quickstart
    assert quickstart.count("```text") == 1
    prompt = (project / ".sdd-frl/automation/task-prompt.md").read_text("utf-8")
    assert str(project.resolve()) in prompt
    assert "sdd-frl · my-product" in prompt
    assert "每天 09:00" in prompt
    assert "Asia/Shanghai" in prompt
    assert "SETUP_BLOCKED" in prompt
    assert (project / "docs/failure-review").is_dir()
    ignore = (project / ".gitignore").read_text("utf-8")
    assert ".sdd-frl/runs/" in ignore
    assert load_workspace(project).project_id == "my-product"


def test_init_moves_known_generated_guides_to_project_root(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".sdd-frl").mkdir()
    (project / ".sdd-frl/README.md").write_text(
        _legacy_workspace_readme("project"),
        encoding="utf-8",
    )
    (project / ".sdd-frl/quickstart.md").write_text(
        _legacy_quickstart(),
        encoding="utf-8",
    )

    result = init_workspace(project, timezone_name="Asia/Shanghai")

    assert (project / "README.md").is_file()
    assert (project / "quickstart.md").is_file()
    assert not (project / ".sdd-frl/README.md").exists()
    assert not (project / ".sdd-frl/quickstart.md").exists()
    assert result["removed"] == [
        ".sdd-frl/README.md",
        ".sdd-frl/quickstart.md",
    ]


def test_init_preserves_existing_root_guides(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "README.md").write_text("product readme", encoding="utf-8")
    (project / "quickstart.md").write_text("product quickstart", encoding="utf-8")

    result = init_workspace(project, timezone_name="Asia/Shanghai")

    assert (project / "README.md").read_text("utf-8") == "product readme"
    assert (project / "quickstart.md").read_text("utf-8") == "product quickstart"
    assert result["warnings"] == [
        "根目录 README.md 已存在，已保留且未覆盖。",
        "根目录 quickstart.md 已存在，已保留且未覆盖。",
    ]


def test_init_upgrades_the_legacy_generated_prompt(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    init_workspace(project, timezone_name="Asia/Shanghai")
    prompt_file = project / ".sdd-frl/automation/task-prompt.md"
    from sdd_frl.workspace import LEGACY_TASK_PROMPT

    prompt_file.write_text(LEGACY_TASK_PROMPT, encoding="utf-8")
    result = init_workspace(project, timezone_name="Asia/Shanghai")

    assert ".sdd-frl/automation/task-prompt.md (updated)" in result["created"]
    assert str(project.resolve()) in prompt_file.read_text("utf-8")


def test_init_preserves_a_custom_prompt(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    init_workspace(project, timezone_name="Asia/Shanghai")
    prompt_file = project / ".sdd-frl/automation/task-prompt.md"
    prompt_file.write_text("custom automation", encoding="utf-8")

    result = init_workspace(project, timezone_name="Asia/Shanghai")

    assert prompt_file.read_text("utf-8") == "custom automation"
    assert result["warnings"] == [
        "现有 .sdd-frl/automation/task-prompt.md 不是生成模板，已保留且未覆盖。"
    ]


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
