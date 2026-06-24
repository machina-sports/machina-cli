# Credentials & Config — Integration Contract

`machina-cli` stores its state under `~/.machina/`. This document describes that layout as a
**stable, public contract** so other tools (e.g. `sportsclaw`, `sports-skills`) can read it for
unified, one-time login. Both files are written with mode `600`.

> **For integrators:** treat `config.json` as readable, non-secret state. Treat
> `credentials.json` as **secret** — check for the *presence* of a credential and read
> non-secret fields (`expires_at` via the JWT, project ids), but do not transmit or log token
> values beyond passing them through the user's own session.

## `~/.machina/config.json` (non-secret content, mode 600)

This file holds no credentials, but `machina-cli` still writes it `600` (owner-only). Integrators
reading it from another user account should expect a permission error, not world-readable state.


| Key | Meaning | Default |
| --- | --- | --- |
| `api_url` | Core API base URL | `https://api.machina.gg` |
| `session_url` | Session service URL | `https://session.machina.gg` |
| `default_organization_id` | Selected org (set by `machina org use`) | `""` |
| `default_project_id` | Selected project (set by `machina project use`) | `""` |
| `client_api_url` | Per-project Client API base, when known | `""` |
| `factory_url` | Factory customer surface | `https://customers.machina.gg` |
| `output_format` | **Reserved** — present in defaults but not yet consulted by any command; pass `--json/-j` per command for machine output | `table` |

Commands may add convenience keys (e.g. `default_organization_name`, `default_project_name`).
Readers should treat unknown keys as additive and ignore them.

## `~/.machina/credentials.json` (secret — mode 600)

| Key | Meaning |
| --- | --- |
| `api_key` | Long-lived API key (`X-Api-Token`), if the user logged in with one |
| `session_token` | Session JWT (`X-Session-Token`); carries an `exp` claim |
| `project_token_<project_id>` | Per-project JWT; its `api` claim resolves the Client API base URL, and it carries `exp` |

## Token resolution precedence

`resolve_auth_token()` returns `(header_name, token_value)` in this order:

1. **`MACHINA_API_KEY`** environment variable → `X-Api-Token`.
2. Stored `api_key` → `X-Api-Token`.
3. Stored `session_token`, **if not expired** → `X-Session-Token`. An expired session token is
   cleared (so the user gets a clean "not authenticated" signal).

The Core API base URL resolves as: `MACHINA_API_URL` env → `config.json` `api_url` → default.

## Reading this safely (for integrators)

- **Enforce perms:** refuse to read `credentials.json` if it is group- or world-readable.
- **Validate shape:** reject malformed JSON with a clean error; never surface raw parse
  exceptions (they can leak paths).
- **Presence over value:** to report "logged in," check that resolution yields a non-empty
  header — you do not need the token value itself.
- **Expiry:** decode the relevant JWT's `exp` to warn before a connection silently fails.

## Environment overrides

| Variable | Effect |
| --- | --- |
| `MACHINA_API_KEY` | Auth token; highest precedence |
| `MACHINA_API_URL` | Override the Core API base URL |
