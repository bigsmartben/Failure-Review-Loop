from __future__ import annotations

import json
from pathlib import Path

import pytest

from sdd_frl.errors import COLLECTION_BLOCKER_CODES, SddFrlError
from sdd_frl.source import collect_source_packet, probe_source
from sdd_frl.validation import validate_source_records
from sdd_frl.workspace import init_workspace, load_workspace


def _write_session(
    file: Path,
    *,
    conversation_id: str,
    cwd: Path,
    content: str,
    timestamp: str = "2026-07-26T01:00:00+08:00",
    project_id: str | None = None,
) -> None:
    rows = [
        {
            "type": "session_meta",
            "payload": {
                "id": conversation_id,
                "cwd": str(cwd),
                "projectId": project_id,
            },
        },
        {
            "type": "response_item",
            "timestamp": timestamp,
            "payload": {
                "type": "message",
                "role": "user",
                "content": content,
            },
        },
    ]
    file.write_text(
        "".join(f"{json.dumps(row)}\n" for row in rows),
        encoding="utf-8",
    )


def test_collection_uses_analysis_target_instead_of_frl_workspace(
    tmp_path: Path,
) -> None:
    runner = tmp_path / "runner"
    target = tmp_path / "harness"
    codex_home = tmp_path / "codex-home"
    sessions = codex_home / "sessions"
    runner.mkdir()
    target.mkdir()
    sessions.mkdir(parents=True)
    init_workspace(
        runner,
        timezone_name="Asia/Shanghai",
        analysis_target=target,
        analysis_project_id="harness",
    )
    config_file = runner / ".sdd-frl/config.json"
    config = json.loads(config_file.read_text("utf-8"))
    config["codex_home"] = str(codex_home)
    config_file.write_text(json.dumps(config), encoding="utf-8")
    _write_session(
        sessions / "runner.jsonl",
        conversation_id="runner-conversation",
        cwd=runner,
        content="runner message",
    )
    _write_session(
        sessions / "target.jsonl",
        conversation_id="target-conversation",
        cwd=target / "nested",
        content="target message",
    )

    packet = collect_source_packet(
        load_workspace(runner),
        "2026-07-26T00:00:00+08:00",
        "2026-07-27T00:00:00+08:00",
    )

    assert packet["project_id"] == "harness"
    assert [item["conversation_id"] for item in packet["conversations"]] == [
        "target-conversation"
    ]
    assert packet["conversations"][0]["binding_method"] == (
        "analysis_target_workspace_root"
    )
    assert packet["source_kind"] == "local_codex_sessions_jsonl"
    assert packet["empty_reason"] is None
    assert packet["collection_summary"] == {
        "session_files_scanned": 2,
        "target_conversations_matched": 1,
        "records_before_window": 0,
        "records_in_window": 1,
        "records_after_window": 0,
        "skipped_missing_meta": 0,
        "skipped_outside_target": 1,
        "skipped_uncollectable": 0,
    }
    validate_source_records(packet)


def _workspace_with_source(tmp_path: Path):
    runner = tmp_path / "runner"
    target = tmp_path / "analysis-target"
    codex_home = tmp_path / "codex-home"
    runner.mkdir()
    target.mkdir()
    (codex_home / "sessions").mkdir(parents=True)
    init_workspace(
        runner,
        timezone_name="Asia/Shanghai",
        analysis_target=target,
        analysis_project_id="analysis-target",
    )
    config_file = runner / ".sdd-frl/config.json"
    config = json.loads(config_file.read_text("utf-8"))
    config["codex_home"] = str(codex_home)
    config_file.write_text(json.dumps(config), encoding="utf-8")
    return load_workspace(runner), codex_home / "sessions"


def test_window_summary_counts_before_and_after_events(tmp_path: Path) -> None:
    workspace, sessions = _workspace_with_source(tmp_path)
    _write_session(
        sessions / "before.jsonl",
        conversation_id="before",
        cwd=workspace.analysis_root,
        content="before",
        timestamp="2026-07-25T23:59:59+08:00",
    )
    _write_session(
        sessions / "after.jsonl",
        conversation_id="after",
        cwd=workspace.analysis_root,
        content="after",
        timestamp="2026-07-27T00:00:00+08:00",
    )

    packet = collect_source_packet(
        workspace,
        "2026-07-26T00:00:00+08:00",
        "2026-07-27T00:00:00+08:00",
    )

    assert packet["empty_reason"] == "NO_EVENTS_IN_WINDOW"
    assert packet["collection_summary"]["records_before_window"] == 1
    assert packet["collection_summary"]["records_after_window"] == 1
    assert packet["collection_summary"]["records_in_window"] == 0
    assert all(not item["records"] for item in packet["conversations"])
    validate_source_records(packet)


