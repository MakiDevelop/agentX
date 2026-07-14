import json
from pathlib import Path

from typer.testing import CliRunner

from agentx import infrastructure_context
from agentx.cli import app


def write_maps(home: Path) -> None:
    infra = home / "infrastructure"
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


def test_infra_cli_outputs_json_for_resource_bundle(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    write_maps(tmp_path)
    monkeypatch.setattr(infrastructure_context.Path, "home", staticmethod(lambda: tmp_path))

    result = CliRunner().invoke(app, ["infra", "resource-bundle", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "agentx.infrastructure_context.v1"
    assert payload["map"] == "resource-bundle"
    assert payload["resolved_map"] == "resource-bundle"
    assert payload["alias_applied"] is False
    assert payload["ok"] is True
    assert payload["read_only"] is True
    assert payload["source_status"] == "complete"
    assert payload["selected_maps"] == ["resource", "home", "vps"]
    assert payload["limits"] == {"per_file_chars": 5000, "max_chars": 14000}
    assert [source["key"] for source in payload["sources"]] == ["resource", "home", "vps"]
    assert all(source["exists"] is True for source in payload["sources"])
    assert "RESOURCE_MARKER" in payload["content"]
    assert "HOME_MARKER" in payload["content"]
    assert "VPS_MARKER" in payload["content"]


def test_infra_cli_outputs_json_for_resource_bundle_alias(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    write_maps(tmp_path)
    monkeypatch.setattr(infrastructure_context.Path, "home", staticmethod(lambda: tmp_path))

    result = CliRunner().invoke(app, ["infra", "資源地圖+家庭AI設施／VPS地圖", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["map"] == "資源地圖+家庭AI設施／VPS地圖"
    assert payload["resolved_map"] == "resource-bundle"
    assert payload["alias_applied"] is True
    assert [source["key"] for source in payload["sources"]] == ["resource", "home", "vps"]
    assert "RESOURCE_MARKER" in payload["content"]
    assert "HOME_MARKER" in payload["content"]
    assert "VPS_MARKER" in payload["content"]


def test_infra_cli_outputs_jsonl_event(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    write_maps(tmp_path)
    monkeypatch.setattr(infrastructure_context.Path, "home", staticmethod(lambda: tmp_path))

    result = CliRunner().invoke(app, ["infra", "home", "--output-format", "jsonl"])

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["event"] == "infra"
    assert envelope["data"]["schema"] == "agentx.infrastructure_context.v1"
    assert envelope["data"]["map"] == "home"
    assert "HOME_MARKER" in envelope["data"]["content"]
    assert "VPS_MARKER" not in envelope["data"]["content"]


def test_infra_cli_outputs_plain_context(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    write_maps(tmp_path)
    monkeypatch.setattr(infrastructure_context.Path, "home", staticmethod(lambda: tmp_path))

    result = CliRunner().invoke(app, ["infra", "vps"])

    assert result.exit_code == 0, result.output
    assert "Infrastructure maps are read-only references" in result.output
    assert "VPS_MARKER" in result.output
    assert "HOME_MARKER" not in result.output
