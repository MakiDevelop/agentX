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

`/infra all` loads quick ref, project map, and resource map together. It is useful
for orientation, but targeted maps are preferred before remote operations because
they reduce irrelevant context.

## Operating Route

Use this route before any SSH, deploy, service restart, cron / launchd change,
cross-machine operation, or answer that maps a domain to a repo:

1. Identify the resource class from the user's words.
2. Read the targeted map:
   - home AI / local compute pool -> `/infra home`
   - public VPS / domain host -> `/infra vps`
   - repo ownership / project boundary -> `/infra project`
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

| Workload | First target | Backup / note |
|----------|--------------|---------------|
| Control plane, OpenClaw, BFF, Redis, light routing | Mac mini M4 | Mac mini M4-2 for backup or low-risk jobs |
| Memory Hall main path | Mac mini M4-2 `100.89.41.50:9100` | Mac mini M4 `100.122.171.74:9100` is backup |
| Embedding main path | Mac mini M4-2 `100.89.41.50:8790` | DGX Spark `8790` is fallback |
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

| Host / domain | Primary meaning | Common repo association |
|---------------|-----------------|-------------------------|
| `n1k.tw` | General web-facing VPS and automation host | `n8n-workflows`, `agent-control-plane` |
| `2ch.tw` | Anonymous forum service | `2ch-core` |
| `ranran.tw` | Personal service node; may host project-specific subdomains | `geo-checker`, project-specific repos |
| `chiba.tw` | Multi-service host: short URL, business card, DX entrances, chatbot backend | `chiba.tw`, `dx-chiba`, `dx-chatbot` |
| `blog.chibakuma.com` | Ghost blog | `blog.chibakuma.com` |
| `paul.applekuma.com` | Customer-facing consumption management | `paul.applekuma.com` |
| `kerker.tw` | Ghost / static display services | Check `/infra vps` before acting |

Important distinctions:

- A domain is not automatically the repo name. `chiba.tw` can mean the short URL
  service, DX frontends, or chatbot backend depending on path, port, and service.
- `ranran.tw` can host more than `geo-checker`; subdomains may be project-specific.
- `pd.ranran.tw` is PopDaily project delivery context even though it sits on a
  personal VPS.
- Company 91APP services should not be routed to personal VPS by default.

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
- `src/agentx/intent.py`: runtime state pre-flight hints for infra-like requests.
- `tests/test_infrastructure_context.py`: map path, alias, section extraction, and
  context cap coverage.

Current aliases intentionally include:

```text
/infra home
/infra 家庭AI設施
/infra 家庭 AI 設施地圖
/infra vps
/infra VPS地圖
/infra 外網主機
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
