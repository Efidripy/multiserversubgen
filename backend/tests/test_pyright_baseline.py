import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/ci/check-pyright-baseline.py"
spec = importlib.util.spec_from_file_location("pyright_baseline", SCRIPT)
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)


def test_comparison_counts_errors_without_line_numbers(tmp_path):
    file = str(tmp_path / "backend" / "example.py")
    fixture = json.loads(json.dumps({"generalDiagnostics": [
        {"file": file, "severity": "error", "rule": "reportArgumentType",
         "message": "Bad\n  argument", "range": {"start": {"line": 1}}},
        {"file": file, "severity": "warning", "message": "Ignored"},
    ]}))
    old = baseline.diagnostics(fixture, tmp_path)
    fixture["generalDiagnostics"][0]["range"]["start"]["line"] = 99
    fixture["generalDiagnostics"].append(dict(fixture["generalDiagnostics"][0]))
    current = baseline.diagnostics(fixture, tmp_path)
    new, removed = baseline.compare(current, baseline.deserialize(baseline.serialize(old)))
    key = ("backend/example.py", "reportArgumentType", "Bad argument")
    assert new[key] == 1
    assert not removed
    assert baseline.compare(old, current)[1][key] == 1


def test_comparison_detects_changed_message_and_file(tmp_path):
    def result(file, message):
        return baseline.diagnostics({"generalDiagnostics": [{
            "file": str(tmp_path / file), "severity": "error", "rule": "rule",
            "message": message,
        }]}, tmp_path)

    old = result("a.py", "old")
    for current in (result("a.py", "new"), result("b.py", "old")):
        new, removed = baseline.compare(current, old)
        assert sum(new.values()) == sum(removed.values()) == 1
