# === DEPRECATION NOTICE (MT22 / v0.3.0) ===
#
# 此檔案幾乎完全在測試舊的單一任務系統（task.py + TaskState）。
# 該系統正在被新的多任務清單（tasks.py + tasks.json）取代。
#
# 狀態：
# - 此檔案已被標記為技術債。
# - 預計在 v0.3.0 後逐步廢棄或大幅重寫。
# - 目前僅保留作為遷移相容測試與歷史參考。
#
# 請優先使用 tests/test_tasks.py 中的多任務相關測試。
#
# 如果你正在新增測試，請改用新系統的 API。

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
