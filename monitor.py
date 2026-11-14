"""Newtral Standing-Mate chair price drop monitor.

Alert only. It reads the public product data on newtralchair.com and Amazon, decides whether
the price dropped, and pushes to ntfy. It never buys, adds to cart, logs in, or tries to get
past any bot protection.

  python monitor.py                 normal run
  python monitor.py --dry-run       print what would alert, send nothing, write no state
  python monitor.py --test-alert    send one test notification at each priority level
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

import notify
import state as state_mod
from checks import amazon, newtral_site
from checks.common import BLOCKED, IN_STOCK, OUT_OF_STOCK, STRUCTURE_BROKEN, UNREADABLE, CheckResult, run_safely
from notify import Alert

HERE = Path(__file__).resolve().parent
INCIDENT_STATUSES = {STRUCTURE_BROKEN, UNREADABLE}  # BLOCKED is expected on Amazon, so it only counts toward the failure warning
CHECKS = {"newtral_site": newtral_site, "amazon": amazon}
LABELS = {"newtral_site": "newtralchair.com", "amazon": "Amazon"}


def load_config(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# ---------------------------------------------------------------- running the checks

def run_checks(cfg: dict, overrides: dict | None = None) -> list[CheckResult]:
    overrides = overrides or {}
    ua, timeout = cfg["user_agent"], cfg["timeout_seconds"]
    results = []
    for name, mod in CHECKS.items():
        tcfg = cfg["targets"][name]
        if tcfg.get("enabled", True):
            results.append(run_safely(name, mod.check, tcfg, ua, timeout, overrides.get(name)))
    return results


# ---------------------------------------------------------------- deciding what to alert

class Pending:
    """An alert plus the state change to apply only once it is actually delivered."""

    def __init__(self, alert: Alert, on_sent=None):
        self.alert = alert
        self.on_sent = on_sent or (lambda: None)


def _money(x: float | None) -> str:
    return "?" if x is None else f"${x:.2f}"


def _price_alerts(r: CheckResult, t: dict, cfg: dict, now: datetime) -> list[Pending]:
    out: list[Pending] = []
    label = LABELS[r.target]
    baseline = float(cfg["baseline_price"])
    target_price = float(cfg["target_price"])
    step = float(cfg["min_drop_dollars"])
    today = now.astimezone(ZoneInfo(cfg["timezone"])).date().isoformat()
    price, prev_status = r.price, t["status"]

    if price is not None and (t["lowest_price"] is None or price < t["lowest_price"]):
        t["lowest_price"], t["lowest_date"] = price, today
    if t["reference_price"] is None:
        t["reference_price"] = baseline

    if r.status == OUT_OF_STOCK:
        if prev_status == IN_STOCK:
            out.append(Pending(Alert(f"Chair out of stock on {label}", r.detail, notify.LOW, ["package"], r.url)))
        t["status"] = OUT_OF_STOCK
        t["price"] = price
        return out

    # IN_STOCK with a price from here on.
    ref = t["reference_price"]
    if price <= ref - step:
        urgent = price <= target_price
        body = (
            f"{label}: {_money(price)} (was {_money(ref)}"
            + (f", normal {_money(baseline)}" if ref != baseline else "") + ").\n"
            f"Lowest seen here: {_money(t['lowest_price'])} on {t['lowest_date']}."
        )
        if r.target == "amazon":
            body += "\nCheck for a clip-on coupon too, the monitor cannot see those."

        def mark(t=t, p=price):
            t["reference_price"] = p

        title = f"CHAIR AT {_money(price)} on {label}" if urgent else f"Chair price drop: {_money(price)} on {label}"
        out.append(Pending(Alert(title, body, notify.URGENT if urgent else notify.HIGH,
                                 ["rotating_light" if urgent else "money_with_wings"], r.url), mark))
    elif price >= ref + step:
        if ref < baseline:
            out.append(Pending(Alert(f"Chair price back up on {label}",
                                     f"{label}: {_money(price)} now (sale price was {_money(ref)}).",
                                     notify.LOW, ["chart_with_upwards_trend"], r.url)))
        t["reference_price"] = min(price, baseline)
    elif prev_status == OUT_OF_STOCK:
        out.append(Pending(Alert(f"Chair back in stock on {label}", r.detail, notify.DEFAULT, ["package"], r.url)))

    t["status"] = IN_STOCK
    t["price"] = price
    return out


def decide(results: list[CheckResult], st: dict, cfg: dict, now: datetime) -> list[Pending]:
    pending: list[Pending] = []
    threshold = cfg["failure_alert_threshold"]
    for r in results:
        t = state_mod.target(st, r.target)
        t["detail"] = r.detail[:200]
        t["last_result"] = r.status
        if r.failed:
            t["consecutive_failures"] += 1
            if r.status in INCIDENT_STATUSES and t["open_incident"] != r.status:
                def mark_incident(t=t, s=r.status):
                    t["open_incident"] = s
                pending.append(Pending(Alert(f"Chair monitor: {LABELS[r.target]} page changed",
                                             f"{r.target}: {r.detail}", notify.DEFAULT, ["warning"], r.url), mark_incident))
            if t["consecutive_failures"] >= threshold and not t["failure_alert_sent"]:
                def mark_fail(t=t):
                    t["failure_alert_sent"] = True
                pending.append(Pending(Alert(
                    f"Chair monitor: {LABELS[r.target]} failing",
                    f"{r.target} failed {t['consecutive_failures']} runs in a row. Latest: {r.detail}",
                    notify.DEFAULT, ["warning"], r.url), mark_fail))
            continue

        t["consecutive_failures"] = 0
        t["failure_alert_sent"] = False
        t["open_incident"] = None
        pending += _price_alerts(r, t, cfg, now)

    hb = heartbeat(results, st, cfg, now)
    if hb:
        pending.append(hb)
    return pending


def heartbeat(results: list[CheckResult], st: dict, cfg: dict, now: datetime) -> Pending | None:
    local = now.astimezone(ZoneInfo(cfg["timezone"]))
    today = local.date().isoformat()
    if local.hour < cfg["heartbeat_hour"] or st["last_heartbeat_date"] == today:
        return None
    by_name = {r.target: r for r in results}
    lines = []
    for name, tcfg in cfg["targets"].items():
        label = LABELS.get(name, name)
        if not tcfg.get("enabled", True):
            lines.append(f"{label}: disabled")
        elif name in by_name:
            r = by_name[name]
            low = st["targets"].get(name, {}).get("lowest_price")
            text = r.detail[:60] if r.failed else f"{_money(r.price)} {r.status.lower().replace('_', ' ')}"
            lines.append(f"{label}: {text}" + (f" (lowest {_money(low)})" if low is not None else ""))

    def mark():
        st["last_heartbeat_date"] = today

    return Pending(Alert("Chair monitor alive", "\n".join(lines), notify.MIN, ["white_check_mark"]), mark)


# ---------------------------------------------------------------- output

def write_summary(results: list[CheckResult], sent: list[str]) -> None:
    lines = ["| Target | Status | Price | Detail |", "|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r.target} | {r.status} | {_money(r.price)} | {r.detail[:150].replace('|', '/')} |")
    lines.append("")
    lines.append("Alerts: " + ("; ".join(sent) if sent else "none"))
    text = "\n".join(lines)
    print(text)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("## Newtral chair price monitor\n\n" + text + "\n")


def send_test_alerts(cfg: dict) -> int:
    ua, timeout = cfg["user_agent"], cfg["timeout_seconds"]
    url = newtral_site.product_url(cfg["targets"]["newtral_site"])
    ok = True
    for prio in (notify.MIN, notify.LOW, notify.DEFAULT, notify.HIGH, notify.URGENT):
        alert = Alert(f"TEST p{prio}: chair monitor", f"Test notification at priority {prio}. No price change.",
                      prio, ["test_tube"], url)
        ok = notify.send(alert, ua, timeout) and ok
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Newtral Standing-Mate chair price monitor (alert only)")
    ap.add_argument("--dry-run", action="store_true", help="print alerts, send nothing, do not write state")
    ap.add_argument("--test-alert", action="store_true", help="send one test notification at each priority")
    ap.add_argument("--config", default=str(HERE / "config.yaml"))
    ap.add_argument("--state", default=str(HERE / "state.json"))
    ap.add_argument("--newtral-json", help="use this local JSON file instead of fetching newtralchair.com")
    ap.add_argument("--amazon-html", help="use this local HTML file instead of fetching Amazon")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    if args.test_alert:
        return send_test_alerts(cfg)

    overrides = {}
    if args.newtral_json:
        overrides["newtral_site"] = Path(args.newtral_json).read_text(encoding="utf-8")
    if args.amazon_html:
        overrides["amazon"] = Path(args.amazon_html).read_text(encoding="utf-8")

    st = state_mod.load(args.state)
    now = datetime.now(timezone.utc)
    results = run_checks(cfg, overrides)
    for r in results:
        print(f"[{r.target}] {r.status}: {r.detail}")

    sent = []
    for p in decide(results, st, cfg, now):
        if notify.send(p.alert, cfg["user_agent"], cfg["timeout_seconds"], dry_run=args.dry_run):
            p.on_sent()
            sent.append(f"p{p.alert.priority} {p.alert.title}")
    write_summary(results, sent)

    if args.dry_run:
        print("[dry-run] state not written")
    elif state_mod.save(args.state, st):
        print("[state] state.json updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
