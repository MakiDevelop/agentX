from __future__ import annotations

from enum import Enum


class Risk(str, Enum):
    """Risk tier for a tool.

    This is the *only* thing the safety module owns. Risk is declared by each
    Tool class as a `risk` class attribute and enforced at a single point:
    `ToolRegistry.run()` (see agentx/tools/registry.py).

    - GREEN  — runs without approval.
    - YELLOW — requires an approver callback, or explicit auto_approve_yellow.
               Fails closed when neither is configured.
    - RED    — never executed by the registry.

    Command-level protection is deliberately NOT pattern matching. Shell access
    is exact-match allowlisted in agentx/tools/_helpers.py (ALLOWED_COMMANDS for
    GREEN, BUILD_COMMANDS for YELLOW); anything not literally in those tables is
    rejected by RunCommandTool / RunBuildCommandTool. An allowlist cannot be
    bypassed by quoting, aliasing, or string obfuscation, which is why the older
    denylist of substrings ("rm -rf", "~/.ssh", ...) was removed rather than
    kept as a second layer: it never ran in production, it had silently drifted
    out of sync with the real tool declarations, and keeping it around implied a
    protection that did not exist.
    """

    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"
