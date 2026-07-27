from __future__ import annotations

import pytest

from sdd_frl.agent import _codex_executable, probe_codex
from sdd_frl.errors import SddFrlError


def test_probe_reports_stable_error_when_codex_cannot_start(monkeypatch) -> None:
    def deny_start(*args, **kwargs):
        raise PermissionError(5, "拒绝访问")

    monkeypatch.setattr("sdd_frl.agent.subprocess.run", deny_start)

    with pytest.raises(SddFrlError) as caught:
        probe_codex()

    assert caught.value.code == "CODEX_PROBE_FAILED"
    assert "无法启动 codex CLI" in caught.value.message


def test_windows_uses_cmd_shim(monkeypatch) -> None:
    monkeypatch.setattr("sdd_frl.agent.sys.platform", "win32")
    monkeypatch.setattr(
        "sdd_frl.agent.shutil.which",
        lambda command: "C:/npm/codex.cmd" if command == "codex.cmd" else None,
    )

    assert _codex_executable() == "C:/npm/codex.cmd"
