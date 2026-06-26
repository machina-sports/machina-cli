# Changelog

All notable changes to machina-cli are documented here.

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
