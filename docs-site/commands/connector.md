# connector

Connectors integrate external data providers and services into your project.

## Usage

```bash
machina connector list                 # list connectors
machina connector list --json          # output as JSON
machina connector get <name>           # get connector details
```

## Subcommands

| Command | Description |
|---------|-------------|
| `connector list` | List connectors in the project |
| `connector get <name>` | Show connector details |

To author or push a new connector, use the [`skills`](/commands/skills) surface, which bootstraps the `mkn-constructor` authoring bridge.
