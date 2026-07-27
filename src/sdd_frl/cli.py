from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .agent import probe_codex
from .errors import SddFrlError
from .pipeline import run_review
from .resources import asset_path
from .validation import load_and_validate_file, schema_errors
from .workspace import init_workspace, load_workspace

KINDS = ("run", "evidence", "findings", "metrics", "trend", "proposal")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sdd-frl",
        description="Workspace-local Failure Review Loop",
    )
    parser.add_argument("--version", action="version", version=f"sdd-frl {__version__}")
    commands = parser.add_subparsers(dest="command")

    init = commands.add_parser("init", help="初始化目标工作区")
    init.add_argument("path", nargs="?", default=".")
    init.add_argument("--project-id")
    init.add_argument("--timezone")

    run = commands.add_parser("run", help="复盘目标工作区")
    run.add_argument("path", nargs="?", default=".")
    run.add_argument("--date", dest="review_date")
    run.add_argument("--window-start")
    run.add_argument("--window-end")
    run.add_argument("--project-id")
    run.add_argument("--run-id")

    probe = commands.add_parser("probe", help="检查工作区与 Codex CLI 能力")
    probe.add_argument("path", nargs="?", default=".")

    validate = commands.add_parser("validate", help="按 JSON Schema 校验产物")
    validate.add_argument("--kind", choices=KINDS, required=True)
    validate.add_argument("--file", required=True)

    commands.add_parser("validate-examples", help="校验内置 Schema 示例")
    return parser


def _print(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _validate_examples() -> int:
    examples = asset_path("examples", "run.valid.basic.json").parent
    failed = False
    results = []
    for file in sorted(examples.glob("*.json")):
        parts = file.name.split(".")
        if len(parts) < 4 or parts[0] not in KINDS or parts[1] not in {"valid", "invalid"}:
            continue
        value = json.loads(file.read_text(encoding="utf-8"))
        errors = schema_errors(parts[0], value)
        passed = (not errors) == (parts[1] == "valid")
        failed = failed or not passed
        results.append({
            "file": file.name,
            "expected": parts[1],
            "passed": passed,
        })
    _print({"passed": not failed, "examples": results})
    return 1 if failed else 0


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    try:
        if args.command == "init":
            _print(init_workspace(
                args.path,
                project_id=args.project_id,
                timezone_name=args.timezone,
            ))
            return 0
        if args.command == "run":
            result = run_review(
                args.path,
                review_date=args.review_date,
                window_start=args.window_start,
                window_end=args.window_end,
                project_id=args.project_id,
                run_id=args.run_id,
            )
            _print(result)
            return 1 if result["status"].startswith("FAILED_") else 0
        if args.command == "probe":
            workspace = load_workspace(args.path)
            result = probe_codex()
            result.update({
                "workspace": str(workspace.root),
                "project_id": workspace.project_id,
                "timezone": workspace.timezone,
            })
            _print(result)
            return 0
        if args.command == "validate":
            value = load_and_validate_file(args.kind, Path(args.file))
            _print({"valid": True, "kind": args.kind, "file": str(Path(args.file).resolve())})
            del value
            return 0
        if args.command == "validate-examples":
            return _validate_examples()
        parser.print_help()
        return 0
    except SddFrlError as error:
        print(f"[{error.code}] {error.message}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("[INTERRUPTED] 用户中断。", file=sys.stderr)
        return 130
