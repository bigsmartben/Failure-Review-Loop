from __future__ import annotations

import json
import secrets
import shutil
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from zoneinfo import ZoneInfo

from .agent import run_codex_stage
from .errors import SddFrlError
from .io import (
    ensure_within,
    hash_json,
    read_json,
    sha256,
    utc_now,
    write_json_atomic,
    write_text_atomic,
)
from .metrics import build_metrics, build_trend
from .report import publish_report, render_report
from .resources import CONTRACT_REVISION, asset_path, contract_bundle_hash
from .source import build_evidence, collect_source_packet, parse_datetime
from .validation import (
    schema_errors,
    validate_evidence,
    validate_findings,
    validate_metrics,
    validate_proposal,
    validate_schema,
    validate_trend,
)
from .workspace import Workspace, load_workspace

STAGES = ("collector", "analyst", "metrics", "trend", "optimizer")
ARCHIVE_FILES = (
    "run.json",
    "source-records.json",
    "evidence.json",
    "findings.json",
    "metrics.json",
    "trend.json",
    "improvement-targets.json",
    "optimizer-evidence.json",
    "proposal.json",
    "report.md",
)


def create_run_id(project_id: str, now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    stamp = current.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}_{project_id}_{secrets.token_hex(3)}"


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def review_window(
    timezone_name: str,
    *,
    review_date: str | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
    now: datetime | None = None,
) -> tuple[str, str, str]:
    if bool(window_start) != bool(window_end):
        raise SddFrlError(
            "INVALID_REVIEW_DATE",
            "--window-start 与 --window-end 必须同时提供。",
        )
    zone = ZoneInfo(timezone_name)
    if window_start and window_end:
        try:
            start = parse_datetime(window_start)
            end = parse_datetime(window_end)
        except (TypeError, ValueError) as exc:
            raise SddFrlError("INVALID_REVIEW_DATE", "时间窗口必须是带时区的 ISO 时间。") from exc
        if start >= end:
            raise SddFrlError("INVALID_REVIEW_DATE", "时间窗口必须满足 start < end。")
        local_date = start.astimezone(zone).date().isoformat()
        if review_date and review_date != local_date:
            raise SddFrlError(
                "INVALID_REVIEW_DATE",
                "--date 必须等于窗口起点在配置时区中的自然日。",
            )
        return _iso(start), _iso(end), local_date
    try:
        selected = date.fromisoformat(review_date) if review_date else (
            (now or datetime.now(timezone.utc)).astimezone(zone).date() - timedelta(days=1)
        )
    except ValueError as exc:
        raise SddFrlError("INVALID_REVIEW_DATE", "日期格式必须是 YYYY-MM-DD。") from exc
    start = datetime.combine(selected, time.min, tzinfo=zone)
    end = datetime.combine(selected + timedelta(days=1), time.min, tzinfo=zone)
    return _iso(start), _iso(end), selected.isoformat()


def _empty_stage() -> dict[str, Any]:
    return {
        "status": "pending",
        "started_at": None,
        "completed_at": None,
        "artifact": None,
    }


