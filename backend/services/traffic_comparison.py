"""Traffic comparison from bounded rolling snapshots."""
import json

from services.db_bootstrap import connect
from services.system_clients import normalize_email

RANGES = {"24h": (3600, 24), "7d": (86400, 7), "30d": (86400, 30)}
# A genuine reset must lose at least half the counter; smaller drops can be
# incomplete readings and must not add the entire accumulated counter.
RESET_MAX_FRACTION = 0.5


def _stats(raw):
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def _metric(item):
    if not isinstance(item, dict):
        return None
    try:
        return max(0, int(item.get("total") or (item.get("up", 0) + item.get("down", 0))))
    except (ValueError, TypeError, OverflowError):
        return None


def _delta(previous, current):
    if previous is None or current is None:
        return 0
    if current >= previous:
        return current - previous
    return current if current <= previous * RESET_MAX_FRACTION else 0


def build_comparison(snapshots, client_snapshots, step, count, now, history_start,
                     range_name, node_id, system_client_emails=()):
    latest = snapshots[-1][0] if snapshots else now
    end = (latest // step) * step
    start = end - 2 * step * count
    values = [0] * (count * 2)
    previous_stats = None
    for timestamp, raw in snapshots:
        bucket = (timestamp // step) * step
        stats = _stats(raw)
        if previous_stats is not None and start < bucket <= end:
            prefix = f"node:{node_id}:inbound:"
            values[(bucket - start) // step - 1] = sum(
                _delta(_metric(previous_stats[key]), _metric(value))
                for key, value in stats.items()
                if key in previous_stats and (node_id is None or key.startswith(prefix))
            )
        previous_stats = stats
    series = [{"ts": start + i * step, "value": value} for i, value in enumerate(values)]
    # Sixty daily samples cover 59 intervals; permit the missing first boundary.
    availability_snapshots = snapshots
    if node_id is not None:
        prefix = f"node:{node_id}:inbound:"
        availability_snapshots = [(ts, raw) for ts, raw in snapshots
                                  if any(key.startswith(prefix) for key in _stats(raw))]
    previous_available = bool(availability_snapshots
                              and availability_snapshots[0][0] // step * step <= start + step
                              and any(ts // step * step == start + count * step
                                      for ts, _ in availability_snapshots))
    clients, growth = [], []
    if client_snapshots and node_id is None and snapshots:
        by_bucket = {ts // step * step: _stats(raw) for ts, raw in client_snapshots}
        old, mid, current = (by_bucket.get(target) for target in (start, start + count * step, end))
        system = {normalize_email(email) for email in system_client_emails}
        if mid is not None and current is not None:
            for email, item in current.items():
                if normalize_email(email) in system or email not in mid or _metric(item) is None:
                    continue
                cur = _delta(_metric(mid[email]), _metric(item))
                prev = _delta(_metric(old[email]), _metric(mid[email])) if old is not None and email in old else None
                clients.append({"email": email, "current": cur, "previous": prev,
                                "delta_pct": round((cur - prev) * 100 / prev, 1) if prev else None})
            growth = sorted((item for item in clients if item["previous"] and item["previous"] > 0),
                            key=lambda item: (-item["delta_pct"], -item["current"], item["email"]))[:10]
            clients = sorted(clients, key=lambda item: (-item["current"], item["email"]))[:10]
    previous, current = series[:count], series[count:]
    return {"range": range_name, "node_id": node_id, "series_current": current,
            "series_previous": previous if previous_available else [],
            "totals": {"current": sum(x["value"] for x in current),
                       "previous": sum(x["value"] for x in previous) if previous_available else None},
            "history_days": round(max(0, now - history_start) / 86400, 1) if history_start is not None else 0,
            "previous_available": previous_available, "top_clients": clients, "top_growth": growth}


def load_comparison(db_path, range_name, node_id, now, system_client_emails=()):
    step, count = RANGES[range_name]
    kind = "hour" if range_name == "24h" else "day"
    with connect(db_path) as conn:
        history_start, latest = conn.execute(
            "SELECT MIN(snapshot_ts), MAX(snapshot_ts) FROM traffic_stats_snapshots "
            "WHERE group_by = 'inbound' AND bucket_kind = ? AND snapshot_ts <= ?", (kind, now)
        ).fetchone()
        snapshots, clients = [], []
        if node_id is not None:
            prefix = f"node:{node_id}:inbound:"
            history_start = next((ts for ts, raw in conn.execute(
                "SELECT snapshot_ts, stats_json FROM traffic_stats_snapshots "
                "WHERE group_by = 'inbound' AND bucket_kind = ? AND snapshot_ts <= ? "
                "ORDER BY snapshot_ts", (kind, now)
            ) if any(key.startswith(prefix) for key in _stats(raw))), None)
        if latest is not None:
            start = (latest // step - 2 * count) * step
            for group, target in (("inbound", snapshots), ("client", clients)):
                if group == "client" and node_id is not None:
                    continue
                target.extend(conn.execute(
                    "SELECT snapshot_ts, stats_json FROM traffic_stats_snapshots "
                    "WHERE group_by = ? AND bucket_kind = ? AND snapshot_ts >= ? AND snapshot_ts <= ? "
                    "ORDER BY snapshot_ts", (group, kind, start, min(now, (latest // step + 1) * step - 1))
                ).fetchall())
    return build_comparison(snapshots, clients, step, count, now, history_start,
                            range_name, node_id, system_client_emails)
