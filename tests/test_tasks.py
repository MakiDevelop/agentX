from pathlib import Path

from agentx.tasks import (
    find_task,
    get_next_task_id,
    load_tasks,
    migrate_single_task_if_needed,
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


def test_migrate_single_task_creates_multi_task(tmp_path: Path):
    """舊的單一進行中任務應能自動遷移成多任務清單的第一筆"""
    from agentx.task import start_task

    # 先建立一個舊的單一任務
    old_task = start_task(tmp_path, "重構認證模組")
    assert old_task.status == "active"

    # 多任務清單本來是空的
    assert load_tasks(tmp_path) == []

    # 觸發遷移
    migrated = migrate_single_task_if_needed(tmp_path)
    assert migrated is True

    multi = load_tasks(tmp_path)
    assert len(multi) == 1
    assert multi[0]["description"] == "重構認證模組"
    assert multi[0]["status"] == "in_progress"
    assert "自動遷移" in multi[0]["notes"]


def test_migrate_does_nothing_if_multi_already_exists(tmp_path: Path):
    """如果已經有多任務清單，就不要再從舊單一任務遷移"""
    from agentx.task import start_task

    start_task(tmp_path, "舊任務")
    # 先手動建立一個多任務
    save_tasks(tmp_path, [{"id": 99, "description": "新任務", "status": "pending", "notes": ""}])

    migrated = migrate_single_task_if_needed(tmp_path)
    assert migrated is False

    multi = load_tasks(tmp_path)
    assert len(multi) == 1
    assert multi[0]["id"] == 99  # 沒有被舊任務覆蓋


def test_migrate_bails_if_tasks_json_exists_even_if_corrupt(tmp_path: Path):
    """即使 tasks.json 存在但損壞，也絕對不要用舊單一任務覆寫（Codex 安全守衛）"""
    from agentx.task import start_task

    # 建立舊單一任務
    start_task(tmp_path, "舊任務")

    # 建立一個損壞的 tasks.json
    tasks_file = tasks_path(tmp_path)
    tasks_file.parent.mkdir(parents=True, exist_ok=True)
    tasks_file.write_text("{ this is not valid json", encoding="utf-8")

    migrated = migrate_single_task_if_needed(tmp_path)
    assert migrated is False

    # 損壞的檔案必須被保留，不能被覆寫
    assert tasks_file.exists()
    # 內容依然是損壞的（我們沒有去修它）
    assert "not valid json" in tasks_file.read_text()


def test_migrate_does_nothing_when_no_old_task(tmp_path: Path):
    """沒有舊單一任務時不做任何事"""
    migrated = migrate_single_task_if_needed(tmp_path)
    assert migrated is False
    assert load_tasks(tmp_path) == []


def test_migrate_renames_old_file_to_backup(tmp_path: Path):
    """遷移成功後，舊的 task.json 應被改名為 task.json.bak（務實策略 B）"""
    from agentx.task import start_task

    start_task(tmp_path, "重構認證模組")

    migrated = migrate_single_task_if_needed(tmp_path)
    assert migrated is True

    old_path = tmp_path / ".agentx" / "task.json"
    backup_path = tmp_path / ".agentx" / "task.json.bak"

    assert not old_path.exists()
    assert backup_path.exists()

    # 確認新多任務清單正確
    multi = load_tasks(tmp_path)
    assert len(multi) == 1
    assert multi[0]["description"] == "重構認證模組"
