# `machina factory` — trigger Factory builds from the CLI

> **Release:** machina-cli **v0.2.25** (2026-05-30) · companion deploy: `machina-factory-customer#136`

The `factory` command group lets you drive the **Machina Factory** coding-agent — the
"build me an app from a prompt" runtime behind `customers.machina.gg/c` — directly from
your terminal. It builds an app in a sandbox, wires it to your project's live data, and
opens a pull request.

It talks to the Factory **customer surface** (`customers.machina.gg/c/api/*`) and
authenticates with the **studio session you already have** — the same login the `/c` web
UI uses. **No new credential to manage.**

---

## Install / upgrade

```bash
pip install --upgrade machina-cli      # or: pipx upgrade machina-cli
machina version                        # -> machina-cli v0.2.25
```

## Authentication

Two modes, picked automatically:

| Mode | When | How to enable | Job ownership |
|------|------|---------------|---------------|
| **Session** (default) | Interactive use | `machina login` (browser) | Your user (`uid`) |
| **API-key** (headless/CI) | No browser | `export MACHINA_API_KEY=<project key>` (and no session) | The key's **organization** |

```bash
machina login                  # browser sign-in — stores the studio session
machina factory whoami         # confirm Factory sees you
```

`whoami` shows the identity Factory resolved:

```
╭─────────── Factory Identity ────────────╮
│ Auth mode: session                       │
│ User ID: 685d3de5cc299716421187e6        │
│ Organization: …                          │
│ Project: r10 (6a11ecebc61a7f0dbb900316)  │
╰──────────────────────────────────────────╯
```

> If you see *"Factory requires a studio session"*, run `machina login`. An API-key-only
> login (`machina login --api-key …`) works for other commands but `factory` needs either a
> studio session or `MACHINA_API_KEY` set for the headless path.

---

## Commands

```text
machina factory run "<prompt>" [--repo owner/name] [--mode …] [--watch]
machina factory status <job-id>
machina factory watch  <job-id>
machina factory logs   <job-id> [--follow]
machina factory follow-up <job-id> "<prompt>" [--watch]
machina factory cancel <job-id>
machina factory open-pr <job-id>
machina factory list
machina factory whoami
```

All commands accept `--project/-p <id>` and `--json/-j`.

### `run` — start a build

```bash
# Simplest: just a prompt (Factory scaffolds a repo)
machina factory run "a single-page live scoreboard for the Premier League"

# Target an existing repo + follow until it finishes, then print the PR
machina factory run "add a heatmap widget to the match page" \
  --repo machina-sports/sports-skills --watch

# Seed the build with a category starter template
machina factory run "workflow that posts a goal alert to Slack" --mode workflow
```

`--mode` (optional category chip): `skill · connector · workflow · agent · template`.
Returns a **job id** (the build's root id) you pass to the other commands.

### `status` / `watch` / `logs`

```bash
machina factory status <job-id>          # snapshot: the build chain + statuses
machina factory watch  <job-id>          # poll until terminal, then print the PR
machina factory logs   <job-id> --follow # live SSE timeline (agent actions, tool calls)
```

Build lifecycle: `queued → provisioning → running → verifying → committing → deploying → completed`
(or `failed` / `cancelled`).

### Iterate, cancel, ship

```bash
machina factory follow-up <job-id> "switch to a dark theme" --watch
machina factory cancel <job-id>
machina factory open-pr <job-id>         # open (or reveal) the PR for a finished build
machina factory list                     # your active + recent builds
```

---

## Headless / CI

No browser available? Use a project **API key** (the `client-api`-named key from
`machina credentials list`, or generate one with `machina credentials generate`):

```bash
export MACHINA_API_KEY="<your project api key>"
machina factory run "rebuild the standings page" --repo machina-sports/sports-skills --json
machina factory list --json
```

In this mode the CLI sends `X-Api-Token`; Factory validates it against core-api and scopes
all `factory` operations to the **key's organization** (not a single user). The build's pod
credentials are derived from the key, so generated apps can still talk to your project's
live data via the pod.

> Headless mode depends on the customers deploy accepting api-key auth (shipped in
> `machina-factory-customer#136`). Session mode works regardless.

---

## Environment variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `MACHINA_FACTORY_URL` | Factory customer surface base URL | `https://customers.machina.gg` |
| `MACHINA_API_KEY` | Project API key for headless mode (`X-Api-Token`) | — |
| `MACHINA_SESSION_TOKEN` | Override the stored studio session token | stored `session_token` |
| `MACHINA_SESSION_COOKIE_NAME` | Session cookie name the surface expects | `machina_production_session_name` |

Config keys live in `~/.machina/config.json` (`factory_url`) and credentials in
`~/.machina/credentials.json` (chmod 600).

---

## How it works

```
machina factory ─(studio cookie | X-Api-Token)→ customers.machina.gg/c/api/*
                                                   │  (thin auth proxy)
                                                   ▼
                                          Factory Jobs API (/v1/jobs)
                                                   │
                                       sandbox build → commit → PR / deploy
```

The CLI never holds the Factory server key (`mf_…`) — that stays server-side. It
authenticates as **you** (session) or as your **project** (api-key), so jobs are correctly
attributed, billed, and ownership-checked.

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `Factory requires a studio session` | Run `machina login`, or set `MACHINA_API_KEY` for headless mode. |
| `401` / `Studio session expired` | Session expired — `machina login` again. |
| `API key rejected by Factory` | Key invalid/revoked, or the customers deploy predates api-key auth. |
| `client-api-url-required` (headless) | Set a project with `machina project use <id>` so `client_api_url` is known. |
| `402` on `run` | Out of build credits — top up. |
