from __future__ import annotations

import copy
import logging
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

import yaml

from services.adguard_runtime import _get_pinned
from services.db_bootstrap import connect
from services.subscription_client_settings import _validate_rule_lines, is_mihomo_config
from shared.security import validate_and_resolve_outbound_url


_MAX_BODY = 1024 * 1024
_ERROR_CODES = {"url", "fetch", "redirect", "too_large", "encoding", "body", "kind"}
_LOGGER = logging.getLogger(__name__)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _read_chunks(read, *, chunk_size: int = 65536) -> str:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = read(chunk_size)
        if not chunk:
            break
        if not isinstance(chunk, bytes):
            raise RuntimeError("fetch")
        total += len(chunk)
        if total > _MAX_BODY:
            raise RuntimeError("too_large")
        chunks.append(chunk)
    try:
        return b"".join(chunks).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError("encoding") from exc


def _read_iterable(chunks) -> str:
    data: list[bytes] = []
    total = 0
    for chunk in chunks:
        if not isinstance(chunk, bytes):
            raise RuntimeError("fetch")
        total += len(chunk)
        if total > _MAX_BODY:
            raise RuntimeError("too_large")
        data.append(chunk)
    try:
        return b"".join(data).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError("encoding") from exc


def fetch_remote(url: str, *, user_agent: str = "", opener=None) -> str:
    """Fetch a remote rules document with DNS pinning and strict size guards."""
    valid, _error, pinned_address = validate_and_resolve_outbound_url(
        url, allow_private=False, require_https=False
    )
    if not valid:
        raise ValueError("url")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("url")
    headers = {"User-Agent": user_agent} if user_agent else {}

    if opener is not None:
        request = urllib.request.Request(url, headers=headers)
        try:
            response = opener.open(request, timeout=10)
            status = getattr(response, "status", None)
            if status is None:
                status = getattr(response, "code", None)
            if status is None:
                getcode = getattr(response, "getcode", None)
                status = getcode() if getcode else None
            if status is not None and 300 <= int(status) < 400:
                raise RuntimeError("redirect")
            return _read_chunks(response.read)
        except urllib.error.HTTPError as exc:
            if 300 <= exc.code < 400:
                raise RuntimeError("redirect") from exc
            raise RuntimeError("fetch") from exc
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError("fetch") from exc
        finally:
            if "response" in locals():
                response.close()

    response = None
    try:
        response = _get_pinned(
            url,
            pinned_address=pinned_address,
            headers=headers,
            timeout=10,
            stream=True,
            allow_redirects=False,
        )
        status = int(response.status_code)
        if 300 <= status < 400:
            raise RuntimeError("redirect")
        if status >= 400:
            raise RuntimeError("fetch")
        return _read_iterable(response.iter_content(65536))
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError("fetch") from exc
    finally:
        if response is not None:
            response.close()


def _validate_body(kind: str, body: str) -> str:
    if not isinstance(body, str):
        raise ValueError("body")
    if kind == "happ":
        if not body.startswith("happ://"):
            raise ValueError("body")
    elif kind == "incy":
        if not body.strip():
            raise ValueError("body")
    elif kind == "mihomo":
        try:
            document = yaml.safe_load(body)
        except Exception as exc:
            raise ValueError("body") from exc
        if isinstance(document, dict) and any(
            key in document for key in ("rules", "rule-providers", "proxy-groups")
        ):
            return body
        return _validate_rule_lines(body)
    else:
        raise ValueError("kind")
    return body


class RemoteRulesStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        with connect(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS subscription_remote_rules ("
                "url TEXT PRIMARY KEY, body TEXT, fetched_at REAL, last_error TEXT, attempted_at REAL)"
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(subscription_remote_rules)")}
            if "attempted_at" not in columns:
                conn.execute("ALTER TABLE subscription_remote_rules ADD COLUMN attempted_at REAL")

    def get(self, url: str) -> str | None:
        with connect(self.db_path) as conn:
            row = conn.execute("SELECT body FROM subscription_remote_rules WHERE url=?", (url,)).fetchone()
        return row[0] if row and row[0] is not None else None

    def status(self, url: str) -> dict | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT fetched_at,attempted_at,last_error FROM subscription_remote_rules WHERE url=?",
                (url,),
            ).fetchone()
        if not row:
            return None
        return {"fetched_at": row[0], "attempted_at": row[1], "last_error": row[2]}

    def refresh(self, url: str, kind: str, *, user_agent: str = "", opener=None, now=None) -> bool:
        timestamp = float(time.time() if now is None else now)
        try:
            body = _validate_body(kind, fetch_remote(url, user_agent=user_agent, opener=opener))
        except Exception as exc:
            code = str(exc.args[0]) if exc.args and str(exc.args[0]) in _ERROR_CODES else "error"
            with connect(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO subscription_remote_rules(url,body,fetched_at,last_error,attempted_at) "
                    "VALUES(?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET "
                    "last_error=excluded.last_error, attempted_at=excluded.attempted_at",
                    (url, None, None, code, timestamp),
                )
            return False
        with connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO subscription_remote_rules(url,body,fetched_at,last_error,attempted_at) "
                "VALUES(?,?,?,NULL,?) ON CONFLICT(url) DO UPDATE SET body=excluded.body, "
                "fetched_at=excluded.fetched_at,last_error=NULL,attempted_at=excluded.attempted_at",
                (url, body, timestamp, timestamp),
            )
        return True


def collect_urls(settings: dict) -> dict[str, str]:
    result: dict[str, str] = {}
    for client in settings.get("clients", []) if isinstance(settings, dict) else []:
        if not isinstance(client, dict) or not client.get("enabled"):
            continue
        kind = client.get("kind")
        values = client.get("settings") or {}
        if not isinstance(values, dict):
            continue
        if kind in {"happ", "incy"}:
            url = values.get("routing_url")
            if isinstance(url, str) and url:
                result[url] = kind
        elif kind == "mihomo":
            url = values.get("rules_url")
            if isinstance(url, str) and url:
                result[url] = "mihomo"
    return result


def refresh_due(store, settings: dict, *, now: float, opener=None) -> int:
    section = settings.get("remote_rules", {}) if isinstance(settings, dict) else {}
    try:
        minutes = float(section.get("refresh_minutes", 60))
    except (TypeError, ValueError):
        minutes = 60.0
    if minutes <= 0:
        return 0
    interval = minutes * 60.0
    user_agent = str(section.get("user_agent", "") or "")
    count = 0
    for url, kind in collect_urls(settings).items():
        status = store.status(url)
        reference = status.get("attempted_at") if status else None
        if reference is None and status:
            reference = status.get("fetched_at")
        if reference is not None and float(now) - float(reference) < interval:
            continue
        if store.refresh(url, kind, user_agent=user_agent, opener=opener, now=now):
            count += 1
    return count


def resolve_client_settings(store: RemoteRulesStore, client: dict) -> dict:
    result = copy.deepcopy(client.get("settings") or {})
    kind = client.get("kind")
    if kind in {"happ", "incy"}:
        url = result.get("routing_url")
        body = store.get(url) if url else None
        if body is not None:
            result["routing"] = body
            result["routing_enable"] = True
    elif kind == "mihomo":
        url = result.get("rules_url")
        body = store.get(url) if url else None
        if body is not None:
            try:
                document = yaml.safe_load(body)
            except Exception:
                document = None
            if isinstance(document, dict) and any(
                key in document for key in ("rules", "rule-providers", "proxy-groups")
            ):
                result["remote_document"] = body
            else:
                result["rules"] = body
            result["enable_routing"] = True
        if result.get("enable_routing") and "remote_document" not in result and is_mihomo_config(result.get("rules")):
            result["mihomo_template"] = result["rules"]
    return result


