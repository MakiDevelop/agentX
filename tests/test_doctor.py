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
