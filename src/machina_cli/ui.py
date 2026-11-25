"""Shared terminal rendering helpers.

Two jobs live here, and they are deliberately separate:

**Response shapes.** The CLI talks to a few API generations, so search endpoints
return collections and pagination either at the top level or nested below
``data``. The small compatibility layer below keeps every command from making
slightly different assumptions about the same response.

**Presentation.** Everything visual is :mod:`machina_cli.theme`. This module
re-exports the parts commands need, so a command has one import site and the
look of the CLI has one definition. New code can import either; prefer
``theme`` for anything that is purely about appearance.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any

import typer
from rich.text import Text

from machina_cli import theme
from machina_cli.theme import (
    ACCENT,
    DIM,
    INK,
    LINE,
    MUTED,
    console,
    err,
    fix,
    hint,
    info,
    kv,
    meter,
    ok,
    rule,
    sparkline,
    warn,
)

__all__ = [
    "ACCENT",
    "DIM",
    "INK",
    "LINE",
    "MUTED",
    "bool_cell",
    "cell",
    "console",
    "datetime_cell",
    "emit_json",
    "empty_state",
    "err",
    "extract_collection",
    "extract_pagination",
    "fix",
    "hint",
    "info",
    "kv",
    "make_table",
    "meter",
    "ok",
    "pagination_total",
    "render_pagination",
    "rule",
    "sparkline",
    "status_cell",
    "validate_pagination",
    "warn",
]


def emit_json(value: Any) -> None:
    """Write one machine-readable JSON document, with no Rich decoration."""
    typer.echo(json.dumps(value, ensure_ascii=False, default=str))


def extract_collection(payload: Any) -> list[dict[str, Any]]:
    """Return rows from both flat and nested Machina search responses.

    Supported examples include ``{"data": [...]}``,
    ``{"data": {"data": [...]}}`` and export-style ``documents``/``items``
    containers. Invalid response shapes safely become an empty collection.
    """
    current = payload
    for _ in range(3):
        if isinstance(current, list):
            return [item for item in current if isinstance(item, dict)]
        if not isinstance(current, Mapping):
            return []

        found = None
        for key in ("data", "documents", "items", "results", "rows"):
            candidate = current.get(key)
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, dict)]
            if found is None and isinstance(candidate, Mapping):
                found = candidate
        if found is None:
            return []
        current = found
    return []


def extract_pagination(payload: Any) -> Mapping[str, Any]:
    """Find pagination metadata in top-level or nested API envelopes."""
    current = payload
    for _ in range(3):
        if not isinstance(current, Mapping):
            break
        pagination = current.get("pagination")
        if isinstance(pagination, Mapping):
            return pagination
        meta = current.get("meta")
        if isinstance(meta, Mapping) and isinstance(meta.get("pagination"), Mapping):
            return meta["pagination"]
        current = current.get("data")
    return {}


def pagination_total(payload: Any) -> int | None:
    pagination = extract_pagination(payload)
    for key in ("total", "total_documents", "total_items", "count"):
        value = pagination.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def validate_pagination(page: int, page_size: int) -> None:
    """Fail before the HTTP call when paging values cannot be valid."""
    if page < 1:
        raise typer.BadParameter("must be at least 1", param_hint="--page")
    if not 1 <= page_size <= 500:
        raise typer.BadParameter("must be between 1 and 500", param_hint="--limit")


def make_table(title: str | None = None, *, expand: bool = False):
    """Create a consistent, compact table that degrades well on narrow TTYs."""
    return theme.table(title, expand=expand)


def cell(value: Any, *, style: str = "", empty: str = "—") -> Text:
    """Render API data literally so brackets cannot be interpreted as markup."""
    if value is None or value == "":
        value = empty
        style = style or MUTED
    return Text(str(value), style=style, overflow="ellipsis")


def status_cell(value: Any) -> Text:
    """A status word carrying its own glyph, so state survives a `--no-color` pipe."""
    return theme.state(value)


def bool_cell(value: Any, *, true_label: str = "yes", false_label: str = "no") -> Text:
    glyph = theme.glyph("ok") if value else theme.glyph("wait")
    label = true_label if bool(value) else false_label
    return Text.assemble(
        (f"{glyph} ", theme.OK if value else MUTED), (label, theme.OK if value else MUTED)
    )


def datetime_cell(value: Any) -> Text:
    if value in (None, ""):
        return cell(None)
    raw = str(value).strip()
    try:
        parsed = (
            parsedate_to_datetime(raw)
            if "," in raw
            else datetime.fromisoformat(raw.replace("Z", "+00:00"))
        )
        return cell(parsed.strftime("%Y-%m-%d %H:%M"), style=MUTED)
    except (TypeError, ValueError):
        normalized = raw.replace("T", " ").removesuffix("Z")
        return cell(normalized[:19], style=MUTED)


def empty_state(noun: str, *, positive: bool = False) -> None:
    """Nothing to show is information, not a failure -- say it quietly."""
    if positive:
        theme.ok(f"No {noun}.")
    else:
        console.print(theme.status("info", f"No {noun} found."))


def render_pagination(
    payload: Any,
    *,
    page: int,
    page_size: int,
    count: int,
    noun: str,
) -> None:
    """Render an accurate range/footer and a discoverable next-page hint."""
    total = pagination_total(payload)
    if total is None:
        if count == page_size:
            console.print(
                Text.assemble(
                    (f"  Page {page} · {count} {noun}", MUTED),
                    (f"   next: --page {page + 1}", DIM),
                )
            )
        return

    pages = max(1, math.ceil(total / page_size))
    start = (page - 1) * page_size + 1 if count else 0
    end = min(start + count - 1, total) if count else 0
    footer = Text(f"  Page {page}/{pages} · {start}–{end} of {total} {noun}", style=MUTED)
    if page < pages:
        footer.append(f"   next: --page {page + 1}", style=DIM)
    console.print(footer)
