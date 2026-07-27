from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import SddFrlError


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SddFrlError("FILE_NOT_FOUND", f"找不到文件：{path}") from exc
    except json.JSONDecodeError as exc:
        raise SddFrlError(
            "INVALID_JSON",
            f"{path} 不是合法 JSON：第 {exc.lineno} 行第 {exc.colno} 列",
        ) from exc


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256(value: str | bytes) -> str:
    data = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def hash_json(value: Any) -> str:
    return f"sha256:{sha256(canonical_json(value))}"


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def write_json_atomic(path: Path, value: Any) -> None:
    write_text_atomic(path, f"{json.dumps(value, ensure_ascii=False, indent=2)}\n")


def ensure_within(workspace: Path, candidate: Path, code: str = "WORKSPACE_PATH_ESCAPE") -> Path:
    root = workspace.resolve()
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SddFrlError(code, f"路径越出工作区：{resolved}") from exc
    return resolved


def relative_posix(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()
