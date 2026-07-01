"""Opportunistic "a new version is available" notice.

Checked at most once a day, cached in ~/.machina/update_check.json (separate
from config.json, which holds user settings, not internal state). Never
blocks a command for more than a fraction of a second: a stale cache kicks
off the real network check in a background thread with a short join budget,
so slow networks degrade to "check again next time" instead of a hang. Never
raises -- an update notice is a nicety, not something that should ever break
a command. Printed at most once per process, and suppressed for --json
output / non-tty stdout so it can never corrupt a script or a pipe.
"""

import json
import sys
import threading
import time

from machina_cli import __version__
from machina_cli.config import CONFIG_DIR

CACHE_FILE = CONFIG_DIR / "update_check.json"
CHECK_INTERVAL_SECONDS = 24 * 60 * 60  # once a day
NETWORK_BUDGET_SECONDS = 1.5  # never make a command wait longer than this

_shown = False  # per-process guard -- never print the banner twice (e.g. once
# at REPL start, once again when the process later exits)


def _parse_version(v: str) -> tuple:
    parts = []
    for p in v.split("."):
        digits = "".join(c for c in p if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _is_newer(latest: str, current: str) -> bool:
    try:
        return _parse_version(latest) > _parse_version(current)
    except Exception:
        return False


def _read_cache() -> dict:
    try:
        return json.loads(CACHE_FILE.read_text())
    except Exception:
        return {}


def _write_cache(data: dict) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(data))
    except Exception:
        pass


def _refresh_in_background(result: dict) -> None:
    """Runs in a daemon thread: the real network call + cache write. If the
    process exits before this finishes, it's simply abandoned -- the next
    invocation's stale-cache branch tries again, so nothing gets corrupted."""
    try:
        from machina_cli.updater import get_latest_version

        latest = get_latest_version()
    except Exception:
        latest = None
    if latest:
        result["latest_version"] = latest
        result["fetched"] = True
        _write_cache({"last_checked": time.time(), "latest_version": latest})


def _should_show() -> bool:
    """Suppress in non-tty (piped/scripted) or --json contexts, and for the
    `update` command itself (it already does its own explicit check)."""
    if not sys.stdout.isatty():
        return False
    if any(a in ("--json", "-j") for a in sys.argv):
        return False
    if "update" in sys.argv:
        return False
    return True


def maybe_notify_update() -> None:
    global _shown
    if _shown or not _should_show():
        return

    cache = _read_cache()
    stale = (time.time() - cache.get("last_checked", 0)) > CHECK_INTERVAL_SECONDS
    latest = cache.get("latest_version")

    if stale:
        result = {}
        t = threading.Thread(target=_refresh_in_background, args=(result,), daemon=True)
        t.start()
        t.join(timeout=NETWORK_BUDGET_SECONDS)
        if result.get("fetched"):
            latest = result["latest_version"]

    if latest and _is_newer(latest, __version__):
        _shown = True
        from rich.console import Console

        console = Console(highlight=False)
        console.print(
            f"\n[dim]A new version of machina-cli is available:[/dim] "
            f"[bold]{__version__}[/bold][dim] → [/dim][bold green]{latest}[/bold green]"
        )
        console.print("[dim]Run[/dim] [bold]machina update[/bold] [dim]to upgrade.[/dim]")
