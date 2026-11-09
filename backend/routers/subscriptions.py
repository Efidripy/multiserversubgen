import base64
import datetime
import hashlib
import hmac
import json
import re
import sqlite3
import time
import secrets
import copy
import random
from threading import Lock
from urllib.parse import quote, urlencode
from services.db_bootstrap import connect
from services.subscription_tokens import (
    delete_tokens,
    ensure_tokens,
    get_token,
    regenerate_token,
    resolve_token,
)
from services.subscription_client_settings import (
    build_headers as build_client_headers,
    device_app_name,
    load_settings as load_client_settings,
    match_client,
    save_settings as save_client_settings,
    schema as client_settings_schema,
    section_schema as client_settings_section_schema,
)
from services.subscription_formats import convert_links, FORMATS
from services.subscription_content import apply_content, render_tokens
from services.subscription_response_rules import parse_rules, evaluate
from services.subscription_remote_rules import RemoteRulesStore, resolve_client_settings, merge_remote_clash, apply_mihomo_template
from services.subscription_devices import DeviceDecision, check_device, list_devices, delete_device
from services.subscription_page import wants_page, render_page, page_headers
from services.subscription_happ_crypto import encrypt_happ_link
from services.subscription_links import get_link_inbound_remark
from services.telegram_qr import build_subscription_qr_png
from services.telegram_access import TelegramSubscriptionAccessGate
from services.telegram_registry import TelegramRegistry
from shared.sql import update_by_id_query
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response


# Apps refetch hourly; a fetch is served from local snapshots, never from nodes.
DEFAULT_PROFILE_UPDATE_INTERVAL_HOURS = 1


