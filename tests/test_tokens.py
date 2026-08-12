"""Token accounting tests.

The context budget decides when to compact. It used to estimate `chars // 4`,
the English rule of thumb, on content that is largely Traditional Chinese.
Measured on realistic agentX conversation text (52% CJK): 994 estimated vs a
2539 floor from any real tokenizer — 2.6x low. Because `_maybe_auto_compact`
fires at 82% of the limit, under-counting by 2.6x meant compaction ran only
after the real context had already exceeded the window it was protecting.
"""

from __future__ import annotations

from agentx.tokens import (
    MESSAGE_OVERHEAD_TOKENS,
    TokenCounter,
    count_dense_chars,
    estimate_messages_tokens,
    estimate_tokens,
)

#: Representative of what agentX actually carries: Chinese prose with embedded
#: identifiers and paths.
CJK_HEAVY = (
    "請幫我把 agentX 的 headless 模式改成可以在長任務中自動壓縮上下文，"
    "並且保留任務清單與已修改檔案清單。"
)
LATIN_ONLY = "Please refactor the headless mode so that it compacts context during long runs."


def test_cjk_costs_far_more_than_the_english_heuristic() -> None:
    """The specific bug: chars//4 on Chinese text."""
    naive = len(CJK_HEAVY) // 4
    estimate = estimate_tokens(CJK_HEAVY)

    assert estimate > naive * 2, f"expected >2x the naive estimate, got {estimate} vs {naive}"


def test_estimate_is_at_least_one_token_per_cjk_character() -> None:
    """No mainstream tokenizer emits fewer than one token per ideograph, so an
    estimate below that count is guaranteed wrong in the dangerous direction."""
    dense = count_dense_chars(CJK_HEAVY)

    assert dense > 0
    assert estimate_tokens(CJK_HEAVY) >= dense


def test_latin_text_keeps_the_familiar_ratio() -> None:
    """The correction must not wreck the case the old heuristic got right."""
    estimate = estimate_tokens(LATIN_ONLY)
    naive = len(LATIN_ONLY) // 4

    assert abs(estimate - naive) <= 2


def test_empty_and_whitespace() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens(" ") >= 0


def test_messages_include_per_message_overhead() -> None:
    messages = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "ok"}]

    total = estimate_messages_tokens(messages)

    assert total >= 2 * MESSAGE_OVERHEAD_TOKENS


def test_counter_is_neutral_before_any_observation() -> None:
    counter = TokenCounter()

    assert counter.calibration == 1.0
    assert counter.estimate(CJK_HEAVY) == estimate_tokens(CJK_HEAVY)


def test_counter_calibrates_toward_reported_usage() -> None:
    """Ollama's prompt_eval_count is ground truth; the estimator should move
    toward it rather than keep guessing."""
    counter = TokenCounter()
    messages = [{"role": "user", "content": CJK_HEAVY}]
    raw = estimate_messages_tokens(messages)

    for _ in range(20):
        counter.observe(messages, raw * 2)

    assert 1.8 < counter.calibration < 2.2, counter.calibration
    assert counter.observations == 20


def test_counter_ignores_unreported_usage() -> None:
    """Backends that report nothing return 0. Treating that as a real count
    would drive calibration to its floor and effectively disable compaction."""
    counter = TokenCounter()
    messages = [{"role": "user", "content": CJK_HEAVY}]

    for _ in range(10):
        counter.observe(messages, 0)

    assert counter.calibration == 1.0
    assert counter.observations == 0


def test_calibration_is_bounded() -> None:
    """One absurd observation must not be able to disable the budget."""
    counter = TokenCounter()
    messages = [{"role": "user", "content": CJK_HEAVY}]

    for _ in range(50):
        counter.observe(messages, 10_000_000)

    assert counter.calibration <= TokenCounter.MAX_CALIBRATION

    counter2 = TokenCounter()
    for _ in range(50):
        counter2.observe(messages, 1)

    assert counter2.calibration >= TokenCounter.MIN_CALIBRATION


def test_compaction_now_triggers_before_the_limit_is_exceeded() -> None:
    """End-to-end statement of the bug that motivated this module.

    With a 8192-token window and compaction at 82%, build a Chinese-heavy
    context sized so the OLD estimator would consider it safe. The new estimator
    must recognise it as over budget.
    """
    limit = 8192
    threshold = limit * 0.82
    # 400 repetitions ≈ 23,600 chars. chars//4 calls that 5,900 tokens — under
    # the 6,717 compaction threshold, so the old code would keep going. A real
    # tokenizer sees ~17,900: more than twice the entire 8,192 window.
    content = CJK_HEAVY * 400
    messages = [{"role": "user", "content": content}]

    old_estimate = len(content) // 4
    new_estimate = estimate_messages_tokens(messages)

    assert old_estimate < threshold, "test fixture no longer reproduces the old blind spot"
    assert new_estimate > threshold, "new estimator still under-counts CJK context"
