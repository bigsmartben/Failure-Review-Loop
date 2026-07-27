from __future__ import annotations

import shutil
import subprocess
import sys
from typing import Any

from .errors import SddFrlError


def _codex_executable() -> str:
    command = "codex.cmd" if sys.platform == "win32" else "codex"
    return shutil.which(command) or command


def probe_codex() -> dict[str, Any]:
    executable = _codex_executable()
    try:
        version = subprocess.run(
            [executable, "--version"],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise SddFrlError("CODEX_NOT_FOUND", "找不到 codex CLI。") from exc
    except OSError as exc:
        raise SddFrlError(
            "CODEX_PROBE_FAILED",
            f"无法启动 codex CLI：{exc}",
        ) from exc
    if version.returncode != 0:
        raise SddFrlError("CODEX_PROBE_FAILED", "Codex CLI 能力探测失败。")
    return {
        "codex_version": version.stdout.strip(),
        "capabilities": {
            "native_subagent_handoff": True,
            "nested_codex_exec": False,
        },
    }
