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
CONFIG_RELATIVE = Path(".sdd-frl/config.json")
TASK_PROMPT_RELATIVE = Path(".sdd-frl/automation/task-prompt.md")
ANALYST_AGENT_RELATIVE = Path(".codex/agents/sdd-frl-analyst.toml")
OPTIMIZER_AGENT_RELATIVE = Path(".codex/agents/sdd-frl-optimizer.toml")
README_RELATIVE = Path("README.md")
QUICKSTART_RELATIVE = Path("quickstart.md")

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

GENERATED_PROMPT_HEADER = "<!-- sdd-frl-generated: codex-automation-setup-v4 -->"
GENERATED_README_HEADER = "<!-- sdd-frl-generated: workspace-readme-v3 -->"
GENERATED_QUICKSTART_HEADER = "<!-- sdd-frl-generated: quickstart-v3 -->"
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


def _task_prompt(timezone_name: str) -> str:
    return f"""{GENERATED_PROMPT_HEADER}
# 请在 Codex App 中创建 FRL 定时任务

## 用户参数

你正在执行一次性设置，不是在运行复盘。

- `target_path`（目标路径）：必填，只能取自用户当前消息中的一个绝对路径。
  如果用户没有提供，或仍是 `<目标项目绝对路径>` 等占位符，必须询问用户并停止设置。
  不得从现有配置、历史任务、目录名称或对话内容猜测。
- 如果用户提供多个目标，必须要求用户只选择一个目标并停止设置。一个定时任务只能分析一个目标。
- `frequency`（运行频率）：可选；用户未提供时使用“每天”。
- `time`（运行时间）：可选；用户未提供时使用 `22:00`。
- 时区固定使用当前配置的本地时区 `{timezone_name}`，不要求用户输入。
- 当前项目目录是内部运行目录。不得询问用户，也不得在确认卡或完成回复中展示。

例如，以下用户消息已经提供全部必填参数：

```text
请创建 FRL 定时任务。
分析目标：C:\\work\\my-project
```

## 确认与创建

确认卡只能展示分析目标、运行频率和运行时间。
不得展示当前目录、FRL 工作区、运行位置、权限、内部项目 ID 或 Agent 配置。
只有用户确认后，才创建并启用定时任务（scheduled task / automation）。
定时任务必须使用当前本地项目，不使用 worktree。不得扫描目录来补全或猜测目标。

## 定时任务执行提示词

创建任务前，将下文中的 `<TARGET_PATH>` 替换为用户确认的目标绝对路径。
不得保留占位符。任务必须逐字保存替换后的执行提示词：

> 只在任务所属的当前本地项目根目录执行 CLI，只复盘目标 `<TARGET_PATH>`。
> 不得切换当前目录，不得访问或分析其他目标。
> 首先执行 `sdd-frl prepare . --target "<TARGET_PATH>"` 并解析返回的 handoff JSON。
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
> 所有候选输出、中间产物、锁和最终文档必须留在当前目录内；
> 目标 `<TARGET_PATH>` 只读。

创建完成后，只回复分析目标、运行频率、运行时间和启用状态。
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


def _workspace_readme(timezone_name: str) -> str:
    return f"""{GENERATED_README_HEADER}
# Failure Review Loop 维护说明

首次设置请让使用者直接打开 [quickstart.md](quickstart.md)。

## 运行契约

| 项目 | 固定值 |
|---|---|
| 默认执行时间 | 每天 22:00（`{timezone_name}`） |
| 运行宿主 | Codex App Scheduled Task |
| CLI 状态机 | `prepare → continue → finalize` |
| 复盘范围 | 最近一个完整自然日 |
| 最终报告 | `docs/failure-review/<project_id>/YYYY-MM-DD.md` |

每个定时任务只保存一个目标路径。目标在任务运行时通过 `prepare --target` 传入，
不会写入 `.sdd-frl/config.json`。数据源不可读或未找到目标对话时，本次运行如实失败。

## 文件职责

| 路径 | 用途 |
|---|---|
| `.sdd-frl/config.json` | 时区、数据源和输出位置 |
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
# Failure Review Loop 使用者快速开始

只做下面三步。

## 1. 安装

```powershell
uv tool install "sdd-frl @ git+ssh://git@github.com/bigsmartben/Failure-Review-Loop.git@v{__version__}"
```

## 2. 初始化当前本地目录

