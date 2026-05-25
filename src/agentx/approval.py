from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from agentx.safety import Risk


class ApprovalMode(str, Enum):
    ASK = "ask"
    AUTO = "auto"
    OFF = "off"


APPROVAL_ALIASES = {
    "strict": ApprovalMode.ASK,
    "auto-approve": ApprovalMode.AUTO,
    "deny": ApprovalMode.OFF,
}


def normalize_approval_mode(value: str) -> ApprovalMode:
    normalized = value.strip().lower()
    if normalized in APPROVAL_ALIASES:
        return APPROVAL_ALIASES[normalized]
    return ApprovalMode(normalized)


@dataclass
class ApprovalPolicy:
    mode: ApprovalMode = ApprovalMode.ASK

    def decide(
        self,
        tool: str,
        args: dict[str, Any],
        risk: Risk,
        prompt_user: Callable[[str, dict[str, Any], Risk], bool] | None = None,
    ) -> bool:
        if risk == Risk.GREEN:
            return True
        if risk == Risk.RED:
            return False
        if self.mode == ApprovalMode.AUTO:
            return True
        if self.mode == ApprovalMode.OFF:
            return False
        if prompt_user is None:
            return False
        return prompt_user(tool, args, risk)
