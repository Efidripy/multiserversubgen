# Knowledge Index: multiserversubgen

Quick navigation between local project context and workspace-level resources.

---

## 🏠 Project Context (Start Here)

**Local Project Documentation:**
- [.local_project_docs/README.md](./.local_project_docs/README.md) — project setup, test variables, operational rules
- [.local_project_docs/AGENTS_PRIVATE.md](./.local_project_docs/AGENTS_PRIVATE.md) — agent guidelines for this project
- [.local_project_docs/LOCAL_PRIVATE_CONTEXT.md](./.local_project_docs/LOCAL_PRIVATE_CONTEXT.md) — internal configuration and environment
- [.local_project_docs/CODEX_INSPECTION_RULE.md](./.local_project_docs/CODEX_INSPECTION_RULE.md) — Codex agent inspection patterns

---

## 📚 Technical Documentation

**API & Components:**
- [.local_project_docs/API_DOCUMENTATION.md](./.local_project_docs/API_DOCUMENTATION.md) — backend API endpoints
- [.local_project_docs/COMPONENTS_GUIDE.md](./.local_project_docs/COMPONENTS_GUIDE.md) — React component architecture
- [.local_project_docs/SUBSCRIPTION_GUIDE.md](./.local_project_docs/SUBSCRIPTION_GUIDE.md) — subscription system design

**Operational Guides:**
- [README.md](./README.md) — main product overview
- [API_DOCUMENTATION.md](./API_DOCUMENTATION.md) — public API docs
- [COMPONENTS_GUIDE.md](./COMPONENTS_GUIDE.md) — component reference
- [IMPROVEMENTS.md](./IMPROVEMENTS.md) — known improvements and roadmap

---

## 🔗 Workspace Resources

**Multi-Project Context:**
- [E:\GitHub\workspace\knowledge\projects\multiserversubgen.md](../workspace/knowledge/projects/multiserversubgen.md) — workspace-level project overview, validation history
- [E:\GitHub\workspace\control\manifests\projects\multiserversubgen\multiserversubgen.md](../workspace/control/manifests/projects/multiserversubgen/multiserversubgen.md) — deployment manifest and runner configuration

**Shared Operational Resources:**
- [E:\GitHub\workspace\knowledge\library\ops-incidents.md](../workspace/knowledge/library/ops-incidents.md) — operational incident log
- [E:\GitHub\workspace\knowledge\library\workflow-playbooks.md](../workspace/knowledge/library/workflow-playbooks.md) — collaborative workflow patterns
- [E:\GitHub\workspace\knowledge\library\cost-efficient-collaboration.md](../workspace/knowledge/library/cost-efficient-collaboration.md) — cost optimization guidelines

**Getting Started:**
- [E:\GitHub\START-HERE.md](../START-HERE.md) — workspace entry point
- [E:\GitHub\WORKSPACE.md](../WORKSPACE.md) — workspace structure and philosophy
- [E:\GitHub\AGENTS.md](../AGENTS.md) — global agent collaboration rules

---

## ⚙️ Development Quick Links

### Running Locally
- **Backend:** `source venv/bin/activate && python3 backend/main.py`
- **Frontend:** `cd frontend && npm run dev`
- **Tests:** `pip install -r backend/requirements-dev.txt && pytest -q backend/tests`

### Validation
- **Smoke tests:** See [.local_project_docs/LOCAL_PRIVATE_CONTEXT.md](./.local_project_docs/LOCAL_PRIVATE_CONTEXT.md) for test servers
- **Full preset regression:** Documented in workspace manifest (vm1.kleva.ru validation history)

---

## 📝 Key Policies

**Repository Boundaries:**
- `.local_project_docs/` is **local only** — never copy to workspace root
- Workspace `knowledge/` and `workspace/` folders are **local-only coordination** — never copy into this repo
- Keep repo independent while leveraging workspace shared patterns

**Synchronization:**
- Shared state syncs every 20 minutes via `E:\GitHub\workspace\control\scripts\pull-main-base-state.ps1`
- Update root workspace docs **only on boundary changes** (deploy flow, validation path, MCP integration)

**Structure Evolution:**
- Align gradually with workspace templates, not big-bang restructuring
- All internal refactors stay local; only material changes trigger root updates

---

## 🔍 For Agents

When starting work on this project:
1. Read [AGENTS.md](./AGENTS.md) first (links to this index and local docs)
2. Check [.local_project_docs/README.md](./.local_project_docs/README.md) for project-specific context
3. Reference [.local_project_docs/AGENTS_PRIVATE.md](./.local_project_docs/AGENTS_PRIVATE.md) for collaboration rules
4. Look up workspace patterns in `E:\GitHub\workspace\knowledge\library\` as needed
5. Validate against [.local_project_docs/CODEX_INSPECTION_RULE.md](./.local_project_docs/CODEX_INSPECTION_RULE.md) before committing

---

**Last Updated:** 2026-03-18  
**Knowledge Index Version:** 1.0
