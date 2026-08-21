"""Read-only Xray compatibility checks for inbound snapshots.

The checks intentionally return only stable finding codes and aggregate counts.
They never normalise, write back, or expose an inbound's keys, credentials,
profiles, destinations, or client values.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any, Dict, Iterable, List


_PROFILE_USERNAME = re.compile(r"^[A-Za-z0-9_]{3,16}$")


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _is_uuid(value: Any) -> bool:
    text = str(value or "")
    parts = text.split("-")
    return len(parts) == 5 and [len(part) for part in parts] == [8, 4, 4, 4, 12] and all(
        all(character in "0123456789abcdefABCDEF" for character in part) for part in parts
    )


def analyze_inbound(inbound: Dict[str, Any]) -> List[str]:
    """Return compatibility finding codes for one inbound without raw values."""
    raw_stream = inbound.get("streamSettings")
    raw_settings = inbound.get("settings")
    stream = _as_dict(raw_stream)
    settings = _as_dict(raw_settings)
    network = str(stream.get("network") or "").lower()
    security = str(stream.get("security") or inbound.get("security") or "").lower()
    findings: List[str] = []

    if (raw_stream not in (None, "", {}) and not stream) or (raw_settings not in (None, "", {}) and not settings):
        findings.append("xray_config_malformed")

    finalmask = _as_dict(stream.get("finalmaskSettings") or stream.get("finalmask"))
    if finalmask and network == "tcp" and security == "reality":
        findings.append("xray_reality_finalmask_tcp")

    # XMC v26.7.28 replaces settings.usernames with settings.profiles[].
    if finalmask:
        if isinstance(finalmask.get("usernames"), list) and finalmask.get("usernames"):
            findings.append("xray_xmc_legacy_usernames")
        profiles = finalmask.get("profiles")
        if profiles is not None:
            valid_profiles = isinstance(profiles, list) and bool(profiles)
            if valid_profiles:
                for profile in profiles:
                    profile_data = _as_dict(profile)
                    if not (
                        _PROFILE_USERNAME.fullmatch(str(profile_data.get("username") or ""))
                        and _is_uuid(profile_data.get("uuid"))
                        and bool(str(profile_data.get("texturesValue") or ""))
                        and bool(str(profile_data.get("texturesSignature") or ""))
                    ):
                        valid_profiles = False
                        break
            if not valid_profiles:
                findings.append("xray_xmc_incomplete_profiles")

    xhttp = _as_dict(stream.get("xhttpSettings"))
    if network == "xhttp":
        if "sessionPlacement" in xhttp or "sessionKey" in xhttp:
            findings.append("xray_xhttp_legacy_session_keys")
        if any(key in xhttp for key in ("sessionIDTable", "sessionIDLength", "xmux")):
            findings.append("xray_xhttp_form_loss_risk")

    if str(inbound.get("protocol") or "").lower() == "wireguard":
        peers = settings.get("peers")
        legacy_clients = settings.get("clients")
        if isinstance(legacy_clients, list) and legacy_clients:
            findings.append("xray_wireguard_legacy_clients_shape")
        if not isinstance(peers, list) or not peers or not bool(str(settings.get("secretKey") or "")):
            findings.append("xray_wireguard_incomplete_peer")
        elif any(
            not isinstance(peer, dict)
            or not bool(str(peer.get("publicKey") or ""))
            or not peer.get("allowedIPs")
            for peer in peers
        ):
            findings.append("xray_wireguard_incomplete_peer")

    if security == "reality" and not isinstance(stream.get("realitySettings"), (dict, str)):
        findings.append("xray_reality_settings_missing")
    elif security == "reality" and not _as_dict(stream.get("realitySettings")):
        findings.append("xray_reality_settings_malformed")

    return findings


def summarize_node_inbounds(inbounds: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate redacted compatibility findings for one node snapshot."""
    counter: Counter[str] = Counter()
    checked = 0
    for inbound in inbounds:
        if not isinstance(inbound, dict):
            continue
        checked += 1
        counter.update(analyze_inbound(inbound))
    severity = {
        "xray_reality_finalmask_tcp": "critical",
        "xray_xmc_legacy_usernames": "error",
        "xray_xmc_incomplete_profiles": "error",
        "xray_wireguard_incomplete_peer": "error",
        "xray_config_malformed": "error",
    }
    findings = [
        {"code": code, "severity": severity.get(code, "warning"), "count": count}
        for code, count in sorted(counter.items())
    ]
    return {
        "status": "warning" if findings else "ok",
        "checked_inbounds": checked,
        "findings": findings,
    }
