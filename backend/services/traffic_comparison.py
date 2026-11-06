"""Bounded traffic comparison from node counters and client snapshots."""
import json

from services.db_bootstrap import connect

RANGES = {"24h": (3600, 24), "7d": (86400, 7), "30d": (86400, 30)}


def build_comparison(rows, baseline, snapshots, start, step, count, now, history_start, range_name, node_id):
    values = [0] * (count * 2)
    last = {node: max(0, int(total)) for node, total in baseline}
    for node, bucket, first, peak, final in rows:
        first, peak, final = (max(0, int(v)) for v in (first, peak, final))
        prior = last.get(node)
        delta = 0 if prior is None else (first - prior if first >= prior else first)
        delta += peak - first
        if final < peak:
            delta += final
        values[int((bucket - start) // step)] += delta
        last[node] = final
    series = [{"ts": start + i * step, "value": value} for i, value in enumerate(values)]
    duration = step * count
    previous_available = history_start is not None and history_start <= start and any(
        start + duration - step <= row[1] < start + duration for row in rows
    )
    clients = []
    if snapshots and node_id is None:
        boundaries = []
        for target in (start, start + duration, now):
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
            "previous_available": previous_available, "top_clients": clients}


def load_comparison(db_path, range_name, node_id, now):
    step, count = RANGES[range_name]
    end = (now // step + 1) * step
    start = end - 2 * step * count
    node_filter = " AND node_id = ?" if node_id is not None else ""
    node_args = [node_id] if node_id is not None else []
    with connect(db_path) as conn:
        history_start = conn.execute("SELECT MIN(ts) FROM node_history WHERE traffic_total IS NOT NULL" + node_filter, node_args).fetchone()[0]
        # Window functions reduce the result to one row per node and UTC bucket.
        rows = conn.execute("""
            WITH ranked AS (
                SELECT node_id, (ts / ?) * ? AS bucket, traffic_total,
                    ROW_NUMBER() OVER (PARTITION BY node_id, ts / ? ORDER BY ts) AS first_rank,
                    ROW_NUMBER() OVER (PARTITION BY node_id, ts / ? ORDER BY ts DESC) AS last_rank
                FROM node_history WHERE ts >= ? AND ts < ? AND traffic_total IS NOT NULL
        """ + node_filter + """
            ) SELECT node_id, bucket, MAX(CASE WHEN first_rank = 1 THEN traffic_total END),
                     MAX(traffic_total), MAX(CASE WHEN last_rank = 1 THEN traffic_total END)
              FROM ranked GROUP BY node_id, bucket ORDER BY bucket, node_id
        """, [step, step, step, step, start, end] + node_args).fetchall()
        baseline = conn.execute("""
            SELECT node_id, traffic_total FROM node_history n WHERE ts < ? AND traffic_total IS NOT NULL
        """ + node_filter + """ AND ts = (SELECT MAX(h.ts) FROM node_history h
            WHERE h.node_id = n.node_id AND h.ts < ? AND h.traffic_total IS NOT NULL)
        """, [start] + node_args + [start]).fetchall()
        snapshots = []
        if node_id is None:
            snapshots = conn.execute("SELECT snapshot_ts, stats_json FROM traffic_stats_snapshots WHERE group_by = 'client' AND bucket_kind = ? AND snapshot_ts BETWEEN ? AND ? ORDER BY snapshot_ts",
                                     ("hour" if range_name == "24h" else "day", start - step, now)).fetchall()
    return build_comparison(rows, baseline, snapshots, start, step, count, now, history_start, range_name, node_id)
