from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class IntentRisk:
    level: str
    reason: str


_HIGH_RISK_PATTERNS = {
    "destructive": ("刪", "刪除", "delete", "remove", "rm ", "reset --hard", "clean"),
    "production": ("production", "prod", "正式", "上線", "deploy", "部署"),
    "remote": ("ssh", "遠端", "vps", "server", "伺服器", "重啟", "restart"),
    "secrets": ("secret", "token", "password", "密碼", "金鑰", "api key", ".env"),
    "data": ("database", "db", "資料庫", "migration", "volume", "備份"),
}

_MEDIUM_RISK_PATTERNS = {
    "git-write": ("commit", "push", "stage", "提交", "推送"),
    "broad-change": ("重構", "refactor", "架構", "全域", "大量", "rewrite"),
    "dependency": ("install", "upgrade", "dependency", "套件", "依賴"),
}

_VERB_HINTS = {
    "deploy": ("deploy", "部署", "上線"),
    "fix": ("修", "修復", "bug", "錯誤", "fail", "failed", "失敗"),
    "add": ("新增", "加", "支援", "implement", "add"),
    "review": ("review", "檢查", "審查", "看一下"),
    "test": ("test", "測試", "驗證", "pytest", "ruff"),
    "document": ("文件", "README", "docs", "說明", "document"),
}

_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "please",
    "幫我",
    "一下",
    "這個",
    "那個",
    "功能",
    "問題",
    "並",
    "到",
}


def analyze_intent(request: str, *, max_terms: int = 6) -> str:
    text = request.strip()
    if not text:
        raise ValueError("intent text is required")

    risk = _classify_risk(text)
    terms = _extract_terms(text, max_terms=max_terms)
    action = _classify_action(text)
    needs_question = risk.level in {"HIGH", "RED"} or not terms

    lines = [
        "## Intent Brief",
        f"- Goal: {text}",
        f"- Likely action: {action}",
        f"- Risk: {risk.level} — {risk.reason}",
        f"- Ask Maki before execution: {'yes' if needs_question else 'no'}",
        "",
        "## Suggested Inspection",
    ]
    if terms:
        for term in terms:
            lines.append(f"- /where {term}")
        lines.append(f"- /find {terms[0]}")
    else:
        lines.append("- Clarify the target module/file before reading or editing.")

    lines.extend(
        [
            "",
            "## Execution Shape",
            "- Read the likely files before editing.",
            "- Make one small reversible change at a time.",
            "- Use precise edit tools instead of broad rewrites.",
            "",
            "## Verification Plan",
            "- Run targeted tests for the touched module when available.",
            "- Run `uv run ruff check .` before commit.",
            "- Run `uv run pytest -q` before final commit/push for repo-level changes.",
        ]
    )
    if risk.level in {"HIGH", "RED"}:
        lines.extend(
            [
                "",
                "## Stop Conditions",
                "- Do not execute remote, production, destructive, secret, DB, or volume actions without explicit approval.",
                "- For SSH/deploy/VPS work, read /infra first and confirm runtime state.",
            ]
        )
    return "\n".join(lines)


def _classify_risk(text: str) -> IntentRisk:
    lowered = text.lower()
    for reason, patterns in _HIGH_RISK_PATTERNS.items():
        if any(pattern in lowered for pattern in patterns):
            level = "RED" if reason in {"destructive", "secrets", "data"} else "HIGH"
            return IntentRisk(level=level, reason=reason)
    for reason, patterns in _MEDIUM_RISK_PATTERNS.items():
        if any(pattern in lowered for pattern in patterns):
            return IntentRisk(level="YELLOW", reason=reason)
    return IntentRisk(level="GREEN", reason="local read/plan or low-risk code inspection")


def _classify_action(text: str) -> str:
    lowered = text.lower()
    for action, patterns in _VERB_HINTS.items():
        if any(pattern in lowered for pattern in patterns):
            return action
    return "inspect-plan"


def _extract_terms(text: str, *, max_terms: int) -> list[str]:
    normalized = re.sub(r"[^\w\u4e00-\u9fff./-]+", " ", text.lower())
    terms: list[str] = []
    for raw in normalized.split():
        term = _clean_term(raw.strip(".,:;!?()[]{}"))
        if len(term) < 2 or term in _STOPWORDS:
            continue
        if term not in terms:
            terms.append(term)
        if len(terms) >= max_terms:
            break
    return terms


def _clean_term(term: str) -> str:
    for prefix in ("請", "幫我", "並", "到"):
        term = term.removeprefix(prefix)
    for suffix in ("一下", "到"):
        term = term.removesuffix(suffix)
    return term
