from __future__ import annotations

import re
from typing import Callable, Dict, Optional, Set

try:
    import pwd
except ImportError:  # pragma: no cover - production runs on Linux
    class _PwdUnavailable:
        @staticmethod
        def getpwnam(_username):
            raise KeyError(_username)

        @staticmethod
        def getpwall():
            return []

    pwd = _PwdUnavailable()

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from services.db_bootstrap import connect


USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
ROLE_ORDER = {"admin": 0, "operator": 1, "viewer": 2}
RoleSet = Set[str] | Callable[[], Set[str]] | None


class RoleBody(BaseModel):
    role: str


class NoteBody(BaseModel):
    note: str


def build_users_router(
    *,
    check_auth: Callable[[Request], Optional[str]],
    get_user_role: Callable[[str], str],
    panel_roles,
    role_admins: RoleSet,
    role_operators: RoleSet,
    role_owners: RoleSet,
    enqueue_audit_event: Callable[[Dict], None],
):
    router = APIRouter()
    def current_roles(value: RoleSet) -> Set[str]:
        resolved = value() if callable(value) else value
        return set(resolved or ())

    def current_role_sets() -> tuple[Set[str], Set[str], Set[str]]:
        return (
            current_roles(role_admins),
            current_roles(role_operators),
            current_roles(role_owners),
        )

    def env_role(username: str, admins: Set[str], operators: Set[str]) -> Optional[str]:
        if username in admins:
            return "admin"
        if username in operators:
            return "operator"
        return None

    def actor_or_unauthorized(request: Request) -> str:
        actor = check_auth(request)
        if not actor:
            raise HTTPException(status_code=401, detail="Unauthorized")
        if get_user_role(actor) != "admin":
            raise HTTPException(status_code=403, detail="Admin role required")
        return actor

    def validate_username(username: str) -> None:
        if not USERNAME_RE.fullmatch(username):
            raise HTTPException(status_code=422, detail="Invalid username")

    def env_record(username: str, admins: Set[str], operators: Set[str], owners: Set[str]) -> Dict:
        configured_role = env_role(username, admins, operators)
        return {
            "username": username,
            "role": "admin" if username in owners else get_user_role(username),
            "source": "env",
            "env_role": configured_role,
            "owner": username in owners,
        }

    @router.get("/api/v1/users")
    def list_users(request: Request):
        actor = actor_or_unauthorized(request)
        admins, operators, owners = current_role_sets()
        env_users = admins | operators | owners
        users = {
            username: env_record(username, admins, operators, owners)
            for username in env_users
            if not panel_roles.is_blocked(username)
        }
        for row in panel_roles.list_roles():
            username = row["username"]
            if username in owners:
                continue
            if panel_roles.is_blocked(username):
                continue
            configured_role = env_role(username, admins, operators)
            users[username] = {
                "username": username,
                "role": row["role"],
                "source": "db",
                "env_role": configured_role,
                "owner": False,
            }
        for user in users.values():
            user["locked"] = user["owner"] or user["username"] == actor
            user["note"] = panel_roles.get_note(user["username"])
        ordered = sorted(
            users.values(),
            key=lambda item: (
                0 if item["owner"] else ROLE_ORDER[item["role"]] + 1,
                item["username"],
            ),
        )
        candidates = []
        blocked = set()
        with connect(panel_roles.db_path) as conn:
            blocked = {row[0] for row in conn.execute("SELECT username FROM panel_user_blocks")}
        for entry in pwd.getpwall():
            if 1000 <= entry.pw_uid <= 59999 and (entry.pw_name not in users or entry.pw_name in blocked) and USERNAME_RE.fullmatch(entry.pw_name):
                candidates.append(entry.pw_name)
        return {
            "users": ordered,
            "candidates": sorted(set(candidates)),
            "me": {"username": actor, "owner": actor in owners},
        }

    @router.put("/api/v1/users/{username}/role")
    def set_user_role(username: str, body: RoleBody, request: Request):
        actor = actor_or_unauthorized(request)
        validate_username(username)
        if body.role not in ROLE_ORDER:
            raise HTTPException(status_code=422, detail="Invalid role")
        _, _, owners = current_role_sets()
        if username in owners or username == actor:
            raise HTTPException(status_code=409, detail="User role is locked")
        try:
            pwd.getpwnam(username)
        except KeyError:
            raise HTTPException(status_code=404, detail="System user not found") from None
        old_role = panel_roles.set_role(username, body.role, actor)
        enqueue_audit_event(
            {
                "event": "panel_role_changed",
                "actor": actor,
                "target": username,
                "old_role": old_role,
                "new_role": body.role,
            }
        )
        return {"username": username, "role": body.role, "source": "db"}

    @router.delete("/api/v1/users/{username}")
    def remove_user(username: str, request: Request):
        actor = actor_or_unauthorized(request)
        validate_username(username)
        _, _, owners = current_role_sets()
        if username in owners or username == actor:
            raise HTTPException(status_code=409, detail="User cannot be removed")
        try:
            pwd.getpwnam(username)
        except KeyError:
            raise HTTPException(status_code=404, detail="System user not found") from None
        old_role = panel_roles.get_role(username) or env_role(username, *current_role_sets()[:2])
        removed = panel_roles.remove_user(username, actor)
        enqueue_audit_event({"event": "panel_user_removed", "actor": actor, "target": username, "old_role": old_role})
        return {"username": username, "removed": removed, "blocked": True}

    @router.put("/api/v1/users/{username}/note")
    def update_note(username: str, body: NoteBody, request: Request):
        actor = actor_or_unauthorized(request)
        validate_username(username)
        note = body.note.strip()
        if len(note) > 200:
            raise HTTPException(status_code=422, detail="Note must be at most 200 characters")
        if not panel_roles.set_note(username, note, actor):
            raise HTTPException(status_code=409, detail="User was removed from the panel")
        return {"username": username, "note": note}

    @router.delete("/api/v1/users/{username}/role")
    def delete_user_role(username: str, request: Request):
        actor = actor_or_unauthorized(request)
        validate_username(username)
        _, _, owners = current_role_sets()
        if username in owners or username == actor:
            raise HTTPException(status_code=409, detail="User role is locked")
        old_role = panel_roles.get_role(username)
        removed = panel_roles.delete_role(username)
        if removed:
            enqueue_audit_event(
                {
                    "event": "panel_role_changed",
                    "actor": actor,
                    "target": username,
                    "old_role": old_role,
                    "new_role": None,
                    "action": "delete",
                }
            )
        return {"username": username, "removed": removed}

    return router
