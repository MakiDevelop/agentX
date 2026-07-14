# Resource Maps

agentX reads Maki's infrastructure maps as read-only context through `/infra` and the
`infrastructure_context` tool. The maps answer three different questions:

| Map | Source | Question answered | agentX entry |
|-----|--------|-------------------|--------------|
| Quick ref | `~/infrastructure/infrastructure-quick-ref.md` | Which SSH alias, IP, port, or high-frequency runtime fact should be checked first? | `/infra quick` |
| Project map | `~/infrastructure/project-map.md` | Which repo owns a domain, service, or deployment target? | `/infra project` |
| Resource map | `~/infrastructure/resource-map.md` | Which machine, service, and access plane should be used? | `/infra resource` |
| Home AI facilities | `~/infrastructure/resource-map.md` section `家庭 AI 中心` | Which home AI node should handle this workload? | `/infra home` or `/infra 家庭AI設施` |
| VPS map | `~/infrastructure/resource-map.md` section `外網主機 / VPS` or `VPS 對照` | Which public VPS/domain hosts this service? | `/infra vps`, `/infra VPS地圖`, or `/infra 外網主機` |

`/infra all` loads quick ref, project map, and resource map together. It is useful
for orientation, but targeted maps are preferred before remote operations because
they reduce irrelevant context.

## Home AI Facilities

The home AI center is an heterogeneous compute pool, not one host. Current routing
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

Before any SSH, deploy, service restart, cron, launchd, or cross-machine action,
agentX must fill a runtime state block from `/infra home` or `/infra vps` instead
of guessing:

```text
Machine:
Service:
Run Mode:
Constraint:
Risk:
Source:
```

If these fields cannot be filled from current repo docs plus `/infra`, the correct
next step is to ask Maki or do more read-only inspection.

## VPS Map

The VPS map is for public-facing personal, client, and non-company services. It
exists to prevent domain-to-repo confusion:

| Host / domain | Primary meaning | Common repo association |
|---------------|-----------------|-------------------------|
| `n1k.tw` | General web-facing VPS and automation host | `n8n-workflows`, `agent-control-plane` |
| `2ch.tw` | Anonymous forum service | `2ch-core` |
| `ranran.tw` | Personal service node; may host project-specific subdomains | `geo-checker`, project-specific repos |
| `chiba.tw` | Multi-service host: short URL, business card, DX entrances, chatbot backend | `chiba.tw`, `dx-chiba`, `dx-chatbot` |

Important distinction: a domain is not automatically the repo name. For example,
`chiba.tw` may refer to the short URL service, the DX frontends, or the chatbot
backend depending on path, port, and service name. Use `/infra vps` plus the current
repo docs before acting.

## Company / Client / Home Boundaries

The maps are also a boundary system:

- `~/GitLab/*` is 91APP company work. Use abd-ai-hub and GCP references, not home
  AI machines or personal VPS assumptions.
- PopDaily is private client work and must stay separate from 91APP maps and
  company repos.
- Home AI and personal VPS resources may support personal projects, but they are
  not default targets for company services.

When a request mixes these contexts, stop and ask Maki which context is intended.

## Implementation Surface

The source code path is:

- `src/agentx/infrastructure_context.py`: map definitions, aliases, section
  extraction, and context limits.
- `src/agentx/tools/builtin.py`: `infrastructure_context` tool registration.
- `src/agentx/cli_runtime_handlers.py`: `/infra` slash command dispatch.
- `tests/test_infrastructure_context.py`: map path, alias, section extraction, and
  context cap coverage.

The tool is intentionally read-only. Reading a map does not grant permission to SSH,
deploy, delete, restart services, or change production state.
