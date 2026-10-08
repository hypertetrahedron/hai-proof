from inventory import Inventory


def test_item_exactly_at_reorder_level_is_low():
    inv = Inventory()
    inv.add("widget", 12, reorder_level=5)
    inv.remove("widget", 7)
    assert inv.quantity("widget") == 5
    assert inv.low_stock() == ["widget"]


def test_mixed_levels():
    inv = Inventory()
    inv.add("a", 5, reorder_level=5)
    inv.add("b", 6, reorder_level=5)
    inv.add("c", 0, reorder_level=0)
    assert inv.low_stock() == ["a", "c"]
