"""Local web dashboard.  Run:  python -m src.dashboard [--port 8000]"""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import alerts, exports, insights

ROOT = Path(__file__).resolve().parent.parent
SHIPMENTS, REPORT = ROOT / "data" / "shipment_records.csv", ROOT / "output" / "anomaly_report.csv"
PAGE = Path(__file__).resolve().parent / "web" / "index.html"
ANOM_H = ["route", "week_of", "cost_per_tonne_km", "vs_own_history", "vs_similar_routes", "flagged", "matched_note_id", "reason"]
FC_H = ["route", "weeks_used", "last_week", "last_rate", "forecast_week", "forecast", "low", "high", "change_pct", "method"]
_cache = {}


def data():
    key = (SHIPMENTS.stat().st_mtime, REPORT.stat().st_mtime)
    if _cache.get("key") != key:
        series = insights.weekly_rates(SHIPMENTS)
        _cache.update(key=key, series=series, fc=insights.forecast(series), rep=insights.load_report(REPORT))
    return _cache["series"], _cache["fc"], _cache["rep"]


class Handler(BaseHTTPRequestHandler):
    def reply(self, code, body, ctype="application/json", headers=None):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/":
            return self.reply(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        try:
            series, fc, rep = data()
        except OSError as e:
            return self.reply(500, {"error": f"Missing file {e.filename}. Run python -m src.main first."})
        p = u.path
        if p == "/api/summary":
            un = sum(r["status"] == "unexplained" for r in rep)
            return self.reply(200, {"anomalies": len(rep), "unexplained": un, "justified": len(rep) - un,
                                    "routes": len(series), "forecast_week": fc[0]["forecast_week"] if fc else None})
        if p == "/api/routes":
            return self.reply(200, sorted(series))
        if p == "/api/forecast":
            return self.reply(200, fc)
        if p == "/api/anomalies":
            st, text = q.get("status", "all"), q.get("q", "").lower()
            rows = [r for r in rep if st in ("all", r["status"]) and text in r["route"].lower()]
            return self.reply(200, rows)
        if p == "/api/route":
            name = q.get("name", "")
            if name not in series:
                return self.reply(404, {"error": "unknown route"})
            flags = {r["week_of"]: r["status"] for r in rep if r["route"] == name}
            hist = [{"week": w.isoformat(), "rate": round(y, 4), "status": flags.get(w.isoformat())} for w, y in series[name]]
            return self.reply(200, {"route": name, "history": hist, "forecast": next((f for f in fc if f["route"] == name), None)})
        if p.startswith("/export/"):
            name, _, fmt = p[8:].partition(".")
            if name == "anomalies":
                head, rows = ANOM_H, [[r[h] for h in ANOM_H] for r in rep]
            elif name == "forecast":
                head, rows = FC_H, [[r[h] for h in FC_H] for r in fc]
            else:
                return self.reply(404, {"error": "unknown export"})
            if fmt == "xlsx":
                body, ctype = exports.to_xlsx(head, rows, name.title()), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            elif fmt == "csv":
                body, ctype = exports.to_csv(head, rows), "text/csv"
            else:
                return self.reply(404, {"error": "use .xlsx or .csv"})
            return self.reply(200, body, ctype, {"Content-Disposition": f'attachment; filename="{name}.{fmt}"'})
        self.reply(404, {"error": "not found"})

    def do_POST(self):
        if urlparse(self.path).path != "/api/alert":
            return self.reply(404, {"error": "not found"})
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != self.headers.get("Host"):
            return self.reply(403, {"error": "cross-origin request refused"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            rep = data()[2]
        except (ValueError, OSError):
            return self.reply(400, {"error": "bad request or missing report"})
        self.reply(200, alerts.send_alert(rep, dry_run=bool(body.get("dry_run", True))))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    print(f"Dashboard: http://{a.host}:{a.port}  (Ctrl+C to stop)")
    ThreadingHTTPServer((a.host, a.port), Handler).serve_forever()