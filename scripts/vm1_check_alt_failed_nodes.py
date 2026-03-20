import base64
import json
import urllib.error
import urllib.request
import time

BASE = "http://127.0.0.1:666"
AUTH = "Basic " + base64.b64encode(b"apitest:ApiTest123").decode("ascii")

cases = [
    {
        "name": "vm1-3xui-current-runtime",
        "url": "https://vm1.kleva.ru/qJiLduiVnd/",
        "user": "pfgHpdpij5",
        "password": "ucJAppld8optEn",
    },
    {
        "name": "first-current-runtime",
        "url": "https://first.kleva.ru/mn1x1GHkcS/",
        "user": "dpCpae73nN",
        "password": "hXkTVKVqKoREB2",
    },
]


def call(payload: dict):
    req = urllib.request.Request(
        BASE + "/api/v1/nodes/check-connection",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Authorization": AUTH, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return 0, str(exc)

print("name | status | success | inbounds | elapsed_ms | details")
for c in cases:
    t0 = time.perf_counter()
    status, body = call({"url": c["url"], "user": c["user"], "password": c["password"]})
    elapsed = int((time.perf_counter() - t0) * 1000)
    success = "?"
    inbounds = "-"
    details = ""
    if status == 200:
        try:
            data = json.loads(body)
            success = str(bool(data.get("success", False))).lower()
            inbounds = str(data.get("inbounds_count", "-"))
            details = (str(data.get("message", "")) + " | " + str(data.get("details", ""))).strip(" |")
        except Exception:
            details = body[:180].replace("\n", " ")
    else:
        details = body[:180].replace("\n", " ")
    if len(details) > 170:
        details = details[:167] + "..."
    print(f"{c['name']} | {status} | {success} | {inbounds} | {elapsed} | {details}")