def build_subscriptions_router(
    *,
    check_auth,
    db_path,
    node_service,
    check_subscription_rate_limit,
    get_emails,
    get_links_filtered,
    subscription_signing_secret,
    invalidate_subscription_cache,
    logger,
    register_subscription_response_cache_invalidator=None,
    get_subscription_userinfo=None,
    get_system_emails=None,
    subscription_profile_update_interval_hours=None,
    subscription_profile_title=None,
):
    router = APIRouter()
    subscription_response_cache: Dict[str, tuple[float, str, Optional[Dict[str, int]], str]] = {}
    subscription_response_cache_lock = Lock()
    subscription_response_cache_ttl = 300
    subscription_response_cache_max_size = 1024
    telegram_access_gate = TelegramSubscriptionAccessGate(db_path)
    telegram_registry = TelegramRegistry(db_path)
    try:
        profile_interval = DEFAULT_PROFILE_UPDATE_INTERVAL_HOURS if subscription_profile_update_interval_hours is None else int(
            subscription_profile_update_interval_hours
        )
        if profile_interval < 0:
            profile_interval = DEFAULT_PROFILE_UPDATE_INTERVAL_HOURS
    except (TypeError, ValueError):
        profile_interval = DEFAULT_PROFILE_UPDATE_INTERVAL_HOURS
    profile_title = (subscription_profile_title or "").replace("\r", "").replace("\n", "")
    if profile_title and not profile_title.isascii():
        profile_title = "base64:" + base64.b64encode(profile_title.encode("utf-8")).decode("ascii")
    profile_title_header = profile_title or None
    remote_store = RemoteRulesStore(db_path)

    def _no_cache_headers():
        return {
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        }

    def _subscription_headers(cache_status: str):
        headers = _no_cache_headers()
        headers["X-Subscription-Cache"] = cache_status
        return headers

    def _with_subscription_headers(headers, nodes=None, emails=None, userinfo=None):
        if userinfo is None and get_subscription_userinfo and nodes is not None and emails is not None:
            userinfo = get_subscription_userinfo(nodes, emails)
        if userinfo:
            headers["Subscription-Userinfo"] = "; ".join(
                f"{key}={userinfo[key]}" for key in ("upload", "download", "total", "expire")
            )

        headers["Vary"] = "User-Agent"
        return headers

    def _subscription_url(request: Request, *, include_filters: bool = True) -> str:
        forwarded_proto = request.headers.get("x-forwarded-proto")
        scheme = forwarded_proto if forwarded_proto in {"http", "https"} else request.url.scheme
        sub_url = str(request.base_url.replace(scheme=scheme)).rstrip("/") + request.url.path
        if include_filters:
            filters = [(key, value) for key, value in request.query_params.multi_items() if key in {"protocol", "nodes"}]
            if filters:
                sub_url += "?" + urlencode(filters)
        return sub_url

    def _client_output_details(links, request: Request, *, userinfo=None, nodes=None, emails=None, cache_headers=None, settings=None, selected=None, rule=None, ctx=None):
        settings = settings or load_client_settings(db_path)
        selected = selected if selected is not None else match_client(settings, request.headers.get("user-agent"))
        requested_format = request.query_params.get("format")
        output_format = "base64" if request.query_params.get("provider") == "1" else (requested_format if requested_format in FORMATS else "")
        if not output_format and rule and rule.get("response") in FORMATS:
            output_format = rule["response"]
        if not output_format:
            output_format = selected.get("format") if selected else "base64"
        selected_settings = resolve_client_settings(remote_store, selected) if selected else {}
        selected_settings = copy.deepcopy(selected_settings)
        if ctx:
            profile = copy.deepcopy(settings.get("profile", {}))
            for key in ("title", "support_url", "announce"):
                profile[key] = render_tokens(profile.get(key, ""), ctx)
            settings = copy.deepcopy(settings)
            settings["profile"] = profile
        extra_text = None
        if selected and selected.get("kind") == "incy" and output_format == "base64":
            if selected_settings.get("routing_enable") and selected_settings.get("routing"):
                extra_text = str(selected_settings["routing"])
        customize = None
        remote_document = selected_settings.get("remote_document")
        if remote_document:
            def customize(body):
                try:
                    merge_remote_clash(body, remote_document, allow_client_config=bool(settings.get("remote_rules", {}).get("use_remote_dns")))
                except ValueError:
                    return
        mihomo_template = selected_settings.get("mihomo_template")
        if mihomo_template and output_format in {"mihomo", "clash"}:
            # shortcut: template providers use the canonical subscription URL; improve when provider filters are supported.
            sub_url = _subscription_url(request, include_filters=False)

            def customize(body):
                try:
                    apply_mihomo_template(body, mihomo_template, sub_url)
                except ValueError:
                    return
        body = convert_links(
            links,
            output_format,
            enable_routing=bool(selected_settings.get("enable_routing")),
            rules=selected_settings.get("rules", []),
            extra_text=extra_text,
            customize=customize,
            encode=bool(settings.get("content", {}).get("encode", True)),
            xray_json=settings.get("xray_json", {}),
        )
        if output_format != "base64" and not body:
            output_format = "base64"
            body = convert_links(
                links,
                output_format,
                extra_text=extra_text,
                encode=bool(settings.get("content", {}).get("encode", True)),
                xray_json=settings.get("xray_json", {}),
            )
        headers = cache_headers or _no_cache_headers()
        headers = _with_subscription_headers(headers, nodes, emails, userinfo)
        _, client_headers = _client_headers(settings, request.headers.get("user-agent"))
        for name, value in client_headers.items():
            for existing in list(headers):
                if existing.lower() == name.lower():
                    del headers[existing]
            headers[name] = value
        return body, output_format, headers

    def _filter_happ_routing(headers, settings, request):
        client = match_client(settings, request.headers.get("user-agent"))
        if not client or client.get("kind") != "happ":
            return
        device_os = request.headers.get("x-device-os")
        platform_hint = device_os if device_os is not None else request.headers.get("user-agent", "")
        platform = None
        for pattern, name in ((r"\b(?:ios|ipados|iphone|ipad)\b", "ios"), (r"\bandroid\b", "android"), (r"\bwindows\b", "windows")):
            if re.search(pattern, platform_hint, re.IGNORECASE):
                platform = name
                break
        if platform and not client.get("settings", {}).get(f"routing_{platform}", True):
            for name in list(headers):
                if name.lower() in {"routing", "routing-enable"}:
                    del headers[name]

    def _client_headers(settings, user_agent):
        settings = copy.deepcopy(settings)
        client = match_client(settings, user_agent)
        if client:
            client["settings"] = resolve_client_settings(remote_store, client)
        return build_client_headers(settings, user_agent, fallback_title=profile_title_header or "", fallback_interval=profile_interval)

    def _response_from_details(details):
        body, output_format, headers = details
        content_type = {
            "base64": "text/plain",
            "mihomo": "text/yaml",
            "clash": "text/yaml",
            "singbox": "application/json",
            "xray_json": "application/json",
        }[output_format]
        return Response(content=body, media_type=content_type, headers=headers)

    def _client_output(links, request: Request, *, userinfo=None, nodes=None, emails=None, cache_headers=None):
        return _response_from_details(
            _client_output_details(
                links,
                request,
                userinfo=userinfo,
                nodes=nodes,
                emails=emails,
                cache_headers=cache_headers,
            )
        )

    def _userinfo_ctx(identifier, emails, userinfo, request):
        info = userinfo or {}
        url_identifier = request.path_params.get("email") or request.path_params.get("token") or request.path_params.get("identifier") or identifier
        return {
            "email": identifier,
            "sub_id": hashlib.sha256(str(url_identifier).encode()).hexdigest()[:12],
            "upload": info.get("upload", 0) if info else 0,
            "download": info.get("download", 0) if info else 0,
            "total": info.get("total", 0) if info else 0,
            "expire": info.get("expire", 0) if info else 0,
            "now": time.time(),
            "lang": request.query_params.get("lang") or request.headers.get("accept-language", ""),
        }

    def _apply_rule_headers(headers, rule):
        for item in (rule or {}).get("headers", []):
            key = str(item.get("key", "")).replace("\r", "").replace("\n", "").strip()
            if not key or not key.isascii() or not re.fullmatch(r"[!#$%&'*+\-.0-9A-Za-z^_`|~]+", key):
                continue
            value = str(item.get("value", "")).replace("\r", "").replace("\n", "").strip()
            if not value.isascii():
                value = "base64:" + base64.b64encode(value.encode()).decode()
            if not value:
                continue
            for old in list(headers):
                if old.lower() == key.lower():
                    del headers[old]
            headers[key] = value

    def _filter_nodes_for_rule(nodes, rule):
        excluded = {str(value).casefold() for value in (rule or {}).get("exclude_nodes", [])}
        if not excluded:
            return list(nodes)
        return [node for node in nodes if str(node.get("name", "")).casefold() not in excluded]

    def _prepare_delivery(links, request, *, identifier, emails, nodes, userinfo=None, grouped=False, rule=None, state=None, as_details=False):
        if state is None:
            settings = load_client_settings(db_path)
            rules = parse_rules(settings.get("response_rules", {}).get("rules", ""))
            rule = rule if rule is not None else evaluate(rules, request.headers)
            if rule and rule.get("response") in {"block", "not_found", "unavailable"}:
                code = {"block": 403, "not_found": 404, "unavailable": 451}[rule["response"]]
                headers = _no_cache_headers()
                _apply_rule_headers(headers, rule)
                return Response(status_code=code, headers=headers)
            info = userinfo
            if info is None and get_subscription_userinfo and nodes is not None and emails is not None:
                info = get_subscription_userinfo(nodes, emails)
            ctx = _userinfo_ctx(identifier, emails, info, request)
            if rule and rule.get("skip_device_limit"):
                decision = DeviceDecision(True, {})
            else:
                subject = f"group:{identifier}" if grouped else f"email:{identifier}"
                decision = check_device(db_path, subject, request.headers, settings.get("devices", {}), now=ctx["now"])
            state = (settings, rule, ctx, decision, info)
        else:
            settings, rule, ctx, decision, info = state
        if rule and rule.get("response") in {"block", "not_found", "unavailable"}:
            code = {"block": 403, "not_found": 404, "unavailable": 451}[rule["response"]]
            headers = _no_cache_headers()
            _apply_rule_headers(headers, rule)
            return Response(status_code=code, headers=headers)
        if not decision.allowed:
            headers = _no_cache_headers()
            headers.update(decision.headers)
            _apply_rule_headers(headers, rule)
            return Response(status_code=404, headers=headers)
        if links is None:
            return state
        links = list(links or [])
        content_section = copy.deepcopy(settings.get("content", {}))
        if rule and rule.get("remark_template"):
            content_section["remark_template"] = rule["remark_template"]
        links = apply_content(links, content_section, ctx, now=ctx["now"], shuffle=random.shuffle, inbound_remark=get_link_inbound_remark)
        page = wants_page(request.headers, request.query_params, settings.get("page", {}), client_matched=bool(match_client(settings, request.headers.get("user-agent"))))
        if rule and rule.get("response") == "page" and settings.get("page", {}).get("enabled"):
            page = True
        if page:
            page_section = settings.get("page", {})
            if page_section.get("profile_mode") == "custom" and page_section.get("profile_url"):
                return RedirectResponse(page_section["profile_url"], status_code=302, headers=page_headers(secrets.token_urlsafe(16)))
            # QR, Happ and the page buttons must return the same filtered subscription.
            sub_url = _subscription_url(request)
            qr = ""
            try:
                qr = "data:image/png;base64," + base64.b64encode(build_subscription_qr_png(sub_url)).decode()
            except Exception:
                pass
            happ = ""
            if settings.get("encryption", {}).get("happ_links"):
                try:
                    happ = encrypt_happ_link(sub_url)
                except ValueError:
                    happ = ""
            nonce = secrets.token_urlsafe(16)
            page_profile = copy.deepcopy(settings.get("profile", {}))
            for key in ("title", "support_url", "announce"):
                page_profile[key] = render_tokens(page_profile.get(key, ""), ctx)
            html = render_page(ctx, page_section, profile=page_profile, sub_url=sub_url, qr_data_url=qr, happ_link=happ, nonce=nonce, query=request.query_params.multi_items())
            headers = page_headers(nonce)
            headers.update(decision.headers)
            _apply_rule_headers(headers, rule)
            return Response(content=html, media_type="text/html", headers=headers)
        details = _client_output_details(links, request, userinfo=info, nodes=nodes, emails=emails, settings=settings, selected=match_client(settings, request.headers.get("user-agent")), rule=rule, ctx=ctx)
        headers = details[2]
        headers.update(decision.headers)
        _apply_rule_headers(headers, rule)
        _filter_happ_routing(headers, settings, request)
        if grouped:
            headers["X-Subscription-Cache"] = headers.get("X-Subscription-Cache", "miss")
        if as_details:
            return details
        return _response_from_details((details[0], details[1], headers))

    def _subscription_cache_key(request: Request, identifier: str) -> str:
        query_items = sorted((key, value) for key, value in request.query_params.multi_items())
        settings = load_client_settings(db_path)
        selected = match_client(settings, request.headers.get("user-agent"))
        requested_format = request.query_params.get("format")
        final_format = "base64" if request.query_params.get("provider") == "1" else (requested_format if requested_format in FORMATS else (selected.get("format") if selected else "base64"))
        raw_key = json.dumps(
            {"identifier": identifier, "query": query_items, "client_id": selected.get("id") if selected else None, "format": final_format},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    def _get_subscription_response_cache(cache_key: str) -> Optional[str]:
        now = time.time()
        with subscription_response_cache_lock:
            cached = subscription_response_cache.get(cache_key)
            if not cached:
                return None
            ts, content, userinfo, final_format = cached
            if now - ts > subscription_response_cache_ttl:
                subscription_response_cache.pop(cache_key, None)
                return None
            return content, userinfo, final_format

    def _set_subscription_response_cache(cache_key: str, content: str, userinfo=None, final_format: str = "base64") -> None:
        with subscription_response_cache_lock:
            if len(subscription_response_cache) >= subscription_response_cache_max_size and cache_key not in subscription_response_cache:
                oldest_key = min(subscription_response_cache, key=lambda item: subscription_response_cache[item][0])
                subscription_response_cache.pop(oldest_key, None)
            subscription_response_cache[cache_key] = (time.time(), content, userinfo, final_format)

    def _clear_subscription_response_cache() -> None:
        with subscription_response_cache_lock:
            subscription_response_cache.clear()

    if register_subscription_response_cache_invalidator is not None:
        register_subscription_response_cache_invalidator(_clear_subscription_response_cache)

    def _verify_subscription_token(token: str, expected_kind: str) -> Optional[str]:
        decoded = _decode_subscription_payload(token, expected_kind)
        if not decoded:
            return None
        encoded, signature, identifier = decoded
        payload = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        expected = hmac.new(subscription_signing_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        return identifier

    def _decode_subscription_payload(token: str, expected_kind: str):
        """Decode the historical signed format without trusting its signature.

        The pre-opaque-token implementation generated HMAC URLs from an
        ephemeral secret. Some of those URLs can outlive a process restart,
        so their original secret is unavailable. We only use this decoder for
        migration: callers must still resolve the identifier against the live
        node/group inventory before redirecting to the current opaque token.
        """
        if not token or "." not in token:
            return None
        encoded, signature = token.rsplit(".", 1)
        if not re.fullmatch(r"[0-9a-f]{64}", signature):
            return None
        try:
            padded = encoded + "=" * (-len(encoded) % 4)
            payload = base64.urlsafe_b64decode(padded.encode("ascii"))
            kind, identifier, expires = payload.decode("utf-8").split("|", 2)
            if kind != expected_kind or int(expires) < int(time.time()) or not identifier:
                return None
            return encoded, signature, identifier
        except (ValueError, TypeError, UnicodeError):
            return None

    def _resolve_legacy_signed_email(token: str) -> Optional[str]:
        decoded = _decode_subscription_payload(token, "email")
        if not decoded:
            return None
        return _resolve_legacy_email(decoded[2])

    def _resolve_legacy_signed_group(token: str) -> Optional[str]:
        decoded = _decode_subscription_payload(token, "group")
        if not decoded:
            return None
        return _resolve_legacy_group(decoded[2])

    def _redirect_to_current_token(request: Request, token: str) -> RedirectResponse:
        query = f"?{request.url.query}" if request.url.query else ""
        return RedirectResponse(
            url=f"./{quote(token, safe='')}{query}",
            status_code=302,
            headers=_no_cache_headers(),
        )

    def _is_system_email(email: str) -> bool:
        """SYSTEM clients never get subscription links; their old links are disabled."""
        if not get_system_emails:
            return False
        try:
            return email.casefold() in {item.casefold() for item in get_system_emails(node_service.list_nodes())}
        except Exception:
            return False

    def _resolve_legacy_email(identifier: str) -> Optional[str]:
        try:
            emails = get_emails(node_service.list_nodes())
        except Exception:
            return None
        return next(
            (email for email in emails if email.lower() == identifier.lower()),
            None,
        )

    def _resolve_legacy_group(identifier: str) -> Optional[str]:
        with connect(db_path) as conn:
            row = conn.execute(
                "SELECT identifier FROM subscription_groups "
                "WHERE identifier = ? COLLATE NOCASE",
                (identifier,),
            ).fetchone()
        return str(row[0]) if row else None

    def _unknown_identifier_response(request: Request) -> PlainTextResponse:
        # Only failed lookups spend this per-IP budget, so valid clients behind NAT are unaffected.
        allowed, retry_after = check_subscription_rate_limit(request, "sub-miss")
        if not allowed:
            return PlainTextResponse(
                content=f"Rate limit exceeded. Retry after {retry_after}s",
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )
        return PlainTextResponse(content="Not found", status_code=404, headers=_no_cache_headers())

    def _ensure_stats_table(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stats (
                email TEXT PRIMARY KEY,
                count INTEGER DEFAULT 0,
                last_download TEXT DEFAULT ''
            )
            """
        )
        conn.commit()

    # These handlers intentionally remain synchronous: FastAPI runs sync route
    # functions in its worker thread pool, keeping SQLite and panel I/O out of
    # the event loop as one coherent transaction boundary.
    @router.get("/api/v1/emails")
    def list_emails(request: Request):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        with connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            _ensure_stats_table(conn)
            nodes = node_service.list_nodes()
            emails = get_emails(nodes)
            system_emails = get_system_emails(nodes) if get_system_emails else []
            system_casefolded = {email.casefold() for email in system_emails}

            stats = {}
            for row in conn.execute("SELECT * FROM stats").fetchall():
                stats[row["email"]] = {"count": row["count"], "last": row["last_download"]}

        # SYSTEM clients get no subscription links: drop any previously issued token.
        delete_tokens(db_path, "email", system_emails)
        return JSONResponse(
            content={
                "emails": emails,
                "system_emails": system_emails,
                "stats": stats,
                "subscription_tokens": ensure_tokens(
                    db_path,
                    "email",
                    [email for email in emails if email.casefold() not in system_casefolded],
                ),
            },
            headers=_no_cache_headers(),
        )

    @router.get("/api/v1/sub/{email}")
    def get_sub(request: Request, email: str, protocol: Optional[str] = None, nodes: Optional[str] = None):
        resolved_email = resolve_token(db_path, "email", email)
        if not resolved_email:
            device_identifier = resolve_token(db_path, "telegram_device", email)
            if device_identifier:
                # A persistent device token is opaque. Its identifier is only a
                # private join key and is resolved through the active Telegram
                # customer gate, never treated as an email or a legacy URL.
                resolved_email = telegram_registry.resolve_subscription_device_email(device_identifier)
                if not resolved_email:
                    return PlainTextResponse(content="Not found", status_code=404, headers=_no_cache_headers())
        if not resolved_email:
            legacy_email = _verify_subscription_token(email, "email")
            if not legacy_email:
                legacy_email = _resolve_legacy_signed_email(email)
            if not legacy_email:
                legacy_email = _resolve_legacy_email(email)
            if not legacy_email:
                return _unknown_identifier_response(request)
            if _is_system_email(legacy_email):
                return PlainTextResponse(content="Not found", status_code=404, headers=_no_cache_headers())
            if not telegram_access_gate.can_serve_email(legacy_email):
                return PlainTextResponse(content="Not found", status_code=404, headers=_no_cache_headers())
            current_token = ensure_tokens(db_path, "email", [legacy_email])[legacy_email]
            return _redirect_to_current_token(request, current_token)
        if _is_system_email(resolved_email) or not telegram_access_gate.can_serve_email(resolved_email):
            return PlainTextResponse(content="Not found", status_code=404, headers=_no_cache_headers())
        allowed, retry_after = check_subscription_rate_limit(request, f"sub:{hashlib.sha256(email.encode()).hexdigest()}")
        if not allowed:
            return PlainTextResponse(
                content=f"Rate limit exceeded. Retry after {retry_after}s",
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )

        no_cache_headers = _no_cache_headers()
        with connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            _ensure_stats_table(conn)
            all_nodes = node_service.list_nodes()
            safe_node_ids = telegram_registry.safe_subscription_node_ids(resolved_email)
            if safe_node_ids is not None:
                all_nodes = [node for node in all_nodes if int(node.get("id", 0)) in safe_node_ids]
            if nodes:
                node_names = [n.strip() for n in nodes.split(",")]
                all_nodes = [n for n in all_nodes if n["name"] in node_names]

            state = _prepare_delivery(
                None,
                request,
                identifier=resolved_email,
                emails=[resolved_email],
                nodes=all_nodes,
            )
            if isinstance(state, Response):
                return state
            settings, rule, _ctx, _decision, _info = state
            all_nodes = _filter_nodes_for_rule(all_nodes, rule)

            links = get_links_filtered(all_nodes, resolved_email, protocol)
            if links:
                now = datetime.datetime.now().strftime("%d.%m %H:%M")
                with connect(db_path) as db:
                    db.execute(
                        "INSERT INTO stats (email, count, last_download) VALUES (?, 1, ?) "
                        "ON CONFLICT(email) DO UPDATE SET count=count+1, last_download=?",
                        (resolved_email, now, now),
                    )
                    db.commit()
                return _prepare_delivery(links, request, identifier=resolved_email, emails=[resolved_email], nodes=all_nodes, state=state)

        return PlainTextResponse(content="Not found", status_code=404, headers=no_cache_headers)

    @router.get("/api/v1/guest-sub/{token}")
    def get_guest_sub(request: Request, token: str, protocol: Optional[str] = None):
        """Deliver one active, expiring guest subscription without token redirects."""

        guest_link = telegram_registry.resolve_guest_subscription_link(token)
        if guest_link is None or not telegram_access_gate.can_serve_email(guest_link.email_display):
            return PlainTextResponse(content="Not found", status_code=404, headers=_no_cache_headers())
        allowed, retry_after = check_subscription_rate_limit(
            request, f"guest-sub:{hashlib.sha256(token.encode()).hexdigest()}"
        )
        if not allowed:
            return PlainTextResponse(
                content=f"Rate limit exceeded. Retry after {retry_after}s",
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )
        with connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            _ensure_stats_table(conn)
            all_nodes = node_service.list_nodes()
            safe_node_ids = telegram_registry.safe_subscription_node_ids(guest_link.email_display)
            if safe_node_ids is not None:
                all_nodes = [node for node in all_nodes if int(node.get("id", 0)) in safe_node_ids]
            state = _prepare_delivery(
                None,
                request,
                identifier=guest_link.email_display,
                emails=[guest_link.email_display],
                nodes=all_nodes,
            )
            if isinstance(state, Response):
                return state
            _settings, rule, _ctx, _decision, _info = state
            all_nodes = _filter_nodes_for_rule(all_nodes, rule)
            links = get_links_filtered(all_nodes, guest_link.email_display, protocol)
            if links:
                now = datetime.datetime.now().strftime("%d.%m %H:%M")
                with connect(db_path) as db:
                    db.execute(
                        "INSERT INTO stats (email, count, last_download) VALUES (?, 1, ?) "
                        "ON CONFLICT(email) DO UPDATE SET count=count+1, last_download=?",
                        (guest_link.email_display, now, now),
                    )
                    db.commit()
                return _prepare_delivery(links, request, identifier=guest_link.email_display, emails=[guest_link.email_display], nodes=all_nodes, state=state)
        return PlainTextResponse(content="Not found", status_code=404, headers=_no_cache_headers())

    @router.get("/api/v1/sub-grouped/{identifier}")
    def get_sub_grouped(
        request: Request,
        identifier: str,
        protocol: Optional[str] = None,
        nodes: Optional[str] = None,
    ):
        resolved_identifier = resolve_token(db_path, "group", identifier)
        if not resolved_identifier:
            legacy_identifier = _verify_subscription_token(identifier, "group")
            if not legacy_identifier:
                legacy_identifier = _resolve_legacy_signed_group(identifier)
            if not legacy_identifier:
                legacy_identifier = _resolve_legacy_group(identifier)
            if not legacy_identifier:
                return _unknown_identifier_response(request)
            current_token = ensure_tokens(db_path, "group", [legacy_identifier])[legacy_identifier]
            return _redirect_to_current_token(request, current_token)
        allowed, retry_after = check_subscription_rate_limit(request, f"sub-grouped:{hashlib.sha256(identifier.encode()).hexdigest()}")
        if not allowed:
            return PlainTextResponse(
                content=f"Rate limit exceeded. Retry after {retry_after}s",
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )

        settings_for_group = load_client_settings(db_path)
        rule_for_group = evaluate(parse_rules(settings_for_group.get("response_rules", {}).get("rules", "")), request.headers)
        pre_state = _prepare_delivery(
            None,
            request,
            identifier=resolved_identifier,
            emails=[],
            nodes=[],
            userinfo={},
            grouped=True,
            rule=rule_for_group,
        )
        if isinstance(pre_state, Response):
            return pre_state
        cache_key = _subscription_cache_key(request, resolved_identifier) + ":" + str((rule_for_group or {}).get("rule", "")) + ":" + str((rule_for_group or {}).get("response", "default"))
        page_requested = wants_page(request.headers, request.query_params, settings_for_group.get("page", {}), client_matched=bool(match_client(settings_for_group, request.headers.get("user-agent")))) or (rule_for_group and rule_for_group.get("response") == "page" and settings_for_group.get("page", {}).get("enabled"))
        content_settings = settings_for_group.get("content", {})
        status_dependent_content = any(
            content_settings.get(key)
            for key in ("expired_template", "depleted_template", "remark_template", "info_node")
        ) or bool((rule_for_group or {}).get("remark_template"))
        cached_response = None if page_requested or status_dependent_content else _get_subscription_response_cache(cache_key)
        if cached_response is not None:
            cached_content, cached_userinfo, cached_format = cached_response
            settings = settings_for_group
            ctx = _userinfo_ctx(resolved_identifier, [], cached_userinfo, request)
            decision = pre_state[3]
            if not decision.allowed:
                headers = _subscription_headers("hit")
                headers.update(decision.headers)
                _apply_rule_headers(headers, rule_for_group)
                return Response(status_code=404, headers=headers)
            headers = _with_subscription_headers(_subscription_headers("hit"), userinfo=cached_userinfo)
            profile_copy = copy.deepcopy(settings.get("profile", {}))
            for key in ("title", "support_url", "announce"):
                profile_copy[key] = render_tokens(profile_copy.get(key, ""), ctx)
            settings_for_headers = copy.deepcopy(settings)
            settings_for_headers["profile"] = profile_copy
            _, selected_headers = _client_headers(settings_for_headers, request.headers.get("user-agent"))
            for name, value in selected_headers.items():
                for existing in list(headers):
                    if existing.lower() == name.lower():
                        del headers[existing]
                headers[name] = value
            headers.update(decision.headers)
            _apply_rule_headers(headers, rule_for_group)
            _filter_happ_routing(headers, settings, request)
            return _response_from_details((cached_content, cached_format, headers))

        no_cache_headers = _subscription_headers("miss")
        with connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            _ensure_stats_table(conn)
            all_nodes = node_service.list_nodes()

            custom_group = conn.execute(
                "SELECT * FROM subscription_groups WHERE identifier = ?",
                (resolved_identifier,),
            ).fetchone()
            if custom_group:
                custom_group = dict(custom_group)
                if custom_group.get("node_filters"):
                    node_names = json.loads(custom_group["node_filters"])
                    all_nodes = [n for n in all_nodes if n["name"] in node_names]
                if custom_group.get("protocol_filter"):
                    protocol = custom_group["protocol_filter"]
                email_patterns = json.loads(custom_group.get("email_patterns", "[]"))
                all_emails = get_emails(all_nodes)
                system_casefolded = (
                    {email.casefold() for email in get_system_emails(all_nodes)}
                    if get_system_emails
                    else set()
                )
                matching_emails = [
                    email for email in all_emails
                    if email.casefold() not in system_casefolded
                    and any(email.lower() == pattern.lower() for pattern in email_patterns)
                ]
            else:
                matching_emails = []

            if not matching_emails:
                return PlainTextResponse(
                    content="No matching clients found",
                    status_code=404,
                    headers=no_cache_headers,
                )

            info = get_subscription_userinfo(all_nodes, matching_emails) if get_subscription_userinfo else None
            state = (pre_state[0], pre_state[1], _userinfo_ctx(resolved_identifier, matching_emails, info, request), pre_state[3], info)
            _settings, _rule, _ctx, _decision, _info = state
            all_nodes = _filter_nodes_for_rule(all_nodes, _rule)

            all_links = []
            for matched_email in matching_emails:
                all_links.extend(get_links_filtered(all_nodes, matched_email, protocol))

            if all_links:
                now = datetime.datetime.now().strftime("%d.%m %H:%M")
                with connect(db_path) as db:
                    for matched_email in matching_emails:
                        db.execute(
                            "INSERT INTO stats (email, count, last_download) VALUES (?, 1, ?) "
                            "ON CONFLICT(email) DO UPDATE SET count=count+1, last_download=?",
                            (matched_email, now, now),
                        )
                    db.commit()
                if page_requested:
                    return _prepare_delivery(
                        all_links,
                        request,
                        identifier=resolved_identifier,
                        emails=matching_emails,
                        nodes=all_nodes,
                        grouped=True,
                        state=state,
                    )
                details = _prepare_delivery(
                    all_links,
                    request,
                    identifier=resolved_identifier,
                    emails=matching_emails,
                    nodes=all_nodes,
                    grouped=True,
                    state=state,
                    as_details=True,
                )
                content, final_format, _headers = details
                if not status_dependent_content:
                    _set_subscription_response_cache(cache_key, content, state[4], final_format)
                return _response_from_details(details)

        return PlainTextResponse(content="Not found", status_code=404, headers=no_cache_headers)

    def _settings_payload(value):
        return {
            "settings": value,
            "schema": client_settings_schema(),
            "section_schema": client_settings_section_schema(),
            "formats": list(FORMATS),
        }

    @router.get("/api/v1/subscription-client-settings")
    def get_subscription_client_settings(request: Request):
        if not check_auth(request):
            raise HTTPException(status_code=401, detail="Unauthorized")
        return _settings_payload(load_client_settings(db_path))

    @router.put("/api/v1/subscription-client-settings")
    def put_subscription_client_settings(request: Request, body: dict):
        if not check_auth(request):
            raise HTTPException(status_code=401, detail="Unauthorized")
        try:
            value = save_client_settings(db_path, body)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        invalidate_subscription_cache()
        _clear_subscription_response_cache()
        return _settings_payload(value)

    @router.post("/api/v1/subscription-client-settings/test")
    def test_subscription_client_settings(request: Request, body: dict):
        if not check_auth(request):
            raise HTTPException(status_code=401, detail="Unauthorized")
        ua = body.get("user_agent", "") if isinstance(body, dict) else ""
        if not isinstance(ua, str) or len(ua) > 512:
            raise HTTPException(status_code=422, detail="user_agent")
        settings = load_client_settings(db_path)
        client = match_client(settings, ua)
        _, headers = _client_headers(settings, ua)
        result = {"matched": bool(client), "client_id": client.get("id") if client else None, "name": client.get("name") if client else None, "format": client.get("format") if client else "base64", "headers": headers}
        if isinstance(body, dict) and isinstance(body.get("headers"), dict):
            rule = evaluate(parse_rules(settings.get("response_rules", {}).get("rules", "")), body["headers"])
            result["rule"] = rule.get("rule") if rule else None
            result["response"] = rule.get("response") if rule else "default"
        return result

    @router.get("/api/v1/subscription-client-settings/devices")
    def get_subscription_devices(request: Request):
        if not check_auth(request):
            raise HTTPException(status_code=401, detail="Unauthorized")
        settings = load_client_settings(db_path)
        devices_cfg = settings.get("devices", {}) if isinstance(settings, dict) else {}
        enabled = bool(devices_cfg.get("enabled", False))
        try:
            raw_max = devices_cfg.get("max_devices", 0)
            max_devices = int(raw_max) if enabled else 0
        except (TypeError, ValueError):
            max_devices = 0
        if max_devices < 0:
            max_devices = 0
        # shortcut: 5000, перейти на пагинацию при росте базы устройств
        raw_devices = list_devices(db_path, limit=5000)
        devices = [
            {
                **dev,
                "app": device_app_name(settings, dev.get("user_agent", "")),
            }
            for dev in raw_devices
        ]
        return {
            "devices": devices,
            "max_devices": max_devices,
        }

    @router.delete("/api/v1/subscription-client-settings/devices/{device_id}")
    def remove_subscription_device(request: Request, device_id: int):
        if not check_auth(request):
            raise HTTPException(status_code=401, detail="Unauthorized")
        if not delete_device(db_path, device_id):
            raise HTTPException(status_code=404, detail="Device not found")
        return {"status": "success"}

    @router.get("/api/v1/subscription-groups")
    def list_subscription_groups(request: Request):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        with connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            groups = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM subscription_groups ORDER BY created_at DESC"
                ).fetchall()
            ]
            for group in groups:
                group["email_patterns"] = json.loads(group.get("email_patterns", "[]"))
                group["node_filters"] = json.loads(group.get("node_filters", "[]"))
            group_tokens = ensure_tokens(db_path, "group", [group["identifier"] for group in groups])
            for group in groups:
                group["subscription_token"] = group_tokens[group["identifier"]]

        return {"groups": groups, "count": len(groups)}

    @router.post("/api/v1/subscription-tokens/{kind}/{identifier}/regenerate")
    def regenerate_subscription_token(request: Request, kind: str, identifier: str):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        if kind not in {"email", "group"} or not identifier:
            raise HTTPException(status_code=400, detail="Unsupported subscription token kind")

        if get_token(db_path, kind, identifier) is None:
            if kind == "email":
                resolved = _resolve_legacy_email(identifier)
            else:
                resolved = _resolve_legacy_group(identifier)
            if not resolved:
                raise HTTPException(status_code=404, detail="Subscription not found")
            ensure_tokens(db_path, kind, [resolved])
            identifier = resolved

        token = regenerate_token(db_path, kind, identifier)
        if not token:
            raise HTTPException(status_code=404, detail="Subscription not found")
        invalidate_subscription_cache()
        return {"kind": kind, "identifier": identifier, "subscription_token": token}

    @router.post("/api/v1/subscription-groups")
    def create_subscription_group(request: Request, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        name = data.get("name")
        identifier = data.get("identifier")
        if not name or not identifier:
            raise HTTPException(status_code=400, detail="name and identifier required")

        try:
            with connect(db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO subscription_groups
                    (name, identifier, description, email_patterns, node_filters, protocol_filter)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        name,
                        identifier,
                        data.get("description", ""),
                        json.dumps(data.get("email_patterns", [])),
                        json.dumps(data.get("node_filters", [])),
                        data.get("protocol_filter"),
                    ),
                )
                conn.commit()
            invalidate_subscription_cache()
            return {"status": "success", "identifier": identifier}
        except Exception as exc:
            logger.error(f"Error creating subscription group: {exc}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.put("/api/v1/subscription-groups/{group_id}")
    def update_subscription_group(request: Request, group_id: int, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        updates = []
        params = []
        if "name" in data:
            updates.append("name")
            params.append(data["name"])
        if "identifier" in data:
            updates.append("identifier")
            params.append(data["identifier"])
        if "description" in data:
            updates.append("description")
            params.append(data["description"])
        if "email_patterns" in data:
            updates.append("email_patterns")
            params.append(json.dumps(data["email_patterns"]))
        if "node_filters" in data:
            updates.append("node_filters")
            params.append(json.dumps(data["node_filters"]))
        if "protocol_filter" in data:
            updates.append("protocol_filter")
            params.append(data["protocol_filter"])
        if not updates:
            raise HTTPException(status_code=400, detail="No updates provided")

        params.append(group_id)
        try:
            with connect(db_path) as conn:
                conn.execute(
                    update_by_id_query(
                        "subscription_groups",
                        updates,
                        extra_set=("updated_at = CURRENT_TIMESTAMP",),
                    ),
                    params,
                )
                conn.commit()
            invalidate_subscription_cache()
            return {"status": "success"}
        except Exception as exc:
            logger.error(f"Error updating subscription group: {exc}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.delete("/api/v1/subscription-groups/{group_id}")
    def delete_subscription_group(request: Request, group_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        try:
            with connect(db_path) as conn:
                conn.execute("DELETE FROM subscription_groups WHERE id = ?", (group_id,))
                conn.commit()
            invalidate_subscription_cache()
            return {"status": "success"}
        except Exception as exc:
            logger.error(f"Error deleting subscription group: {exc}")
            raise HTTPException(status_code=500, detail="Internal server error")

    return router
