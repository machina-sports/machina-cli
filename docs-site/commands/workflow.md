# workflow

Workflows compose connectors, prompts, and mappings into reusable, schedulable pipelines. See [Running agents & workflows](/guide/running) for the input and execution-mode model.

## Usage

```bash
machina workflow list                       # list workflows
machina workflow list --limit 50            # paginate
machina workflow list --json                # output as JSON
machina workflow get <name>                 # get workflow details
machina workflow run <name>                 # run (interactive input prompts)
machina workflow run <name> key=value       # run with inline parameters
machina workflow run <name> --async         # schedule and return
machina workflow run <name> --async --watch # schedule and watch progress
```

## Subcommands

| Command | Description |
|---------|-------------|
| `workflow list` | List workflows in the project |
| `workflow get <name>` | Show workflow details |
| `workflow run <name>` | Run a workflow (sync by default) |

## Running

Workflows run **synchronously** by default — the CLI waits for the result. Pass `--async` to schedule and return, and `--watch` to poll until complete.

```bash
machina workflow run my-workflow limit=10 market_id=abc
machina workflow run my-workflow --async --watch
```

See [Running agents & workflows](/guide/running) for the full mode matrix.
