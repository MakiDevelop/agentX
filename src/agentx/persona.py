from __future__ import annotations


PERSONAS: dict[str, str] = {
    "default": "預設 agentX 工程助手。直接、務實、以完成任務與驗證為優先。",
    "tutor": (
        "女子大學生家庭教師模式。用親切、清楚、有耐心的繁體中文說明。"
        "像家庭教師一樣先理解 Maki 的程度，再用小步驟、例子、反問確認理解。"
        "保持專業與安全邊界，不使用曖昧、戀愛、情色或角色扮演式親密語氣。"
        "工程任務仍要務實，必要時直接指出風險與下一步。"
    ),
}


def persona_prompt(name: str | None) -> str:
    key = normalize_persona(name)
    return PERSONAS[key]


def normalize_persona(name: str | None) -> str:
    key = (name or "default").strip().lower()
    aliases = {
        "": "default",
        "none": "default",
        "off": "default",
        "teacher": "tutor",
        "家庭教師": "tutor",
        "女子大學生家庭教師": "tutor",
        "女子大學生家庭教師模式": "tutor",
    }
    key = aliases.get(key, key)
    if key not in PERSONAS:
        allowed = ", ".join(sorted(PERSONAS))
        raise ValueError(f"persona must be one of: {allowed}")
    return key


def list_personas() -> str:
    return "\n".join(f"{name}: {description}" for name, description in PERSONAS.items())
