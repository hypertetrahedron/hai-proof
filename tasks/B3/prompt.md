Since we upgraded, our terminal dashboard draws panels in the wrong place and some live changes never show up.

The screen is a `Layout`: a narrow sidebar with two stacked panels on the left, and a main area on the right that shows a table of running jobs.

```python
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

status = Text("starting")
jobs = Table("job", "status")
jobs.add_row("build", status)

layout = Layout(name="root")
layout.split_row(Layout(name="sidebar", size=14), Layout(name="main"))
layout["sidebar"].split_column(
    Layout(Panel("Services"), name="services"),
    Layout(Panel("Queue"), name="queue"),
)
layout["main"].update(Panel(jobs))

console = Console(width=60, height=14)
console.print(layout)
```

Three problems:

1. The "Queue" panel should sit under "Services" in the sidebar. Instead it is drawn on the far right, next to the lower half of the main panel, and the rows it lands on are the wrong width, so the right-hand border is ragged. With only two top-level panels side by side everything is fine. It only goes wrong once one of the columns is itself split.

2. We let users widen the sidebar with a key binding (`layout["sidebar"].size = 24`, then redraw). Nothing changes on screen. Changing a panel's `ratio` or `minimum_size` at runtime does nothing either. If we build a brand new `Layout` with the new numbers it renders correctly, so the numbers themselves are fine.

3. When a job finishes we update the `Text` we put in the table (`status.plain = "finished successfully"`) and redraw. The table keeps its old column width, so the new text is wrapped and cut off with an ellipsis. A new `Table` built with the same text is laid out correctly. Editing a column's `header` or `max_width` after the first draw has the same problem.

I assumed the Panels were the problem and spent a while on their `expand`/`height` options. I also tried `layout.refresh_screen(...)` and wrapping everything in `Live(screen=True)`, but the result was the same. Could you work out what is going wrong and fix it?
