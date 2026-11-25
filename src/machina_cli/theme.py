"""The machina-cli design system.

One place that decides what the CLI looks like, so a command never has to.

Three rules hold the whole thing together:

1. **Colour is punctuation, not paint.** A status glyph carries the colour; the
   sentence after it stays default-foreground. Painting whole sentences red is
   what makes a terminal shout -- a red ``✕`` in front of plain text says the
   same thing and stays readable on light and dark themes alike.
2. **One accent.** Machina orange marks the brand and the current thing. Green /
   yellow / red / cyan mean *state*, and appear only on glyphs and status values.
3. **Every surface degrades.** Narrow terminals, no-colour pipes and ASCII-only
   fonts all have a defined fallback -- never a broken layout.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from typing import Any

from rich import box
from rich.console import Console, Group, RenderableType
from rich.table import Table
from rich.text import Text

# --- palette ---------------------------------------------------------------
ACCENT = "#FF5C1F"  # Machina orange — brand + "the current thing"
ACCENT_DIM = "#A33B14"  # orange at rest: rules, inactive borders
INK = "#3C96B4"  # the secondary brand blue — versions, links, ids

WORDMARK_FG = "grey70"  # the logo's letterforms (the mark itself is ACCENT)

MUTED = "grey62"  # secondary text: descriptions, units, footers
DIM = "grey39"  # tertiary: hints, separators, disabled
LINE = "grey30"  # borders and rules

OK = "green"
WARN = "yellow"
ERR = "red"
INFO = "cyan"

# --- glyphs ----------------------------------------------------------------
BRAND_GLYPH = "✦"

_UNICODE = {
    "ok": "✓",
    "err": "✕",
    "warn": "▲",
    "info": "ⓘ",
    "hint": "→",
    "run": "●",
    "wait": "○",
    "bullet": "·",
    "tree": "└",
    "branch": "├",
    "pipe": "│",
}
_ASCII = {
    "ok": "+",
    "err": "x",
    "warn": "!",
    "info": "i",
    "hint": ">",
    "run": "*",
    "wait": "o",
    "bullet": "-",
    "tree": "`",
    "branch": "|",
    "pipe": "|",
}

SPINNER = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
SPARK = "▁▂▃▄▅▆▇█"
METER_FULL = "█"
METER_HALF = "▓"
METER_EMPTY = "░"


def _ascii_only() -> bool:
    """True when the terminal cannot be trusted with box drawing / glyphs."""
    if os.environ.get("MACHINA_ASCII"):
        return True
    encoding = (getattr(sys.stdout, "encoding", "") or "").lower()
    return "utf" not in encoding


def glyph(name: str) -> str:
    return (_ASCII if _ascii_only() else _UNICODE).get(name, "")


# --- consoles --------------------------------------------------------------
# Two streams, because a CLI that writes diagnostics to stdout cannot be piped.
# Results go to stdout; anything that reports trouble goes to stderr, so
# `machina ... --json | jq` keeps working while the operator still sees why.
console = Console(highlight=False)
error_console = Console(highlight=False, stderr=True)


def width() -> int:
    return console.width or shutil.get_terminal_size((80, 24)).columns


# --- status lines ----------------------------------------------------------
@dataclass(frozen=True)
class _Level:
    key: str
    color: str


_LEVELS = {
    "ok": _Level("ok", OK),
    "err": _Level("err", ERR),
    "warn": _Level("warn", WARN),
    "info": _Level("info", INFO),
    "hint": _Level("hint", DIM),
}


def status(level: str, message: str, *, detail: str | None = None, indent: int = 1) -> Text:
    """Build one status line: a coloured glyph, then plain text.

    ``detail`` is the quieter half -- an id, a path, a reason -- set in MUTED so
    the eye lands on the message first.
    """
    spec = _LEVELS[level]
    line = Text(" " * indent)
    line.append(f"{glyph(spec.key)} ", style=f"bold {spec.color}")
    line.append(message)
    if detail:
        line.append(f"  {detail}", style=MUTED)
    return line


def ok(message: str, *, detail: str | None = None) -> None:
    console.print(status("ok", message, detail=detail))


def err(message: str, *, detail: str | None = None) -> None:
    error_console.print(status("err", message, detail=detail))


def warn(message: str, *, detail: str | None = None) -> None:
    error_console.print(status("warn", message, detail=detail))


def info(message: str, *, detail: str | None = None) -> None:
    console.print(status("info", message, detail=detail))


def hint(message: str) -> None:
    """A next step the user can run. Commands inside render bold."""
    console.print(status("hint", message))


def fix(message: str, command: str) -> None:
    """An error's remedy: what went wrong, then the exact command that fixes it.

    Goes to stderr, because it only ever follows an ``err`` or a ``warn`` and
    belongs with them.
    """
    line = Text("   ")
    line.append(f"{glyph('hint')} ", style=DIM)
    line.append(message, style=MUTED)
    line.append("  ")
    line.append(command, style=f"bold {ACCENT}")
    error_console.print(line)


# --- structure -------------------------------------------------------------
def rule(title: str, *, subtitle: str | None = None) -> Text:
    """A section header: an accent tick, the title, then a rule to the margin."""
    line = Text()
    line.append("▌ ", style=ACCENT)
    line.append(title, style="bold")
    if subtitle:
        line.append(f"  {subtitle}", style=MUTED)
    pad = width() - line.cell_len - 2
    if pad > 2:
        line.append(" " + "─" * pad, style=LINE)
    return line


def kv(pairs: list[tuple[str, Any]], *, key_width: int = 0, indent: int = 2) -> Table:
    """An aligned key/value block -- the detail view's workhorse."""
    table = Table.grid(padding=(0, 2))
    table.add_column(style=MUTED, justify="left", min_width=key_width or 12, no_wrap=True)
    table.add_column(overflow="fold")
    for key, value in pairs:
        rendered = value if isinstance(value, Text) else Text(str(value))
        table.add_row(Text(" " * indent + str(key)), rendered)
    return table


