# Interactive REPL

Run `machina` with no arguments to open an interactive session (REPL):

```text
$ machina

  ✦ Machina CLI v0.2.x
  Organization: Acme Corp
  Project:      demo-project

  Type a command (e.g. `workflow list`) or `help` for commands.
  Press Ctrl+D or type `exit` to quit.

✦ Acme Corp/demo-project > workflow list
✦ Acme Corp/demo-project > agent list
✦ Acme Corp/demo-project > project list limit 5
✦ Acme Corp/demo-project > exit
```

## No prefix, no dashes

Inside the session you type commands without the `machina` prefix and without `--` before flags:

```text
workflow list              # same as: machina workflow list
project list limit 5       # same as: machina project list --limit 5
credentials list json      # same as: machina credentials list --json
```

## Features

- **Tab completion** — across command groups, subcommands, and flags.
- **Command history** — persisted in `~/.machina/history`, available across sessions.
- **Live context** — your current organization and project show in the prompt.
- **`help`** — lists every command group; `exit` or `Ctrl+D` quits.

::: tip
The REPL is the default when you run `machina`, and it opens automatically after `machina login`. For the static banner instead of a session, run `machina --no-interactive`.
:::

## Shell prompt integration

Prefer your current org/project in your *shell* prompt rather than a session? See [Configuration → Shell prompt integration](/guide/configuration#shell-prompt-integration).
