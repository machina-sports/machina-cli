# mcp

The `mcp` command group resolves a project's **Model Context Protocol (MCP) endpoint** so an external agent can connect to it without a hand-pasted URL.

Every Machina project exposes an MCP server at its Client-API base (the `api` claim in the project token) plus a fixed path. `mcp url` derives that endpoint for you.

::: tip Wiring an external agent? Use `connect`
`mcp url` returns just the raw endpoint (URL, transport, auth header). To get a ready-to-register connection **with the auth token paired in** (and optionally a durable minted key), use [`machina connect`](/commands/connect) instead.
:::

## `url` — resolve the MCP endpoint

```text
machina mcp url [project_id] [--json] [--probe]
```

| Arg / flag | Purpose |
|------------|---------|
| `project_id` | Project to resolve (defaults to the selected project). |
| `--json`, `-j` | Machine-readable output. |
| `--probe` | Open the SSE stream and verify the endpoint is actually reachable (200 + `event-stream`). |

```bash
machina mcp url                    # selected project
machina mcp url <project-id> --probe
```

The endpoint is:

| Field | Value |
|-------|-------|
| **URL** | `<client-api base>/mcp/sse` (base = the project token's `api` claim) |
| **Transport** | `sse` |
| **Auth header** | `X-Api-Token` (or `X-Session-Token`; `X-Project-Token` is **not** required) |

`--probe` confirms a reachable SSE endpoint (not full MCP protocol conformance) — use it to catch an org-client-deployed project whose MCP host differs from its `api` host, rather than handing out an unverified URL.

## Related

- [`connect`](/commands/connect) — resolve the endpoint **and** pair the auth token for an external agent (e.g. sportsclaw), with `--mint` for a durable dedicated key.
