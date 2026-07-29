from __future__ import annotations

import json
from pathlib import Path

import pytest

from sdd_frl.errors import COLLECTION_BLOCKER_CODES, SddFrlError
from sdd_frl.source import collect_source_packet
from sdd_frl.validation import validate_source_records
from sdd_frl.workspace import init_workspace, load_workspace

WINDOW_START = "2026-07-26T00:00:00+08:00"
WINDOW_END = "2026-07-27T00:00:00+08:00"


def _write_session(
    file: Path,
    *,
    conversation_id: str,
    cwd: Path,
    content: str,
    timestamp: str = "2026-07-26T01:00:00+08:00",
) -> None:
    rows = [
        {
            "type": "session_meta",
            "payload": {"id": conversation_id, "cwd": str(cwd)},
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


def _runtime_with_source(tmp_path: Path):
    project = tmp_path / "frl-test"
    target = tmp_path / "product-a"
    codex_home = tmp_path / "codex-home"
    project.mkdir()
    target.mkdir()
    (codex_home / "sessions").mkdir(parents=True)
    init_workspace(project, timezone_name="Asia/Shanghai")
    config_file = project / ".sdd-frl/config.json"
    config = json.loads(config_file.read_text("utf-8"))
    config["codex_home"] = str(codex_home)
    config_file.write_text(json.dumps(config), encoding="utf-8")
    return load_workspace(project), target, codex_home / "sessions"


def _collect(workspace, target: Path, project_id: str = "product-a"):
    return collect_source_packet(
        workspace,
        target,
        project_id,
        WINDOW_START,
        WINDOW_END,
    )


def test_runtime_target_selects_only_its_own_sessions(tmp_path: Path) -> None:
    workspace, target_a, sessions = _runtime_with_source(tmp_path)
    target_b = tmp_path / "product-b"
    target_b.mkdir()
    _write_session(
        sessions / "a.jsonl",
        conversation_id="conversation-a",
        cwd=target_a / "nested",
        content="A message",
    )
    _write_session(
        sessions / "b.jsonl",
        conversation_id="conversation-b",
        cwd=target_b,
        content="B message",
    )

    packet_a = _collect(workspace, target_a)
    packet_b = _collect(workspace, target_b, "product-b")

    assert [item["conversation_id"] for item in packet_a["conversations"]] == [
        "conversation-a"
    ]
    assert [item["conversation_id"] for item in packet_b["conversations"]] == [
        "conversation-b"
    ]
    assert packet_a["conversations"][0]["match_method"] == "target_cwd"
    assert packet_a["project_id"] == "product-a"
    assert packet_b["project_id"] == "product-b"
    validate_source_records(packet_a)
    validate_source_records(packet_b)


def test_collection_preserves_raw_local_content(tmp_path: Path) -> None:
    workspace, target, sessions = _runtime_with_source(tmp_path)
    raw_content = "token=local-regression-secret"
    _write_session(
        sessions / "raw.jsonl",
        conversation_id="raw",
        cwd=target,
        content=raw_content,
    )

    packet = _collect(workspace, target)

    assert packet["conversations"][0]["records"][0]["content_or_reference"] == raw_content
    assert packet["conversations"][0]["records"][0]["collection_status"] == "collected"
    validate_source_records(packet)


def test_window_summary_counts_before_and_after_events(tmp_path: Path) -> None:
    workspace, target, sessions = _runtime_with_source(tmp_path)
    _write_session(
        sessions / "before.jsonl",
        conversation_id="before",
        cwd=target,
        content="before",
        timestamp="2026-07-25T23:59:59+08:00",
    )
    _write_session(
        sessions / "after.jsonl",
        conversation_id="after",
        cwd=target,
        content="after",
        timestamp=WINDOW_END,
    )

    packet = _collect(workspace, target)

    assert packet["empty_reason"] == "NO_EVENTS_IN_WINDOW"
    assert packet["collection_summary"]["records_before_window"] == 1
    assert packet["collection_summary"]["records_after_window"] == 1
    assert packet["collection_summary"]["records_in_window"] == 0
    validate_source_records(packet)


def test_readable_source_without_target_conversations_is_a_runtime_failure(
    tmp_path: Path,
) -> None:
    workspace, target, sessions = _runtime_with_source(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    _write_session(
        sessions / "outside.jsonl",
        conversation_id="outside",
        cwd=outside,
        content="outside",
    )

    packet = _collect(workspace, target)

    assert packet["empty_reason"] == "TARGET_CONVERSATIONS_NOT_FOUND"
    assert packet["collection_summary"]["target_conversations_matched"] == 0
    assert packet["collection_summary"]["skipped_outside_target"] == 1
    validate_source_records(packet)


def test_missing_session_root_raises_stable_error(tmp_path: Path) -> None:
    workspace, target, sessions = _runtime_with_source(tmp_path)
    sessions.rmdir()

    with pytest.raises(SddFrlError) as caught:
        _collect(workspace, target)

    assert caught.value.code == "CODEX_SOURCE_UNAVAILABLE"
    assert caught.value.code in COLLECTION_BLOCKER_CODES
