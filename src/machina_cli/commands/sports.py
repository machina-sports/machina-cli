"""Dynamic passthrough to the ``sports-skills`` CLI.

The entire sports-skills command surface (football, f1, nfl, polymarket, kalshi,
news, …) is mounted under ``machina sports`` so that any future module or
command added to sports-skills is picked up automatically — we never enumerate
the sub-commands in this file. See ``sports_skills/cli.py`` for the
introspectable registry backing the delegation.
"""

from __future__ import annotations

import sys
from typing import Iterable, List

import typer


def _invoke_sports_skills(argv: Iterable[str]) -> int:
    """Call ``sports_skills.cli.main`` with a fabricated argv.

    Preference order per the integration spec:
        1. Native in-process invocation (import the package and call ``main``).
           This is argparse-based today but we re-use whatever entrypoint the
           installed sports-skills exposes, so upgrades Just Work.
        2. Subprocess to the ``sports-skills`` console script as a last-resort
           fallback if the package cannot be imported (e.g. stripped install).
    """
    argv_list: List[str] = ["sports-skills", *argv]

    try:
        from sports_skills import cli as sports_skills_cli  # type: ignore
    except ImportError:
        # Last-resort fallback: forward to the installed console script.
        import subprocess

        try:
            completed = subprocess.run(
                argv_list,
                stdin=sys.stdin,
                stdout=sys.stdout,
                stderr=sys.stderr,
            )
        except FileNotFoundError as exc:  # pragma: no cover - extremely unlikely
            typer.echo(
                "sports-skills is not installed. Reinstall machina-cli or "
                f"run `pip install sports-skills` manually ({exc}).",
                err=True,
            )
            return 127
        return completed.returncode

    # In-process delegation — rewrite sys.argv so argparse sees the right prog.
    saved_argv = sys.argv
    sys.argv = argv_list
    try:
        result = sports_skills_cli.main()
    except SystemExit as exc:  # argparse / --help raise SystemExit
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        # Non-int exit codes are treated as error messages by argparse.
        typer.echo(str(code), err=True)
        return 1
    finally:
        sys.argv = saved_argv

    if isinstance(result, int):
        return result
    return 0


# NOTE: we intentionally do NOT use ``typer.Typer`` here. Typer/Click groups
# intercept ``--help`` and pretty-print their own help screen, which would
# mask the sports-skills help output. Instead we expose a single command on
# the root app that swallows every argument and forwards it verbatim.
#
# This single-command form is still invoked as ``machina sports …`` and
# therefore matches the "top-level command group" naming convention used by
# the rest of machina-cli (workflow, agent, skills, …).
SPORTS_CONTEXT_SETTINGS = {
    "allow_extra_args": True,
    "ignore_unknown_options": True,
    # Disable Click's automatic --help so sports-skills can render its own.
    "help_option_names": [],
}


def register(app: typer.Typer) -> None:
    """Attach the ``sports`` command to the given Typer app."""

    @app.command(
        "sports",
        context_settings=SPORTS_CONTEXT_SETTINGS,
        help=(
            "Delegate to the sports-skills CLI. "
            "Run `machina sports --help` to see every module (football, f1, "
            "nfl, nba, polymarket, kalshi, news, …) the installed "
            "sports-skills version exposes."
        ),
        # Prevent Typer from rendering a rich help page that would hide the
        # sports-skills help output.
        rich_help_panel="Sports",
    )
    def sports(ctx: typer.Context) -> None:
        code = _invoke_sports_skills(ctx.args)
        if code:
            raise typer.Exit(code=code)
