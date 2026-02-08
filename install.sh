#!/bin/bash

# --- КОНФИГУРАЦИЯ ---
LOG_FILE="/opt/.sub_manager_install.log"

uninstall() {
    echo -e "\n--- Удаление и откат настроек ---"
    if [ ! -f "$LOG_FILE" ]; then echo "❌ Лог не найден."; return 1; fi
    source "$LOG_FILE"
    systemctl stop "$PROJECT_NAME" 2>/dev/null
    systemctl disable "$PROJECT_NAME" 2>/dev/null
    rm -f "/etc/systemd/system/$PROJECT_NAME.service"
    rm -f "/etc/fail2ban/jail.d/multi-manager.local"
    rm -f "/etc/fail2ban/filter.d/multi-manager.conf"
    systemctl daemon-reload
    systemctl restart fail2ban
    if [ -f "${SELECTED_CFG}.bak" ]; then
        mv "${SELECTED_CFG}.bak" "$SELECTED_CFG"
        nginx -t && systemctl restart nginx
    fi
    rm -rf "$PROJECT_DIR" "$HTML_DIR" "$LOG_FILE"
    echo "✅ Система полностью очищена."
}

if [ -f "$LOG_FILE" ]; then
    source "$LOG_FILE"
    clear
    echo "ОБНАРУЖЕНА УСТАНОВКА: $PROJECT_NAME"
    echo "1) Удалить 2) Переустановить 3) Выход"
    read -p "Выбор: " choice
    case $choice in
        1) uninstall; exit 0 ;;
        2) uninstall ;;
        *) exit 0 ;;
    esac
fi

if [ "$EUID" -ne 0 ]; then echo "Запустите от root!"; exit; fi

clear
echo "======================================================"
echo "    MULTI-SERVER MANAGER INSTALLER (v2.1 - 2026)"
echo "======================================================"

read -p "Имя проекта/сервиса (sub-manager): " PROJECT_NAME
PROJECT_NAME=${PROJECT_NAME:-sub-manager}
read -p "Локальный порт Python (666): " APP_PORT
APP_PORT=${APP_PORT:-666}
read -p "Путь в браузере (my-vpn): " WEB_PATH
WEB_PATH=${WEB_PATH:-my-vpn}
WEB_PATH=$(echo $WEB_PATH | sed 's/\///g') # Убираем слэши если пользователь ввел их

PROJECT_DIR="/opt/$PROJECT_NAME"
HTML_DIR="/var/www/$PROJECT_NAME"

