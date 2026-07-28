from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from sdd_frl.errors import SddFrlError
from sdd_frl.validation import validate_evidence, validate_source_records


ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILE = ROOT / "examples/source-records.valid.regression-data.json"
EVIDENCE_FILE = ROOT / "examples/evidence.valid.regression-data.json"


def _read(file: Path) -> dict:
    return json.loads(file.read_text(encoding="utf-8"))


def _run_for(evidence: dict) -> dict:
    return {
        "run_id": evidence["run_id"],
        "parameters": {
            "project_id": evidence["project_id"],
            "window_start": evidence["window_start"],
            "window_end": evidence["window_end"],
            "contract_revision": evidence["contract_revision"],
            "contract_bundle_hash": evidence["contract_bundle_hash"],
        },
    }


def _error_code(value: dict) -> str:
    with pytest.raises(SddFrlError) as caught:
        validate_source_records(value)
    return caught.value.code


def test_collected_regression_data_satisfies_source_and_evidence_contracts() -> None:
    source = _read(SOURCE_FILE)
    evidence = _read(EVIDENCE_FILE)

    validate_source_records(source)
    validate_evidence(evidence, run=_run_for(evidence), source=source)


def test_source_contract_rejects_missing_content() -> None:
    source = _read(SOURCE_FILE)
    del source["conversations"][0]["records"][0]["content_or_reference"]

    assert _error_code(source) == "SOURCE-RECORDS_SCHEMA_INVALID"


def test_source_contract_rejects_duplicate_sequence() -> None:
    source = _read(SOURCE_FILE)
    source["conversations"][0]["records"][1]["sequence"] = 0

    assert _error_code(source) == "SOURCE_RECORDS_SEQUENCE_INVALID"


def test_source_contract_rejects_a_tool_result_without_an_earlier_call() -> None:
    source = _read(SOURCE_FILE)
    source["conversations"][0]["records"].pop(2)
    source["collection_summary"]["records_in_window"] -= 1

    assert _error_code(source) == "SOURCE_RECORDS_TOOL_CALL_MISSING"


def test_source_contract_rejects_content_hash_drift() -> None:
    source = _read(SOURCE_FILE)
    source["conversations"][0]["records"][0][
        "content_or_reference"
    ] = "篡改后的输入"

    assert _error_code(source) == "SOURCE_RECORDS_CONTENT_HASH_MISMATCH"


def test_evidence_must_preserve_source_record_order() -> None:
    source = _read(SOURCE_FILE)
    evidence = _read(EVIDENCE_FILE)
    reordered = copy.deepcopy(evidence)
    reordered["records"][0], reordered["records"][1] = (
        reordered["records"][1],
        reordered["records"][0],
    )

    with pytest.raises(SddFrlError) as caught:
        validate_evidence(reordered, run=_run_for(evidence), source=source)

    assert caught.value.code == "EVIDENCE_SOURCE_MISMATCH"
