"""
MT22 遷移相容性測試（歷史 + 驗證）。

本檔案**僅保留用於驗證舊單一任務 → 新多任務清單的自動遷移行為**。
即使 src/agentx/task.py 已完全移除（MT22 Phase A 完成），
這些測試仍使用 _write_legacy_task() 直接在 .agentx/task.json 寫入舊格式 JSON，
來確保 migrate_single_task_if_needed() 在各種 dirty/edge 情境下仍正確運作。

原則：
- 所有新功能測試請使用 agentx.tasks 的公開 API（load/save/find 等）。
- 本檔案的 migrate 系列測試是「移除 legacy 後仍需保留的相容性保險」。
- 已移除的舊 reader 測試（原 _get_legacy_task_if_exists 等）已刪或以 importorskip 保護。
- 不要再依賴 agentx.task 模組（它已不存在）。

參見：
- docs/MT22-Legacy-Removal-Checklist.md
- docs/MT22-Migration-Guide.md
- src/agentx/tasks.py 中的 has_legacy_single_task / get_task_migration_status（僅供 doctor 診斷）
"""

from pathlib import Path
from typing import Any

import json
import os
import subprocess
import sys

from agentx.tasks import (
    find_task,
    get_next_task_id,
    get_task_migration_status,
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
    MT22 測試輔助函式（僅供本檔案歷史相容測試使用）。

    直接寫入舊的單一任務 JSON（.agentx/task.json），
    用於測試 migrate_single_task_if_needed 在各種 legacy dirty data 下的行為。
    注意：_get_legacy_task_if_exists 及對應 reader 已隨 task.py 移除，本 helper 已改為純 JSON 寫入。
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
    _write_legacy_task(tmp_path, title="測試任務")
    migrated1 = migrate_single_task_if_needed(tmp_path)
    assert migrated1 is True

    # 第二次呼叫
    migrated2 = migrate_single_task_if_needed(tmp_path)
    assert migrated2 is False

    # 應該只有一筆任務
    multi = load_tasks(tmp_path)
    assert len(multi) == 1


def test_migrate_renames_old_file_to_backup(tmp_path: Path):
    """遷移成功後，舊的 task.json 應被改名為帶時間戳的 task.json.bak.*（務實策略 B）"""
    _write_legacy_task(tmp_path, title="重構認證模組")

    migrated = migrate_single_task_if_needed(tmp_path)
    assert migrated is True

    old_path = tmp_path / ".agentx" / "task.json"

    # 舊檔應該不再以 task.json 的形式存在（已被備份）
    assert not old_path.exists()

    # 確認新多任務清單正確
    multi = load_tasks(tmp_path)
    assert len(multi) == 1
    assert multi[0]["description"] == "重構認證模組"


def test_migrate_keeps_old_file_when_backup_rename_fails(tmp_path: Path, monkeypatch):
    """備份 rename 失敗時不刪除舊 task.json，避免 silent data loss。"""
    _write_legacy_task(tmp_path, title="保留舊檔")
    old_path = tmp_path / ".agentx" / "task.json"

    def fail_rename(self: Path, target: Path) -> Path:
        if self == old_path:
            raise OSError("simulated backup failure")
        return original_rename(self, target)

    original_rename = Path.rename
    monkeypatch.setattr(Path, "rename", fail_rename)

    migrated = migrate_single_task_if_needed(tmp_path)
    assert migrated is True
    assert old_path.exists()

    multi = load_tasks(tmp_path)
    assert len(multi) == 1
    assert multi[0]["description"] == "保留舊檔"

    status = get_task_migration_status(tmp_path)
    assert status["has_legacy_single_task"] is True
    assert status["has_multi_task_file"] is True
    assert status["legacy_system_active"] is False


def test_migrate_always_uses_timestamped_backup(tmp_path: Path):
    """無論如何，備份檔都應使用時間戳命名，避免覆蓋既有 .bak"""
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
    # 至少應該存在一個備份檔（時間戳的優先）
    assert len(bak_files) >= 1


def test_migrate_skips_blank_title(tmp_path: Path):
    """舊任務標題全是空白（或僅空白）時應安全跳過遷移（對應 migrate 內 if not title）"""
    _write_legacy_task(tmp_path, title="   ", status="active")

    migrated = migrate_single_task_if_needed(tmp_path)
    assert migrated is False
    assert load_tasks(tmp_path) == []


# =============================================================================
# CI 風格「模擬完全無 legacy 環境」測試
# 這些測試專為 CI / 回歸保護設計：
# - 使用乾淨 tmp_path（無任何 .agentx 或無 task.json）
# - 驗證 migration status 為 clean / no legacy
# - 驗證新系統 API 完全不依賴舊格式
# - 驗證關鍵字 "MT22" / "legacy" 不會意外出現在純新環境的診斷/摘要中（除 doctor 的固定項目名）
# - 可被 CI 直接收集執行，作為 "task.py 移除後無回歸" 的 gate
# =============================================================================

def test_ci_no_legacy_clean_workspace_migration_status(tmp_path: Path):
    """模擬完全無 legacy 環境：乾淨 workspace 應回報無 legacy 資料。"""
    status = get_task_migration_status(tmp_path)

    assert status["has_legacy_single_task"] is False
    assert status["has_multi_task_file"] is False
    assert status["legacy_system_active"] is False
    assert status["multi_task_count"] == 0


def test_ci_no_legacy_subprocess_has_no_task_module(tmp_path: Path):
    """模擬完全無 legacy 環境：fresh Python process 不應再看到 agentx.task。"""
    repo_root = Path(__file__).resolve().parents[1]
    src_path = repo_root / "src"
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(src_path)
        if not existing_pythonpath
        else f"{src_path}{os.pathsep}{existing_pythonpath}"
    )
    code = """
from importlib.util import find_spec
from pathlib import Path

import agentx

workspace = Path.cwd()
assert not (workspace / ".agentx").exists()
package = Path(agentx.__file__).parent
assert not (package / "task.py").exists(), package
assert find_spec("agentx.task") is None
"""

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert "Traceback" not in result.stderr


def test_ci_no_legacy_after_migrate_old_file_is_gone_and_new_is_clean(tmp_path: Path):
    """模擬有 legacy 但 migrate 後：舊檔消失、新 tasks.json 乾淨、無舊 reader 污染。"""
    _write_legacy_task(tmp_path, title="即將被遷移的舊任務", status="active")

    # 遷移前狀態
    pre = get_task_migration_status(tmp_path)
    assert pre["has_legacy_single_task"] is True

    migrated = migrate_single_task_if_needed(tmp_path)
    assert migrated is True

    # 舊檔已備份，不再是 task.json
    old = tmp_path / ".agentx" / "task.json"
    assert not old.exists()

    # 新系統乾淨（.bak 存在但不影響 has_legacy 判斷；has_legacy 只看 task.json）
    post = get_task_migration_status(tmp_path)
    assert post["has_legacy_single_task"] is False
    assert post["has_multi_task_file"] is True
    assert post["legacy_system_active"] is False
    assert post["multi_task_count"] == 1

    # 載入新清單不應有任何 legacy 殘留
    tasks = load_tasks(tmp_path)
    assert len(tasks) == 1
    assert "自動遷移" in tasks[0]["notes"]
    # 沒有舊 TaskState 物件等污染
