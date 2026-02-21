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
from pathlib import Path
from typing import List, Dict, Optional
from fastapi import FastAPI, Request, HTTPException, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from urllib.parse import urlparse
import urllib3

# Локальный импорт crypto-модуля (для шифрования паролей)
import sys
sys.path.insert(0, str(Path(__file__).parent))
from crypto import encrypt, decrypt
from inbound_manager import InboundManager
from client_manager import ClientManager
from server_monitor import ServerMonitor
from websocket_manager import manager as ws_manager, handle_websocket_message

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = FastAPI(title="Multi-Server Sub Manager", version="3.0")

# CORS для локального development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Конфигурация
PROJECT_DIR = os.getenv("PROJECT_DIR", "/opt/sub-manager")
DB_PATH = os.path.join(PROJECT_DIR, "admin.db")
CACHE_TTL = int(os.getenv("CACHE_TTL", "30"))

p = pam.pam()
emails_cache = {"ts": 0.0, "emails": []}
links_cache = {}

# Инициализация менеджеров
inbound_mgr = InboundManager(decrypt_func=decrypt, encrypt_func=encrypt)
client_mgr = ClientManager(decrypt_func=decrypt, encrypt_func=encrypt)
server_monitor = ServerMonitor(decrypt_func=decrypt)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("sub_manager")


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
        
        conn.commit()


init_db()


def check_auth(request: Request) -> str:
    """Проверка Basic Auth через PAM"""
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return None
    try:
        scheme, credentials = auth_header.split()
        decoded = base64.b64decode(credentials).decode("utf-8")
        username, password = decoded.split(":", 1)
        if p.authenticate(username, password):
            return username
    except Exception as e:
        logger.warning(f"Auth error: {e}")
    return None


def fetch_inbounds(node: Dict) -> List[Dict]:
    """Получить список inbound'ов с node panel панели"""
    s = requests.Session()
    s.verify = False
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
    
    try:
        s.post(f"{base_url}/login", 
               data={"username": node['user'], "password": node_password}, 
               timeout=5)
        res = s.get(f"{base_url}/panel/api/inbounds/list", timeout=5)
        res.raise_for_status()
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
            try:
                clients = json.loads(ib.get("settings", "{}")).get("clients", [])
            except (TypeError, ValueError) as exc:
                logger.warning(f"Invalid settings JSON for node {n['name']}: {exc}")
                continue
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
            inbound = {
                "id": ib.get("id"),
                "node_name": n["name"],
                "node_ip": n["ip"],
                "protocol": ib.get("protocol"),
                "port": ib.get("port"),
                "remark": ib.get("remark", ""),
                "enable": ib.get("enable", True),
                "streamSettings": ib.get("streamSettings", {}),
                "settings": ib.get("settings", {})
            }
            security = ib.get("streamSettings", {}).get("security", "")
            inbound["security"] = security
            inbound["is_reality"] = security == "reality"
            inbounds.append(inbound)
    return inbounds


def add_inbound_to_node(node: Dict, inbound_config: Dict) -> bool:
    """Добавить инбаунд на узел node panel"""
    s = requests.Session()
    s.verify = False
    b_path = node["base_path"].strip("/")
    prefix = f"/{b_path}" if b_path else ""
    base_url = f"https://{node['ip']}:{node['port']}{prefix}"
    
    try:
        s.post(f"{base_url}/login", data={"username": node['user'], "password": decrypt(node.get('password', ''))})
        res = s.post(f"{base_url}/panel/api/inbounds/add", json=inbound_config, timeout=5)
        return res.status_code == 200
    except Exception as exc:
        logger.warning(f"Failed to add inbound to {node['name']}: {exc}")
    return False


