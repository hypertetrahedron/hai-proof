import pytest

from inventory import Inventory, OutOfStockError, UnknownSkuError


def test_add_and_quantity():
    inv = Inventory()
    inv.add("widget", 3)
    inv.add("widget", 2)
    assert inv.quantity("widget") == 5


def test_remove():
    inv = Inventory()
    inv.add("widget", 5)
    inv.remove("widget", 2)
    assert inv.quantity("widget") == 3


def test_remove_too_many():
    inv = Inventory()
    inv.add("widget", 1)
    with pytest.raises(OutOfStockError):
        inv.remove("widget", 2)


def test_unknown_sku():
    with pytest.raises(UnknownSkuError):
        Inventory().quantity("nope")


def test_low_stock_below_level():
    inv = Inventory()
    inv.add("bolt", 2, reorder_level=10)
    inv.add("nut", 50, reorder_level=10)
    assert inv.low_stock() == ["bolt"]
