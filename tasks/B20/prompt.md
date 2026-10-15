We have a long-running service that keeps an `astropy.table.Table` in memory (a few hundred thousand rows) and looks rows up by a key column. The key column is a `MaskedColumn` (some keys are missing) of ISO timestamp strings, and we call `t.add_index("idx")` on it so lookups are fast.

Each request does something like:

```python
rows = t[t["idx"] == key]
```

The results are always correct, but the process's memory grows on every request, without bound. In production it reached 18 GB before being killed. `gc.collect()` does not release anything, and the growth stops if we drop the index or use a plain `Column` instead of a `MaskedColumn`. The amount leaked per request seems to scale with the size of the indexed column.

A small reproduction:

```python
import numpy as np
from astropy.table import Table, MaskedColumn

size = 200_000
vals = np.array([f"2000-01-01T00:00:{i % 60:02d}.000" for i in range(size)])
t = Table({"a": np.arange(size), "idx": MaskedColumn(vals)})
t.add_index("idx")

for v in t["idx"][:200]:
    t[t["idx"] == v]   # memory keeps climbing
```

Please find and fix the cause in astropy, add a regression test, and keep the existing tests passing.
