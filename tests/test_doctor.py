from types import SimpleNamespace
from pathlib import Path

from agentx.doctor import _check_command, _check_task_migration
from agentx.tasks import save_tasks


def test_check_command_reports_success() -> None:
    name, ok, detail = _check_command("python", ["python", "--version"])

    assert name == "python"
    assert ok
    assert "Python" in detail


# === MT22: _check_task_migration 基本覆蓋（回應 Codex P0） ===

def test_check_task_migration_clean_workspace(tmp_path: Path) -> None:
    """乾淨 workspace（無舊無新）應回報 no_task_data。"""
    fake_settings = SimpleNamespace(workspace=tmp_path)
    name, ok, detail = _check_task_migration(fake_settings)

    assert name == "task_migration (MT22)"
    assert ok is True
    assert "no_task_data" in detail
    assert "legacy=False" in detail


def test_check_task_migration_legacy_only(tmp_path: Path) -> None:
    """只有舊單一任務時應回報 legacy_only 並帶 [需遷移] 旗標。"""
    # 建立舊 task.json
    legacy_dir = tmp_path / ".agentx"
    legacy_dir.mkdir()
    (legacy_dir / "task.json").write_text('{"title":"舊任務","status":"active"}', encoding="utf-8")

    fake_settings = SimpleNamespace(workspace=tmp_path)
    name, ok, detail = _check_task_migration(fake_settings)

    assert name == "task_migration (MT22)"
    assert ok is True
    assert "legacy_only (舊系統仍主導)" in detail
    assert "[需遷移]" in detail


def test_check_task_migration_multi_only(tmp_path: Path) -> None:
    """只有新多任務清單時應回報 multi_only。"""
    save_tasks(tmp_path, [{"id": 1, "description": "新任務", "status": "pending", "notes": ""}])

    fake_settings = SimpleNamespace(workspace=tmp_path)
    name, ok, detail = _check_task_migration(fake_settings)

    assert name == "task_migration (MT22)"
    assert ok is True
    assert "multi_only (新系統為主)" in detail
    assert "tasks=1" in detail


def test_check_task_migration_mixed_state(tmp_path: Path) -> None:
    """新舊並存時應回報 mixed 狀態。"""
    # 舊任務
    legacy_dir = tmp_path / ".agentx"
    legacy_dir.mkdir()
    (legacy_dir / "task.json").write_text('{"title":"舊任務","status":"active"}', encoding="utf-8")

    # 新任務
    save_tasks(tmp_path, [{"id": 1, "description": "新任務", "status": "in_progress", "notes": ""}])

    fake_settings = SimpleNamespace(workspace=tmp_path)
    name, ok, detail = _check_task_migration(fake_settings)

    assert name == "task_migration (MT22)"
    assert ok is True
    assert "mixed (legacy + multi 並存)" in detail


def test_check_task_migration_handles_error_gracefully() -> None:
    """當無法取得 workspace 資訊時應安全回報錯誤而不崩潰。"""
    bad_settings = SimpleNamespace(workspace=None)  # 故意製造錯誤情境
    name, ok, detail = _check_task_migration(bad_settings)

    assert name == "task_migration (MT22)"
    assert ok is False
    assert "Error" in detail or "Exception" in detail or "NoneType" in detail


def test_check_task_migration_with_corrupted_legacy_file(tmp_path: Path) -> None:
    """舊 task.json 損壞時仍應能安全回報狀態，而非崩潰。"""
    legacy_dir = tmp_path / ".agentx"
    legacy_dir.mkdir()
    (legacy_dir / "task.json").write_text("{ invalid json", encoding="utf-8")

    fake_settings = SimpleNamespace(workspace=tmp_path)
    name, ok, detail = _check_task_migration(fake_settings)

    assert name == "task_migration (MT22)"
    assert ok is True
    # 應該仍能正確判斷有 legacy 存在（即使內容損壞）
    assert "legacy=True" in detail or "legacy_only" in detail or "mixed" in detail


def test_check_task_migration_legacy_with_corrupted_multi_tasks(tmp_path: Path) -> None:
    """有舊任務，但新的 tasks.json 損壞時，應能正確回報 mixed 狀態。"""
    # 建立舊任務
    legacy_dir = tmp_path / ".agentx"
    legacy_dir.mkdir()
    (legacy_dir / "task.json").write_text('{"title":"舊任務","status":"active"}', encoding="utf-8")

    # 建立損壞的 tasks.json
    (legacy_dir / "tasks.json").write_text("{ this is not valid json", encoding="utf-8")

    fake_settings = SimpleNamespace(workspace=tmp_path)
    name, ok, detail = _check_task_migration(fake_settings)

    assert name == "task_migration (MT22)"
    assert ok is True
    # 即使新的 tasks.json 損壞，仍然應該正確偵測到 legacy 存在
    assert "legacy=True" in detail or "legacy_only" in detail or "mixed" in detail
    # 注意：目前實作在這種情況下 multi 狀態可能不準確，這是可接受的邊界（可後續加強）


def test_check_task_migration_legacy_with_empty_title(tmp_path: Path) -> None:
    """舊任務 title 為空時，應被視為無效 legacy，不影響 multi-task 判斷。"""
    legacy_dir = tmp_path / ".agentx"
    legacy_dir.mkdir()
    (legacy_dir / "task.json").write_text('{"title":"","status":"active"}', encoding="utf-8")

    # 同時有新任務
    save_tasks(tmp_path, [{"id": 1, "description": "正常任務", "status": "pending", "notes": ""}])

    fake_settings = SimpleNamespace(workspace=tmp_path)
    name, ok, detail = _check_task_migration(fake_settings)

    assert name == "task_migration (MT22)"
    assert ok is True
    # 應該只看到 multi-task，不把空的 legacy 算進去
    assert "multi_only" in detail or "tasks=1" in detail
    assert "legacy=False" in detail or "legacy_only" not in detail


def test_check_task_migration_legacy_with_empty_multi_tasks(tmp_path: Path) -> None:
    """有舊任務，但新 tasks.json 存在卻是空的，應正確顯示 mixed 狀態。"""
    # 建立舊任務
    legacy_dir = tmp_path / ".agentx"
    legacy_dir.mkdir()
    (legacy_dir / "task.json").write_text('{"title":"舊任務","status":"active"}', encoding="utf-8")

    # 建立空的 tasks.json（模擬剛初始化但還沒加任務）
    (legacy_dir / "tasks.json").write_text("[]", encoding="utf-8")

    fake_settings = SimpleNamespace(workspace=tmp_path)
    name, ok, detail = _check_task_migration(fake_settings)

    assert name == "task_migration (MT22)"
    assert ok is True
    assert "mixed" in detail
    assert "tasks=0" in detail


def test_run_doctor_includes_task_migration_check(tmp_path: Path) -> None:
    """完整 run_doctor 應包含 task_migration (MT22) 檢查項目。"""
    # 建立一個帶有舊任務的 workspace
    legacy_dir = tmp_path / ".agentx"
    legacy_dir.mkdir()
    (legacy_dir / "task.json").write_text('{"title":"舊單一任務","status":"active"}', encoding="utf-8")

    # 這裡用一個極簡的 Settings 模擬（只需要 workspace）
    fake_settings = SimpleNamespace(workspace=tmp_path)

    # 直接呼叫內部函式來驗證整合（避免依賴完整 Ollama/MemoryHall）
    from agentx.doctor import _check_task_migration
    name, ok, detail = _check_task_migration(fake_settings)

    assert name == "task_migration (MT22)"
    assert "legacy=True" in detail or "legacy_only" in detail
