from __future__ import annotations

import json
from pathlib import Path

import pytest

from sdd_frl.errors import SddFrlError
from sdd_frl.workspace import (
    init_workspace,
    inspect_agent_configuration,
    load_workspace,
)


def test_init_creates_unbound_local_runtime_contract(tmp_path: Path) -> None:
    project = tmp_path / "frl-test"
    project.mkdir()

    first = init_workspace(project, timezone_name="Asia/Shanghai")
    second = init_workspace(project, timezone_name="Asia/Shanghai")
    config = json.loads((project / ".sdd-frl/config.json").read_text("utf-8"))

    assert first["status"] == "initialized"
    assert second["status"] == "already_initialized"
    assert set(first) == {"status", "timezone", "created", "warnings"}
    assert set(config) == {
        "schema_version",
        "timezone",
        "runs_dir",
        "reports_dir",
        "codex_home",
    }
    assert config["schema_version"] == "2.0.0"
    assert not (project / "failure-review.project.json").exists()
    assert (project / ".codex/agents/sdd-frl-analyst.toml").is_file()
    assert (project / ".codex/agents/sdd-frl-optimizer.toml").is_file()
    assert (project / ".sdd-frl/contracts/findings.schema.json").is_file()
    assert (project / ".sdd-frl/contracts/proposal.schema.json").is_file()
    analyst_contract = (project / ".sdd-frl/contracts/analyst.md").read_text("utf-8")
    assert "`push`、`commit`、`PR`、`merge`" in analyst_contract
    assert "不得按工具、命令、阶段或 Git 操作机械切分任务" in analyst_contract
    assert load_workspace(project).root == project.resolve()


def test_generated_quickstart_is_exactly_three_user_steps(tmp_path: Path) -> None:
    project = tmp_path / "frl-test"
    project.mkdir()
    init_workspace(project, timezone_name="Asia/Shanghai")

    quickstart = (project / "quickstart.md").read_text("utf-8")
    prompt = (project / ".sdd-frl/automation/task-prompt.md").read_text("utf-8")

    assert quickstart.count("## ") == 3
    assert "sdd-frl init ." in quickstart
    assert (
        "请读取 `.sdd-frl/automation/task-prompt.md`，"
        "为以下分析目标创建一个独立的 FRL 定时任务。"
    ) in quickstart
    assert "分析目标：<目标项目绝对路径>" in quickstart
    assert quickstart.count("```text") == 1
    assert "probe" not in quickstart
    assert "绑定" not in quickstart
    assert "`target_path`（目标路径）：必填" in prompt
    assert "用户提供多个目标" in prompt
    assert "用户未提供时使用“每天”" in prompt
    assert "用户未提供时使用 `22:00`" in prompt
    assert 'sdd-frl prepare . --target "<TARGET_PATH>"' in prompt
    assert "确认卡只能展示分析目标、运行频率和运行时间" in prompt
    assert "不得展示当前目录、FRL 工作区" in prompt


def test_init_rejects_legacy_config_instead_of_migrating(tmp_path: Path) -> None:
    project = tmp_path / "frl-test"
    config_file = project / ".sdd-frl/config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text(
        json.dumps({"schema_version": "1.0.0", "project_id": "legacy"}),
        encoding="utf-8",
    )

    with pytest.raises(SddFrlError) as caught:
        init_workspace(project, timezone_name="Asia/Shanghai")

    assert caught.value.code == "LEGACY_WORKSPACE_UNSUPPORTED"
    assert json.loads(config_file.read_text("utf-8"))["schema_version"] == "1.0.0"


def test_init_preserves_custom_root_guides_and_prompt(tmp_path: Path) -> None:
    project = tmp_path / "frl-test"
    prompt_file = project / ".sdd-frl/automation/task-prompt.md"
    prompt_file.parent.mkdir(parents=True)
    (project / "README.md").write_text("custom readme", encoding="utf-8")
    (project / "quickstart.md").write_text("custom quickstart", encoding="utf-8")
    prompt_file.write_text("custom automation", encoding="utf-8")

    result = init_workspace(project, timezone_name="Asia/Shanghai")

    assert (project / "README.md").read_text("utf-8") == "custom readme"
    assert (project / "quickstart.md").read_text("utf-8") == "custom quickstart"
    assert prompt_file.read_text("utf-8") == "custom automation"
    assert len(result["warnings"]) == 3


def test_init_blocks_custom_agent_file_conflict(tmp_path: Path) -> None:
    project = tmp_path / "frl-test"
    agent = project / ".codex/agents/sdd-frl-analyst.toml"
    agent.parent.mkdir(parents=True)
    agent.write_text('name = "other"\n', encoding="utf-8")

    with pytest.raises(SddFrlError) as caught:
        init_workspace(project, timezone_name="Asia/Shanghai")

    assert caught.value.code == "FRL_AGENT_CONFLICT"


def test_agent_inspection_detects_disabled_native_agents(tmp_path: Path) -> None:
    project = tmp_path / "frl-test"
    project.mkdir()
    init_workspace(project, timezone_name="Asia/Shanghai")
    (project / ".codex/config.toml").write_text(
        "[agents]\nenabled = false\n",
        encoding="utf-8",
    )

    with pytest.raises(SddFrlError) as caught:
        inspect_agent_configuration(project)

    assert caught.value.code == "AGENTS_DISABLED"


def test_workspace_rejects_output_escape(tmp_path: Path) -> None:
    project = tmp_path / "frl-test"
    project.mkdir()
    init_workspace(project, timezone_name="Asia/Shanghai")
    config_file = project / ".sdd-frl/config.json"
    config = json.loads(config_file.read_text("utf-8"))
    config["reports_dir"] = "../outside"
    config_file.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(SddFrlError) as caught:
        load_workspace(project)

    assert caught.value.code == "WORKSPACE_PATH_ESCAPE"
