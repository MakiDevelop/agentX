from __future__ import annotations

from difflib import get_close_matches

CommandCatalogItem = dict[str, object]

COMMAND_CATALOG: list[CommandCatalogItem] = [
    {"usage": "/help [COMMAND]", "description": "列出所有 slash command；提供 COMMAND 時顯示單一命令說明", "examples": ["/help", "/help workflow", "/help /infra"], "related": ["/guide", "/workflows", "/workflow"]},
    {"usage": "/guide", "description": "60 秒快速導覽：模式選擇、常用工作流、安全與記憶", "examples": ["/guide"], "related": ["/help", "/workflows", "/tools"]},
    {"usage": "/workflows", "description": "列出實務工作流：理解、修改、測試、review、handoff", "examples": ["/workflows"], "related": ["/workflow", "/guide", "/help"]},
    {"usage": "/workflow NAME", "description": "輸出單一 workflow recipe，例如 headless、audit、commit", "examples": ["/workflow headless", "/workflow audit", "/workflow commit"], "related": ["/workflows", "/guide", "/help"]},
    {"usage": "/init", "description": "掃描 repo 並寫入 project profile 到 Memory Hall", "examples": ["/init"], "related": ["/doctor", "/memory", "/remember"]},
    {"usage": "/task [TEXT|status|list|add ...|update <id> ...|done <id>|clear]", "description": "多任務清單管理（已統一為真相來源）", "examples": ["/task status", "/task add 補 README 文件", "/task update 1 done"], "related": ["/plan-task", "/intent", "/status"]},
    {"usage": "/doctor", "description": "檢查 Ollama、模型、Memory Hall、git、uv 狀態", "examples": ["/doctor"], "related": ["/status", "/config", "/tools"]},
    {"usage": "/config", "description": "顯示目前 agentX 設定", "examples": ["/config", "/config set mode agent"], "related": ["/doctor", "/status", "/model"], "risk": "YELLOW - set 會寫入 .agentx/config.toml"},
    {"usage": "/config set KEY VALUE", "description": "寫入 .agentx/config.toml", "examples": ["/config", "/config set mode agent"], "related": ["/doctor", "/status", "/model"], "risk": "YELLOW - set 會寫入 .agentx/config.toml"},
    {"usage": "/tools", "description": "列出可用工具（已依 GREEN/YELLOW/RED 風險分組，符合安全視覺化）", "examples": ["/tools"], "related": ["/approval", "/run", "/help"]},
    {"usage": "/context", "description": "顯示目前 agent 上下文使用量與壓縮次數", "examples": ["/context"], "related": ["/compact", "/status", "/clear"]},
    {"usage": "/compact", "description": "壓縮目前 agent session 上下文，保留最近訊息摘要", "examples": ["/compact"], "related": ["/context", "/status", "/clear"]},
    {"usage": "/history", "description": "顯示本輪 shell 的簡短互動紀錄", "examples": ["/history"], "related": ["/sessions", "/transcript", "/handoff"]},
    {"usage": "/jobs", "description": "顯示目前執行中與排隊中的 prompt", "examples": ["/jobs"], "related": ["/cancel", "/status"]},
    {"usage": "/cancel [JOB_ID|all]", "description": "取消尚未執行的 queued prompt", "examples": ["/cancel 3", "/cancel all"], "related": ["/jobs", "/status"]},
    {"usage": "/sessions", "description": "列出最近 transcript，可搭配 /resume", "examples": ["/sessions"], "related": ["/resume", "/transcript", "/handoff"]},
    {"usage": "/transcript [approvals [latest|SESSION] [--denied]]", "description": "顯示 transcript 路徑；approvals 會列出本輪或指定 session 的 YELLOW approval receipts", "examples": ["/transcript approvals latest --denied"], "related": ["/sessions", "/resume", "/handoff"]},
    {"usage": "/handoff [TEXT]", "description": "寫入 Memory Hall 交接摘要；未提供文字時自動整理本輪紀錄", "examples": ["/handoff 完成 CLI help 覆蓋率補強"], "related": ["/sessions", "/resume", "/memory"], "risk": "YELLOW - 會寫入 Memory Hall"},
    {"usage": "/resume [latest|FILE]", "description": "從 JSONL transcript 載入最近上下文摘要", "examples": ["/resume latest"], "related": ["/sessions", "/transcript", "/handoff"]},
    {"usage": "/files [PATH]", "description": "列出 repo 檔案，預設目前 workspace", "examples": ["/files", "/files src/agentx"], "related": ["/read", "/find", "/where"]},
    {"usage": "/read PATH", "description": "讀取 repo 內指定檔案", "examples": ["/read README.md"], "related": ["/files", "/find", "/attach"]},
    {"usage": "/attach PATH...", "description": "把指定檔案內容加入本輪 context；支援拖曳路徑", "examples": ["/attach README.md docs/product-tour.md"], "related": ["/read", "/files", "/context"]},
    {"usage": "/find KEYWORD", "description": "依 keyword 搜尋檔名/路徑與內容，並建議 /read 目標", "examples": ["/find workflow"], "related": ["/read", "/search", "/where"]},
    {"usage": "/where TOPIC", "description": "依 topic 定位最可能的檔案位置，輸出 ranked /read 建議", "examples": ["/where slash command dispatch"], "related": ["/find", "/read", "/infra"]},
    {"usage": "/infra [all|quick|project|resource|home|vps|resource-bundle]", "description": "讀取專案/資源地圖；home/vps 會抽取家庭 AI 設施與 VPS 章節，混合 alias 會載入 resource+home+vps（read-only）", "examples": ["/infra home", "/infra vps", "/infra resource-bundle"], "related": ["/intent", "/where", "/read"]},
    {"usage": "/intent TEXT", "description": "把需求整理成目標、風險、建議讀檔與驗證計畫", "examples": ["/intent 部署到 VPS production 並重啟服務"], "related": ["/infra", "/plan-task", "/task"]},
    {"usage": "/plan-task [--apply] TEXT", "description": "把需求拆成 checklist；--apply 會寫入 /task 清單", "examples": ["/plan-task 補測試", "/plan-task --apply 補 tests"], "related": ["/task", "/intent", "/guide"], "risk": "YELLOW - --apply 會寫入 task list"},
    {"usage": "/grep PATTERN [PATH]", "description": "在指定 path 內做 rg 內容搜尋；預設整個 workspace", "examples": ["/grep workflow src/agentx"], "related": ["/search", "/read", "/where"]},
    {"usage": "/search PATTERN", "description": "在 repo 內搜尋文字", "examples": ["/search workflow"], "related": ["/grep", "/read", "/find"]},
    {"usage": "/fetch URL", "description": "讀取指定外部網頁文字，會阻擋 localhost 與私有網段", "examples": ["/fetch https://example.com"], "related": ["/read", "/attach", "/intent"]},
    {"usage": "/git [status|branch|log [N]|show [REV]]", "description": "顯示 allowlisted git 唯讀資訊", "examples": ["/git status", "/git log 5", "/git show HEAD"], "related": ["/diff", "/review", "/commit"]},
    {"usage": "/diff [PATH]", "description": "顯示 git diff，可指定單一檔案", "examples": ["/diff", "/diff src/agentx/cli.py"], "related": ["/git", "/review", "/commit"]},
    {"usage": "/stage PATH...", "description": "逐檔 stage 指定檔案；拒絕 .、glob、目錄與 workspace 外路徑", "examples": ["/stage README.md"], "related": ["/diff", "/git", "/commit"], "risk": "YELLOW - 會修改 git index"},
    {"usage": "/unstage PATH...", "description": "逐檔 unstage 指定檔案，保留 worktree 修改", "examples": ["/unstage README.md"], "related": ["/stage", "/diff", "/git"], "risk": "YELLOW - 會修改 git index"},
    {"usage": "/push", "description": "推送目前 branch 到既有 upstream；不接受參數", "examples": ["/push"], "related": ["/git", "/commit", "/review"], "risk": "YELLOW - 外部 git write"},
    {"usage": "/apply PATCH_FILE", "description": "套用 workspace 內 patch 檔，會先要求 approval", "examples": ["/apply fix.patch"], "related": ["/diff", "/review", "/test"], "risk": "YELLOW - 套用 patch，會要求 approval"},
    {"usage": "/approval [ask|auto|off|strict|auto-approve|deny]", "description": "查看或切換 YELLOW 工具 approval policy", "examples": ["/approval", "/approval strict"], "related": ["/tools", "/run", "/docker"]},
    {"usage": "/memory QUERY", "description": "查詢目前 namespace 的 Memory Hall 記憶", "examples": ["/memory agentX handoff"], "related": ["/remember", "/handoff", "/resume"]},
    {"usage": "/run COMMAND", "description": "執行固定 allowlist 命令", "examples": ["/run uv run pytest -q"], "related": ["/tools", "/approval", "/test"], "risk": "YELLOW - 執行 allowlisted shell command"},
    {"usage": "/docker [ps|build|up|logs|down]", "description": "執行 workspace 內 Docker Compose allowlist 指令", "examples": ["/docker ps", "/docker logs"], "related": ["/tools", "/approval", "/run"], "risk": "YELLOW - Docker build/up/down 需注意 runtime side effects"},
    {"usage": "/test", "description": "執行固定 allowlist 驗證：ruff check 與 pytest", "examples": ["/test"], "related": ["/review", "/commit"], "risk": "GREEN - 執行既有驗證命令"},
    {"usage": "/review", "description": "收集 git diff 與測試結果，輸出 findings-first review", "examples": ["/review"], "related": ["/diff", "/test", "/commit"]},
    {"usage": "/commit [MESSAGE]", "description": "跑測試後逐檔 stage、中文 commit 並 push", "examples": ["/commit 新增 workflow 單一路徑查詢"], "related": ["/review", "/test", "/push"], "risk": "YELLOW - 會跑測試、stage、commit 並 push"},
    {"usage": "/plan", "description": "切換 plan 模式；plan 模式只討論方案，不使用工具", "examples": ["/plan"], "related": ["/execute", "/mode", "/plan-task"]},
    {"usage": "/execute", "description": "從 plan 模式切換至執行模式，後續將可使用工具實際執行方案", "examples": ["/execute"], "related": ["/plan", "/mode", "/task"]},
    {"usage": "/mode chat", "description": "切換到純聊天模式，不使用工具，速度較快", "examples": ["/mode chat", "/mode agent", "/mode ask"], "related": ["/plan", "/execute", "/status"]},
    {"usage": "/mode ask", "description": "切換到單次任務語意的 agent 工具模式，同 /mode agent", "examples": ["/mode chat", "/mode agent", "/mode ask"], "related": ["/plan", "/execute", "/status"]},
    {"usage": "/mode agent", "description": "切換到 agent 工具模式，可使用 repo / git / Memory Hall 工具", "examples": ["/mode chat", "/mode agent", "/mode ask"], "related": ["/plan", "/execute", "/status"]},
    {"usage": "/models", "description": "列出 Ollama 目前可用模型", "examples": ["/models"], "related": ["/model", "/status", "/doctor"]},
    {"usage": "/model [MODEL]", "description": "查看或切換 Ollama 模型，例如 /model gemma4:31b", "examples": ["/model", "/model gemma4:31b"], "related": ["/models", "/status", "/config"]},
    {"usage": "/persona [default|tutor|gemma4]", "description": "查看或切換人格設定；tutor 是家庭教師，gemma4 是弱模型專用（小步驟+嚴格驗證）", "examples": ["/persona", "/persona gemma4"], "related": ["/mode", "/status", "/model"]},
    {"usage": "/remember TEXT", "description": "把指定內容寫入目前 Memory Hall namespace", "examples": ["/remember agentX 新增 command help metadata 覆蓋率"], "related": ["/memory", "/handoff", "/resume"], "risk": "YELLOW - 會寫入 Memory Hall"},
    {"usage": "/status", "description": "顯示目前模型、模式、namespace、訊息數與粗估 context tokens", "examples": ["/status"], "related": ["/context", "/model", "/approval"]},
    {"usage": "/clear", "description": "清空目前 shell session 上下文，並重新載入 repo 與 Memory Hall context", "examples": ["/clear"], "related": ["/context", "/resume", "/status"]},
    {"usage": "/exit", "description": "離開 agentX shell", "examples": ["/exit"], "related": ["/quit", "/handoff", "/sessions"]},
    {"usage": "/quit", "description": "離開 agentX shell，同 /exit", "examples": ["/quit"], "related": ["/exit", "/handoff", "/sessions"]},
]


