import pytest

from agentx.config import Settings
from agentx.project_config import load_project_config, set_project_config


def test_set_and_load_project_config(tmp_path):
    set_project_config(tmp_path, "model", "gemma4:e2b")
    set_project_config(tmp_path, "auto_handoff", "false")

    config = load_project_config(tmp_path)

    assert config.model == "gemma4:e2b"
    assert config.auto_handoff is False


def test_reject_invalid_project_config_values(tmp_path):
    with pytest.raises(ValueError, match="mode must be chat or agent"):
        set_project_config(tmp_path, "mode", "plan")

    with pytest.raises(ValueError, match="approval must be ask"):
        set_project_config(tmp_path, "approval", "yes")


def test_settings_can_be_updated_without_reloading_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTX_WORKSPACE", str(tmp_path))
    settings = Settings()

    updated = settings.with_updates(model="gemma4:31b", max_steps=3)

    assert updated.model == "gemma4:31b"
    assert updated.max_steps == 3
    assert updated.workspace == tmp_path


def test_settings_reads_context_limit_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTX_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("AGENTX_CONTEXT_LIMIT", "32768")

    settings = Settings()

    assert settings.context_limit_tokens == 32768
