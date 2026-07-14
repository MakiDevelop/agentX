from pathlib import Path

import pytest

from agentx.learning import LearningManager, LearningProposal
from helpers import make_settings


def _manager(workspace: Path) -> LearningManager:
    return LearningManager(make_settings(workspace, learning_enabled=True), memory=None)


def test_learning_proposal_status_gate_rejects_unknown_status(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    proposal = LearningProposal(id="abc123", title="Test", evidence=["evidence"])
    manager.propose(proposal)

    with pytest.raises(ValueError, match="unknown proposal status"):
        manager.update_status("abc123", "done")

    assert manager.get_proposal("abc123").status == "proposed"  # type: ignore[union-attr]


def test_learning_proposal_status_gate_rejects_direct_apply(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    proposal = LearningProposal(id="abc123", title="Test", evidence=["evidence"])
    manager.propose(proposal)

    with pytest.raises(ValueError, match="invalid proposal status transition"):
        manager.update_status("abc123", "applied", applied_to=["AGENTX.md"])

    assert manager.get_proposal("abc123").status == "proposed"  # type: ignore[union-attr]


def test_learning_proposal_status_gate_requires_applied_target(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    proposal = LearningProposal(id="abc123", title="Test", evidence=["evidence"])
    manager.propose(proposal)
    assert manager.update_status("abc123", "approved")

    with pytest.raises(ValueError, match="applied proposals must record applied_to"):
        manager.update_status("abc123", "applied")

    assert manager.get_proposal("abc123").status == "approved"  # type: ignore[union-attr]


def test_learning_proposal_status_gate_syncs_applied_artifacts(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    proposal = LearningProposal(id="abc123", title="Test", evidence=["evidence"])
    manager.propose(proposal)

    assert manager.update_status("abc123", "approved")
    assert manager.update_status("abc123", "applied", applied_to=["AGENTX.md:10"])

    applied = manager.get_proposal("abc123")
    assert applied is not None
    assert applied.status == "applied"
    assert applied.applied_to == ["AGENTX.md:10"]

    proposal_files = list((tmp_path / ".agentx" / "learning" / "proposals").glob("*.md"))
    assert len(proposal_files) == 1
    md_content = proposal_files[0].read_text(encoding="utf-8")
    assert "**Status**: applied" in md_content
    assert "- AGENTX.md:10" in md_content
