import pytest

from agentx.intent import analyze_intent, plan_task_checklist, plan_task_items


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


def test_plan_task_checklist_builds_task_commands() -> None:
    plan = plan_task_checklist("新增 /plan-task 指令並補測試")

    assert "## Task Plan" in plan
    assert "- Likely action: add" in plan
    assert "- Risk: GREEN" in plan
    assert "## Checklist" in plan
    assert "## Suggested /task Commands" in plan
    assert "/task add 釐清目標與風險：新增 /plan-task 指令並補測試" in plan
    assert "/task add 實作最小可逆改動" in plan


def test_plan_task_items_match_checklist_task_commands() -> None:
    text = "新增 /plan-task apply mode"
    items = plan_task_items(text)
    plan = plan_task_checklist(text)

    assert items
    for item in items:
        assert f"/task add {item}" in plan


def test_plan_task_checklist_includes_high_risk_guardrail() -> None:
    plan = plan_task_checklist("部署到 VPS production 並重啟服務")

    assert "- Risk: HIGH" in plan
    assert "取得 Maki 明確確認後才處理高風險操作" in plan
    assert "讀取 /infra 並確認 runtime state" in plan
    assert "This plan is read-only" in plan


def test_plan_task_checklist_requires_text() -> None:
    with pytest.raises(ValueError, match="plan-task text is required"):
        plan_task_checklist("")
