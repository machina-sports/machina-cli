"""Phase A hardening (86ajj3jn6): agent visibility + evidence freshness."""

from datetime import datetime, timezone

from machina_cli.commands.context_graph import SELF_HEAL_AGENTS, _apply_staleness

NOW = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)


def test_all_context_verify_agents_are_recognized():
    for name in (
        "surface-watch-beat",
        "loop-beat",
        "loop-runner",
        "context-verify-beat",
        "context-verify-runner",
        "context-heal-runner",
    ):
        assert name in SELF_HEAL_AGENTS


def test_fresh_green_stays_green_with_age():
    badge, color, detail = _apply_staleness("ok", "green", "0%", "Thu, 16 Jul 2026 11:30:00 GMT", now=NOW)
    assert badge == "ok"
    assert color == "green"
    assert detail == "0% · 30m ago"


def test_stale_evidence_is_never_green():
    badge, color, detail = _apply_staleness("ok", "green", "0%", "Wed, 01 Jul 2026 21:39:40 GMT", now=NOW)
    assert badge == "ok (stale)"
    assert color == "yellow"
    assert "seen 14d ago" in detail


def test_stale_degraded_keeps_its_color():
    badge, color, _ = _apply_staleness("degraded", "red", "3%", "Wed, 01 Jul 2026 21:39:40 GMT", now=NOW)
    assert badge == "degraded (stale)"
    assert color == "red"


def test_missing_timestamp_is_left_untouched():
    assert _apply_staleness("ok", "green", "0%", "") == ("ok", "green", "0%")
