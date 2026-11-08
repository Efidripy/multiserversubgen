"""Bounded traffic comparison from node counters and client snapshots."""
import json

from services.db_bootstrap import connect

RANGES = {"24h": (3600, 24), "7d": (86400, 7), "30d": (86400, 30)}


def build_comparison(rows, snapshots, start, step, count, now, history_start, range_name, node_id):
    values = [0] * (count * 2)
    for node, bucket, delta in rows:
        values[int((bucket - start) // step)] += delta
    series = [{"ts": start + i * step, "value": value} for i, value in enumerate(values)]
    duration = step * count
    previous_available = history_start is not None and history_start <= start and any(
        start + duration - step <= row[1] < start + duration for row in rows
    )
    clients = []
    growth = []
    if snapshots and node_id is None:
        boundaries = []
        latest = max(snapshots, key=lambda row: row[0])[0]
        for target in (latest - 2 * duration, latest - duration, latest):
            nearest = min(snapshots, key=lambda row: abs(row[0] - target))
            boundaries.append(nearest if abs(nearest[0] - target) <= step else None)
        if boundaries[1] and boundaries[2] and boundaries[1][0] < boundaries[2][0]:
            try:
                data = [json.loads(row[1]) if row else None for row in boundaries]
                def metric(item):
                    if not isinstance(item, dict):
                        return 0
                    return max(0, int(item.get("total") or (item.get("up", 0) + item.get("down", 0))))
                for email, item in data[2].items():
                    if not isinstance(item, dict):
                        continue
                    end, mid = metric(item), metric(data[1].get(email))
                    cur = end - mid if end >= mid else end
                    prev = None
                    if data[0] is not None and boundaries[0][0] < boundaries[1][0]:
                        old = metric(data[0].get(email))
                        prev = mid - old if mid >= old else mid
                    clients.append({"email": email, "current": cur, "previous": prev,
                                    "delta_pct": round((cur - prev) * 100 / prev, 1) if prev else None})
                growth = sorted((item for item in clients if item["previous"] and item["previous"] > 0),
                                key=lambda item: (-item["delta_pct"], -item["current"], item["email"]))[:10]
                clients.sort(key=lambda item: (-item["current"], item["email"]))
                clients = clients[:10]
            except (ValueError, TypeError, AttributeError):
                clients = []
    previous, current = series[:count], series[count:]
    return {"range": range_name, "node_id": node_id, "series_current": current,
            "series_previous": previous if previous_available else [],
            "totals": {"current": sum(x["value"] for x in current),
                       "previous": sum(x["value"] for x in previous) if previous_available else None},
            "history_days": round(max(0, now - history_start) / 86400, 1) if history_start is not None else 0,
            "previous_available": previous_available, "top_clients": clients, "top_growth": growth}


def load_comparison(db_path, range_name, node_id, now):
    step, count = RANGES[range_name]
    end = (now // step + 1) * step
    start = end - 2 * step * count
    node_filter = " AND node_id = ?" if node_id is not None else ""
    node_args = [node_id] if node_id is not None else []
    with connect(db_path) as conn:
        history_start = conn.execute("SELECT MIN(ts) FROM node_history WHERE traffic_total IS NOT NULL" + node_filter, node_args).fetchone()[0]
        # Compute consecutive counter deltas in SQLite and return only bucket sums.
        rows = conn.execute("""
            WITH readings AS (
                SELECT node_id, ts, MAX(0, traffic_total) AS total,
                    LAG(MAX(0, traffic_total)) OVER (PARTITION BY node_id ORDER BY ts) AS prior
                FROM node_history WHERE ts >= ? AND ts < ? AND traffic_total IS NOT NULL
        """ + node_filter + """
            ), with_baseline AS (
                SELECT node_id, ts, total, COALESCE(prior, (
                    SELECT MAX(0, h.traffic_total) FROM node_history h
                    WHERE h.node_id = readings.node_id AND h.ts < ? AND h.traffic_total IS NOT NULL
                    ORDER BY h.ts DESC LIMIT 1
                )) AS previous FROM readings
            )
            SELECT node_id, (ts / ?) * ? AS bucket,
                SUM(CASE WHEN previous IS NULL THEN 0
                         WHEN total >= previous THEN total - previous ELSE total END)
            FROM with_baseline GROUP BY node_id, bucket ORDER BY bucket, node_id
        """, [start, end] + node_args + [start, step, step]).fetchall()
        snapshots = []
        if node_id is None:
            kind = "hour" if range_name == "24h" else "day"
            latest = conn.execute("SELECT MAX(snapshot_ts) FROM traffic_stats_snapshots WHERE group_by = 'client' AND bucket_kind = ? AND snapshot_ts <= ?",
                                  (kind, now)).fetchone()[0]
            if latest is not None:
                snapshots = conn.execute("SELECT snapshot_ts, stats_json FROM traffic_stats_snapshots WHERE group_by = 'client' AND bucket_kind = ? AND snapshot_ts BETWEEN ? AND ? ORDER BY snapshot_ts",
                                         (kind, latest - 2 * step * count - step, latest)).fetchall()
    return build_comparison(rows, snapshots, start, step, count, now, history_start, range_name, node_id)