SLASH_COMMANDS = [(str(item["usage"]), str(item["description"])) for item in COMMAND_CATALOG]

COMMAND_EXAMPLES = {
    str(item["usage"]).split()[0]: [str(example) for example in item["examples"]]
    for item in COMMAND_CATALOG
}
COMMAND_RELATED = {
    str(item["usage"]).split()[0]: [str(command) for command in item["related"]]
    for item in COMMAND_CATALOG
}
COMMAND_RISK_HINTS = {
    str(item["usage"]).split()[0]: str(item["risk"])
    for item in COMMAND_CATALOG
    if "risk" in item
}


def command_catalog_payload() -> dict[str, object]:
    return filtered_command_catalog_payload()


def filtered_command_catalog_payload(query: str | None = None) -> dict[str, object]:
    normalized_query = (query or "").strip().lower()
    commands: list[dict[str, object]] = []
    for item in COMMAND_CATALOG:
        usage = str(item["usage"])
        command = usage.split()[0]
        examples = [str(example) for example in item["examples"]]
        related = [str(related) for related in item["related"]]
        risk = str(item.get("risk", "GREEN - read-only, local display, or low-risk routing"))
        if normalized_query and not _catalog_item_matches(
            normalized_query,
            usage=usage,
            command=command,
            description=str(item["description"]),
            examples=examples,
            related=related,
            risk=risk,
        ):
            continue
        commands.append(
            {
                "command": command,
                "usage": usage,
                "description": str(item["description"]),
                "examples": examples,
                "related": related,
                "risk": risk,
            }
        )
    return {
        "schema": "agentx.command_catalog.v1",
        "query": query or "",
        "count": len(commands),
        "commands": commands,
    }


