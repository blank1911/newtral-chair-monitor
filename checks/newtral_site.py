"""newtralchair.com price check.

The store runs on Shopify, which publishes every product as plain JSON at
/products/<handle>.js. That is the same data the product page itself loads, so one small
GET gives the exact price (in cents) and stock flag for each size, with no HTML scraping.
"""
from __future__ import annotations

import json

from .common import (
    IN_STOCK,
    OUT_OF_STOCK,
    STRUCTURE_BROKEN,
    UNREADABLE,
    BLOCKED,
    CheckResult,
    fetch,
    looks_like_challenge,
)

TARGET = "newtral_site"


def json_url(cfg: dict) -> str:
    return f"https://newtralchair.com/products/{cfg['handle']}.js"


def product_url(cfg: dict) -> str:
    return f"https://newtralchair.com/products/{cfg['handle']}?variant={cfg['variant_id']}"


def parse(text: str, cfg: dict) -> CheckResult:
    url = product_url(cfg)
    try:
        data = json.loads(text)
    except ValueError:
        if looks_like_challenge(text):
            return CheckResult(TARGET, BLOCKED, "bot challenge page instead of product JSON", url=url)
        return CheckResult(TARGET, UNREADABLE, "product JSON did not parse", url=url)
    variants = data.get("variants") if isinstance(data, dict) else None
    if not variants:
        return CheckResult(TARGET, STRUCTURE_BROKEN, "no variants in product JSON", url=url)
    want = int(cfg["variant_id"])
    variant = next((v for v in variants if int(v.get("id", 0)) == want), None)
    if variant is None:
        names = ", ".join(str(v.get("title", "?"))[:30] for v in variants)
        return CheckResult(TARGET, STRUCTURE_BROKEN, f"variant {want} is gone; sizes now: {names}", url=url)
    try:
        price = round(int(variant["price"]) / 100, 2)
    except (KeyError, TypeError, ValueError):
        return CheckResult(TARGET, STRUCTURE_BROKEN, "variant has no usable price", url=url)
    size = str(variant.get("title", "")).split(":")[0].strip()
    status = IN_STOCK if variant.get("available") else OUT_OF_STOCK
    return CheckResult(TARGET, status, f"{size} ${price:.2f}", price=price, url=url)


def check(cfg: dict, user_agent: str, timeout: float, override: str | None = None) -> CheckResult:
    text = override if override is not None else fetch(json_url(cfg), user_agent, timeout, accept="application/json").text
    return parse(text, cfg)
