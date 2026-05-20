# === DEPRECATION NOTICE (MT22) ===
# 此檔案測試的是舊的單一任務系統（task.py + TaskState），
# 該系統正在被新的多任務清單（tasks.py）取代。
# 這些測試僅作為過渡期相容與遷移驗證之用。
# 預計在後續版本中大幅簡化或移除。
#
# 請改用 tests/test_tasks.py 中的多任務測試。

from agentx.task import clear_task, finish_task, load_task, start_task


def test_task_lifecycle(tmp_path):
    task = start_task(tmp_path, "demo")
    assert task.active

    loaded = load_task(tmp_path)
    assert loaded.title == "demo"
    assert loaded.status == "active"

    done = finish_task(tmp_path)
    assert done.status == "done"

    cleared = clear_task(tmp_path)
    assert not cleared.title
