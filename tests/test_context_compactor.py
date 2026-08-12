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

    # 找包含任務清單的 system message（v2 一定會有）
    summary_content = ""
    for m in new_msgs:
        if "目前任務清單" in m.get("content", ""):
            summary_content = m.get("content", "")
            break

    assert "【目前任務清單（最重要）】" in summary_content
    assert "重構認證" in summary_content
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


def test_compaction_brings_a_long_cjk_session_back_under_budget() -> None:
    """The point of the whole budget: compaction must actually rescue a session.

    Written against real token accounting (agentx.tokens) rather than the old
    chars//4 estimate. Under the old estimate a session like this one read as
    ~5.5k tokens and never triggered compaction at all, while really sitting at
    ~22k — nearly three times the 8,192 window.
    """
    from agentx.context_compactor import HeuristicContextCompactor
    from agentx.tokens import estimate_messages_tokens

    cjk = "請幫我把 agentX 的 headless 模式改成可以在長任務中自動壓縮上下文，並保留任務清單。"
    messages: list[dict[str, object]] = [
        {"role": "system", "content": "repo context " + cjk * 5},
        {"role": "system", "content": "memory context " + cjk * 5},
        {"role": "system", "content": "system prompt " + cjk * 5},
    ]
    for index in range(60):
        messages.append({"role": "user", "content": f"步驟 {index} " + cjk * 3})
        messages.append({"role": "assistant", "content": f'{{"type":"reflect","focus":"{index}"}}'})
        messages.append({"role": "tool", "content": f"檔案內容 {index} " + cjk * 4})

    tasks = [{"id": 1, "description": "重構 headless", "status": "in_progress", "notes": ""}]
    limit_tokens = 8192
    compaction_threshold = limit_tokens * 0.82

    before = estimate_messages_tokens(messages)  # type: ignore[arg-type]
    assert before > limit_tokens, "fixture no longer represents an over-budget session"

    compactor = HeuristicContextCompactor()
    compacted, _summary = compactor.compact(messages, tasks, keep_last=5)
    after = estimate_messages_tokens(compacted)

    assert after < compaction_threshold, (
        f"compaction left {after} tokens, still above the {compaction_threshold:.0f} "
        "threshold — the loop would compact again every turn"
    )

    # Repeated compaction must not grow the context, or auto-compact oscillates.
    twice, _ = compactor.compact(compacted, tasks, keep_last=5)
    assert estimate_messages_tokens(twice) <= after