def table(title: str | None = None, *, expand: bool = False) -> Table:
    """The list view. Header in accent, hairline rules, no heavy chrome."""
    return Table(
        title=Text(title, style="bold") if title else None,
        title_justify="left",
        header_style=f"bold {ACCENT}",
        border_style=LINE,
        box=box.SIMPLE_HEAD,
        collapse_padding=True,
        pad_edge=False,
        show_edge=False,  # SIMPLE_HEAD still emits blank edge rows otherwise
        expand=expand,
    )


def panel_group(*renderables: RenderableType) -> Group:
    return Group(*renderables)


# --- data display ----------------------------------------------------------
def sparkline(values: list[float], *, style: str = ACCENT) -> Text:
    """A one-line trend. Flat series render as a mid-level baseline."""
    numbers = [float(v) for v in values if isinstance(v, (int, float))]
    if not numbers:
        return Text("", style=MUTED)
    low, high = min(numbers), max(numbers)
    span = high - low
    if span == 0:
        # A flat series at zero is *no activity* — draw it on the floor, dim, so
        # it never reads as steady mid-level traffic.
        if high == 0:
            return Text(SPARK[0] * len(numbers), style=LINE)
        return Text(SPARK[3] * len(numbers), style=style)
    scale = len(SPARK) - 1
    return Text(
        "".join(SPARK[round((n - low) / span * scale)] for n in numbers),
        style=style,
    )


def meter(
    fraction: float,
    *,
    size: int = 20,
    style: str | None = None,
    ramp: str = "usage",
) -> Text:
    """A proportion bar.

    ``ramp`` says which end is bad, because the same bar means opposite things
    in the two places we draw it: ``"usage"`` (quota, tokens, storage) goes red
    as it fills, ``"health"`` (verified edges, pass rate) goes red as it empties.
    """
    frac = max(0.0, min(1.0, float(fraction)))
    if style is None:
        if ramp == "health":
            style = OK if frac >= 0.9 else WARN if frac >= 0.7 else ERR
        else:
            style = OK if frac < 0.7 else WARN if frac < 0.9 else ERR
    filled = int(frac * size)
    remainder = frac * size - filled
    bar = METER_FULL * filled
    if remainder >= 0.5 and filled < size:
        bar += METER_HALF
    out = Text(bar, style=style)
    out.append(METER_EMPTY * (size - out.cell_len), style=LINE)
    return out


def state(value: Any) -> Text:
    """Render a status word with its glyph, so state reads without colour."""
    raw = str(value if value not in (None, "") else "unknown")
    key = raw.lower().replace("_", "-")
    if key in {"true", "active", "online", "success", "completed", "approved", "executed", "ok"}:
        return Text.assemble((f"{glyph('ok')} ", OK), (raw, OK))
    if key in {"false", "failed", "error", "offline", "rejected", "cancelled"} or "fail" in key:
        return Text.assemble((f"{glyph('err')} ", ERR), (raw, ERR))
    if key in {"pending", "running", "processing", "queued", "scheduled"}:
        return Text.assemble((f"{glyph('run')} ", WARN), (raw, WARN))
    if key in {"draft", "inactive", "paused", "unknown", "stale"}:
        return Text.assemble((f"{glyph('wait')} ", MUTED), (raw, MUTED))
    return Text(raw, style=MUTED)
