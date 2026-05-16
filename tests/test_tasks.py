from pathlib import Path

from agentx.tasks import (
    find_task,
    get_next_task_id,
    load_tasks,
    save_tasks,
    tasks_path,
)


def test_load_tasks_when_no_file_returns_empty(tmp_path: Path):
    """當 .agentx/tasks.json 不存在時，應安全回傳空列表"""
    result = load_tasks(tmp_path)
    assert result == []


def test_save_and_load_roundtrip(tmp_path: Path):
    """儲存後再載入應能完整還原任務資料"""
    tasks = [
        {"id": 1, "description": "重構認證模組", "status": "in_progress", "notes": "JWT 已完成"},
        {"id": 2, "description": "加上 rate limit", "status": "pending", "notes": ""},
    ]

    save_tasks(tmp_path, tasks)
    loaded = load_tasks(tmp_path)

    assert loaded == tasks
    assert tasks_path(tmp_path).exists()


def test_get_next_task_id():
    """get_next_task_id 應正確計算下一個 id"""
    assert get_next_task_id([]) == 1
    assert get_next_task_id([{"id": 1}, {"id": 3}, {"id": 2}]) == 4
    assert get_next_task_id([{"id": 5}]) == 6


def test_find_task():
    """find_task 應能根據 id 正確找出任務"""
    tasks = [
        {"id": 1, "description": "A", "status": "pending", "notes": ""},
        {"id": 2, "description": "B", "status": "in_progress", "notes": "進行中"},
    ]

    assert find_task(tasks, 2)["description"] == "B"
    assert find_task(tasks, 99) is None


def test_load_tasks_on_corrupted_json_returns_empty(tmp_path: Path):
    """當 tasks.json 內容損壞時，應優雅回傳空列表而非拋例外"""
    tasks_file = tasks_path(tmp_path)
    tasks_file.parent.mkdir(parents=True, exist_ok=True)
    tasks_file.write_text("{ this is not valid json }", encoding="utf-8")

    result = load_tasks(tmp_path)
    assert result == []


def test_save_tasks_creates_agentx_directory(tmp_path: Path):
    """第一次儲存時應自動建立 .agentx 目錄"""
    tasks = [{"id": 1, "description": "測試任務", "status": "pending", "notes": ""}]

    # 確保目錄原本不存在
    agentx_dir = tmp_path / ".agentx"
    assert not agentx_dir.exists()

    save_tasks(tmp_path, tasks)

    assert agentx_dir.exists()
    assert (agentx_dir / "tasks.json").exists()