def _catalog_item_matches(
    query: str,
    *,
    usage: str,
    command: str,
    description: str,
    examples: list[str],
    related: list[str],
    risk: str,
) -> bool:
    if query.startswith("/"):
        return command.lower().startswith(query) or usage.lower().startswith(query)
    haystack = " ".join([command, usage, description, *examples, *related, risk]).lower()
    return query in haystack


def slash_command_entries() -> dict[str, tuple[str, str]]:
    return {command.split()[0]: (command, desc) for command, desc in SLASH_COMMANDS}


def normalize_slash_command_topic(topic: str) -> str:
    normalized = topic.strip().split()[0] if topic.strip() else ""
    if normalized and not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return normalized


def slash_command_help(topic: str) -> str:
    key = normalize_slash_command_topic(topic)
    entries = slash_command_entries()
    if not key or key not in entries:
        available = ", ".join(sorted(entries))
        label = topic.strip() or "(empty)"
        return f"command not found: {label}\navailable: {available}\nexample: /help workflow"

    usage, description = entries[key]
    risk = COMMAND_RISK_HINTS.get(key, "GREEN - read-only, local display, or low-risk routing")
    examples = COMMAND_EXAMPLES.get(key, [usage])
    related = COMMAND_RELATED.get(key, [])

    lines = [
        f"Command: {key}",
        f"Usage: {usage}",
        f"Description: {description}",
        f"Risk: {risk}",
        "Examples:",
        *[f"- {example}" for example in examples],
    ]
    if related:
        lines.extend(["Related:", *[f"- {command}" for command in related]])
    return "\n".join(lines)


def slash_command_suggestions(command: str, *, limit: int = 3) -> list[str]:
    key = normalize_slash_command_topic(command)
    entries = slash_command_entries()
    if not key or key in entries:
        return []
    commands = sorted(entries)
    matches = get_close_matches(key, commands, n=limit, cutoff=0.58)
    if matches:
        return matches
    prefix_matches = [item for item in commands if item.startswith(key[:3])]
    return prefix_matches[:limit]


def format_unknown_slash_command(prompt: str) -> str:
    command = prompt.strip().split(None, 1)[0] if prompt.strip() else ""
    suggestions = slash_command_suggestions(command)
    lines = [f"unknown slash command: {command or '(empty)'}"]
    if suggestions:
        lines.append("Did you mean:")
        lines.extend(f"- {item}" for item in suggestions)
    lines.append("Use /help for all commands or /help COMMAND for details.")
    return "\n".join(lines)
