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

## Automatic update notices

You don't have to remember to check. Any `machina` command opportunistically checks for a newer release (at most once a day) and prints a one-line notice after its own output if one is available:

```text
$ machina workflow list
...

A new version of machina-cli is available: 0.5.2 → 0.5.3
Run machina update to upgrade.
```

This never slows a command down — a fresh check is cached locally (`~/.machina/update_check.json`); a stale cache refreshes in the background with a short budget, so a slow network just means "check again next time" instead of a delay. It's automatically silent for `--json` output and piped/non-interactive usage, so it never lands in a script's output.
