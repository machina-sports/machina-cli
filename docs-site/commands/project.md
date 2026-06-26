# project

Manage projects within your organization and set the default used by every other command.

## Usage

```bash
machina project list                   # list projects
machina project list --limit 10        # paginate (10 per page)
machina project list --json            # output as JSON
machina project create <name>          # create a project
machina project use <project-id>       # set the default project
machina project status                 # deployment status
```

## Subcommands

| Command | Description |
|---------|-------------|
| `project list` | List projects in the organization |
| `project create <name>` | Create a new project |
| `project use <project-id>` | Set the default project (writes `default_project_id` to config) |
| `project status` | Show the project's deployment status |

::: tip
Once you've run `project use`, every resource command (`workflow`, `agent`, …) targets that project. Override a single command with `--project <id>`.
:::
