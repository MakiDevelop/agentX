import pytest

from agentx.config import Settings
from agentx.project_config import load_project_config, set_project_config


def test_set_and_load_project_config(tmp_path):
    set_project_config(tmp_path, "model", "gemma4:e2b")
    set_project_config(tmp_path, "auto_handoff", "false")
    set_project_config(tmp_path, "mode", "ask")
    set_project_config(tmp_path, "approval", "auto-approve")

    config = load_project_config(tmp_path)

    assert config.model == "gemma4:e2b"
    assert config.auto_handoff is False
    assert config.mode == "agent"
    assert config.approval == "auto"


def test_set_and_load_persona_config(tmp_path):
    set_project_config(tmp_path, "persona", "女子大學生家庭教師模式")

    config = load_project_config(tmp_path)

    assert config.persona == "tutor"


def test_reject_invalid_project_config_values(tmp_path):
    with pytest.raises(ValueError, match="mode must be chat, ask, or agent"):
        set_project_config(tmp_path, "mode", "plan")

    with pytest.raises(ValueError, match="approval must be ask"):
        set_project_config(tmp_path, "approval", "yes")

    with pytest.raises(ValueError, match="persona must be one of"):
        set_project_config(tmp_path, "persona", "unknown")


def test_settings_can_be_updated_without_reloading_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTX_WORKSPACE", str(tmp_path))
    settings = Settings()

    updated = settings.with_updates(model="gemma4:31b", max_steps=3)

    assert updated.model == "gemma4:31b"
    assert updated.max_steps == 3
    assert updated.persona == "default"
    assert updated.workspace == tmp_path


def test_settings_accepts_explicit_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTX_WORKSPACE", str(tmp_path / "other"))
    set_project_config(tmp_path, "model", "gemma4:e2b")

    settings = Settings(workspace=tmp_path)

    assert settings.workspace == tmp_path
    assert settings.model == "gemma4:e2b"


def test_settings_reads_context_limit_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTX_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("AGENTX_CONTEXT_LIMIT", "32768")

    settings = Settings()

    assert settings.context_limit_tokens == 32768


def test_settings_normalizes_persona_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTX_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("AGENTX_PERSONA", "女子大學生家庭教師模式")

    settings = Settings()

    assert settings.persona == "tutor"


def test_settings_default_memory_hall_url_matches_home_ai_main_path(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTX_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("AGENTX_MEMORY_HALL_URL", raising=False)

    settings = Settings()

    assert settings.memory_hall_url == "http://100.89.41.50:9100"
