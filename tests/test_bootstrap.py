from pathlib import Path

from agentx.bootstrap import build_repo_context


def test_repo_context_includes_known_files(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Demo", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'", encoding="utf-8")

    context = build_repo_context(tmp_path)

    assert "README.md" in context
    assert "# Demo" in context
    assert "pyproject.toml" in context
