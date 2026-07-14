from pathlib import Path

import pytest

from agentx.infrastructure_context import build_infrastructure_context, infrastructure_maps


def test_infrastructure_maps_point_to_expected_files(tmp_path: Path) -> None:
    maps = infrastructure_maps(tmp_path)

    assert maps["quick"].path == tmp_path / "infrastructure" / "infrastructure-quick-ref.md"
    assert maps["project"].path == tmp_path / "infrastructure" / "project-map.md"
    assert maps["resource"].path == tmp_path / "infrastructure" / "resource-map.md"
    assert maps["all"].path == tmp_path / "infrastructure"


def test_build_infrastructure_context_reads_selected_map(tmp_path: Path) -> None:
    infra = tmp_path / "infrastructure"
    infra.mkdir()
    (infra / "project-map.md").write_text("PROJECT_MAP_MARKER", encoding="utf-8")

    context = build_infrastructure_context("project", home=tmp_path)

    assert "read-only references" in context
    assert "For SSH/deploy/production actions" in context
    assert "--- project-map" in context
    assert "PROJECT_MAP_MARKER" in context


def test_build_infrastructure_context_all_includes_missing_markers(tmp_path: Path) -> None:
    infra = tmp_path / "infrastructure"
    infra.mkdir()
    (infra / "resource-map.md").write_text("RESOURCE_MARKER", encoding="utf-8")

    context = build_infrastructure_context("all", home=tmp_path)

    assert "--- infrastructure-quick-ref" in context
    assert "--- project-map" in context
    assert "--- resource-map" in context
    assert "RESOURCE_MARKER" in context
    assert "(missing)" in context


def test_build_infrastructure_context_accepts_home_and_vps_aliases(tmp_path: Path) -> None:
    infra = tmp_path / "infrastructure"
    infra.mkdir()
    (infra / "infrastructure-quick-ref.md").write_text("HOME_AI_AND_VPS_MARKER", encoding="utf-8")

    home_context = build_infrastructure_context("home", home=tmp_path)
    vps_context = build_infrastructure_context("vps", home=tmp_path)

    assert "Map alias: home -> quick" in home_context
    assert "Map alias: vps -> quick" in vps_context
    assert "HOME_AI_AND_VPS_MARKER" in home_context
    assert "HOME_AI_AND_VPS_MARKER" in vps_context


def test_build_infrastructure_context_rejects_unknown_map(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown infrastructure map"):
        build_infrastructure_context("unknown", home=tmp_path)


def test_build_infrastructure_context_respects_caps(tmp_path: Path) -> None:
    infra = tmp_path / "infrastructure"
    infra.mkdir()
    (infra / "project-map.md").write_text("A" * 200, encoding="utf-8")

    context = build_infrastructure_context("project", home=tmp_path, per_file_chars=10, max_chars=1000)

    assert len(context) <= 1000
    assert "A" * 10 in context
    assert "A" * 11 not in context
