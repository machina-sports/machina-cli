# machina-cli

CLI for the Machina AI Agent platform.

## Install

### macOS / Linux (one-liner)

```bash
curl -fsSL https://raw.githubusercontent.com/machina-sports/machina-cli/main/install.sh | bash
```

### Windows (PowerShell)

```powershell
irm https://raw.githubusercontent.com/machina-sports/machina-cli/main/install.ps1 | iex
```

### PyPI

```bash
pip install machina-cli
```

### From source

```bash
git clone https://github.com/machina-sports/machina-cli.git
cd machina-cli
pip install -e .
```

## Usage

```bash
machina --help
machina login --api-key <your-key>
machina org list
machina project list
machina credentials list
machina deploy start
```
