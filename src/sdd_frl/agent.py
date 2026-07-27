from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .errors import SddFrlError
from .io import write_text_atomic
from .resources import asset_path


def _reasoning_config(value: str) -> str:
    return f"model_reasoning_effort={json.dumps(value)}"


def run_codex_stage(
    *,
    stage: str,
    model: str,
    reasoning_effort: str,
    prompt_name: str,
    schema_name: str,
    input_files: dict[str, Path],
    output_file: Path,
    log_file: Path,
    workspace: Path,
) -> dict[str, Any]:
    base_prompt = asset_path("prompts", prompt_name).read_text(encoding="utf-8")
    runtime = "\n".join([
        "",
        "## 本次运行的只读文件",
        *[f"- {name}: {file.resolve()}" for name, file in input_files.items()],
        "",
        f"阶段：{stage}",
        "读取上述文件后直接返回契约 JSON。不要写入或修改任何文件。",
    ])
    prompt = f"{base_prompt}\n{runtime}\n"
    temporary = output_file.with_name(f".{output_file.name}.agent-output.tmp")
    args = [
        "codex",
        "--ask-for-approval",
        "never",
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--sandbox",
        "read-only",
        "--model",
        model,
        "--config",
        _reasoning_config(reasoning_effort),
        "--output-schema",
        str(asset_path("schemas", schema_name)),
        "--output-last-message",
        str(temporary),
        "--json",
        "--cd",
        str(workspace),
        "-",
    ]
    try:
        result = subprocess.run(
            args,
            cwd=workspace,
            input=prompt,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise SddFrlError("CODEX_NOT_FOUND", "找不到 codex CLI。") from exc
    write_text_atomic(
        log_file,
        "\n".join(filter(None, [
            json.dumps(
                {
                    "stage": stage,
                    "model": model,
                    "reasoning_effort": reasoning_effort,
                },
                ensure_ascii=False,
            ),
            result.stdout,
            result.stderr,
        ])),
    )
    if result.returncode != 0:
        raise SddFrlError(
            f"{stage.upper()}_PROCESS_FAILED",
            f"Codex 进程退出码 {result.returncode}；日志：{log_file}",
        )
    try:
        text = temporary.read_text(encoding="utf-8")
        value = json.loads(text)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise SddFrlError(
            f"{stage.upper()}_OUTPUT_INVALID",
            f"Codex 没有产生合法 JSON；日志：{log_file}",
        ) from exc
    write_text_atomic(output_file, text if text.endswith("\n") else f"{text}\n")
    temporary.unlink(missing_ok=True)
    return value


def probe_codex() -> dict[str, Any]:
    try:
        version = subprocess.run(
            ["codex", "--version"],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        help_result = subprocess.run(
            ["codex", "exec", "--help"],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise SddFrlError("CODEX_NOT_FOUND", "找不到 codex CLI。") from exc
    if version.returncode != 0 or help_result.returncode != 0:
        raise SddFrlError("CODEX_PROBE_FAILED", "Codex CLI 能力探测失败。")
    help_text = help_result.stdout
    return {
        "codex_version": version.stdout.strip(),
        "capabilities": {
            "output_schema": "--output-schema" in help_text,
            "output_last_message": "--output-last-message" in help_text,
            "model_flag": "--model" in help_text,
            "reasoning_config": "--config" in help_text,
        },
    }
