Could we add a `suffixes` option to `click.Path`? A lot of my commands take a config file and I end up
writing a callback just to check the extension. I'd like to be able to write:

```python
@click.command()
@click.option("--config", type=click.Path(suffixes=(".yml", ".yaml")))
def cli(config):
    click.echo(config)
```

so that `--config app.yaml` is accepted and `--config app.json` fails with the usual usage error
(exit code 2) that names the allowed suffixes. A single string such as `suffixes=".toml"` should work
too, the comparison should be case-insensitive (`APP.YML` is fine), and the check should apply
whether or not the file exists. It should not apply to `-` when `allow_dash=True`. Default
behaviour (no `suffixes`) must stay as it is.
