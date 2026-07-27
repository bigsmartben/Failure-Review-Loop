from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tzlocal import get_localzone_name

from .errors import SddFrlError
from .io import ensure_within, read_json, relative_posix, write_json_atomic, write_text_atomic

PROJECT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
MARKER_NAME = "failure-review.project.json"
CONFIG_RELATIVE = Path(".sdd-frl/config.json")
TASK_PROMPT_RELATIVE = Path(".sdd-frl/automation/task-prompt.md")

DEFAULT_MODELS = {
    "analyst": {
        "planned_name": "Sol",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "high",
    },
    "optimizer": {
        "planned_name": "Sol",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "xhigh",
    },
}

TASK_PROMPT = """# sdd-frl 工作区定时任务

本任务只复盘它所绑定的当前工作区。不要切换到其他项目或工作区运行。

1. 确认当前目录存在 `.sdd-frl/config.json` 与 `failure-review.project.json`。
2. 执行 `sdd-frl run .`。CLI 会使用工作区配置的时区复盘最近一个完整自然日。
3. 打开命令返回的 `report` 路径并报告状态、目标达成率、执行效能和主要问题。
4. 失败时报告稳定错误码与 `.sdd-frl/runs/<run_id>/report.md`；不得把失败或空结果称为成功。
5. Optimizer 只生成提案，不应用、提交、发布或部署修改。

所有中间产物、锁和最终文档必须留在当前工作区内。
"""

GITIGNORE_BLOCK = """# sdd-frl runtime state
.sdd-frl/runs/
.sdd-frl/locks/
.sdd-frl/tmp/
"""


@dataclass(frozen=True)
class Workspace:
    root: Path
    config_file: Path
    marker_file: Path
    config: dict[str, Any]
    project_id: str
    timezone: str
    runs_dir: Path
    reports_dir: Path
    locks_dir: Path


def slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")[:63]
    if not PROJECT_ID_PATTERN.fullmatch(result):
        raise SddFrlError(
            "INVALID_PROJECT_ID",
            f"无法从 {value!r} 得到合法项目 ID；请使用 --project-id 指定。",
        )
    return result


def validate_project_id(value: str) -> str:
    if not PROJECT_ID_PATTERN.fullmatch(value):
        raise SddFrlError(
            "INVALID_PROJECT_ID",
            "项目 ID 只能包含小写字母、数字和连字符，长度不超过 63。",
        )
    return value


def validate_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise SddFrlError("TIMEZONE_REQUIRED", f"不是可用的 IANA 时区：{value}") from exc
    return value


def detect_timezone(explicit: str | None = None) -> str:
    if explicit:
        return validate_timezone(explicit)
    environment = os.environ.get("TZ")
    candidates = [environment] if environment else []
    try:
        candidates.append(get_localzone_name())
    except Exception:
        pass
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return validate_timezone(candidate)
        except SddFrlError:
            continue
    raise SddFrlError(
        "TIMEZONE_REQUIRED",
        "无法自动识别 IANA 时区；请重试并传入 --timezone，例如 Asia/Shanghai。",
    )


def _read_marker(marker_file: Path) -> dict[str, Any] | None:
    if not marker_file.exists():
        return None
    marker = read_json(marker_file)
    project_id = marker.get("project_id")
    if not isinstance(project_id, str):
        raise SddFrlError("INIT_CONFLICT", f"{marker_file} 缺少 project_id。")
    validate_project_id(project_id)
    return marker


def _relative_target(target: dict[str, Any], root: Path, legacy_dir: Path) -> dict[str, Any] | None:
    value = target.get("path")
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = legacy_dir / candidate
    try:
        resolved = ensure_within(root, candidate)
    except SddFrlError:
        return None
    return {
        "id": target.get("id"),
        "type": target.get("type"),
        "path": relative_posix(resolved, root),
    }


def _legacy_config(root: Path, project_id: str) -> tuple[dict[str, Any], list[str]]:
    legacy_file = root / "failure-review.config.json"
    if not legacy_file.exists():
        return {}, []
    legacy = read_json(legacy_file)
    warnings: list[str] = []
    matching = None
    for binding in legacy.get("project_bindings", []):
        if binding.get("project_id") != project_id:
            continue
        roots = binding.get("roots", [])
        matching_root = False
        for item in roots:
            if not isinstance(item, str):
                continue
            candidate = Path(item)
            if not candidate.is_absolute():
                candidate = legacy_file.parent / candidate
            try:
                matching_root = ensure_within(root, candidate) == root.resolve()
            except SddFrlError:
                matching_root = False
            if matching_root:
                break
        if matching_root:
            matching = binding
            break
    if matching is None:
        warnings.append("旧配置没有与当前工作区精确匹配的项目绑定，未导入。")
        return {}, warnings

    selected_ids = set(matching.get("improvement_target_ids", []))
    imported_targets = []
    for target in legacy.get("improvement_targets", []):
        if selected_ids and target.get("id") not in selected_ids:
            continue
        normalized = _relative_target(target, root, legacy_file.parent)
        if normalized is None:
            warnings.append(f"未导入工作区外改进载体：{target.get('id', '<unknown>')}")
        else:
            imported_targets.append(normalized)
    return {
        "models": legacy.get("models"),
        "privacy": legacy.get("privacy"),
        "codex_home": legacy.get("codex_home"),
        "conversation_ids": matching.get("conversation_ids", []),
        "improvement_targets": imported_targets,
    }, warnings