def test_explicit_conversation_id_overrides_target_and_deduplicates_binding(
    tmp_path: Path,
) -> None:
    workspace, sessions = _workspace_with_source(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    config = json.loads(workspace.config_file.read_text("utf-8"))
    config["conversation_ids"] = ["outside-id", "inside-id"]
    workspace.config_file.write_text(json.dumps(config), encoding="utf-8")
    workspace = load_workspace(workspace.root)
    _write_session(
        sessions / "outside.jsonl",
        conversation_id="outside-id",
        cwd=outside,
        content="explicit outside",
    )
    _write_session(
        sessions / "inside.jsonl",
        conversation_id="inside-id",
        cwd=workspace.analysis_root,
        content="explicit and root",
    )
    _write_session(
        sessions / "inside-duplicate.jsonl",
        conversation_id="inside-id",
        cwd=workspace.analysis_root / "nested",
        content="duplicate file must not duplicate conversation",
    )

    packet = collect_source_packet(
        workspace,
        "2026-07-26T00:00:00+08:00",
        "2026-07-27T00:00:00+08:00",
    )

    assert [item["conversation_id"] for item in packet["conversations"]] == [
        "inside-id",
        "outside-id",
    ]
    assert all(
        item["binding_method"] == "explicit_conversation_id"
        for item in packet["conversations"]
    )
    assert packet["collection_summary"]["target_conversations_matched"] == 2
    assert packet["collection_summary"]["records_in_window"] == 2


def test_uncollectable_event_has_distinct_empty_reason(tmp_path: Path) -> None:
    workspace, sessions = _workspace_with_source(tmp_path)
    rows = [
        {
            "type": "session_meta",
            "payload": {"id": "unsupported", "cwd": str(workspace.analysis_root)},
        },
        {
            "type": "response_item",
            "timestamp": "2026-07-26T01:00:00+08:00",
            "payload": {"type": "unsupported"},
        },
    ]
    (sessions / "unsupported.jsonl").write_text(
        "".join(f"{json.dumps(row)}\n" for row in rows),
        encoding="utf-8",
    )

    packet = collect_source_packet(
        workspace,
        "2026-07-26T00:00:00+08:00",
        "2026-07-27T00:00:00+08:00",
    )

    assert packet["empty_reason"] == "EVENTS_IN_WINDOW_UNCOLLECTABLE"
    assert packet["collection_summary"]["skipped_uncollectable"] == 1
    validate_source_records(packet)


def test_missing_session_root_raises_stable_error_and_probe_reports_it(
    tmp_path: Path,
) -> None:
    workspace, sessions = _workspace_with_source(tmp_path)
    sessions.rmdir()

    with pytest.raises(SddFrlError) as caught:
        collect_source_packet(
            workspace,
            "2026-07-26T00:00:00+08:00",
            "2026-07-27T00:00:00+08:00",
        )

    assert caught.value.code == "CODEX_SOURCE_UNAVAILABLE"
    assert caught.value.code in COLLECTION_BLOCKER_CODES
    probe = probe_source(workspace)
    assert probe["available"] is False
    assert probe["blocker_codes"] == ["CODEX_SOURCE_UNAVAILABLE"]


def test_unenumerable_session_root_is_source_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace, _ = _workspace_with_source(tmp_path)

    def unavailable(*args, **kwargs):
        del args, kwargs
        raise PermissionError("denied")

    monkeypatch.setattr("sdd_frl.source.os.walk", unavailable)
    with pytest.raises(SddFrlError) as caught:
        collect_source_packet(
            workspace,
            "2026-07-26T00:00:00+08:00",
            "2026-07-27T00:00:00+08:00",
        )
    assert caught.value.code == "CODEX_SOURCE_UNAVAILABLE"


def test_readable_source_without_target_has_binding_blocker(tmp_path: Path) -> None:
    workspace, sessions = _workspace_with_source(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    _write_session(
        sessions / "outside.jsonl",
        conversation_id="outside",
        cwd=outside,
        content="outside",
    )

    packet = collect_source_packet(
        workspace,
        "2026-07-26T00:00:00+08:00",
        "2026-07-27T00:00:00+08:00",
    )
    probe = probe_source(workspace)

    assert packet["empty_reason"] == "ANALYSIS_TARGET_CONVERSATIONS_NOT_FOUND"
    assert packet["collection_summary"]["skipped_outside_target"] == 1
    assert probe["available"] is True
    assert probe["target_binding_verified"] is False
    assert probe["blocker_codes"] == [
        "ANALYSIS_TARGET_CONVERSATIONS_NOT_FOUND"
    ]
