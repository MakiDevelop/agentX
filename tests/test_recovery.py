from agentx.errors import ErrorContext, ErrorType, RecoveryAction
from agentx.recovery import RecoveryPlaybook


def make_error(tool: str, etype: ErrorType, msg: str = "fail", count: int = 1) -> list[ErrorContext]:
    return [ErrorContext(error_type=etype, tool_name=tool, error_message=msg) for _ in range(count)]


def test_playbook_prefers_backtrack_on_repeated_same_tool():
    playbook = RecoveryPlaybook()
    history = make_error("search_replace", ErrorType.EXECUTION_ERROR, count=4)

    suggestions = playbook.generate_suggestions(history[-1], history)

    actions = [s.action for s in suggestions]
    assert RecoveryAction.BACKTRACK in actions
    assert any(s.confidence > 0.7 for s in suggestions)


def test_playbook_escalates_when_too_many_errors():
    playbook = RecoveryPlaybook()
    history = make_error("search_replace", ErrorType.CALL_ERROR, count=8)

    suggestions = playbook.generate_suggestions(history[-1], history)

    actions = [s.action for s in suggestions]
    assert RecoveryAction.ESCALATE_TO_USER in actions


def test_playbook_detects_same_file_repeated_failure():
    """同一個檔案連續 edit 失敗應該優先建議 BACKTRACK"""
    playbook = RecoveryPlaybook()
    history = make_error("search_replace", ErrorType.EXECUTION_ERROR, msg="search_replace on src/auth.py failed", count=4)

    suggestions = playbook.generate_suggestions(history[-1], history)

    actions = [s.action for s in suggestions]
    assert RecoveryAction.BACKTRACK in actions


def test_playbook_detects_tool_oscillation():
    """在兩個工具間來回失敗應該建議 CHANGE_STRATEGY"""
    playbook = RecoveryPlaybook()
    history = []
    tools = ["search_replace", "insert_code"] * 4
    for t in tools:
        history.append(ErrorContext(error_type=ErrorType.EXECUTION_ERROR, tool_name=t, error_message="fail"))

    suggestions = playbook.generate_suggestions(history[-1], history)

    actions = [s.action for s in suggestions]
    assert RecoveryAction.CHANGE_STRATEGY in actions


def test_playbook_suggests_reprioritize_when_tasks_exist_and_stuck():
    playbook = RecoveryPlaybook()
    history = make_error("search_replace", ErrorType.EXECUTION_ERROR, count=7)
    tasks = [{"id": 1, "description": "重構", "status": "in_progress"}]

    suggestions = playbook.generate_suggestions(history[-1], history, tasks=tasks)

    actions = [s.action for s in suggestions]
    assert RecoveryAction.REPRIORITIZE in actions or RecoveryAction.ESCALATE_TO_USER in actions
