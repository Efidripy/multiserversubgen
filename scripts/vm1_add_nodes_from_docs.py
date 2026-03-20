from __future__ import annotations

import argparse
import base64
import json
import re
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
    read_only: bool


def _call(base_url: str, auth_header: str, method: str, path: str, payload: dict | None = None) -> tuple[int, str]:
    data = None
    headers = {"Authorization": auth_header}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(base_url + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def _extract_inline_value(line: str) -> str:
    m = re.search(r"`([^`]+)`", line)
    return m.group(1).strip() if m else ""


def parse_nodes(md_text: str) -> list[NodeSpec]:
    lines = md_text.splitlines()

    # 1) Writable vm1 node from section "### 3x-ui (vm1)"
    vm1_url = vm1_user = vm1_password = ""
    in_vm1_section = False

    for line in lines:
        if line.strip().startswith("### 3x-ui (vm1)"):
            in_vm1_section = True
            continue
        if in_vm1_section and line.strip().startswith("### ") and "3x-ui (vm1)" not in line:
            break
        if in_vm1_section:
            s = line.strip()
            if s.startswith("- URL:") and not vm1_url:
                vm1_url = _extract_inline_value(s)
            elif s.startswith("- Login:") and not vm1_user:
                vm1_user = _extract_inline_value(s)
            elif s.startswith("- Password:") and not vm1_password:
                vm1_password = _extract_inline_value(s)

    specs: list[NodeSpec] = []
    if vm1_url and vm1_user and vm1_password:
        specs.append(
            NodeSpec(
                name="vm1-3xui",
                url=vm1_url,
                user=vm1_user,
                password=vm1_password,
                read_only=False,
            )
        )

    # 2) Read-only source section (ebola-ro)
    ro_url = ro_user = ro_password = ro_name = ""
    in_ro_section = False

    for line in lines:
        if line.strip().startswith("### 3x-ui Read-Only Source"):
            in_ro_section = True
            continue
        if in_ro_section and line.strip().startswith("### ") and "Read-Only Source" not in line:
            break
        if in_ro_section:
            s = line.strip()
            if s.startswith("- URL:") and not ro_url:
                ro_url = _extract_inline_value(s)
            elif s.startswith("- Login:") and not ro_user:
                ro_user = _extract_inline_value(s)
            elif s.startswith("- Password:") and not ro_password:
                ro_password = _extract_inline_value(s)
            elif s.startswith("- Node name in panel:") and not ro_name:
                ro_name = _extract_inline_value(s)

    if ro_url and ro_user and ro_password:
        specs.append(
            NodeSpec(
                name=ro_name or "ebola-ro",
                url=ro_url,
                user=ro_user,
                password=ro_password,
                read_only=True,
            )
        )

    # 3) Additional 3x-ui Nodes section
    in_additional = False
    current_name = ""
    current_url = current_user = current_password = ""

    def flush_current() -> None:
        nonlocal current_name, current_url, current_user, current_password
        if current_name and current_url and current_user and current_password:
            specs.append(
                NodeSpec(
                    name=current_name,
                    url=current_url,
                    user=current_user,
                    password=current_password,
                    read_only=True,
                )
            )
        current_name = ""
        current_url = current_user = current_password = ""

    for line in lines:
        s = line.strip()
        if s.startswith("### Additional 3x-ui Nodes"):
            in_additional = True
            continue
        if in_additional and s.startswith("### ") and "Additional 3x-ui Nodes" not in s:
            flush_current()
            break

        if not in_additional:
            continue

        # Node block marker: - `name`
        if re.match(r"^-\s+`[^`]+`$", s):
            flush_current()
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

    flush_current()

    # De-duplicate by name (keep first occurrence)
    uniq: dict[str, NodeSpec] = {}
    for spec in specs:
        if spec.name not in uniq:
            uniq[spec.name] = spec
    return list(uniq.values())


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed nodes on vm1 from LOCAL_PRIVATE_CONTEXT markdown.")
    parser.add_argument("--context", required=True, help="Path to LOCAL_PRIVATE_CONTEXT.md on target host")
    parser.add_argument("--api-base", default="http://127.0.0.1:666", help="Sub-manager API base URL")
    parser.add_argument("--api-user", default="apitest", help="Basic auth user")
    parser.add_argument("--api-password", default="ApiTest123", help="Basic auth password")
    args = parser.parse_args()

    text = Path(args.context).read_text(encoding="utf-8", errors="replace")
    specs = parse_nodes(text)
    if not specs:
        print("ERROR: no nodes parsed from docs")
        return 1

    token = base64.b64encode(f"{args.api_user}:{args.api_password}".encode("utf-8")).decode("ascii")
    auth_header = f"Basic {token}"

    status, body = _call(args.api_base, auth_header, "GET", "/api/v1/nodes")
    if status != 200:
        print(f"ERROR: GET /api/v1/nodes failed status={status} body={body}")
        return 1

    existing = json.loads(body)
    existing_names = {str(n.get("name", "")) for n in existing}

    created = 0
    skipped = 0
    failed = 0

    print("Parsed nodes from docs:")
    for s in specs:
        print(f"  - {s.name} | read_only={1 if s.read_only else 0}")

    for spec in specs:
        if spec.name in existing_names:
            skipped += 1
            print(f"SKIP {spec.name}: already exists")
            continue

        payload = {
            "name": spec.name,
            "url": spec.url,
            "user": spec.user,
            "password": spec.password,
            "read_only": spec.read_only,
        }
        status, body = _call(args.api_base, auth_header, "POST", "/api/v1/nodes", payload)
        if status == 200:
            created += 1
            print(f"OK   {spec.name}")
        else:
            failed += 1
            print(f"FAIL {spec.name}: status={status} body={body}")

    status, body = _call(args.api_base, auth_header, "GET", "/api/v1/nodes")
    if status != 200:
        print(f"ERROR: post-check GET /api/v1/nodes failed status={status} body={body}")
        return 1

    nodes = json.loads(body)
    by_name = {str(n.get("name", "")): n for n in nodes}

    print("\nSummary:")
    print(f"  created={created}")
    print(f"  skipped={skipped}")
    print(f"  failed={failed}")
    print(f"  total_nodes={len(nodes)}")

    print("\nNode verification (name | read_only | scheme | port | base_path):")
    for spec in specs:
        n = by_name.get(spec.name)
        if not n:
            print(f"  - {spec.name}: MISSING")
            continue
        print(
            "  - "
            f"{spec.name} | read_only={n.get('read_only')} | scheme={n.get('scheme')} | "
            f"port={n.get('port')} | base_path={n.get('base_path')}"
        )

    # Quick endpoint sanity: nodes list + nodes simple
    s1, _ = _call(args.api_base, auth_header, "GET", "/api/v1/nodes")
    s2, _ = _call(args.api_base, auth_header, "GET", "/api/v1/nodes/list")
    print("\nEndpoint sanity:")
    print(f"  GET /api/v1/nodes      -> {s1}")
    print(f"  GET /api/v1/nodes/list -> {s2}")

    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
