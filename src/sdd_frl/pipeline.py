from __future__ import annotations

import secrets
import shutil
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from zoneinfo import ZoneInfo

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
from .resources import CONTRACT_REVISION, contract_bundle_hash
from .source import build_evidence, collect_source_packet, parse_datetime
from .validation import (
    schema_errors,
    validate_evidence,
    validate_findings,
    validate_metrics,
    validate_proposal,
    validate_schema,
    validate_source_records,
    validate_trend,
)
from .workspace import Workspace, inspect_agent_configuration, load_workspace, slug

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
RUNTIME_CONTRACT_ROOT = Path(".sdd-frl/contracts")
TERMINAL_STATUSES = {
    "COMPLETED_NO_TASKS",
    "COMPLETED_WITH_METRICS",
    "COMPLETED_WITH_FINDINGS",
    "COMPLETED_WITH_PROPOSAL",
}


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
    write_text_atomic(raw_report, render_report(run=run, review_date=review_date))


@contextmanager
def _project_lock(
    workspace: Workspace,
    project_id: str,
    run_id: str,
) -> Iterator[None]:
    lock = workspace.locks_dir / f"{project_id}.lock"
    try:
        lock.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise SddFrlError(
            "OVERLAPPING_RUN",
            f"项目 {project_id} 已有活动运行。",
        ) from exc
    write_json_atomic(lock / "owner.json", {"run_id": run_id, "acquired_at": utc_now()})
    try:
        yield
    finally:
        shutil.rmtree(lock, ignore_errors=True)


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


