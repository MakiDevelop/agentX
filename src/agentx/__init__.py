from agentx.config import Settings
from agentx.coordinator import (
    Coordinator,
    CoordinatorError,
    CoordinatorResult,
    Plan,
    PlanStep,
    StepResult,
)
from agentx.hooks import (
    HookEvent,
    HookManager,
    HookResult,
    HookVeto,
    ToolCallContext,
    ToolResultContext,
)
from agentx.protocol import Tool, ToolResult
from agentx.safety import Risk
from agentx.tools import ApprovalCallback, ToolRegistry, builtin_tools
from agentx.learning import LearningManager, load_learning_manager  # self-learning proposals + reflexion (ai-tetsu inspired)

__all__ = [
    "__version__",
    "ApprovalCallback",
    "Coordinator",
    "CoordinatorError",
    "CoordinatorResult",
    "HookEvent",
    "HookManager",
    "HookResult",
    "HookVeto",
    "Plan",
    "PlanStep",
    "Risk",
    "Settings",
    "StepResult",
    "Tool",
    "ToolCallContext",
    "ToolRegistry",
    "ToolResult",
    "ToolResultContext",
    "builtin_tools",
    "LearningManager",
    "load_learning_manager",
]

__version__ = "0.1.0"
