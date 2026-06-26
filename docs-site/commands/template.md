# template

Templates are fully packaged agent workflows with connectors, mappings, prompts, and datasets. `template` is a compatibility surface — for new authoring, prefer [`skills`](/commands/skills).

## Usage

```bash
machina template list                       # browse the template repository
machina template list --repo <url>          # browse a custom repository
machina template list --branch dev          # a specific branch
machina template list --json                # output as JSON
machina template install <path>             # install a template
machina template install <path> --json      # install with structured JSON output
machina template push ./my-agent            # push a local custom template
```

## Installing a template

```bash
# 1. Browse available templates
machina template list

# 2. Install one (e.g. agent-templates/bundesliga-podcast)
machina template install agent-templates/bundesliga-podcast
```

This provisions cloud resources (connectors, datasets, mappings) on your project and downloads the template files (`SKILL.md`, workflow configs) to `./bundesliga-podcast/`.

## Pushing a custom template

```bash
machina template push ./my-custom-agent
```

This validates `_install.yml` (a pre-flight linter), zips and uploads to the Machina Cloud Pod, and provisions webhook endpoints and data streams.

::: info
`template install … --json` emits structured output designed for agent integration — useful when a coding agent drives the CLI.
:::
