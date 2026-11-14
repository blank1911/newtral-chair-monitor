from datetime import datetime, timedelta, timezone

import monitor
import state as state_mod
from checks.common import BLOCKED, ERROR, IN_STOCK, OUT_OF_STOCK, STRUCTURE_BROKEN, CheckResult
from helpers import FIXTURES, ROOT

CFG = monitor.load_config(ROOT / "config.yaml")
NOON_DENVER = datetime(2026, 11, 14, 19, 0, tzinfo=timezone.utc)  # 12:00 MST
EARLY_DENVER = datetime(2026, 11, 14, 13, 0, tzinfo=timezone.utc)  # 06:00 MST


def fresh():
    st = state_mod.default_state()
    st["last_heartbeat_date"] = "2026-11-14"  # keep heartbeats out of most tests
    return st


def deliver(pending):
    for p in pending:
        p.on_sent()
    return [p.alert for p in pending]


def site(price, status=IN_STOCK, target="newtral_site"):
    return CheckResult(target, status, f"${price}", price=price, url=f"https://example/{target}")


def run(st, *results, now=NOON_DENVER):
    return deliver(monitor.decide(list(results), st, CFG, now))


def test_no_alert_at_normal_price():
    st = fresh()
    assert run(st, site(349.99), site(349.99, target="amazon")) == []
    assert run(st, site(349.99)) == []


def test_drop_alerts_high_once():
    st = fresh()
    run(st, site(349.99))
    alerts = run(st, site(319.99))
    assert len(alerts) == 1
    a = alerts[0]
    assert a.title == "Chair price drop: $319.99 on newtralchair.com"
    assert a.priority == 4
    assert "was $349.99" in a.body
    assert a.click == "https://example/newtral_site"
    assert run(st, site(319.99)) == []


def test_further_drop_alerts_again_and_target_price_is_urgent():
    st = fresh()
    run(st, site(349.99))
    run(st, site(319.99))
    a = run(st, site(299.99))
    assert len(a) == 1 and a[0].priority == 5 and a[0].title.startswith("CHAIR AT $299.99")


def test_first_run_below_baseline_alerts():
    st = fresh()
    assert len(run(st, site(329.99))) == 1


def test_small_wiggle_ignored():
    st = fresh()
    run(st, site(349.99))
    assert run(st, site(349.49)) == []


def test_back_up_then_drop_again():
    st = fresh()
    run(st, site(349.99))
    run(st, site(319.99))
    up = run(st, site(349.99))
    assert len(up) == 1 and up[0].title.startswith("Chair price back up") and up[0].priority == 2
    assert len(run(st, site(319.99))) == 1


def test_price_rise_above_baseline_is_quiet():
    st = fresh()
    run(st, site(349.99))
    assert run(st, site(379.99)) == []
    assert run(st, site(349.99)) == []
    assert len(run(st, site(339.99))) == 1


def test_failed_send_retries_next_run():
    st = fresh()
    run(st, site(349.99))
    assert len(monitor.decide([site(319.99)], st, CFG, NOON_DENVER)) == 1  # never delivered
    assert len(monitor.decide([site(319.99)], st, CFG, NOON_DENVER)) == 1


def test_lowest_price_tracked():
    st = fresh()
    for p in (349.99, 309.99, 349.99):
        run(st, site(p))
    t = st["targets"]["newtral_site"]
    assert (t["lowest_price"], t["lowest_date"]) == (309.99, "2026-11-14")


def test_stock_changes():
    st = fresh()
    run(st, site(349.99))
    out = run(st, site(349.99, OUT_OF_STOCK))
    assert len(out) == 1 and out[0].priority == 2
    back = run(st, site(349.99))
    assert len(back) == 1 and back[0].title.startswith("Chair back in stock")


def test_amazon_blocked_is_quiet_until_threshold_then_warns_once():
    st = fresh()
    blocked = CheckResult("amazon", BLOCKED, "Amazon robot check page, skipped")
    assert run(st, blocked) == []
    assert run(st, blocked) == []
    warn = run(st, blocked)
    assert len(warn) == 1 and warn[0].title == "Chair monitor: Amazon failing"
    for _ in range(5):
        assert run(st, blocked) == []


def test_layout_change_warns_once_per_incident():
    st = fresh()
    broken = CheckResult("newtral_site", STRUCTURE_BROKEN, "variant gone")
    a = run(st, broken)
    assert len(a) == 1 and "page changed" in a[0].title
    assert run(st, broken) == []
    run(st, site(349.99))
    assert len(run(st, broken)) == 1


def test_failures_do_not_touch_price_state():
    st = fresh()
    run(st, site(349.99))
    run(st, CheckResult("newtral_site", ERROR, "timeout"))
    assert st["targets"]["newtral_site"]["price"] == 349.99
    assert run(st, site(349.99)) == []


def test_heartbeat_once_a_day_after_9am():
    st = state_mod.default_state()
    assert run(st, site(349.99), now=EARLY_DENVER) == []
    hb = run(st, site(349.99), site(349.99, target="amazon"))
    assert len(hb) == 1 and hb[0].priority == 1
    assert "newtralchair.com: $349.99 in stock" in hb[0].body
    assert run(st, site(349.99), now=NOON_DENVER + timedelta(hours=2)) == []


def test_dry_run_against_sale_fixture(capsys, tmp_path):
    state_file = tmp_path / "state.json"
    state_file.write_text("{}")
    rc = monitor.main(["--dry-run", "--state", str(state_file),
                       "--newtral-json", str(FIXTURES / "newtral_sale.json"),
                       "--amazon-html", str(FIXTURES / "amazon_current.html")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "would send p5: CHAIR AT $299.99 on newtralchair.com" in out
    assert state_file.read_text() == "{}"


def test_state_round_trip(tmp_path):
    p = tmp_path / "s.json"
    st = fresh()
    run(st, site(319.99))
    assert state_mod.save(p, st) is True
    assert state_mod.save(p, state_mod.load(p)) is False


def test_no_em_dashes_anywhere():
    for path in ROOT.rglob("*"):
        if path.is_file() and ".git" not in path.parts and path.suffix in {".py", ".md", ".yml", ".yaml", ".json", ".html"}:
            assert chr(0x2014) not in path.read_text(encoding="utf-8"), path
