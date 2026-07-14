import pytest

from agentx.intent import analyze_intent


def test_analyze_intent_builds_low_risk_execution_brief() -> None:
    brief = analyze_intent("新增 /intent 指令並補測試")

    assert "## Intent Brief" in brief
    assert "- Likely action: add" in brief
    assert "- Risk: GREEN" in brief
    assert "- Ask Maki before execution: no" in brief
    assert "## Suggested Inspection" in brief
    assert "/where" in brief
    assert "/find" in brief
    assert "uv run pytest -q" in brief


def test_analyze_intent_flags_remote_and_production_work() -> None:
    brief = analyze_intent("部署到 VPS production 並重啟服務")

    assert "- Likely action: deploy" in brief
    assert "- Risk: HIGH" in brief
    assert "- Ask Maki before execution: yes" in brief
    assert "/where vps" in brief
    assert "/where 重啟服務" in brief
    assert "read /infra first" in brief
    assert "without explicit approval" in brief


def test_analyze_intent_flags_destructive_work_as_red() -> None:
    brief = analyze_intent("刪除資料庫 volume")

    assert "- Risk: RED" in brief
    assert "- Ask Maki before execution: yes" in brief


def test_analyze_intent_requires_text() -> None:
    with pytest.raises(ValueError, match="intent text is required"):
        analyze_intent(" ")