def add_client_to_inbound(node: Dict, inbound_id: int, client_config: Dict) -> bool:
    """Добавить клиента в инбаунд"""
    s = requests.Session()
    s.verify = False
    b_path = node["base_path"].strip("/")
    prefix = f"/{b_path}" if b_path else ""
    base_url = f"https://{node['ip']}:{node['port']}{prefix}"
    
    try:
        s.post(f"{base_url}/login", data={"username": node['user'], "password": decrypt(node.get('password', ''))})
        payload = {"id": inbound_id, "settings": {"clients": [client_config]}}
        res = s.post(f"{base_url}/panel/api/inbounds/addClient", json=payload, timeout=5)
        return res.status_code == 200
    except Exception as exc:
        logger.warning(f"Failed to add client to {node['name']}: {exc}")
    return False


def delete_client_from_inbound(node: Dict, inbound_id: int, client_id: str) -> bool:
    """Удалить клиента из инбаунда"""
    s = requests.Session()
    s.verify = False
    b_path = node["base_path"].strip("/")
    prefix = f"/{b_path}" if b_path else ""
    base_url = f"https://{node['ip']}:{node['port']}{prefix}"
    
    try:
        s.post(f"{base_url}/login", data={"username": node['user'], "password": decrypt(node.get('password', ''))})
        res = s.post(f"{base_url}/panel/api/inbounds/{inbound_id}/delClient/{client_id}", timeout=5)
        return res.status_code == 200
    except Exception as exc:
        logger.warning(f"Failed to delete client from {node['name']}: {exc}")
    return False


