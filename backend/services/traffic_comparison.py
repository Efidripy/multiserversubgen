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
    if isinstance(item, (int, float)):
        return max(0, int(item))
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
                     range_name, node_id, system_client_emails=(), samples=()):
    latest = max([ts for ts, _ in snapshots] + [row[1] for row in samples], default=now)
    end = latest
    duration = step * count
    start = end - 2 * duration
    values = [0.0] * (count * 2)
    estimates = [0.0] * (count * 2)
    prefix = f"node:{node_id}:inbound:"
    parsed = [(ts, _stats(raw)) for ts, raw in snapshots]
    sample_streams = {}
    for sample_node, ts, inbound_raw, client_raw in samples:
        sample_streams.setdefault(str(sample_node), []).append((ts, _stats(inbound_raw), _stats(client_raw)))
    cutoffs = {key: rows[0][0] for key, rows in sample_streams.items()}

    def distribute(t0, t1, delta, limit=None):
        if t1 <= t0:
            return
        first = max(0, (t0 - start) // step)
        last = min(count * 2 - 1, (t1 - start - 1) // step)
        for i in range(first, last + 1):
            right = min(t1, start + (i + 1) * step, limit if limit is not None else t1)
            overlap = max(0, right - max(t0, start + i * step))
            part = delta * overlap / (t1 - t0)
            values[i] += part
            if t1 - t0 > 2 * step:
                estimates[i] += part

    for (t0, before), (t1, after) in zip(parsed, parsed[1:]):
        for key, item in after.items():
            if key not in before or (node_id is not None and not key.startswith(prefix)):
                continue
            parts = key.split(":", 3)
            cutoff = cutoffs.get(parts[1]) if len(parts) >= 4 and parts[0] == "node" else None
            distribute(t0, t1, _delta(_metric(before[key]), _metric(item)), cutoff)
    for rows in sample_streams.values():
        for (t0, before, _), (t1, after, _) in zip(rows, rows[1:]):
            delta = sum(_delta(_metric(before[key]), _metric(item))
                        for key, item in after.items() if key in before)
            distribute(t0, t1, delta)
    series = []
    for i, value in enumerate(values):
        point = {"ts": start + i * step, "value": value}
        if estimates[i] > value / 2:
            point["estimated"] = True
        series.append(point)
    availability = [(ts, stats) for ts, stats in parsed
                    if any(node_id is None or key.startswith(prefix) for key in stats)]
    availability.extend((rows[0][0], {}) for rows in sample_streams.values() if rows)
    availability.extend((rows[-1][0], {}) for rows in sample_streams.values() if rows)
    availability.sort(key=lambda item: item[0])
    previous_available = bool(availability
                              and availability[0][0] <= start + max(step, duration * 0.1)
                              and any(ts > start + duration for ts, _ in availability))
    clients, growth = [], []
    if node_id is None and (client_snapshots or sample_streams):
        system = {normalize_email(email) for email in system_client_emails}
        client_data = [(ts, _stats(raw)) for ts, raw in client_snapshots]
        amounts = {}
        def add_client_pairs(data, limit=None):
            for (t0, before), (t1, after) in zip(data, data[1:]):
                if t1 <= t0:
                    continue
                for email, item in after.items():
                    if email not in before or normalize_email(email) in system:
                        continue
                    old_metric, new_metric = _metric(before[email]), _metric(item)
                    if old_metric is None or new_metric is None:
                        continue
                    delta = _delta(old_metric, new_metric)
                    entry = amounts.setdefault(email, [0.0, 0.0, False, False, None])
                    for index, left in enumerate((start, start + duration)):
                        right = min(t1, left + duration, limit if limit is not None else t1)
                        overlap = max(0, right - max(t0, left))
                        if overlap:
                            entry[index] += delta * overlap / (t1 - t0)
                            entry[index + 2] = True
                            entry[4] = t0 if entry[4] is None else min(entry[4], t0)

        add_client_pairs(client_data, min(cutoffs.values()) if cutoffs else None)
        for rows in sample_streams.values():
            add_client_pairs([(ts, clients) for ts, _, clients in rows])
        for email, (prev, cur, has_prev, has_cur, earliest) in amounts.items():
            if not has_cur:
                continue
            prev = prev if (has_prev and previous_available
                            and earliest <= start + max(step, duration * 0.1)) else None
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
        # Fresh samples stay raw for three days, so every range needs all tiers.
        tiers = ("raw", "hour", "day")
        sample_history, sample_latest = conn.execute(
            "SELECT MIN(ts), MAX(ts) FROM traffic_samples WHERE tier IN (?, ?, ?) AND ts<=? "
            "AND (? IS NULL OR node_id=?)", (*tiers, now, node_id, str(node_id))
        ).fetchone()
        latest = max((value for value in (latest, sample_latest) if value is not None), default=None)
        history_start = min((value for value in (history_start, sample_history) if value is not None), default=None)
        samples = []
        if sample_latest is not None:
            sample_start = latest - 2 * count * step
            # Buckets are never finer than `step`, so keep only the first sample
            # per node and step plus each node's latest one; this bounds the
            # parsed client JSON to about one row per bucket.
            samples = conn.execute(
                "WITH base AS (SELECT node_id, MAX(ts) AS ts FROM traffic_samples "
                "WHERE tier IN (?, ?, ?) AND ts<? AND (? IS NULL OR node_id=?) GROUP BY node_id), "
                "candidates AS (SELECT node_id, tier, ts FROM traffic_samples "
                "WHERE tier IN (?, ?, ?) AND ts>=? AND ts<=? AND (? IS NULL OR node_id=?) "
                "UNION ALL SELECT s.node_id, s.tier, s.ts FROM base b JOIN traffic_samples s "
                "ON s.node_id=b.node_id AND s.ts=b.ts AND s.tier IN (?, ?, ?)), "
                "picked AS (SELECT node_id, tier, ts, "
                "ROW_NUMBER() OVER (PARTITION BY node_id, ts / ? ORDER BY ts) AS rn, "
                "MAX(ts) OVER (PARTITION BY node_id) AS last_ts FROM candidates) "
                "SELECT s.node_id, s.ts, s.inbounds_json, s.clients_json FROM picked p "
                "JOIN traffic_samples s ON s.node_id=p.node_id AND s.tier=p.tier AND s.ts=p.ts "
                "WHERE p.rn=1 OR p.ts=p.last_ts ORDER BY s.node_id, s.ts",
                (*tiers, sample_start, node_id, str(node_id),
                 *tiers, sample_start, now, node_id, str(node_id), *tiers, step),
            ).fetchall()
        if node_id is not None:
            prefix = f"node:{node_id}:inbound:"
            snapshot_history = next((ts for ts, raw in conn.execute(
                "SELECT snapshot_ts, stats_json FROM traffic_stats_snapshots "
                "WHERE group_by = 'inbound' AND bucket_kind = ? AND snapshot_ts <= ? "
                "ORDER BY snapshot_ts", (kind, now)
            ) if any(key.startswith(prefix) for key in _stats(raw))), None)
            history_start = min((v for v in (snapshot_history, sample_history) if v is not None), default=None)
        if latest is not None:
            start = latest - 2 * count * step
            for group, target in (("inbound", snapshots), ("client", clients)):
                if group == "client" and node_id is not None:
                    continue
                target.extend(conn.execute(
                    "SELECT snapshot_ts, stats_json FROM traffic_stats_snapshots "
                    "WHERE group_by = ? AND bucket_kind = ? AND snapshot_ts >= COALESCE( "
                    "(SELECT MAX(snapshot_ts) FROM traffic_stats_snapshots "
                    "WHERE group_by = ? AND bucket_kind = ? AND snapshot_ts < ?), ?) "
                    "AND snapshot_ts <= ? ORDER BY snapshot_ts",
                    (group, kind, group, kind, start, start, latest)
                ).fetchall())
    return build_comparison(snapshots, clients, step, count, now, history_start,
                            range_name, node_id, system_client_emails, samples)
