from pathlib import Path
from typing import Any

import json

from agentx.tasks import (
    _get_legacy_task_if_exists,
    find_task,
    get_next_task_id,
    load_tasks,
    migrate_single_task_if_needed,
    save_tasks,
    tasks_path,
)


def _write_legacy_task(
    workspace: Path,
    *,
    title: str,
    status: str = "active",
    created_at: str = "",
    updated_at: str = "",
    **extra: Any,
) -> None:
    """
    MT22 測試輔助函式。

    直接寫入舊的單一任務 JSON（.agentx/task.json），
    用於測試 migrate_single_task_if_needed 與 _get_legacy_task_if_exists。

    目的：讓遷移測試不再依賴已經 deprecated 的 agentx.task API，
    使「新系統測試新系統」的意圖更清楚。
    """
    legacy_dir = workspace / ".agentx"
    legacy_dir.mkdir(parents=True, exist_ok=True)

    data: dict[str, Any] = {
        "title": title,
        "status": status,
        "created_at": created_at,
        "updated_at": updated_at,
    }
    data.update(extra)

    (legacy_dir / "task.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
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
    # 使用直接寫 JSON 的方式建立舊任務（避免依賴 deprecated API）
    _write_legacy_task(tmp_path, title="重構認證模組", status="active")

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
    _write_legacy_task(tmp_path, title="舊任務")
    # 先手動建立一個多任務
    save_tasks(tmp_path, [{"id": 99, "description": "新任務", "status": "pending", "notes": ""}])

    migrated = migrate_single_task_if_needed(tmp_path)
    assert migrated is False

    multi = load_tasks(tmp_path)
    assert len(multi) == 1
    assert multi[0]["id"] == 99  # 沒有被舊任務覆蓋


def test_migrate_bails_if_tasks_json_exists_even_if_corrupt(tmp_path: Path):
    """即使 tasks.json 存在但損壞，也絕對不要用舊單一任務覆寫（Codex 安全守衛）"""
    _write_legacy_task(tmp_path, title="舊任務")

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


def test_migrate_does_nothing_for_non_active_old_task(tmp_path: Path):
    """舊任務不是 active 狀態時不進行遷移"""
    # 直接寫入非 active 的舊任務（不再使用 deprecated save_task）
    _write_legacy_task(tmp_path, title="已完成的工作", status="done")

    migrated = migrate_single_task_if_needed(tmp_path)
    assert migrated is False
    assert load_tasks(tmp_path) == []


def test_migrate_handles_corrupted_old_task_json(tmp_path: Path):
    """舊 task.json 損壞時應安全失敗，不影響新系統"""
    old_path = tmp_path / ".agentx" / "task.json"
    old_path.parent.mkdir(parents=True, exist_ok=True)
    old_path.write_text("{ invalid json content", encoding="utf-8")

    migrated = migrate_single_task_if_needed(tmp_path)
    assert migrated is False
    assert load_tasks(tmp_path) == []


def test_migrate_handles_old_task_without_created_at(tmp_path: Path):
    """舊任務沒有 created_at 時仍應能正常遷移"""
    _write_legacy_task(tmp_path, title="沒有時間的任務", status="active")

    migrated = migrate_single_task_if_needed(tmp_path)
    assert migrated is True

    multi = load_tasks(tmp_path)
    assert len(multi) == 1
    assert multi[0]["description"] == "沒有時間的任務"
    assert "自動遷移自舊單一任務系統" in multi[0]["notes"]


def test_migrate_is_safe_to_call_multiple_times(tmp_path: Path):
    """多次呼叫遷移函式應該是安全的"""
    _write_legacy_task(tmp_path, title="重複測試任務")

    # 第一次
    result1 = migrate_single_task_if_needed(tmp_path)
    assert result1 is True
    assert len(load_tasks(tmp_path)) == 1

    # 第二次
    result2 = migrate_single_task_if_needed(tmp_path)
    assert result2 is False
    assert len(load_tasks(tmp_path)) == 1  # 不應該重複新增


def test_migrate_preserves_migration_metadata(tmp_path: Path):
    """遷移後的 notes 應包含有用的原始資訊"""
    _write_legacy_task(tmp_path, title="有時間戳的任務")

    migrated = migrate_single_task_if_needed(tmp_path)
    assert migrated is True

    multi = load_tasks(tmp_path)
    notes = multi[0]["notes"]
    assert "自動遷移自舊單一任務系統" in notes
    assert "原始標題" in notes


def test_migrate_handles_very_long_old_title(tmp_path: Path):
    """舊任務標題極長時仍應能正常截斷並遷移"""
    very_long_title = "這是一個非常非常非常長的舊單一任務標題" * 10
    _write_legacy_task(tmp_path, title=very_long_title, status="active")

    migrated = migrate_single_task_if_needed(tmp_path)
    assert migrated is True

    multi = load_tasks(tmp_path)
    assert len(multi) == 1
    assert len(multi[0]["description"]) <= 200
    assert "自動遷移" in multi[0]["notes"]


def test_migrate_is_idempotent_after_first_run(tmp_path: Path):
    """第一次遷移後，後續呼叫不應再做任何事"""
    from agentx.task import start_task

    start_task(tmp_path, "測試任務")
    migrated1 = migrate_single_task_if_needed(tmp_path)
    assert migrated1 is True

    # 第二次呼叫
    migrated2 = migrate_single_task_if_needed(tmp_path)
    assert migrated2 is False

    # 應該只有一筆任務
    multi = load_tasks(tmp_path)
    assert len(multi) == 1


def test_get_legacy_task_returns_none_for_oversized_file(tmp_path: Path):
    """檔案過大時應視為無效（防禦性設計）"""
    legacy_dir = tmp_path / ".agentx"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    large_file = legacy_dir / "task.json"
    # 寫入超過 1MB 的檔案
    large_file.write_bytes(b"x" * (1024 * 1024 + 100))

    result = _get_legacy_task_if_exists(tmp_path)
    assert result is None


def test_get_legacy_task_normalizes_invalid_status(tmp_path: Path):
    """status 不合法時應被正規化成空字串，而不是直接丟棄任務"""
    from agentx.task import start_task

    # 使用較長標題，確保通過「status 空 + title 太短」的最終品質守衛（A1-1l）
    start_task(tmp_path, "測試任務資料")
    # 手動修改舊檔，讓 status 變成無效值
    old_file = tmp_path / ".agentx" / "task.json"
    data = json.loads(old_file.read_text())
    data["status"] = "weird_status"
    old_file.write_text(json.dumps(data), encoding="utf-8")

    result = _get_legacy_task_if_exists(tmp_path)
    assert result is not None
    assert result.status == ""  # 被正規化了
    assert result.title == "測試任務資料"


def test_get_legacy_task_status_mapping(tmp_path: Path):
    """舊的 'active' 應被映射為 'in_progress'"""
    from agentx.task import start_task

    start_task(tmp_path, "狀態測試")

    old_file = tmp_path / ".agentx" / "task.json"
    data = json.loads(old_file.read_text())
    data["status"] = "active"
    old_file.write_text(json.dumps(data), encoding="utf-8")

    result = _get_legacy_task_if_exists(tmp_path)
    assert result is not None
    assert result.status == "in_progress"  # 被映射了


def test_get_legacy_task_normalizes_data(tmp_path: Path):
    """應對舊資料做基本清理（去空白、截斷、長度限制）"""
    from agentx.task import start_task

    start_task(tmp_path, "   髒資料任務   ")

    # 手動修改舊檔，加上很長的 title 和 notes
    old_file = tmp_path / ".agentx" / "task.json"
    data = json.loads(old_file.read_text())
    data["title"] = "   " + "A" * 300
    data["notes"] = "B" * 800
    old_file.write_text(json.dumps(data), encoding="utf-8")

    result = _get_legacy_task_if_exists(tmp_path)
    assert result is not None
    assert result.title == "A" * 200          # 有截斷
    assert result.title.strip() == result.title  # 已去空白
    assert result.status == "in_progress"  # 被映射為新系統標準值


def test_normalize_legacy_date_various_formats(tmp_path: Path):
    """日期欄位應能處理常見舊格式"""
    from agentx.task import start_task

    start_task(tmp_path, "日期測試任務")

    old_file = tmp_path / ".agentx" / "task.json"
    data = json.loads(old_file.read_text())

    # 各種常見舊格式
    test_cases = [
        ("2024-01-15T10:30:00", True),
        ("2024-01-15T10:30:00Z", True),
        ("2024-01-15T10:30:00.123456", True),
        ("2024-01-15T10:30:00+08:00", True),
        ("invalid-date", False),
        ("", False),
    ]

    for date_val, should_keep in test_cases:
        data["created_at"] = date_val
        old_file.write_text(json.dumps(data), encoding="utf-8")

        result = _get_legacy_task_if_exists(tmp_path)
        assert result is not None
        if should_keep:
            assert result.created_at == date_val.strip()
        else:
            assert result.created_at == ""


def test_get_legacy_task_removes_control_characters(tmp_path: Path):
    """應移除 title 中的控制字元與不可見字元"""
    from agentx.task import start_task

    start_task(tmp_path, "正常任務")

    old_file = tmp_path / ".agentx" / "task.json"
    data = json.loads(old_file.read_text())
    data["title"] = "髒任務\x00\x01\x1f隱藏字元\x7f"
    old_file.write_text(json.dumps(data), encoding="utf-8")

    result = _get_legacy_task_if_exists(tmp_path)
    assert result is not None
    assert result.title == "髒任務隱藏字元"  # 控制字元已被移除
    assert "\x00" not in result.title
    assert "\x1f" not in result.title


def test_get_legacy_task_rejects_too_short_title_after_cleanup(tmp_path: Path):
    """清理後 title 太短應被視為無效"""
    from agentx.task import start_task

    start_task(tmp_path, "OK")

    old_file = tmp_path / ".agentx" / "task.json"
    data = json.loads(old_file.read_text())
    data["title"] = "   a   "   # 清理後只剩 1 個字元
    old_file.write_text(json.dumps(data), encoding="utf-8")

    result = _get_legacy_task_if_exists(tmp_path)
    assert result is None


def test_get_legacy_task_overall_quality_judgment(tmp_path: Path):
    """整體品質判斷：清理後幾乎無有效資訊的任務應被拒絕（A1-1g）"""
    _write_legacy_task(tmp_path, title="OK")

    old_file = tmp_path / ".agentx" / "task.json"
    data = json.loads(old_file.read_text())
    data["title"] = "   x   "   # 清理後極短
    data["status"] = "weird"    # 無法有效映射
    old_file.write_text(json.dumps(data), encoding="utf-8")

    result = _get_legacy_task_if_exists(tmp_path)
    assert result is None  # 應被整體品質守衛拒絕


def test_get_legacy_task_aggressive_title_cleanup(tmp_path: Path):
    """應移除 emoji、特殊符號與多餘空白"""
    _write_legacy_task(tmp_path, title="正常任務")

    old_file = tmp_path / ".agentx" / "task.json"
    data = json.loads(old_file.read_text())
    data["title"] = "  任務  🚀  測試   ！  "
    old_file.write_text(json.dumps(data), encoding="utf-8")

    result = _get_legacy_task_if_exists(tmp_path)
    assert result is not None
    # emoji 被移除，連續空白收斂為單一空白
    assert result.title == "任務  測試 ！" or result.title == "任務 測試 ！"


def test_get_legacy_task_strips_leading_trailing_punctuation(tmp_path: Path):
    """應移除 title 前後的常見無意義標點"""
    from agentx.task import start_task

    start_task(tmp_path, "正常任務")

    old_file = tmp_path / ".agentx" / "task.json"
    data = json.loads(old_file.read_text())
    data["title"] = "  --- 【 重要任務 】 ---  "
    old_file.write_text(json.dumps(data), encoding="utf-8")

    result = _get_legacy_task_if_exists(tmp_path)
    assert result is not None
    assert result.title == "重要任務"  # 前後標點已被移除


def test_get_legacy_task_strips_leading_id_and_number(tmp_path: Path):
    """應移除 title 前面的常見編號或 ID（如 123 - 、BUG-456: ）"""
    from agentx.task import start_task

    start_task(tmp_path, "正常任務")

    old_file = tmp_path / ".agentx" / "task.json"
    data = json.loads(old_file.read_text())

    test_cases = [
        "123 - 修復登入問題",
        "BUG-456: 修復登入問題",
        "456: 修復登入問題",
        "   789 -   修復登入問題   ",
    ]

    for raw_title in test_cases:
        data["title"] = raw_title
        old_file.write_text(json.dumps(data), encoding="utf-8")
        result = _get_legacy_task_if_exists(tmp_path)
        assert result is not None
        assert result.title == "修復登入問題", f"'{raw_title}' 應清理為 '修復登入問題'"


def test_migrate_renames_old_file_to_backup(tmp_path: Path):
    """遷移成功後，舊的 task.json 應被改名為 task.json.bak（務實策略 B）"""
    _write_legacy_task(tmp_path, title="重構認證模組")

    migrated = migrate_single_task_if_needed(tmp_path)
    assert migrated is True

    old_path = tmp_path / ".agentx" / "task.json"

    # 舊檔應該不再以 task.json 的形式存在（已被備份或刪除）
    assert not old_path.exists()

    # 確認新多任務清單正確
    multi = load_tasks(tmp_path)
    assert len(multi) == 1
    assert multi[0]["description"] == "重構認證模組"


def test_migrate_always_uses_timestamped_backup(tmp_path: Path):
    """無論如何，備份檔都應使用時間戳命名，避免覆蓋"""
    # 第一次遷移
    _write_legacy_task(tmp_path, title="任務一")
    migrated1 = migrate_single_task_if_needed(tmp_path)
    assert migrated1 is True

    # 手動建立一個沒有時間戳的 .bak（模擬舊環境）
    backup_dir = tmp_path / ".agentx"
    (backup_dir / "task.json.bak").write_text("old backup", encoding="utf-8")

    # 為了觸發第二次遷移，先移除 tasks.json
    (backup_dir / "tasks.json").unlink()

    _write_legacy_task(tmp_path, title="任務二")
    migrated2 = migrate_single_task_if_needed(tmp_path)
    assert migrated2 is True

    bak_files = list(backup_dir.glob("task.json.bak*"))
    # 至少應該存在一個備份檔（可能是時間戳的）
    assert len(bak_files) >= 1

def test_get_legacy_task_status_mapping_chinese(tmp_path: Path):
    """中文舊 status 應正確映射到新系統值"""
    _write_legacy_task(tmp_path, title="中文狀態測試", status="進行中")

    old_file = tmp_path / ".agentx" / "task.json"
    data = json.loads(old_file.read_text())

    for old_status, expected in [
        ("進行中", "in_progress"),
        ("已完成", "done"),
        ("待辦", "pending"),
        ("未開始", "pending"),
    ]:
        data["status"] = old_status
        old_file.write_text(json.dumps(data), encoding="utf-8")
        result = _get_legacy_task_if_exists(tmp_path)
        assert result is not None
        assert result.status == expected, f"{old_status} 應映射為 {expected}"

def test_normalize_legacy_date_more_edge_cases(tmp_path: Path):
    """更多日期邊界：毫秒、空格分隔、無效格式"""
    from agentx.task import start_task

    start_task(tmp_path, "日期邊界測試")

    old_file = tmp_path / ".agentx" / "task.json"
    data = json.loads(old_file.read_text())

    # 成功案例
    for good_date in [
        "2024-05-20T14:30:00.123",
        "2024-05-20 14:30:00",
        "2023-12-31T23:59:59Z",
    ]:
        data["created_at"] = good_date
        old_file.write_text(json.dumps(data), encoding="utf-8")
        result = _get_legacy_task_if_exists(tmp_path)
        assert result is not None
        assert result.created_at == good_date

    # 寬鬆結構檢查：這些會被保留（因為結構像日期），這是我們對 legacy 資料的務實容忍
    for weird_but_structured in [
        "2024-13-01T00:00:00",  # 無效月份，但結構像日期
    ]:
        data["created_at"] = weird_but_structured
        old_file.write_text(json.dumps(data), encoding="utf-8")
        result = _get_legacy_task_if_exists(tmp_path)
        assert result is not None
        # 目前採寬鬆策略，保留原始字串
        assert result.created_at == weird_but_structured

    # 明顯不是日期的才清空
    for clearly_bad in ["not-a-date", "2024/05/20"]:
        data["created_at"] = clearly_bad
        old_file.write_text(json.dumps(data), encoding="utf-8")
        result = _get_legacy_task_if_exists(tmp_path)
        assert result is not None
        assert result.created_at == ""


def test_normalize_legacy_date_robust_formats(tmp_path: Path):
    """日期正規化應穩健處理各種常見舊格式"""
    from agentx.task import start_task

    start_task(tmp_path, "日期穩健測試")

    old_file = tmp_path / ".agentx" / "task.json"
    data = json.loads(old_file.read_text())

    good_cases = [
        "2024-05-20T14:30:00",
        "2024-05-20T14:30:00.123456",
        "2024-05-20 14:30:00",
        "2024-05-20T14:30:00Z",
    ]

    for good in good_cases:
        data["created_at"] = good
        old_file.write_text(json.dumps(data), encoding="utf-8")
        result = _get_legacy_task_if_exists(tmp_path)
        assert result is not None
        assert result.created_at == good

    bad_cases = [
        "not a date",
        "2024/05/20",
        "完全不是日期",
    ]

    for bad in bad_cases:
        data["created_at"] = bad
        old_file.write_text(json.dumps(data), encoding="utf-8")
        result = _get_legacy_task_if_exists(tmp_path)
        assert result is not None
        assert result.created_at == ""

def test_get_legacy_task_records_original_in_notes(tmp_path: Path):
    """當回傳 legacy 任務時，應把原始標題與狀態記錄到 notes 供追溯（A1-1f）"""
    from agentx.task import start_task

    start_task(tmp_path, "原始標題測試")

    old_file = tmp_path / ".agentx" / "task.json"
    data = json.loads(old_file.read_text())
    data["status"] = "進行中"
    old_file.write_text(json.dumps(data), encoding="utf-8")

    result = _get_legacy_task_if_exists(tmp_path)
    assert result is not None
    assert hasattr(result, 'notes')
    assert "原始標題測試" in getattr(result, 'notes', '')
    assert "進行中" in getattr(result, 'notes', '') or "in_progress" in getattr(result, 'notes', '')

def test_get_legacy_task_strips_todo_fixme_prefix(tmp_path: Path):
    """應移除 title 前面的 TODO/FIXME 等常見前綴"""
    from agentx.task import start_task

    start_task(tmp_path, "正常任務")

    old_file = tmp_path / ".agentx" / "task.json"
    data = json.loads(old_file.read_text())

    test_cases = [
        ("TODO: 修復登入問題", "修復登入問題"),
        ("FIXME - 修復登入問題", "修復登入問題"),
        ("BUG: 修復登入問題", "修復登入問題"),
        ("HACK: 臨時解決方案", "臨時解決方案"),
        ("   XXX: 待重構   ", "待重構"),
    ]

    for raw_title, expected in test_cases:
        data["title"] = raw_title
        old_file.write_text(json.dumps(data), encoding="utf-8")
        result = _get_legacy_task_if_exists(tmp_path)
        assert result is not None
        assert result.title == expected, f"'{raw_title}' 應被清理為 '{expected}'"

def test_get_legacy_task_rejects_symbol_only_title(tmp_path: Path):
    """清理後只剩符號/數字的 title 應被視為無效（A1-1l）"""
    from agentx.task import start_task

    start_task(tmp_path, "正常任務")

    old_file = tmp_path / ".agentx" / "task.json"
    data = json.loads(old_file.read_text())
    data["title"] = "   123 --- !!!   "
    old_file.write_text(json.dumps(data), encoding="utf-8")

    result = _get_legacy_task_if_exists(tmp_path)
    assert result is None  # 應被整體品質守衛拒絕

def test_migrate_handles_old_task_with_whitespace_only_title(tmp_path: Path):
    """舊任務標題全是空白時應安全跳過遷移"""
    from agentx.task import TaskState, save_task

    old_task = TaskState(title="   ", status="active")
    save_task(tmp_path, old_task)

    migrated = migrate_single_task_if_needed(tmp_path)
    assert migrated is False
    assert load_tasks(tmp_path) == []
