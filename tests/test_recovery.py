from agentx.errors import ErrorContext, ErrorType, RecoveryAction
from agentx.recovery import RecoveryPlaybook


def make_error(tool: str, etype: ErrorType, count: int = 1) -> list[ErrorContext]:
    return [ErrorContext(error_type=etype, tool_name=tool, error_message="fail") for _ in range(count)]


def test_playbook_prefers_backtrack_on_repeated_same_tool():
    playbook = RecoveryPlaybook()
    history = make_error("search_replace", ErrorType.EXECUTION_ERROR, 4)

    suggestions = playbook.generate_suggestions(history[-1], history)

    actions = [s.action for s in suggestions]
    assert RecoveryAction.BACKTRACK in actions
    assert any(s.confidence > 0.7 for s in suggestions)


def test_playbook_escalates_when_too_many_errors():
    playbook = RecoveryPlaybook()
    history = make_error("search_replace", ErrorType.CALL_ERROR, 8)

    suggestions = playbook.generate_suggestions(history[-1], history)

    actions = [s.action for s in suggestions]
    assert RecoveryAction.ESCALATE_TO_USER in actions


def test_playbook_gives_change_strategy_for_execution_errors():
    playbook = RecoveryPlaybook()
    history = make_error("search_replace", ErrorType.EXECUTION_ERROR, 3)

    suggestions = playbook.generate_suggestions(history[-1], history)

    actions = [s.action for s in suggestions]
    assert RecoveryAction.CHANGE_STRATEGY in actions or RecoveryAction.SIMPLIFY_SCOPE in actions
