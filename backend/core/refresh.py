from starlette.requests import Request


def effective_refresh(request: Request, requested: bool) -> bool:
    """Enable cache bypass only for operator-level authenticated requests."""
    if not requested:
        return False
    role = getattr(request.state, "auth_role", "viewer")
    return role in {"operator", "admin"}
