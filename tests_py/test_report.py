from __future__ import annotations

import json
from pathlib import Path

from sdd_frl.findings_report import render_findings_section

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures/report/actionable-findings.json"
GOLDEN = ROOT / "fixtures/report/actionable-findings.expected.md"


def test_actionable_findings_match_shared_golden_contract() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))

    rendered = render_findings_section(data["findings"], data["evidence"])

    assert rendered == GOLDEN.read_text(encoding="utf-8").rstrip()
    assert "sk-live-super-secret" not in rendered
    assert "C:\\Users\\Alice" not in rendered
    assert "报告对象识别错误（已解决）" in rendered
    assert "优化对象：Prompt" in rendered
    assert "未发现有证据支持的分歧" in rendered
    assert "task_target_report" not in rendered
    assert "ev_user_report" not in rendered
