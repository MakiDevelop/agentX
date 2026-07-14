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

_RUNTIME_TARGET_HINTS = {
    "n1k.tw": "n1k.tw",
    "n1k": "n1k.tw",
    "2ch.tw": "2ch.tw",
    "2ch": "2ch.tw",
    "ranran.tw": "ranran.tw",
    "ranran": "ranran.tw",
    "chiba.tw": "chiba.tw",
    "chiba": "chiba.tw",
    "mac mini m4-2": "Mac mini M4-2",
    "mini2": "Mac mini M4-2",
    "mac mini m4": "Mac mini M4",
    "mini": "Mac mini M4",
    "dgx spark": "DGX Spark",
    "dgx": "DGX Spark",
    "rtx 3090": "RTX 3090 PC",
    "rtx3090": "RTX 3090 PC",
    "nas": "NAS DS2415+",
    "s20 ultra": "S20 Ultra",
    "pdsnet-z13": "PDSNET-Z13",
}

_SERVICE_HINTS = {
    "n8n": "n8n-workflows",
    "agent-control-plane": "agent-control-plane",
    "2ch-core": "2ch-core",
    "geo-checker": "geo-checker",
    "dx-chatbot": "dx-chatbot",
    "dx.chiba.tw": "dx-chiba",
    "ai.chiba.tw": "dx-chiba",
    "memhall": "memhall",
    "memory-hall": "memhall",
    "ollama": "Ollama",
    "comfyui": "ComfyUI",
    "stable diffusion": "ComfyUI",
    "flux": "ComfyUI",
    "mk-brain": "mk-brain",
    "embed": "embed_server",
}

_RUN_MODE_HINTS = {
    "docker compose": "Docker Compose",
    "docker-compose": "Docker Compose",
    "docker": "Docker",
    "cloud run": "Cloud Run",
    "launchd": "launchd",
    "cron": "cron",
    "systemd": "systemd",
}

_HOME_INFRA_HINTS = ("家庭", "home ai", "home-ai", "mac mini", "mini2", "dgx", "rtx", "nas", "s20", "pdsnet")
_VPS_INFRA_HINTS = ("vps", "外網", "n1k", "2ch", "ranran", "chiba.tw", "dx.chiba", "ai.chiba")

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
        if risk.reason in {"production", "remote"}:
            lines.extend(["", *_runtime_state_preflight(text, risk)])
        lines.extend(
            [
                "",
                "## Stop Conditions",
                "- Do not execute remote, production, destructive, secret, DB, or volume actions without explicit approval.",
                "- For SSH/deploy/VPS work, read /infra first and confirm runtime state.",
            ]
        )
    return "\n".join(lines)


def plan_task_checklist(request: str, *, max_terms: int = 4) -> str:
    text = request.strip()
    if not text:
        raise ValueError("plan-task text is required")

    risk = _classify_risk(text)
    action = _classify_action(text)
    tasks = plan_task_items(text, max_terms=max_terms)

    lines = [
        "## Task Plan",
        f"- Source request: {text}",
        f"- Likely action: {action}",
        f"- Risk: {risk.level} — {risk.reason}",
        "",
        "## Checklist",
    ]
    for index, task in enumerate(tasks, start=1):
        lines.append(f"{index}. {task}")

    lines.extend(["", "## Suggested /task Commands"])
    for task in tasks:
        lines.append(f"/task add {task}")

    if risk.level in {"HIGH", "RED"}:
        lines.extend(
            [
                "",
                "## Guardrail",
                "This plan is read-only. Do not execute remote, production, destructive, secret, DB, or volume actions without explicit approval.",
            ]
        )
    return "\n".join(lines)


def plan_task_items(request: str, *, max_terms: int = 4) -> list[str]:
    text = request.strip()
    if not text:
        raise ValueError("plan-task text is required")

    risk = _classify_risk(text)
    terms = _extract_terms(text, max_terms=max_terms)
    inspection_target = terms[0] if terms else text[:40]
    tasks = [
        f"釐清目標與風險：{text}",
        f"定位相關檔案：/where {inspection_target}",
        f"讀取並確認實作位置：/find {inspection_target}",
        "實作最小可逆改動",
        "執行 targeted 驗證與 ruff",
        "執行 repo-level pytest 後 review diff",
    ]
    if risk.level in {"HIGH", "RED"}:
        tasks.insert(1, "取得 Maki 明確確認後才處理高風險操作")
        if risk.reason in {"production", "remote"}:
            tasks.insert(2, "讀取 /infra 並填寫 runtime state pre-flight")
    return tasks


def _runtime_state_preflight(text: str, risk: IntentRisk) -> list[str]:
    lowered = text.lower()
    map_hint = _infra_map_hint(lowered)
    machine = _first_hint(lowered, _RUNTIME_TARGET_HINTS) or "unknown - resolve from /infra before acting"
    service = _first_hint(lowered, _SERVICE_HINTS) or "unknown - identify concrete service/repo/container/job"
    run_mode = _first_hint(lowered, _RUN_MODE_HINTS) or "unknown - verify from repo docs, process manager, or infra map"
    constraint = _runtime_constraint(risk)

    return [
        "## Runtime State Pre-flight",
        f"- Machine: {machine}",
        f"- Service: {service}",
        f"- Run Mode: {run_mode}",
        f"- Constraint: {constraint}",
        f"- Risk: {risk.level} — {risk.reason}",
        f"- Source: /infra {map_hint} plus current repo docs; do not infer missing fields",
        "",
        "## Post-check Plan",
        "- Confirm the target service/process/container is the intended one.",
        "- Check health endpoint, logs, or process status after the operation.",
        "- Verify the user-facing URL or CLI behavior tied to the change.",
        "- Capture rollback or recovery notes before any production action.",
    ]


def _infra_map_hint(lowered: str) -> str:
    if any(hint in lowered for hint in _HOME_INFRA_HINTS):
        return "home"
    if any(hint in lowered for hint in _VPS_INFRA_HINTS):
        return "vps"
    return "all"


def _first_hint(lowered: str, hints: dict[str, str]) -> str | None:
    for needle, value in hints.items():
        if needle in lowered:
            return value
    return None


def _runtime_constraint(risk: IntentRisk) -> str:
    if risk.reason == "production":
        return "production path; requires explicit Maki approval before external write/restart/deploy"
    if risk.reason == "remote":
        return "remote host; read-only inspection until machine/service/run mode are confirmed"
    return "high-risk action; explicit approval required before execution"


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
