import pytest

from agentx.persona import list_personas, normalize_persona, persona_prompt


def test_normalize_tutor_aliases() -> None:
    assert normalize_persona("女子大學生家庭教師模式") == "tutor"
    assert normalize_persona("teacher") == "tutor"


def test_persona_prompt_has_professional_boundary() -> None:
    prompt = persona_prompt("tutor")

    assert "女子大學生家庭教師模式" in prompt
    assert "家庭教師" in prompt
    assert "小Ge" in prompt
    assert "安全邊界" in prompt


def test_list_personas_includes_tutor() -> None:
    assert "tutor" in list_personas()


def test_unknown_persona_is_rejected() -> None:
    with pytest.raises(ValueError):
        normalize_persona("mentor")
