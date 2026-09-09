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


# --- investigator (belief state) events -------------------------------------------------

def _belief(top, p, escalate=False, reason=None, evidence=("progress=stuck_2plus (13 -> 13)",)):
    return {
        "incident": True,
        "top": top,
        "top_p": p,
        "escalate": escalate,
        "escalate_reason": reason,
        "evidence": list(evidence),
        "hypotheses": [{"cause": top, "p": p}],
    }


def _health_doc_with_belief(created, broken, belief, healed=None):
    doc = _health_doc(created, "analysis<->fixture", broken, healed)
    doc["value"]["belief"] = belief
    return doc


def test_belief_adds_investigated_and_escalated_events():
    docs = [
        _health_doc("Wed, 01 Jul 2026 10:00:00 GMT", "analysis<->fixture", 0),
        _health_doc_with_belief("Wed, 01 Jul 2026 11:00:00 GMT", 13,
                                _belief("pipeline_batch_inheritance", 0.64, evidence=()),
                                {"heal_count": 5}),
        _health_doc_with_belief("Wed, 01 Jul 2026 12:00:00 GMT", 13,
                                _belief("pipeline_batch_inheritance", 0.58), {"heal_count": 5}),
        _health_doc_with_belief("Wed, 01 Jul 2026 13:00:00 GMT", 13,
                                _belief("pipeline_batch_inheritance", 0.72, True,
                                        "pipeline_batch_inheritance (72%): root cause needs a human"),
                                {"heal_count": 5}),
        _health_doc("Wed, 01 Jul 2026 14:00:00 GMT", "analysis<->fixture", 0),
    ]
    events = _events_from_history(docs, [])
    kinds = [(e["event"], e["ts"].hour) for e in events]
    assert kinds == [
        ("detected", 11), ("heal", 11), ("investigated", 11),
        ("heal", 12),                       # same top cause: no repeat "investigated"
        ("heal", 13), ("escalated", 13),
        ("recovered", 14),
    ]
    assert events[2]["detail"] == "most likely pipeline_batch_inheritance (64%) — on priors"
    assert "root cause needs a human" in events[5]["detail"]


def test_investigated_fires_again_when_the_leading_cause_changes():
    docs = [
        _health_doc_with_belief("Wed, 01 Jul 2026 11:00:00 GMT", 13,
                                _belief("pipeline_batch_inheritance", 0.4, evidence=())),
        _health_doc_with_belief("Wed, 01 Jul 2026 12:00:00 GMT", 10,
                                _belief("stale_backlog_draining", 0.79,
                                        evidence=("progress=improved (13 -> 10 after a heal round)",))),
    ]
    events = [e for e in _events_from_history(docs, []) if e["event"] == "investigated"]
    assert [e["detail"] for e in events] == [
        "most likely pipeline_batch_inheritance (40%) — on priors",
        "most likely stale_backlog_draining (79%) — progress=improved",
    ]


def test_escalation_state_resets_after_recovery():
    esc = _belief("pipeline_batch_inheritance", 0.72, True, "needs a human")
    docs = [
        _health_doc_with_belief("Wed, 01 Jul 2026 11:00:00 GMT", 13, esc),
        _health_doc("Wed, 01 Jul 2026 12:00:00 GMT", "analysis<->fixture", 0),
        _health_doc_with_belief("Wed, 01 Jul 2026 13:00:00 GMT", 2, esc),
    ]
    events = [e["event"] for e in _events_from_history(docs, [])]
    assert events.count("escalated") == 2 and events.count("investigated") == 2


def test_docs_without_belief_emit_no_investigator_events():
    docs = [
        _health_doc("Wed, 01 Jul 2026 10:00:00 GMT", "analysis<->fixture", 13, {"heal_count": 5}),
        _health_doc("Wed, 01 Jul 2026 11:00:00 GMT", "analysis<->fixture", 0),
    ]
    events = [e["event"] for e in _events_from_history(docs, [])]
    assert "investigated" not in events and "escalated" not in events
