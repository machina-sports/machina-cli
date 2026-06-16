# agent

Agents are specialized AI systems for fan engagement, content, and real-time interaction. See [Running agents & workflows](/guide/running) for the input and execution-mode model.

## Usage

```bash
machina agent list                     # list agents
machina agent list --json              # output as JSON
machina agent get <name>               # details (workflows, context, activity)
machina agent run <name>               # run (interactive input prompts)
machina agent run <name> key=value     # run with inline parameters
machina agent run <name> --sync        # run and wait for the result
machina agent run <name> --watch       # run async and watch progress
machina agent executions               # list recent executions
```

## Subcommands

| Command | Description |
|---------|-------------|
| `agent list` | List agents in the project |
| `agent get <name>` | Show agent details — workflows, context, recent activity |
| `agent run <name>` | Run an agent (async by default) |
| `agent executions` | List recent agent executions |

## Running

Agents run **asynchronously** by default — they schedule and return a run id. Pass `--sync` to wait for the result, or `--watch` to poll until complete.

```bash
machina agent run my-agent season_id=sr:season:123 --watch
machina agent run my-agent --sync
```

See [Running agents & workflows](/guide/running) for the full mode matrix, and [`execution`](/commands/execution) to inspect any run by id.
