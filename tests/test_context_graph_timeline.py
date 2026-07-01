"""Tests for the self-healing timeline reconstruction (`context-graph timeline`).

`_events_from_history` is a pure function over the persisted graph-health doc
trail — these pin the event semantics: 0->N broken is a detection, heal_count>0
is a heal round, budget_exceeded is auto-heal pausing, N->0 is a recovery, and
surface verdict transitions map the same way. The trail is append-only history,
so ordering must come from parsing `created`, not list position.
"""

from __future__ import annotations

from machina_cli.commands.context_graph import _events_from_history


def _health_doc(created, edge, broken, healed=None, count_field="broken_edges"):
    return {
        "created": created,
        "value": {"health": {"edge": edge, count_field: broken}, "healed": healed or {}},
    }


def _surface_doc(created, verdict, healed=None):
    return {"created": created, "value": {"verdict": verdict, "healed": healed or {}}}


def test_detect_heal_recover_arc():
    docs = [
        _health_doc("Wed, 01 Jul 2026 10:00:00 GMT", "analysis<->fixture", 0),
        _health_doc("Wed, 01 Jul 2026 11:00:00 GMT", "analysis<->fixture", 13,
                    {"heal_count": 5, "backlog": 1}),
        _health_doc("Wed, 01 Jul 2026 12:00:00 GMT", "analysis<->fixture", 7,
                    {"heal_count": 5}),
        _health_doc("Wed, 01 Jul 2026 13:00:00 GMT", "analysis<->fixture", 0),
    ]
    events = _events_from_history(docs, [])
    kinds = [(e["event"], e["ts"].hour) for e in events]
    assert kinds == [("detected", 11), ("heal", 11), ("heal", 12), ("recovered", 13)]
    # recovery reports the incident PEAK (13), not the immediately-prior drained
    # reading (7) — "was 1" after a 13->...->1 drain hides the story from the reader
    assert "peaked at 13" in events[-1]["detail"]
    assert "+1 queued" in events[1]["detail"]


def test_ordering_comes_from_created_not_list_position():
    # newest-first input (how the API returns it) must still yield a chronological story
    docs = [
        _health_doc("Wed, 01 Jul 2026 13:00:00 GMT", "analysis<->fixture", 0),
        _health_doc("Wed, 01 Jul 2026 11:00:00 GMT", "analysis<->fixture", 13),
        _health_doc("Wed, 01 Jul 2026 10:00:00 GMT", "analysis<->fixture", 0),
    ]
    events = _events_from_history(docs, [])
    assert [e["event"] for e in events] == ["detected", "recovered"]
    assert events[0]["ts"] < events[1]["ts"]


def test_still_broken_scans_emit_no_repeat_detection():
    docs = [
        _health_doc("Wed, 01 Jul 2026 10:00:00 GMT", "analysis<->fixture", 13),
        _health_doc("Wed, 01 Jul 2026 11:00:00 GMT", "analysis<->fixture", 13),
        _health_doc("Wed, 01 Jul 2026 12:00:00 GMT", "analysis<->fixture", 13),
    ]
    events = _events_from_history(docs, [])
    assert [e["event"] for e in events] == ["detected"]


def test_budget_exceeded_becomes_heal_paused():
    docs = [
        _health_doc("Wed, 01 Jul 2026 10:00:00 GMT", "analysis<->fixture", 13,
                    {"budget_exceeded": True, "prior_attempts": 3}),
    ]
    events = _events_from_history(docs, [])
    assert [e["event"] for e in events] == ["detected", "heal-paused"]
    assert "needs a human" in events[1]["detail"]


def test_edges_are_isolated():
    # one edge broken must not leak a detection onto the other edge
    docs = [
        _health_doc("Wed, 01 Jul 2026 10:00:00 GMT", "analysis<->fixture", 13),
        _health_doc("Wed, 01 Jul 2026 10:00:01 GMT", "odd<->market<->fixture", 0,
                    count_field="misattributed"),
    ]
    events = _events_from_history(docs, [])
    assert len(events) == 1 and events[0]["edge"] == "analysis<->fixture"


def test_second_incident_peak_does_not_inherit_the_first():
    docs = [
        _health_doc("Wed, 01 Jul 2026 10:00:00 GMT", "analysis<->fixture", 13),
        _health_doc("Wed, 01 Jul 2026 11:00:00 GMT", "analysis<->fixture", 0),
        _health_doc("Wed, 01 Jul 2026 12:00:00 GMT", "analysis<->fixture", 2),
        _health_doc("Wed, 01 Jul 2026 13:00:00 GMT", "analysis<->fixture", 0),
    ]
    events = _events_from_history(docs, [])
    recoveries = [e for e in events if e["event"] == "recovered"]
    assert "peaked at 13" in recoveries[0]["detail"]
    assert "peaked at 2" in recoveries[1]["detail"]


def test_surface_transitions_and_heal():
    docs = [
        _surface_doc("Wed, 01 Jul 2026 10:00:00 GMT", "ok"),
        _surface_doc("Wed, 01 Jul 2026 11:00:00 GMT", "degraded:odds",
                     {"healed": [{"season_id": "s1", "status": "executed"}], "heal_count": 1}),
        _surface_doc("Wed, 01 Jul 2026 12:00:00 GMT", "degraded:odds"),  # unchanged: silent
        _surface_doc("Wed, 01 Jul 2026 13:00:00 GMT", "ok"),
    ]
    events = _events_from_history([], docs)
    assert [e["event"] for e in events] == ["detected", "heal", "recovered"]
    assert all(e["edge"] == "surface<->users" for e in events)


def test_surface_cross_degraded_transition_is_a_new_detection():
    docs = [
        _surface_doc("Wed, 01 Jul 2026 10:00:00 GMT", "degraded:odds"),
        _surface_doc("Wed, 01 Jul 2026 11:00:00 GMT", "degraded:errors"),
    ]
    events = _events_from_history([], docs)
    assert [e["event"] for e in events] == ["detected", "detected"]
    assert events[1]["detail"] == "degraded:errors"


def test_unknown_edges_and_bad_dates_are_skipped():
    docs = [
        {"created": "not a date", "value": {"health": {"edge": "analysis<->fixture", "broken_edges": 9}}},
        _health_doc("Wed, 01 Jul 2026 10:00:00 GMT", "market->fixture(link)", 5),
    ]
    assert _events_from_history(docs, []) == []
