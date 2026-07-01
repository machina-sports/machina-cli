# org

Manage the organizations you belong to and set the default used by every other command.

## Usage

```bash
machina org list                       # list organizations
machina org list --limit 5             # paginate (5 per page)
machina org list --page 2              # page 2
machina org list --json                # output as JSON
machina org create <name>              # create an organization
machina org use <org-id>               # set the default organization
machina org usage                      # LLM token consumption rollup (last 30d)
machina org usage --days 7 --top 10    # window + top-N breakdown
```

## Subcommands

| Command | Description |
|---------|-------------|
| `org list` | List organizations you belong to |
| `org create <name>` | Create a new organization |
| `org use <org-id>` | Set the default organization (writes `default_organization_id` to config) |
| `org usage` | Aggregate LLM token consumption across the org's agent executions |

`list` supports the global `--limit`, `--page`, and `--json` flags — see [Configuration → Global flags](/guide/configuration#global-flags).

## usage — token consumption

`machina org usage` answers **"how many LLM tokens did this org consume"**. Token usage is recorded on **agent** executions (`execution_tokens`), and the Client-API totals are page-level only, so the command iterates the org's projects, paginates + sums client-side, and breaks the total down by **project, agent, and day** — surfacing the prompt/completion split (the cost-shape signal).

```bash
machina org usage --days 30 --top 10 --json
```

| Flag | Purpose | Default |
|------|---------|---------|
| `--org`, `-o` | Organization (defaults to the selected org) | selected org |
| `--project`, `-p` | Scope to a single project | all projects |
| `--days` | Rolling window (a frozen upper bound keeps pagination stable) | `30` |
| `--top` | Top-N agents/projects in the breakdown | — |
| `--limit` | Max rows | — |
| `--json`, `-j` | Machine-readable output | — |

Unreachable / undeployed projects are listed under `projects_unreachable` rather than failing the run; a project that is reachable but errors mid-scan flags the run **INCOMPLETE / PARTIAL** (a partial total is never presented as if it were whole).
