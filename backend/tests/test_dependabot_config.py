"""Regression coverage for the low-noise Dependabot policy."""

from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[2]


def test_dependabot_disables_routine_version_update_prs_but_groups_security_updates():
    config = yaml.safe_load((REPO / ".github/dependabot.yml").read_text(encoding="utf-8"))

    assert config["version"] == 2
    updates = {entry["package-ecosystem"]: entry for entry in config["updates"]}

    for ecosystem, group_name in (("npm", "frontend-security"), ("pip", "backend-security")):
        entry = updates[ecosystem]

        assert entry["schedule"]["interval"] == "monthly"
        assert entry["open-pull-requests-limit"] == 0
        assert entry["groups"][group_name] == {
            "applies-to": "security-updates",
            "patterns": ["*"],
        }
