# context-graph

The `context-graph` command group shows the **self-healing / monitoring layer** from the terminal — the same truth the [Studio Context Graph page](https://studio.machina.gg/) renders, but across **all your projects at once**.

The Context Graph is the set of **verified, self-healing edges over your data**: entity-resolution links (e.g. a bookmaker market → the canonical team/fixture URN), data-integrity health, and the **live surface** (are real users still seeing odds and not hitting errors?). The [`loop`](/commands/loop) and its `surface-verify` / `context-verify` workflows write that state into each project as `context_graph_health`, `context_graph_links`, and `context_graph_surface_health` documents. `context-graph status` reads it back — **no extra state**, derived live.

## Usage

```text
machina context-graph status   [--project <id>] [--org] [--json]
machina context-graph timeline [--project <id>] [--org] [--days N] [--json]
```

| Flag | Purpose |
|------|---------|
| `--project`, `-p` | A specific project (defaults to the selected project). |
| `--org` | Roll up **every project** in the organization. |
| `--days`, `-d` | (`timeline`) How far back to look — default 30. |
| `--json`, `-j` | Machine-readable output. |

## `status` — one project

```bash
machina context-graph status
```

```text
enrichment-production (6a41b3c4…)
  edge analysis<->fixture       ok        0%
  edge market<->team_urn        linked    52.5% linked
  edge market<->price_quality   degraded  34.1%
  surface odds/errors           degraded:errors  sessions 1003 · 1386 exc · err/s 1.41
  agent surface-watch-beat      active · freq=30   2026-06-30 22:15:33
  agent loop-runner             inactive
```

Each line is one part of the layer:

- **edge** — a verified Context Graph edge and its health. `linked` / `ok` (green) or `degraded` / `unlinked` (red), with the headline number (link rate, broken rate, or unresolved count).
- **surface** — the live odds/error verdict for real users (`ok` · `low_traffic` · `degraded:odds` · `degraded:errors`), with **session-normalized** signals and the exception count.
- **agent** — the self-heal agents (`surface-watch-beat`, `loop-beat`, `loop-runner`) and whether they're actually running.

::: warning A beat that says `active` but `scheduled=True` is silently dead
The platform's frequency beat only dispatches agents with **`scheduled=False` + `status=active` + a `config-frequency`**. `status` flags an `active` agent that is `scheduled=True` as **`scheduled=True (won't fire)`** — the trap that makes a monitor look enabled while it never runs. Fix with `PUT /agent/<id> {"scheduled": false, "status": "active"}`.
:::

## `status --org` — the whole org

```bash
machina context-graph status --org
```

```text
              Self-healing across the org
┏━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━┓
┃ Project                ┃ Edges ┃ Surface         ┃ Beat ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━┩
│ enrichment-production  │     3 │ degraded:errors │ live │
│ enrichment-staging     │     3 │ ok              │ off  │
│ sbot-prd               │     0 │ —               │ none │
└────────────────────────┴───────┴─────────────────┴──────┘
```

One screen answers **what self-healing is provisioned where, and how healthy it is** — without opening each project. Projects with nothing provisioned are omitted; unreachable ones are counted as skipped.

::: tip Consistency with the Studio
`context-graph status` and the Studio Context Graph page read the **same** `context_graph_*` documents, so the CLI and the UI never disagree. Use the CLI for a fast org-wide sweep; open a project in the Studio to drill into its edges, resolved links, orphans, and surface tab.
:::

## `timeline` — the self-healing event history

`status` shows the *current* state; `timeline` shows the *story* — every detection, heal round, escalation, and recovery, reconstructed from the persisted graph-health trail (works retroactively, no new state):

```bash
machina context-graph timeline --days 7
```

```text
        Self-healing timeline — last 7 day(s)
┏━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Time (UTC)   ┃ Edge               ┃ Event     ┃ Detail                            ┃
┡━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Jul 01 17:25 │ analysis<->fixture │ detected  │ 13 broken                         │
│ Jul 01 18:10 │ analysis<->fixture │ heal      │ re-research dispatched for 5      │
│              │                    │           │ fixture(s) (+8 queued)            │
│ Jul 01 19:12 │ analysis<->fixture │ recovered │ back to 0 broken (was 4)          │
└──────────────┴────────────────────┴───────────┴───────────────────────────────────┘
  1 detected · 1 heal round(s) · 1 recovered · 0 escalated to a human
```

The summary line is the ROI number: **how many times the loop found and fixed a problem before a human had to**. Events:

| Event | Meaning |
|-------|---------|
| `detected` | An edge went from clean to broken (or the surface entered a degraded verdict). |
| `heal` | An auto-heal round dispatched (odds refresh, or per-fixture re-research). |
| `heal-paused` | Auto-heal hit its no-progress budget and escalated to a human. |
| `recovered` | The edge/surface returned to clean. |

`--org` merges all projects into one chronological stream (adds a Project column).

## `--json`

```bash
machina context-graph status --org --json
machina context-graph timeline --org --days 30 --json
```

`status` emits `{ "projects": [{ "name", "id", "edges", "surface", "agents" }], "skipped": N }`; `timeline` emits `{ "events": [...], "summary": {...} }` — pipe into `jq` for alerts or dashboards.

## Related

- [`loop`](/commands/loop) — the durable loop + `surface-verify` / `context-verify` workflows that produce the Context Graph state (and auto-heal `degraded:odds` + misattributed analyses).
- Provisioning kit — `docs/harness-loop-kit/` in the [machina-cli repo](https://github.com/machina-sports/machina-cli).
