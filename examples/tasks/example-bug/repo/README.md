# inventory

A tiny in-memory stock tracker.

```python
from inventory import Inventory

inv = Inventory()
inv.add("widget", 12, reorder_level=5)
inv.remove("widget", 7)
inv.low_stock()   # SKUs that need reordering
```
