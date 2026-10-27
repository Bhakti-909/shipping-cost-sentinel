"""Data layer for the dashboard: weekly rates, next-week forecast, report loading (stdlib only)."""
import csv
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation


def monday(d):
    return d - timedelta(days=d.weekday())


def weekly_rates(path):
    """Return {route: [(week_monday, cost_per_tonne_km), ...]} sorted by week."""
    cost, work = defaultdict(Decimal), defaultdict(Decimal)
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            try:
                d = date.fromisoformat(r["shipment_date"].strip()[:10])
                c, q, k = Decimal(r["freight_cost_inr"]), Decimal(r["quantity_tonnes"]), Decimal(r["distance_km"])
            except (KeyError, ValueError, InvalidOperation):
                continue
            if q <= 0 or k <= 0 or c < 0:
                continue
            key = (f"{r['origin'].strip()}-{r['destination'].strip()}", monday(d))
            cost[key] += c
            work[key] += q * k
    series = defaultdict(list)
    for key in sorted(cost):
        series[key[0]].append((key[1], float(cost[key] / work[key])))
    return dict(series)


def forecast(series, window=8):
    """Next-week estimate per route: linear trend over the last `window` weeks (mean if < 3 weeks).
    Band = +/- one RMS residual. Routes with no data in the last `window` weeks are skipped."""
    if not series:
        return []
    last = max(p[-1][0] for p in series.values())
    target = last + timedelta(days=7)
    out = []
    for route, pts in series.items():
        pts = pts[-window:]
        if pts[-1][0] < last - timedelta(weeks=window):
            continue
        ys = [y for _, y in pts]
        n, my, mx = len(ys), sum(ys) / len(ys), (len(ys) - 1) / 2
        sxx = sum((i - mx) ** 2 for i in range(n))
        slope = sum((i - mx) * (y - my) for i, y in enumerate(ys)) / sxx if n >= 3 else 0.0
        pred = max(my + slope * (n - mx), 0.0)
        band = (sum((y - (my + slope * (i - mx))) ** 2 for i, y in enumerate(ys)) / n) ** 0.5
        out.append({
            "route": route, "weeks_used": n, "last_week": pts[-1][0].isoformat(),
            "last_rate": round(ys[-1], 4), "forecast_week": target.isoformat(),
            "forecast": round(pred, 4), "low": round(max(pred - band, 0), 4), "high": round(pred + band, 4),
            "change_pct": round((pred / ys[-1] - 1) * 100, 1) if ys[-1] else None,
            "method": "trend" if n >= 3 else "mean",
        })
    return sorted(out, key=lambda r: -(r["change_pct"] or 0))


def load_report(path):
    """Read output/anomaly_report.csv; add status = unexplained | justified."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["status"] = "unexplained" if r["flagged"].strip().lower() == "yes" else "justified"
    return rows