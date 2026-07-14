# Resource Maps

agentX reads Maki's infrastructure maps as read-only context through `/infra` and the
`infrastructure_context` tool. This document defines how agentX should use those
maps when a request touches resources, home AI facilities, VPS hosts, or
domain-to-repo routing.

Canonical sources stay outside this repo:

| Map | Source | Question answered | agentX entry |
|-----|--------|-------------------|--------------|
| Quick ref | `~/infrastructure/infrastructure-quick-ref.md` | Which SSH alias, IP, port, or high-frequency runtime fact should be checked first? | `/infra quick` |
| Project map | `~/infrastructure/project-map.md` | Which repo owns a domain, service, or deployment target? | `/infra project` |
| Resource map | `~/infrastructure/resource-map.md` | Which machine, service, and access plane should be used? | `/infra resource` |
| Home AI facilities | `~/infrastructure/resource-map.md` section `家庭 AI 中心` | Which home AI node should handle this workload? | `/infra home`, `/infra 家庭AI設施` |
| VPS map | `~/infrastructure/resource-map.md` section `外網主機 / VPS` or `VPS 對照` | Which public VPS/domain hosts this service? | `/infra vps`, `/infra VPS地圖`, `/infra 外網主機` |

`/infra all` loads quick ref, project map, and resource map together. `/infra
resource-bundle` loads the resource map plus the extracted home AI and VPS
sections. The bundle is the canonical route for Maki's mixed wording
`資源地圖+家庭AI設施/VPS地圖`.

Snapshot status:

- Last synced in this repo: 2026-07-15.
- Source files checked: `~/infrastructure/infrastructure-quick-ref.md`,
  `~/infrastructure/project-map.md`, `~/infrastructure/resource-map.md`.
- This document is a routing snapshot and agentX usage contract, not the SSOT.
  When acting on infrastructure, read `/infra ...` or the source files again.
- Runtime `/infra` / `agentx infra` output redacts sensitive key/token/secret
  lines before returning context.

## Lookup Index

Use these lookups as the first move when Maki names a resource, machine, domain,
or deployment target:

| User wording | agentX lookup | Expected answer shape |
|--------------|---------------|-----------------------|
| `資源地圖`, `resource map` | `/infra resource` | machine, service, access plane, boundary |
| `專案地圖`, `project map` | `/infra project` | domain/service to repo ownership |
| `家庭AI地圖`, `家庭AI設施`, `設施地圖`, `home ai map` | `/infra home` | node role, workload route, stop condition |
| `VPS地圖`, `外網主機`, `vps map` | `/infra vps` | public host, service, repo association, caution |
| `資源地圖+家庭AI設施/VPS地圖`, `資源地圖+家庭AI設施／VPS地圖` | `/infra resource-bundle` | resource map + extracted home AI and VPS sections |
| mixed or unclear resource | `/infra all` | quick ref + project map + resource map context |

The lookup result is evidence for planning. It is not permission to perform SSH,
deploy, restart, delete, memory writes, or production changes.

## Agent-Facing Deliverables

When Maki asks agentX to "make the resource map", "家庭 AI 設施地圖", or
"VPS 地圖", the expected deliverable is this three-layer package:

| Layer | File / command | Purpose |
|-------|----------------|---------|
| Repo contract | `docs/RESOURCE_MAPS.md` | Stable rules, aliases, stop conditions, and current routing snapshot for agentX developers. |
| Runtime context | `/infra home`, `/infra vps`, `/infra resource-bundle`, `/infra all`; `agentx infra ... --json` for headless runners | Read-only extraction from `~/infrastructure/*` for the current machine before answering or acting. |
| Local constitution | `AGENTX.md` resource-map gate | Always-on instruction that forces runtime state pre-flight for SSH/deploy/cross-machine work. |

Acceptance criteria for this map package:

- Home AI facilities and VPS hosts are separately searchable.
- Headless JSON exposes `resolved_map`, `selected_maps`, `sources`,
  `source_status`, and context caps so runners do not parse markdown for routing.
- Domain-to-repo and machine-to-service ambiguity is called out before action.
- The maps never grant permission to SSH, deploy, delete, restart, write memory,
  or touch production by themselves.
