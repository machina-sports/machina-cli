# execution

Executions are the run records produced when agents and workflows run. Inspect any run by id.

## Usage

```bash
machina execution list                 # list recent executions
machina execution list --limit 50      # paginate
machina execution get <id>             # get execution details
machina execution get <id> --compact   # compact output
machina execution get <id> --json      # full JSON output
```

## Subcommands

| Command | Description |
|---------|-------------|
| `execution list` | List recent executions |
| `execution get <id>` | Show execution details (use `--compact` or `--json`) |

::: tip
`machina agent run … --watch` and `machina workflow run … --watch` already follow a run to completion. Use `execution get <id>` to revisit a run later, or to inspect one started elsewhere — Studio, the API, or a schedule.
:::
