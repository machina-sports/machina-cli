# Configuration & global flags

## Config file

Configuration lives in `~/.machina/config.json`. Read and write it with the [`config`](/commands/config) command, or set common keys directly:

```bash
machina config list                              # show all settings
machina config get <key>                         # read one setting
machina config set <key> <value>                 # update a setting

machina config set api_url https://api.machina.gg
machina config set session_url https://session.machina.gg
machina config set default_organization_id <org-id>
machina config set default_project_id <project-id>
```

`machina org use` and `machina project use` write the `default_organization_id` / `default_project_id` keys for you.

## Environment variables

Environment variables override config-file values:

| Variable | Description |
|----------|-------------|
| `MACHINA_API_KEY` | API key for authentication |
| `MACHINA_API_URL` | Override the Core API URL |

## Global flags

Every `list` command supports pagination and JSON output:

| Flag | Short | Description |
|------|-------|-------------|
| `--limit` | `-l` | Items per page (default: 20) |
| `--page` | | Page number for pagination |
| `--json` | `-j` | Output raw JSON (pipe it to `jq`) |
| `--project` | `-p` | Override the default project for this command |

```bash
machina project list --limit 5 --page 2        # 5 items, page 2
machina workflow list --json | jq '.[].name'   # pipe to jq
machina agent list -p <other-project-id>       # a different project
```

## Shell prompt integration

Show your current org/project in your terminal prompt:

```bash
# Add to .zshrc or .bashrc
precmd() { RPROMPT=$(machina shell-prompt 2>/dev/null); }
```

`machina shell-prompt` prints a compact `✦ org/project` marker (and nothing when you're not logged in), so it's safe to call on every prompt.