- Company, PopDaily, personal VPS, and home AI boundaries are explicit.

## Operating Route

Use this route before any SSH, deploy, service restart, cron / launchd change,
cross-machine operation, or answer that maps a domain to a repo:

1. Identify the resource class from the user's words.
2. Read the targeted map:
   - home AI / local compute pool -> `/infra home`
   - public VPS / domain host -> `/infra vps`
   - repo ownership / project boundary -> `/infra project`
   - Maki's mixed resource/home/VPS request -> `/infra resource-bundle`
   - unknown or mixed resource -> `/infra all`
3. Fill the runtime state block from the map and current repo docs.
4. If any runtime state field is unknown, stop and ask Maki or perform more
   read-only inspection.
5. Only after confirmation, run the smallest allowed diagnostic or implementation
   step. The map itself never grants deploy, SSH, delete, or production permission.

Runtime state block:

```text
Machine:
Service:
Run Mode:
Constraint:
Risk:
Source:
```

Post-check plan before remote actions:

```text
1. Confirm the target service/process/container name.
2. Check health or status through the least invasive read-only command.
3. Confirm logs or expected endpoint response.
4. Confirm git/worktree or deployed revision when relevant.
5. Record handoff if the operation changes future routing knowledge.
```

## Home AI Facilities

The home AI center is a heterogeneous compute pool, not one host. Current routing
intent from the resource map:

### Facility Inventory

| Node | Access / address | Role | First-choice workloads | Do not use for |
|------|------------------|------|------------------------|----------------|
| Mac mini M4 | `ssh mini-ts`; `192.168.11.122`; `100.122.171.74` | Control plane, always-on services, memhall backup | OpenClaw, Nginx, BFF, Redis, Memory Gateway, DL-Pilot, MOMO Home AI, ERIKA personal | Long GPU inference, memhall main path |
| Mac mini M4-2 | `ssh mini2-ts`; `100.89.41.50` | memhall main, backup control plane, light jobs, embed server main | Memory Hall `:9100`, Hermes Gateway, Telegram channel, mk-brain embed_server `:8790` | Silent second primary gateway, heavy batch inference |
| DGX Spark | `ssh dgx-ts`; `192.168.11.123`; `100.110.14.65` | Main text inference and scoring node | Ollama `:11434`, Open WebUI, vLLM, LLM chat, RAG answer, rerank, batch scoring, embedding fallback | Web-facing app primary, database state source |
| RTX 3090 PC | `ssh rtx3090`; `192.168.11.168`; `100.120.136.40` | Image generation and x86 CUDA fallback | ComfyUI, Stable Diffusion / Flux, LoRA, CUDA-only PoC, image batch work | Control plane, core database, reliable state service |
| NAS DS2415+ | `ssh nas-ts`; `192.168.11.112`; `100.82.57.32` | Shared storage and backup | Models, LoRA, ControlNet, datasets, generated outputs, archive | Inference, API service, app deployment |
| S20 Ultra | `100.68.254.82` | Mobile capture and edge inbox | Capture inbox, mobile upload, temporary webhook, sensor input | Heavy inference, reliable always-on core service |
| PDSNET-Z13 | `ssh pdsnet-z13-ts`; `100.90.226.15` | Windows 11 / external 5G / mobile GPU fallback | Windows-only PoC, CUDA compatibility checks, external 5G scenario tests | Production, database, core state, always-on service |

### Home AI Quick Decisions

Use this list to answer "where should this run?" before selecting a host:

| If the request says... | Read first | Likely target | Confirm before action |
|------------------------|------------|---------------|-----------------------|
| ERIKA personal, OpenClaw, LINE Bot, BFF, Redis, Memory Gateway | `/infra home` | Mac mini M4 | process manager, port, repo name |
| Memory Hall, AMH adapter, `:9100`, mk-brain embed `:8790` main | `/infra home` | Mac mini M4-2 | main vs backup path, AMH store mode |
| Ollama, Open WebUI, LLM inference, rerank, RAG answer | `/infra home` | DGX Spark | model name, VRAM/load, endpoint |
| ComfyUI, Flux, Stable Diffusion, LoRA, CUDA x86 fallback | `/infra home` | RTX 3090 PC | GPU availability, output storage |
| models, datasets, generated assets, backup | `/infra home` | NAS DS2415+ | source/destination path, mount state |
| mobile capture, temporary edge inbox | `/infra home` | S20 Ultra | non-SLA nature, upload path |
| Windows-only PoC, external 5G, RTX 4090 Laptop GPU test | `/infra home` | PDSNET-Z13 | temporary scope, no production state |

