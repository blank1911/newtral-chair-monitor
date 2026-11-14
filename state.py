"""state.json: what the monitor remembers between runs.

Only facts that change on real events are stored (no "last run" timestamp), so the workflow
commits state.json only when something actually happened.
"""
from __future__ import annotations

import json
from pathlib import Path


def default_state() -> dict:
    return {
        "targets": {},
        "last_heartbeat_date": None,
        "last_keepalive": None,
    }


def default_target() -> dict:
    return {
        "status": None,             # IN_STOCK / OUT_OF_STOCK from the last good read
        "price": None,              # last price read
        "reference_price": None,    # price a drop is measured from (last alerted price, or baseline)
        "lowest_price": None,
        "lowest_date": None,
        "last_result": None,
        "detail": "",
        "consecutive_failures": 0,
        "failure_alert_sent": False,
        "open_incident": None,
    }


def load(path: str | Path) -> dict:
    state = default_state()
    p = Path(path)
    if p.exists() and p.read_text(encoding="utf-8").strip():
        loaded = json.loads(p.read_text(encoding="utf-8"))
        state.update({k: v for k, v in loaded.items() if k in state})
    for name, t in list(state["targets"].items()):
        state["targets"][name] = {**default_target(), **t}
    return state


def target(state: dict, name: str) -> dict:
    return state["targets"].setdefault(name, default_target())


def dumps(state: dict) -> str:
    return json.dumps(state, indent=2, sort_keys=True) + "\n"


def save(path: str | Path, state: dict) -> bool:
    """Write state if its content changed. Returns True when the file was written."""
    p = Path(path)
    new = dumps(state)
    old = p.read_text(encoding="utf-8") if p.exists() else ""
    if new == old:
        return False
    p.write_text(new, encoding="utf-8", newline="\n")
    return True
