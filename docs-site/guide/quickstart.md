# Quickstart

From a fresh install to running your first workflow. If you haven't installed the CLI yet, start with [Installation](/guide/installation).

## 1. Authenticate

```bash
machina login
```

This opens your browser for Clerk SSO / magic-link sign-in and stores your session locally. For CI or headless environments, use an API key instead — see [Authentication](/guide/authentication).

## 2. Select an organization

```bash
machina org list             # list organizations you belong to
machina org use <org-id>     # set the default organization
```

## 3. Select a project

```bash
machina project list                # list projects in the org
machina project use <project-id>    # set the default project
```

Your default org and project are saved to `~/.machina/config.json` and used for every subsequent command. Override per-command with `--project`.

## 4. Explore and run

```bash
machina workflow list           # browse workflows
machina agent list              # browse agents
machina skills list             # browse the skills registry

machina workflow run <name>          # run a workflow (prompts for inputs)
machina agent run <name> --watch     # run an agent and watch progress
```

::: tip
Run `machina` with no arguments to open the [interactive REPL](/guide/repl) — the same commands without the `machina` prefix, with tab completion and history.
:::

## Next up

- [Run agents & workflows →](/guide/running) — inline params, sync / async, and watch mode.
- [Command reference →](/commands/login) — every command, flag, and example.
