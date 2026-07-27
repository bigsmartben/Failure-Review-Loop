from __future__ import annotations

import json
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tzlocal import get_localzone_name

from . import __version__
from .errors import SddFrlError
from .io import ensure_within, read_json, relative_posix, write_json_atomic, write_text_atomic
from .resources import asset_path

PROJECT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
MARKER_NAME = "failure-review.project.json"
CONFIG_RELATIVE = Path(".sdd-frl/config.json")
TASK_PROMPT_RELATIVE = Path(".sdd-frl/automation/task-prompt.md")
ANALYST_AGENT_RELATIVE = Path(".codex/agents/sdd-frl-analyst.toml")
OPTIMIZER_AGENT_RELATIVE = Path(".codex/agents/sdd-frl-optimizer.toml")
README_RELATIVE = Path("README.md")
QUICKSTART_RELATIVE = Path("quickstart.md")
LEGACY_README_RELATIVE = Path(".sdd-frl/README.md")
LEGACY_QUICKSTART_RELATIVE = Path(".sdd-frl/quickstart.md")

DEFAULT_MODELS = {
    "analyst": {
        "planned_name": "Sol",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "high",
    },
    "optimizer": {
        "planned_name": "Sol",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "medium",
    },
}

LEGACY_TASK_PROMPT = """# sdd-frl 工作区定时任务

本任务只复盘它所绑定的当前工作区。不要切换到其他项目或工作区运行。

1. 确认当前目录存在 `.sdd-frl/config.json` 与 `failure-review.project.json`。
2. 执行 `sdd-frl run .`。CLI 会使用工作区配置的时区复盘最近一个完整自然日。
3. 打开命令返回的 `report` 路径并报告状态、目标达成率、执行效能和主要问题。
4. 失败时报告稳定错误码与 `.sdd-frl/runs/<run_id>/report.md`；不得把失败或空结果称为成功。
5. Optimizer 只生成提案，不应用、提交、发布或部署修改。

所有中间产物、锁和最终文档必须留在当前工作区内。
"""

GENERATED_PROMPT_HEADER = "<!-- sdd-frl-generated: codex-automation-setup-v2 -->"
LEGACY_GENERATED_PROMPT_HEADER = "<!-- sdd-frl-generated: codex-automation-setup-v1 -->"
GENERATED_README_HEADER = "<!-- sdd-frl-generated: workspace-readme-v2 -->"
GENERATED_QUICKSTART_HEADER = "<!-- sdd-frl-generated: quickstart-v2 -->"
GENERATED_AGENT_HEADER = "# sdd-frl-generated: native-agent-v1"
RUNTIME_CONTRACTS = (
    ("prompts", "analyst.md", "analyst.md"),
    ("prompts", "optimizer.md", "optimizer.md"),
    ("schemas", "findings.schema.json", "findings.schema.json"),
    ("schemas", "proposal.schema.json", "proposal.schema.json"),
    ("contracts", "deduplication.md", "deduplication.md"),
    ("contracts", "precedence.md", "precedence.md"),
    ("contracts", "issue-signatures.json", "issue-signatures.json"),
)


