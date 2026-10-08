Clamping on an open-bounded `click.IntRange` goes the wrong way. With `clamp=True` and an open
bound, an out-of-range value should be moved to the nearest value that is actually allowed (just
inside the range), but I get a value outside the range instead.

```python
import click

@click.command()
@click.option("--level", type=click.IntRange(0, 10, min_open=True, max_open=True, clamp=True), default=5)
def cli(level):
    click.echo(f"level={level}")

if __name__ == "__main__":
    cli()
```

```
$ python repro.py --level=0
level=-1
$ python repro.py --level=99
level=11
```

Expected `level=1` and `level=9` respectively (the range is 1..9 inclusive since both ends are
open). Closed bounds with `clamp=True` still behave correctly.
