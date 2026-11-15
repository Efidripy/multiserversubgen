"""Compare pyright errors with the checked-in baseline."""

import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "backend" / ".pyright-baseline.json"


def diagnostics(output, root=ROOT):
    counts = Counter()
    for item in output["generalDiagnostics"]:
        if item["severity"] != "error":
            continue
        path = Path(item["file"]).resolve().relative_to(root.resolve()).as_posix()
        message = " ".join(item["message"].split())
        counts[(path, item.get("rule", ""), message)] += 1
    return counts


def serialize(counts):
    return [
        {"file": path, "rule": rule, "message": message, "count": count}
        for (path, rule, message), count in sorted(counts.items())
    ]


def deserialize(entries):
    counts = Counter()
    for entry in entries:
        key = (entry["file"], entry["rule"], entry["message"])
        count = entry["count"]
        if key in counts or not isinstance(count, int) or isinstance(count, bool) or count <= 0:
            raise ValueError("Invalid or duplicate baseline entry")
        counts[key] = count
    return counts


def compare(current, baseline):
    return current - baseline, baseline - current


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update-baseline", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="pyright command after --")
    args = parser.parse_args()
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("provide a pyright command after --")
    try:
        result = subprocess.run(
            [*command, "--outputjson"], cwd=ROOT, capture_output=True, encoding="utf-8"
        )
        if result.returncode not in (0, 1):
            raise ValueError(f"pyright failed (exit {result.returncode}): {result.stderr.strip()}")
        output = json.loads(result.stdout)
        current = diagnostics(output)
        if output["summary"]["errorCount"] != sum(current.values()):
            raise ValueError("pyright error count does not match diagnostics")
        if args.update_baseline:
            BASELINE.write_text(json.dumps(serialize(current), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"Updated baseline: {sum(current.values())} errors")
            return 0
        baseline = deserialize(json.loads(BASELINE.read_text(encoding="utf-8")))
        new, removed = compare(current, baseline)
        if removed:
            print(f"{sum(removed.values())} baseline errors resolved; consider --update-baseline.")
        if new:
            print(f"{sum(new.values())} new pyright errors:")
            for entry in serialize(new):
                print(f"  {entry['file']} [{entry['rule']}] x{entry['count']}: {entry['message']}")
            return 1
        print(f"Pyright baseline satisfied ({sum(current.values())} errors).")
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Pyright baseline check failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
