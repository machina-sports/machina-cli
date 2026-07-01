# connect

`machina connect` is the **one-command bridge** that lets an external agent (e.g. [sportsclaw](/commands/loop#related)) talk to a project's [MCP endpoint](/commands/mcp) — it resolves the endpoint and pairs it with an auth token, ready to register, without a hand-pasted URL or key.

## Usage

```text
machina connect [project_id] [--reveal] [--probe] [--name <n>] [--mint [--org <id>]] [--json]
```

| Arg / flag | Purpose |
|------------|---------|
| `project_id` | Project to connect (defaults to the selected project). |
| `--reveal` | Show the auth token (**masked by default**). |
| `--probe` | Verify the SSE endpoint is reachable before handing it out. |
| `--name`, `-n` | Server name for the agent (defaults to the project id; coerced to `^[A-Za-z0-9_-]+$`). |
| `--mint` | Reuse or **create a dedicated `sportsclaw-<project>` project API key** for a durable connection. |
| `--org`, `-o` | Organization ID for `--mint` (defaults to the selected org). |
| `--json`, `-j` | Machine-readable output (add `--reveal` to include the token). |

## Examples

```bash
# resolve + verify the connection for the selected project (token masked)
machina connect --probe

# durable connection: reuse/mint a dedicated project key and reveal it
machina connect <project-id> --mint --reveal

# JSON for scripting an agent's server registration
machina connect <project-id> --mint --reveal --json
```

## What you get

- The **MCP URL**, **transport** (`sse`), and **auth header** (`X-Api-Token`) — the same derivation as [`machina mcp url`](/commands/mcp).
- A **token** paired to that endpoint. By default the ambient session/API-key credential; with `--mint`, a durable dedicated **`sportsclaw-<project>`** project API key (reused if it already exists, minted if not — so the connection survives your session expiring).

::: warning Token handling
The token is **masked** unless you pass `--reveal`. Treat a revealed token as a live credential — it grants access to the project's MCP surface. `--mint` keys are scoped per project and named `sportsclaw-<project>`; manage them with [`machina credentials`](/commands/credentials).
:::

## Related

- [`mcp url`](/commands/mcp) — the raw endpoint resolver (no token pairing).
- [`credentials`](/commands/credentials) — list/revoke the project API keys (`--mint` reuses these).