def _assert_manifest_targets_unchanged(manifest: dict[str, Any]) -> None:
    for target in manifest["targets"]:
        path = Path(target["path"])
        try:
            current = sha256(path.read_bytes())
        except OSError as exc:
            raise SddFrlError(
                "IMPROVEMENT_TARGET_MUTATED",
                f"锁定载体不可读：{target['id']}。",
            ) from exc
        if f"sha256:{current}" != target["content_hash"]:
            raise SddFrlError(
                "IMPROVEMENT_TARGET_MUTATED",
                f"Optimizer 阶段前后载体发生变化：{target['id']}。",
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
    resolved_id = run_id or create_run_id(parameters["project_id"])
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


def _review_date(run: dict[str, Any]) -> str:
    return parse_datetime(run["parameters"]["window_start"]).date().isoformat()


def _load_run(workspace: Workspace, run_id: str) -> tuple[dict[str, Any], Path, Path]:
    run_dir = ensure_within(workspace.runs_dir, workspace.runs_dir / run_id, "RUN_IDENTITY_MISMATCH")
    run_file = run_dir / "run.json"
    run = read_json(run_file)
    validate_schema("run", run)
    if run.get("run_id") != run_id:
        raise SddFrlError("RUN_IDENTITY_MISMATCH", "run_id 与运行目录不一致。")
    return run, run_dir, run_file


def _handoff(
    run: dict[str, Any],
    *,
    next_action: str,
    input_packet: dict[str, Any] | None = None,
    output_schema: str | None = None,
    blocker_codes: list[str] | None = None,
    report: str | None = None,
) -> dict[str, Any]:
    value = {
        "schema_version": "1.0.0",
        "run_id": run["run_id"],
        "status": run["status"],
        "next_action": next_action,
        "input_packet": input_packet,
        "output_schema": output_schema,
        "blocker_codes": blocker_codes or [],
        "report": report,
    }
    validate_schema("handoff", value)
    return value


def _stage_packet(
    workspace: Workspace,
    run: dict[str, Any],
    run_dir: Path,
    stage: str,
) -> dict[str, Any]:
    contracts = workspace.root / RUNTIME_CONTRACT_ROOT
    output_file = run_dir / "agent-output" / f"{stage}.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    if stage == "analyst":
        input_files = {
            "run": run_dir / "run.json",
            "evidence": run_dir / "evidence.json",
            "deduplication_contract": contracts / "deduplication.md",
            "contract_precedence": contracts / "precedence.md",
            "issue_signatures": contracts / "issue-signatures.json",
        }
        prompt = contracts / "analyst.md"
        schema = contracts / "findings.schema.json"
        agent = "sdd_frl_analyst"
    else:
        manifest = read_json(run_dir / "improvement-targets.json")
        input_files = {
            "run": run_dir / "run.json",
            "evidence": run_dir / "optimizer-evidence.json",
            "findings": run_dir / "findings.json",
            "improvement_targets": run_dir / "improvement-targets.json",
        }
        for index, target in enumerate(manifest["targets"]):
            input_files[f"target_{index}_{target['id']}"] = Path(target["path"])
        prompt = contracts / "optimizer.md"
        schema = contracts / "proposal.schema.json"
        agent = "sdd_frl_optimizer"
    missing = [str(path) for path in [prompt, schema, *input_files.values()] if not path.is_file()]
    if missing:
        raise SddFrlError(
            "AGENT_CONFIG_UNAVAILABLE",
            f"原生子代理输入缺失：{', '.join(missing)}",
        )
    return {
        "stage": stage,
        "agent": agent,
        "prompt": str(prompt),
        "input_files": {name: str(path) for name, path in input_files.items()},
        "output_file": str(output_file),
    }


def _agent_handoff(
    workspace: Workspace,
    run: dict[str, Any],
    run_dir: Path,
    stage: str,
) -> dict[str, Any]:
    packet = _stage_packet(workspace, run, run_dir, stage)
    return _handoff(
        run,
        next_action=f"SPAWN_{stage.upper()}",
        input_packet=packet,
        output_schema=(
            str(workspace.root / RUNTIME_CONTRACT_ROOT / "findings.schema.json")
            if stage == "analyst"
            else str(workspace.root / RUNTIME_CONTRACT_ROOT / "proposal.schema.json")
        ),
    )


def _finalize_artifacts(
    workspace: Workspace,
    *,
    run: dict[str, Any],
    run_dir: Path,
) -> dict[str, Any]:
    review_date = _review_date(run)
    raw_report = run_dir / "report.md"
    artifacts: dict[str, Any] = {}
    for name in ("findings", "metrics", "trend", "proposal"):
        file = run_dir / f"{name}.json"
        if file.exists():
            artifacts[name] = read_json(file)
    source_file = run_dir / "source-records.json"
    source = read_json(source_file) if source_file.exists() else None
    evidence_file = run_dir / "evidence.json"
    evidence = read_json(evidence_file) if evidence_file.exists() else None
    write_text_atomic(
        raw_report,
        render_report(
            run=run,
            review_date=review_date,
            source=source,
            findings=artifacts.get("findings"),
            evidence=evidence,
            metrics=artifacts.get("metrics"),
            trend=artifacts.get("trend"),
            proposal=artifacts.get("proposal"),
        ),
    )
    report, published = publish_report(
        workspace=workspace,
        raw_report=raw_report,
        project_id=run["parameters"]["project_id"],
        review_date=review_date,
        status=run["status"],
    )
    del published
    blockers = []
    if run["status"].startswith("FAILED_"):
        blockers = [(run.get("failure") or {}).get("code", "UNKNOWN")]
    return _handoff(
        run,
        next_action="STOP",
        blocker_codes=blockers,
        report=str(report),
    )


def _compute_after_findings(
    workspace: Workspace,
    *,
    run: dict[str, Any],
    run_dir: Path,
    run_file: Path,
    findings: dict[str, Any],
) -> dict[str, Any]:
    _stage_start(run_file, run, "metrics", "COMPUTING_METRICS")
    metrics = build_metrics(run=run, findings=findings, generated_at=utc_now())
    validate_metrics(metrics, metrics)
    write_json_atomic(run_dir / "metrics.json", metrics)
    _stage_success(run_file, run, "metrics", "metrics.json")

    _stage_start(run_file, run, "trend", "COMPUTING_TREND")
    params = run["parameters"]
    baseline = _baseline_metrics(
        workspace,
        current_run_id=run["run_id"],
        project_id=params["project_id"],
        target_ids=params["improvement_target_ids"],
        contract_hash=params["contract_bundle_hash"],
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

    run["status"] = "CHECKING_THRESHOLD"
    _save_run(run_file, run)
    eligible = findings["optimizer_eligible_cluster_ids"]
    if not eligible:
        run["status"] = (
            "COMPLETED_NO_TASKS"
            if not findings["task_episodes"]
            else "COMPLETED_WITH_METRICS"
        )
        run["stages"]["optimizer"]["status"] = "skipped"
        _save_run(run_file, run)
        return _handoff(run, next_action="FINALIZE")
    if not params["improvement_target_ids"]:
        run["status"] = "COMPLETED_WITH_FINDINGS"
        run["stages"]["optimizer"]["status"] = "skipped"
        _save_run(run_file, run)
        return _handoff(run, next_action="FINALIZE")

    evidence = read_json(run_dir / "evidence.json")
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
    manifest = read_json(run_dir / "improvement-targets.json")
    _assert_manifest_targets_unchanged(manifest)
    _stage_start(run_file, run, "optimizer", "OPTIMIZING")
    return _agent_handoff(workspace, run, run_dir, "optimizer")


def prepare_review(
    path: str | Path,
    *,
    target: str | Path,
    review_date: str | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
    run_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    workspace = load_workspace(path)
    inspect_agent_configuration(workspace.root)
    requested_target = Path(target).expanduser()
    if not requested_target.is_absolute():
        raise SddFrlError(
            "TARGET_PATH_NOT_ABSOLUTE",
            "目标必须是绝对路径。",
        )
    target_root = requested_target.resolve()
    if not target_root.is_dir():
        raise SddFrlError("TARGET_NOT_DIRECTORY", f"目标不是目录：{target_root}")
    project_id = slug(target_root.name)
    start, end, selected_date = review_window(
        workspace.timezone,
        review_date=review_date,
        window_start=window_start,
        window_end=window_end,
        now=now,
    )
    contract_hash = contract_bundle_hash()
    targets: list[dict[str, Any]] = []
    snapshots: dict[str, str] = {}
    pending_manifest = _target_manifest("pending", targets, snapshots)
    parameters = {
        "project_id": project_id,
        "target_root": str(target_root),
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

    with _project_lock(workspace, project_id, run["run_id"]):
        try:
            _stage_start(run_file, run, "collector", "COLLECTING")
            source = collect_source_packet(
                workspace,
                target_root,
                project_id,
                start,
                end,
            )
            write_json_atomic(run_dir / "source-records.json", source)
            validate_source_records(source)
            if source["empty_reason"] == "TARGET_CONVERSATIONS_NOT_FOUND":
                raise SddFrlError(
                    "TARGET_CONVERSATIONS_NOT_FOUND",
                    "Codex session 数据源可读，但没有找到属于本次目标的对话。",
                )
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
            failed_status = (
                "FAILED_EVIDENCE_VALIDATION"
                if run["status"] == "VALIDATING_EVIDENCE"
                else "FAILED_COLLECTION"
            )
            _fail(
                run_file,
                raw_report,
                run,
                status=failed_status,
                stage="collector",
                error=error,
                review_date=selected_date,
            )
            return _finalize_artifacts(workspace, run=run, run_dir=run_dir)

        if not evidence["records"]:
            findings = _empty_findings(run)
            write_json_atomic(run_dir / "findings.json", findings)
            _stage_start(run_file, run, "analyst", "ANALYZING")
            _stage_success(run_file, run, "analyst", "findings.json")
            try:
                return _compute_after_findings(
                    workspace,
                    run=run,
                    run_dir=run_dir,
                    run_file=run_file,
                    findings=findings,
                )
            except Exception as error:
                stage = (
                    "trend"
                    if run["status"] == "COMPUTING_TREND"
                    else "metrics"
                )
                status = "FAILED_TREND" if stage == "trend" else "FAILED_METRICS"
                _fail(
                    run_file,
                    raw_report,
                    run,
                    status=status,
                    stage=stage,
                    error=error,
                    review_date=selected_date,
                )
                return _finalize_artifacts(workspace, run=run, run_dir=run_dir)

        _stage_start(run_file, run, "analyst", "ANALYZING")
        return _agent_handoff(workspace, run, run_dir, "analyst")


def _candidate_value(run_dir: Path, stage: str, input_file: str | Path) -> dict[str, Any]:
    expected = (run_dir / "agent-output" / f"{stage}.json").resolve()
    actual = ensure_within(run_dir, Path(input_file), "WORKSPACE_MISMATCH")
    if actual != expected:
        raise SddFrlError(
            "WORKSPACE_MISMATCH",
            f"{stage} 输出必须写入 handoff 指定路径：{expected}",
        )
    value = read_json(actual)
    if not isinstance(value, dict):
        raise SddFrlError("AGENT_OUTPUT_INVALID", f"{stage} 输出必须是 JSON 对象。")
    return value


def continue_review(
    path: str | Path,
    *,
    run_id: str,
    stage: str,
    input_file: str | Path,
) -> dict[str, Any]:
    workspace = load_workspace(path)
    if stage not in {"analyst", "optimizer"}:
        raise SddFrlError("STAGE_ORDER_INVALID", f"不支持的继续阶段：{stage}。")
    expected_status = "ANALYZING" if stage == "analyst" else "OPTIMIZING"
    run, run_dir, run_file = _load_run(workspace, run_id)
    with _project_lock(workspace, run["parameters"]["project_id"], run_id):
        if run["status"] != expected_status or run["stages"][stage]["status"] != "running":
            raise SddFrlError(
                "STAGE_ORDER_INVALID",
                f"{stage} 不能在状态 {run['status']} 下继续。",
            )
        raw_report = run_dir / "report.md"
        review_date = _review_date(run)
        try:
            value = _candidate_value(run_dir, stage, input_file)
            if (
                value.get("run_id") != run_id
                or value.get("project_id") != run["parameters"]["project_id"]
            ):
                raise SddFrlError(
                    "RUN_IDENTITY_MISMATCH",
                    f"{stage} 输出的 run_id 或 project_id 不一致。",
                )
            if stage == "analyst":
                run["status"] = "VALIDATING_FINDINGS"
                _save_run(run_file, run)
                evidence = read_json(run_dir / "evidence.json")
                validate_findings(value, run=run, evidence=evidence)
                write_json_atomic(run_dir / "findings.json", value)
                _stage_success(run_file, run, "analyst", "findings.json")
            else:
                run["status"] = "VALIDATING_PROPOSAL"
                _save_run(run_file, run)
                findings = read_json(run_dir / "findings.json")
                manifest = read_json(run_dir / "improvement-targets.json")
                _assert_manifest_targets_unchanged(manifest)
                validate_proposal(value, run=run, findings=findings)
                write_json_atomic(run_dir / "proposal.json", value)
                _stage_success(run_file, run, "optimizer", "proposal.json")
                run["status"] = (
                    "COMPLETED_WITH_PROPOSAL"
                    if value["proposals"]
                    else "COMPLETED_WITH_FINDINGS"
                )
                _save_run(run_file, run)
        except Exception as error:
            if isinstance(error, SddFrlError) and error.code == "RUN_IDENTITY_MISMATCH":
                failure = error
            else:
                code, message = _failure_details(error)
                failure = SddFrlError(
                    "AGENT_OUTPUT_INVALID",
                    f"{stage} 输出校验失败（{code}）：{message}",
                )
            status = (
                "FAILED_FINDINGS_VALIDATION"
                if stage == "analyst"
                else "FAILED_PROPOSAL_VALIDATION"
            )
            _fail(
                run_file,
                raw_report,
                run,
                status=status,
                stage=stage,
                error=failure,
                review_date=review_date,
            )
            return _finalize_artifacts(workspace, run=run, run_dir=run_dir)

        if stage == "optimizer":
            return _handoff(run, next_action="FINALIZE")
        try:
            return _compute_after_findings(
                workspace,
                run=run,
                run_dir=run_dir,
                run_file=run_file,
                findings=value,
            )
        except Exception as error:
            if run["status"] in {"COMPUTING_TREND", "FAILED_TREND"}:
                failed_stage, failed_status = "trend", "FAILED_TREND"
            elif run["status"] == "OPTIMIZING":
                failed_stage, failed_status = "optimizer", "FAILED_OPTIMIZATION"
            else:
                failed_stage, failed_status = "metrics", "FAILED_METRICS"
            _fail(
                run_file,
                raw_report,
                run,
                status=failed_status,
                stage=failed_stage,
                error=error,
                review_date=review_date,
            )
            return _finalize_artifacts(workspace, run=run, run_dir=run_dir)


def finalize_review(path: str | Path, *, run_id: str) -> dict[str, Any]:
    workspace = load_workspace(path)
    run, run_dir, _ = _load_run(workspace, run_id)
    if run["status"] not in TERMINAL_STATUSES and not run["status"].startswith("FAILED_"):
        raise SddFrlError(
            "STAGE_ORDER_INVALID",
            f"运行 {run_id} 尚未到达可收尾状态：{run['status']}。",
        )
    with _project_lock(workspace, run["parameters"]["project_id"], run_id):
        return _finalize_artifacts(workspace, run=run, run_dir=run_dir)


def run_review(
    path: str | Path,
    *,
    target: str | Path,
    review_date: str | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
    run_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Compatibility entry point: prepare only; never launches a nested Codex process."""
    return prepare_review(
        path,
        target=target,
        review_date=review_date,
        window_start=window_start,
        window_end=window_end,
        run_id=run_id,
        now=now,
    )