def _task_prompt(root: Path, project_id: str, timezone_name: str) -> str:
    return f"""{GENERATED_PROMPT_HEADER}
# 请在 Codex App 中创建工作区定时任务

## 设置契约

你正在执行一次性设置，不是在运行复盘。目标工作区固定为：

- 名称：`sdd-frl · {project_id}`
- 频率：每天 09:00
- 时区：`{timezone_name}`
- 目标工作区：`{root}`
- 运行位置：本地项目（local project），首期不得选择 worktree

创建前必须依次验证：

1. 当前项目绝对路径等于 `{root}`，并且 `.sdd-frl/config.json` 与
   `failure-review.project.json` 的 `project_id` 都是 `{project_id}`；
2. 当前项目已被 Codex 信任，项目级 `.codex/agents/` 配置已加载；
3. 可按名称调用 `sdd_frl_analyst` 和 `sdd_frl_optimizer` 两个原生
   subagent（子代理）；
4. 运行 `sdd-frl probe .`，结果中的 `ready` 为 `true`；
5. 定时任务具有当前工作区写权限。不得请求工作区外写入或网络权限。

任一验证失败时停止创建，回复对应稳定错误码：
`WORKSPACE_MISMATCH`、`PROJECT_NOT_TRUSTED`、`AGENT_CONFIG_UNAVAILABLE`、
`AGENTS_DISABLED`、`WORKSPACE_WRITE_REQUIRED` 或
`SCHEDULE_PERMISSION_DENIED`。不要猜测、修复或改绑其他项目。
如果用户要求改为 worktree，首期返回 `SETUP_BLOCKED`；若 `.codex/agents/`、
`.sdd-frl/contracts/` 或任务提示词尚未提交，同时报告
`WORKTREE_REQUIRES_COMMIT`。

验证通过后，先向用户展示名称、工作区、频率、时区、运行位置和权限的确认卡。
只有用户确认后，才创建并启用定时任务（scheduled task / automation）。

## 定时任务执行提示词

创建的任务必须逐字保存以下执行提示词：

> 只复盘目标工作区 `{root}`，不得切换到其他项目或工作区。
> 首先执行 `sdd-frl prepare .` 并解析返回的 handoff JSON。
> 只根据 `next_action` 执行下一步，不得从自然语言猜测阶段：
> - `SPAWN_ANALYST`：调用原生子代理 `sdd_frl_analyst`，把
>   `input_packet`、`output_schema` 和其中列出的只读文件交给它。
>   将子代理返回的纯 JSON 原样写入 `input_packet.output_file`，然后执行
>   `sdd-frl continue . --run-id <run_id> --stage analyst --input <output_file>`。
> - `SPAWN_OPTIMIZER`：同样调用 `sdd_frl_optimizer`，保存纯 JSON 后执行
>   `sdd-frl continue . --run-id <run_id> --stage optimizer --input <output_file>`。
> - `FINALIZE`：执行 `sdd-frl finalize . --run-id <run_id>`。
> - `STOP`：停止，不再调用任何下游阶段。
> 命令中的 `<run_id>` 与 `<output_file>` 是字段占位符：每次都必须分别替换为
> 当前 handoff 的 `run_id` 与 `input_packet.output_file`；不得省略、原样传递或沿用上一次运行的值。
> 每次 CLI 调用后都重新解析 handoff JSON，直到 `next_action` 为 `STOP`。
> 不得调用嵌套的 `codex exec`。不得跳过 CLI 的 JSON Schema 校验、阶段顺序校验
> 或运行身份校验。子代理不得修改文件；Optimizer 只返回提案。
> 最后打开 handoff 的 `report` 路径，报告状态、目标达成率、执行效能和主要问题。
> 失败时报告全部 `blocker_codes` 与 `.sdd-frl/runs/<run_id>/report.md`，
> 不得把失败、空输出或未完成状态称为成功。
> 所有候选输出、中间产物、锁和最终文档必须留在目标工作区内。

创建完成后，只回复任务名称、工作区、频率、时区、运行位置和启用状态。
如果当前环境不能创建定时任务，回复 `SETUP_BLOCKED` 和具体原因；不得声称任务已经创建。
"""


