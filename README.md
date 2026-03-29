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

# 2. List your organizations
machina org list

# 3. List your projects
machina project list

# 4. Select a project to work with
machina project use <project-id>

# 5. Explore project resources
machina workflow list
machina agent list
machina template list
```

## Authentication

The CLI supports three authentication methods:

| Method | Command | Use case |
|--------|---------|----------|
| **Browser** (default) | `machina login` | Interactive use — opens browser for Clerk SSO / magic link |
| **API Key** | `machina login --api-key <key>` | CI/CD pipelines and scripts |
| **Username/Password** | `machina login --with-credentials` | Internal / dev environments |

Credentials are stored securely in your OS keychain (macOS Keychain, Windows Credential Manager, or Linux Secret Service).

## Commands

### Platform

```bash
machina login                          # Authenticate (browser-based)
machina login --api-key <key>          # Authenticate with API key
machina auth logout                    # Clear stored credentials
machina auth whoami                    # Show current user info
```

### Organizations

```bash
machina org list                       # List organizations
machina org create <name>              # Create organization
machina org use <org-id>               # Set default organization
```

### Projects

```bash
machina project list                   # List projects
machina project create <name>          # Create project
machina project use <project-id>       # Set default project
machina project status                 # Deployment status
```

### Workflows

```bash
machina workflow list                  # List workflows
machina workflow get <name>            # Get workflow details
```

### Agents

```bash
machina agent list                     # List agents
machina agent get <name>               # Get agent details
machina agent executions               # List recent executions
```

### Templates

```bash
machina template list                  # Browse template repository
machina template list --json           # Output as JSON
```

### Credentials

```bash
machina credentials list               # List API keys
machina credentials generate           # Generate new API key
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
```

## Global Options

Most list commands support:

| Flag | Description |
|------|-------------|
| `--json`, `-j` | Output raw JSON (useful for piping to `jq`) |
| `--project`, `-p` | Override default project for this command |
| `--limit`, `-l` | Items per page (default: 20) |
| `--page` | Page number for pagination |

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
