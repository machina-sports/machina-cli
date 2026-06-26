# credentials

Manage the API keys attached to your project. Keys authenticate headless / CI use of the CLI and the platform API.

## Usage

```bash
machina credentials list                      # list API keys (masked)
machina credentials list --show-keys          # list API keys (full values)
machina credentials list --copy client-api    # copy a key to the clipboard
machina credentials generate                  # generate a new API key
machina credentials generate --name my-key    # generate with a custom name
machina credentials revoke <key-id>           # revoke an API key
```

## Subcommands

| Command | Description |
|---------|-------------|
| `credentials list` | List API keys (masked by default) |
| `credentials generate` | Generate a new API key |
| `credentials revoke <key-id>` | Revoke an existing key |

::: warning
`--show-keys` prints full secret values to your terminal. Use it only on a trusted machine, and never paste the output into shared logs or tickets.
:::

The `client-api` key is the one to export as `MACHINA_API_KEY` for headless [authentication](/guide/authentication) and [Factory CI builds](/commands/factory).
