Our reorder report is missing items. `Inventory.low_stock()` is documented as returning SKUs whose quantity is "at or below" their reorder level, but a SKU that has dropped exactly to its reorder level doesn't show up.

Repro:

```python
from inventory import Inventory

inv = Inventory()
inv.add("widget", 12, reorder_level=5)
inv.remove("widget", 7)          # 5 left, reorder level is 5
print(inv.low_stock())           # prints []   (expected ['widget'])
```

The warehouse only noticed once the widgets were already at zero. Can you fix it?
