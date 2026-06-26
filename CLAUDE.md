# CLAUDE.md - machina-cli Guidelines

## Tech Stack
- Language: Python 3.10+
- Package Manager: uv (for local development dependencies)
- Build System: hatch / hatchling
- Shell Scripts: install.sh, install.ps1 (must be kept functional and lightweight)

## Commands
- Install for development: `uv pip install -e .`
- Build package: `hatch build`
- Run CLI locally: `python -m machina_cli` or `machina` (if installed in dev mode)
- Format Code: `ruff format .`
- Lint Code: `ruff check .`

## Code Conventions
- No Heavy Dependencies: The CLI must remain a thin, fast shell. Avoid adding thick libraries (like pandas, heavy SDKs) unless strictly required.
- Standard Output: Always output structured JSON when `--json` flag is provided. Default console output must be clean, ANSI-colored, and user-friendly.
- Files: kebab-case or snake_case as appropriate for Python.
