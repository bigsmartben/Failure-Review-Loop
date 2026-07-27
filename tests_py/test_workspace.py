from __future__ import annotations

import json
from pathlib import Path

import pytest

from sdd_frl.errors import SddFrlError
from sdd_frl.workspace import (
    _legacy_quickstart,
    _legacy_workspace_readme,
    init_workspace as _init_workspace,
    inspect_agent_configuration,
    load_workspace,
    slug,
)


def _analysis_target(path: Path) -> Path:
    return path.parent / f"{path.name}-analysis-target"


def init_workspace(path: str | Path, **kwargs):
    workspace = Path(path)
    if kwargs.get("analysis_target") is None:
        target = _analysis_target(workspace)
        target.mkdir(exist_ok=True)
        kwargs["analysis_target"] = target
        kwargs.setdefault("analysis_project_id", slug(workspace.name))
    return _init_workspace(path, **kwargs)


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
    assert "models" not in config
    assert config["analysis_target"] == {
        "workspace_root": str(_analysis_target(project).resolve()),
        "project_id": "my-product",
    }
    analyst_agent = (project / ".codex/agents/sdd-frl-analyst.toml").read_text("utf-8")
    optimizer_agent = (project / ".codex/agents/sdd-frl-optimizer.toml").read_text("utf-8")
    assert 'name = "sdd_frl_analyst"' in analyst_agent
    assert 'model = "gpt-5.6-sol"' in analyst_agent
    assert 'model_reasoning_effort = "high"' in analyst_agent
    assert 'sandbox_mode = "read-only"' in analyst_agent
    assert 'name = "sdd_frl_optimizer"' in optimizer_agent
    assert 'model_reasoning_effort = "medium"' in optimizer_agent
    assert (project / ".sdd-frl/contracts/findings.schema.json").is_file()
    assert (project / ".sdd-frl/contracts/proposal.schema.json").is_file()
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
    assert "sdd-frl-my-product" in prompt
    assert "每天 09:00" in prompt
    assert "Asia/Shanghai" in prompt
    assert "SETUP_BLOCKED" in prompt
    assert "sdd-frl prepare ." in prompt
    assert "sdd_frl_analyst" in prompt
    assert "不得调用嵌套的 `codex exec`" in prompt
    assert "不得省略、原样传递或沿用上一次运行的值" in prompt
    assert (project / "docs/failure-review").is_dir()
    ignore = (project / ".gitignore").read_text("utf-8")
    assert ".sdd-frl/runs/" in ignore
    assert load_workspace(project).project_id == "my-product"


def test_init_separates_runner_workspace_from_analysis_target(tmp_path: Path) -> None:
    runner = tmp_path / "frl-runner"
    target = tmp_path / "harness"
    runner.mkdir()
    target.mkdir()

    result = init_workspace(
        runner,
        project_id="frl-runner",
        timezone_name="Asia/Shanghai",
        analysis_target=target,
        analysis_project_id="harness",
    )

    assert result["analysis_target"] == {
        "workspace_root": str(target.resolve()),
        "project_id": "harness",
    }
    config = json.loads((runner / ".sdd-frl/config.json").read_text("utf-8"))
    assert config["project_id"] == "frl-runner"
    assert config["analysis_target"] == result["analysis_target"]
    workspace = load_workspace(runner)
    assert workspace.root == runner.resolve()
    assert workspace.workspace_project_id == "frl-runner"
    assert workspace.analysis_root == target.resolve()
    assert workspace.project_id == "harness"
    prompt = (runner / ".sdd-frl/automation/task-prompt.md").read_text("utf-8")
    assert f"FRL 工作区：`{runner.resolve()}`" in prompt
    assert f"分析目标：`{target.resolve()}`" in prompt
    assert "名称：`sdd-frl-harness`" in prompt
    assert f"分析目标 `{target.resolve()}` 只读" in prompt
    assert not (target / ".sdd-frl").exists()


