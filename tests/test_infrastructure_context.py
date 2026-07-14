from pathlib import Path

import pytest

from agentx.infrastructure_context import build_infrastructure_context, infrastructure_context_metadata, infrastructure_maps


def test_infrastructure_maps_point_to_expected_files(tmp_path: Path) -> None:
    maps = infrastructure_maps(tmp_path)

    assert maps["quick"].path == tmp_path / "infrastructure" / "infrastructure-quick-ref.md"
    assert maps["project"].path == tmp_path / "infrastructure" / "project-map.md"
    assert maps["resource"].path == tmp_path / "infrastructure" / "resource-map.md"
    assert maps["home"].path == tmp_path / "infrastructure" / "resource-map.md"
    assert maps["vps"].path == tmp_path / "infrastructure" / "resource-map.md"
    assert maps["resource-bundle"].path == tmp_path / "infrastructure" / "resource-map.md"
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


def test_infrastructure_context_metadata_describes_resource_bundle_sources(tmp_path: Path) -> None:
    infra = tmp_path / "infrastructure"
    infra.mkdir()
    (infra / "resource-map.md").write_text("RESOURCE_MARKER", encoding="utf-8")

    metadata = infrastructure_context_metadata("資源地圖+家庭AI設施／VPS地圖", home=tmp_path)

    assert metadata["resolved_map"] == "resource-bundle"
    assert metadata["alias_applied"] is True
    assert metadata["selected_maps"] == ["resource", "home", "vps"]
    assert metadata["source_status"] == "complete"
    sources = metadata["sources"]
    assert isinstance(sources, list)
    assert [source["key"] for source in sources] == ["resource", "home", "vps"]
    assert all(source["exists"] is True for source in sources)
    assert sources[1]["section_headings"] == ["家庭 AI 中心"]
    assert sources[2]["section_headings"] == ["外網主機 / VPS", "VPS 對照"]


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
    (infra / "resource-map.md").write_text(
        "\n".join(
            [
                "# 資源地圖",
                "",
                "## 家庭 AI 中心（192.168.11.x）",
                "HOME_AI_MARKER",
                "",
                "### Mac mini M4",
                "MINI_MARKER",
                "",
                "## 外網主機 / VPS",
                "VPS_MARKER",
                "",
                "### n1k.tw",
                "N1K_MARKER",
                "",
                "## GCP / 公司環境",
                "GCP_MARKER",
            ]
        ),
        encoding="utf-8",
    )

    home_context = build_infrastructure_context("home", home=tmp_path)
    home_alias_context = build_infrastructure_context("home-ai", home=tmp_path)
    vps_context = build_infrastructure_context("vps", home=tmp_path)

    assert "--- home-ai-facilities-map" in home_context
    assert "HOME_AI_MARKER" in home_context
    assert "MINI_MARKER" in home_context
    assert "VPS_MARKER" not in home_context
    assert "GCP_MARKER" not in home_context
    assert "Map alias: home-ai -> home" in home_alias_context
    assert "HOME_AI_MARKER" in home_alias_context
    assert "--- vps-map" in vps_context
    assert "VPS_MARKER" in vps_context
    assert "N1K_MARKER" in vps_context
    assert "GCP_MARKER" not in vps_context


def test_build_infrastructure_context_vps_can_fallback_to_quick_ref_heading(tmp_path: Path) -> None:
    infra = tmp_path / "infrastructure"
    infra.mkdir()
    (infra / "resource-map.md").write_text(
        "\n".join(
            [
                "# 資源地圖",
                "",
                "## VPS 對照",
                "QUICK_STYLE_VPS_MARKER",
                "",
                "## Other",
                "OTHER_MARKER",
            ]
        ),
        encoding="utf-8",
    )

    context = build_infrastructure_context("vps", home=tmp_path)

    assert "QUICK_STYLE_VPS_MARKER" in context
    assert "OTHER_MARKER" not in context


