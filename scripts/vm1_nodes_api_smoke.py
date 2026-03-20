import base64
import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:666"
AUTH = "Basic " + base64.b64encode(b"apitest:ApiTest123").decode("ascii")


def call(path: str):
    req = urllib.request.Request(BASE + path, headers={"Authorization": AUTH}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, body
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return 0, str(exc)


paths = [
    "/api/v1/nodes",
    "/api/v1/nodes/list",
    "/api/v1/servers/status",
    "/api/v1/inbounds",
    "/api/v1/clients",
]

print("=== API smoke ===")
for p in paths:
    status, body = call(p)
    extra = ""
    if status == 200:
        try:
            data = json.loads(body)
            if isinstance(data, list):
                extra = f" len={len(data)}"
            elif isinstance(data, dict):
                extra = f" keys={len(data.keys())}"
        except Exception:
            extra = " body=non-json"
    print(f"{p} -> {status}{extra}")