def test_reinit_preserves_configured_analysis_target_without_flag(
    tmp_path: Path,
) -> None:
    runner = tmp_path / "runner"
    target = tmp_path / "target"
    runner.mkdir()
    target.mkdir()
    init_workspace(
        runner,
        timezone_name="Asia/Shanghai",
        analysis_target=target,
        analysis_project_id="target-project",
    )

    result = _init_workspace(runner, timezone_name="Asia/Shanghai")
    config = json.loads((runner / ".sdd-frl/config.json").read_text("utf-8"))

    assert result["status"] == "already_initialized"
    assert result["project_id"] == "target-project"
    assert config["analysis_target"] == {
        "workspace_root": str(target.resolve()),
        "project_id": "target-project",
    }


def test_load_workspace_rejects_missing_analysis_target(tmp_path: Path) -> None:
    runner = tmp_path / "runner"
    target = tmp_path / "target"
    runner.mkdir()
    target.mkdir()
    init_workspace(runner, analysis_target=target)
    target.rmdir()

    with pytest.raises(SddFrlError) as caught:
        load_workspace(runner)

    assert caught.value.code == "ANALYSIS_TARGET_NOT_DIRECTORY"


def test_init_requires_a_distinct_analysis_target(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(SddFrlError) as missing:
        _init_workspace(workspace, timezone_name="Asia/Shanghai")
    with pytest.raises(SddFrlError) as same:
        _init_workspace(
            workspace,
            timezone_name="Asia/Shanghai",
            analysis_target=workspace,
        )

    assert missing.value.code == "ANALYSIS_TARGET_REQUIRED"
    assert same.value.code == "ANALYSIS_TARGET_MUST_DIFFER"


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


def test_init_removes_known_legacy_guides_even_with_custom_root_guides(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "README.md").write_text("product readme", encoding="utf-8")
    (project / "quickstart.md").write_text("product quickstart", encoding="utf-8")
    (project / ".sdd-frl").mkdir()
    (project / ".sdd-frl/README.md").write_text(
        _legacy_workspace_readme("project"),
        encoding="utf-8",
    )
    (project / ".sdd-frl/quickstart.md").write_text(
        _legacy_quickstart("0.3.0"),
        encoding="utf-8",
    )

    result = init_workspace(project, timezone_name="Asia/Shanghai")

    assert result["removed"] == [".sdd-frl/README.md", ".sdd-frl/quickstart.md"]
    assert not (project / ".sdd-frl/README.md").exists()
    assert not (project / ".sdd-frl/quickstart.md").exists()


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


def test_init_migrates_models_from_business_config_to_agent_toml(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    init_workspace(project, timezone_name="Asia/Shanghai")
    config_file = project / ".sdd-frl/config.json"
    config = json.loads(config_file.read_text("utf-8"))
    config["models"] = {
        "analyst": {"model": "custom-analyst", "reasoning_effort": "xhigh"},
        "optimizer": {"model": "custom-optimizer", "reasoning_effort": "low"},
    }
    config_file.write_text(json.dumps(config), encoding="utf-8")

    result = init_workspace(project, timezone_name="Asia/Shanghai")
    migrated = json.loads(config_file.read_text("utf-8"))

    assert "models" not in migrated
    assert ".sdd-frl/config.json (migrated)" in result["created"]
    analyst = (project / ".codex/agents/sdd-frl-analyst.toml").read_text("utf-8")
    optimizer = (project / ".codex/agents/sdd-frl-optimizer.toml").read_text("utf-8")
    assert 'model = "custom-analyst"' in analyst
    assert 'model_reasoning_effort = "xhigh"' in analyst
    assert 'model = "custom-optimizer"' in optimizer
    assert 'model_reasoning_effort = "low"' in optimizer


def test_init_blocks_custom_agent_file_conflict(tmp_path: Path) -> None:
    project = tmp_path / "project"
    agent = project / ".codex/agents/sdd-frl-analyst.toml"
    agent.parent.mkdir(parents=True)
    agent.write_text('name = "other"\n', encoding="utf-8")

    with pytest.raises(SddFrlError) as caught:
        init_workspace(project, timezone_name="Asia/Shanghai")

    assert caught.value.code == "FRL_AGENT_CONFLICT"


def test_probe_contract_detects_disabled_native_agents(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    init_workspace(project, timezone_name="Asia/Shanghai")
    config = project / ".codex/config.toml"
    config.write_text("[agents]\nenabled = false\n", encoding="utf-8")

    with pytest.raises(SddFrlError) as caught:
        inspect_agent_configuration(project)

    assert caught.value.code == "AGENTS_DISABLED"
