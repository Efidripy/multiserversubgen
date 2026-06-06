# PROJECT: multiserversubgen

Single hub — все слои workspace для этого проекта.

## Code
- Repo: `E:\GitHub\repos\multiserversubgen\`
- CLAUDE.md: `./CLAUDE.md`
- AGENTS.md: `./AGENTS.md` ← AgentMemory rules + checkpoint format
- KNOWLEDGE_INDEX.md: `./KNOWLEDGE_INDEX.md`
- Private docs: `./.local_project_docs/`

## Workspace layers
| Слой | Путь |
|---|---|
| Knowledge card | `E:\GitHub\workspace\knowledge\projects\multiserversubgen.md` |
| Manifest | `E:\GitHub\workspace\control\manifests\projects\multiserversubgen\multiserversubgen.md` |
| Registry row | `E:\GitHub\workspace\registry\projects-registry.md` → `multiserversubgen` |
| Runners | `OPS_RUNNER`, `MCP_RUNNER` |
| Logs | `E:\GitHub\workspace\runtime\logs\projects\multiserversubgen\` |
| State | `E:\GitHub\workspace\runtime\state\projects\multiserversubgen\` |

## AgentMemory
- Search: `memory_smart_search("multiserversubgen checkpoint")`
- Search: `memory_smart_search("multiserversubgen donor figma sprint")`
- Project ID: `multiserversubgen`
- File-based: `C:\Users\xman\.claude\projects\E--GitHub\memory\multiserversubgen-figma-baseline.md`

## Active branches (2026-06-04)
- `feature/admin-redesign-sprint2`
- `codex/dashboard-to-figma-design-migration` ← Figma Variant4, baseline commit 48e297f

## Cross-repo links
- SSH deploy: `dev.kleva.ru:1452` — shared с `lnv-push`
- InstallKit: потенциальный connector `mssg-deploy`

## Stack
FastAPI (Python) + React/TS/Vite + Bootstrap 5 + i18next + SQLite
