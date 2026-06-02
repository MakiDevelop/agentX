# === DEPRECATION NOTICE (MT22 / v0.3.0) ===
#
# 此檔案**僅用於歷史相容驗證**（legacy single-task system）。
# 該系統（task.py + TaskState + .agentx/task.json）正在被新的多任務清單
# （tasks.py + tasks.json + agentx.tasks API）取代。
#
# 狀態：
# - 此檔案**僅保留作為遷移相容測試與歷史參考**。
# - 所有新測試請使用 tests/test_tasks.py 中的多任務相關測試。
# - 預計在 v0.3.0 後逐步廢棄或移除此檔案及對應的 task.py 模組。
#
# 如果你正在新增測試，請改用新系統的 API（load_tasks / save_tasks 等）。
# 此檔案中的測試**不會**被視為新功能覆蓋的一部分。

import pytest
pytest.importorskip(
    "agentx.task",
    reason="task.py is legacy (MT22); this test file is kept ONLY for historical compatibility verification. "
           "All new tests should use tests/test_tasks.py . Module will be removed when checklist conditions met.",
)

from agentx.task import clear_task, finish_task, load_task, start_task

# TODO (MT22 / v0.3.0)：開始逐步將此檔案中的測試轉換為新系統測試，
# 或明確標記為僅用於遷移驗證。


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