@pytest.mark.parametrize(
    ("alias", "expected_marker"),
    [
        ("家庭AI設施", "HOME_MARKER"),
        ("家庭AI地圖", "HOME_MARKER"),
        ("家庭AI中心地圖", "HOME_MARKER"),
        ("設施地圖", "HOME_MARKER"),
        ("home ai map", "HOME_MARKER"),
        ("家庭 AI 設施地圖", "HOME_MARKER"),
        ("VPS地圖", "VPS_MARKER"),
        ("vps map", "VPS_MARKER"),
        ("外網主機", "VPS_MARKER"),
        ("資源地圖", "RESOURCE_MARKER"),
        ("resource map", "RESOURCE_MARKER"),
        ("專案地圖", "PROJECT_MARKER"),
        ("project map", "PROJECT_MARKER"),
        ("基礎設施速查", "QUICK_MARKER"),
        ("quick ref", "QUICK_MARKER"),
    ],
)
def test_build_infrastructure_context_accepts_chinese_aliases(
    tmp_path: Path,
    alias: str,
    expected_marker: str,
) -> None:
    infra = tmp_path / "infrastructure"
    infra.mkdir()
    (infra / "infrastructure-quick-ref.md").write_text("QUICK_MARKER", encoding="utf-8")
    (infra / "project-map.md").write_text("PROJECT_MARKER", encoding="utf-8")
    (infra / "resource-map.md").write_text(
        "\n".join(
            [
                "# RESOURCE_MARKER",
                "",
                "## 家庭 AI 中心",
                "HOME_MARKER",
                "",
                "## 外網主機 / VPS",
                "VPS_MARKER",
            ]
        ),
        encoding="utf-8",
    )

    context = build_infrastructure_context(alias, home=tmp_path)

    assert expected_marker in context
    assert f"Map alias: {alias.lower()}" in context


@pytest.mark.parametrize(
    "alias",
    [
        "資源地圖+家庭AI設施/VPS地圖",
        "資源地圖+家庭AI設施／VPS地圖",
        "資源地圖 + 家庭 AI 設施 / VPS 地圖",
        "資源地圖 + 家庭 AI 設施 ／ VPS 地圖",
    ],
)
def test_build_infrastructure_context_accepts_combined_resource_aliases(
    tmp_path: Path,
    alias: str,
) -> None:
    infra = tmp_path / "infrastructure"
    infra.mkdir()
    (infra / "infrastructure-quick-ref.md").write_text("QUICK_MARKER", encoding="utf-8")
    (infra / "project-map.md").write_text("PROJECT_MARKER", encoding="utf-8")
    (infra / "resource-map.md").write_text(
        "\n".join(
            [
                "# RESOURCE_MARKER",
                "",
                "## 家庭 AI 中心",
                "HOME_MARKER",
                "",
                "## 外網主機 / VPS",
                "VPS_MARKER",
            ]
        ),
        encoding="utf-8",
    )

    context = build_infrastructure_context(alias, home=tmp_path)

    assert f"Map alias: {alias.lower()} -> resource-bundle" in context
    assert "RESOURCE_MARKER" in context
    assert "--- resource-map" in context
    assert "--- home-ai-facilities-map" in context
    assert "HOME_MARKER" in context
    assert "--- vps-map" in context
    assert "VPS_MARKER" in context
    assert "QUICK_MARKER" not in context
    assert "PROJECT_MARKER" not in context


def test_build_infrastructure_context_combined_alias_extracts_home_and_vps_sections_after_resource_cap(
    tmp_path: Path,
) -> None:
    infra = tmp_path / "infrastructure"
    infra.mkdir()
    (infra / "resource-map.md").write_text(
        "\n".join(
            [
                "# RESOURCE_MARKER",
                "GENERAL_RESOURCE_LINE",
                "X" * 400,
                "",
                "## 家庭 AI 中心",
                "HOME_AFTER_CAP_MARKER",
                "",
                "## 外網主機 / VPS",
                "VPS_AFTER_CAP_MARKER",
            ]
        ),
        encoding="utf-8",
    )

    context = build_infrastructure_context(
        "資源地圖+家庭AI設施／VPS地圖",
        home=tmp_path,
        per_file_chars=80,
        max_chars=1000,
    )

    assert "GENERAL_RESOURCE_LINE" in context
    assert "HOME_AFTER_CAP_MARKER" in context
    assert "VPS_AFTER_CAP_MARKER" in context


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


def test_build_infrastructure_context_redacts_sensitive_lines(tmp_path: Path) -> None:
    infra = tmp_path / "infrastructure"
    infra.mkdir()
    (infra / "infrastructure-quick-ref.md").write_text(
        "\n".join(
            [
                "# 基礎設施速查",
                "normal routing line",
                "API Key: AIzaSySECRET",
                "LOOKER_CLIENT_SECRET = super-secret",
                "X-API-Key: abc123",
            ]
        ),
        encoding="utf-8",
    )

    context = build_infrastructure_context("quick", home=tmp_path)

    assert "normal routing line" in context
    assert "AIzaSySECRET" not in context
    assert "super-secret" not in context
    assert "abc123" not in context
    assert "[redacted sensitive infrastructure line]" in context
