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

## Configuration (create / update / delete)

```bash
machina workflow create --file workflow.json            # POST /workflow, then read back
machina workflow get <name> --json > workflow.json      # edit, then:
machina workflow update <name|id> --file workflow.json  # PUT /workflow/<id>, then read back
machina workflow delete <name|id> --yes               # DELETE /workflow/<id>
```

| Operation | Route | Semantics |
|-----------|-------|-----------|
| create | `POST /workflow` | Body is the file, as-is (`name` required). The persisted record is read back and printed. |
| read | `GET /workflow/id/<id>` · `GET /workflow/<name>` | `workflow get`, and used for resolution and read-back. |
| update | `PUT /workflow/<id>` | The server applies `$set`, so **omitted fields are kept**. `_id`, `created` and `updated` are dropped. The persisted record is read back. |
| delete | `DELETE /workflow/<id>` | Asks for confirmation; `--yes` skips it, and `--json` requires it. Permission and dependency checks are the server's. |

**Configuration never changes lifecycle.** `update` does not write `status`, `scheduled`, `processing` or `last_execution`. A file that carries them with their current values (e.g. straight from `workflow get --json`) round-trips fine. A file that would *change* them is refused with `lifecycle_change_refused`, because activation and scheduling are separate operations.

A rejected write exits `1` with a structured error. That covers any 4xx/5xx, and also `status: false` in an HTTP 200 body, which is how the legacy controllers report "already exists" or "Item not found". With `--json` the error goes to stdout as `{"schema": "machina.config/v1", "error", "error_code", "http_status", "details"?}`. `error_code` is one of `rejected`, `invalid_request`, `not_found`, `conflict`, `forbidden`, `unauthorized`, `server_error`, `invalid_file`, `id_mismatch`, `lifecycle_change_refused`, `confirmation_required` or `outcome_unknown`.

