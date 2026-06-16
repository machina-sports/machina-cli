# update

Keep the CLI current, and check which version you're running.

## Usage

```bash
machina update                         # update to the latest version
machina update --force                 # force a re-install even if current
machina version                        # show the installed version
```

## Options

| Flag | Short | Description |
|------|-------|-------------|
| `--force` | `-f` | Update even if already on the latest version |

::: tip
Installed from PyPI? You can also update with `pip install --upgrade machina-cli` (or `pipx upgrade machina-cli`). `machina update` works regardless of how you installed.
:::
