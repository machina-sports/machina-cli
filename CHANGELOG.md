# Changelog

All notable changes to machina-cli are documented here.

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
