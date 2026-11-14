from checks import newtral_site
from checks.common import BLOCKED, IN_STOCK, OUT_OF_STOCK, STRUCTURE_BROKEN, UNREADABLE
from helpers import FIXTURES, ROOT
import monitor

CFG = monitor.load_config(ROOT / "config.yaml")["targets"]["newtral_site"]


def read(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_current_price_is_medium_large_not_cheapest():
    r = newtral_site.parse(read("newtral_current.json"), CFG)
    assert (r.status, r.price) == (IN_STOCK, 349.99)
    assert r.detail.startswith("Medium/Large")
    assert "variant=41672021115013" in r.url


def test_sale_price():
    assert newtral_site.parse(read("newtral_sale.json"), CFG).price == 299.99


def test_sold_out():
    r = newtral_site.parse(read("newtral_sold_out.json"), CFG)
    assert (r.status, r.price) == (OUT_OF_STOCK, 349.99)


def test_variant_gone_is_structure_broken():
    r = newtral_site.parse(read("newtral_variant_gone.json"), CFG)
    assert r.status == STRUCTURE_BROKEN
    assert "Small" in r.detail


def test_html_instead_of_json():
    assert newtral_site.parse("<html>oops</html>", CFG).status == UNREADABLE
    assert newtral_site.parse("<html><title>Just a moment...</title></html>", CFG).status == BLOCKED
