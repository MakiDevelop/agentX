from pathlib import Path

from agentx.project_profile import build_project_profile


def test_project_profile_detects_python_uv(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")

    profile = build_project_profile(tmp_path, "project:demo")

    assert "Python project" in profile
    assert "uv-managed dependencies" in profile
    assert "uv run pytest -q" in profile