def _agent_toml(stage: str, model: dict[str, str]) -> str:
    if stage == "analyst":
        name = "sdd_frl_analyst"
        description = "FRL 问题分析器：只读取已校验证据并返回 findings 契约 JSON。"
        instructions = """
你的单一职责是执行 Failure Review Loop 的 analyst 阶段。
只读取父代理明确列在 input_packet 中的文件；不得读取原始会话、其他运行或改进载体。
以 input_packet.prompt 指向的阶段契约和 output_schema 指向的 JSON Schema 为准。
不得修改、创建或删除任何文件，不得调用其他代理，不得提出载体修改。
最终响应只能是一个符合 output_schema 的 JSON 对象，不附加 Markdown、解释或代码围栏。
如果输入不足，仍须按 Schema 表达 unknown 或 excluded evidence；不得伪造证据。
""".strip()
    else:
        name = "sdd_frl_optimizer"
        description = "FRL 优化提案器：只读分析合格问题簇并返回 proposal 契约 JSON。"
        instructions = """
你的单一职责是执行 Failure Review Loop 的 optimizer 阶段。
只读取父代理明确列在 input_packet 中的文件和锁定改进载体；不得读取其他运行或清单外文件。
以 input_packet.prompt 指向的阶段契约和 output_schema 指向的 JSON Schema 为准。
不得修改、创建或删除任何文件，不得调用其他代理，不得应用、提交、发布或部署提案。
最终响应只能是一个符合 output_schema 的 JSON 对象，不附加 Markdown、解释或代码围栏。
证据不足时使用 no_supported_target；不得猜测目标、位置或改动。
""".strip()
    return "\n".join([
        GENERATED_AGENT_HEADER,
        f'name = {json.dumps(name, ensure_ascii=False)}',
        f'description = {json.dumps(description, ensure_ascii=False)}',
        f'model = {json.dumps(model["model"])}',
        f'model_reasoning_effort = {json.dumps(model["reasoning_effort"])}',
        'sandbox_mode = "read-only"',
        'developer_instructions = """',
        instructions,
        '"""',
        "",
    ])


def _workspace_readme(project_id: str, timezone_name: str) -> str:
    return f"""{GENERATED_README_HEADER}
# Failure Review Loop 维护说明

本文供维护者（maintainer）检查和维护项目 `{project_id}` 的自动复盘。
首次设置请让使用者直接打开 [quickstart.md](quickstart.md)。

## 运行契约

| 项目 | 固定值 |
|---|---|
| 定时任务 | `sdd-frl · {project_id}` |
| 执行时间 | 每天 09:00（`{timezone_name}`） |
| 运行宿主 | Codex App Scheduled Task |
| CLI 状态机 | `prepare → continue → finalize` |
| 复盘范围 | 最近一个完整自然日 |
| 最终报告 | `docs/failure-review/YYYY-MM-DD.md` |

## 维护检查

```powershell
sdd-frl probe .
```

该命令应返回当前工作区、项目 ID、时区和 Codex CLI 能力。

## 文件职责

| 路径 | 用途 |
|---|---|
| `.sdd-frl/config.json` | 项目、时区和输出位置 |
| `.sdd-frl/automation/task-prompt.md` | 创建定时任务的权威提示词 |
| `.codex/agents/sdd-frl-analyst.toml` | Analyst 的模型、推理强度和只读边界 |
| `.codex/agents/sdd-frl-optimizer.toml` | Optimizer 的模型、推理强度和只读边界 |
| `.sdd-frl/runs/` | 每次复盘的证据、指标和日志 |
| `docs/failure-review/` | 给人阅读的最终报告 |

运行失败时查看命令返回的错误码和 `.sdd-frl/runs/<run_id>/report.md`。
失败结果不会覆盖同一天已有的成功报告。
"""


def _quickstart() -> str:
    return f"""{GENERATED_QUICKSTART_HEADER}
# 使用者第三步：复制、粘贴、发送

复制下面代码框里的整句话，粘贴到**当前项目**的 Codex 对话，然后发送。

```text
请读取当前项目的 `.sdd-frl/automation/task-prompt.md`，并严格按照文件内容创建定时任务。
```

确认卡中的工作区、频率、时区和“本地项目”无误后确认创建。
Codex 回复任务名称、工作区、频率、时区、运行位置和“已启用”，就完成了。
如果 Codex 返回 `SETUP_BLOCKED`，把原因交给维护者处理。
"""


