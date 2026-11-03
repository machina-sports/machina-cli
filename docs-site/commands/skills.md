# skills

Skills are packaged capabilities — workflows, connectors, and agents — distributed through the Machina registry. `skills install`, `push` and `constructor` bootstrap the `mkn-constructor` authoring bridge from `machina-templates` on first use; read-only commands never download or install anything.

## Usage

```bash
machina skills list                    # browse skills / packages from the registry
machina skills install <path>          # install a skill / package
machina skills info <path>             # show metadata and manifest (when available)
machina skills run <name>              # resolve a skill entrypoint into runtime
machina skills push <path>             # push a local skill / package
machina skills constructor             # re-run the mkn-constructor authoring bridge

# installed project Skills, through the project's MCP server
machina skills show <name|id>          # identity, entrypoints, ordered documents
machina skills docs <name|id>          # read the linked instructions/references
machina skills run <name|id> --remote  # submit one execution → skill_run_id
machina skills result <skill_run_id>   # persisted outcome (never resubmits)
```

## Subcommands

| Command | Description |
|---------|-------------|
| `skills list` | Browse skills / packages from the registry |
| `skills install <path>` | Install a skill / package |
| `skills info <path>` | Show skill metadata and manifest when available |
| `skills run <name>` | Resolve a skill entrypoint into workflow / agent runtime |
| `skills push <path>` | Push a local skill / package |
| `skills constructor` | Manually re-run the `mkn-constructor` authoring bridge |

::: info
`mkn-constructor` is the built-in authoring bridge for creating new skills, templates, and connectors. The write commands (`install`, `push`) bootstrap it automatically the first time you need it; `skills constructor` re-runs it on demand. Discovery (`list`, `info`, `show`, `docs`, `result`) never installs.
:::

## Installed project Skills (remote)

`show`, `docs`, `run --remote` and `result` work against the Skills **installed in the selected project**, through the project's MCP server (same connection resolution and typed errors as [`machina mcp`](/commands/mcp)).

| Command | MCP tools | Notes |
|---------|-----------|-------|
| `skills show <name\|id>` | `get_skill` / `get_skill_by_name` | Supplied metadata only; fields the server doesn't supply are listed under `missing`. `instruction_only` is true when no workflow/agent entrypoint is supplied. `status` is the registry status, not proof of runnability. |
| `skills docs <name\|id> [--name doc]` | `get_skill` → ordered `documents[]` → `get_document` | Exits `1` if a linked document is missing or the Skill supplies none. |
| `skills run <name\|id> --remote [k=v ...] [-m msg]` | `execute_skill` | **Submit-only**: prints `outcome: accepted` and a `skill_run_id` — never "completed". Refuses instruction-only Skills. On a timeout after submission it reports `submission_unknown` and does **not** resubmit. |
| `skills result <skill_run_id>` | `get_skill_execution` (`compact=false`) | Exit `0` completed · `1` failed · `2` partial (`completed_workflows < total_workflows`) · `3` not finished yet / unknown. A server-supplied `outcome` field wins. |
