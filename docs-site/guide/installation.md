# Installation

The CLI ships as a self-contained install script and on PyPI. Pick whichever fits your environment.

## macOS / Linux

```bash
curl -fsSL https://raw.githubusercontent.com/machina-sports/machina-cli/main/install.sh | bash
```

## Windows (PowerShell)

```powershell
irm https://raw.githubusercontent.com/machina-sports/machina-cli/main/install.ps1 | iex
```

## PyPI

If you already manage Python tools, install from PyPI:

```bash
pip install machina-cli
# or, isolated in its own environment:
pipx install machina-cli
```

::: tip
`pipx` keeps the CLI and its dependencies isolated from your other Python projects — recommended when it's available.
:::

## Verify

```bash
machina version          # -> prints the installed version, e.g. machina-cli 0.4.9
```

## Update

Update in place at any time:

```bash
machina update           # update to the latest version
machina update --force   # force a re-install even if already current
```

See [`update`](/commands/update) for details.

## Install from source

For local development on the CLI itself:

```bash
git clone https://github.com/machina-sports/machina-cli.git
cd machina-cli
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
machina version
```

## Next up

[Authenticate and run your first command →](/guide/quickstart)