def _legacy_workspace_readme(project_id: str) -> str:
    return f"""# sdd-frl

此目录属于项目 `{project_id}` 的 Failure Review Loop，不是项目源码目录。

- `config.json`：项目、时区、运行目录和报告目录配置。
- `quickstart.md`：用户仅需执行的三步操作。
- `automation/task-prompt.md`：完整复制到 Codex App 对话中的一次性设置提示词。
- `runs/`：每次复盘的证据、指标和日志。

最终文档位于 `../docs/failure-review/YYYY-MM-DD.md`。不要把任务绑定到其他工作区。
"""


def _legacy_quickstart(version: str | None = None) -> str:
    release = version or __version__
    return f"""# 三步完成 sdd-frl 设置

## 1. 安装

```powershell
uv tool install "sdd-frl @ git+ssh://git@github.com/bigsmartben/Failure-Review-Loop.git@v{release}"
```

## 2. 在目标项目初始化

```powershell
sdd-frl init .
```

## 3. 在 Codex App 创建定时任务

打开 `.sdd-frl/automation/task-prompt.md`，复制全文，在 Codex App 当前项目的对话中发送。

不需要手工执行 `probe`、`run` 或配置计划任务；Codex App 会按照提示词创建绑定到当前工作区的每日任务。任务内部执行 `sdd-frl run .`，不能绑定到中央 `Failure-Review-Loop` 运行器。
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
        "privacy": privacy,
    }


def _agent_models(value: Any) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    source = value if isinstance(value, dict) else {}
    for stage in ("analyst", "optimizer"):
        candidate = source.get(stage)
        if not isinstance(candidate, dict):
            candidate = {}
        model = candidate.get("model")
        effort = candidate.get("reasoning_effort")
        result[stage] = {
            "model": model if isinstance(model, str) and model else DEFAULT_MODELS[stage]["model"],
            "reasoning_effort": (
                effort
                if effort in {"low", "medium", "high", "xhigh", "max", "ultra"}
                else DEFAULT_MODELS[stage]["reasoning_effort"]
            ),
        }
    return result


def _ensure_agent_file(
    *,
    file: Path,
    content: str,
    root: Path,
    created: list[str],
) -> None:
    relative = relative_posix(file, root)
    if not file.exists():
        write_text_atomic(file, content)
        created.append(relative)
        return
    existing = file.read_text(encoding="utf-8")
    if existing == content:
        return
    if not existing.startswith(GENERATED_AGENT_HEADER):
        raise SddFrlError(
            "FRL_AGENT_CONFLICT",
            f"{relative} 已存在且不是 sdd-frl 生成文件；请先更名或移除冲突配置。",
        )
    write_text_atomic(file, content)
    created.append(f"{relative} (updated)")


def _sync_runtime_contracts(root: Path, created: list[str]) -> None:
    destination = root / ".sdd-frl/contracts"
    for group, source_name, target_name in RUNTIME_CONTRACTS:
        file = destination / target_name
        content = asset_path(group, source_name).read_text(encoding="utf-8")
        existed = file.exists()
        if existed and file.read_text(encoding="utf-8") == content:
            continue
        write_text_atomic(file, content)
        suffix = " (updated)" if existed else ""
        created.append(f"{relative_posix(file, root)}{suffix}")


def inspect_agent_configuration(root: Path) -> dict[str, Any]:
    project_config = root / ".codex/config.toml"
    if project_config.exists():
        try:
            parsed = tomllib.loads(project_config.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise SddFrlError(
                "AGENT_CONFIG_UNAVAILABLE",
                f"无法解析项目级 .codex/config.toml：{exc}",
            ) from exc
        agents = parsed.get("agents", {})
        if isinstance(agents, dict) and agents.get("enabled") is False:
            raise SddFrlError("AGENTS_DISABLED", "项目级 .codex/config.toml 禁用了原生子代理。")
        features = parsed.get("features", {})
        if isinstance(features, dict) and features.get("multi_agent") is False:
            raise SddFrlError(
                "AGENTS_DISABLED",
                "项目级 .codex/config.toml 禁用了 multi_agent 功能。",
            )

    expected = {
        "analyst": (root / ANALYST_AGENT_RELATIVE, "sdd_frl_analyst"),
        "optimizer": (root / OPTIMIZER_AGENT_RELATIVE, "sdd_frl_optimizer"),
    }
    result: dict[str, Any] = {}
    for stage, (file, expected_name) in expected.items():
        if not file.is_file():
            raise SddFrlError("AGENT_CONFIG_UNAVAILABLE", f"缺少 {relative_posix(file, root)}。")
        try:
            value = tomllib.loads(file.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise SddFrlError(
                "AGENT_CONFIG_UNAVAILABLE",
                f"无法解析 {relative_posix(file, root)}：{exc}",
            ) from exc
        required = ("name", "description", "developer_instructions", "model", "model_reasoning_effort")
        if value.get("name") != expected_name or any(not value.get(key) for key in required):
            raise SddFrlError(
                "AGENT_CONFIG_UNAVAILABLE",
                f"{relative_posix(file, root)} 不符合原生 Agent 配置契约。",
            )
        if value.get("sandbox_mode") != "read-only":
            raise SddFrlError(
                "AGENT_CONFIG_UNAVAILABLE",
                f"{expected_name} 必须使用 read-only sandbox。",
            )
        if value["model_reasoning_effort"] not in {
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
            "ultra",
        }:
            raise SddFrlError(
                "AGENT_CONFIG_UNAVAILABLE",
                f"{expected_name} 的 model_reasoning_effort 无效。",
            )
        result[stage] = {
            "name": expected_name,
            "model": value["model"],
            "reasoning_effort": value["model_reasoning_effort"],
            "file": str(file),
        }
    for group, source_name, target_name in RUNTIME_CONTRACTS:
        expected_content = asset_path(group, source_name).read_text(encoding="utf-8")
        contract = root / ".sdd-frl/contracts" / target_name
        if not contract.is_file() or contract.read_text(encoding="utf-8") != expected_content:
            raise SddFrlError(
                "AGENT_CONFIG_UNAVAILABLE",
                f".sdd-frl/contracts/{target_name} 缺失或与当前 CLI 契约不一致；请重新执行 init。",
            )
    return result


def _update_gitignore(root: Path) -> bool:
    gitignore = root / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    required = [line for line in GITIGNORE_BLOCK.splitlines() if line and not line.startswith("#")]
    if all(any(row.strip() == line for row in existing.splitlines()) for line in required):
        return False
    separator = "" if not existing or existing.endswith("\n") else "\n"
    write_text_atomic(gitignore, f"{existing}{separator}{GITIGNORE_BLOCK}")
    return True


def _ensure_generated_guide(
    *,
    file: Path,
    content: str,
    generated_header: str,
    root: Path,
    created: list[str],
    warnings: list[str],
) -> bool:
    relative = relative_posix(file, root)
    if not file.exists():
        write_text_atomic(file, content)
        created.append(relative)
        return True

    existing = file.read_text(encoding="utf-8")
    if existing == content:
        return True
    if existing.startswith(generated_header):
        write_text_atomic(file, content)
        created.append(f"{relative} (updated)")
        return True

    warnings.append(f"根目录 {relative} 已存在，已保留且未覆盖。")
    return False


def _remove_legacy_generated_guide(
    *,
    file: Path,
    legacy_content: str | tuple[str, ...],
    root: Path,
    removed: list[str],
    warnings: list[str],
) -> None:
    if not file.exists():
        return
    relative = relative_posix(file, root)
    known = (legacy_content,) if isinstance(legacy_content, str) else legacy_content
    if file.read_text(encoding="utf-8") not in known:
        warnings.append(f"现有 {relative} 不是旧版生成内容，已保留且未删除。")
        return
    file.unlink()
    removed.append(relative)


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
    removed: list[str] = []
    warnings: list[str] = []
    legacy_models: Any = None

    if config_file.exists():
        config = read_json(config_file)
        if config.get("project_id") != resolved_project:
            raise SddFrlError(
                "INIT_CONFLICT",
                f"现有配置属于 {config.get('project_id')}，标记属于 {resolved_project}。",
            )
        validate_timezone(config.get("timezone", ""))
        legacy_models = config.pop("models", None)
        if legacy_models is not None:
            write_json_atomic(config_file, config)
            created.append(f"{relative_posix(config_file, root)} (migrated)")
    else:
        legacy, warnings = _legacy_config(root, resolved_project)
        legacy_models = legacy.get("models")
        config = _workspace_config(root, resolved_project, timezone_value, legacy)
        write_json_atomic(config_file, config)
        created.append(relative_posix(config_file, root))

    if marker is None:
        write_json_atomic(
            marker_file,
            {"schema_version": "1.0.0", "project_id": resolved_project},
        )
        created.append(MARKER_NAME)

    models = _agent_models(legacy_models)
    _ensure_agent_file(
        file=root / ANALYST_AGENT_RELATIVE,
        content=_agent_toml("analyst", models["analyst"]),
        root=root,
        created=created,
    )
    _ensure_agent_file(
        file=root / OPTIMIZER_AGENT_RELATIVE,
        content=_agent_toml("optimizer", models["optimizer"]),
        root=root,
        created=created,
    )
    _sync_runtime_contracts(root, created)

    _ensure_generated_guide(
        file=root / README_RELATIVE,
        content=_workspace_readme(resolved_project, config["timezone"]),
        generated_header=GENERATED_README_HEADER,
        root=root,
        created=created,
        warnings=warnings,
    )
    _remove_legacy_generated_guide(
        file=root / LEGACY_README_RELATIVE,
        legacy_content=_legacy_workspace_readme(resolved_project),
        root=root,
        removed=removed,
        warnings=warnings,
    )

    _ensure_generated_guide(
        file=root / QUICKSTART_RELATIVE,
        content=_quickstart(),
        generated_header=GENERATED_QUICKSTART_HEADER,
        root=root,
        created=created,
        warnings=warnings,
    )
    _remove_legacy_generated_guide(
        file=root / LEGACY_QUICKSTART_RELATIVE,
        legacy_content=(
            _legacy_quickstart(),
            _legacy_quickstart("0.3.0"),
        ),
        root=root,
        removed=removed,
        warnings=warnings,
    )

    task_prompt = root / TASK_PROMPT_RELATIVE
    expected_prompt = _task_prompt(root, resolved_project, config["timezone"])
    if not task_prompt.exists():
        write_text_atomic(task_prompt, expected_prompt)
        created.append(relative_posix(task_prompt, root))
    else:
        existing_prompt = task_prompt.read_text(encoding="utf-8")
        generated_prompt = existing_prompt.startswith(
            (GENERATED_PROMPT_HEADER, LEGACY_GENERATED_PROMPT_HEADER)
        )
        legacy_prompt = existing_prompt.strip() == LEGACY_TASK_PROMPT.strip()
        if existing_prompt != expected_prompt and (generated_prompt or legacy_prompt):
            write_text_atomic(task_prompt, expected_prompt)
            created.append(f"{relative_posix(task_prompt, root)} (updated)")
        elif existing_prompt != expected_prompt:
            warnings.append(
                "现有 .sdd-frl/automation/task-prompt.md 不是生成模板，已保留且未覆盖。"
            )

    for directory in (
        root / config["runs_dir"],
        root / config["reports_dir"],
        root / ".sdd-frl/locks",
    ):
        ensure_within(root, directory).mkdir(parents=True, exist_ok=True)

    if _update_gitignore(root):
        created.append(".gitignore (updated)")

    return {
        "status": "initialized" if created or removed else "already_initialized",
        "workspace": str(root),
        "project_id": resolved_project,
        "timezone": config["timezone"],
        "created": created,
        "removed": removed,
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
