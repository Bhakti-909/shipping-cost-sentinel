"""Email alert for unexplained anomalies. Preview by default; sends only with --send.

Env: ALERT_SMTP_HOST, ALERT_SMTP_PORT (587), ALERT_SMTP_USER, ALERT_SMTP_PASSWORD, ALERT_FROM, ALERT_TO (comma list)
"""
import argparse
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

from . import insights

REPORT = Path(__file__).resolve().parent.parent / "output" / "anomaly_report.csv"


def build(rows, limit=25):
    un = [r for r in rows if r["status"] == "unexplained"]
    lines = [f"{len(un)} unexplained cost anomalies need review ({len(rows) - len(un)} others have a supporting note).", ""]
    for r in un[:limit]:
        lines.append(f"- {r['route']} | week of {r['week_of']} | {r['cost_per_tonne_km']} INR/tonne-km"
                     f" | vs own history {r['vs_own_history']} | vs similar routes {r['vs_similar_routes']}")
    if len(un) > limit:
        lines.append(f"...and {len(un) - limit} more in the dashboard.")
    return f"Freight Tiger: {len(un)} unexplained shipping cost anomalies", "\n".join(lines), len(un)


def send_alert(rows, dry_run=True, to=None):
    subject, body, count = build(rows)
    host, user, pw = os.getenv("ALERT_SMTP_HOST"), os.getenv("ALERT_SMTP_USER"), os.getenv("ALERT_SMTP_PASSWORD")
    rcpt = [a.strip() for a in (to or os.getenv("ALERT_TO", "")).split(",") if a.strip()]
    res = {"subject": subject, "body": body, "count": count, "to": rcpt, "sent": False}
    if dry_run:
        return {**res, "note": "Preview only; nothing was sent."}
    if not (host and rcpt):
        return {**res, "note": "Not sent: set ALERT_SMTP_HOST and ALERT_TO (see src/alerts.py)."}
    if count == 0:
        return {**res, "note": "Not sent: there are no unexplained anomalies."}
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, os.getenv("ALERT_FROM") or user or rcpt[0], ", ".join(rcpt)
    msg.set_content(body)
    try:
        with smtplib.SMTP(host, int(os.getenv("ALERT_SMTP_PORT", "587")), timeout=20) as s:
            s.starttls()
            if user and pw:
                s.login(user, pw)
            s.send_message(msg)
    except (OSError, smtplib.SMTPException) as e:
        return {**res, "note": f"Send failed: {e}"}
    return {**res, "sent": True, "note": f"Sent to {', '.join(rcpt)}."}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="actually send (default: preview)")
    ap.add_argument("--to", help="comma-separated recipients (overrides ALERT_TO)")
    a = ap.parse_args()
    r = send_alert(insights.load_report(REPORT), dry_run=not a.send, to=a.to)
    print(r["note"], f"\nTo: {r['to']}\nSubject: {r['subject']}\n\n{r['body']}")