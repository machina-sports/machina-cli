# Changelog

All notable changes to machina-cli are documented here.

## [Unreleased]

### Fixed
- **`context-verify-beat` can now actually fire.** The harness-loop-kit provisioner created the beat with `scheduled: true`, but the platform dispatcher only fires `scheduled: false` agents (the cron path is silently never dispatched without a real cron) — so the sweep was structurally dead even after being activated. It is now provisioned `scheduled: false`, the same contract as `loop-beat`/`surface-watch-beat`. Part of the Context Graph phase-A hardening (86ajj3jn6).

### Changed
- **`context-graph status` sees the whole self-heal layer and stops trusting old evidence.** The agent roster now includes `context-verify-beat`, `context-verify-runner` and `context-heal-runner` (previously invisible in Studio/CLI), the `--org` Beat column also recognizes `context-verify-beat`, and every edge/surface row shows its evidence age — evidence older than 24h renders as `(stale)` and is never green.

## [0.7.1] - 2026-07-08

### Added
- **Arena Context Graph certification edges.** `machina context-graph status` now renders `arena:*` edges with Arena-native badges: `certified` for passing artifacts, `repair` for artifacts that need a fix, and `blocked` for hard failures. The detail line includes gate pass rate, judge score, approval state, and failed gates when present, so Factory/Arena certification proof is visible from the same CLI surface as live Context Graph health. (#65)

## [0.7.0] - 2026-07-02

### Added
- **Human approval checkpoints — `machina approvals` + the `compose_approval`/`resolve_approval` nodes.** A workflow that produces something risky or publishable (an AI-written article, a bulk change) can now gate its final action behind a human: it composes an `approval-request` document (title, preview, and the workflow+inputs that should run **if approved**), saves it, and posts the ask to Slack — the request side is three tasks from the `machina-nodes` library (the provisioned `machina-approval-demo` is a copyable example; an actionless request works too, as a pure acknowledgment gate). The human resolves via `machina approvals list / approve / reject`; resolution executes the in-pod `machina-approval-resolve` workflow, so every surface (CLI, Studio, MCP) shares the same logic — approve dispatches the stored action in-pod, reject just records, double-resolution is guarded, and a dispatch failure is recorded and surfaced without un-approving the decision. This is the Pressbox adoption plan's step ② and the Loop-Engineering "keep one door open" checkpoint as a first-class workflow primitive.

## [0.6.3] - 2026-07-02

### Added
- **`machina-nodes` — a shared action-node library for pod workflows** (`docs/harness-loop-kit/nodes.py`). The Pressbox lesson applied to Machina's own engine: workflows are already data walked by an executor — what was missing was a registry of small, composable action nodes, so a new automation is graph wiring instead of another copy-pasted pyscript (the Slack notify logic had been written twice across the verify kits). Ships two nodes: `slack_notify` (posts a ready-composed text; webhook from the same `slack-notify-config` doc the verifies use) and `github_issue` (opens a GitHub issue; token+repo from a `github-issue-config` doc — **inert until configured**, so it deploys everywhere safely). Every node is best-effort (never raises), inert without config, and composed via task inputs. A `machina-nodes-demo` workflow ships as living documentation of the pattern.

## [0.6.2] - 2026-07-01

### Fixed
- **The analysis audit no longer alerts on — or heals — matches that were already played.** User question after the first live cycle: *why is it looking at these matches when the championship is paused?* Root cause: the scan audits the newest researched fixture documents with no notion of time, and during the World Cup pause those are all finished games — the first heal cycle re-researched 22 already-played Copa do Brasil/friendly fixtures (real cost, no reader: nobody reads a pre-match analysis for a finished match). Now `broken_edges` (the alerting/healing metric) covers only groups touching at least one not-yet-played fixture; fully-played groups are counted separately as `broken_played_edges` (archival integrity debt — reported in messages as a note, never paged, never healed). Heal dispatches exclude finished fixtures even in mixed groups; missing/unknown status still counts as relevant so a possibly-live page is never hidden.

## [0.6.1] - 2026-07-01

### Fixed
- **Slack + timeline messages now tell the whole incident, in plain language.** User feedback from the first live heal cycle: the recovered message said "Back to 0 broken (was 1)" after a 13→10→7→4→1→0 drain — the last reading, not the story — and neither message explained what the error *means* or how the fix works. The recovered message now walks the incident's history: "the incident peaked at 13; auto-heal re-researched 22 fixture(s) across 5 round(s) (fresh web search + AI extraction per fixture), no human needed." The detected message now opens with what users are actually seeing ("N match page(s) are showing a pre-match analysis that belongs to a DIFFERENT match") before the LLM's concrete example, and states how the heal works. `context-graph timeline`'s recovered event likewise reports the incident peak.

## [0.6.0] - 2026-07-01

### Added
- **Auto-heal for the `analysis<->fixture` edge** (opt-in via `ANALYSIS_HEAL_WORKFLOW` at provision time). When `context-verify` finds fixtures sharing an identical pre-match analysis (the misattribution class), each affected fixture now gets one **async** `context-heal-runner` dispatch that runs the pod's own per-fixture research workflow (fresh web search + LLM extract + doc update) — regenerating the misattributed analyses instead of just flagging them. Async by design: a dozen sequential researches inside one connector execution is the silent-death failure mode `scan_link` hit at enterprise scale. Bounded twice: `max_fixtures_per_run` (default 5) caps cost per scan with the backlog draining across scheduled scans, and a **no-progress budget** (`max_heal_attempts`, default 3) stops re-dispatching when healing isn't working — a draining backlog (13→10→7) never trips it; a stuck one (13→13→13) escalates to Slack ("could NOT self-heal") instead. Slack messages now distinguish *found + self-healing* from *found, needs a human*.
- **`machina context-graph timeline [--org] [--days N]`** — the self-healing event history: every `detected` → `heal` → `heal-paused`/`recovered` event, reconstructed from the persisted graph-health trail (works retroactively on any pod with history; no new state). The summary line is the ROI number: how many times the loop found and fixed a problem before a human had to. `--org` merges all projects into one chronological stream.

## [0.5.8] - 2026-07-01

### Fixed
- **`context-verify`'s new Slack notify (0.5.7) used the rounded `broken_rate_pct` as its broken/clean signal — `round(100 * 1/500)` is `0`, so a single genuine broken record could round down to a "clean" 0% and never alert.** Found immediately while deploying 0.5.7 to SBOT Prd, on the exact real record it should have caught. Switched to the raw broken-count field per edge (`broken_edges` for `analysis<->fixture`, `misattributed` for `odd<->market<->fixture`) — exact, never rounds away a real finding. The percentage is still shown in messages, just no longer used as the decision signal.

## [0.5.7] - 2026-07-01

### Added
- **`context-verify` posts to Slack on a data-integrity transition.** The two edges with a `broken_rate_pct` verdict (`analysis<->fixture`, `odd<->market<->fixture`) now post when that edge goes from clean to broken, or back — reusing the eval prompt's own assessment text as the message body (already a specific, human-written summary — e.g. "an analysis regarding Vitória vs Flamengo being incorrectly attributed to..."). Silent while an already-flagged issue stays open. Shares the same `slack-notify-config` webhook as `surface-verify.py` — one webhook per pod covers both. The linkability edge (`market->fixture(link)`) has no `broken_rate_pct` and isn't wired to this — its link-rate isn't inherently good/bad the same way (many markets are structurally unlinkable outrights).

## [0.5.6] - 2026-07-01

### Fixed
- **`context-verify`'s linkability edge silently died on enterprise-scale data.** `scan_link` pulls the full fixture + market universe, paginated at 50 docs/request — fine at hundreds of documents, but SBOT Prd (sportingbot.com) has ~4k fixtures + ~1.8k markets, meaning ~116 sequential round-trips inside one connector execution. Long enough to die mid-run server-side with no health doc and no error — not a crash, just silence. Bumped pagination to 500/request (confirmed the same data pulls in ~30s either way; ~116 round-trips → ~12). Also fixed a second, unrelated truncation in the same function: the markets pull was capped at 500 regardless of how many existed (sized for when "markets are few" — not true at 1.8k), silently dropping candidates from the join *before* any of the function's own reported drop-counts could see them.

## [0.5.5] - 2026-07-01

### Added
- **`context-verify` supports per-tenant document names** (`FIXTURE_DOC_NAME` / `MARKETS_DOC_NAME`, default `sportradar-fixture` / `entain-markets-tier3` — unchanged, so existing deployments are unaffected). Needed to provision it on SBOT Prd (sportingbot.com): same underlying fixture/markets schema (`bwin_fixture_id`, `markets_tier3`, `pre_match_research`, ...), verified field-identical, but stored under `sportingbot-fixture` / `sportingbot-markets-tier3` instead of the entain-branded names — running unmodified would have silently audited zero documents.

## [0.5.4] - 2026-07-01

### Fixed
- **`surface-verify`'s odds-heal now has a retry budget.** `trigger_odds_heal` re-runs `entain-coverage-fut-refresh-markets` — a real 15-step workflow that calls the live bwin API — on every `degraded:odds` scan, with no limit on how many times a stuck incident could re-trigger it. It now stops after `max_heal_attempts` (default 3) **consecutive** `degraded:odds` scans, read from the persisted health-doc history (each scan is a fresh, memory-less process), and hands off to a human via Slack ("could NOT self-heal ... needs a human") instead of continuing to re-trigger the workflow. A prior recovery resets the count, so an old resolved incident never counts against a new one. Investigated 2026-07-01: `heal_needed` had never actually fired in `enrichment-production`'s history (0/39 scans) — the gap was latent, not yet a real incident.

## [0.5.3] - 2026-07-01

### Added
- **A "new version available" notice, shown automatically.** Any `machina` command now checks (at most once a day, cached in `~/.machina/update_check.json`) whether a newer release exists, and prints a one-line notice after the command's own output if so — pointing at `machina update`. Zero added latency on ~everything: a fresh cache is a local file read; a stale one kicks off the real GitHub check in a background thread with a 1.5s budget, so a slow network degrades to "check again next time" instead of a hang. Never blocks, never raises, never shows twice in one process, and is suppressed for `--json` output and piped/non-tty stdout so it can never corrupt a script. The REPL shows it once at startup too.

## [0.5.2] - 2026-07-01

### Added
- **`surface-verify` threshold overrides** (`session_floor` / `odds_floor` / `err_ceiling` as workflow inputs, defaulting to the calibrated values — the recurring beat is unaffected). Lets a verdict be forced on demand for testing; used to prove 0.5.1's Slack notify end-to-end against the live `enrichment-production` pod without touching the odds-heal side effect. Note: the workflow engine's `$.get(key, default)` treats `0` as "not provided" — use a small non-zero override (e.g. `0.001`), not `0.0`.

## [0.5.1] - 2026-07-01

### Added
- **`surface-verify` now pings Slack on a verdict transition.** When the live-surface monitor enters a degraded state — or recovers from one — it now posts to a Slack channel (via an incoming webhook), so a human is aware whether or not the auto-heal fixed it: `:adhesive_bandage: self-healed` (odds refresh auto-triggered, no action needed), `:rotating_light: could NOT self-heal` (odds broke and the heal didn't run/errored — needs a human), `:rotating_light: needs review` (error-rate spike — not something auto-heal can fix, likely a code regression), or `:white_check_mark: recovered`. Notifications are **edge-triggered**: an unchanged ongoing state (e.g. a multi-hour `degraded:errors` incident) never re-notifies — the Studio/CLI dashboards already show that continuously — so the channel only gets pinged for news. The webhook lives in a `slack-notify-config` document (provision by setting `SLACK_WEBHOOK_URL` when running `surface-verify.py`), same posture as the PostHog key.

## [0.5.0] - 2026-07-01

### Added
- **`machina org usage --month YYYY-MM` and `--last-month`** — full-calendar-month token totals for invoicing an org for a completed month (inclusive first..last day, leap-year correct). Precedence is `--month` > `--last-month` > `--days`; the resolved window and a human label appear in the panel and in `--json` (`window.label`). Because the ledger is permanent, prior months are fully available. (#51)

### Fixed
- **`machina org usage` now reads the permanent `organization_ledger` via core-api instead of per-project agent executions.** Agent-execution token records (`execution_tokens`) are purged after ~5 days, so a "last 30d" scan really summed only the retained days and undercounted ~6× vs the Studio usage view (e.g. SBOT Prd reported ~297M instead of ~1.80B, and the total shrank day-over-day). It now uses the same ledger source as Studio, so the total matches and covers the full window. The headline + by-day come from `{scope}/{id}/usage`; the by-project / by-agent breakdown is best-effort from `{scope}/{id}/usage/export` (omitted with a note if it fails on a very large org). The per-tenant scan and INCOMPLETE/PARTIAL machinery are removed; `--json` keeps the `incomplete`/`projects_*` keys (now inert) for back-compat and adds `source` and `breakdown_available`. (#51)

## [0.4.9] - 2026-07-01

### Fixed
- **`machina context-graph status --org` no longer leaks per-project errors.** Projects that are unreachable or forbidden made `ProjectClient` print `Error authenticating project` / `Client API error.` / `Cannot reach Client API …` before raising — which cluttered the table and corrupted `--json` output. The org rollup now silences per-project stderr and skips those projects cleanly (counted in `skipped`), so `--json` stays valid.

## [0.4.8] - 2026-06-30

### Added
- **`machina context-graph status`** — see the self-healing / monitoring layer from the CLI (the same truth the Studio Context Graph page shows). Per project it lists the verified edges + health (e.g. `market → team linked 52.5%`, `market ↔ price quality degraded 34.1%`), the live surface verdict (odds/errors, with session-normalized signals + exception count), and the self-heal agents with their beat status — and warns when a beat is `active` but `scheduled=True` (silently not firing). `--org` rolls it up across every project in the org; `--json` for scripts. Answers "what self-healing is running, where, and how healthy" without opening each project one by one.

## [0.4.7] - 2026-06-30

### Added
- **The harness loop can now read documents and real conversations.** Its tool catalog gained `read_documents` (read any document on the project pod by name — copilot threads, harness sessions, fixtures, config docs, via the same `document_search` the MCP uses) and `fetch_conversations` (recent real SportingBOT end-user chat transcripts from PostHog — user context + bot answer + category, read from `posthog.ai_events`). Before, the loop only had `find_fixtures`/`calculate`/`get_datetime`/`echo`, so "analyse the recent chats and suggest bot improvements" got "give me the logs"; it now pulls live transcripts and returns grounded, evaluator-checked findings. (#41)

### Fixed
- **`machina login --api-key` no longer discards a valid key.** The key was verified against `login/session`, which returns 5xx for API-key auth; the client read that as "key invalid", deleted the just-stored key, and silently fell back to the session token (printing "Authenticated as Unknown"). The client now never clears the key on a 5xx — it falls back for the current request only, and only when a session-token retry actually succeeds — and `login --api-key` verifies without that fallback and reports an honest result. The key is always kept. (#42)
- **Release pipeline no longer ships empty releases.** The `github-release` CI step used `gh release create`, which errors when the release already exists (e.g. cut from the GitHub UI, which also creates the triggering tag) and then dies before attaching the binaries. It is now idempotent — create, or upload assets onto the existing release. (#43)

## [0.4.4] - 2026-06-30

### Fixed
- **`machina org usage` shows a readable label for nameless project stubs.** Some `user/projects/search` records are bare membership stubs (`project_id` only, no `project_name` — e.g. a deleted project's leftover association); they were rendered as a raw 24-char ObjectId in the "Skipped" line. They now show `(unnamed:<id8>)`. The project is still scanned (never silently excluded over a missing name), so a real project can't be dropped this way.

## [0.4.3] - 2026-06-30

### Fixed
- **`machina org usage` no longer silently drops a project on a transient error.** The big collections (e.g. `sbot-prd`) return intermittent `500`s under load; the previous build caught that as "unreachable" and skipped the project, producing a complete-looking but wildly undercounted total (e.g. 73M instead of ~440M when SBOT Prd dropped). Now:
  - Each project session + execution page is **retried** on transient failures (`500`/timeout) with backoff, so the heavy projects scan through.
  - A reachable project whose scan still fails is reported as **errored** and the run is flagged **INCOMPLETE / PARTIAL** in red (with the affected projects listed) — distinct from a benign **skip** of an undeployed/no-access project. A partial total is never presented as if it were whole. `--json` gains `incomplete`, `projects_errored`, `projects_skipped`.

## [0.4.2] - 2026-06-29

### Added
- **`machina org usage`**: roll up LLM token consumption across an organization's agent executions — the repeatable answer to "how many tokens did this org consume". Token usage is recorded on **agent** executions (`execution_tokens`), not workflow executions, and the Client-API `execution/agent-search` totals are **page-level only**, so the command iterates the org's projects and paginates+sums client-side, broken down by **project, agent, and day**, with the prompt/completion split surfaced (the cost-shape signal — SportingBOT's chat is ~98% prompt tokens). Flags: `--org` (defaults to the selected org), `--project` to scope to one, `--days` window (default 30; a frozen upper bound keeps pagination stable as new runs arrive), `--top`, `--limit`, and `--json`. Unreachable/undeployed projects are skipped and listed under `projects_unreachable` rather than failing the run. Verified end-to-end against the live Entain SportingBOT deployment.

## [0.4.1] - 2026-06-26

### Added
- **Loop retry-with-critique (Cap 8.2).** When the gate passes but the independent evaluator *rejects* a turn's answer, the loop now does ONE bounded repair pass — feeding the rejection reason back into a `loop-repair` prompt — then re-verifies with `loop-evaluate-2` before deciding `idle` vs `needs_review`. Generator/evaluator → generator/evaluator/**repairer**. A *gate* failure is still never repaired (straight to `needs_review`); the repair is bounded to one pass (no loop). `value.verification.repaired` records whether a turn self-healed; the CLI appends `· self-repaired` to the verdict line. Provisioner adds the `loop-repair` + `loop-evaluate-2` prompts.

## [0.4.0] - 2026-06-26

### Added
- **Loop verification — the generator/evaluator separation (Cap 8).** A loop turn is now finalized `idle` only after it clears a **deterministic gate** (cheap, code-only — a non-trivial answer, no error marker, and the tool succeeded if one ran) **and** an **independent evaluator** (`loop-evaluate`: a separate prompt with a fresh context + an "assume it's wrong" posture and its own `EVAL_MODEL`). Any failure → **`needs_review`**, the human checkpoint — never a silent pass. The resume path carries an attempt budget (`LOOP_MAX_ATTEMPTS`) so the beat can't re-run a stuck session forever. Verified live against a staging pod.
  - `machina loop` (`run`/`watch`/`say`) now treats `needs_review` as terminal and renders the evaluator's verdict (`✓ verified` / `⚠ needs review — <reason>`).
  - Provisioner `docs/harness-loop-kit/provision.py` gains the `loop-evaluate` prompt, the gate, and the attempt budget; tunable via `EVAL_MODEL` (use a stronger model than the generator in prod) and `LOOP_MAX_ATTEMPTS`.
  - New: `docs/harness-loop-kit/PLAYBOOK-SCORECARD.md` — the loop scored against the Loop-Engineering playbook (the five failure modes, the First-Loop Checklist, the Stripe-Minions pattern) with the live verification results.

## [0.3.0] - 2026-06-26

### Added
- **`machina loop …`**: drive a durable agentic turn loop (harness) that runs server-side on Studio primitives, with the CLI as a thin driver/observer (same pattern as `machina factory`). Commands: `run`, `watch`, `say`, `stop`, `sessions`.
  - **Durable**: the loop is a scheduled agent + `harness_session` documents; each turn is persisted before advancing, and the beat resumes a session left `active` (survives crash / async tool / awaiting input). A turn ends at `idle` (awaiting the next `say`).
  - **Multi-turn**: `say` injects a follow-up; prior conversation is fed back to the model. `watch` is turn-aware and streams new turns (incl. `→ tool` / `← result` steps).
  - Server-side resources (prompt/workflow/agent) live in the project's Studio; the CLI reuses the existing project session — no new credential.
  - Architecture + chapter-by-chapter build (caps 1–7) and verified platform contracts: `docs/agentic-harness-loop.md`. Dynamic multi-tool dispatcher reference: `docs/loop-tools-connector.py`.

## [0.2.27] - 2026-06-25

### Added
- **`machina connect [project]`**: one-command MCP connection bundle for external agents (e.g. sportsclaw) — emits `{name, url, transport, auth_header, token, masked, durable}` so an agent can register a Machina MCP server with no hand-pasted URL. Token is masked by default; `--reveal` emits it (in `--json`, `token` is `null` unless `--reveal`, so a script can't mistake a redacted string for a credential). `--mint` reuses or creates a dedicated `sportsclaw-<project>` project API key for a durable connection (refuses to mint a duplicate); `--org` supplies the organization inline; `--probe` checks reachability with the credential actually emitted.
- **`machina mcp url [project]`**: resolve a project's MCP endpoint (`{client-api}/mcp/sse`, SSE transport, `X-Api-Token`/`X-Session-Token` auth) from the project-token JWT `api` claim. `--probe` verifies the SSE endpoint is reachable and fails loud on a wrong derivation; `--json` for machine output. Verified against machina-core-api + machina-client-api.
- **`--json` on identity/config/deploy commands**: `whoami`, `config get`, `config list`, `deploy status`, and `credentials list` now emit machine-readable JSON. Error paths use a consistent `{"error": ...}` envelope with a non-zero exit.
- **`docs/credentials.md`**: documents `~/.machina/config.json` + `credentials.json` as a stable integration contract (fields, mode `600`, env overrides, `resolve_auth_token` precedence) so other tools can read it for unified, one-time login.
- REPL: `mcp` and `connect` added to the command list, tab-completion, and help.

### Changed
- **Secret redaction**: `config list` masks secret-looking keys; `config get <secret>` masks by default with `--reveal` to opt in. `credentials list` key masking is fail-safe — a short key is never echoed verbatim, and the JSON `masked` flag is honest.

### Fixed
- `config get --json` now signals a missing key (`{"error": "key not found"}` + exit 1) instead of `value: null` with exit 0.
- `deploy status` and `credentials list` in `--json` mode emit a JSON error envelope on API failure instead of no output.

## [0.2.26] - 2026-05-31

### Changed
- **REPL `help` + tab-completion now list every command group.** Added the missing `factory` (Build apps / Factory coding-agent) and `sports` (sports-skills passthrough) entries under Operations, plus `login` / `update` / `version` under Session. `factory` and its sub-commands (`run`/`status`/`watch`/`logs`/`follow-up`/`cancel`/`open-pr`/`list`/`whoami`) are now tab-completable.

### Added
- **`docs/factory.md`** — usage guide for the `machina factory` commands.

## [0.2.25] - 2026-05-30

### Added
- **`machina factory …`**: trigger Factory coding-agent builds from the CLI. Drives the customer surface (`customers.machina.gg/c/api/*`) using the studio session the CLI already holds — the same auth the `/c` web UI uses, **no new credential**. Commands: `run`, `status`, `watch`, `logs` (live SSE timeline), `follow-up`, `cancel`, `open-pr`, `list`, `whoami`.
  - **Session mode** (default): reuses your `machina login` session — jobs are owned by your user.
  - **API-key mode** (headless / CI): set `MACHINA_API_KEY` to a project API key and the CLI sends `X-Api-Token`; jobs are scoped to the key's organization. Requires the matching customers-side change (machina-factory-customer#136).
  - New config key `factory_url` (default `https://customers.machina.gg`); override with `MACHINA_FACTORY_URL`. Session-cookie name overridable with `MACHINA_SESSION_COOKIE_NAME` (prod default `machina_production_session_name`).

## [0.2.24] - 2026-04-20

### Added
- **`machina sports …`**: full sports-skills CLI mounted dynamically under `machina sports` (catalog, schema, every domain — `football`, `f1`, `nfl`, `polymarket`, …). Output is byte-identical to running `sports-skills` directly, and new sports-skills releases surface automatically without a machina-cli upgrade.
- **`machina template install --private` + `--gh-token`**: install a template from a private GitHub repo. `--gh-token` falls back to `GH_TOKEN` / `GITHUB_TOKEN` env vars, and is forwarded both to the platform's `templates/git` endpoint and to the GitHub-API contents fetch used to download local agent context.

### Fixed
- **Lint**: drop an extraneous f-string prefix in `auth.py` that was breaking ruff CI on main.

## [0.2.23] - 2026-04-12

### Added
- **MFA support for `--with-credentials` login**: when a user has MFA enabled, the CLI prompts for a TOTP code or backup code and completes verification via `POST /mfa/verify`
- **Skills commands**: `machina skills list`, `machina skills run` for managing and executing project skills

## [0.2.22] - 2026-04-06

### Added
- **`machina auth clear-session`**: nuclear option to clear all local credentials + browser cookies when staging login is stuck in a loop
- **`machina auth logout`**: now also opens browser to clear server-side session cookies (Clerk + machina)

## [0.2.21] - 2026-04-05

### Fixed
- **Template install**: use correct endpoint `templates/git` (was `templates/directories/git`) and field name `repo_branch` (was `branch`), matching the Studio implementation

## [0.2.20] - 2026-04-05

### Fixed
- **`machina version`**: now reports the correct version from `__version__` instead of stale pip metadata
- **API key auto-fallback**: when an API key returns 500 (e.g. missing from Redis), the CLI automatically clears it and retries with the session token if available
- **Login enters REPL**: `machina login` now starts the interactive REPL after successful authentication instead of exiting

## [0.2.19] - 2026-04-05

### Fixed
- **API key login verification**: `login/session` returns 500 with API keys — now falls back to org search as verification, with clear feedback on success or failure

## [0.2.18] - 2026-04-05

### Fixed
- **Template install/push**: fix false-positive error checks that could treat successful responses as failures (status check now only triggers on explicit `"error"` status)
- **Template cleanup**: remove duplicate imports, dead comments, and extra blank lines from template.py

## [0.2.17] - 2026-04-05

### Fixed
- **Browser login 404**: switch auth flow from `/cli/auth` (page not deployed) to `/clerk/sign-in?cli_callback=...` which is handled by the SESSION middleware directly

## [0.2.16] - 2026-04-05

### Fixed
- **Lint fixes**: resolve ruff errors in template.py (duplicate imports, misplaced module-level imports, `== False` comparisons)

## [0.2.15] - 2026-04-05

### Fixed
- **Expired token detection**: session tokens are now checked for JWT expiry before API calls — expired tokens are automatically cleared with a clear "not authenticated" message instead of hitting the API and getting cryptic "Invalid Session Key" errors
- **Project token cleanup**: expired project tokens are now cleared from credentials on detection or 401 response, so re-running the command auto-refreshes
- **Auth guard on API calls**: unauthenticated requests are caught early with guidance to run `machina login`

## [0.2.14] - 2026-03-30

### Fixed
- **Browser login**: fixed 500 error on `/api/auth/cli-token` — now correctly handles backend 303 redirect and extracts session token from `Set-Cookie` headers
- **REPL shortcuts**: `logout`, `login`, `whoami` now work directly in the REPL without the `auth` prefix

## [0.2.13] - 2026-03-29

### Added
- **Run agents from CLI**: `machina agent run <name>` — run agents with interactive input prompts or inline `key=value` parameters. Supports `--sync`, `--watch`, and `--json` modes
- **Run workflows from CLI**: `machina workflow run <name>` — same interactive/inline experience. Sync by default, `--async` and `--watch` available
- **Interactive input prompts**: when running without parameters, the CLI fetches available inputs from the agent/workflow definition and prompts the user with defaults extracted from the config (e.g. `limit (default: 50):`)
- **Inline parameters**: pass `key=value` pairs directly for scripting: `machina agent run my-agent season_id=sr:season:123 force=true`

## [0.2.11] - 2026-03-29

### Added
- **Release notes on update**: `machina update` now shows "What's new" from GitHub Release notes before downloading
- **Changelog-driven releases**: GitHub Actions extracts notes from CHANGELOG.md for each release instead of auto-generated notes

### Changed
- Synced `__version__` in `__init__.py` with `pyproject.toml`

## [0.2.10] - 2026-03-29

### Added
- **Agent activity view**: `agent get <name>` now shows full agent detail — workflows with descriptions and conditions, context variables, scheduling status, frequency, last execution time
- **Agent list improvements**: shows title, scheduled status, and last execution in the list view

## [0.2.9] - 2026-03-29

### Fixed
- **CLI login flow**: new `/cli/auth` page and `/api/auth/cli-token` API endpoint in machina-session — fixes login when user is already authenticated with Clerk (previously redirected to Studio instead of completing CLI auth)
- **Timeout fallback**: when browser auth times out, shows clear instructions for alternative auth methods (`--api-key` or `--with-credentials`)

## [0.2.8] - 2026-03-29

### Fixed
- Removed customer-specific references from README

## [0.2.7] - 2026-03-29

### Fixed
- Ruff linting errors that blocked the CI pipeline

## [0.2.6] - 2026-03-29

### Fixed
- CI/CD pipeline: added `contents: write` and `id-token: write` permissions for PyPI OIDC trusted publisher

## [0.2.5] - 2026-03-29

### Added
- **Connector commands**: `connector list`, `connector get <name>`
- **Mapping commands**: `mapping list`, `mapping get <name>`
- **Prompt commands**: `prompt list`, `prompt get <name>` (shows content preview)
- **Document commands**: `document list`, `document get <id>` (shows content preview)
- All new commands support `--json`, `--limit`, `--page`, `--project`

## [0.2.4] - 2026-03-29

### Changed
- **Execution commands reworked**: `execution get` now uses correct `agent-run` API endpoint, shows name, status, execution time, workflow count, response JSON, and individual workflow statuses
- **Updater simplified**: always downloads binary from GitHub Releases to `/usr/local/bin` — no more install method detection confusion
- **Dropped keyring dependency**: credentials stored in `~/.machina/credentials.json` with chmod 600 (no more macOS Keychain password popups)

## [0.2.3] - 2026-03-29

### Added
- **Pagination everywhere**: `org list`, `project list` now support `--limit`, `--page`, `--json`
- **REPL bare flags**: type `project list limit 5` instead of `project list --limit 5` inside the REPL

### Fixed
- REPL `--help` and `-h` now show help instead of erroring
- REPL auto-strips `machina` prefix if typed by habit

## [0.2.1] - 2026-03-29

### Fixed
- REPL `click.exceptions.SystemExit` import error (removed, using built-in `SystemExit`)
- REPL now ignores `machina` prefix when user types `machina agent list` inside session

## [0.2.0] - 2026-03-29

### Added
- **Interactive REPL mode**: run `machina` with no arguments to enter an interactive session with tab completion, command history, and org/project context in the prompt
- **Execution commands**: `execution get <id>`, `execution list`
- **Credentials improvements**: `--show-keys` to reveal full API keys, `--copy client-api` to copy to clipboard
- **Shell prompt**: `machina shell-prompt` outputs `✦ OrgName/ProjectName` for terminal integration
- **Grouped help**: banner and REPL help organized by category (Platform, Resources, Operations)
- Org/project names resolved and saved on `use` command

## [0.1.1] - 2026-03-29

### Fixed
- **Org list**: reads `organization_name`, `organization_slug`, `organization_id` from API (was reading wrong fields)
- **Project list**: reads `project_name`, `project_slug`, `project_id` from API lookup
- **Banner colors**: works on both light and dark terminal themes
- **Dynamic version**: uses `importlib.metadata` instead of hardcoded `__version__`

## [0.1.0] - 2026-03-29

### Added
- **Browser login**: opens browser for Clerk SSO / magic link authentication
- **API key login**: `machina login --api-key <key>` for CI/CD
- **Username/password login**: `machina login --with-credentials` for dev environments
- **Self-update**: `machina update` downloads latest binary from GitHub Releases
- **Organization commands**: `org list`, `org create`, `org use`
- **Project commands**: `project list`, `project create`, `project use`, `project status`
- **Workflow commands**: `workflow list`, `workflow get <name>`
- **Agent commands**: `agent list`, `agent get <name>`, `agent executions`
- **Template commands**: `template list` (browse Git repository)
- **Credentials commands**: `credentials list`, `credentials generate`, `credentials revoke`
- **Deploy commands**: `deploy start`, `deploy status`, `deploy restart`
- **Config commands**: `config list`, `config set`, `config get`
- **ASCII banner**: MACHINA ✦ SPORTS wordmark on launch
- Secure credential storage in `~/.machina/credentials.json`
- Config in `~/.machina/config.json`
