from pathlib import Path

from agentx.cli import apply_plan_task
from agentx.tasks import load_tasks


def test_apply_plan_task_writes_checklist_to_task_list(tmp_path: Path) -> None:
    output = apply_plan_task(tmp_path, "新增 workflow 測試")
    tasks = load_tasks(tmp_path)

    assert output.startswith("已新增 6 個任務")
    assert len(tasks) == 6
    assert tasks[0]["id"] == 1
    assert tasks[0]["status"] == "in_progress"
    assert tasks[0]["description"] == "釐清目標與風險：新增 workflow 測試"
    assert tasks[0]["notes"] == "[來自 /plan-task --apply]"
    assert all(task["status"] == "pending" for task in tasks[1:])


def test_apply_plan_task_appends_after_existing_tasks(tmp_path: Path) -> None:
    first = apply_plan_task(tmp_path, "新增第一批")
    second = apply_plan_task(tmp_path, "新增第二批")
    tasks = load_tasks(tmp_path)

    assert "已新增 6 個任務" in first
    assert "已新增 6 個任務" in second
    assert len(tasks) == 12
    assert tasks[6]["id"] == 7
    assert tasks[6]["status"] == "in_progress"
    assert tasks[6]["description"] == "釐清目標與風險：新增第二批"


def test_apply_plan_task_rejects_empty_text(tmp_path: Path) -> None:
    assert apply_plan_task(tmp_path, " ") == "usage: /plan-task --apply TEXT"
    assert load_tasks(tmp_path) == []