### Workload Routing

| Workload | First target | Backup / note |
|----------|--------------|---------------|
| LINE / Telegram / webhook ingress | Mac mini M4 | Mac mini M4-2 only when explicitly scoped |
| Control plane, OpenClaw, BFF, Redis, light routing | Mac mini M4 | Mac mini M4-2 for backup or low-risk jobs |
| Memory Hall main path | Mac mini M4-2 `100.89.41.50:9100` | Mac mini M4 `100.122.171.74:9100` is backup |
| Embedding main path | Mac mini M4-2 `100.89.41.50:8790` | DGX Spark `100.110.14.65:8790` is fallback |
| LLM chat, RAG answer, rerank, batch scoring | DGX Spark | External model or small Mac mini model only when appropriate |
| Image generation, CUDA x86 fallback | RTX 3090 PC | External image API if local GPU is unavailable |
| Shared storage, models, datasets, generated assets | NAS DS2415+ | Do not treat NAS as an app deployment node |
| Mobile capture or edge inbox | S20 Ultra | Not a reliable always-on core service |
| Windows/CUDA-only PoC, external 5G scenario | PDSNET-Z13 | Not production or core state |

Home AI stop conditions:

- Do not silently move a control-plane service from Mac mini M4 to Mac mini M4-2.
- Do not treat DGX Spark as the default web-facing app host.
- Do not treat NAS, S20 Ultra, or PDSNET-Z13 as reliable core service hosts.
- Do not write to Memory Hall through raw HTTP; use AMH / approved adapter paths.
- If a company or client task appears in the same request, confirm the intended
  boundary before using home AI resources.

## VPS Map

The VPS map is for public-facing personal, client, and non-company services. It
exists to prevent domain-to-repo confusion:

| Host / domain | Access / IP | Primary services | Common repo association | Caution |
|---------------|-------------|------------------|-------------------------|---------|
| `n1k.tw` | `ssh n1k`; `167.179.69.8` | n8n, control-plane-bff experiment, popup-ad-manager, SearXNG | `n8n-workflows`, `agent-control-plane` | Multi-service host; confirm process manager before acting |
| `2ch.tw` | `ssh 2ch`; `139.180.199.219` | Anonymous forum, all Docker | `2ch-core` | Domain and repo names differ |
| `ranran.tw` | `ssh ranran`; `139.180.201.136` | Personal service node, GEO Checker, AI education, PopDaily delivery subdomain | `geo-checker`, `abd-ids-class`, `popdaily-private` | `ranran.tw` is not only `geo-checker`; `pd.ranran.tw` is PopDaily context |
| `chiba.tw` | `ssh chiba`; `139.180.197.137` | Short URL, business card, DX entrances, shared chatbot backend | `chiba.tw`, `dx-chiba`, `dx-chatbot` | Most likely to be confused; path, subdomain, and port decide the repo |
| `blog.chibakuma.com` | `ssh blog`; `202.182.115.151` | Ghost technical blog | `blog.chibakuma.com` | Blog host, not a generic app box |
| `paul.applekuma.com` | `ssh paul`; `45.76.207.168` | Customer-facing consumption management | `paul.applekuma.com` | Existing `_legacy` flow may still matter |
| `kerker.tw` | `ssh kerker`; `202.182.112.147` | Ghost / static display services | Check `/infra vps` before acting | Repo ownership must be confirmed |
| `greenleaves.dig.tw` | cPanel | River tracing activity platform with payment | `greenleaves` | Payment-related; treat changes as higher risk |

### VPS Quick Decisions

Use this list to disambiguate domain, host, service, and repo:

