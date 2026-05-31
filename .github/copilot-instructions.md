# GitHub Copilot Instructions

Follow the repository rules in `AGENTS.md` and `CLAUDE.md`.

## AgentMemory MCP

If MCP `agentmemory` is available in the active tool/session environment, use it for non-trivial work.

Use AgentMemory to:
- recall project status and prior decisions before making changes;
- save compact checkpoints after meaningful cleanup, audit, security, architecture, or implementation iterations;
- preserve handoff context for Claude, Codex, and future Copilot-assisted work.

Checkpoint format:

```text
multiserversubgen checkpoint:
done: ...
current debt/status: ...
next: ...
checks: ...
risks/notes: ...
```

Do not store:
- source dumps or long code blocks;
- secrets, credentials, private `.local_project_docs` content, or raw sensitive output;
- raw logs without synthesis;
- unverified guesses.

If AgentMemory is not exposed to Copilot in the current environment, rely on `AGENTS.md`, `CLAUDE.md`, and project docs, and ask the lead agent/user to save durable checkpoint context when needed.

## Project Reminders

- Frontend commands run from `frontend/`.
- Backend tests run from the repository root.
- All user-visible frontend strings should go through i18n.
- Do not put credentials in WebSocket URLs or query strings.
