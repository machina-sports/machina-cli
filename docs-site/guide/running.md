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

| Flag | Agent | Workflow | Behaviour |
|------|-------|----------|-----------|
| _(none)_ | submit-only | sync | Agent: schedule and return. Workflow: execute in the request. |
| `--sync` | sync | sync | Execute in the request, then read the **persisted run** for the real outcome |
| `--async` | — | submit-only | Schedule and return the run id |
| `--wait` / `--watch` | wait | wait (with `--async`) | Submit, then wait up to `--timeout` (default 300s) for the outcome |

**Submit-only is not completion.** It exits `0` with `outcome: "accepted"` and the run id. Check it later with `machina execution get <agent_run_id>` or `machina execution get --workflow <workflow_run_id>`, from any session.

Waiting commands (`--sync`, `--wait`, `--watch`, and a sync workflow run) exit by the run's **persisted** outcome. That covers the case where the HTTP request succeeded but the run failed.

| Exit | Outcome |
|------|---------|
| `0` | completed (a workflow that declared `skipped` also counts as completed) |
| `1` | failed, or the submission was rejected (including `status: false` in an HTTP 200) |
| `2` | partial: the agent ran, but `completed_workflows < total_workflows` |
| `3` | timeout, unknown, or a status poll that failed |

Agent waits use the server long-poll (`GET /execution/agent-run/<id>?wait=25`). Workflow waits poll `GET /workflow/schedule/<id>` every 3s. A server-supplied `outcome` field takes precedence.

**No blind retries.** If the *submission* times out, the CLI cannot know whether the run started. It prints "submission may have run — check …", exits `3`, and never resubmits. Re-running is always an explicit new `run`.

`--json` prints one document on stdout: `{"schema": "machina.execution/v1", "kind", "mode", "run_id", "outcome", "status", "result_command", "run"?, ...}`.

```bash
machina agent run my-agent                        # submit-only → agent_run_id
machina agent run my-agent --wait --timeout 600   # wait for the real outcome
machina workflow run my-workflow --async --watch  # schedule, then wait
machina execution get --workflow <workflow_run_id>
```

## See also

- [`workflow`](/commands/workflow) — all subcommands and flags.
- [`agent`](/commands/agent) — all subcommands and flags.
