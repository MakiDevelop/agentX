from __future__ import annotations

from difflib import get_close_matches

CommandCatalogItem = dict[str, object]

COMMAND_CATALOG: list[CommandCatalogItem] = [
    {"usage": "/help [COMMAND]", "description": "列出所有 slash command；提供 COMMAND 時顯示單一命令說明", "examples": ["/help", "/help workflow", "/help /infra"], "related": ["/guide", "/workflows", "/workflow"]},
    {"usage": "/commands [QUERY]", "description": "列出或搜尋 slash command catalog；QUERY 支援命令 prefix 或 keyword", "examples": ["/commands", "/commands /workflow", "/commands memory"], "related": ["/help", "/guide", "/workflows"]},
    {"usage": "/guide", "description": "60 秒快速導覽：模式選擇、常用工作流、安全與記憶", "examples": ["/guide"], "related": ["/help", "/workflows", "/tools"]},
    {"usage": "/workflows", "description": "列出實務工作流：理解、修改、測試、review、handoff", "examples": ["/workflows"], "related": ["/workflow", "/guide", "/help"]},
    {"usage": "/workflow NAME", "description": "輸出單一 workflow recipe，例如 headless、audit、commit", "examples": ["/workflow headless", "/workflow audit", "/workflow commit"], "related": ["/workflows", "/guide", "/help"]},
    {"usage": "/init", "description": "掃描 repo 並寫入 project profile 到 Memory Hall", "examples": ["/init"], "related": ["/doctor", "/memory", "/remember"]},
    {"usage": "/task [TEXT|status|list|add ...|update <id> ...|done <id>|clear]", "description": "多任務清單管理（已統一為真相來源）", "examples": ["/task status", "/task add 補 README 文件", "/task update 1 done"], "related": ["/plan-task", "/intent", "/status"]},
    {"usage": "/doctor", "description": "檢查 Ollama、模型、Memory Hall、git、uv 狀態", "examples": ["/doctor"], "related": ["/status", "/config", "/tools"]},
    {"usage": "/config", "description": "顯示目前 agentX 設定", "examples": ["/config", "/config set mode agent"], "related": ["/doctor", "/status", "/model"], "risk": "YELLOW - set 會寫入 .agentx/config.toml"},
    {"usage": "/config set KEY VALUE", "description": "寫入 .agentx/config.toml", "examples": ["/config", "/config set mode agent"], "related": ["/doctor", "/status", "/model"], "risk": "YELLOW - set 會寫入 .agentx/config.toml"},
    {"usage": "/tools [QUERY]", "description": "列出或搜尋可用工具；QUERY 支援 keyword 或 GREEN/YELLOW/RED 風險分組", "examples": ["/tools", "/tools git", "/tools YELLOW"], "related": ["/approval", "/run", "/help"]},
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

CLI_CAPABILITIES: list[CommandCatalogItem] = [
    {
        "command": "agentx",
        "usage": "agentx -p TEXT --agent --json",
        "description": "Run a headless agent task and emit agentx.headless_result.v1.",
        "examples": ["agentx -p 'inspect repo' --agent --json", "agentx --prompt-file briefing.md --agent --output-format jsonl"],
        "schemas": ["agentx.headless_result.v1"],
        "jsonl_event": "result",
        "risk": "YELLOW - agent mode may run tools according to approval policy",
    },
    {
        "command": "agentx init",
        "usage": "agentx init --json",
        "description": "Inspect workspace project profile; --write-memory is explicit opt-in.",
        "examples": ["agentx init --json", "agentx init --write-memory --json"],
        "schemas": ["agentx.init.v1", "agentx.project_profile.v1"],
        "jsonl_event": "init",
        "risk": "GREEN by default; YELLOW with --write-memory",
    },
    {
        "command": "agentx sessions",
        "usage": "agentx sessions --json",
        "description": "List saved transcript summaries for resume and audit routing.",
        "examples": ["agentx sessions --json", "agentx sessions --limit 5 --output-format jsonl"],
        "schemas": ["agentx.sessions.v1"],
        "jsonl_event": "sessions",
        "risk": "GREEN - read-only local inspection",
    },
    {
        "command": "agentx artifacts",
        "usage": "agentx artifacts [.agentx/runs] --json",
        "description": "List saved headless artifact bundles for runner discovery and resume routing.",
        "examples": ["agentx artifacts --json", "agentx artifacts .agentx/runs/latest --output-format jsonl"],
        "schemas": ["agentx.artifacts.v1"],
        "jsonl_event": "artifacts",
        "risk": "GREEN - read-only local inspection",
    },
    {
        "command": "agentx handoff-inspect",
        "usage": "agentx handoff-inspect PATH --json",
        "description": "Inspect a saved headless result payload and extract resume fields or handoff gates.",
        "examples": [
            "agentx handoff-inspect .agentx/runs/latest/result.json --json",
            "agentx handoff-inspect result.json --field resume_command --output-format jsonl",
        ],
        "schemas": [],
        "jsonl_event": "handoff_inspect",
        "risk": "GREEN - read-only local artifact inspection",
    },
    {
        "command": "agentx handoff-resume",
        "usage": "agentx handoff-resume DIR_OR_RESULT --dry-run",
        "description": "Build or execute the resume command from a headless artifact bundle or result payload.",
        "examples": [
            "agentx handoff-resume .agentx/runs/latest --dry-run",
            "agentx handoff-resume .agentx/runs/latest --dry-run --output-format jsonl",
        ],
        "schemas": [],
        "jsonl_event": "handoff_resume",
        "risk": "GREEN with --dry-run; YELLOW with --execute because it runs the generated command",
    },
    {
        "command": "agentx approvals",
        "usage": "agentx approvals [SESSION] --json",
        "description": "List approval receipts from transcripts; can fail CI on denied receipts.",
        "examples": ["agentx approvals latest --json", "agentx approvals latest --denied --fail-on-denied --json"],
        "schemas": ["agentx.approvals.v1"],
        "jsonl_event": "approvals",
        "risk": "GREEN - read-only local inspection",
    },
    {
        "command": "agentx traces",
        "usage": "agentx traces [SESSION] --json",
        "description": "Summarize transcript events, tools, approvals, and error-like records.",
        "examples": ["agentx traces latest --json", "agentx traces 20260102-000000 --output-format jsonl"],
        "schemas": ["agentx.traces.v1"],
        "jsonl_event": "traces",
        "risk": "GREEN - read-only local inspection",
    },
    {
        "command": "agentx diff",
        "usage": "agentx diff [PATH] --json",
        "description": "Summarize git diff as machine-readable file stats for review and commit runners.",
        "examples": ["agentx diff --json", "agentx diff src/agentx/cli.py --staged --output-format jsonl"],
        "schemas": ["agentx.diff.v1"],
        "jsonl_event": "diff",
        "risk": "GREEN - read-only local git inspection",
    },
    {
        "command": "agentx patch-check",
        "usage": "agentx patch-check PATCH --json",
        "description": "Validate a workspace patch file with git apply --check and safe path inspection without applying it.",
        "examples": ["agentx patch-check patches/fix.patch --json", "agentx patch-check fix.patch --json --fail-on-blocker"],
        "schemas": ["agentx.patch_check.v1"],
        "jsonl_event": "patch_check",
        "risk": "GREEN - read-only local patch inspection",
    },
    {
        "command": "agentx command-plan",
        "usage": "agentx command-plan COMMAND --json",
        "description": "Classify a shell command against agentX allowlists, approval policy, and destructive blockers without executing it.",
        "examples": ["agentx command-plan 'uv run pytest -q' --json", "agentx command-plan 'npm test' --json", "agentx command-plan 'git clean -fd' --json --fail-on-blocker"],
        "schemas": ["agentx.command_plan.v1"],
        "jsonl_event": "command_plan",
        "risk": "GREEN - read-only command policy inspection",
    },
    {
        "command": "agentx review",
        "usage": "agentx review --json",
        "description": "Run a deterministic review gate: diff summary plus verification posture.",
        "examples": ["agentx review --json", "agentx review --json --fail-on-blocker", "agentx review --skip-verify --output-format jsonl"],
        "schemas": ["agentx.review.v1"],
        "jsonl_event": "review",
        "risk": "GREEN - read-only local git inspection and existing verification commands",
    },
    {
        "command": "agentx commit-plan",
        "usage": "agentx commit-plan --message TEXT --json",
        "description": "Preview the files, message, review gate, and blockers for a future commit without staging.",
        "examples": ["agentx commit-plan --message '新增 review gate' --json", "agentx commit-plan -m '更新文件' --skip-verify --output-format jsonl"],
        "schemas": ["agentx.commit_plan.v1"],
        "jsonl_event": "commit_plan",
        "risk": "GREEN - read-only local git inspection and existing verification commands",
    },
    {
        "command": "agentx gate",
        "usage": "agentx gate --json",
        "description": "Run an aggregate runner gate: review, static doctor, and latest approval-denial audit.",
        "examples": ["agentx gate --json", "agentx gate --json --fail-on-blocker", "agentx gate --skip-verify --skip-approvals --output-format jsonl"],
        "schemas": ["agentx.gate.v1"],
        "jsonl_event": "gate",
        "risk": "GREEN - read-only local inspection and existing verification commands",
    },
    {
        "command": "agentx next",
        "usage": "agentx next --json",
        "description": "Recommend the next runner command from local diff, tasks, artifacts, and approval receipts.",
        "examples": ["agentx next --json", "agentx next --output-format jsonl"],
        "schemas": ["agentx.next.v1"],
        "jsonl_event": "next",
        "risk": "GREEN - read-only local planning",
    },
    {
        "command": "agentx tasks",
        "usage": "agentx tasks [STATUS] --json",
        "description": "List project task state from .agentx/tasks.json.",
        "examples": ["agentx tasks --json", "agentx tasks active --output-format jsonl"],
        "schemas": ["agentx.tasks.v1"],
        "jsonl_event": "tasks",
        "risk": "GREEN - read-only local inspection",
    },
    {
        "command": "agentx task-update",
        "usage": "agentx task-update ID STATUS [NOTES] --json",
        "description": "Update one project task in .agentx/tasks.json for headless runners.",
        "examples": [
            "agentx task-update 1 done --json",
            "agentx task-update 2 blocked 'needs Maki input' --output-format jsonl",
        ],
        "schemas": ["agentx.task_update.v1"],
        "jsonl_event": "task_update",
        "risk": "YELLOW - writes local .agentx/tasks.json state",
    },
    {
        "command": "agentx verify",
        "usage": "agentx verify --json",
        "description": "Run detected project verification commands and emit check results.",
        "examples": ["agentx verify --json", "agentx verify --json --fail-on-error"],
        "schemas": ["agentx.verify.v1"],
        "jsonl_event": "verify",
        "risk": "GREEN - runs existing local verification commands",
    },
    {
        "command": "agentx inspect",
        "usage": "agentx inspect --json",
        "description": "Print a read-only aggregate preflight bundle for external runners.",
        "examples": ["agentx inspect --json", "agentx inspect --output-format jsonl"],
        "schemas": ["agentx.inspect.v1"],
        "jsonl_event": "inspect",
        "risk": "GREEN - read-only local inspection",
    },
    {
        "command": "agentx status",
        "usage": "agentx status --json",
        "description": "Inspect runtime, git posture, task counts, and resolved config.",
        "examples": ["agentx status --json", "agentx status --output-format jsonl"],
        "schemas": ["agentx.status.v1", "agentx.config.v1"],
        "jsonl_event": "status",
        "risk": "GREEN - read-only local inspection",
    },
    {
        "command": "agentx doctor",
        "usage": "agentx doctor --json",
        "description": "Run health checks; --static avoids live Ollama and memory probes.",
        "examples": ["agentx doctor --static --json", "agentx doctor --static --json --fail-on-error"],
        "schemas": ["agentx.doctor.v1"],
        "jsonl_event": "doctor",
        "risk": "GREEN - local checks; live probes may touch configured local services",
    },
    {
        "command": "agentx commands",
        "usage": "agentx commands [QUERY] --json",
        "description": "List slash command catalog for interactive shell routing.",
        "examples": ["agentx commands --json", "agentx commands memory --json"],
        "schemas": ["agentx.command_catalog.v1"],
        "jsonl_event": "commands",
        "risk": "GREEN - read-only catalog",
    },
    {
        "command": "agentx tools",
        "usage": "agentx tools [QUERY] --json",
        "description": "List tool catalog and GREEN/YELLOW/RED risk metadata.",
        "examples": ["agentx tools --json", "agentx tools YELLOW --json"],
        "schemas": ["agentx.tool_catalog.v1"],
        "jsonl_event": "tools",
        "risk": "GREEN - read-only catalog",
    },
    {
        "command": "agentx tool-plan",
        "usage": "agentx tool-plan TOOL --args-json JSON --json",
        "description": "Classify an agentX tool call, aliases, risk, approval posture, and basic arg blockers without executing it.",
        "examples": [
            "agentx tool-plan read_file --args-json '{\"path\":\"README.md\"}' --json",
            "agentx tool-plan search_replace --args-json '{\"path\":\"README.md\",\"edits\":[{\"oldText\":\"old\",\"newText\":\"new\"}]}' --json",
        ],
        "schemas": ["agentx.tool_plan.v1"],
        "jsonl_event": "tool_plan",
        "risk": "GREEN - read-only tool-call policy inspection",
    },
    {
        "command": "agentx infra",
        "usage": "agentx infra [all|quick|project|resource|home|vps|resource-bundle] --json",
        "description": "Read Maki's project/resource/home-AI/VPS maps as read-only context for runtime preflight.",
        "examples": ["agentx infra home --json", "agentx infra vps --json", "agentx infra resource-bundle --output-format jsonl"],
        "schemas": ["agentx.infrastructure_context.v1"],
        "jsonl_event": "infra",
        "risk": "GREEN - read-only local infrastructure map context",
    },
    {
        "command": "agentx memory-status",
        "usage": "agentx memory-status --json",
        "description": "Inspect read-only Memory Hall / AMH backend posture for runners without writing memory.",
        "examples": [
            "agentx memory-status --json",
            "agentx memory-status --live-probe --output-format jsonl",
        ],
        "schemas": ["agentx.memory_status.v1"],
        "jsonl_event": "memory_status",
        "risk": "GREEN - read-only memory backend status inspection",
    },
    {
        "command": "agentx memory-read",
        "usage": "agentx memory-read QUERY --json",
        "description": "Read/search Memory Hall through the configured backend for runner handoff context.",
        "examples": [
            "agentx memory-read 'handoff' --namespace project:agentX --json",
            "agentx memory-read 'ACE status' --limit 3 --output-format jsonl",
        ],
        "schemas": ["agentx.memory_read.v1"],
        "jsonl_event": "memory_read",
        "risk": "GREEN - read-only memory query",
    },
    {
        "command": "agentx memory-write",
        "usage": "agentx memory-write CONTENT --write --json",
        "description": "Preview or explicitly write one ACA-shaped Memory Hall entry.",
        "examples": [
            "agentx memory-write 'handoff summary' --type handoff --json",
            "agentx memory-write 'human-confirmed fact' --tier human_confirmed --type fact --write --json",
        ],
        "schemas": ["agentx.memory_write.v1"],
        "jsonl_event": "memory_write",
        "risk": "GREEN dry-run by default; YELLOW with --write because it writes memory",
    },
    {
        "command": "agentx instructions",
        "usage": "agentx instructions --json",
        "description": "Inspect repo-local AGENTX.md / AGENTS.md / CLAUDE.md instruction files in bootstrap priority order.",
        "examples": [
            "agentx instructions --json",
            "agentx instructions --workspace /path/to/repo --output-format jsonl",
        ],
        "schemas": ["agentx.local_instructions.v1"],
        "jsonl_event": "instructions",
        "risk": "GREEN - read-only repo-local instruction inspection",
    },
    {
        "command": "agentx ace-init",
        "usage": "agentx ace-init SESSION --goal GOAL --json",
        "description": "Preview or create an ACE session directory with _manifest.md for multi-agent file-based coordination.",
        "examples": [
            "agentx ace-init 2026-07-15-agentx-ace --goal 'Add ACE support' --json",
            "agentx ace-init 2026-07-15-agentx-ace --goal 'Add ACE support' --route 'Codex: architect; Gemini: review' --write --json",
        ],
        "schemas": ["agentx.ace_session.v1"],
        "jsonl_event": "ace_init",
        "risk": "GREEN by default; YELLOW with --write because it creates local ACE files",
    },
    {
        "command": "agentx ace-append",
        "usage": "agentx ace-append SESSION SECTION TEXT --json",
        "description": "Append one timestamped entry to an ACE _manifest.md section.",
        "examples": [
            "agentx ace-append 2026-07-15-agentx-ace finding 'Gemini found no blocker' --json",
            "agentx ace-append 2026-07-15-agentx-ace decision 'Use file-based ACE manifest first' --agent codex --json",
        ],
        "schemas": ["agentx.ace_append.v1"],
        "jsonl_event": "ace_append",
        "risk": "YELLOW - writes local ACE manifest files",
    },
    {
        "command": "agentx ace-briefing",
        "usage": "agentx ace-briefing SESSION --agent AGENT --json",
        "description": "Preview or write a scoped briefing file for one agent from an ACE manifest.",
        "examples": [
            "agentx ace-briefing 2026-07-15-agentx-ace --agent gemini --role Reviewer --task 'Review the proposal' --json",
            "agentx ace-briefing 2026-07-15-agentx-ace --agent grok --role Implementer --write --json",
        ],
        "schemas": ["agentx.ace_briefing.v1"],
        "jsonl_event": "ace_briefing",
        "risk": "GREEN by default; YELLOW with --write because it creates local ACE briefing files",
    },
    {
        "command": "agentx ace-answer",
        "usage": "agentx ace-answer SESSION --agent AGENT --answer TEXT --json",
        "description": "Record one external agent answer file and append its summary to the ACE manifest.",
        "examples": [
            "agentx ace-answer 2026-07-15-agentx-ace --agent gemini --answer 'No blocker found' --summary 'Gemini found no blocker' --json",
            "agentx ace-answer 2026-07-15-agentx-ace --agent grok --section decision --answer 'Use option A' --json",
        ],
        "schemas": ["agentx.ace_answer.v1"],
        "jsonl_event": "ace_answer",
        "risk": "YELLOW - writes local ACE answer and manifest files",
    },
    {
        "command": "agentx ace-status",
        "usage": "agentx ace-status SESSION --json",
        "description": "Summarize one ACE session manifest, briefing files, answer files, and open questions.",
        "examples": [
            "agentx ace-status 2026-07-15-agentx-ace --json",
            "agentx ace-status 2026-07-15-agentx-ace --max-manifest-chars 4000 --output-format jsonl",
        ],
        "schemas": ["agentx.ace_status.v1"],
        "jsonl_event": "ace_status",
        "risk": "GREEN - read-only ACE session status inspection",
    },
    {
        "command": "agentx workflows",
        "usage": "agentx workflows [QUERY] --json",
        "description": "List practical workflow recipes for headless, audit, and commit flows.",
        "examples": ["agentx workflows --json", "agentx workflows headless --json"],
        "schemas": ["agentx.workflow_catalog.v1"],
        "jsonl_event": "workflows",
        "risk": "GREEN - read-only catalog",
    },
    {
        "command": "agentx workflow-plan",
        "usage": "agentx workflow-plan NAME --input KEY=VALUE --json",
        "description": "Expand one workflow into ordered command plans, substituted ready commands, required inputs, blockers, and side-effect gates without executing it.",
        "examples": [
            "agentx workflow-plan memory --json",
            "agentx workflow-plan memory --input 完成與待辦='完成 AMH 交接' --json",
            "agentx workflow-plan ace --json --fail-on-blocker",
        ],
        "schemas": ["agentx.workflow_plan.v1"],
        "jsonl_event": "workflow_plan",
        "risk": "GREEN - read-only workflow execution planning",
    },
    {
        "command": "agentx workflow-run",
        "usage": "agentx workflow-run NAME --input KEY=VALUE --result-output PATH --json",
        "description": "Dry-run a workflow or execute eligible GREEN agentx CLI steps; can persist the result artifact; YELLOW gates require --allow-yellow-gates plus --approval-reason.",
        "examples": [
            "agentx workflow-run memory --input 完成與待辦='完成 AMH 交接' --json",
            "agentx workflow-run memory --input 完成與待辦='完成 AMH 交接' --result-output .agentx/runs/workflow-memory.json --json",
            "agentx workflow-run infra --execute --json --fail-on-blocker",
            "agentx workflow-run memory --input 完成與待辦='完成 AMH 交接' --execute --allow-yellow-gates --approval-reason 'Maki approved memory handoff write' --json",
        ],
        "schemas": ["agentx.workflow_run.v1"],
        "jsonl_event": "workflow_run",
        "risk": "GREEN dry-run by default; YELLOW with --execute because it can run commands",
    },
    {
        "command": "agentx workflow-inspect",
        "usage": "agentx workflow-inspect PATH --input KEY=VALUE --json",
        "description": "Inspect a saved workflow-run artifact and generate a rerun command with known inputs plus placeholders for missing inputs.",
        "examples": [
            "agentx workflow-inspect .agentx/runs/workflow-memory.json --json",
            "agentx workflow-inspect .agentx/runs/workflow-memory.json --input 完成與待辦='完成 AMH 交接' --json",
            "agentx workflow-inspect .agentx/runs/workflow-memory.json --result-output auto --json",
            "agentx workflow-inspect .agentx/runs/workflow-memory.json --field resume_command",
        ],
        "schemas": ["agentx.workflow_artifact.v1"],
        "jsonl_event": "workflow_inspect",
        "risk": "GREEN - read-only local artifact inspection",
    },
    {
        "command": "agentx workflow-resume",
        "usage": "agentx workflow-resume PATH --input KEY=VALUE --dry-run --json",
        "description": "Build or execute the generated workflow-run rerun command from a saved workflow-run artifact.",
        "examples": [
            "agentx workflow-resume .agentx/runs/workflow-memory.json --dry-run --json",
            "agentx workflow-resume .agentx/runs/workflow-memory.json --input 完成與待辦='完成 AMH 交接' --dry-run --json",
            "agentx workflow-resume .agentx/runs/workflow-memory.json --result-output auto --dry-run --json",
            "agentx workflow-resume .agentx/runs/workflow-memory.json --workflow-execute --dry-run --json",
        ],
        "schemas": ["agentx.workflow_resume.v1"],
        "jsonl_event": "workflow_resume",
        "risk": "GREEN with --dry-run; YELLOW with --execute because it runs the generated command",
    },
    {
        "command": "agentx models",
        "usage": "agentx models --json",
        "description": "List models for the selected backend.",
        "examples": ["agentx models --json", "agentx models --backend llama_cpp --base-url http://127.0.0.1:8081 --json"],
        "schemas": [],
        "jsonl_event": "models",
        "risk": "GREEN - backend catalog probe",
    },
    {
        "command": "agentx backends",
        "usage": "agentx backends --json",
        "description": "List registered LLM backend implementations.",
        "examples": ["agentx backends --json"],
        "schemas": [],
        "jsonl_event": "backends",
        "risk": "GREEN - read-only catalog",
    },
    {
        "command": "agentx command-parity",
        "usage": "agentx command-parity --json",
        "description": "Inspect slash-command to runner JSON command parity for AMH, ACE, artifacts, next, gate, and command-plan surfaces.",
        "examples": ["agentx command-parity --json", "agentx command-parity memory --output-format jsonl"],
        "schemas": ["agentx.command_parity.v1"],
        "jsonl_event": "command_parity",
        "risk": "GREEN - read-only command catalog inspection",
    },
    {
        "command": "agentx reliability-suite",
        "usage": "agentx reliability-suite --json",
        "description": "Run local-only recorded backend reliability cases and score headless artifacts, next, gate, and recovery posture.",
        "examples": ["agentx reliability-suite --json", "agentx reliability-suite --case edit --run-id local-check --output-format jsonl"],
        "schemas": ["agentx.reliability_suite.v1"],
        "jsonl_event": "reliability_suite",
        "risk": "YELLOW - writes local .agentx/reliability fixture artifacts; no external services or memory writes",
    },
    {
        "command": "agentx version",
        "usage": "agentx version --json",
        "description": "Print agentX and Python runtime versions.",
        "examples": ["agentx version --json"],
        "schemas": [],
        "jsonl_event": "version",
        "risk": "GREEN - read-only local inspection",
    },
]

COMMAND_PARITY_MATRIX: list[dict[str, object]] = [
    {
        "domain": "memory",
        "status": "mapped",
        "slash_commands": ["/memory QUERY", "/remember TEXT", "/handoff [TEXT]", "/config set memory_backend|memory_amh_store|memory_amh_path VALUE"],
        "runner_commands": ["agentx memory-status --json", "agentx memory-read QUERY --json", "agentx memory-write CONTENT --json"],
        "schemas": ["agentx.memory_status.v1", "agentx.memory_read.v1", "agentx.memory_write.v1"],
        "jsonl_events": ["memory_status", "memory_read", "memory_write"],
        "workflow_aliases": ["memory", "amh"],
        "risk_alignment": "read/status are GREEN; shell /remember and runner memory-write require explicit write behavior",
        "notes": "Runner memory-write is dry-run unless --write is provided; shell /remember is explicit human input and writes through Memory Hall tools.",
    },
    {
        "domain": "ace",
        "status": "runner_only_workflow",
        "slash_commands": ["/workflow ace", "/workflow council", "/workflows"],
        "runner_commands": [
            "agentx ace-init SESSION --goal GOAL --json",
            "agentx ace-briefing SESSION --agent AGENT --json",
            "agentx ace-answer SESSION --agent AGENT --answer TEXT --json",
            "agentx ace-status SESSION --json",
        ],
        "schemas": ["agentx.ace_session.v1", "agentx.ace_briefing.v1", "agentx.ace_answer.v1", "agentx.ace_status.v1"],
        "jsonl_events": ["ace_init", "ace_briefing", "ace_answer", "ace_status"],
        "workflow_aliases": ["ace", "council", "multi-agent", "gemini"],
        "risk_alignment": "ACE previews are GREEN; --write creates local ACE files and is explicit",
        "notes": "Interactive shell discovers ACE through workflow recipes; structured ACE operations are runner-facing top-level commands.",
    },
    {
        "domain": "artifacts",
        "status": "runner_only",
        "slash_commands": ["/workflow headless", "/workflow audit"],
        "runner_commands": ["agentx artifacts --json", "agentx handoff-inspect PATH --json", "agentx handoff-resume DIR_OR_RESULT --dry-run"],
        "schemas": ["agentx.artifacts.v1"],
        "jsonl_events": ["artifacts", "handoff_inspect", "handoff_resume"],
        "workflow_aliases": ["headless", "audit"],
        "risk_alignment": "artifact inspection is GREEN; handoff-resume is GREEN with --dry-run and YELLOW with --execute",
        "notes": "Shell workflows show copyable routes; runner commands provide machine-readable artifact discovery and resume planning.",
    },
    {
        "domain": "next",
        "status": "runner_only",
        "slash_commands": ["/workflow audit", "/workflow commit"],
        "runner_commands": ["agentx next --json", "agentx inspect --json"],
        "schemas": ["agentx.next.v1", "agentx.inspect.v1"],
        "jsonl_events": ["next", "inspect"],
        "workflow_aliases": ["audit", "commit"],
        "risk_alignment": "GREEN read-only routing",
        "notes": "The shell has workflow recipes for human-readable next routes; runner next/inspect returns deterministic recommendations.",
    },
    {
        "domain": "gate",
        "status": "mapped",
        "slash_commands": ["/review", "/commit [MESSAGE]", "/test"],
        "runner_commands": ["agentx gate --json", "agentx review --json", "agentx verify --json", "agentx commit-plan --message TEXT --json"],
        "schemas": ["agentx.gate.v1", "agentx.review.v1", "agentx.verify.v1", "agentx.commit_plan.v1"],
        "jsonl_events": ["gate", "review", "verify", "commit_plan"],
        "workflow_aliases": ["audit", "commit"],
        "risk_alignment": "review/gate/commit-plan are GREEN previews; shell /commit performs YELLOW git write after checks",
        "notes": "Runner surfaces separate preflight from mutation; shell /commit remains the interactive commit/push path.",
    },
    {
        "domain": "command-plan",
        "status": "runner_only",
        "slash_commands": ["/run COMMAND", "/docker ...", "/apply PATCH_FILE"],
        "runner_commands": ["agentx command-plan COMMAND --json", "agentx tool-plan TOOL --args-json JSON --json", "agentx patch-check PATCH --json"],
        "schemas": ["agentx.command_plan.v1", "agentx.tool_plan.v1", "agentx.patch_check.v1"],
        "jsonl_events": ["command_plan", "tool_plan", "patch_check"],
        "workflow_aliases": [],
        "risk_alignment": "GREEN read-only preflight for commands and tool calls; execution remains separate",
        "notes": "Runner preflight mirrors shell execution families without executing commands.",
    },
]

RUNNER_RECOMMENDED_ENTRYPOINTS: list[dict[str, object]] = [
    {
        "name": "discover",
        "command": "agentx capabilities --json",
        "schema": "agentx.capabilities.v1",
        "reason": "discover stable runner-facing commands, schemas, events, and recommended entrypoints",
    },
    {
        "name": "preflight",
        "command": "agentx inspect --json",
        "schema": "agentx.inspect.v1",
        "reason": "collect read-only workspace status, diff, tasks, approvals, artifacts, next recommendation, and command plans",
    },
    {
        "name": "infra_preflight",
        "command": "agentx infra resource-bundle --json",
        "schema": "agentx.infrastructure_context.v1",
        "reason": "load read-only resource, home AI facilities, and VPS routing context before SSH, deploy, or cross-machine work",
    },
    {
        "name": "memory_handoff",
        "command": "agentx workflows memory --json",
        "schema": "agentx.workflow_catalog.v1",
        "reason": "discover the AMH read, dry-run write, and explicit write handoff sequence",
    },
    {
        "name": "ace_council",
        "command": "agentx workflows ace --json",
        "schema": "agentx.workflow_catalog.v1",
        "reason": "discover the ACE manifest, briefing, answer, and status workflow for multi-agent coordination",
    },
    {
        "name": "next",
        "command": "agentx next --json",
        "schema": "agentx.next.v1",
        "reason": "choose the next deterministic runner command from local state",
    },
    {
        "name": "gate",
        "command": "agentx gate --json --fail-on-blocker",
        "schema": "agentx.gate.v1",
        "reason": "block commit or handoff when review, doctor, or approval audit finds blockers",
    },
    {
        "name": "verify",
        "command": "agentx verify --json --fail-on-error",
        "schema": "agentx.verify.v1",
        "reason": "run detected verification commands and return process-compatible status",
    },
]


RUNNER_SMOKE_WORKFLOWS: list[dict[str, object]] = [
    {
        "name": "amh_memory_workflow_chain",
        "workflow": "memory",
        "risk": "GREEN - dry-run only; does not write AMH",
        "seed_command": "agentx workflow-run memory --input 完成與待辦='完成 AMH 交接' --result-output .agentx/runs/workflow-memory.json --json",
        "artifact": ".agentx/runs/workflow-memory.json",
        "expected_chain_status": "ready",
        "next_command": "agentx next --json",
        "resume_command": "agentx workflow-resume .agentx/runs/workflow-memory.json --result-output auto --dry-run --json",
        "gate_command": "agentx gate --skip-verify --skip-approvals --json",
        "covered_by": "tests/test_workflows_cli.py::test_memory_workflow_runner_smoke_links_artifact_next_resume_and_gate",
    },
    {
        "name": "ace_council_workflow_chain",
        "workflow": "ace",
        "risk": "GREEN - dry-run only; does not create ACE files",
        "seed_command": "agentx workflow-run ace --input SESSION=2026-07-15-agentx --input GOAL='Add ACE workflow' --input ANSWER='No blocker' --input SUMMARY='Gemini found no blocker' --result-output .agentx/runs/workflow-ace.json --json",
        "artifact": ".agentx/runs/workflow-ace.json",
        "expected_chain_status": "ready",
        "next_command": "agentx next --json",
        "resume_command": "agentx workflow-resume .agentx/runs/workflow-ace.json --result-output auto --dry-run --json",
        "gate_command": "agentx gate --skip-verify --skip-approvals --json",
        "covered_by": "tests/test_workflows_cli.py::test_ace_workflow_runner_smoke_links_artifact_next_resume_and_gate",
    },
]


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


def capabilities_payload(query: str | None = None) -> dict[str, object]:
    normalized_query = (query or "").strip().lower()
    capabilities: list[dict[str, object]] = []
    for item in CLI_CAPABILITIES:
        schemas = [str(schema) for schema in item.get("schemas", [])]
        examples = [str(example) for example in item["examples"]]
        risk = str(item["risk"])
        if normalized_query and not _capability_item_matches(
            normalized_query,
            command=str(item["command"]),
            usage=str(item["usage"]),
            description=str(item["description"]),
            examples=examples,
            schemas=schemas,
            jsonl_event=str(item["jsonl_event"]),
            risk=risk,
        ):
            continue
        capabilities.append(
            {
                "command": str(item["command"]),
                "usage": str(item["usage"]),
                "description": str(item["description"]),
                "examples": examples,
                "schemas": schemas,
                "jsonl_event": str(item["jsonl_event"]),
                "risk": risk,
            }
        )
    return {
        "schema": "agentx.capabilities.v1",
        "query": query or "",
        "count": len(capabilities),
        "recommended_entrypoints": RUNNER_RECOMMENDED_ENTRYPOINTS,
        "runner_smokes": RUNNER_SMOKE_WORKFLOWS,
        "by_schema": _capabilities_by_schema(capabilities),
        "capabilities": capabilities,
    }


def command_parity_payload(query: str | None = None) -> dict[str, object]:
    normalized_query = (query or "").strip().lower()
    entries: list[dict[str, object]] = []
    for item in COMMAND_PARITY_MATRIX:
        if normalized_query and normalized_query not in " ".join(
            [
                str(item["domain"]),
                str(item["status"]),
                *[str(value) for value in item["slash_commands"]],  # type: ignore[index]
                *[str(value) for value in item["runner_commands"]],  # type: ignore[index]
                *[str(value) for value in item["schemas"]],  # type: ignore[index]
                *[str(value) for value in item["jsonl_events"]],  # type: ignore[index]
                *[str(value) for value in item["workflow_aliases"]],  # type: ignore[index]
                str(item["risk_alignment"]),
                str(item["notes"]),
            ]
        ).lower():
            continue
        entries.append(
            {
                "domain": str(item["domain"]),
                "status": str(item["status"]),
                "slash_commands": [str(value) for value in item["slash_commands"]],  # type: ignore[index]
                "runner_commands": [str(value) for value in item["runner_commands"]],  # type: ignore[index]
                "schemas": [str(value) for value in item["schemas"]],  # type: ignore[index]
                "jsonl_events": [str(value) for value in item["jsonl_events"]],  # type: ignore[index]
                "workflow_aliases": [str(value) for value in item["workflow_aliases"]],  # type: ignore[index]
                "risk_alignment": str(item["risk_alignment"]),
                "notes": str(item["notes"]),
            }
        )
    return {
        "schema": "agentx.command_parity.v1",
        "query": query or "",
        "count": len(entries),
        "entries": entries,
        "by_domain": {str(entry["domain"]): entry for entry in entries},
    }


def _capabilities_by_schema(capabilities: list[dict[str, object]]) -> dict[str, dict[str, str]]:
    by_schema: dict[str, dict[str, str]] = {}
    for capability in capabilities:
        for schema in capability.get("schemas", []):
            schema_key = str(schema)
            if not schema_key:
                continue
            by_schema[schema_key] = {
                "command": str(capability["command"]),
                "jsonl_event": str(capability["jsonl_event"]),
                "usage": str(capability["usage"]),
            }
    return by_schema


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


def _capability_item_matches(
    query: str,
    *,
    command: str,
    usage: str,
    description: str,
    examples: list[str],
    schemas: list[str],
    jsonl_event: str,
    risk: str,
) -> bool:
    haystack = " ".join([command, usage, description, *examples, *schemas, jsonl_event, risk]).lower()
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
