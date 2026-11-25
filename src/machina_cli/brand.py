"""Machina Sports brand marks for the terminal.

The wordmark is a hand-tuned 6px bitmap folded into half-block characters, so it
stays crisp at any terminal font size and costs nothing at runtime (the art is
baked in as literals -- no font, no rasterizer, no dependency).

Three lockups, picked by available width:

    FULL      >= 60 cols   MACHINA over the star + SPORTS, the real logo
    WORDMARK  >= 52 cols   MACHINA alone
    COMPACT   anything     the star + the name on one line

``lockup()`` does that choice for you.
"""

from __future__ import annotations

from rich.console import Group
from rich.text import Text

from machina_cli.theme import ACCENT, BRAND_GLYPH, MUTED, WORDMARK_FG

# --- the marks -------------------------------------------------------------
# MACHINA — 3 rows, 50 cols
MACHINA: tuple[str, ...] = (
    "██▄ ▄██ ▄█▀▀▀█▄ ▄█▀▀▀█▄ ██   ██ ██ ██▄  ██ ▄█▀▀▀█▄",
    "██ █ ██ ██▄▄▄██ ██      ███████ ██ ██ █ ██ ██▄▄▄██",
    "██   ██ ██   ██ ▀█▄▄▄█▀ ██   ██ ██ ██  ▀██ ██   ██",
)

# SPORTS — 3 rows, 47 cols
SPORTS: tuple[str, ...] = (
    "▄█▀▀▀█▄ ██▀▀▀▄▄ ▄█▀▀▀█▄ ██▀▀▀▄▄ ▀▀▀██▀▀ ▄█▀▀▀█▄",
    " ▀▀█▄▄  ██▄▄▄▀▀ ██   ██ ██▄▄▄▀▀    ██    ▀▀█▄▄ ",
    "▀█▄▄▄█▀ ██      ▀█▄▄▄█▀ ██  ▀█▄    ██   ▀█▄▄▄█▀",
)

SPORTS_INDENT = 5
FULL_WIDTH = SPORTS_INDENT + len(SPORTS[0])  # 52
WORDMARK_WIDTH = len(MACHINA[0])  # 50


def full() -> Group:
    """MACHINA stacked over the star and SPORTS -- the primary lockup."""
    lines: list[Text] = [Text(row, style=WORDMARK_FG) for row in MACHINA]
    for i, row in enumerate(SPORTS):
        line = Text()
        if i == 1:
            line.append("   ", style=MUTED)
            line.append(BRAND_GLYPH, style=f"bold {ACCENT}")
            line.append(" ", style=MUTED)
        else:
            line.append(" " * SPORTS_INDENT)
        line.append(row, style=WORDMARK_FG)
        lines.append(line)
    return Group(*lines)


def wordmark() -> Group:
    """MACHINA alone, with the star and SPORTS set as a baseline rule."""
    lines: list[Text] = [Text(row, style=WORDMARK_FG) for row in MACHINA]
    tag = Text()
    tag.append(BRAND_GLYPH, style=f"bold {ACCENT}")
    tag.append("  S P O R T S", style=f"bold {MUTED}")
    lines.append(tag)
    return Group(*lines)


def compact(*, name: str = "MACHINA SPORTS") -> Text:
    """One-line mark, for narrow terminals and inline use."""
    return Text.assemble((f"{BRAND_GLYPH} ", f"bold {ACCENT}"), (name, "bold"))


def mark() -> Text:
    """The star on its own -- prompt, spinners, bullets."""
    return Text(BRAND_GLYPH, style=f"bold {ACCENT}")


def lockup(width: int) -> Group | Text:
    """Pick the largest lockup that fits ``width``."""
    if width >= FULL_WIDTH + 4:
        return full()
    if width >= WORDMARK_WIDTH + 4:
        return wordmark()
    return compact()