def _new_run(run_id: str, parameters: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    return {
        "schema_version": "1.0.0",
        "run_id": run_id,
        "attempt": 1,
        "status": "PENDING",
        "parameters": parameters,
        "created_at": now,
        "updated_at": now,
        "stages": {stage: _empty_stage() for stage in STAGES},
        "failure": None,
    }


def _save_run(file: Path, run: dict[str, Any]) -> None:
    run["updated_at"] = utc_now()
    validate_schema("run", run)
    write_json_atomic(file, run)


def _stage_start(file: Path, run: dict[str, Any], stage: str, status: str) -> None:
    run["status"] = status
    run["stages"][stage] = {
        "status": "running",
        "started_at": utc_now(),
        "completed_at": None,
        "artifact": None,
    }
    _save_run(file, run)


def _stage_success(file: Path, run: dict[str, Any], stage: str, artifact: str) -> None:
    run["stages"][stage].update({
        "status": "succeeded",
        "completed_at": utc_now(),
        "artifact": artifact,
    })
    _save_run(file, run)


def _failure_details(error: Exception) -> tuple[str, str]:
    if isinstance(error, SddFrlError):
        return error.code, error.message
    return error.__class__.__name__.upper(), str(error)


def _fail(
    run_file: Path,
    raw_report: Path,
    run: dict[str, Any],
    *,
    status: str,
    stage: str,
    error: Exception,
    review_date: str,
) -> None:
    code, message = _failure_details(error)
    run["status"] = status
    run["failure"] = {"code": code, "message": message, "stage": stage}
    if stage in run["stages"]:
        run["stages"][stage].update({
            "status": "failed",
            "completed_at": utc_now(),
        })
    _save_run(run_file, run)
    write_text_atomic(
        raw_report,
        render_report(run=run, review_date=review_date),
    )


@contextmanager
def _project_lock(workspace: Workspace, run_id: str) -> Iterator[None]:
    lock = workspace.locks_dir / f"{workspace.project_id}.lock"
    try:
        lock.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise SddFrlError(
            "OVERLAPPING_RUN",
            f"项目 {workspace.project_id} 已有活动运行。",
        ) from exc
    write_json_atomic(lock / "owner.json", {"run_id": run_id, "acquired_at": utc_now()})
    try:
        yield
    finally:
        shutil.rmtree(lock, ignore_errors=True)


def _normalize_targets(workspace: Workspace) -> tuple[list[dict[str, Any]], dict[str, str]]:
    targets = []
    snapshots: dict[str, str] = {}
    ids: set[str] = set()
    paths: set[str] = set()
    for index, item in enumerate(workspace.config.get("improvement_targets", [])):
        if not isinstance(item, dict):
            raise SddFrlError(
                "IMPROVEMENT_TARGET_INVALID",
                f"improvement_targets[{index}] 必须是对象。",
            )
        target_id = item.get("id")
        target_type = item.get("type")
        if (
            not isinstance(target_id, str)
            or target_id in ids
            or target_type not in {"skill", "agents", "prompt", "script", "template"}
        ):
            raise SddFrlError("IMPROVEMENT_TARGET_INVALID", f"无效改进载体：{item}")
        candidate = Path(item.get("path", ""))
        if not candidate.is_absolute():
            candidate = workspace.root / candidate
        resolved = ensure_within(workspace.root, candidate)
        key = str(resolved).lower()
        if key in paths or not resolved.is_file():
            raise SddFrlError("IMPROVEMENT_TARGET_INVALID", f"无效改进载体路径：{resolved}")
        ids.add(target_id)
        paths.add(key)
        digest = sha256(resolved.read_bytes())
        targets.append({"id": target_id, "type": target_type, "path": str(resolved)})
        snapshots[target_id] = digest
    return targets, snapshots


def _target_manifest(
    run_id: str,
    targets: list[dict[str, Any]],
    snapshots: dict[str, str],
) -> dict[str, Any]:
    items = [
        {**target, "content_hash": f"sha256:{snapshots[target['id']]}"}
        for target in targets
    ]
    normalized = [
        {
            "id": item["id"],
            "type": item["type"],
            "path": item["path"],
            "content_hash": item["content_hash"],
        }
        for item in sorted(items, key=lambda value: value["id"])
    ]
    return {
        "schema_version": "1.0.0",
        "run_id": run_id,
        "target_set_hash": hash_json(normalized),
        "targets": items,
    }


def _assert_targets_unchanged(targets: list[dict[str, Any]], snapshots: dict[str, str]) -> None:
    for target in targets:
        if sha256(Path(target["path"]).read_bytes()) != snapshots[target["id"]]:
            raise SddFrlError(
                "IMPROVEMENT_TARGET_MUTATED",
                f"Optimizer 修改了只读载体 {target['id']}。",
            )


def _empty_findings(run: dict[str, Any]) -> dict[str, Any]:
    params = run["parameters"]
    return {
        "schema_version": "1.0.0",
        "contract_revision": params["contract_revision"],
        "contract_bundle_hash": params["contract_bundle_hash"],
        "run_id": run["run_id"],
        "project_id": params["project_id"],
        "task_episodes": [],
        "excluded_evidence": [],
        "problem_instances": [],
        "issue_clusters": [],
        "optimizer_eligible_cluster_ids": [],
    }


def _baseline_metrics(
    workspace: Workspace,
    *,
    current_run_id: str,
    project_id: str,
    target_ids: list[str],
    contract_hash: str,
    before: str,
) -> list[dict[str, Any]]:
    result = []
    for directory in sorted(workspace.runs_dir.iterdir(), reverse=True):
        if not directory.is_dir() or directory.name.startswith(".") or directory.name == current_run_id:
            continue
        try:
            run = read_json(directory / "run.json")
            metrics = read_json(directory / "metrics.json")
        except SddFrlError:
            continue
        if schema_errors("metrics", metrics):
            continue
        if (
            not run.get("status", "").startswith("COMPLETED_")
            or metrics.get("project_id") != project_id
            or sorted(metrics["target_scope"]["improvement_target_ids"]) != sorted(target_ids)
            or metrics["target_scope"]["contract_bundle_hash"] != contract_hash
            or parse_datetime(metrics["generated_at"]) >= parse_datetime(before)
        ):
            continue
        result.append(metrics)
    return sorted(
        result,
        key=lambda item: (parse_datetime(item["generated_at"]), item["run_id"]),
        reverse=True,
    )[:7]


def _archive_attempt(run_dir: Path, attempt: int) -> None:
    archive = run_dir / "attempts" / str(attempt)
    archive.mkdir(parents=True, exist_ok=True)
    for name in ARCHIVE_FILES:
        source = run_dir / name
        if source.exists():
            shutil.copy2(source, archive / name)


def _prepare_run(
    workspace: Workspace,
    *,
    run_id: str | None,
    parameters: dict[str, Any],
) -> tuple[dict[str, Any], Path]:
    resolved_id = run_id or create_run_id(workspace.project_id)
    run_dir = ensure_within(workspace.root, workspace.runs_dir / resolved_id)
    run_file = run_dir / "run.json"
    run_dir.mkdir(parents=True, exist_ok=True)
    if run_file.exists():
        run = read_json(run_file)
        if not run_id:
            raise SddFrlError("RUN_ID_COLLISION", resolved_id)
        if not run.get("status", "").startswith("FAILED_"):
            raise SddFrlError("RETRY_NOT_ALLOWED", "只能重试失败运行。")
        if run.get("parameters") != parameters:
            raise SddFrlError("RETRY_PARAMETER_MISMATCH", "重试必须保持锁定范围不变。")
        _archive_attempt(run_dir, run["attempt"])
        run["attempt"] += 1
        run["status"] = "PENDING"
        run["failure"] = None
        run["stages"] = {stage: _empty_stage() for stage in STAGES}
    else:
        run = _new_run(resolved_id, parameters)
    validate_schema("run", run)
    return run, run_dir


def _finalize(
    workspace: Workspace,
    *,
    run: dict[str, Any],
    run_dir: Path,
    review_date: str,
    findings: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    trend: dict[str, Any] | None = None,
    proposal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw_report = run_dir / "report.md"
    if not raw_report.exists() or not run["status"].startswith("FAILED_"):
        write_text_atomic(
            raw_report,
            render_report(
                run=run,
                review_date=review_date,
                findings=findings,
                metrics=metrics,
                trend=trend,
                proposal=proposal,
            ),
        )
    report, published = publish_report(
        workspace=workspace,
        raw_report=raw_report,
        review_date=review_date,
        status=run["status"],
    )
    return {
        "run_id": run["run_id"],
        "status": run["status"],
        "project_id": workspace.project_id,
        "review_date": review_date,
        "report": str(report),
        "raw_report": str(raw_report),
        "published": published,
    }


def run_review(
    path: str | Path,
    *,
    review_date: str | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
    project_id: str | None = None,
    run_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    workspace = load_workspace(path)
    if project_id and project_id != workspace.project_id:
        raise SddFrlError(
            "WORKSPACE_PROJECT_MISMATCH",
            f"参数项目 {project_id} 与工作区项目 {workspace.project_id} 不一致。",
        )
    start, end, selected_date = review_window(
        workspace.timezone,
        review_date=review_date,
        window_start=window_start,
        window_end=window_end,
        now=now,
    )
    contract_hash = contract_bundle_hash()
    targets, snapshots = _normalize_targets(workspace)
    pending_manifest = _target_manifest("pending", targets, snapshots)
    parameters = {
        "project_id": workspace.project_id,
        "window_start": start,
        "window_end": end,
        "timezone": workspace.timezone,
        "contract_revision": CONTRACT_REVISION,
        "contract_bundle_hash": contract_hash,
        "improvement_target_ids": [item["id"] for item in targets],
        "improvement_targets": targets,
        "target_set_hash": pending_manifest["target_set_hash"],
    }
    run, run_dir = _prepare_run(workspace, run_id=run_id, parameters=parameters)
    run_file = run_dir / "run.json"
    raw_report = run_dir / "report.md"
    _save_run(run_file, run)
    write_json_atomic(
        run_dir / "improvement-targets.json",
        _target_manifest(run["run_id"], targets, snapshots),
    )

    with _project_lock(workspace, run["run_id"]):
        try:
            _stage_start(run_file, run, "collector", "COLLECTING")
            source = collect_source_packet(workspace, start, end)
            write_json_atomic(run_dir / "source-records.json", source)
            evidence = build_evidence(
                source,
                run_id=run["run_id"],
                contract_revision=CONTRACT_REVISION,
                contract_hash=contract_hash,
            )
            run["status"] = "VALIDATING_EVIDENCE"
            _save_run(run_file, run)
            validate_evidence(evidence, run=run, source=source)
            write_json_atomic(run_dir / "evidence.json", evidence)
            _stage_success(run_file, run, "collector", "evidence.json")
        except Exception as error:
            _fail(
                run_file, raw_report, run,
                status="FAILED_COLLECTION",
                stage="collector",
                error=error,
                review_date=selected_date,
            )
            return _finalize(workspace, run=run, run_dir=run_dir, review_date=selected_date)

        try:
            _stage_start(run_file, run, "analyst", "ANALYZING")
            findings_file = run_dir / "findings.json"
            if evidence["records"]:
                models = workspace.config["models"]
                findings = run_codex_stage(
                    stage="analyst",
                    model=models["analyst"]["model"],
                    reasoning_effort=models["analyst"]["reasoning_effort"],
                    prompt_name="analyst.md",
                    schema_name="findings.schema.json",
                    input_files={
                        "run": run_file,
                        "evidence": run_dir / "evidence.json",
                        "deduplication_contract": asset_path("contracts", "deduplication.md"),
                        "contract_precedence": asset_path("contracts", "precedence.md"),
                        "issue_signatures": asset_path("contracts", "issue-signatures.json"),
                    },
                    output_file=findings_file,
                    log_file=run_dir / "logs" / f"analyst.attempt-{run['attempt']}.log",
                    workspace=workspace.root,
                )
            else:
                findings = _empty_findings(run)
                write_json_atomic(findings_file, findings)
            run["status"] = "VALIDATING_FINDINGS"
            _save_run(run_file, run)
            validate_findings(findings, run=run, evidence=evidence)
            _stage_success(run_file, run, "analyst", "findings.json")
        except Exception as error:
            _fail(
                run_file, raw_report, run,
                status="FAILED_FINDINGS_VALIDATION"
                if run["status"] == "VALIDATING_FINDINGS"
                else "FAILED_ANALYSIS",
                stage="analyst",
                error=error,
                review_date=selected_date,
            )
            return _finalize(workspace, run=run, run_dir=run_dir, review_date=selected_date)

        try:
            _stage_start(run_file, run, "metrics", "COMPUTING_METRICS")
            metrics = build_metrics(run=run, findings=findings, generated_at=utc_now())
            validate_metrics(metrics, metrics)
            write_json_atomic(run_dir / "metrics.json", metrics)
            _stage_success(run_file, run, "metrics", "metrics.json")
        except Exception as error:
            _fail(
                run_file, raw_report, run,
                status="FAILED_METRICS",
                stage="metrics",
                error=error,
                review_date=selected_date,
            )
            return _finalize(
                workspace,
                run=run,
                run_dir=run_dir,
                review_date=selected_date,
                findings=findings,
            )

        try:
            _stage_start(run_file, run, "trend", "COMPUTING_TREND")
            baseline = _baseline_metrics(
                workspace,
                current_run_id=run["run_id"],
                project_id=workspace.project_id,
                target_ids=parameters["improvement_target_ids"],
                contract_hash=contract_hash,
                before=metrics["generated_at"],
            )
            trend = build_trend(
                run=run,
                metrics=metrics,
                baseline=baseline,
                generated_at=utc_now(),
            )
            validate_trend(trend, trend)
            write_json_atomic(run_dir / "trend.json", trend)
            _stage_success(run_file, run, "trend", "trend.json")
        except Exception as error:
            _fail(
                run_file, raw_report, run,
                status="FAILED_TREND",
                stage="trend",
                error=error,
                review_date=selected_date,
            )
            return _finalize(
                workspace,
                run=run,
                run_dir=run_dir,
                review_date=selected_date,
                findings=findings,
                metrics=metrics,
            )

        run["status"] = "CHECKING_THRESHOLD"
        _save_run(run_file, run)
        proposal = None
        eligible = findings["optimizer_eligible_cluster_ids"]
        if not eligible:
            run["status"] = (
                "COMPLETED_NO_TASKS"
                if not findings["task_episodes"]
                else "COMPLETED_WITH_METRICS"
            )
            run["stages"]["optimizer"]["status"] = "skipped"
            _save_run(run_file, run)
        elif not targets:
            run["status"] = "COMPLETED_WITH_FINDINGS"
            run["stages"]["optimizer"]["status"] = "skipped"
            _save_run(run_file, run)
        else:
            try:
                _stage_start(run_file, run, "optimizer", "OPTIMIZING")
                needed = {
                    evidence_id
                    for cluster in findings["issue_clusters"]
                    if cluster["issue_cluster_id"] in set(eligible)
                    for evidence_id in cluster["evidence_ids"]
                }
                optimizer_evidence = {
                    **evidence,
                    "records": [
                        item for item in evidence["records"]
                        if item["evidence_id"] in needed
                    ],
                }
                write_json_atomic(run_dir / "optimizer-evidence.json", optimizer_evidence)
                inputs = {
                    "run": run_file,
                    "evidence": run_dir / "optimizer-evidence.json",
                    "findings": run_dir / "findings.json",
                    "improvement_targets": run_dir / "improvement-targets.json",
                }
                for index, target in enumerate(targets):
                    inputs[f"target_{index}_{target['id']}"] = Path(target["path"])
                models = workspace.config["models"]
                proposal = run_codex_stage(
                    stage="optimizer",
                    model=models["optimizer"]["model"],
                    reasoning_effort=models["optimizer"]["reasoning_effort"],
                    prompt_name="optimizer.md",
                    schema_name="proposal.schema.json",
                    input_files=inputs,
                    output_file=run_dir / "proposal.json",
                    log_file=run_dir / "logs" / f"optimizer.attempt-{run['attempt']}.log",
                    workspace=workspace.root,
                )
                _assert_targets_unchanged(targets, snapshots)
                run["status"] = "VALIDATING_PROPOSAL"
                _save_run(run_file, run)
                validate_proposal(proposal, run=run, findings=findings)
                _stage_success(run_file, run, "optimizer", "proposal.json")
                run["status"] = (
                    "COMPLETED_WITH_PROPOSAL"
                    if proposal["proposals"]
                    else "COMPLETED_WITH_FINDINGS"
                )
                _save_run(run_file, run)
            except Exception as error:
                _fail(
                    run_file, raw_report, run,
                    status="FAILED_PROPOSAL_VALIDATION"
                    if run["status"] == "VALIDATING_PROPOSAL"
                    else "FAILED_OPTIMIZATION",
                    stage="optimizer",
                    error=error,
                    review_date=selected_date,
                )
                return _finalize(
                    workspace,
                    run=run,
                    run_dir=run_dir,
                    review_date=selected_date,
                    findings=findings,
                    metrics=metrics,
                    trend=trend,
                )

        return _finalize(
            workspace,
            run=run,
            run_dir=run_dir,
            review_date=selected_date,
            findings=findings,
            metrics=metrics,
            trend=trend,
            proposal=proposal,
        )
