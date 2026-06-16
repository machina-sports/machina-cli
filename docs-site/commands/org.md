# org

Manage the organizations you belong to and set the default used by every other command.

## Usage

```bash
machina org list                       # list organizations
machina org list --limit 5             # paginate (5 per page)
machina org list --page 2              # page 2
machina org list --json                # output as JSON
machina org create <name>              # create an organization
machina org use <org-id>               # set the default organization
```

## Subcommands

| Command | Description |
|---------|-------------|
| `org list` | List organizations you belong to |
| `org create <name>` | Create a new organization |
| `org use <org-id>` | Set the default organization (writes `default_organization_id` to config) |

`list` supports the global `--limit`, `--page`, and `--json` flags — see [Configuration → Global flags](/guide/configuration#global-flags).