echo -e "\nВыберите конфиг Nginx из списка:"
configs=( /etc/nginx/sites-available/* )
for i in "${!configs[@]}"; do echo "$i) $(basename "${configs[$i]}")"; done
read -p "Введите номер: " cfg_idx
SELECTED_CFG="${configs[$cfg_idx]}"

# Сохранение параметров
cat <<EOF > "$LOG_FILE"
PROJECT_NAME="$PROJECT_NAME"
PROJECT_DIR="$PROJECT_DIR"
HTML_DIR="$HTML_DIR"
SELECTED_CFG="$SELECTED_CFG"
APP_PORT="$APP_PORT"
WEB_PATH="$WEB_PATH"
EOF

cp "$SELECTED_CFG" "${SELECTED_CFG}.bak"

echo "Установка системных пакетов и Python-библиотек..."
apt update && apt install -y python3-pip libpam0g-dev fail2ban python3-venv sqlite3 nginx psmisc
mkdir -p "$PROJECT_DIR" "$HTML_DIR"

# Создание VENV и установка зависимостей
python3 -m venv "$PROJECT_DIR/venv"
"$PROJECT_DIR/venv/bin/pip" install fastapi uvicorn requests python-pam six jinja2 python-multipart urllib3

# --- ГЕНЕРАЦИЯ MAIN.PY ---
cat <<EOF > "$PROJECT_DIR/main.py"
import sqlite3, requests, json, base64, pam, datetime, os, logging, time
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from urllib.parse import urlparse
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = FastAPI()
templates = Jinja2Templates(directory="$HTML_DIR")
p = pam.pam()
DB_PATH = os.path.join('$PROJECT_DIR', 'admin.db')
CACHE_TTL = 30
emails_cache = {"ts": 0.0, "emails": []}
links_cache = {}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("sub_manager")

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS nodes 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, ip TEXT, port TEXT, 
                      user TEXT, password TEXT, base_path TEXT DEFAULT '')''')
        try: conn.execute('ALTER TABLE nodes ADD COLUMN base_path TEXT DEFAULT ""')
        except: pass
        conn.execute('CREATE TABLE IF NOT EXISTS stats (email TEXT PRIMARY KEY, count INTEGER DEFAULT 0, last_download TEXT)')
init_db()

def check_auth(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header: return None
    try:
        scheme, credentials = auth_header.split()
        decoded = base64.b64decode(credentials).decode("utf-8")
        username, password = decoded.split(":")
        if p.authenticate(username, password): return username
    except: pass
    return None

def fetch_inbounds(node):
    s = requests.Session(); s.verify = False
    b_path = node['base_path'].strip('/')
    prefix = f"/{b_path}" if b_path else ""
    base_url = f"https://{node['ip']}:{node['port']}{prefix}"
    try:
        s.post(f"{base_url}/login", data={"username": node['user'], "password": node['password']}, timeout=5)
        res = s.get(f"{base_url}/panel/api/inbounds/list", timeout=5)
        res.raise_for_status()
        data = res.json()
        if not data.get("success"):
            logger.warning("3X-UI %s returned success=false", node['name'])
            return []
        return data.get("obj", [])
    except requests.RequestException as exc:
        logger.warning("3X-UI %s request failed: %s", node['name'], exc)
    except ValueError as exc:
        logger.warning("3X-UI %s invalid JSON: %s", node['name'], exc)
    return []

def get_emails(nodes):
    now = time.time()
    if now - emails_cache["ts"] < CACHE_TTL:
        return emails_cache["emails"]
    emails = set()
    for n in nodes:
        for ib in fetch_inbounds(n):
            try:
                clients = json.loads(ib.get("settings", "{}")).get("clients", [])
            except (TypeError, ValueError) as exc:
                logger.warning("Invalid settings JSON for node %s: %s", n['name'], exc)
                continue
            for c in clients:
                if c.get("email"):
                    emails.add(c.get("email"))
    emails_list = sorted(list(emails))
    emails_cache.update({"ts": now, "emails": emails_list})
    return emails_list

def get_links(nodes, email):
    now = time.time()
    cached = links_cache.get(email)
    if cached and now - cached[0] < CACHE_TTL:
        return cached[1]
    links = []
    for n in nodes:
        for ib in fetch_inbounds(n):
            if ib.get("protocol") != "vless":
                continue
            try:
                s_set = json.loads(ib.get("streamSettings", "{}"))
            except (TypeError, ValueError) as exc:
                logger.warning("Invalid streamSettings JSON for node %s: %s", n['name'], exc)
                continue
            if s_set.get("security") != "reality":
                continue
            try:
                settings = json.loads(ib.get("settings", "{}"))
            except (TypeError, ValueError) as exc:
                logger.warning("Invalid settings JSON for node %s: %s", n['name'], exc)
                continue
            for c in settings.get("clients", []):
                if c.get("email") != email:
                    continue
                r = s_set.get('realitySettings', {})
                pbk = r.get('settings', {}).get('publicKey', '')
                sid = r.get('shortIds', [''])[0] if r.get('shortIds') else ''
                sni = (r.get('serverNames') or [''])[0]
                links.append(
                    f"vless://{c['id']}@{n['ip']}:443?encryption=none&security=reality"
                    f"&sni={sni}&fp={r.get('fingerprint','chrome')}&pbk={pbk}&sid={sid}"
                    f"&type={s_set.get('network','tcp')}#{c['email']} ({n['name']})"
                )
    links_cache[email] = (now, links)
    return links

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    user = check_auth(request)
    if not user: raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Basic"})
    
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    nodes = conn.execute('SELECT * FROM nodes').fetchall()
    stats = {r['email']: {"count": r['count'], "last": r['last_download']} for r in conn.execute('SELECT * FROM stats').fetchall()}
    emails = get_emails(nodes)

    return templates.TemplateResponse("index.html", {
        "request": request, "nodes": nodes, "emails": emails, 
        "stats": stats, "user": user, "web_path": "$WEB_PATH"
    })

@app.post("/add_node")
async def add_node(request: Request, name=Form(...), url=Form(...), user=Form(...), password=Form(...)):
    if not check_auth(request): raise HTTPException(status_code=401)
    if not url.startswith(('http://', 'https://')): url = 'https://' + url
    parsed = urlparse(url)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('INSERT INTO nodes (name, ip, port, user, password, base_path) VALUES (?,?,?,?,?,?)', 
                     (name, parsed.hostname, str(parsed.port) if parsed.port else "443", user, password, parsed.path.strip('/')))
    emails_cache["ts"] = 0
    links_cache.clear()
    return RedirectResponse(url="./", status_code=303)

@app.get("/sub/{email}")
async def sub(email: str):
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    nodes = conn.execute('SELECT * FROM nodes').fetchall()
    links = get_links(nodes, email)
    if links:
        now = datetime.datetime.now().strftime("%d.%m %H:%M")
        with sqlite3.connect(DB_PATH) as db:
            db.execute('INSERT INTO stats (email, count, last_download) VALUES (?, 1, ?) ON CONFLICT(email) DO UPDATE SET count=count+1, last_download=?', (email, now, now))
        return PlainTextResponse(content=base64.b64encode("\n".join(links).encode()).decode())
    return PlainTextResponse(content="Not found", status_code=404)

@app.get("/delete_node/{id}")
async def del_node(request: Request, id: int):
    if not check_auth(request): raise HTTPException(status_code=401)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('DELETE FROM nodes WHERE id = ?', (id,))
    emails_cache["ts"] = 0
    links_cache.clear()
    return RedirectResponse(url="../", status_code=303)
EOF

# --- ГЕНЕРАЦИЯ INDEX.HTML ---
cat <<EOF > "$HTML_DIR/index.html"
<!DOCTYPE html>
<html lang="ru" data-bs-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <title>VPN Sub Manager</title>
    <style>
        body { background-color: #0d1117; color: #c9d1d9; font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif; }
        .card { background-color: #161b22; border: 1px solid #30363d; }
        .table { color: #c9d1d9; border-color: #30363d; }
        .form-control { background-color: #0d1117; border: 1px solid #30363d; color: #fff; }
        .form-control:focus { background-color: #0d1117; border-color: #58a6ff; color: #fff; box-shadow: none; }
    </style>
</head>
<body class="container py-4">
    <div class="d-flex justify-content-between align-items-center mb-4 border-bottom border-secondary pb-3">
        <h4>📡 Multi-Server Manager</h4>
        <span class="badge bg-outline-secondary border text-secondary">Admin: {{ user }}</span>
    </div>

    <div class="card p-3 mb-4 shadow-sm">
        <h6 class="mb-3 text-primary">Добавить 3X-UI Панель</h6>
        <form action="./add_node" method="post" class="row g-2 small">
            <div class="col-md-2"><input type="text" name="name" class="form-control" placeholder="Метка (напр. NL)" required></div>
            <div class="col-md-4"><input type="text" name="url" class="form-control" placeholder="https://ip:port/path/" required></div>
            <div class="col-md-2"><input type="text" name="user" class="form-control" placeholder="Логин" required></div>
            <div class="col-md-2"><input type="password" name="password" class="form-control" placeholder="Пароль" required></div>
            <div class="col-md-2"><button class="btn btn-primary w-100">Добавить</button></div>
        </form>
    </div>

    <div class="row">
        <div class="col-md-4">
            <div class="card p-3 mb-4">
                <h6 class="text-secondary mb-3">Список узлов</h6>
                {% for n in nodes %}
                <div class="d-flex justify-content-between align-items-center mb-2 p-2 border-bottom border-secondary">
                    <div><strong>{{ n.name }}</strong><br><small class="text-secondary">{{ n.ip }}</small></div>
                    <a href="./delete_node/{{ n.id }}" class="btn btn-sm btn-outline-danger">×</a>
                </div>
                {% endfor %}
            </div>
        </div>
        <div class="col-md-8">
            <div class="card p-3">
                <h6 class="text-secondary">Управление подписками</h6>
                <table class="table table-hover mt-3 small">
                    <thead><tr><th>Email пользователя</th><th>Статистика</th><th>Ссылка (Base64)</th></tr></thead>
                    <tbody>
                        {% for e in emails %}
                        <tr>
                            <td class="align-middle"><strong>{{ e }}</strong></td>
                            <td class="align-middle text-nowrap">
                                <span class="badge bg-info text-dark">{{ stats[e].count if e in stats else 0 }}</span>
                                <div style="font-size:0.7rem" class="text-secondary mt-1">{{ stats[e].last if e in stats else '--' }}</div>
                            </td>
                            <td class="align-middle w-50">
                                <div class="input-group input-group-sm">
                                    <input type="text" id="link-{{ loop.index }}" class="form-control form-control-sm" readonly value="https://{{ request.headers.get('host') }}/{{ web_path }}/sub/{{ e }}">
                                    <button class="btn btn-outline-primary" onclick="copy('link-{{ loop.index }}')">Copy</button>
                                </div>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    <script>
        async function copy(id) {
            const copyText = document.getElementById(id);
            const text = copyText.value;
            try {
                await navigator.clipboard.writeText(text);
            } catch (err) {
                copyText.select();
                document.execCommand("copy");
            }
            const btn = document.querySelector('[onclick="copy(\''+id+'\')"]');
            const oldText = btn.innerText;
            btn.innerText = 'OK!';
            setTimeout(() => { btn.innerText = oldText; }, 1000);
        }
    </script>
</body>
</html>
EOF

# --- ЗАПУСК СЕРВИСА ---
cat <<EOF > "/etc/systemd/system/$PROJECT_NAME.service"
[Unit]
Description=$PROJECT_NAME Service
After=network.target

[Service]
User=root
WorkingDirectory=$PROJECT_DIR
ExecStartPre=/usr/bin/bash -c "/usr/bin/fuser -k $APP_PORT/tcp || true"
ExecStart=$PROJECT_DIR/venv/bin/uvicorn main:app --host 127.0.0.1 --port $APP_PORT
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now "$PROJECT_NAME.service"

# --- НАСТРОЙКА NGINX ---
# Очищаем старые записи именно этого пути
sed -i "/location .*\/$WEB_PATH/,/}/d" "$SELECTED_CFG"
# Вставляем новый блок
sed -i "/server_name/a \\
    location ^~ /$WEB_PATH/ {\\
        proxy_pass http://127.0.0.1:$APP_PORT/;\\
        proxy_set_header Host \$host;\\
        proxy_set_header X-Real-IP \$remote_addr;\\
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;\\
        proxy_set_header X-Forwarded-Proto \$scheme;\\
        proxy_intercept_errors off;\\
    }" "$SELECTED_CFG"

nginx -t && systemctl restart nginx

# --- FAIL2BAN ---
cat <<EOF > "/etc/fail2ban/filter.d/multi-manager.conf"
[Definition]
failregex = ^<HOST> -.*"GET .*$WEB_PATH/.*" (401|403)
EOF

cat <<EOF > "/etc/fail2ban/jail.d/multi-manager.local"
[multi-manager]
enabled  = true
port     = 0-65535
filter   = multi-manager
logpath  = /var/log/nginx/access.log
maxretry = 5
findtime = 600
bantime  = 300
EOF

systemctl restart fail2ban

echo -e "\n✅ УСТАНОВКА ЗАВЕРШЕНА!"
echo "🔗 Админка: https://$(hostname -f)/$WEB_PATH/"