def _workspace_config(
    root: Path,
    project_id: str,
    timezone_name: str,
    legacy: dict[str, Any],
) -> dict[str, Any]:
    models = legacy.get("models")
    if isinstance(models, dict):
        models = {key: value for key, value in models.items() if key in {"analyst", "optimizer"}}
    if not models or "analyst" not in models or "optimizer" not in models:
        models = DEFAULT_MODELS
    privacy = legacy.get("privacy")
    if not isinstance(privacy, dict):
        privacy = {
            "content_mode": "redact_secrets",
            "retention_days": None,
            "copy_raw_conversations": False,
        }
    return {
        "schema_version": "1.0.0",
        "project_id": project_id,
        "workspace_root": ".",
        "timezone": timezone_name,
        "runs_dir": ".sdd-frl/runs",
        "reports_dir": "docs/failure-review",
        "codex_home": legacy.get("codex_home"),
        "conversation_ids": legacy.get("conversation_ids", []),
        "improvement_targets": legacy.get("improvement_targets", []),
        "models": models,
        "privacy": privacy,
    }


def _update_gitignore(root: Path) -> bool:
    gitignore = root / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    required = [line for line in GITIGNORE_BLOCK.splitlines() if line and not line.startswith("#")]
    if all(any(row.strip() == line for row in existing.splitlines()) for line in required):
        return False
    separator = "" if not existing or existing.endswith("\n") else "\n"
    write_text_atomic(gitignore, f"{existing}{separator}{GITIGNORE_BLOCK}")
    return True


def init_workspace(
    path: str | Path,
    *,
    project_id: str | None = None,
    timezone_name: str | None = None,
) -> dict[str, Any]:
    root = Path(path).expanduser()
    if not root.exists() or not root.is_dir():
        raise SddFrlError("INIT_TARGET_NOT_DIRECTORY", f"初始化目标不是目录：{root}")
    root = root.resolve()
    marker_file = root / MARKER_NAME
    marker = _read_marker(marker_file)
    marker_project = marker.get("project_id") if marker else None
    requested = validate_project_id(project_id) if project_id else None
    if marker_project and requested and marker_project != requested:
        raise SddFrlError(
            "INIT_CONFLICT",
            f"现有标记属于 {marker_project}，不能改为 {requested}。",
        )
    resolved_project = marker_project or requested or slug(root.name)
    timezone_value = detect_timezone(timezone_name)
    config_file = root / CONFIG_RELATIVE
    created: list[str] = []
    warnings: list[str] = []

    if config_file.exists():
        config = read_json(config_file)
        if config.get("project_id") != resolved_project:
            raise SddFrlError(
                "INIT_CONFLICT",
                f"现有配置属于 {config.get('project_id')}，标记属于 {resolved_project}。",
            )
        validate_timezone(config.get("timezone", ""))
    else:
        legacy, warnings = _legacy_config(root, resolved_project)
        config = _workspace_config(root, resolved_project, timezone_value, legacy)
        write_json_atomic(config_file, config)
        created.append(relative_posix(config_file, root))

    if marker is None:
        write_json_atomic(
            marker_file,
            {"schema_version": "1.0.0", "project_id": resolved_project},
        )
        created.append(MARKER_NAME)

    task_prompt = root / TASK_PROMPT_RELATIVE
    if not task_prompt.exists():
        write_text_atomic(task_prompt, TASK_PROMPT)
        created.append(relative_posix(task_prompt, root))

    for directory in (
        root / config["runs_dir"],
        root / config["reports_dir"],
        root / ".sdd-frl/locks",
    ):
        ensure_within(root, directory).mkdir(parents=True, exist_ok=True)

    if _update_gitignore(root):
        created.append(".gitignore (updated)")

    return {
        "status": "initialized" if created else "already_initialized",
        "workspace": str(root),
        "project_id": resolved_project,
        "timezone": config["timezone"],
        "created": created,
        "warnings": warnings,
    }


def load_workspace(path: str | Path) -> Workspace:
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise SddFrlError("WORKSPACE_NOT_INITIALIZED", f"工作区不存在：{root}")
    config_file = root / CONFIG_RELATIVE
    marker_file = root / MARKER_NAME
    if not config_file.exists() or not marker_file.exists():
        raise SddFrlError(
            "WORKSPACE_NOT_INITIALIZED",
            f"{root} 尚未初始化；请先运行 sdd-frl init {json.dumps(str(root))}。",
        )
    config = read_json(config_file)
    marker = _read_marker(marker_file)
    project_id = config.get("project_id")
    if not isinstance(project_id, str) or marker is None or marker["project_id"] != project_id:
        raise SddFrlError(
            "WORKSPACE_PROJECT_MISMATCH",
            "工作区配置与项目标记的 project_id 不一致。",
        )
    validate_project_id(project_id)
    timezone_name = validate_timezone(config.get("timezone", ""))
    runs_dir = ensure_within(root, root / config.get("runs_dir", ".sdd-frl/runs"))
    reports_dir = ensure_within(root, root / config.get("reports_dir", "docs/failure-review"))
    locks_dir = ensure_within(root, root / ".sdd-frl/locks")
    return Workspace(
        root=root,
        config_file=config_file,
        marker_file=marker_file,
        config=config,
        project_id=project_id,
        timezone=timezone_name,
        runs_dir=runs_dir,
        reports_dir=reports_dir,
        locks_dir=locks_dir,
    )
