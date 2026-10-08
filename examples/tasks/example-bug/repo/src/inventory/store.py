"""In-memory stock store."""

from __future__ import annotations

from dataclasses import dataclass


class UnknownSkuError(KeyError):
    """Raised when a SKU has never been added."""


class OutOfStockError(ValueError):
    """Raised when removing more units than are on hand."""


@dataclass
class _Entry:
    quantity: int
    reorder_level: int


class Inventory:
    """Tracks units on hand per SKU, with an optional reorder level for each."""

    def __init__(self) -> None:
        self._items: dict[str, _Entry] = {}

    def add(self, sku: str, quantity: int, reorder_level: int = 0) -> None:
        """Add `quantity` units of `sku`, creating it if needed."""
        if quantity < 0:
            raise ValueError("quantity must be non-negative")
        entry = self._items.get(sku)
        if entry is None:
            self._items[sku] = _Entry(quantity, reorder_level)
        else:
            entry.quantity += quantity
            entry.reorder_level = reorder_level

    def remove(self, sku: str, quantity: int) -> None:
        """Remove `quantity` units of `sku`."""
        entry = self._entry(sku)
        if quantity > entry.quantity:
            raise OutOfStockError(f"only {entry.quantity} of {sku!r} on hand")
        entry.quantity -= quantity

    def quantity(self, sku: str) -> int:
        return self._entry(sku).quantity

    def low_stock(self) -> list[str]:
        """SKUs whose quantity is at or below their reorder level, sorted by name."""
        return sorted(
            sku for sku, e in self._items.items() if e.quantity < e.reorder_level
        )

    def _entry(self, sku: str) -> _Entry:
        try:
            return self._items[sku]
        except KeyError:
            raise UnknownSkuError(sku) from None
