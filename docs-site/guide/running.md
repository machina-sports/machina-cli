# Running agents & workflows

The CLI runs agents and workflows directly from the terminal — just like the Studio playground. Both `agent run` and `workflow run` share the same input and execution-mode model.

## Interactive mode

Run without parameters and the CLI fetches the available inputs and prompts you for each one:

```text
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

## Inline mode

Pass parameters directly as `key=value` pairs:

```bash
machina agent run my-agent season_id=sr:season:123 force=true
machina workflow run my-workflow limit=10 market_id=abc
```

## Execution modes

| Flag | Agent default | Workflow default | Behavior |
|------|---------------|------------------|----------|
| _(none)_ | async | sync | Agent schedules; workflow waits |
| `--sync` | sync | sync | Wait for the result |
| `--async` | async | async | Schedule and return |
| `--watch` | poll 3s | poll 3s | Watch until complete |

```bash
machina agent run my-agent --watch                # run and watch progress
machina workflow run my-workflow --async --watch  # schedule, then watch
machina agent run my-agent --sync                 # wait for the full result
```

::: info
Agents default to **async** (they schedule and return a run id); workflows default to **sync** (they wait for the result). Use the flags above to override either default.
:::

## See also

- [`workflow`](/commands/workflow) — all subcommands and flags.
- [`agent`](/commands/agent) — all subcommands and flags.
