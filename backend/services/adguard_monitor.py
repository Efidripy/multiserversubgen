import json
import logging
import re
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse, urlunparse

import requests


logger = logging.getLogger("sub_manager.adguard")


def _first_number(obj: Dict, keys: List[str], default: float = 0.0) -> float:
    for key in keys:
        if key in obj and obj[key] is not None:
            try:
                return float(obj[key])
            except Exception:
                continue
    return float(default)


@dataclass
class AdGuardSource:
    id: int
    name: str
    admin_url: str
    dns_url: str
    username: str
    password: str
    verify_tls: bool
    enabled: bool


class AdGuardMonitor:
    """Pulls AdGuard Home data from remote admin APIs without remote agents."""

    def __init__(self, decrypt_func: Callable[[str], str], default_verify: bool = True):
        self.decrypt = decrypt_func
        self.default_verify = default_verify

    @staticmethod
    def _normalize_url(url: str) -> str:
        raw = (url or "").strip()
        if not raw:
            return ""
        if not raw.startswith(("http://", "https://")):
            raw = "https://" + raw
        p = urlparse(raw)
        netloc = p.netloc.rstrip(":")
        path = p.path.rstrip("/")
        return urlunparse((p.scheme, netloc, path, "", "", ""))

    def _candidate_prefixes(self, admin_url: str) -> List[str]:
        base = self._normalize_url(admin_url)
        if not base:
            return []
        p = urlparse(base)
        root = urlunparse((p.scheme, p.netloc, "", "", "", ""))
        prefixes: List[str] = []
        for pref in (base, root):
            if pref and pref not in prefixes:
                prefixes.append(pref)
        return prefixes

    def _verify_value(self, source: AdGuardSource):
        return bool(source.verify_tls)

    def _login(self, source: AdGuardSource) -> Tuple[Optional[requests.Session], Optional[str], Optional[str]]:
        prefixes = self._candidate_prefixes(source.admin_url)
        if not prefixes:
            return None, None, "Empty admin URL"

        errors: List[str] = []
        for prefix in prefixes:
            session = requests.Session()
            session.headers.update({"User-Agent": "sub-manager-adguard/1.0"})
            login_url = f"{prefix}/control/login"
            payload = {"name": source.username, "password": source.password}
            try:
                res = session.post(login_url, json=payload, timeout=8, verify=self._verify_value(source))
                if res.status_code in (200, 204):
                    return session, prefix, None
                errors.append(f"{prefix} login_status={res.status_code}")
            except Exception as exc:
                errors.append(f"{prefix} login_error={exc}")
                logger.debug(f"AdGuard login failed at {login_url}: {exc}")

            # Some AdGuard setups disable /control/login and expect HTTP Basic Auth.
            try:
                session.auth = (source.username, source.password)
                status_res = session.get(
                    f"{prefix}/control/status",
                    timeout=8,
                    verify=self._verify_value(source),
                )
                if status_res.status_code == 200:
                    return session, prefix, None
                errors.append(f"{prefix} basic_status={status_res.status_code}")
            except Exception as exc:
                errors.append(f"{prefix} basic_error={exc}")
                logger.debug(f"AdGuard basic-auth probe failed at {prefix}/control/status: {exc}")
        if errors:
            return None, None, "Failed to auth AdGuard API: " + "; ".join(errors[:4])
        return None, None, "Failed to auth AdGuard API"

    def _get_json(self, session: requests.Session, url: str, verify, timeout: int = 8) -> Optional[Dict]:
        try:
            res = session.get(url, timeout=timeout, verify=verify)
            if res.status_code == 200:
                return res.json()
        except Exception:
            return None
        return None

    def _get_text(self, session: requests.Session, url: str, verify, timeout: int = 8) -> Optional[str]:
        try:
            res = session.get(url, timeout=timeout, verify=verify)
            if res.status_code == 200:
                return res.text
        except Exception:
            return None
        return None

    def _fetch_querylog(self, session: requests.Session, prefix: str, verify) -> List[Dict]:
        # Try common AdGuard querylog APIs (version-dependent).
        candidates = [
            ("get", f"{prefix}/control/querylog?limit=200", None),
            ("post", f"{prefix}/control/querylog", {"limit": 200}),
        ]
        for method, url, payload in candidates:
            try:
                if method == "get":
                    res = session.get(url, timeout=10, verify=verify)
                else:
                    res = session.post(url, json=payload, timeout=10, verify=verify)
                if res.status_code != 200:
                    continue
                data = res.json()
                if isinstance(data, dict):
                    if isinstance(data.get("data"), list):
                        return data.get("data") or []
                    if isinstance(data.get("queries"), list):
                        return data.get("queries") or []
                if isinstance(data, list):
                    return data
            except Exception:
                continue
        return []

    @staticmethod
    def _parse_prometheus_metrics(metrics_text: str) -> Dict[str, float]:
        values: Dict[str, float] = {}
        if not metrics_text:
            return values
        for raw in metrics_text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+([-+eE0-9\.]+)$", line)
            if not m:
                continue
            key = m.group(1)
            try:
                val = float(m.group(3))
            except Exception:
                continue
            values[key] = values.get(key, 0.0) + val
        return values

    @staticmethod
    def _extract_query_fields(item: Dict) -> Tuple[str, str, bool]:
        # Works for multiple AGH querylog formats.
        domain = (
            item.get("question_host")
            or item.get("domain")
            or item.get("host")
            or item.get("QH")
            or ""
        )
        client = (
            item.get("client")
            or item.get("client_name")
            or item.get("IP")
            or item.get("ip")
            or ""
        )
        blocked = bool(
            item.get("blocked")
            or item.get("is_filtered")
            or item.get("Result") in ("Filtered", "Blocked", "filtered", "blocked")
            or item.get("reason") in ("filtered", "blocked")
        )
        return str(domain), str(client), blocked

    def collect_source(self, source_row: Dict) -> Dict:
        source = AdGuardSource(
            id=int(source_row["id"]),
            name=str(source_row.get("name") or f"AdGuard-{source_row['id']}"),
            admin_url=str(source_row.get("admin_url") or ""),
            dns_url=str(source_row.get("dns_url") or ""),
            username=str(source_row.get("username") or ""),
            password=self.decrypt(str(source_row.get("password") or "")),
            verify_tls=bool(source_row.get("verify_tls", self.default_verify)),
            enabled=bool(source_row.get("enabled", True)),
        )
        if not source.enabled:
            return {
                "source_id": source.id,
                "source_name": source.name,
                "available": False,
                "error": "Disabled",
            }

        session, api_prefix, login_error = self._login(source)
        if not session or not api_prefix:
            return {
                "source_id": source.id,
                "source_name": source.name,
                "available": False,
                "error": login_error or "Login failed",
            }

        verify = self._verify_value(source)
        status = self._get_json(session, f"{api_prefix}/control/status", verify) or {}
        stats = self._get_json(session, f"{api_prefix}/control/stats", verify) or {}
        metrics_text = self._get_text(session, f"{api_prefix}/control/prometheus/metrics", verify) or ""
        prom = self._parse_prometheus_metrics(metrics_text)
        querylog = self._fetch_querylog(session, api_prefix, verify)

        queries_total = _first_number(
            prom,
            ["adguard_dns_queries_total", "adguard_dns_queries"],
            default=_first_number(stats, ["num_dns_queries", "dns_queries", "queries"], default=0),
        )
        blocked_total = _first_number(
            prom,
            ["adguard_dns_queries_blocked_total", "adguard_dns_blocked_total"],
            default=_first_number(stats, ["num_blocked_filtering", "blocked_filtering", "blocked"], default=0),
        )
        cached_total = _first_number(
            prom,
            ["adguard_dns_queries_cached_total", "adguard_dns_cache_hits_total"],
            default=0,
        )
        upstream_errors = _first_number(
            prom,
            [
                "adguard_dns_upstream_errors_total",
                "adguard_dns_errors_total",
                "adguard_dns_upstream_failure_total",
            ],
            default=_first_number(stats, ["upstream_failures", "dns_upstream_errors", "upstream_errors"], default=0),
        )
        avg_latency_ms = _first_number(
            prom,
            ["adguard_dns_upstream_avg_time_seconds"],
            default=_first_number(stats, ["avg_processing_time", "average_processing_time", "avg_time"], default=0),
        )
        if avg_latency_ms <= 1:
            avg_latency_ms *= 1000.0
        cache_hit_ratio = (cached_total / queries_total * 100.0) if queries_total > 0 else 0.0
        blocked_rate = (blocked_total / queries_total * 100.0) if queries_total > 0 else 0.0

        domain_counter: Counter = Counter()
        blocked_domain_counter: Counter = Counter()
        client_counter: Counter = Counter()
        for item in querylog[:400]:
            if not isinstance(item, dict):
                continue
            domain, client, blocked = self._extract_query_fields(item)
            if domain:
                domain_counter[domain] += 1
            if client:
                client_counter[client] += 1
            if blocked and domain:
                blocked_domain_counter[domain] += 1

        return {
            "source_id": source.id,
            "source_name": source.name,
            "admin_url": source.admin_url,
            "dns_url": source.dns_url,
            "api_base": api_prefix,
            "available": True,
            "error": "",
            "queries_total": float(queries_total),
            "blocked_total": float(blocked_total),
            "blocked_rate": float(blocked_rate),
            "cache_hit_ratio": float(cache_hit_ratio),
            "avg_latency_ms": float(avg_latency_ms),
            "upstream_errors": float(upstream_errors),
            "top_domains": [{"name": k, "count": v} for k, v in domain_counter.most_common(10)],
            "top_blocked_domains": [{"name": k, "count": v} for k, v in blocked_domain_counter.most_common(10)],
            "top_clients": [{"name": k, "count": v} for k, v in client_counter.most_common(10)],
            "status": status,
        }
