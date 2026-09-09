"""Tests for the Context Graph investigator (belief state v0, docs/harness-loop-kit/belief.py).

belief.py is embedded verbatim into the `context-verify-tools` connector and imported here
from the kit, so these pin the SAME code the pod runs: a deterministic posterior over the
competing causes of a broken edge, the evidence extracted from the health-doc trail, and
the decision rules -- the belief may only make healing more conservative, escalation must
come with a reason, and the legacy no-progress semantics are preserved.
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

_KIT = Path(__file__).resolve().parents[1] / "docs" / "harness-loop-kit" / "belief.py"
_spec = importlib.util.spec_from_file_location("kit_belief", _KIT)
belief = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(belief)

EDGE = "analysis<->fixture"
IDS = tuple(f"sr:sport_event:{i}" for i in range(13))


def _scan(broken, heal=None, ids=(), extra=None, healed_items=None):
    """One persisted context_graph_health value, as HVAL writes it."""
    h = {"edge": EDGE, "broken_edges": broken}
    if extra:
        h.update(extra)
    v = {"health": h, "flagged": [{"fixture_ids": list(ids)}] if ids else []}
    if heal is not None:
        items = healed_items
        if items is None:
            items = [{"fixture_id": f, "status": "dispatched"} for f in list(ids)[:heal]]
        v["healed"] = {"heal_count": heal, "healed": items}
    return v


KNOWN_BATCH = {"live_groups": 4, "batch_groups": 4, "live_ids": 13, "unknown_status_ids": 1}


def test_priors_sum_to_one_and_posterior_is_normalized():
    for edge, hs in belief.HYPOTHESES.items():
        assert math.isclose(sum(h["prior"] for h in hs), 1.0, abs_tol=1e-9), edge
    post = belief.update(EDGE, [("progress=stuck_2plus", ""), ("batch=signature", "")])
    assert math.isclose(sum(x["p"] for x in post), 1.0, abs_tol=2e-3)
    assert post == sorted(post, key=lambda x: -x["p"])


def test_every_likelihood_row_names_only_known_causes():
    causes = {h["cause"] for h in belief.HYPOTHESES[EDGE]}
    for label, row in belief.LIKELIHOOD.items():
        assert set(row) <= causes, label


def test_clean_edge_is_not_an_incident():
    b = belief.investigate(EDGE, {"edge": EDGE, "broken_edges": 0}, [], [])
    assert b["incident"] is False and b["action"] == "none" and b["escalate"] is False


def test_scan_error_and_unknown_edges_degrade_to_no_belief():
    assert belief.investigate(EDGE, {"edge": EDGE, "error": "boom"}, [], [])["scan_error"] is True
    b = belief.investigate("market->fixture(link)", {"edge": "market->fixture(link)"}, [], [])
    assert b["unsupported_edge"] is True and b["incident"] is False
    # the odds edge has a count but no hypothesis catalog yet: an incident without a belief
    b = belief.investigate("odd<->market<->fixture", {"edge": "odd<->market<->fixture", "misattributed": 3}, [], [])
    assert b["incident"] is True and b["hypotheses"] == [] and b["action"] == "none"


def test_stuck_rounds_mirror_the_legacy_budget_semantics():
    draining = [_scan(7, 5, IDS[:7]), _scan(10, 5, IDS[:10]), _scan(13, 5, IDS)]  # newest first
    assert belief.stuck_rounds(4, draining) == 0  # 13 -> 10 -> 7 -> 4: every round helped
    stuck = [_scan(13, 5, IDS), _scan(13, 5, IDS), _scan(0)]
    assert belief.stuck_rounds(13, stuck) == 2  # 13 -> 13 -> 13: two rounds, no progress
    assert belief.stuck_rounds(13, [_scan(13, None, IDS)]) == 0  # no heal attempted = no round


def test_stuck_incident_escalates_with_a_reason_and_keeps_healing():
    trail = [_scan(0)] + [_scan(13, 5, IDS, KNOWN_BATCH) for _ in range(4)]
    out = belief.replay(trail, EDGE, heal_configured=True, max_attempts=3)
    assert out[0]["incident"] is False
    first = out[1]
    assert first["top"] == "pipeline_batch_inheritance" and first["escalate"] is False
    assert first["action"] == "heal"
    # the LEGACY budget would page only after 3 no-progress rounds; the investigator
    # explains itself at 2 -- and names the cause instead of "could NOT self-heal"
    assert out[2]["escalate"] is False and out[2]["stuck_rounds"] == 1
    third = out[3]
    assert third["stuck_rounds"] == 2 and third["escalate"] is True
    assert "pipeline_batch_inheritance" in third["escalate_reason"]
    assert "root cause needs a human" in third["escalate_reason"]
    assert third["action"] == "heal"  # symptom relief continues while a human looks
    assert third["confidence"] == "high" and third["top_p"] >= 0.7
    assert any(e.startswith("progress=stuck_2plus") for e in third["evidence"])


def test_draining_backlog_is_recognized_and_never_escalates():
    trail = [_scan(0), _scan(13, 5, IDS), _scan(10, 5, IDS[:10]), _scan(7, 5, IDS[:7]), _scan(4, 4, IDS[:4]), _scan(0)]
    out = belief.replay(trail, EDGE)
    for b in out[2:5]:
        assert b["top"] == "stale_backlog_draining"
        assert b["escalate"] is False and b["action"] == "heal"
        assert any(e.startswith("progress=improved") for e in b["evidence"])
    assert out[-1]["incident"] is False


def test_status_less_fixtures_make_the_investigator_skip_the_heal():
    unknown = {"live_groups": 3, "batch_groups": 0, "live_ids": 6, "unknown_status_ids": 6}
    trail = [_scan(0), _scan(6, 3, IDS[:6], unknown), _scan(6, 3, IDS[:6], unknown)]
    out = belief.replay(trail, EDGE)
    assert out[1]["top"] == "not_live_false_positive"
    b = out[2]
    assert b["top"] == "not_live_false_positive" and b["top_p"] >= 0.5
    assert b["action"] == "skip_heal" and b["escalate"] is False  # not a defect: no heal, no page


def test_dispatch_errors_point_at_the_heal_mechanism():
    errs = [{"fixture_id": f, "error": "HTTP 500"} for f in IDS[:5]]
    trail = [_scan(0), _scan(13, 5, IDS, healed_items=errs), _scan(13, 5, IDS, healed_items=errs)]
    b = belief.replay(trail, EDGE)[2]
    assert b["top"] == "heal_mechanism_failing"
    assert b["action"] == "skip_heal" and b["escalate"] is True
    assert "no automatable remedy" in b["escalate_reason"]
    assert any(e.startswith("dispatch=errors") for e in b["evidence"])


def test_new_breakage_after_a_heal_round_points_at_the_pipeline():
    fresh = tuple(f"sr:sport_event:new{i}" for i in range(13))
    trail = [_scan(0), _scan(13, 5, IDS), _scan(13, 5, fresh)]
    b = belief.replay(trail, EDGE)[2]
    assert b["top"] == "pipeline_batch_inheritance"
    assert any(e.startswith("new_groups=new_breakage") for e in b["evidence"])


def test_detect_only_pod_drops_heal_only_hypotheses_and_escalates():
    b = belief.investigate(EDGE, {"edge": EDGE, "broken_edges": 13, **KNOWN_BATCH}, [], [], heal_configured=False)
    assert {h["cause"] for h in b["hypotheses"]} == {
        "pipeline_batch_inheritance", "stale_backlog_draining", "not_live_false_positive"}
    assert b["action"] == "none" and b["escalate"] is True
    assert "not configured" in b["escalate_reason"]


def test_belief_never_dispatches_more_than_the_budget():
    # after max_attempts no-progress rounds the investigator escalates too (the cap stays)
    trail = [_scan(0)] + [_scan(13, 5, IDS) for _ in range(5)]
    out = belief.replay(trail, EDGE, heal_configured=True, max_attempts=3)
    assert out[4]["stuck_rounds"] == 3 and out[4]["escalate"] is True
    assert all(b["action"] in ("heal", "skip_heal", "none") for b in out)


def test_first_reading_uses_priors_and_says_so():
    b = belief.investigate(EDGE, {"edge": EDGE, "broken_edges": 3}, [], [])
    assert b["evidence"] == [] and b["top"] == "pipeline_batch_inheritance"
    assert "priors alone" in b["explain"] and "40%" in b["explain"]
    assert b["confidence"] == "low"  # 0.40 < UNDECIDED_BELOW: keep running the cheap experiment
    assert b["action"] == "heal"


def test_mixed_trail_only_uses_this_edges_history():
    other = {"health": {"edge": "odd<->market<->fixture", "misattributed": 9}, "healed": {"heal_count": 9}}
    b = belief.investigate(EDGE, {"edge": EDGE, "broken_edges": 3}, [], [other, other])
    assert b["evidence"] == [] and b["stuck_rounds"] == 0


def test_explain_line_names_top_evidence_and_runner_up():
    trail = [_scan(0)] + [_scan(13, 5, IDS, KNOWN_BATCH) for _ in range(3)]
    line = belief.replay(trail, EDGE)[3]["explain"]
    assert line.startswith("Most likely pipeline_batch_inheritance (")
    assert "because progress=stuck_2plus" in line and "Runner-up:" in line


@pytest.mark.parametrize("bad", [None, {}, {"health": None}])
def test_investigate_tolerates_garbage_history(bad):
    b = belief.investigate(EDGE, {"edge": EDGE, "broken_edges": 2}, [], [bad])
    assert b["incident"] is True
