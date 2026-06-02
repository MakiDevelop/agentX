from agentx.approval import ApprovalMode, ApprovalPolicy, normalize_approval_mode
from agentx.safety import Risk


def test_green_is_always_allowed() -> None:
    policy = ApprovalPolicy(mode=ApprovalMode.OFF)
    assert policy.decide("read_file", {}, Risk.GREEN)


def test_red_is_always_blocked() -> None:
    policy = ApprovalPolicy(mode=ApprovalMode.AUTO)
    assert not policy.decide("danger", {}, Risk.RED)


def test_yellow_auto_allows() -> None:
    policy = ApprovalPolicy(mode=ApprovalMode.AUTO)
    assert policy.decide("memory_write", {}, Risk.YELLOW)


def test_yellow_off_blocks() -> None:
    policy = ApprovalPolicy(mode=ApprovalMode.OFF)
    assert not policy.decide("memory_write", {}, Risk.YELLOW)


def test_yellow_ask_uses_callback() -> None:
    policy = ApprovalPolicy(mode=ApprovalMode.ASK)
    assert policy.decide("memory_write", {}, Risk.YELLOW, lambda *_: True)


def test_approval_aliases_normalize_to_existing_modes() -> None:
    assert normalize_approval_mode("strict") == ApprovalMode.ASK
    assert normalize_approval_mode("auto-approve") == ApprovalMode.AUTO
    assert normalize_approval_mode("deny") == ApprovalMode.OFF
