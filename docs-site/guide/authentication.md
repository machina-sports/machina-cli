# Authentication

The CLI supports three authentication methods. Browser login is the default for interactive use; API keys are the right choice for CI/CD.

## Methods

| Method | Command | Use case |
|--------|---------|----------|
| **Browser** (default) | `machina login` | Interactive use — opens the browser for Clerk SSO / magic link |
| **API key** | `machina login --api-key <key>` | CI/CD pipelines and scripts |
| **Username / password** | `machina login --with-credentials` | Internal / dev environments |

```bash
machina login                          # browser-based (default)
machina login --api-key <key>          # authenticate with an API key
machina login --with-credentials       # username / password
```

After a successful login the CLI drops you into the [interactive REPL](/guide/repl). Pass `--no-interactive` to skip it.

## Session commands

```bash
machina auth whoami        # show the current user
machina auth logout        # clear stored credentials
```

## Where credentials live

Credentials are stored locally in `~/.machina/credentials.json` with `600` file permissions (owner read/write only).

::: warning
Treat `~/.machina/credentials.json` like any secret. An API key grants the same access as your account — never commit it or paste it into shared logs.
:::

## Environment variables

Environment variables override values in the config file — useful for CI:

| Variable | Description |
|----------|-------------|
| `MACHINA_API_KEY` | API key for authentication (used when no browser session is present) |
| `MACHINA_API_URL` | Override the Core API URL |

```bash
export MACHINA_API_KEY="<your project api key>"
machina workflow list      # authenticates with the key — no browser needed
```

## Next up

[Pick a project and run something →](/guide/quickstart)