def apply_mihomo_template(base: dict, text: str, sub_url: str) -> None:
    parsed = urlparse(sub_url)
    path = parsed.path.strip("/").split("/")
    sub_id = path[-1] if path else ""
    parent = "/".join(path[:-1])
    replacements = {
        "${DOMAIN}": parsed.netloc,
        "${SUB_PATH}": parent,
        "${SUB_ID}": sub_id,
    }
    rendered = text
    for source, target in replacements.items():
        rendered = rendered.replace(source, target)
    try:
        document = yaml.safe_load(rendered)
    except Exception as exc:
        raise ValueError("yaml") from exc
    if not isinstance(document, dict):
        raise ValueError("yaml")
    for key in list(document):
        if isinstance(key, str) and key.startswith("x-"):
            del document[key]
    providers = document.get("proxy-providers")
    if not isinstance(providers, dict) or not providers:
        template_proxies = document.get("proxies")
        if not isinstance(template_proxies, list):
            template_proxies = []
        generated = base.get("proxies") if isinstance(base.get("proxies"), list) else []
        document["proxies"] = copy.deepcopy(generated) + copy.deepcopy(template_proxies)
        base_groups = base.get("proxy-groups") if isinstance(base.get("proxy-groups"), list) else []
        base_proxy_group = next(
            (group for group in base_groups if isinstance(group, dict) and group.get("name") == "PROXY"),
            None,
        )
        groups = document.get("proxy-groups")
        if not isinstance(groups, list):
            groups = []
            document["proxy-groups"] = groups
        if base_proxy_group is not None and not any(
            isinstance(group, dict) and group.get("name") == "PROXY" for group in groups
        ):
            groups.insert(0, copy.deepcopy(base_proxy_group))
    base.clear()
    base.update(document)


def merge_remote_clash(base: dict, text: str, *, allow_client_config: bool) -> None:
    try:
        remote = yaml.safe_load(text)
    except Exception as exc:
        raise ValueError("yaml") from exc
    if not isinstance(remote, dict):
        raise ValueError("yaml")
    if isinstance(remote.get("rules"), list):
        base["rules"] = copy.deepcopy(remote["rules"])
    for key in ("rule-providers",):
        if key in remote and isinstance(remote[key], dict):
            existing = base.get(key) if isinstance(base.get(key), dict) else {}
            base[key] = {**existing, **copy.deepcopy(remote[key])}
    if isinstance(remote.get("proxy-groups"), list):
        groups = base.get("proxy-groups") if isinstance(base.get("proxy-groups"), list) else []
        names = {g.get("name") for g in groups if isinstance(g, dict)}
        proxy_names = {
            p.get("name") if isinstance(p, dict) else p
            for p in (base.get("proxies") or [])
            if isinstance(p, (dict, str))
        }
        incoming_names = {
            group.get("name")
            for group in remote["proxy-groups"]
            if isinstance(group, dict) and group.get("name") and group.get("name") != "PROXY"
        }
        valid = proxy_names | names | incoming_names | {"DIRECT", "REJECT"}
        for group in remote["proxy-groups"]:
            if not isinstance(group, dict) or not group.get("name") or group.get("name") == "PROXY":
                continue
            item = copy.deepcopy(group)
            if isinstance(item.get("proxies"), list):
                item["proxies"] = [name for name in item["proxies"] if name in valid]
            groups.append(item)
            names.add(item["name"])
            valid.add(item["name"])
        base["proxy-groups"] = groups
    if allow_client_config:
        for key in ("dns", "sniffer"):
            if key in remote:
                base[key] = copy.deepcopy(remote[key])
    rules = base.get("rules")
    if isinstance(rules, list):
        base["rules"] = [rule for rule in rules if not str(rule).strip().upper().startswith("MATCH,")]
        base["rules"].append("MATCH,PROXY")


class RemoteRulesRefresher:
    def __init__(self, db_path, load_settings, *, tick_seconds=60):
        self.store = RemoteRulesStore(db_path)
        self.load_settings = load_settings
        self.tick_seconds = tick_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="subscription-remote-rules", daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                refresh_due(self.store, self.load_settings(), now=time.time())
            except Exception as exc:
                _LOGGER.warning("remote rules refresh failed: %s", type(exc).__name__)
            self._stop.wait(self.tick_seconds)

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=max(1.0, float(self.tick_seconds) + 1.0))
            self._thread = None
