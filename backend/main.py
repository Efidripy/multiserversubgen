import sqlite3
import requests
import json
import base64
import pam
import datetime
import os
import logging
import time
import asyncio
import uuid
from collections import defaultdict, deque
from threading import Lock, Thread
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from fastapi import FastAPI, Request, HTTPException, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from urllib.parse import urlparse
import urllib3
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
import pyotp
try:
    import redis
except Exception:
    redis = None

# Локальный импорт crypto-модуля (для шифрования паролей)
import sys
sys.path.insert(0, str(Path(__file__).parent))
from crypto import encrypt, decrypt
from xui_session import login_node panel
from inbound_manager import InboundManager
from client_manager import ClientManager
from utils import parse_field_as_dict
from server_monitor import ServerMonitor, ThreeXUIMonitor
from websocket_manager import manager as ws_manager, handle_websocket_message
from services.node_service import NodeService
from services.collector import SnapshotCollector
from routers.observability import build_observability_router
from routers.live_data import build_live_data_router

# Конфигурация
PROJECT_DIR = os.getenv("PROJECT_DIR", "/opt/sub-manager")
WEB_PATH = os.getenv("WEB_PATH", "").strip("/")
root_path = f"/{WEB_PATH}" if WEB_PATH else ""
CACHE_TTL = int(os.getenv("CACHE_TTL", "30"))
ALLOW_ORIGINS_RAW = os.getenv(
    "ALLOW_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
)
ALLOW_ORIGINS = [origin.strip() for origin in ALLOW_ORIGINS_RAW.split(",") if origin.strip()]
VERIFY_TLS = os.getenv("VERIFY_TLS", "true").strip().lower() in ("1", "true", "yes", "on")
CA_BUNDLE_PATH = os.getenv("CA_BUNDLE_PATH", "").strip()
READ_ONLY_MODE = os.getenv("READ_ONLY_MODE", "false").strip().lower() in ("1", "true", "yes", "on")
SUB_RATE_LIMIT_COUNT = int(os.getenv("SUB_RATE_LIMIT_COUNT", "30"))
SUB_RATE_LIMIT_WINDOW_SEC = int(os.getenv("SUB_RATE_LIMIT_WINDOW_SEC", "60"))
TRAFFIC_STATS_CACHE_TTL = int(os.getenv("TRAFFIC_STATS_CACHE_TTL", "10"))
ONLINE_CLIENTS_CACHE_TTL = int(os.getenv("ONLINE_CLIENTS_CACHE_TTL", "10"))
TRAFFIC_STATS_STALE_TTL = int(os.getenv("TRAFFIC_STATS_STALE_TTL", "120"))
ONLINE_CLIENTS_STALE_TTL = int(os.getenv("ONLINE_CLIENTS_STALE_TTL", "60"))
CLIENTS_CACHE_TTL = int(os.getenv("CLIENTS_CACHE_TTL", "20"))
CLIENTS_CACHE_STALE_TTL = int(os.getenv("CLIENTS_CACHE_STALE_TTL", "180"))
REDIS_URL = os.getenv("REDIS_URL", "").strip()
COLLECTOR_BASE_INTERVAL_SEC = int(os.getenv("COLLECTOR_BASE_INTERVAL_SEC", "5"))
COLLECTOR_MAX_INTERVAL_SEC = int(os.getenv("COLLECTOR_MAX_INTERVAL_SEC", "60"))
COLLECTOR_MAX_PARALLEL = int(os.getenv("COLLECTOR_MAX_PARALLEL", "8"))
NODE_HISTORY_ENABLED = os.getenv("NODE_HISTORY_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")
NODE_HISTORY_MIN_INTERVAL_SEC = int(os.getenv("NODE_HISTORY_MIN_INTERVAL_SEC", "30"))
NODE_HISTORY_RETENTION_DAYS = int(os.getenv("NODE_HISTORY_RETENTION_DAYS", "30"))
AUDIT_QUEUE_BATCH_SIZE = int(os.getenv("AUDIT_QUEUE_BATCH_SIZE", "200"))
ROLE_VIEWERS_RAW = os.getenv("ROLE_VIEWERS", "").strip()
ROLE_OPERATORS_RAW = os.getenv("ROLE_OPERATORS", "").strip()
ROLE_VIEWERS = {u.strip() for u in ROLE_VIEWERS_RAW.split(",") if u.strip()}
ROLE_OPERATORS = {u.strip() for u in ROLE_OPERATORS_RAW.split(",") if u.strip()}
ROLE_RANK = {"viewer": 1, "operator": 2, "admin": 3}
MFA_TOTP_ENABLED = os.getenv("MFA_TOTP_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
MFA_TOTP_USERS_RAW = os.getenv("MFA_TOTP_USERS", "").strip()
MFA_TOTP_WS_STRICT = os.getenv("MFA_TOTP_WS_STRICT", "false").strip().lower() in ("1", "true", "yes", "on")


def _get_requests_verify_value():
    if not VERIFY_TLS:
        return False
    if CA_BUNDLE_PATH:
        return CA_BUNDLE_PATH
    return True


REQUESTS_VERIFY = _get_requests_verify_value()
if REQUESTS_VERIFY is False:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _parse_mfa_users(raw: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    if not raw:
        return result
    for item in raw.split(","):
        item = item.strip()
        if not item or ":" not in item:
            continue
        username, secret = item.split(":", 1)
        username = username.strip()
        secret = secret.strip().replace(" ", "")
        if username and secret:
            result[username] = secret
    return result


MFA_TOTP_USERS = _parse_mfa_users(MFA_TOTP_USERS_RAW)

app = FastAPI(title="Multi-Server Sub Manager", version="3.0", root_path=root_path)

# Gzip compression for responses larger than 1 KB
app.add_middleware(GZipMiddleware, minimum_size=1000)

# CORS для локального development
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
DB_PATH = os.path.join(PROJECT_DIR, "admin.db")

p = pam.pam()
emails_cache = {"ts": 0.0, "emails": []}
links_cache = {}
subscription_rate_state = defaultdict(deque)
subscription_rate_lock = Lock()
traffic_stats_cache: Dict[str, tuple] = {}
online_clients_cache = {"ts": 0.0, "data": []}
clients_cache = {"ts": 0.0, "data": []}
cache_refresh_state = {
    "traffic": set(),
    "online_clients": False,
    "clients": False,
}
auth_cache_lock = Lock()
auth_cache: Dict[str, Tuple[float, str]] = {}
AUTH_CACHE_TTL_SEC = 30
AUTH_CACHE_NEGATIVE_TTL_SEC = 5
_redis_client = None
audit_worker_task = None
history_write_state = {"last_by_node": {}, "last_cleanup_ts": 0.0}
history_write_lock = Lock()
node_metric_labels_state: Dict[str, str] = {}
node_metric_labels_lock = Lock()

# Инициализация менеджеров
inbound_mgr = InboundManager(decrypt_func=decrypt, encrypt_func=encrypt)
client_mgr = ClientManager(decrypt_func=decrypt, encrypt_func=encrypt)
server_monitor = ServerMonitor(decrypt_func=decrypt)
xui_monitor = ThreeXUIMonitor(decrypt_func=decrypt)
node_service = NodeService(DB_PATH)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("sub_manager")
HTTP_REQUEST_COUNT = Counter(
    "sub_manager_http_requests_total",
    "HTTP requests total",
    ["method", "path", "status"],
)
HTTP_REQUEST_LATENCY = Histogram(
    "sub_manager_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "path"],
)
NODE_AVAILABILITY = Gauge(
    "sub_manager_node_available",
    "Node availability (1 available, 0 unavailable)",
    ["node_name", "node_id"],
)
NODE_XRAY_RUNNING = Gauge(
    "sub_manager_node_xray_running",
    "Xray running state on node (1 running, 0 stopped)",
    ["node_name", "node_id"],
)
NODE_CPU_PERCENT = Gauge(
    "sub_manager_node_cpu_percent",
    "Node CPU usage percent",
    ["node_name", "node_id"],
)
NODE_ONLINE_CLIENTS = Gauge(
    "sub_manager_node_online_clients",
    "Online clients count per node",
    ["node_name", "node_id"],
)
NODE_TRAFFIC_TOTAL_BYTES = Gauge(
    "sub_manager_node_traffic_total_bytes",
    "Total traffic bytes per node snapshot",
    ["node_name", "node_id"],
)
NODE_POLL_DURATION_MS = Gauge(
    "sub_manager_node_poll_duration_ms",
    "Collector poll duration per node in milliseconds",
    ["node_name", "node_id"],
)


def _remove_node_metric_labels(node_name: str, node_id: str):
    for metric in (
        NODE_AVAILABILITY,
        NODE_XRAY_RUNNING,
        NODE_CPU_PERCENT,
        NODE_ONLINE_CLIENTS,
        NODE_TRAFFIC_TOTAL_BYTES,
        NODE_POLL_DURATION_MS,
    ):
        try:
            metric.remove(node_name, node_id)
        except KeyError:
            pass
        except ValueError:
            pass


def _record_node_snapshot(snapshot: Dict):
    node_name = str(snapshot.get("name", "unknown"))
    node_id = str(snapshot.get("node_id", "0"))

    with node_metric_labels_lock:
        prev_name = node_metric_labels_state.get(node_id)
        if prev_name and prev_name != node_name:
            _remove_node_metric_labels(prev_name, node_id)
        node_metric_labels_state[node_id] = node_name

    NODE_AVAILABILITY.labels(node_name=node_name, node_id=node_id).set(1 if snapshot.get("available") else 0)
    NODE_XRAY_RUNNING.labels(node_name=node_name, node_id=node_id).set(1 if snapshot.get("xray_running") else 0)
    NODE_CPU_PERCENT.labels(node_name=node_name, node_id=node_id).set(float(snapshot.get("cpu", 0) or 0))
    NODE_ONLINE_CLIENTS.labels(node_name=node_name, node_id=node_id).set(float(snapshot.get("online_clients", 0) or 0))
    NODE_TRAFFIC_TOTAL_BYTES.labels(node_name=node_name, node_id=node_id).set(float(snapshot.get("traffic_total", 0) or 0))
    NODE_POLL_DURATION_MS.labels(node_name=node_name, node_id=node_id).set(float(snapshot.get("poll_ms", 0) or 0))

    if not NODE_HISTORY_ENABLED:
        return

    now_ts = time.time()
    with history_write_lock:
        node_last = history_write_state["last_by_node"].get(node_id, 0.0)
        if now_ts - node_last < max(1, NODE_HISTORY_MIN_INTERVAL_SEC):
            return
        history_write_state["last_by_node"][node_id] = now_ts

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO node_history (
                ts, node_id, node_name, available, xray_running, cpu, online_clients, traffic_total, poll_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(now_ts),
                int(snapshot.get("node_id") or 0),
                node_name,
                1 if snapshot.get("available") else 0,
                1 if snapshot.get("xray_running") else 0,
                float(snapshot.get("cpu", 0) or 0),
                int(snapshot.get("online_clients", 0) or 0),
                float(snapshot.get("traffic_total", 0) or 0),
                float(snapshot.get("poll_ms", 0) or 0),
            ),
        )

        # Lazy retention cleanup (at most once per hour).
        with history_write_lock:
            do_cleanup = now_ts - history_write_state["last_cleanup_ts"] >= 3600
            if do_cleanup:
                history_write_state["last_cleanup_ts"] = now_ts
        if do_cleanup:
            cutoff = int(now_ts - max(1, NODE_HISTORY_RETENTION_DAYS) * 86400)
            conn.execute("DELETE FROM node_history WHERE ts < ?", (cutoff,))
        conn.commit()


snapshot_collector = SnapshotCollector(
    fetch_nodes=node_service.list_nodes,
    xui_monitor=xui_monitor,
    ws_manager=ws_manager,
    on_snapshot=_record_node_snapshot,
    base_interval_sec=COLLECTOR_BASE_INTERVAL_SEC,
    max_interval_sec=COLLECTOR_MAX_INTERVAL_SEC,
    max_parallel_polls=COLLECTOR_MAX_PARALLEL,
)


def render_metrics_response():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def deps_health_status() -> Dict:
    redis_ok = False
    redis_error = None
    client = _redis_get_client()
    if client is None:
        redis_error = "disabled_or_unavailable"
    else:
        try:
            redis_ok = bool(client.ping())
        except Exception as exc:
            redis_error = str(exc)

    return {
        "status": "ok" if snapshot_collector.is_running() else "degraded",
        "collector_running": snapshot_collector.is_running(),
        "redis": {"enabled": bool(REDIS_URL), "ok": redis_ok, "error": redis_error},
    }


app.include_router(
    build_observability_router(
        get_latest_snapshot=snapshot_collector.latest_snapshot,
        render_metrics=render_metrics_response,
        get_deps_health=deps_health_status,
    )
)


def init_db():
    """Инициализация БД"""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS nodes 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, ip TEXT, port TEXT, 
                      user TEXT, password TEXT, base_path TEXT DEFAULT '')''')
        try:
            conn.execute('ALTER TABLE nodes ADD COLUMN base_path TEXT DEFAULT ""')
        except:
            pass
        conn.execute('CREATE TABLE IF NOT EXISTS stats (email TEXT PRIMARY KEY, count INTEGER DEFAULT 0, last_download TEXT)')
        
        # Таблица custom subscription groups
        conn.execute('''CREATE TABLE IF NOT EXISTS subscription_groups 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      name TEXT UNIQUE NOT NULL,
                      identifier TEXT UNIQUE NOT NULL,
                      description TEXT,
                      email_patterns TEXT,
                      node_filters TEXT,
                      protocol_filter TEXT,
                      created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                      updated_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS audit_events
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                      payload TEXT NOT NULL)''')
        conn.execute(
            '''CREATE TABLE IF NOT EXISTS node_history
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      ts INTEGER NOT NULL,
                      node_id INTEGER NOT NULL,
                      node_name TEXT NOT NULL,
                      available INTEGER NOT NULL,
                      xray_running INTEGER NOT NULL,
                      cpu REAL NOT NULL,
                      online_clients INTEGER NOT NULL,
                      traffic_total REAL NOT NULL,
                      poll_ms REAL NOT NULL)'''
        )
        conn.execute('CREATE INDEX IF NOT EXISTS idx_node_history_ts ON node_history(ts)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_node_history_node_ts ON node_history(node_id, ts)')
        
        conn.commit()


init_db()


def sync_node_history_names_with_nodes():
    """Backfill node_history.node_name from current nodes.name by node_id."""
    with sqlite3.connect(DB_PATH) as conn:
        result = conn.execute(
            """
            UPDATE node_history
            SET node_name = (
                SELECT n.name
                FROM nodes n
                WHERE n.id = node_history.node_id
            )
            WHERE EXISTS (
                SELECT 1
                FROM nodes n
                WHERE n.id = node_history.node_id
                  AND IFNULL(n.name, '') <> IFNULL(node_history.node_name, '')
            )
            """
        )
        conn.commit()
    if result.rowcount:
        logger.info(f"node_history names synchronized: {result.rowcount} rows updated")


def check_basic_auth_header(auth_header: Optional[str]) -> Optional[str]:
    """Проверка Basic Auth header через PAM."""
    if not auth_header:
        return None

    now = time.time()
    with auth_cache_lock:
        cached = auth_cache.get(auth_header)
        if cached:
            ts, cached_user = cached
            ttl = AUTH_CACHE_TTL_SEC if cached_user else AUTH_CACHE_NEGATIVE_TTL_SEC
            if now - ts < ttl:
                return cached_user or None
            auth_cache.pop(auth_header, None)

    try:
        scheme, credentials = auth_header.split()
        if scheme.lower() != "basic":
            with auth_cache_lock:
                auth_cache[auth_header] = (now, "")
            return None
        decoded = base64.b64decode(credentials).decode("utf-8")
        username, password = decoded.split(":", 1)
        if p.authenticate(username, password):
            with auth_cache_lock:
                auth_cache[auth_header] = (now, username)
            return username
    except Exception as e:
        logger.warning(f"Auth error: {e}")

    with auth_cache_lock:
        auth_cache[auth_header] = (now, "")
    return None


def verify_totp_code(username: str, totp_code: Optional[str]) -> bool:
    if not MFA_TOTP_ENABLED:
        return True
    if not totp_code:
        return False
    secret = MFA_TOTP_USERS.get(username)
    if not secret:
        return False
    try:
        return bool(pyotp.TOTP(secret).verify(totp_code.strip(), valid_window=1))
    except Exception:
        return False


def _redis_get_client():
    global _redis_client
    if not REDIS_URL or redis is None:
        return None
    if _redis_client is not None:
        return _redis_client
    try:
        _redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    except Exception as exc:
        logger.warning(f"Failed to initialize redis client: {exc}")
        _redis_client = None
    return _redis_client


def _redis_get_json(key: str):
    client = _redis_get_client()
    if not client:
        return None
    try:
        raw = client.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as exc:
        logger.warning(f"Redis get failed for {key}: {exc}")
        return None


def _redis_set_json(key: str, value, ttl: int):
    client = _redis_get_client()
    if not client:
        return
    try:
        client.setex(key, ttl, json.dumps(value, ensure_ascii=False))
    except Exception as exc:
        logger.warning(f"Redis set failed for {key}: {exc}")


def _redis_delete(*keys: str):
    client = _redis_get_client()
    if not client:
        return
    try:
        client.delete(*keys)
    except Exception as exc:
        logger.warning(f"Redis delete failed: {exc}")


def enqueue_audit_event(payload: Dict):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO audit_events (payload) VALUES (?)",
                (json.dumps(payload, ensure_ascii=False),),
            )
            conn.commit()
    except Exception as exc:
        logger.warning(f"Failed to enqueue audit event: {exc}")


def _drain_audit_events_batch(limit: int) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, payload FROM audit_events ORDER BY id ASC LIMIT ?",
            (limit,),
        ).fetchall()
        if not rows:
            return 0
        ids = []
        for row in rows:
            ids.append(row["id"])
            try:
                payload = json.loads(row["payload"])
            except Exception:
                payload = {"event": "audit", "raw": row["payload"]}
            logger.info(json.dumps({"event": "audit_log", "payload": payload}, ensure_ascii=False))
        placeholders = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM audit_events WHERE id IN ({placeholders})", ids)
        conn.commit()
        return len(ids)


async def audit_worker_loop():
    while True:
        try:
            drained = await asyncio.to_thread(_drain_audit_events_batch, AUDIT_QUEUE_BATCH_SIZE)
            await asyncio.sleep(0.2 if drained > 0 else 1.0)
        except Exception as exc:
            logger.error(f"audit worker error: {exc}")
            await asyncio.sleep(1.0)


def extract_basic_auth_username(auth_header: Optional[str]) -> Optional[str]:
    """Извлечь username из Basic Auth header без валидации PAM."""
    if not auth_header:
        return None
    try:
        scheme, credentials = auth_header.split()
        if scheme.lower() != "basic":
            return None
        decoded = base64.b64decode(credentials).decode("utf-8")
        username, _ = decoded.split(":", 1)
        return username
    except Exception:
        return None


def _get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _check_subscription_rate_limit(request: Request, resource_key: str) -> Tuple[bool, int]:
    now = time.time()
    key = f"{_get_client_ip(request)}:{resource_key}"
    with subscription_rate_lock:
        q = subscription_rate_state[key]
        while q and now - q[0] > SUB_RATE_LIMIT_WINDOW_SEC:
            q.popleft()
        if len(q) >= SUB_RATE_LIMIT_COUNT:
            retry_after = max(1, int(SUB_RATE_LIMIT_WINDOW_SEC - (now - q[0])))
            return False, retry_after
        q.append(now)
    return True, 0


def invalidate_live_stats_cache():
    traffic_stats_cache.clear()
    online_clients_cache["ts"] = 0.0
    online_clients_cache["data"] = []
    clients_cache["ts"] = 0.0
    clients_cache["data"] = []
    _redis_delete("traffic_stats:client", "traffic_stats:inbound", "traffic_stats:node", "online_clients")


def _start_cache_refresh(flag_key: str, worker, worker_key: Optional[str] = None):
    with subscription_rate_lock:
        if flag_key == "traffic":
            if not worker_key:
                return
            if worker_key in cache_refresh_state["traffic"]:
                return
            cache_refresh_state["traffic"].add(worker_key)
        else:
            if cache_refresh_state.get(flag_key):
                return
            cache_refresh_state[flag_key] = True

    def _runner():
        try:
            worker()
        except Exception as exc:
            logger.warning(f"Cache refresh failed ({flag_key}): {exc}")
        finally:
            with subscription_rate_lock:
                if flag_key == "traffic":
                    if worker_key:
                        cache_refresh_state["traffic"].discard(worker_key)
                else:
                    cache_refresh_state[flag_key] = False

    Thread(target=_runner, daemon=True).start()


def get_cached_traffic_stats(nodes: List[Dict], group_by: str) -> Dict:
    redis_key = f"traffic_stats:{group_by}"
    redis_data = _redis_get_json(redis_key)
    if redis_data is not None:
        return redis_data

    now = time.time()
    cached = traffic_stats_cache.get(group_by)
    if cached and now - cached[0] < TRAFFIC_STATS_CACHE_TTL:
        return cached[1]

    # Serve stale data quickly and refresh in background.
    if cached and now - cached[0] < TRAFFIC_STATS_STALE_TTL:
        def _refresh():
            fresh = client_mgr.get_traffic_stats(nodes, group_by)
            traffic_stats_cache[group_by] = (time.time(), fresh)
            _redis_set_json(redis_key, fresh, TRAFFIC_STATS_CACHE_TTL)
        _start_cache_refresh("traffic", _refresh, worker_key=group_by)
        return cached[1]

    data = client_mgr.get_traffic_stats(nodes, group_by)
    traffic_stats_cache[group_by] = (now, data)
    _redis_set_json(redis_key, data, TRAFFIC_STATS_CACHE_TTL)
    return data


def get_cached_online_clients(nodes: List[Dict]) -> List[Dict]:
    redis_data = _redis_get_json("online_clients")
    if isinstance(redis_data, list):
        return redis_data

    now = time.time()
    if now - online_clients_cache["ts"] < ONLINE_CLIENTS_CACHE_TTL:
        return online_clients_cache["data"]

    if online_clients_cache["data"] and now - online_clients_cache["ts"] < ONLINE_CLIENTS_STALE_TTL:
        def _refresh():
            fresh = client_mgr.get_online_clients(nodes)
            online_clients_cache["ts"] = time.time()
            online_clients_cache["data"] = fresh
            _redis_set_json("online_clients", fresh, ONLINE_CLIENTS_CACHE_TTL)
        _start_cache_refresh("online_clients", _refresh)
        return online_clients_cache["data"]

    data = client_mgr.get_online_clients(nodes)
    online_clients_cache["ts"] = now
    online_clients_cache["data"] = data
    _redis_set_json("online_clients", data, ONLINE_CLIENTS_CACHE_TTL)
    return data


def get_cached_clients(nodes: List[Dict], email_filter: Optional[str] = None) -> List[Dict]:
    now = time.time()
    full_list = clients_cache["data"] if isinstance(clients_cache["data"], list) else []

    def _apply_filter(items: List[Dict]) -> List[Dict]:
        if not email_filter:
            return items
        needle = email_filter.lower()
        return [c for c in items if needle in str(c.get("email", "")).lower()]

    if full_list and now - clients_cache["ts"] < CLIENTS_CACHE_TTL:
        return _apply_filter(full_list)

    if full_list and now - clients_cache["ts"] < CLIENTS_CACHE_STALE_TTL:
        def _refresh():
            fresh = client_mgr.get_all_clients(nodes, email_filter=None)
            clients_cache["ts"] = time.time()
            clients_cache["data"] = fresh
        _start_cache_refresh("clients", _refresh)
        return _apply_filter(full_list)

    fresh = client_mgr.get_all_clients(nodes, email_filter=None)
    clients_cache["ts"] = now
    clients_cache["data"] = fresh
    return _apply_filter(fresh)


def get_user_role(username: str) -> str:
    if username in ROLE_OPERATORS:
        return "operator"
    if username in ROLE_VIEWERS:
        return "viewer"
    return "admin"


def has_min_role(user_role: str, min_role: str) -> bool:
    return ROLE_RANK.get(user_role, 0) >= ROLE_RANK.get(min_role, 0)


def _is_public_endpoint(path: str) -> bool:
    return (
        path == "/health"
        or path == "/api/v1/health"
        or path == "/api/v1/auth/mfa-status"
        or path.startswith("/api/v1/sub/")
        or path.startswith("/api/v1/sub-grouped/")
    )


def _required_role_for_request(method: str, path: str) -> str:
    if method == "POST" and path.startswith("/api/v1/servers/") and path.endswith("/restart-xray"):
        return "admin"
    if method == "POST" and path == "/api/v1/automation/reset-all-traffic":
        return "admin"
    if method == "POST" and path == "/api/v1/inbounds/batch-delete":
        return "admin"
    if method == "POST" and path == "/api/v1/clients/batch-delete":
        return "admin"
    if method == "POST" and path.startswith("/api/v1/backup/database/"):
        return "admin"
    if method == "DELETE" and path.startswith("/api/v1/nodes/"):
        return "admin"
    if method == "DELETE" and path.startswith("/api/v1/subscription-groups/"):
        return "admin"
    if method in {"POST", "PUT", "DELETE", "PATCH"}:
        return "operator"
    return "viewer"


def check_auth(request: Request) -> Optional[str]:
    """Проверка Basic Auth через PAM."""
    if hasattr(request.state, "auth_user"):
        return request.state.auth_user
    return check_basic_auth_header(request.headers.get("Authorization"))


@app.middleware("http")
async def request_controls_and_audit_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    start = time.perf_counter()
    path = request.url.path

    request.state.auth_user = None
    request.state.auth_role = None
    request.state.auth_mfa_ok = False

    response = None

    if path.startswith("/api/v1/") and not _is_public_endpoint(path):
        auth_user = check_basic_auth_header(request.headers.get("Authorization"))
        if not auth_user:
            response = JSONResponse(status_code=401, content={"detail": "Unauthorized"})
        else:
            auth_role = get_user_role(auth_user)
            request.state.auth_user = auth_user
            request.state.auth_role = auth_role
            mfa_code = request.headers.get("X-TOTP-Code")
            if not verify_totp_code(auth_user, mfa_code):
                response = JSONResponse(status_code=401, content={"detail": "MFA required"})
                request.state.auth_mfa_ok = False
            else:
                request.state.auth_mfa_ok = True
            if response is not None:
                pass
            required_role = _required_role_for_request(request.method, path)
            if response is None and not has_min_role(auth_role, required_role):
                response = JSONResponse(
                    status_code=403,
                    content={"detail": f"Forbidden for role '{auth_role}', requires '{required_role}'"},
                )

    if response is None and READ_ONLY_MODE and request.method in {"POST", "PUT", "DELETE", "PATCH"} and path.startswith("/api/v1/"):
        response = JSONResponse(
            status_code=403,
            content={"detail": "Read-only mode is enabled"},
        )
    elif response is None:
        response = await call_next(request)

    if (
        response.status_code < 400
        and request.method in {"POST", "PUT", "DELETE", "PATCH"}
        and path.startswith("/api/v1/")
    ):
        invalidate_live_stats_cache()

    response.headers["X-Request-ID"] = request_id
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    path_label = path if path.startswith("/api/v1/") else path
    HTTP_REQUEST_COUNT.labels(request.method, path_label, str(response.status_code)).inc()
    HTTP_REQUEST_LATENCY.labels(request.method, path_label).observe(duration_ms / 1000.0)
    audit_payload = {
        "event": "http_access",
        "request_id": request_id,
        "method": request.method,
        "path": path,
        "status_code": response.status_code,
        "duration_ms": duration_ms,
        "client_ip": _get_client_ip(request),
        "user_hint": request.state.auth_user or extract_basic_auth_username(request.headers.get("Authorization")) or "anonymous",
        "user_role": request.state.auth_role,
    }
    enqueue_audit_event(audit_payload)
    return response


def fetch_inbounds(node: Dict) -> List[Dict]:
    """Получить список inbound'ов с node panel панели"""
    s = requests.Session()
    s.verify = REQUESTS_VERIFY
    b_path = node['base_path'].strip('/')
    prefix = f"/{b_path}" if b_path else ""
    base_url = f"https://{node['ip']}:{node['port']}{prefix}"
    
    # Расшифровываем пароль если зашифрован
    node_password = node.get('password', '')
    if node_password:
        try:
            node_password = decrypt(node_password)
        except Exception as e:
            logger.warning(f"Failed to decrypt password for node {node['name']}: {e}")
    
    if not login_node panel(s, base_url, node['user'], node_password):
        logger.warning(f"node panel {node['name']} login failed")
        return []

    try:
        res = s.get(f"{base_url}/panel/api/inbounds/list", timeout=5)
        if res.status_code != 200:
            logger.warning(
                f"node panel {node['name']} inbounds list returned status {res.status_code}; "
                f"response (first 200 chars): {res.text[:200]!r}"
            )
            return []
        data = res.json()
        
        if not data.get("success"):
            logger.warning(f"node panel {node['name']} returned success=false")
            return []
        return data.get("obj", [])
    except requests.RequestException as exc:
        logger.warning(f"node panel {node['name']} request failed: {exc}")
    except ValueError as exc:
        logger.warning(f"node panel {node['name']} invalid JSON: {exc}")
    return []


def get_emails(nodes: List[Dict]) -> List[str]:
    """Получить список всех email'ов с узлов"""
    now = time.time()
    if now - emails_cache["ts"] < CACHE_TTL:
        return emails_cache["emails"]
    
    emails = set()
    for n in nodes:
        for ib in fetch_inbounds(n):
            clients = parse_field_as_dict(
                ib.get("settings"), node_id=n["name"], field_name="settings"
            ).get("clients", [])
            for c in clients:
                if c.get("email"):
                    emails.add(c.get("email"))
    
    emails_list = sorted(list(emails))
    emails_cache.update({"ts": now, "emails": emails_list})
    return emails_list


def get_links(nodes: List[Dict], email: str) -> List[str]:
    """Генерировать ссылки подписки для email'а"""
    now_link = time.time()
    cached = links_cache.get(email)
    if cached and now_link - cached[0] < CACHE_TTL:
        return cached[1]


# === Inbounds Management ===


def get_all_inbounds(nodes: List[Dict]) -> List[Dict]:
    """Получить все инбаунды со всех узлов"""
    inbounds = []
    for n in nodes:
        for ib in fetch_inbounds(n):
            stream = parse_field_as_dict(
                ib.get("streamSettings"), node_id=n["name"], field_name="streamSettings"
            )
            inbound = {
                "id": ib.get("id"),
                "node_name": n["name"],
                "node_ip": n["ip"],
                "protocol": ib.get("protocol"),
                "port": ib.get("port"),
                "remark": ib.get("remark", ""),
                "enable": ib.get("enable", True),
                "streamSettings": stream,
                "settings": parse_field_as_dict(
                    ib.get("settings"), node_id=n["name"], field_name="settings"
                )
            }
            security = stream.get("security", "")
            inbound["security"] = security
            inbound["is_reality"] = security == "reality"
            inbounds.append(inbound)
    return inbounds


def add_inbound_to_node(node: Dict, inbound_config: Dict) -> bool:
    """Добавить инбаунд на узел node panel"""
    s = requests.Session()
    s.verify = REQUESTS_VERIFY
    b_path = node["base_path"].strip("/")
    prefix = f"/{b_path}" if b_path else ""
    base_url = f"https://{node['ip']}:{node['port']}{prefix}"
    
    try:
        if not login_node panel(s, base_url, node['user'], decrypt(node.get('password', ''))):
            logger.warning(f"Failed to login for add_inbound on {node['name']}")
            return False
        res = s.post(f"{base_url}/panel/api/inbounds/add", json=inbound_config, timeout=5)
        return res.status_code == 200
    except Exception as exc:
        logger.warning(f"Failed to add inbound to {node['name']}: {exc}")
    return False


def add_client_to_inbound(node: Dict, inbound_id: int, client_config: Dict) -> bool:
    """Добавить клиента в инбаунд"""
    s = requests.Session()
    s.verify = REQUESTS_VERIFY
    b_path = node["base_path"].strip("/")
    prefix = f"/{b_path}" if b_path else ""
    base_url = f"https://{node['ip']}:{node['port']}{prefix}"
    
    try:
        if not login_node panel(s, base_url, node['user'], decrypt(node.get('password', ''))):
            logger.warning(f"Failed to login for add_client on {node['name']}")
            return False
        payload = {"id": inbound_id, "settings": {"clients": [client_config]}}
        res = s.post(f"{base_url}/panel/api/inbounds/addClient", json=payload, timeout=5)
        return res.status_code == 200
    except Exception as exc:
        logger.warning(f"Failed to add client to {node['name']}: {exc}")
    return False


def delete_client_from_inbound(node: Dict, inbound_id: int, client_id: str) -> bool:
    """Удалить клиента из инбаунда"""
    s = requests.Session()
    s.verify = REQUESTS_VERIFY
    b_path = node["base_path"].strip("/")
    prefix = f"/{b_path}" if b_path else ""
    base_url = f"https://{node['ip']}:{node['port']}{prefix}"
    
    try:
        if not login_node panel(s, base_url, node['user'], decrypt(node.get('password', ''))):
            logger.warning(f"Failed to login for delete_client on {node['name']}")
            return False
        res = s.post(f"{base_url}/panel/api/inbounds/{inbound_id}/delClient/{client_id}", timeout=5)
        return res.status_code == 200
    except Exception as exc:
        logger.warning(f"Failed to delete client from {node['name']}: {exc}")
    return False


def get_client_traffic(node: Dict, client_id: str, protocol: str) -> Dict:
    """Получить статистику клиента"""
    s = requests.Session()
    s.verify = REQUESTS_VERIFY
    b_path = node["base_path"].strip("/")
    prefix = f"/{b_path}" if b_path else ""
    base_url = f"https://{node['ip']}:{node['port']}{prefix}"
    
    try:
        if not login_node panel(s, base_url, node['user'], decrypt(node.get('password', ''))):
            logger.warning(f"Failed to login for get_traffic on {node['name']}")
            return {}
        if protocol in ("vless", "vmess"):
            res = s.get(f"{base_url}/panel/api/inbounds/getClientTrafficsById/{client_id}", timeout=5)
        else:
            res = s.get(f"{base_url}/panel/api/inbounds/getClientTraffics/{client_id}", timeout=5)
        if res.status_code == 200:
            obj = res.json().get("obj", {})
            if not isinstance(obj, dict):
                logger.warning(
                    f"Unexpected type for traffic obj on {node['name']}: "
                    f"expected dict, got {type(obj).__name__}"
                )
                return {}
            return obj
    except Exception as exc:
        logger.warning(f"Failed to get traffic from {node['name']}: {exc}")
    return {}
    
    links = []
    for n in nodes:
        for ib in fetch_inbounds(n):
            protocol = ib.get("protocol", "")
            try:
                s_set = json.loads(ib.get("streamSettings", "{}"))
            except (TypeError, ValueError) as exc:
                logger.warning(f"Invalid streamSettings JSON for node {n['name']}: {exc}")
                continue
            
            security = s_set.get("security", "")
            if protocol not in ("vless", "vmess", "trojan"):
                continue
            if security not in ("reality", "tls"):
                continue
            
            try:
                settings = json.loads(ib.get("settings", "{}"))
            except (TypeError, ValueError) as exc:
                logger.warning(f"Invalid settings JSON for node {n['name']}: {exc}")
                continue
            
            for c in settings.get("clients", []):
                if c.get("email") != email:
                    continue
                
                r = s_set.get('realitySettings', {})
                pbk = r.get('settings', {}).get('publicKey', '')
                
                if protocol == "vless":
                    sid = r.get('shortIds', [''])[0] if r.get('shortIds') else ''
                    sni = (r.get('serverNames') or [''])[0]
                    fp = r.get('fingerprint', 'chrome')
                    network = s_set.get('network', 'tcp')
                    flow = c.get('flow', '')
                    flow_param = f"&flow={flow}" if flow else ""
                    
                    if security == "reality":
                        links.append(
                            f"vless://{c['id']}@{n['ip']}:443?encryption=none&security=reality"
                            f"&sni={sni}&fp={fp}&pbk={pbk}&sid={sid}"
                            f"{flow_param}&type={network}#{n['name']}"
                        )
                    else:
                        links.append(
                            f"vless://{c['id']}@{n['ip']}:443?encryption=none&security=tls"
                            f"&sni={sni}&fp={fp}{flow_param}&type={network}#{n['name']}"
                        )
                
                elif protocol == "vmess":
                    if security == "reality":
                        sid = r.get('shortIds', [''])[0] if r.get('shortIds') else ''
                        link_obj = {
                            "v": "2", "ps": f"{c['email']} ({n['name']})", "add": n['ip'], "port": "443",
                            "id": c.get('id', ''), "aid": "0", "net": s_set.get('network', 'tcp'),
                            "type": "none", "tls": "",
                            "sni": (r.get('serverNames') or [''])[0], "host": (r.get('serverNames') or [''])[0],
                            "pbk": pbk, "sid": sid, "fp": r.get('fingerprint', 'chrome')
                        }
                        links.append("vmess://" + base64.b64encode(json.dumps(link_obj).encode()).decode())
                    else:
                        link_obj = {
                            "v": "2", "ps": f"{c['email']} ({n['name']})", "add": n['ip'], "port": "443",
                            "id": c.get('id', ''), "aid": "0", "net": s_set.get('network', 'tcp'),
                            "type": "none", "tls": "tls", "sni": ((s_set.get('tlsSettings', {}) or {}).get('serverNames', [''] or [''])[0])
                        }
                        links.append("vmess://" + base64.b64encode(json.dumps(link_obj).encode()).decode())
                
                elif protocol == "trojan":
                    if security == "reality":
                        sid = r.get('shortIds', [''])[0] if r.get('shortIds') else ''
                        sni = (r.get('serverNames') or [''])[0]
                        fp = r.get('fingerprint', 'chrome')
                        network = s_set.get('network', 'tcp')
                        links.append(
                            f"trojan://{c['password']}@{n['ip']}:443?security=reality"
                            f"&sni={sni}&fp={fp}&pbk={pbk}&sid={sid}"
                            f"&type={network}#{n['name']}"
                        )
                    else:
                        sni = ((s_set.get('tlsSettings', {}) or {}).get('serverNames', [''] or [''])[0])
                        links.append(
                            f"trojan://{c['password']}@{n['ip']}:443?security=tls"
                            f"&sni={sni}&type={s_set.get('network','tcp')}#{n['name']}"
                        )
    
    links_cache[email] = (now_link, links)
    return links


def get_links_filtered(nodes: List[Dict], email: str, protocol_filter: Optional[str] = None) -> List[str]:
    """Генерировать ссылки подписки с фильтрацией"""
    cache_key = f"{email}_{protocol_filter or 'all'}_{','.join([n['name'] for n in nodes])}"
    now_link = time.time()
    cached = links_cache.get(cache_key)
    if cached and now_link - cached[0] < CACHE_TTL:
        return cached[1]
    
    links = []
    for n in nodes:
        for ib in fetch_inbounds(n):
            protocol = ib.get("protocol", "")
            
            # Фильтр по протоколу
            if protocol_filter and protocol != protocol_filter:
                continue
            
            s_set = parse_field_as_dict(
                ib.get("streamSettings"), node_id=n["name"], field_name="streamSettings"
            )
            
            security = s_set.get("security", "")
            if protocol not in ("vless", "vmess", "trojan"):
                continue
            if security not in ("reality", "tls"):
                continue
            
            settings = parse_field_as_dict(
                ib.get("settings"), node_id=n["name"], field_name="settings"
            )
            
            for c in settings.get("clients", []):
                if c.get("email") != email:
                    continue
                
                r = s_set.get('realitySettings', {})
                pbk = r.get('settings', {}).get('publicKey', '')
                
                if protocol == "vless":
                    sid = r.get('shortIds', [''])[0] if r.get('shortIds') else ''
                    sni = (r.get('serverNames') or [''])[0]
                    fp = r.get('fingerprint', 'chrome')
                    network = s_set.get('network', 'tcp')
                    flow = c.get('flow', '')
                    flow_param = f"&flow={flow}" if flow else ""
                    
                    if security == "reality":
                        links.append(
                            f"vless://{c['id']}@{n['ip']}:443?encryption=none&security=reality"
                            f"&sni={sni}&fp={fp}&pbk={pbk}&sid={sid}"
                            f"{flow_param}&type={network}#{n['name']}"
                        )
                    else:
                        links.append(
                            f"vless://{c['id']}@{n['ip']}:443?encryption=none&security=tls"
                            f"&sni={sni}&fp={fp}{flow_param}&type={network}#{n['name']}"
                        )
                
                elif protocol == "vmess":
                    if security == "reality":
                        sid = r.get('shortIds', [''])[0] if r.get('shortIds') else ''
                        link_obj = {
                            "v": "2", "ps": f"{c['email']} ({n['name']})", "add": n['ip'], "port": "443",
                            "id": c.get('id', ''), "aid": "0", "net": s_set.get('network', 'tcp'),
                            "type": "none", "tls": "",
                            "sni": (r.get('serverNames') or [''])[0], "host": (r.get('serverNames') or [''])[0],
                            "pbk": pbk, "sid": sid, "fp": r.get('fingerprint', 'chrome')
                        }
                        links.append("vmess://" + base64.b64encode(json.dumps(link_obj).encode()).decode())
                    else:
                        link_obj = {
                            "v": "2", "ps": f"{c['email']} ({n['name']})", "add": n['ip'], "port": "443",
                            "id": c.get('id', ''), "aid": "0", "net": s_set.get('network', 'tcp'),
                            "type": "none", "tls": "tls", "sni": ((s_set.get('tlsSettings', {}) or {}).get('serverNames', [''] or [''])[0])
                        }
                        links.append("vmess://" + base64.b64encode(json.dumps(link_obj).encode()).decode())
                
                elif protocol == "trojan":
                    if security == "reality":
                        sid = r.get('shortIds', [''])[0] if r.get('shortIds') else ''
                        sni = (r.get('serverNames') or [''])[0]
                        fp = r.get('fingerprint', 'chrome')
                        network = s_set.get('network', 'tcp')
                        links.append(
                            f"trojan://{c['password']}@{n['ip']}:443?security=reality"
                            f"&sni={sni}&fp={fp}&pbk={pbk}&sid={sid}"
                            f"&type={network}#{n['name']}"
                        )
                    else:
                        sni = ((s_set.get('tlsSettings', {}) or {}).get('serverNames', [''] or [''])[0])
                        links.append(
                            f"trojan://{c['password']}@{n['ip']}:443?security=tls"
                            f"&sni={sni}&type={s_set.get('network','tcp')}#{n['name']}"
                        )
    
    links_cache[cache_key] = (now_link, links)
    return links


# === API Endpoints ===

@app.get("/api/v1/health")
@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.datetime.now().isoformat()}


@app.get("/api/v1/auth/verify")
async def verify_auth(request: Request):
    """Проверить авторизацию"""
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not verify_totp_code(user, request.headers.get("X-TOTP-Code")):
        raise HTTPException(status_code=401, detail="MFA required")
    role = getattr(request.state, "auth_role", None) or get_user_role(user)
    return {"user": user, "role": role, "mfa_enabled": MFA_TOTP_ENABLED}


@app.get("/api/v1/auth/mfa-status")
async def mfa_status():
    return {"enabled": MFA_TOTP_ENABLED}


@app.get("/api/v1/nodes")
async def list_nodes(request: Request):
    """Получить список узлов"""
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    nodes = node_service.list_nodes()
    result = []
    for node_dict in nodes:
        node_dict.pop("password", None)
        result.append(node_dict)
    return JSONResponse(content=result, headers={"Cache-Control": "private, max-age=300"})


@app.get("/api/v1/nodes/list")
async def list_nodes_simple(request: Request):
    """Получить упрощённый список узлов (id + name) для выбора в UI"""
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    return JSONResponse(
        content=node_service.list_nodes_simple(),
        headers={"Cache-Control": "private, max-age=300"},
    )


@app.post("/api/v1/nodes")
async def add_node(request: Request, data: Dict):
    """Добавить новый узел"""
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    name = data.get("name")
    url = data.get("url")
    node_user = data.get("user")
    password = data.get("password")
    
    if not all([name, url, node_user, password]):
        raise HTTPException(status_code=400, detail="Missing required fields")
    
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    parsed = urlparse(url)
    
    try:
        # Шифруем пароль перед сохранением
        encrypted_password = encrypt(password)
        
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute('INSERT INTO nodes (name, ip, port, user, password, base_path) VALUES (?,?,?,?,?,?)',
                        (name, parsed.hostname, str(parsed.port) if parsed.port else "443", node_user, encrypted_password, parsed.path.strip('/')))
            conn.commit()
    except Exception as e:
        logger.error(f"Error adding node: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
    emails_cache["ts"] = 0
    links_cache.clear()
    return {"status": "success"}


@app.put("/api/v1/nodes/{node_id}")
async def update_node(node_id: int, request: Request, data: Dict):
    """Обновить имя узла"""
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    name = data.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name cannot be empty")

    try:
        with sqlite3.connect(DB_PATH) as conn:
            existing = conn.execute('SELECT name FROM nodes WHERE id = ?', (node_id,)).fetchone()
            if not existing:
                raise HTTPException(status_code=404, detail="Node not found")

            old_name = str(existing[0] or "")
            result = conn.execute('UPDATE nodes SET name = ? WHERE id = ?', (name, node_id))
            conn.execute('UPDATE node_history SET node_name = ? WHERE node_id = ?', (name, node_id))
            conn.commit()
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail="Node not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating node: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    node_id_str = str(node_id)
    with node_metric_labels_lock:
        if old_name and old_name != name:
            _remove_node_metric_labels(old_name, node_id_str)
        node_metric_labels_state[node_id_str] = name

    emails_cache["ts"] = 0
    links_cache.clear()
    return {"status": "success"}


@app.delete("/api/v1/nodes/{node_id}")
async def delete_node(node_id: int, request: Request):
    """Удалить узел"""
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute('DELETE FROM nodes WHERE id = ?', (node_id,))
            conn.commit()
    except Exception as e:
        logger.error(f"Error deleting node: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
    emails_cache["ts"] = 0
    links_cache.clear()
    return {"status": "success"}


@app.get("/api/v1/emails")
async def list_emails(request: Request):
    """Получить список всех email'ов"""
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        nodes = conn.execute('SELECT * FROM nodes').fetchall()
        emails = get_emails([dict(n) for n in nodes])
        
        # Получить статистику
        stats = {}
        for row in conn.execute('SELECT * FROM stats').fetchall():
            stats[row['email']] = {"count": row['count'], "last": row['last_download']}
        
        return JSONResponse(
            content={"emails": emails, "stats": stats},
            headers={"Cache-Control": "private, max-age=600"},
        )


@app.get("/api/v1/sub/{email}")
async def get_sub(request: Request, email: str, protocol: Optional[str] = None, nodes: Optional[str] = None):
    """Получить подписку для email'а (без авторизации)
    
    Query params:
    - protocol: фильтр по протоколу (vless, vmess, trojan)
    - nodes: список node names через запятую (node1,node2)
    """
    allowed, retry_after = _check_subscription_rate_limit(request, f"sub:{email.lower()}")
    if not allowed:
        return PlainTextResponse(
            content=f"Rate limit exceeded. Retry after {retry_after}s",
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        all_nodes = [dict(n) for n in conn.execute('SELECT * FROM nodes').fetchall()]
        
        # Фильтрация по nodes
        if nodes:
            node_names = [n.strip() for n in nodes.split(',')]
            all_nodes = [n for n in all_nodes if n['name'] in node_names]
        
        links = get_links_filtered(all_nodes, email, protocol)
        
        if links:
            now = datetime.datetime.now().strftime("%d.%m %H:%M")
            with sqlite3.connect(DB_PATH) as db:
                db.execute('INSERT INTO stats (email, count, last_download) VALUES (?, 1, ?) '
                          'ON CONFLICT(email) DO UPDATE SET count=count+1, last_download=?',
                          (email, now, now))
                db.commit()
            return PlainTextResponse(content=base64.b64encode("\n".join(links).encode()).decode())
        
        return PlainTextResponse(content="Not found", status_code=404)


@app.get("/api/v1/sub-grouped/{identifier}")
async def get_sub_grouped(request: Request, identifier: str, protocol: Optional[str] = None, nodes: Optional[str] = None):
    """Получить групповую подписку (по части email или имени)
    
    Примеры:
    - /api/v1/sub-grouped/company - все email содержащие 'company'
    - /api/v1/sub-grouped/user1 - все email содержащие 'user1'
    """
    allowed, retry_after = _check_subscription_rate_limit(request, f"sub-grouped:{identifier.lower()}")
    if not allowed:
        return PlainTextResponse(
            content=f"Rate limit exceeded. Retry after {retry_after}s",
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        all_nodes = [dict(n) for n in conn.execute('SELECT * FROM nodes').fetchall()]
        
        # Проверить custom group
        custom_group = conn.execute('SELECT * FROM subscription_groups WHERE identifier = ?', (identifier,)).fetchone()
        if custom_group:
            custom_group = dict(custom_group)
            # Использовать настройки группы
            if custom_group.get('node_filters'):
                node_names = json.loads(custom_group['node_filters'])
                all_nodes = [n for n in all_nodes if n['name'] in node_names]
            
            if custom_group.get('protocol_filter'):
                protocol = custom_group['protocol_filter']
            
            # Получить email patterns
            email_patterns = json.loads(custom_group.get('email_patterns', '[]'))
            
            all_emails = get_emails(all_nodes)
            matching_emails = []
            for pattern in email_patterns:
                matching_emails.extend([e for e in all_emails if pattern.lower() in e.lower()])
            matching_emails = list(set(matching_emails))  # Удалить дубликаты
        else:
            # Фильтрация по nodes
            if nodes:
                node_names = [n.strip() for n in nodes.split(',')]
                all_nodes = [n for n in all_nodes if n['name'] in node_names]
            
            # Найти все email содержащие identifier
            all_emails = get_emails(all_nodes)
            matching_emails = [e for e in all_emails if identifier.lower() in e.lower()]
        
        if not matching_emails:
            return PlainTextResponse(content="No matching clients found", status_code=404)
        
        # Собрать ссылки для всех найденных email
        all_links = []
        for email in matching_emails:
            links = get_links_filtered(all_nodes, email, protocol)
            all_links.extend(links)
        
        if all_links:
            now = datetime.datetime.now().strftime("%d.%m %H:%M")
            with sqlite3.connect(DB_PATH) as db:
                for email in matching_emails:
                    db.execute('INSERT INTO stats (email, count, last_download) VALUES (?, 1, ?) '
                              'ON CONFLICT(email) DO UPDATE SET count=count+1, last_download=?',
                              (email, now, now))
                db.commit()
            return PlainTextResponse(content=base64.b64encode("\n".join(all_links).encode()).decode())
        
        return PlainTextResponse(content="Not found", status_code=404)


# === Subscription Groups Management API ===


@app.get("/api/v1/subscription-groups")
async def list_subscription_groups(request: Request):
    """Получить список custom subscription groups"""
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        groups = [dict(row) for row in conn.execute('SELECT * FROM subscription_groups ORDER BY created_at DESC').fetchall()]
        
        # Распарсить JSON поля
        for group in groups:
            group['email_patterns'] = json.loads(group.get('email_patterns', '[]'))
            group['node_filters'] = json.loads(group.get('node_filters', '[]'))
        
        return {"groups": groups, "count": len(groups)}


@app.post("/api/v1/subscription-groups")
async def create_subscription_group(request: Request, data: Dict):
    """Создать custom subscription group
    
    Payload:
    {
        "name": "VIP Clients",
        "identifier": "vip-clients",
        "description": "VIP clients subscription",
        "email_patterns": ["vip", "premium"],
        "node_filters": ["Node1", "Node2"],
        "protocol_filter": "vless"
    }
    """
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    name = data.get("name")
    identifier = data.get("identifier")
    description = data.get("description", "")
    email_patterns = json.dumps(data.get("email_patterns", []))
    node_filters = json.dumps(data.get("node_filters", []))
    protocol_filter = data.get("protocol_filter")
    
    if not name or not identifier:
        raise HTTPException(status_code=400, detail="name and identifier required")
    
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute('''INSERT INTO subscription_groups 
                          (name, identifier, description, email_patterns, node_filters, protocol_filter)
                          VALUES (?, ?, ?, ?, ?, ?)''',
                        (name, identifier, description, email_patterns, node_filters, protocol_filter))
            conn.commit()
        return {"status": "success", "identifier": identifier}
    except Exception as e:
        logger.error(f"Error creating subscription group: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/v1/subscription-groups/{group_id}")
async def update_subscription_group(request: Request, group_id: int, data: Dict):
    """Обновить custom subscription group"""
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    updates = []
    params = []
    
    if "name" in data:
        updates.append("name = ?")
        params.append(data["name"])
    if "identifier" in data:
        updates.append("identifier = ?")
        params.append(data["identifier"])
    if "description" in data:
        updates.append("description = ?")
        params.append(data["description"])
    if "email_patterns" in data:
        updates.append("email_patterns = ?")
        params.append(json.dumps(data["email_patterns"]))
    if "node_filters" in data:
        updates.append("node_filters = ?")
        params.append(json.dumps(data["node_filters"]))
    if "protocol_filter" in data:
        updates.append("protocol_filter = ?")
        params.append(data["protocol_filter"])
    
    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")
    
    updates.append("updated_at = CURRENT_TIMESTAMP")
    params.append(group_id)
    
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(f"UPDATE subscription_groups SET {', '.join(updates)} WHERE id = ?", params)
            conn.commit()
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error updating subscription group: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/v1/subscription-groups/{group_id}")
async def delete_subscription_group(request: Request, group_id: int):
    """Удалить custom subscription group"""
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute('DELETE FROM subscription_groups WHERE id = ?', (group_id,))
            conn.commit()
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error deleting subscription group: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# === Inbounds Management API ===


@app.get("/api/v1/inbounds")
async def list_inbounds(request: Request, protocol: Optional[str] = None, security: Optional[str] = None):
    """Получить список инбаундов с фильтрацией"""
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401)
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        nodes = conn.execute('SELECT * FROM nodes').fetchall()
        inbounds = get_all_inbounds([dict(n) for n in nodes])
        
        # Apply filters
        if protocol:
            inbounds = [ib for ib in inbounds if ib['protocol'] == protocol]
        if security:
            inbounds = [ib for ib in inbounds if ib['security'] == security]
        
        return JSONResponse(
            content={"inbounds": inbounds, "count": len(inbounds)},
            headers={"Cache-Control": "private, max-age=300"},
        )


@app.post("/api/v1/inbounds")
async def add_inbound(request: Request, config: Dict):
    """Добавить инбаунд на один или несколько узлов"""
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401)
    
    # Get nodes to add to
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        nodes = [dict(n) for n in conn.execute('SELECT * FROM nodes').fetchall()]
    
    results = []
    for n in nodes:
        success = inbound_mgr.add_inbound(n, config)
        results.append({"node": n['name'], "success": success})
    
    return {"results": results}


@app.post("/api/v1/inbounds/clone")
async def clone_inbound(request: Request, data: Dict):
    """Клонировать инбаунд с одного узла на другие
    
    Payload:
    {
        "source_node_id": 1,
        "source_inbound_id": 2,
        "target_node_ids": [2, 3],  // или null для всех кроме источника
        "modifications": {
            "remark": "Cloned Inbound",
            "port": 8443  // опционально
        }
    }
    """
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401)
    
    source_node_id = data.get("source_node_id")
    source_inbound_id = data.get("source_inbound_id")
    target_node_ids = data.get("target_node_ids")
    modifications = data.get("modifications", {})
    
    if not source_node_id or not source_inbound_id:
        raise HTTPException(status_code=400, detail="source_node_id and source_inbound_id required")
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        
        source_node = conn.execute('SELECT * FROM nodes WHERE id = ?', (source_node_id,)).fetchone()
        if not source_node:
            raise HTTPException(status_code=404, detail="Source node not found")
        source_node = dict(source_node)
        
        if target_node_ids:
            placeholders = ','.join('?' * len(target_node_ids))
            target_nodes = [dict(n) for n in conn.execute(f'SELECT * FROM nodes WHERE id IN ({placeholders})', target_node_ids).fetchall()]
        else:
            # Все узлы кроме источника
            target_nodes = [dict(n) for n in conn.execute('SELECT * FROM nodes WHERE id != ?', (source_node_id,)).fetchall()]
    
    result = inbound_mgr.clone_inbound(source_node, source_inbound_id, target_nodes, modifications)
    return result


@app.delete("/api/v1/inbounds/{inbound_id}")
async def delete_inbound(request: Request, inbound_id: int, node_id: int):
    """Удалить инбаунд с узла"""
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401)
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        node = conn.execute('SELECT * FROM nodes WHERE id = ?', (node_id,)).fetchone()
        if not node:
            raise HTTPException(status_code=404, detail="Node not found")
        node = dict(node)
    
    success = inbound_mgr.delete_inbound(node, inbound_id)
    return {"success": success}


@app.post("/api/v1/inbounds/batch-enable")
async def batch_enable_inbounds(request: Request, data: Dict):
    """Массово включить/выключить инбаунды
    
    Payload:
    {
        "node_ids": [1, 2],  // или null для всех
        "inbound_ids": [1, 2, 3],
        "enable": true
    }
    """
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401)
    
    node_ids = data.get("node_ids")
    inbound_ids = data.get("inbound_ids", [])
    enable = data.get("enable", True)
    
    if not inbound_ids:
        raise HTTPException(status_code=400, detail="inbound_ids required")
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if node_ids:
            placeholders = ','.join('?' * len(node_ids))
            nodes = [dict(n) for n in conn.execute(f'SELECT * FROM nodes WHERE id IN ({placeholders})', node_ids).fetchall()]
        else:
            nodes = [dict(n) for n in conn.execute('SELECT * FROM nodes').fetchall()]
    
    result = inbound_mgr.batch_enable_inbounds(nodes, inbound_ids, enable)
    
    # Broadcast WebSocket update
    await ws_manager.broadcast_inbound_update({
        "action": "batch_enable",
        "result": result
    })
    
    return result


@app.post("/api/v1/inbounds/batch-update")
async def batch_update_inbounds(request: Request, data: Dict):
    """Массово обновить инбаунды
    
    Payload:
    {
        "node_ids": [1, 2],  // или null для всех
        "inbound_ids": [1, 2, 3],
        "updates": {
            "remark": "New Remark",
            "enable": true
        }
    }
    """
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401)
    
    node_ids = data.get("node_ids")
    inbound_ids = data.get("inbound_ids", [])
    updates = data.get("updates", {})
    
    if not inbound_ids:
        raise HTTPException(status_code=400, detail="inbound_ids required")
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if node_ids:
            placeholders = ','.join('?' * len(node_ids))
            nodes = [dict(n) for n in conn.execute(f'SELECT * FROM nodes WHERE id IN ({placeholders})', node_ids).fetchall()]
        else:
            nodes = [dict(n) for n in conn.execute('SELECT * FROM nodes').fetchall()]
    
    result = inbound_mgr.batch_update_inbounds(nodes, inbound_ids, updates)
    
    # Broadcast WebSocket update
    await ws_manager.broadcast_inbound_update({
        "action": "batch_update",
        "result": result
    })
    
    return result


@app.post("/api/v1/inbounds/batch-delete")
async def batch_delete_inbounds(request: Request, data: Dict):
    """Массово удалить инбаунды
    
    Payload:
    {
        "node_ids": [1, 2],  // или null для всех
        "inbound_ids": [1, 2, 3]
    }
    """
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401)
    
    node_ids = data.get("node_ids")
    inbound_ids = data.get("inbound_ids", [])
    
    if not inbound_ids:
        raise HTTPException(status_code=400, detail="inbound_ids required")
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if node_ids:
            placeholders = ','.join('?' * len(node_ids))
            nodes = [dict(n) for n in conn.execute(f'SELECT * FROM nodes WHERE id IN ({placeholders})', node_ids).fetchall()]
        else:
            nodes = [dict(n) for n in conn.execute('SELECT * FROM nodes').fetchall()]
    
    result = inbound_mgr.batch_delete_inbounds(nodes, inbound_ids)
    
    # Broadcast WebSocket update
    await ws_manager.broadcast_inbound_update({
        "action": "batch_delete",
        "result": result
    })
    
    return result


# === Clients Management API ===


@app.get("/api/v1/clients")
async def list_clients(request: Request, email: Optional[str] = None):
    """Получить список всех клиентов с фильтрацией"""
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401)
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        nodes = [dict(n) for n in conn.execute('SELECT * FROM nodes').fetchall()]

    clients = get_cached_clients(nodes, email_filter=email)
    return JSONResponse(
        content={"clients": clients, "count": len(clients)},
        headers={"Cache-Control": "private, max-age=180"},
    )


@app.post("/api/v1/clients/batch-add")
async def batch_add_clients(request: Request, data: Dict):
    """Массово добавить клиентов на узлы
    
    Payload:
    {
        "node_ids": [1, 2, 3],  // ID узлов или null для всех
        "clients": [
            {
                "email": "user@example.com",
                "inbound_id": 1,  // или "inbound_remark": "My Inbound"
                "totalGB": 100,
                "expiryTime": 1735689600000,
                "enable": true
            }
        ]
    }
    """
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401)
    
    node_ids = data.get("node_ids")
    clients_configs = data.get("clients", [])
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if node_ids:
            placeholders = ','.join('?' * len(node_ids))
            nodes = [dict(n) for n in conn.execute(f'SELECT * FROM nodes WHERE id IN ({placeholders})', node_ids).fetchall()]
        else:
            nodes = [dict(n) for n in conn.execute('SELECT * FROM nodes').fetchall()]
    
    results = client_mgr.batch_add_clients(nodes, clients_configs)
    return results


@app.post("/api/v1/clients/add-to-nodes")
async def add_client_to_nodes(request: Request, data: Dict):
    """Добавить одного клиента на несколько узлов с автогенерацией UUID и subId=email.

    Payload:
    {
        "email": "user@example.com",
        "flow": "",                      // "", "xtls-rprx-vision", "xtls-rprx-vision-udp443"
        "inbound_id": 1,
        "totalGB": 0,
        "expiryTime": 0,
        "enable": true,
        "node_ids": [1, 2, 3]           // null или отсутствует = все серверы
    }
    """
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401)

    email = data.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="email is required")

    inbound_id = data.get("inbound_id")
    if inbound_id is None:
        raise HTTPException(status_code=400, detail="inbound_id is required")

    flow = data.get("flow", "")
    totalGB = data.get("totalGB", 0)
    expiryTime = data.get("expiryTime", 0)
    enable = data.get("enable", True)
    node_ids = data.get("node_ids")

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if node_ids:
            placeholders = ','.join('?' * len(node_ids))
            nodes = [dict(n) for n in conn.execute(
                f'SELECT * FROM nodes WHERE id IN ({placeholders})', node_ids
            ).fetchall()]
        else:
            nodes = [dict(n) for n in conn.execute('SELECT * FROM nodes').fetchall()]

    try:
        results = client_mgr.add_client_to_multiple_nodes(
            nodes=nodes,
            email=email,
            inbound_id=inbound_id,
            flow=flow,
            totalGB=totalGB,
            expiryTime=expiryTime,
            enable=enable,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return results


@app.put("/api/v1/clients/{client_uuid}")
async def update_client(request: Request, client_uuid: str, data: Dict):
    """Обновить параметры клиента
    
    Payload:
    {
        "node_id": 1,
        "inbound_id": 1,
        "updates": {
            "email": "newemail@example.com",
            "enable": false,
            "totalGB": 200
        }
    }
    """
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401)
    
    node_id = data.get("node_id")
    inbound_id = data.get("inbound_id")
    updates = data.get("updates", {})
    
    if not node_id or not inbound_id:
        raise HTTPException(status_code=400, detail="node_id and inbound_id required")
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        node = conn.execute('SELECT * FROM nodes WHERE id = ?', (node_id,)).fetchone()
        if not node:
            raise HTTPException(status_code=404, detail="Node not found")
        node = dict(node)
    
    success = client_mgr.update_client(node, inbound_id, client_uuid, updates)
    return {"success": success}


@app.delete("/api/v1/clients/{client_uuid}")
async def delete_client(request: Request, client_uuid: str, node_id: int, inbound_id: int):
    """Удалить клиента"""
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401)
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        node = conn.execute('SELECT * FROM nodes WHERE id = ?', (node_id,)).fetchone()
        if not node:
            raise HTTPException(status_code=404, detail="Node not found")
        node = dict(node)
    
    success = client_mgr.delete_client(node, inbound_id, client_uuid)
    return {"success": success}


@app.post("/api/v1/clients/batch-delete")
async def batch_delete_clients(request: Request, data: Dict):
    """Массово удалить клиентов с фильтрами
    
    Payload:
    {
        "node_ids": [1, 2],  // или null для всех узлов
        "email_pattern": "test",  // опционально
        "expired_only": false,
        "depleted_only": false
    }
    """
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401)
    
    node_ids = data.get("node_ids")
    email_pattern = data.get("email_pattern")
    expired_only = data.get("expired_only", False)
    depleted_only = data.get("depleted_only", False)
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if node_ids:
            placeholders = ','.join('?' * len(node_ids))
            nodes = [dict(n) for n in conn.execute(f'SELECT * FROM nodes WHERE id IN ({placeholders})', node_ids).fetchall()]
        else:
            nodes = [dict(n) for n in conn.execute('SELECT * FROM nodes').fetchall()]
    
    results = client_mgr.batch_delete_clients(nodes, email_pattern, expired_only, depleted_only)
    return results


@app.post("/api/v1/clients/{client_uuid}/reset-traffic")
async def reset_client_traffic(request: Request, client_uuid: str, data: Dict):
    """Сбросить трафик клиента
    
    Payload:
    {
        "node_id": 1,
        "inbound_id": 1,
        "email": "user@example.com"
    }
    """
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401)
    
    node_id = data.get("node_id")
    inbound_id = data.get("inbound_id")
    email = data.get("email")
    
    if not all([node_id, inbound_id, email]):
        raise HTTPException(status_code=400, detail="node_id, inbound_id, and email required")
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        node = conn.execute('SELECT * FROM nodes WHERE id = ?', (node_id,)).fetchone()
        if not node:
            raise HTTPException(status_code=404, detail="Node not found")
        node = dict(node)
    
    success = client_mgr.reset_client_traffic(node, inbound_id, email)
    return {"success": success}


# === Automation API ===


@app.post("/api/v1/automation/reset-all-traffic")
async def reset_all_traffic(request: Request, data: Dict):
    """Сбросить весь трафик на узлах
    
    Payload:
    {
        "node_ids": [1, 2],  // или null для всех
        "inbound_id": 1  // опционально, для сброса только одного инбаунда
    }
    """
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401)
    
    node_ids = data.get("node_ids")
    inbound_id = data.get("inbound_id")
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if node_ids:
            placeholders = ','.join('?' * len(node_ids))
            nodes = [dict(n) for n in conn.execute(f'SELECT * FROM nodes WHERE id IN ({placeholders})', node_ids).fetchall()]
        else:
            nodes = [dict(n) for n in conn.execute('SELECT * FROM nodes').fetchall()]
    
    results = client_mgr.reset_all_traffic(nodes, inbound_id)
    return results


# === Server Monitoring API ===


@app.get("/api/v1/servers/status")
async def get_servers_status(request: Request):
    """Получить статус всех серверов (CPU, RAM, диск, Xray)"""
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401)
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        nodes = [dict(n) for n in conn.execute('SELECT * FROM nodes').fetchall()]
    
    statuses = server_monitor.get_all_servers_status(nodes)
    return {"servers": statuses, "count": len(statuses)}


@app.get("/api/v1/servers/{node_id}/status")
async def get_server_status(request: Request, node_id: int):
    """Получить детальный статус конкретного сервера"""
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401)
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        node = conn.execute('SELECT * FROM nodes WHERE id = ?', (node_id,)).fetchone()
        if not node:
            raise HTTPException(status_code=404, detail="Node not found")
        node = dict(node)
    
    status = server_monitor.get_server_status(node)
    return status


@app.get("/api/v1/servers/availability")
async def check_servers_availability(request: Request):
    """Проверить доступность всех серверов (ping + latency)"""
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401)
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        nodes = [dict(n) for n in conn.execute('SELECT * FROM nodes').fetchall()]
    
    availability = []
    for node in nodes:
        av = server_monitor.check_server_availability(node)
        availability.append(av)
    
    return {"availability": availability}


@app.post("/api/v1/servers/{node_id}/restart-xray")
async def restart_xray_on_server(request: Request, node_id: int):
    """Перезапустить Xray на сервере"""
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401)
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        node = conn.execute('SELECT * FROM nodes WHERE id = ?', (node_id,)).fetchone()
        if not node:
            raise HTTPException(status_code=404, detail="Node not found")
        node = dict(node)
    
    success = server_monitor.restart_xray(node)
    return {"success": success}


@app.get("/api/v1/servers/{node_id}/logs")
async def get_server_logs(request: Request, node_id: int, count: int = 100, level: str = "info"):
    """Получить логи с сервера
    
    Query params:
        count: Количество строк (по умолчанию 100)
        level: Уровень логов (debug, info, warning, error)
    """
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401)
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        node = conn.execute('SELECT * FROM nodes WHERE id = ?', (node_id,)).fetchone()
        if not node:
            raise HTTPException(status_code=404, detail="Node not found")
        node = dict(node)
    
    logs = server_monitor.get_server_logs(node, count, level)
    return logs


# === Backup/Restore API ===


@app.get("/api/v1/backup/database/{node_id}")
async def get_database_backup(request: Request, node_id: int):
    """Получить резервную копию базы данных с сервера"""
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401)
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        node = conn.execute('SELECT * FROM nodes WHERE id = ?', (node_id,)).fetchone()
        if not node:
            raise HTTPException(status_code=404, detail="Node not found")
        node = dict(node)
    
    backup = server_monitor.get_database_backup(node)
    return backup


@app.post("/api/v1/backup/database/{node_id}")
async def import_database_backup(request: Request, node_id: int, data: Dict):
    """Импортировать резервную копию базы данных на сервер
    
    Payload:
    {
        "backup_data": "base64 или SQL данные"
    }
    """
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401)
    
    backup_data = data.get("backup_data")
    if not backup_data:
        raise HTTPException(status_code=400, detail="backup_data required")
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        node = conn.execute('SELECT * FROM nodes WHERE id = ?', (node_id,)).fetchone()
        if not node:
            raise HTTPException(status_code=404, detail="Node not found")
        node = dict(node)
    
    success = server_monitor.import_database_backup(node, backup_data)
    return {"success": success}


@app.get("/api/v1/backup/all")
async def get_all_databases_backup(request: Request):
    """Получить резервные копии баз данных со всех серверов"""
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401)
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        nodes = [dict(n) for n in conn.execute('SELECT * FROM nodes').fetchall()]
    
    backups = []
    for node in nodes:
        backup = server_monitor.get_database_backup(node)
        backups.append(backup)
    
    return {"backups": backups, "count": len(backups)}


# === Per-node 3x-UI API endpoints ===


def _get_node_or_404(node_id: int) -> Dict:
    """Вспомогательная функция: получить узел по ID или выбросить 404."""
    node = node_service.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return node


@app.get("/api/v1/history/nodes/{node_id}")
async def node_history(request: Request, node_id: int, since_sec: int = 86400, limit: int = 2000):
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401)
    if since_sec < 60:
        since_sec = 60
    if since_sec > 30 * 86400:
        since_sec = 30 * 86400
    if limit < 100:
        limit = 100
    if limit > 5000:
        limit = 5000

    _get_node_or_404(node_id)
    ts_from = int(time.time()) - since_sec
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT ts, node_id, node_name, available, xray_running, cpu, online_clients, traffic_total, poll_ms
            FROM node_history
            WHERE node_id = ? AND ts >= ?
            ORDER BY ts DESC
            LIMIT ?
            """,
            (node_id, ts_from, limit),
        ).fetchall()

    points = [dict(r) for r in reversed(rows)]
    return {"node_id": node_id, "since_sec": since_sec, "count": len(points), "points": points}


app.include_router(
    build_live_data_router(
        get_node_or_404=_get_node_or_404,
        get_cached_traffic_stats=get_cached_traffic_stats,
        get_cached_online_clients=get_cached_online_clients,
        list_nodes=node_service.list_nodes,
        xui_monitor=xui_monitor,
    )
)


# === WebSocket API ===


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint для real-time обновлений"""
    user = check_basic_auth_header(websocket.headers.get("Authorization"))
    if not user:
        token = websocket.query_params.get("token")
        if token:
            try:
                decoded = base64.b64decode(token).decode("utf-8")
                username, password = decoded.split(":", 1)
                if p.authenticate(username, password):
                    user = username
            except Exception:
                user = None
    if not user:
        await websocket.close(code=1008)
        return
    ws_totp_code = websocket.query_params.get("totp") or websocket.headers.get("X-TOTP-Code")
    # Practical default: keep MFA strict for HTTP API, but do not hard-fail WS reconnects
    # unless explicitly enabled via MFA_TOTP_WS_STRICT=true.
    if MFA_TOTP_WS_STRICT:
        if not verify_totp_code(user, ws_totp_code):
            await websocket.close(code=1008)
            return
    elif ws_totp_code:
        # If client provided a TOTP, validate it; if absent, allow WS auth by Basic token.
        if not verify_totp_code(user, ws_totp_code):
            await websocket.close(code=1008)
            return
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            await handle_websocket_message(websocket, data)
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        ws_manager.disconnect(websocket)


@app.on_event("startup")
async def startup_event():
    """Запустить background tasks при старте приложения"""
    global audit_worker_task
    await asyncio.to_thread(sync_node_history_names_with_nodes)
    audit_worker_task = asyncio.create_task(audit_worker_loop())
    await snapshot_collector.start()


@app.on_event("shutdown")
async def shutdown_event():
    global audit_worker_task
    if audit_worker_task:
        audit_worker_task.cancel()
        try:
            await audit_worker_task
        except asyncio.CancelledError:
            pass
        audit_worker_task = None
    await snapshot_collector.stop()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("APP_PORT", "666")))
