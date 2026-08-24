"""Regression coverage for side-effect-free production package imports."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_live_package_imports_do_not_load_retired_framework_modules():
    script = """
import sys
sys.path.insert(0, r'{backend_dir}')
import core.lifespan
import shared.security
retired = {{
    'core.base_module',
    'core.container',
    'core.event_bus',
    'core.feature_flags',
    'core.job_queue',
    'core.module_registry',
    'shared.exceptions',
    'shared.metrics',
}}
unexpected = sorted(retired.intersection(sys.modules))
raise SystemExit(f'unexpected imports: {{unexpected}}' if unexpected else 0)
""".format(backend_dir=BACKEND_DIR)

    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
