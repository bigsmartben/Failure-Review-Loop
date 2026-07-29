from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from sdd_frl.cli import main


def test_cli_init_succeeds_without_target_parameters(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    project = tmp_path / "frl-test"
    project.mkdir()
    monkeypatch.setattr(
        sys,
        "argv",
        ["sdd-frl", "init", str(project), "--timezone", "Asia/Shanghai"],
    )

    assert main() == 0
    result = json.loads(capsys.readouterr().out)
    config = json.loads((project / ".sdd-frl/config.json").read_text("utf-8"))

    assert result["status"] == "initialized"
    assert set(result) == {"status", "timezone", "created", "warnings"}
    assert set(config) == {
        "schema_version",
        "timezone",
        "runs_dir",
        "reports_dir",
        "codex_home",
    }


@pytest.mark.parametrize(
    "obsolete_flag",
    [
        "--analysis" + "-target",
        "--analysis" + "-project-id",
    ],
)
def test_cli_rejects_removed_init_parameters(
    tmp_path: Path,
    monkeypatch,
    obsolete_flag: str,
) -> None:
    project = tmp_path / "frl-test"
    project.mkdir()
    monkeypatch.setattr(
        sys,
        "argv",
        ["sdd-frl", "init", str(project), obsolete_flag, str(tmp_path)],
    )

    with pytest.raises(SystemExit) as caught:
        main()

    assert caught.value.code == 2


def test_cli_rejects_removed_probe_command(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["sdd-frl", "probe"])

    with pytest.raises(SystemExit) as caught:
        main()

    assert caught.value.code == 2
