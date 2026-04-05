# machina-cli

The official command-line interface for the [Machina Sports](https://machina.gg) AI Agent platform.

Manage organizations, projects, workflows, agents, skills, and templates directly from your terminal.

The CLI is intentionally a thin shell. The built-in authoring bridge for creating new skills/templates/connectors is `mkn-constructor` from `machina-templates`.

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
machina skills list
machina template list
```

## Interactive Session

Run `machina` with no arguments to open an interactive REPL:

```
$ machina

  ✦ Machina CLI v0.2.2
  Organization: Acme Corp
  Project:      demo-project

  Type a command (e.g. `workflow list`) or `help` for commands.
  Press Ctrl+D or type `exit` to quit.

✦ Acme Corp/demo-project > workflow list
✦ Acme Corp/demo-project > agent list
✦ Acme Corp/demo-project > project list limit 5
✦ Acme Corp/demo-project > exit
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
machina workflow run <name>            # Run workflow (interactive input prompts)
machina workflow run <name> key=value  # Run with inline parameters
machina workflow run <name> --async    # Run async (schedule and return)
machina workflow run <name> --async --watch  # Run async and watch progress
```

### Agents

```bash
machina agent list                     # List agents
machina agent list --json              # Output as JSON
machina agent get <name>               # Get agent details (workflows, context, activity)
machina agent run <name>               # Run agent (interactive input prompts)
machina agent run <name> key=value     # Run with inline parameters
machina agent run <name> --sync        # Run and wait for result
machina agent run <name> --watch       # Run async and watch progress
machina agent executions               # List recent executions
```

### Connectors

```bash
machina connector list                 # List connectors
machina connector list --json          # Output as JSON
machina connector get <name>           # Get connector details
```

### Mappings

```bash
machina mapping list                   # List mappings
machina mapping list --json            # Output as JSON
machina mapping get <name>             # Get mapping details
```

### Prompts

```bash
machina prompt list                    # List prompts
machina prompt list --json             # Output as JSON
machina prompt get <name>              # Get prompt with content preview
```

### Documents

```bash
machina document list                  # List documents
machina document list --limit 50       # Paginate
machina document list --json           # Output as JSON
machina document get <id>              # Get document with content preview
```

### Executions

```bash
machina execution list                 # List recent executions
machina execution list --limit 50      # Paginate
machina execution get <id>             # Get execution details
machina execution get <id> --compact   # Compact output
machina execution get <id> --json      # Full JSON output
```

### Skills

```bash
machina skills list                    # Browse skills/packages from the registry
machina skills install <path>          # Install a skill/package
machina skills info <path>             # Show expected skill manifest files
machina skills run <name>              # Skills-first run surface (bridge placeholder)
machina skills push <path>             # Push a local skill/package
machina skills constructor             # Install and use mkn-constructor as the authoring bridge
```

### Templates (compatibility surface)

```bash
machina template list                  # Browse template repository
machina template list --repo <url>     # Browse a custom repository
machina template list --branch dev     # Specific branch
machina template list --json           # Output as JSON
machina template install <path>        # Install a template/package
machina template push <path>           # Push a local template/package
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

## Running Agents & Workflows

The CLI can run agents and workflows directly from the terminal — just like the Studio UI.

### Interactive mode

When you run without parameters, the CLI fetches the available inputs and prompts you:

```
$ machina workflow run assistant-tools-event-matcher

  Workflow: assistant-tools-event-matcher
  Tool for matching events to markets

  Available inputs: (press Enter to skip)

  competitionIds:
  externalSeasonId: sr:season:123
  limit (default: 50): 10
  market_id:

  Running workflow: assistant-tools-event-matcher
  externalSeasonId=sr:season:123
  limit=10

  Executing workflow...
```

### Inline mode

Pass parameters directly as `key=value` pairs:

```bash
machina agent run my-agent season_id=sr:season:123 force=true
machina workflow run my-workflow limit=10 market_id=abc
```

### Execution modes

| Flag | Agent default | Workflow default | Behavior |
|------|--------------|-----------------|----------|
| (none) | async | sync | Agent schedules, workflow waits |
| `--sync` | sync | sync | Wait for result |
| `--async` | async | async | Schedule and return |
| `--watch` | poll 3s | poll 3s | Watch until complete |

```bash
machina agent run my-agent --watch              # Run and watch progress
machina workflow run my-workflow --async --watch # Schedule and watch
machina agent run my-agent --sync               # Wait for full result
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