| If the request says... | Read first | Likely host | Likely repo / scope | Confirm before action |
|------------------------|------------|-------------|---------------------|-----------------------|
| n8n, workflow automation, SearXNG, control-plane experiment | `/infra vps` + `/infra project` | `n1k.tw` | `n8n-workflows`, `agent-control-plane` | systemd vs Docker, service name |
| anonymous forum, 2ch | `/infra vps` | `2ch.tw` | `2ch-core` | Docker compose path |
| GEO Checker, AI education, `pd.ranran.tw` | `/infra vps` + boundary check | `ranran.tw` | `geo-checker`, `abd-ids-class`, PopDaily delivery | personal vs PopDaily context |
| short URL, business card, `dx.chiba.tw`, `ai.chiba.tw`, chatbot port `8900` | `/infra vps` + `/infra project` | `chiba.tw` | `chiba.tw`, `dx-chiba`, `dx-chatbot` | path/subdomain/port |
| Ghost technical blog | `/infra vps` | `blog.chibakuma.com` | `blog.chibakuma.com` | Ghost service path |
| customer consumption management, `_legacy` | `/infra vps` | `paul.applekuma.com` | `paul.applekuma.com` | legacy flow |
| Ghost/static display on `kerker.tw` | `/infra vps` | `kerker.tw` | unconfirmed | repo ownership |
| river tracing, payment | `/infra vps` | `greenleaves.dig.tw` | `greenleaves` | payment risk and cPanel path |

Important distinctions:

- A domain is not automatically the repo name. `chiba.tw` can mean the short URL
  service, DX frontends, or chatbot backend depending on path, port, and service.
- `ranran.tw` can host more than `geo-checker`; subdomains may be project-specific.
- `pd.ranran.tw` is PopDaily project delivery context even though it sits on a
  personal VPS.
- Company 91APP services should not be routed to personal VPS by default.

### VPS Disambiguation Questions

Before answering or acting on a VPS request, resolve these fields:

1. Is the user naming a domain, a host, a service, or a repo?
2. Which subdomain/path/port identifies the service?
3. Is the context personal, PopDaily, 91APP, or another client?
4. Which canonical repo owns the change?
5. Is the requested action read-only, reversible, or production-affecting?

## Boundary Rules

The maps are also a boundary system:

- `~/GitLab/*` is 91APP company work. Use abd-ai-hub and GCP references, not home
  AI machines or personal VPS assumptions.
- PopDaily is private client work and must stay separate from 91APP maps and
  company repos.
- Home AI and personal VPS resources may support personal projects, but they are
  not default targets for company services.
- If a request mixes 91APP, PopDaily, personal VPS, and home AI contexts, stop and
  ask Maki which context is intended.

## AgentX Implementation Surface

The source code path is:

- `src/agentx/infrastructure_context.py`: map definitions, aliases, section
  extraction, and context limits.
- `src/agentx/tools/builtin.py`: `infrastructure_context` tool registration.
- `src/agentx/cli_runtime_handlers.py`: `/infra` slash command dispatch.
- `src/agentx/cli.py`: `agentx infra ... --json` top-level runner command.
- `src/agentx/intent.py`: runtime state pre-flight hints for infra-like requests.
- `tests/test_infrastructure_context.py`: map path, alias, section extraction, and
  context cap coverage.
- `tests/test_infra_cli.py`: top-level CLI JSON, JSONL, and plain output coverage.

Current aliases intentionally include:

```text
/infra home
/infra 家庭AI設施
/infra 家庭 AI 設施地圖
/infra vps
/infra VPS地圖
/infra 外網主機
/infra resource-bundle
/infra 資源地圖+家庭AI設施/VPS地圖
/infra 資源地圖+家庭AI設施／VPS地圖
```

The tool is intentionally read-only. Reading a map does not grant permission to
SSH, deploy, delete, restart services, change production state, or write memory.

## Verification

For documentation-only changes to this map spec:

```bash
uv run pytest -q tests/test_infrastructure_context.py tests/test_intent.py
uv run ruff check src/agentx/infrastructure_context.py src/agentx/intent.py
```

For runtime changes to `/infra` behavior, also run:

```bash
uv run pytest -q tests/test_cli_runtime_handlers.py tests/test_tools.py
uv run pytest -q
uv run ruff check .
```
