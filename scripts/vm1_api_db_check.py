import base64
import json
import sqlite3
import urllib.error
import urllib.request

BASE = 'http://127.0.0.1:666'
AUTH = 'Basic ' + base64.b64encode(b'apitest:ApiTest123').decode('ascii')


def call(method: str, path: str, payload: dict | None = None):
    data = None
    headers = {'Authorization': AUTH}
    if payload is not None:
        data = json.dumps(payload).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', errors='replace')


print('=== PRE GET /api/v1/nodes ===')
s, b = call('GET', '/api/v1/nodes')
print('status=', s)
try:
    pre_nodes = json.loads(b)
    print('count=', len(pre_nodes))
except Exception:
    pre_nodes = []
    print('body=', b)

cases = [
    {'name': 'qa-explicit-8443', 'url': 'https://10.10.10.10:8443/panel', 'user': 'u1', 'password': 'p1'},
    {'name': 'qa-http-no-port', 'url': 'http://10.20.30.40/panel', 'user': 'u2', 'password': 'p2'},
    {'name': 'qa-no-scheme-no-port', 'url': '10.30.40.50/panel', 'user': 'u3', 'password': 'p3'},
]

print('\n=== POST /api/v1/nodes ===')
for payload in cases:
    s, b = call('POST', '/api/v1/nodes', payload)
    print(payload['name'], 'status=', s, 'body=', b)

print('\n=== GET /api/v1/nodes (qa-*) ===')
s, b = call('GET', '/api/v1/nodes')
print('status=', s)
try:
    nodes = json.loads(b)
except Exception:
    nodes = []
qa_nodes = [n for n in nodes if str(n.get('name', '')).startswith('qa-')]
print(json.dumps(qa_nodes, ensure_ascii=False))

print('\n=== DB rows (qa-*) ===')
conn = sqlite3.connect('/opt/sub-manager/admin.db')
cur = conn.cursor()
cur.execute("SELECT id, name, ip, port, scheme, base_path, panel_url, username, user, read_only, verify_tls FROM nodes WHERE name LIKE 'qa-%' ORDER BY id")
for row in cur.fetchall():
    print(row)
conn.close()

print('\n=== check-connection self-signed probe ===')
probe = {'url': 'https://self-signed.badssl.com', 'user': 'dummy', 'password': 'dummy'}
s, b = call('POST', '/api/v1/nodes/check-connection', probe)
print('status=', s)
print('body=', b)
