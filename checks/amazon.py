"""Amazon product page price check.

Amazon often answers requests from cloud servers (including GitHub Actions) with a robot
check page or HTTP 503. When that happens we log BLOCKED and skip. We never retry, rotate
user agents, or try to get past it. The newtralchair.com check keeps working either way.
"""
from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from .common import (
    BLOCKED,
    IN_STOCK,
    OUT_OF_STOCK,
    STRUCTURE_BROKEN,
    CheckResult,
    fetch,
    looks_like_challenge,
    normalize,
)

TARGET = "amazon"
PRICE_RE = re.compile(r"\$?\s*([0-9][0-9,]*\.?[0-9]{0,2})")
UNAVAILABLE_WORDS = ("currently unavailable", "out of stock", "temporarily out of stock")


def product_url(cfg: dict) -> str:
    return f"https://www.amazon.com/dp/{cfg['asin']}"


def _money(text: str | None) -> float | None:
    if not text:
        return None
    m = PRICE_RE.search(text.replace("\xa0", " "))
    if not m:
        return None
    try:
        value = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return value if value > 0 else None


def _price(soup: BeautifulSoup, html: str) -> float | None:
    """The price Amazon shows in the buy box, trying the most specific spot first."""
    tag = soup.find("input", id="twister-plus-price-data-price")
    if tag and _money(tag.get("value")):
        return _money(tag.get("value"))
    for sel in (
        "#corePriceDisplay_desktop_feature_div .priceToPay .a-offscreen",
        "#corePrice_feature_div .a-offscreen",
        "#corePrice_desktop .a-offscreen",
        "#apex_desktop .priceToPay .a-offscreen",
    ):
        found = soup.select_one(sel)
        if found and _money(found.get_text()):
            return _money(found.get_text())
    m = re.search(r'"priceAmount"\s*:\s*([0-9.]+)', html)
    if m:
        return _money(m.group(1))
    return None


def parse(html: str, cfg: dict) -> CheckResult:
    url = product_url(cfg)
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.find(id="productTitle")
    if title_tag is None:
        if looks_like_challenge(html):
            return CheckResult(TARGET, BLOCKED, "Amazon robot check page, skipped", url=url)
        return CheckResult(TARGET, STRUCTURE_BROKEN, "no product title on the page", url=url)
    title = normalize(title_tag.get_text(" "))
    keyword = normalize(cfg.get("title_keyword", ""))
    if keyword and keyword not in title:
        return CheckResult(TARGET, STRUCTURE_BROKEN, f"listing title changed: {title[:80]}", url=url)
    avail_tag = soup.find(id="availability")
    avail = normalize(avail_tag.get_text(" ")) if avail_tag else ""
    price = _price(soup, html)
    if any(w in avail for w in UNAVAILABLE_WORDS):
        return CheckResult(TARGET, OUT_OF_STOCK, f"Amazon: {avail[:60]}", price=price, url=url)
    if price is None:
        return CheckResult(TARGET, STRUCTURE_BROKEN, "product page has no price in the buy box", url=url)
    return CheckResult(TARGET, IN_STOCK, f"Amazon ${price:.2f}", price=price, url=url)


def check(cfg: dict, user_agent: str, timeout: float, override: str | None = None) -> CheckResult:
    html = override if override is not None else fetch(product_url(cfg), user_agent, timeout).text
    return parse(html, cfg)
