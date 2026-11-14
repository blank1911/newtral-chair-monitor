from unittest import mock

import requests

from checks import amazon
from checks.common import BLOCKED, IN_STOCK, OUT_OF_STOCK, STRUCTURE_BROKEN, fetch, run_safely
from helpers import FIXTURES, ROOT
import monitor

CFG = monitor.load_config(ROOT / "config.yaml")["targets"]["amazon"]


def read(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_current_price():
    r = amazon.parse(read("amazon_current.html"), CFG)
    assert (r.status, r.price) == (IN_STOCK, 349.99)
    assert r.url == "https://www.amazon.com/dp/B0H3699JFY"


def test_sale_price_ignores_list_price():
    assert amazon.parse(read("amazon_sale.html"), CFG).price == 289.99


def test_falls_back_to_buy_box_price():
    r = amazon.parse(read("amazon_no_twister.html"), CFG)
    assert (r.status, r.price) == (IN_STOCK, 329.99)


def test_unavailable():
    assert amazon.parse(read("amazon_unavailable.html"), CFG).status == OUT_OF_STOCK


def test_robot_check_is_blocked_not_broken():
    assert amazon.parse(read("amazon_robot_check.html"), CFG).status == BLOCKED


def test_wrong_listing_is_flagged():
    cfg = {**CFG, "title_keyword": "gaming chair"}
    assert amazon.parse(read("amazon_current.html"), cfg).status == STRUCTURE_BROKEN


def _resp(code, text):
    r = requests.Response()
    r.status_code, r._content = code, text.encode()
    return r


def test_503_robot_page_and_429_are_blocked():
    for code, body in ((503, read("amazon_robot_check.html")), (429, ""), (403, "")):
        with mock.patch("checks.common.requests.get", return_value=_resp(code, body)):
            r = run_safely("amazon", amazon.check, CFG, "ua", 15)
        assert r.status == BLOCKED, code


def test_one_request_with_polite_headers():
    with mock.patch("checks.common.requests.get", return_value=_resp(200, read("amazon_current.html"))) as get:
        amazon.check(CFG, "my-ua", 15)
    assert get.call_count == 1
    assert get.call_args.kwargs["headers"]["User-Agent"] == "my-ua"
    assert get.call_args.kwargs["timeout"] == 15
