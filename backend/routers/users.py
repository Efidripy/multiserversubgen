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


USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
ROLE_ORDER = {"admin": 0, "operator": 1, "viewer": 2}


class RoleBody(BaseModel):
    role: str


def build_users_router(
    *,
    check_auth: Callable[[Request], Optional[str]],
    get_user_role: Callable[[str], str],
    panel_roles,
    role_admins: Set[str],
    role_operators: Set[str],
    role_owners: Set[str],
    enqueue_audit_event: Callable[[Dict], None],
):
    router = APIRouter()
    env_users = set(role_admins) | set(role_operators) | set(role_owners)

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

    def env_record(username: str) -> Dict:
        return {
            "username": username,
            "role": get_user_role(username),
            "source": "env",
            "owner": username in role_owners,
            "locked": True,
        }

    @router.get("/api/v1/users")
    def list_users(request: Request):
        actor_or_unauthorized(request)
        users = {username: env_record(username) for username in env_users}
        for row in panel_roles.list_roles():
            username = row["username"]
            if username not in users:
                users[username] = {
                    "username": username,
                    "role": row["role"],
                    "source": "db",
                    "owner": False,
                    "locked": False,
                }
        ordered = sorted(users.values(), key=lambda item: (ROLE_ORDER[item["role"]], item["username"]))
        candidates = []
        for entry in pwd.getpwall():
            if 1000 <= entry.pw_uid <= 59999 and entry.pw_name not in users:
                candidates.append(entry.pw_name)
        return {"users": ordered, "candidates": sorted(set(candidates))}

    @router.put("/api/v1/users/{username}/role")
    def set_user_role(username: str, body: RoleBody, request: Request):
        actor = actor_or_unauthorized(request)
        validate_username(username)
        if body.role not in ROLE_ORDER:
            raise HTTPException(status_code=422, detail="Invalid role")
        if username in env_users or username == actor:
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

    @router.delete("/api/v1/users/{username}/role")
    def delete_user_role(username: str, request: Request):
        actor = actor_or_unauthorized(request)
        validate_username(username)
        if username in env_users or username == actor:
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
