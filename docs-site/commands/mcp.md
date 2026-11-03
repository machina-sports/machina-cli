# mcp

The `mcp` command group resolves a project's **Model Context Protocol (MCP) endpoint** so an external agent can connect to it without a hand-pasted URL.

Every Machina project exposes an MCP server at its Client-API base (the `api` claim in the project token) plus a fixed path. `mcp url` derives that endpoint for you.

::: tip Wiring an external agent? Use `connect`
`mcp url` returns just the raw endpoint (URL, transport, auth header). To get a ready-to-register connection **with the auth token paired in** (and optionally a durable minted key), use [`machina connect`](/commands/connect) instead.
:::

## `url` — resolve the MCP endpoint

```text
machina mcp url [project_id] [--json] [--probe] [--timeout <s>]
```

| Arg / flag | Purpose |
|------------|---------|
| `project_id` | Project to resolve (defaults to the selected project). |
| `--json`, `-j` | Machine-readable output (schema `machina.mcp.connection/v1`). |
| `--probe` | Connect and verify readiness: MCP handshake → `tools/list` (all pages) → the harmless `health_check` tool. |
| `--timeout` | Probe timeout in seconds (default 15). |

```bash
machina mcp url                    # selected project, unverified
machina mcp url <project-id> --probe --json
```

### Transport resolution

The CLI only ever connects to the project's Client-API base (the project token's `api` claim — never another host):

1. **Streamable HTTP** at `<base>/mcp`.
2. **Legacy SSE** at `<base>/mcp/sse` — only when (1) answers `404`/`405` (the deployment has no streamable endpoint). Never after a `401`/`403`: an auth denial is reported, not silently downgraded.

Without `--probe` nothing is negotiated: the payload reports the legacy SSE endpoint every released deployment serves, with `"verified": false`. With `--probe`, `url`/`transport` are the ones the handshake actually succeeded on, plus the negotiated `protocol_version`, `server`, `tool_count` and `health_check`. An HTTP 200 or an open stream alone is never reported as ready.

Auth header: `X-Api-Token` (or `X-Session-Token`; `X-Project-Token` is **not** required). The probe refuses to connect without a credential.

### Errors

Failures exit `1` with a typed envelope — `{"schema", "error", "error_code", "hint", ...}`:

| `error_code` | Meaning |
|--------------|---------|
| `missing_credentials` | Not logged in / no API key. |
| `expired_credentials` | The server rejected the credential (401). |
| `wrong_project` | No project selected, or the project session can't be resolved. |
| `access_denied` | Valid credential without access to this project (403). |
| `endpoint_unavailable` | Connection refused, timeout, 5xx, or no MCP endpoint at all. |
| `incompatible_protocol` | The server's MCP reply isn't a compatible protocol (or lacks `health_check`). |
| `health_check_failed` | Server is up but the `health_check` read failed. |

Credentials never appear in output, errors or logs.

## Related

- [`connect`](/commands/connect) — resolve the endpoint **and** pair the auth token for an external agent (e.g. sportsclaw), with `--mint` for a durable dedicated key.
