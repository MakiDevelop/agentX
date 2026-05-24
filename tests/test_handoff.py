from pathlib import Path
from unittest.mock import MagicMock

from agentx.cli import _handoff_next_steps, build_handoff


def test_handoff_next_steps_prefers_active_tasks() -> None:
    tasks = [
        {"id": 1, "description": "完成 guide", "status": "done"},
        {"id": 2, "description": "改善 resume", "status": "in_progress"},
    ]

    result = _handoff_next_steps(tasks)

    assert "#2: 改善 resume [in_progress]" in result
    assert "#1" not in result


def test_build_handoff_includes_next_steps(tmp_path: Path) -> None:
    settings = MagicMock(
        workspace=tmp_path,
        model="gemma4:31b",
    )
    transcript = MagicMock(path=tmp_path / ".agentx" / "sessions" / "demo.jsonl")

    content = build_handoff(
        settings=settings,
        namespace="project:agentX",
        mode="agent",
        history=[("agent", "請改善 resume")],
        transcript=transcript,
        tasks=[{"id": 3, "description": "補 handoff next steps", "status": "pending"}],
    )

    assert "建議下一步：" in content
    assert "#3: 補 handoff next steps [pending]" in content
    assert "最近互動：" in content