def get_client_traffic(node: Dict, client_id: str, protocol: str) -> Dict:
    """Получить статистику клиента"""
    s = requests.Session()
    s.verify = False
    b_path = node["base_path"].strip("/")
    prefix = f"/{b_path}" if b_path else ""
    base_url = f"https://{node['ip']}:{node['port']}{prefix}"
    
    try:
        s.post(f"{base_url}/login", data={"username": node['user'], "password": decrypt(node.get('password', ''))})
        if protocol in ("vless", "vmess"):
            res = s.get(f"{base_url}/panel/api/inbounds/getClientTrafficsById/{client_id}", timeout=5)
        else:
            res = s.get(f"{base_url}/panel/api/inbounds/getClientTraffics/{client_id}", timeout=5)
        if res.status_code == 200:
            return res.json().get("obj", {})
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
                    
                    if security == "reality":
                        links.append(
                            f"vless://{c['id']}@{n['ip']}:443?encryption=none&security=reality"
                            f"&sni={sni}&fp={fp}&pbk={pbk}&sid={sid}"
                            f"&type={network}#{c['email']} ({n['name']})"
                        )
                    else:
                        links.append(
                            f"vless://{c['id']}@{n['ip']}:443?encryption=none&security=tls"
                            f"&sni={sni}&fp={fp}&type={network}#{c['email']} ({n['name']})"
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
                            f"&type={network}#{c['email']} ({n['name']})"
                        )
                    else:
                        sni = ((s_set.get('tlsSettings', {}) or {}).get('serverNames', [''] or [''])[0])
                        links.append(
                            f"trojan://{c['password']}@{n['ip']}:443?security=tls"
                            f"&sni={sni}&type={s_set.get('network','tcp')}#{c['email']} ({n['name']})"
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
                    
                    if security == "reality":
                        links.append(
                            f"vless://{c['id']}@{n['ip']}:443?encryption=none&security=reality"
                            f"&sni={sni}&fp={fp}&pbk={pbk}&sid={sid}"
                            f"&type={network}#{c['email']} ({n['name']})"
                        )
                    else:
                        links.append(
                            f"vless://{c['id']}@{n['ip']}:443?encryption=none&security=tls"
                            f"&sni={sni}&fp={fp}&type={network}#{c['email']} ({n['name']})"
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
                            f"&type={network}#{c['email']} ({n['name']})"
                        )
                    else:
                        sni = ((s_set.get('tlsSettings', {}) or {}).get('serverNames', [''] or [''])[0])
                        links.append(
                            f"trojan://{c['password']}@{n['ip']}:443?security=tls"
                            f"&sni={sni}&type={s_set.get('network','tcp')}#{c['email']} ({n['name']})"
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
    return {"user": user}


@app.get("/api/v1/nodes")
async def list_nodes(request: Request):
    """Получить список узлов"""
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        nodes = conn.execute('SELECT * FROM nodes').fetchall()
        # Расшифровываем пароли
        result = []
        for n in nodes:
            node_dict = dict(n)
            if node_dict.get('password'):
                node_dict['password'] = decrypt(node_dict['password'])
            result.append(node_dict)
        return result


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
        
        return {
            "emails": emails,
            "stats": stats
        }


@app.get("/api/v1/sub/{email}")
async def get_sub(email: str, protocol: Optional[str] = None, nodes: Optional[str] = None):
    """Получить подписку для email'а (без авторизации)
    
    Query params:
    - protocol: фильтр по протоколу (vless, vmess, trojan)
    - nodes: список node names через запятую (node1,node2)
    """
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
async def get_sub_grouped(identifier: str, protocol: Optional[str] = None, nodes: Optional[str] = None):
    """Получить групповую подписку (по части email или имени)
    
    Примеры:
    - /api/v1/sub-grouped/company - все email содержащие 'company'
    - /api/v1/sub-grouped/user1 - все email содержащие 'user1'
    """
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
        
        return {"inbounds": inbounds, "count": len(inbounds)}


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
        
    clients = client_mgr.get_all_clients(nodes, email_filter=email)
    return {"clients": clients, "count": len(clients)}


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


# === Traffic Statistics API ===


@app.get("/api/v1/traffic/stats")
async def get_traffic_stats(request: Request, group_by: str = "client"):
    """Получить агрегированную статистику трафика
    
    Query params:
        group_by: client, inbound, или node
    """
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401)
    
    if group_by not in ["client", "inbound", "node"]:
        raise HTTPException(status_code=400, detail="group_by must be client, inbound, or node")
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        nodes = [dict(n) for n in conn.execute('SELECT * FROM nodes').fetchall()]
    
    stats = client_mgr.get_traffic_stats(nodes, group_by)
    return stats


@app.get("/api/v1/clients/online")
async def get_online_clients(request: Request):
    """Получить список онлайн клиентов"""
    user = check_auth(request)
    if not user:
        raise HTTPException(status_code=401)
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        nodes = [dict(n) for n in conn.execute('SELECT * FROM nodes').fetchall()]
    
    online = client_mgr.get_online_clients(nodes)
    return {"online_clients": online, "count": len(online)}


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


# === WebSocket API ===


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint для real-time обновлений"""
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


# Background task для периодической отправки обновлений
async def broadcast_updates():
    """Периодически отправлять обновления через WebSocket"""
    while True:
        try:
            await asyncio.sleep(5)  # Каждые 5 секунд
            
            # Получаем данные для всех подключенных клиентов
            if len(ws_manager.active_connections) > 0:
                with sqlite3.connect(DB_PATH) as conn:
                    conn.row_factory = sqlite3.Row
                    nodes = [dict(n) for n in conn.execute('SELECT * FROM nodes').fetchall()]
                
                # Server status update
                if any("server_status" in ws_manager.subscriptions.get(conn, set()) 
                       for conn in ws_manager.active_connections):
                    statuses = server_monitor.get_all_servers_status(nodes)
                    await ws_manager.broadcast_server_status({"servers": statuses})
                
                # Traffic update
                if any("traffic" in ws_manager.subscriptions.get(conn, set()) 
                       for conn in ws_manager.active_connections):
                    stats = client_mgr.get_traffic_stats(nodes, "client")
                    await ws_manager.broadcast_traffic_update(stats)
                
        except Exception as e:
            logger.error(f"Broadcast updates error: {e}")
            await asyncio.sleep(5)


@app.on_event("startup")
async def startup_event():
    """Запустить background tasks при старте приложения"""
    asyncio.create_task(broadcast_updates())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("APP_PORT", "666")))
