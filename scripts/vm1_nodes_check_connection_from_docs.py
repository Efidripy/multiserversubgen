from __future__ import annotations

import argparse
import base64
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass
class NodeSpec:
    name: str
    url: str
    user: str
    password: str


def call(base_url: str, auth_header: str, method: str, path: str, payload: dict | None = None) -> tuple[int, str]:
    data = None
    headers = {"Authorization": auth_header}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(base_url + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return 0, str(exc)


def _extract_inline_value(line: str) -> str:
    m = re.search(r"`([^`]+)`", line)
    return m.group(1).strip() if m else ""


def parse_nodes(md_text: str) -> list[NodeSpec]:
    lines = md_text.splitlines()

    specs: list[NodeSpec] = []

    # vm1 primary
    in_vm1 = False
    vm1_url = vm1_user = vm1_password = ""
    for line in lines:
        s = line.strip()
        if s.startswith("### 3x-ui (vm1)"):
            in_vm1 = True
            continue
        if in_vm1 and s.startswith("### ") and "3x-ui (vm1)" not in s:
            break
        if in_vm1:
            if s.startswith("- URL:") and not vm1_url:
                vm1_url = _extract_inline_value(s)
            elif s.startswith("- Login:") and not vm1_user:
                vm1_user = _extract_inline_value(s)
            elif s.startswith("- Password:") and not vm1_password:
                vm1_password = _extract_inline_value(s)
    if vm1_url and vm1_user and vm1_password:
        specs.append(NodeSpec("vm1-3xui", vm1_url, vm1_user, vm1_password))

    # read-only source
    in_ro = False
    ro_url = ro_user = ro_password = ro_name = ""
    for line in lines:
        s = line.strip()
        if s.startswith("### 3x-ui Read-Only Source"):
            in_ro = True
            continue
        if in_ro and s.startswith("### ") and "Read-Only Source" not in s:
            break
        if in_ro:
            if s.startswith("- URL:") and not ro_url:
                ro_url = _extract_inline_value(s)
            elif s.startswith("- Login:") and not ro_user:
                ro_user = _extract_inline_value(s)
            elif s.startswith("- Password:") and not ro_password:
                ro_password = _extract_inline_value(s)
            elif s.startswith("- Node name in panel:") and not ro_name:
                ro_name = _extract_inline_value(s)
    if ro_url and ro_user and ro_password:
        specs.append(NodeSpec(ro_name or "ebola-ro", ro_url, ro_user, ro_password))

    # additional nodes
    in_additional = False
    current_name = ""
    current_url = current_user = current_password = ""

    def flush() -> None:
        nonlocal current_name, current_url, current_user, current_password
        if current_name and current_url and current_user and current_password:
            specs.append(NodeSpec(current_name, current_url, current_user, current_password))
        current_name = ""
        current_url = current_user = current_password = ""

    for line in lines:
        s = line.strip()
        if s.startswith("### Additional 3x-ui Nodes"):
            in_additional = True
            continue
        if in_additional and s.startswith("### ") and "Additional 3x-ui Nodes" not in s:
            flush()
            break

        if not in_additional:
            continue

        if re.match(r"^-\s+`[^`]+`$", s):
            flush()
            current_name = _extract_inline_value(s)
            continue

        if s.startswith("- URL:"):
            current_url = _extract_inline_value(s)
        elif s.startswith("- Legacy URL:"):
            current_url = _extract_inline_value(s)
        elif s.startswith("- Login:"):
            current_user = _extract_inline_value(s)
        elif s.startswith("- Legacy Login:"):
            current_user = _extract_inline_value(s)
        elif s.startswith("- Password:"):
            current_password = _extract_inline_value(s)
        elif s.startswith("- Legacy Password:"):
            current_password = _extract_inline_value(s)

    flush()

    uniq: dict[str, NodeSpec] = {}
    for spec in specs:
        if spec.name not in uniq:
            uniq[spec.name] = spec
    return list(uniq.values())


def main() -> int:
    parser = argparse.ArgumentParser(description="Run /nodes/check-connection for nodes from docs")
    parser.add_argument("--context", required=True)
    parser.add_argument("--api-base", default="http://127.0.0.1:666")
    parser.add_argument("--api-user", default="apitest")
    parser.add_argument("--api-password", default="ApiTest123")
    args = parser.parse_args()

    text = Path(args.context).read_text(encoding="utf-8", errors="replace")
    nodes = parse_nodes(text)
    if not nodes:
        print("ERROR: no nodes parsed from docs")
        return 1

    token = base64.b64encode(f"{args.api_user}:{args.api_password}".encode("utf-8")).decode("ascii")
    auth = f"Basic {token}"

    print("=== check-connection results ===")
    print("node | status | success | inbounds | elapsed_ms | note")

    failures = 0
    for node in nodes:
        payload = {
            "url": node.url,
            "user": node.user,
            "password": node.password,
        }
        t0 = time.perf_counter()
        status, body = call(args.api_base, auth, "POST", "/api/v1/nodes/check-connection", payload)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        success = "?"
        inbounds = "-"
        note = ""

        if status == 200:
            try:
                data = json.loads(body)
                success = str(bool(data.get("success", False))).lower()
                inbounds = str(data.get("inbounds_count", "-"))
                msg = str(data.get("message", "")).strip()
                details = str(data.get("details", "")).strip()
                base_url = str(data.get("base_url", "")).strip()
                note = "; ".join([p for p in [msg, details, base_url] if p])
            except Exception:
                success = "parse_err"
                note = body[:180].replace("\n", " ")
        else:
            failures += 1
            success = "http_err"
            note = body[:180].replace("\n", " ")

        # avoid huge lines
        if len(note) > 170:
            note = note[:167] + "..."

        print(f"{node.name} | {status} | {success} | {inbounds} | {elapsed_ms} | {note}")

    return 0 if failures == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
