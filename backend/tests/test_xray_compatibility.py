"""Regression coverage for non-mutating Xray compatibility analysis."""
from services.xray_compatibility import analyze_inbound, summarize_node_inbounds


def test_xmc_legacy_usernames_and_incomplete_profiles_are_detected_without_values():
    findings = analyze_inbound({
        "protocol": "vless",
        "streamSettings": {
            "network": "xhttp",
            "finalmaskSettings": {
                "usernames": ["legacy-user"],
                "profiles": [{"username": "bad", "uuid": "not-a-uuid"}],
            },
        },
    })

    assert "xray_xmc_legacy_usernames" in findings
    assert "xray_xmc_incomplete_profiles" in findings
    assert all("legacy-user" not in finding for finding in findings)


def test_xhttp_and_wireguard_shape_findings_are_reported_read_only():
    summary = summarize_node_inbounds([
        {
            "protocol": "vless",
            "streamSettings": {
                "network": "xhttp",
                "xhttpSettings": {"sessionPlacement": "path", "sessionKey": "old"},
            },
        },
        {
            "protocol": "wireguard",
            "settings": {"clients": [{"privateKey": "never-returned"}], "peers": []},
        },
    ])

    codes = {item["code"] for item in summary["findings"]}
    assert summary["status"] == "warning"
    assert summary["checked_inbounds"] == 2
    assert {"xray_xhttp_legacy_session_keys", "xray_wireguard_legacy_clients_shape", "xray_wireguard_incomplete_peer"} <= codes
    assert "privateKey" not in str(summary)


def test_reality_finalmask_tcp_and_missing_settings_are_actionable():
    findings = analyze_inbound({
        "protocol": "vless",
        "streamSettings": {
            "network": "tcp",
            "security": "reality",
            "finalmaskSettings": {"profiles": []},
        },
    })

    assert "xray_reality_finalmask_tcp" in findings
    assert "xray_reality_settings_missing" in findings
