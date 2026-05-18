from agentx.context_compactor import HeuristicContextCompactor


def test_heuristic_compactor_basic():
    compactor = HeuristicContextCompactor()

    messages = [
        {"role": "system", "content": "Repo bootstrap..."},
        {"role": "system", "content": "Memory Hall context..."},
        {"role": "user", "content": "請幫我重構認證模組"},
        {"role": "assistant", "content": '{"type":"reflect","focus":"先規劃"}'},
        {"role": "system", "content": "=== Reflection ===\n規劃如下..."},
        {"role": "user", "content": "繼續"},
        {"role": "tool", "content": "search_replace 成功"},
    ]

    tasks = [
        {"id": 1, "description": "重構認證", "status": "in_progress", "notes": ""},
        {"id": 2, "description": "加 rate limit", "status": "pending", "notes": ""},
    ]

    new_msgs, result = compactor.compact(messages, tasks, keep_last=3)

    # 摘要會被放在 bootstrap 之後、tail 之前的那個 system message
    summary_msg = new_msgs[-4] if len(new_msgs) > 3 else new_msgs[-1]
    assert "【目前任務清單】" in summary_msg.get("content", "")
    assert "重構認證" in summary_msg.get("content", "")
    assert "已執行 Context Compaction v2" in result


def test_compactor_with_empty_tasks():
    compactor = HeuristicContextCompactor()
    messages = [{"role": "user", "content": "hi"}]

    new_msgs, result = compactor.compact(messages, [], keep_last=2)

    # 摘要在倒數第 2 或第 3 個位置（bootstrap + summary + tail）
    summary_content = ""
    for m in new_msgs:
        if "Session 已壓縮" in m.get("content", "") or "任務清單" in m.get("content", ""):
            summary_content = m.get("content", "")
            break

    assert "目前沒有進行中的任務" in summary_content or "Session 已壓縮" in summary_content
    assert len(new_msgs) > 0
