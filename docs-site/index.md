---
layout: home

hero:
  name: Machina CLI
  text: The platform, from your terminal
  tagline: Manage organizations, projects, workflows, agents, and skills — or kick off a Factory build — without leaving the command line.
  image:
    light: /machina-logo-light.png
    dark: /machina-logo-dark.png
    alt: Machina Sports
  actions:
    - theme: brand
      text: Quickstart
      link: /guide/quickstart
    - theme: alt
      text: Installation
      link: /guide/installation
    - theme: alt
      text: Command reference
      link: /commands/login

features:
  - icon: 💻
    title: Interactive REPL
    details: Run `machina` with no arguments for a session with tab completion, history, and your current org/project in the prompt.
  - icon: ▶️
    title: Run agents & workflows
    details: Sync, async, and watch modes — with interactive prompts or inline key=value params, straight from the terminal.
  - icon: 🏭
    title: Factory builds
    details: Drive the Machina Factory coding-agent — build an app from a prompt, wire it to your data, and open a pull request.
  - icon: ⚽
    title: Sports data
    details: The full sports-skills CLI mounted under `machina sports` — football, F1, NBA, markets and more, delegated live.
  - icon: 🧩
    title: Skills & templates
    details: Browse, install, run, and push packaged skills and agent templates from the registry.
  - icon: 🔑
    title: Scriptable auth
    details: Browser SSO for humans, API keys for CI. Every list command speaks --json for piping to jq.
---

## Install in one line

```bash
curl -fsSL https://raw.githubusercontent.com/machina-sports/machina-cli/main/install.sh | bash
```

Then authenticate and explore:

```bash
machina login
machina org list
machina workflow list
```

## Command groups

| Group | Commands |
| --- | --- |
| **Platform** | `login` · `org` · `project` · `credentials` |
| **Resources** | `workflow` · `agent` · `connector` · `mapping` · `prompt` · `document` |
| **Operations** | `execution` · `skills` · `factory` · `sports` · `template` · `deploy` · `config` · `update` |

New here? Start with [Installation](/guide/installation), then the [Quickstart](/guide/quickstart).
