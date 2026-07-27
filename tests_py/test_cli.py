from __future__ import annotations

import json
import sys
from pathlib import Path

from sdd_frl.cli import main
from sdd_frl.workspace import init_workspace


def test_probe_reports_source_availability_and_target_sample(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    runner = tmp_path / "runner"
    target = tmp_path / "target"
    codex_home = tmp_path / "codex-home"
    sessions = codex_home / "sessions"
    runner.mkdir()
    target.mkdir()
    sessions.mkdir(parents=True)
    init_workspace(
        runner,
        timezone_name="Asia/Shanghai",
        analysis_target=target,
        analysis_project_id="target",
    )
    config_file = runner / ".sdd-frl/config.json"
    config = json.loads(config_file.read_text("utf-8"))
    config["codex_home"] = str(codex_home)
    config_file.write_text(json.dumps(config), encoding="utf-8")
    rows = [{
        "type": "session_meta",
        "payload": {
            "id": "target-conversation",
            "cwd": str(target),
            "projectId": None,
        },
    }]
    (sessions / "target.jsonl").write_text(
        "".join(f"{json.dumps(row)}\n" for row in rows),
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "argv", ["sdd-frl", "probe", str(runner)])

    assert main() == 0
    result = json.loads(capsys.readouterr().out)

    assert result["ready"] is True
    assert result["source"]["available"] is True
    assert result["source"]["target_binding_verified"] is True
    assert result["source"]["target_conversations_matched"] == 1
    assert result["blocker_codes"] == []
