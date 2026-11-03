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

## Configuration (create / update / delete)

```bash
machina agent create --file agent.json            # POST /agent, then read back
machina agent get <name> --json > agent.json      # edit, then:
machina agent update <name|id> --file agent.json  # PUT /agent/<id>, then read back
machina agent delete <name|id> --yes               # DELETE /agent/<id>
```

| Operation | Route | Semantics |
|-----------|-------|-----------|
| create | `POST /agent` | Body is the file, as-is (`name` required). The persisted record is read back and printed. |
| read | `GET /agent/id/<id>` · `GET /agent/<name>` | `agent get`, and used for resolution and read-back. |
| update | `PUT /agent/<id>` | The server applies `$set`, so **omitted fields are kept**. `_id`, `created` and `updated` are dropped. The persisted record is read back. |
| delete | `DELETE /agent/<id>` | Asks for confirmation; `--yes` skips it, and `--json` requires it. Permission and dependency checks are the server's. |

**Configuration never changes lifecycle.** `update` does not write `status`, `scheduled`, `processing` or `last_execution`. A file that carries them with their current values (e.g. straight from `agent get --json`) round-trips fine. A file that would *change* them is refused with `lifecycle_change_refused`, because activation and scheduling are separate operations.

A rejected write exits `1` with a structured error. That covers any 4xx/5xx, and also `status: false` in an HTTP 200 body, which is how the legacy controllers report "already exists" or "Item not found". With `--json` the error goes to stdout as `{"schema": "machina.config/v1", "error", "error_code", "http_status", "details"?}`. `error_code` is one of `rejected`, `invalid_request`, `not_found`, `conflict`, `forbidden`, `unauthorized`, `server_error`, `invalid_file`, `id_mismatch`, `lifecycle_change_refused`, `confirmation_required` or `outcome_unknown`.