```powershell
sdd-frl init .
```

## 3. 在当前项目的 Codex 对话框输入

```text
请读取 `.sdd-frl/automation/task-prompt.md`，为以下分析目标创建一个独立的 FRL 定时任务。

分析目标：<目标项目绝对路径>
```
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
    config: dict[str, Any]
    timezone: str
    runs_dir: Path
    reports_dir: Path
    locks_dir: Path


def slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")[:63]
    if not PROJECT_ID_PATTERN.fullmatch(result):
        raise SddFrlError(
            "INVALID_PROJECT_ID",
            f"无法从目标目录名 {value!r} 生成运行项目 ID。",
        )
    return result


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


def _workspace_config(
    timezone_name: str,
) -> dict[str, Any]:
    return {
        "schema_version": "2.0.0",
        "timezone": timezone_name,
        "runs_dir": ".sdd-frl/runs",
        "reports_dir": "docs/failure-review",
        "codex_home": None,
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


def init_workspace(
    path: str | Path,
    *,
    timezone_name: str | None = None,
) -> dict[str, Any]:
    root = Path(path).expanduser()
    if not root.exists() or not root.is_dir():
        raise SddFrlError("INIT_TARGET_NOT_DIRECTORY", f"初始化目标不是目录：{root}")
    root = root.resolve()
    timezone_value = detect_timezone(timezone_name)
    config_file = root / CONFIG_RELATIVE
    created: list[str] = []
    warnings: list[str] = []

    if config_file.exists():
        config = read_json(config_file)
        expected_keys = {
            "schema_version",
            "timezone",
            "runs_dir",
            "reports_dir",
            "codex_home",
        }
        if config.get("schema_version") != "2.0.0" or set(config) != expected_keys:
            raise SddFrlError(
                "LEGACY_WORKSPACE_UNSUPPORTED",
                "现有配置不属于当前无绑定模型；请移除旧配置后重新执行干净初始化。",
            )
        validate_timezone(config.get("timezone", ""))
    else:
        config = _workspace_config(
            timezone_value,
        )
        write_json_atomic(config_file, config)
        created.append(relative_posix(config_file, root))

    models = _agent_models(None)
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
        content=_workspace_readme(config["timezone"]),
        generated_header=GENERATED_README_HEADER,
        root=root,
        created=created,
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

    task_prompt = root / TASK_PROMPT_RELATIVE
    expected_prompt = _task_prompt(config["timezone"])
    if not task_prompt.exists():
        write_text_atomic(task_prompt, expected_prompt)
        created.append(relative_posix(task_prompt, root))
    else:
        existing_prompt = task_prompt.read_text(encoding="utf-8")
        if existing_prompt != expected_prompt and existing_prompt.startswith(
            GENERATED_PROMPT_HEADER
        ):
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
        "status": "initialized" if created else "already_initialized",
        "timezone": config["timezone"],
        "created": created,
        "warnings": warnings,
    }


def load_workspace(path: str | Path) -> Workspace:
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise SddFrlError("WORKSPACE_NOT_INITIALIZED", f"工作区不存在：{root}")
    config_file = root / CONFIG_RELATIVE
    if not config_file.exists():
        raise SddFrlError(
            "WORKSPACE_NOT_INITIALIZED",
            f"{root} 尚未初始化；请先运行 sdd-frl init {json.dumps(str(root))}。",
        )
    config = read_json(config_file)
    expected_keys = {
        "schema_version",
        "timezone",
        "runs_dir",
        "reports_dir",
        "codex_home",
    }
    if config.get("schema_version") != "2.0.0" or set(config) != expected_keys:
        raise SddFrlError(
            "LEGACY_WORKSPACE_UNSUPPORTED",
            "现有配置不属于当前无绑定模型；请移除旧配置后重新执行干净初始化。",
        )
    timezone_name = validate_timezone(config.get("timezone", ""))
    runs_dir = ensure_within(root, root / config.get("runs_dir", ".sdd-frl/runs"))
    reports_dir = ensure_within(root, root / config.get("reports_dir", "docs/failure-review"))
    locks_dir = ensure_within(root, root / ".sdd-frl/locks")
    return Workspace(
        root=root,
        config_file=config_file,
        config=config,
        timezone=timezone_name,
        runs_dir=runs_dir,
        reports_dir=reports_dir,
        locks_dir=locks_dir,
    )
