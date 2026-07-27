from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .io import hash_json
from .workspace import Workspace

REDACTION_RULES = (
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), "[REDACTED_OPENAI_KEY]"),
    (re.compile(r"\bgh[opurs]_[A-Za-z0-9]{20,}\b"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE), "Bearer [REDACTED]"),
    (
        re.compile(
            r"(password|passwd|secret|token|api[_-]?key)\s*[:=]\s*[^\s,;\"']+",
            re.IGNORECASE,
        ),
        r"\1=[REDACTED]",
    ),
)
ARTIFACT_PATTERN = re.compile(
    r"(?:[A-Za-z]:[\\/][^\s\"'<>|]+|(?:\.{0,2}[\\/])?"
    r"[A-Za-z0-9_.-]+(?:[\\/][A-Za-z0-9_.-]+)*\."
    r"(?:md|json|ya?ml|toml|js|ts|py|log|txt))"
)


def parse_datetime(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    result = datetime.fromisoformat(normalized)
    if result.tzinfo is None:
        raise ValueError(f"Timestamp must include an offset: {value}")
    return result


def redact(value: str) -> str:
    result = value
    for pattern, replacement in REDACTION_RULES:
        result = pattern.sub(replacement, result)
    return result


def _text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return json.dumps(content, ensure_ascii=False)
    values = []
    for item in content:
        if isinstance(item, dict):
            values.append(
                item.get("text")
                or item.get("input_text")
                or item.get("output_text")
                or json.dumps(item, ensure_ascii=False)
            )
        else:
            values.append(str(item))
    return "\n".join(values)


def _classify(payload: dict[str, Any]) -> list[dict[str, Any]]:
    payload_type = payload.get("type")
    if payload_type == "message":
        actor = payload.get("role")
        if actor not in {"user", "assistant", "system"}:
            actor = "system"
        return [{
            "actor": actor,
            "event_type": "message",
            "call_id": None,
            "content": _text_content(payload.get("content")),
            "location": f"response_item:{actor}",
        }]
    if payload_type in {"function_call", "custom_tool_call"}:
        return [{
            "actor": "tool",
            "event_type": "tool_call",
            "call_id": payload.get("call_id"),
            "content": json.dumps(
                {
                    "name": payload.get("name"),
                    "arguments": payload.get("arguments", payload.get("input")),
                    "call_id": payload.get("call_id"),
                },
                ensure_ascii=False,
            ),
            "location": f"response_item:{payload_type}",
        }]
    if payload_type in {"function_call_output", "custom_tool_call_output"}:
        output = _text_content(payload.get("output"))
        failed = bool(re.search(
            r"exit code:\s*[1-9]|process exited with code [1-9]|isError[\"']?\s*:\s*true",
            output,
            re.IGNORECASE,
        ))
        result = [{
            "actor": "tool",
            "event_type": "execution_error" if failed else "tool_result",
            "call_id": payload.get("call_id"),
            "content": output,
            "location": f"response_item:{payload_type}",
        }]
        if not failed:
            seen: set[str] = set()
            for match in ARTIFACT_PATTERN.findall(output):
                if match in seen:
                    continue
                seen.add(match)
                result.append({
                    "actor": "tool",
                    "event_type": "artifact_reference",
                    "call_id": payload.get("call_id"),
                    "content": match,
                    "location": "derived-artifact-reference",
                })
        return result
    return []


def _iter_rows(file: Path) -> Iterable[tuple[int, dict[str, Any]]]:
    with file.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            yield number, json.loads(line)


def _session_meta(file: Path) -> dict[str, Any] | None:
    for _, row in _iter_rows(file):
        if row.get("type") == "session_meta":
            payload = row.get("payload")
            return payload if isinstance(payload, dict) else None
    return None


def _inside(candidate: Path, root: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _codex_home(workspace: Workspace) -> Path:
    configured = workspace.config.get("codex_home")
    if configured:
        candidate = Path(configured).expanduser()
        if not candidate.is_absolute():
            candidate = workspace.root / candidate
        return candidate.resolve()
    environment = os.environ.get("CODEX_HOME")
    if environment:
        return Path(environment).expanduser().resolve()
    return Path.home() / ".codex"


def collect_source_packet(
    workspace: Workspace,
    window_start: str,
    window_end: str,
) -> dict[str, Any]:
    start = parse_datetime(window_start)
    end = parse_datetime(window_end)
    explicit_ids = set(workspace.config.get("conversation_ids", []))
    sessions = _codex_home(workspace) / "sessions"
    conversations: list[dict[str, Any]] = []
    if not sessions.exists():
        return {
            "schema_version": "1.0.0",
            "project_id": workspace.project_id,
            "window_start": window_start,
            "window_end": window_end,
            "conversations": conversations,
        }

    for file in sorted(sessions.rglob("*.jsonl")):
        meta = _session_meta(file)
        if not meta or not meta.get("cwd"):
            continue
        conversation_id = meta.get("id") or meta.get("session_id")
        accepted_explicitly = conversation_id in explicit_ids
        accepted_by_root = _inside(Path(meta["cwd"]), workspace.root)
        if not accepted_explicitly and not accepted_by_root:
            continue
        records = []
        sequence = 0
        before = False
        after = False
        for line_number, row in _iter_rows(file):
            if row.get("type") != "response_item":
                continue
            timestamp_value = row.get("timestamp")
            if not isinstance(timestamp_value, str):
                continue
            timestamp = parse_datetime(timestamp_value)
            payload = row.get("payload")
            if not isinstance(payload, dict):
                continue
            for item in _classify(payload):
                item_sequence = sequence
                sequence += 1
                if timestamp < start:
                    before = True
                    continue
                if timestamp >= end:
                    after = True
                    continue
                if not item["content"]:
                    continue
                content = str(item["content"])
                if workspace.config.get("privacy", {}).get("content_mode") == "redact_secrets":
                    content = redact(content)
                record = {
                    "conversation_id": conversation_id,
                    "timestamp": timestamp_value,
                    "actor": item["actor"],
                    "sequence": item_sequence,
                    "event_type": item["event_type"],
                    "call_id": item["call_id"],
                    "source_location": (
                        f"{file.name}:{line_number}:{item['location']}"
                    ),
                    "content_or_reference": content,
                    "collection_status": (
                        "referenced"
                        if item["event_type"] == "artifact_reference"
                        else "redacted"
                        if content != str(item["content"])
                        else "collected"
                    ),
                }
                hash_input = {
                    key: record[key]
                    for key in (
                        "conversation_id",
                        "timestamp",
                        "actor",
                        "sequence",
                        "event_type",
                        "call_id",
                        "source_location",
                        "content_or_reference",
                    )
                }
                record["content_hash"] = hash_json(hash_input)
                records.append(record)
        if records:
            conversations.append({
                "conversation_id": conversation_id,
                "project_id": workspace.project_id,
                "binding_method": (
                    "explicit_conversation_id"
                    if accepted_explicitly
                    else "project_marker_plus_workspace_root"
                ),
                "has_events_before_window": before,
                "has_events_after_window": after,
                "records": records,
            })
    return {
        "schema_version": "1.0.0",
        "project_id": workspace.project_id,
        "window_start": window_start,
        "window_end": window_end,
        "conversations": conversations,
    }


def build_evidence(
    source: dict[str, Any],
    *,
    run_id: str,
    contract_revision: str,
    contract_hash: str,
) -> dict[str, Any]:
    records = []
    seen_hashes: dict[str, str] = {}
    for conversation_index, conversation in enumerate(source["conversations"]):
        for record_index, record in enumerate(conversation["records"]):
            evidence_id = f"ev_{conversation_index}_{record_index}"
            duplicate_of = seen_hashes.get(record["content_hash"])
            seen_hashes.setdefault(record["content_hash"], evidence_id)
            records.append({
                "evidence_id": evidence_id,
                "conversation_id": record["conversation_id"],
                "project_id": source["project_id"],
                "timestamp": record["timestamp"],
                "actor": record["actor"],
                "sequence": record["sequence"],
                "event_type": record["event_type"],
                "call_id": record["call_id"],
                "source_location": record["source_location"],
                "content_or_reference": record["content_or_reference"],
                "content_hash": record["content_hash"],
                "collection_status": record["collection_status"],
                "duplicate_of": duplicate_of,
            })
    return {
        "schema_version": "1.0.0",
        "contract_revision": contract_revision,
        "contract_bundle_hash": contract_hash,
        "run_id": run_id,
        "project_id": source["project_id"],
        "window_start": source["window_start"],
        "window_end": source["window_end"],
        "conversations": [
            {
                "conversation_id": item["conversation_id"],
                "has_events_before_window": item["has_events_before_window"],
                "has_events_after_window": item["has_events_after_window"],
            }
            for item in source["conversations"]
        ],
        "records": records,
    }
