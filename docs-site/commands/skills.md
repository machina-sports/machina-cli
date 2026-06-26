# skills

Skills are packaged capabilities — workflows, connectors, and agents — distributed through the Machina registry. The skills surface auto-bootstraps the `mkn-constructor` authoring bridge from `machina-templates` on first use.

## Usage

```bash
machina skills list                    # browse skills / packages from the registry
machina skills install <path>          # install a skill / package
machina skills info <path>             # show metadata and manifest (when available)
machina skills run <name>              # resolve a skill entrypoint into runtime
machina skills push <path>             # push a local skill / package
machina skills constructor             # re-run the mkn-constructor authoring bridge
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
`mkn-constructor` is the built-in authoring bridge for creating new skills, templates, and connectors. The skills surface bootstraps it automatically the first time you need it; `skills constructor` re-runs it on demand.
:::
