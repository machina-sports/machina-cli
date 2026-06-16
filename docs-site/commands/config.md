# config

Read and write the CLI configuration stored in `~/.machina/config.json`. See [Configuration & global flags](/guide/configuration) for the bigger picture and the keys you'll set most often.

## Usage

```bash
machina config list                    # show all settings
machina config get <key>               # read a setting
machina config set <key> <value>       # update a setting
```

## Common keys

```bash
machina config set api_url https://api.machina.gg
machina config set session_url https://session.machina.gg
machina config set default_organization_id <org-id>
machina config set default_project_id <project-id>
```

::: info
`machina org use` and `machina project use` write `default_organization_id` / `default_project_id` for you — you rarely set those by hand. Environment variables (`MACHINA_API_KEY`, `MACHINA_API_URL`) override config-file values.
:::
