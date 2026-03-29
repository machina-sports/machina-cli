# machina-cli

The official command-line interface for the [Machina Sports](https://machina.gg) AI Agent platform.

Manage organizations, projects, workflows, agents, and templates directly from your terminal.

## Install

### macOS / Linux

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
# or
pipx install machina-cli
```

## Quick Start

```bash
# 1. Authenticate (opens browser)
machina login

# 2. List your organizations and select one
machina org list
machina org use <org-id>

# 3. List your projects and select one
machina project list
machina project use <project-id>

# 4. Explore project resources
machina workflow list
machina agent list
machina template list
```

## Interactive Session

Run `machina` with no arguments to open an interactive REPL:

```
$ machina

  ✦ Machina CLI v0.2.2
  Organization: Entain Organization
  Project:      sbot-stg

  Type a command (e.g. `workflow list`) or `help` for commands.
  Press Ctrl+D or type `exit` to quit.

✦ Entain Organization/sbot-stg > workflow list
✦ Entain Organization/sbot-stg > agent list
✦ Entain Organization/sbot-stg > project list limit 5
✦ Entain Organization/sbot-stg > exit
```

Inside the session you can type commands without the `machina` prefix and without `--` before flags:

```
workflow list              # same as: machina workflow list
project list limit 5       # same as: machina project list --limit 5
credentials list json      # same as: machina credentials list --json
```

Features: tab completion, command history (persisted in `~/.machina/history`), current org/project in prompt.

## Authentication

The CLI supports three authentication methods:

| Method | Command | Use case |
|--------|---------|----------|
| **Browser** (default) | `machina login` | Interactive use — opens browser for Clerk SSO / magic link |
| **API Key** | `machina login --api-key <key>` | CI/CD pipelines and scripts |
| **Username/Password** | `machina login --with-credentials` | Internal / dev environments |

Credentials are stored locally in `~/.machina/credentials.json` (file permissions `600`).

## Commands

### Platform

```bash
machina login                          # Authenticate (browser-based)
machina login --api-key <key>          # Authenticate with API key
machina login --with-credentials       # Authenticate with username/password
machina auth logout                    # Clear stored credentials
machina auth whoami                    # Show current user info
```

### Organizations

```bash
machina org list                       # List organizations
machina org list --limit 5             # Paginate (5 per page)
machina org list --page 2              # Page 2
machina org list --json                # Output as JSON
machina org create <name>              # Create organization
machina org use <org-id>               # Set default organization
```

### Projects

```bash
machina project list                   # List projects
machina project list --limit 10        # Paginate (10 per page)
machina project list --json            # Output as JSON
machina project create <name>          # Create project
machina project use <project-id>       # Set default project
machina project status                 # Deployment status
```

### Workflows

```bash
machina workflow list                  # List workflows
machina workflow list --limit 50       # Paginate
machina workflow list --json           # Output as JSON
machina workflow get <name>            # Get workflow details
machina workflow get <name> --json     # Workflow details as JSON
```

### Agents

```bash
machina agent list                     # List agents
machina agent list --json              # Output as JSON
machina agent get <name>               # Get agent details
machina agent get <name> --json        # Agent details as JSON
machina agent executions               # List recent executions
```

### Executions

```bash
machina execution list                 # List recent executions
machina execution list --limit 50      # Paginate
machina execution get <id>             # Get execution details
machina execution get <id> --compact   # Compact output
machina execution get <id> --json      # Full JSON output
```

### Templates

```bash
machina template list                  # Browse template repository
machina template list --repo <url>     # Browse a custom repository
machina template list --branch dev     # Specific branch
machina template list --json           # Output as JSON
```

### Credentials

```bash
machina credentials list               # List API keys (masked)
machina credentials list --show-keys   # List API keys (full)
machina credentials list --copy client-api  # Copy key to clipboard
machina credentials generate           # Generate new API key
machina credentials generate --name my-key  # Custom key name
machina credentials revoke <key-id>    # Revoke an API key
```

### Deployment

```bash
machina deploy start                   # Deploy Client API
machina deploy status                  # Check deployment status
machina deploy restart                 # Restart deployment
```

### Configuration

```bash
machina config list                    # Show all settings
machina config set <key> <value>       # Update a setting
machina config get <key>               # Read a setting
```

### Self-update

```bash
machina update                         # Update to latest version
machina update --force                 # Force re-install
machina version                        # Show current version
```

## Global Options

All list commands support pagination and JSON output:

| Flag | Short | Description |
|------|-------|-------------|
| `--limit` | `-l` | Items per page (default: 20) |
| `--page` | | Page number for pagination |
| `--json` | `-j` | Output raw JSON (useful for piping to `jq`) |
| `--project` | `-p` | Override default project for this command |

Examples:

```bash
machina project list --limit 5 --page 2    # 5 items, page 2
machina workflow list --json | jq '.[].name'  # Pipe to jq
machina agent list -p <other-project-id>   # Different project
```

## Configuration

Config is stored in `~/.machina/config.json`:

```bash
machina config set api_url https://api.machina.gg
machina config set session_url https://session.machina.gg
machina config set default_organization_id <org-id>
machina config set default_project_id <project-id>
```

Environment variables override config file values:

| Variable | Description |
|----------|-------------|
| `MACHINA_API_KEY` | API key for authentication |
| `MACHINA_API_URL` | Override Core API URL |

### Shell Prompt Integration

Show current org/project in your terminal prompt:

```bash
# Add to .zshrc or .bashrc
precmd() { RPROMPT=$(machina shell-prompt 2>/dev/null); }
```

## Development

```bash
git clone https://github.com/machina-sports/machina-cli.git
cd machina-cli
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
machina version
```

## License

MIT
