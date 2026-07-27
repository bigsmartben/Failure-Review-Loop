from __future__ import annotations

from importlib import resources
from pathlib import Path

from .io import canonical_json, sha256

CONTRACT_REVISION = "2026-07-24.contract-first.1"
CONTRACT_FILES = (
    ("contracts", "precedence.md"),
    ("contracts", "deduplication.md"),
    ("contracts", "issue-signatures.json"),
    ("schemas", "run.schema.json"),
    ("schemas", "evidence.schema.json"),
    ("schemas", "findings.schema.json"),
    ("schemas", "metrics.schema.json"),
    ("schemas", "trend.schema.json"),
    ("schemas", "proposal.schema.json"),
    ("schemas", "handoff.schema.json"),
    ("prompts", "collector.md"),
    ("prompts", "analyst.md"),
    ("prompts", "optimizer.md"),
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def asset_path(group: str, name: str) -> Path:
    packaged = resources.files("sdd_frl").joinpath("assets", group, name)
    packaged_path = Path(str(packaged))
    if packaged_path.exists():
        return packaged_path
    fallback_group = "docs/contracts" if group == "contracts" else group
    fallback = _repo_root() / fallback_group / name
    if not fallback.exists():
        raise FileNotFoundError(f"Missing packaged asset: {group}/{name}")
    return fallback


def contract_bundle_hash() -> str:
    entries = [
        {
            "path": f"{group}/{name}",
            "content": asset_path(group, name).read_text(encoding="utf-8"),
        }
        for group, name in CONTRACT_FILES
    ]
    return f"sha256:{sha256(canonical_json(entries))}"
