"""Shared terminal rendering helpers.

The CLI talks to a few API generations.  Search endpoints therefore return
collections and pagination either at the top level or nested below ``data``.
Keeping the small compatibility layer here prevents every command from making
slightly different assumptions about the same response.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any

import typer
from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

ACCENT = "#FF5C1F"
MUTED = "grey62"

console = Console(highlight=False)


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


def make_table(title: str, *, expand: bool = False) -> Table:
    """Create a consistent, compact table that degrades well on narrow TTYs."""
    return Table(
        title=Text(title, style="bold"),
        title_justify="left",
        header_style=f"bold {ACCENT}",
        border_style="grey35",
        box=box.SIMPLE_HEAD,
        collapse_padding=True,
        pad_edge=False,
        expand=expand,
    )


def cell(value: Any, *, style: str = "", empty: str = "—") -> Text:
    """Render API data literally so brackets cannot be interpreted as markup."""
    if value is None or value == "":
        value = empty
        style = style or MUTED
    return Text(str(value), style=style, overflow="ellipsis")


def status_cell(value: Any) -> Text:
    raw = str(value if value not in (None, "") else "unknown")
    normalized = raw.lower().replace("_", "-")
    if normalized in {
        "true",
        "active",
        "online",
        "success",
        "completed",
        "approved",
        "executed",
        "agent-executed",
    }:
        style = "green"
    elif (
        normalized
        in {"false", "failed", "failure", "error", "offline", "rejected", "cancelled", "canceled"}
        or "fail" in normalized
    ):
        style = "red"
    elif normalized in {
        "pending",
        "running",
        "processing",
        "scheduled",
        "draft",
        "inactive",
        "queued",
        "unknown",
    }:
        style = "yellow"
    else:
        style = MUTED
    return Text(raw, style=style)


def bool_cell(value: Any, *, true_label: str = "yes", false_label: str = "no") -> Text:
    return Text(true_label if bool(value) else false_label, style="green" if value else MUTED)


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
    style = "green" if positive else "yellow"
    console.print(Text(f"No {noun} found.", style=style))


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
                    (f"Page {page} · {count} {noun}", MUTED),
                    (f"   next: --page {page + 1}", "dim"),
                )
            )
        return

    pages = max(1, math.ceil(total / page_size))
    start = (page - 1) * page_size + 1 if count else 0
    end = min(start + count - 1, total) if count else 0
    footer = Text(f"Page {page}/{pages} · {start}–{end} of {total} {noun}", style=MUTED)
    if page < pages:
        footer.append(f"   next: --page {page + 1}", style="dim")
    console.print(footer)
