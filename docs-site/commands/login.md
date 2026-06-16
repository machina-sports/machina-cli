# login

`machina login` authenticates the CLI and stores credentials locally. The related `auth` subcommands inspect and clear that session. For the full picture, see the [Authentication guide](/guide/authentication).

## Usage

```bash
machina login                          # browser-based SSO (default)
machina login --api-key <key>          # authenticate with an API key (CI/CD)
machina login --with-credentials       # username / password
machina login --no-interactive         # don't open the REPL afterwards

machina auth whoami                    # show the current user
machina auth logout                    # clear stored credentials
```

## Options

| Flag | Short | Description |
|------|-------|-------------|
| `--api-key` | `-k` | Authenticate with an API key instead of the browser |
| `--with-credentials` | | Use username / password instead of the browser |

## Behavior

- Browser login opens your browser for Clerk SSO / magic-link sign-in, then stores the session in `~/.machina/credentials.json` (`600`).
- After a successful login the CLI opens the [interactive REPL](/guide/repl). Pass `--no-interactive` to skip it — useful in scripts.
- For CI, prefer `--api-key` or the `MACHINA_API_KEY` environment variable.

::: tip
In CI, set `MACHINA_API_KEY` instead of calling `machina login` — every command picks the key up automatically with no interactive step.
:::
