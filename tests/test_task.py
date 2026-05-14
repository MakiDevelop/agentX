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
