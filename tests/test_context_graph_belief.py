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
        groups: dict = {}
        for h in hs:  # verdict edges carry one sub-catalog per verdict
            groups.setdefault(tuple(h.get("verdicts") or ()), []).append(h["prior"])
        for verdicts, priors in groups.items():
            assert math.isclose(sum(priors), 1.0, abs_tol=1e-9), (edge, verdicts)
    post = belief.update(EDGE, [("progress=stuck_2plus", ""), ("batch=signature", "")])
    assert math.isclose(sum(x["p"] for x in post), 1.0, abs_tol=2e-3)
    assert post == sorted(post, key=lambda x: -x["p"])


def test_every_likelihood_row_names_only_known_causes():
    causes = {h["cause"] for hs in belief.HYPOTHESES.values() for h in hs}
    assert len(causes) == sum(len(hs) for hs in belief.HYPOTHESES.values())  # unique across edges
    for label, row in belief.LIKELIHOOD.items():
        assert set(row) <= causes, label


def test_clean_edge_is_not_an_incident():
    b = belief.investigate(EDGE, {"edge": EDGE, "broken_edges": 0}, [], [])
    assert b["incident"] is False and b["action"] == "none" and b["escalate"] is False


def test_scan_error_and_unknown_edges_degrade_to_no_belief():
    assert belief.investigate(EDGE, {"edge": EDGE, "error": "boom"}, [], [])["scan_error"] is True
    b = belief.investigate("market->fixture(link)", {"edge": "market->fixture(link)"}, [], [])
    assert b["unsupported_edge"] is True and b["incident"] is False
    # the odds edge is detect-only: an incident with a catalog, no heal to run
    b = belief.investigate("odd<->market<->fixture", {"edge": "odd<->market<->fixture", "misattributed": 3}, [], [],
                           heal_configured=False)
    assert b["incident"] is True and len(b["hypotheses"]) == 4 and b["action"] == "none"
    assert b["top"] == "refresh_merge_collision"  # highest prior, first reading


def test_stuck_rounds_mirror_the_legacy_budget_semantics():
    draining = [_scan(7, 5, IDS[:7]), _scan(10, 5, IDS[:10]), _scan(13, 5, IDS)]  # newest first
    assert belief.stuck_rounds(EDGE, 4, draining) == 0  # 13 -> 10 -> 7 -> 4: every round helped
    stuck = [_scan(13, 5, IDS), _scan(13, 5, IDS), _scan(0)]
    assert belief.stuck_rounds(EDGE, 13, stuck) == 2  # 13 -> 13 -> 13: two rounds, no progress
    assert belief.stuck_rounds(EDGE, 13, [_scan(13, None, IDS)]) == 0  # no heal attempted = no round


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


def test_same_fixtures_without_a_heal_round_is_not_evidence():
    # detect-only pod (or heal not yet fired): the same flagged set is what EVERY hypothesis
    # predicts, so the belief must not drift toward "backlog" scan after scan
    live = {"live_groups": 46, "batch_groups": 46, "live_ids": 104, "unknown_status_ids": 0}
    trail = [_scan(0), _scan(58, None, IDS, live), _scan(58, None, IDS, live), _scan(58, None, IDS, live)]
    out = belief.replay(trail, EDGE, heal_configured=False)
    assert out[1]["top"] == "pipeline_batch_inheritance"
    assert out[3]["top"] == "pipeline_batch_inheritance" and out[3]["top_p"] == out[1]["top_p"]
    assert not any(e.startswith("new_groups=") for e in out[3]["evidence"])
    # ...but NEW collapsed groups appearing with nothing healed in between still count
    fresh = tuple(f"sr:sport_event:new{i}" for i in range(13))
    b = belief.replay([_scan(0), _scan(13, None, IDS), _scan(13, None, fresh)], EDGE, heal_configured=False)[2]
    assert any(e.startswith("new_groups=new_breakage") for e in b["evidence"])


def test_detect_only_pod_drops_heal_only_hypotheses_and_escalates():
    b = belief.investigate(EDGE, {"edge": EDGE, "broken_edges": 13, **KNOWN_BATCH}, [], [], heal_configured=False)
    assert {h["cause"] for h in b["hypotheses"]} == {
        "pipeline_batch_inheritance", "stale_backlog_draining", "not_live_false_positive"}
    assert b["action"] == "none" and b["escalate"] is True
    assert "no auto-heal is wired" in b["escalate_reason"]


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


# --- odd<->market<->fixture catalog (detect-only edge) -------------------------------------

ODDS = "odd<->market<->fixture"


def _odds(broken, id_only=0, outright=0, age=1.0, ids=()):
    h = {"edge": ODDS, "misattributed": broken, "flagged_total": broken, "flagged_id_only": id_only,
         "flagged_outright_like": outright, "hours_since_refresh": age}
    return {"health": h, "flagged": [{"fixture_ids": [i]} for i in ids]}


def test_odds_id_only_mismatch_points_at_a_bookmaker_remap():
    b = belief.investigate(ODDS, _odds(6, id_only=5, outright=0, age=2.0)["health"], [], [], heal_configured=False)
    assert b["top"] == "bookmaker_id_remap" and b["top_p"] >= 0.5
    labels = [e.split(" (")[0] for e in b["evidence"]]
    assert labels == ["mismatch=id_only", "market_types=match_like", "refresh_age=fresh"]
    assert b["action"] == "none" and b["escalate"] is True  # nothing automatable here: a human


def test_odds_mixed_content_points_at_the_refresh_merge():
    b = belief.investigate(ODDS, _odds(6, id_only=0, outright=0, age=2.0)["health"], [], [], heal_configured=False)
    assert b["top"] == "refresh_merge_collision" and b["top_p"] >= 0.5


def test_odds_outright_markets_are_not_a_defect():
    b = belief.investigate(ODDS, _odds(6, id_only=0, outright=6, age=2.0)["health"], [], [], heal_configured=False)
    assert b["top"] == "multi_fixture_market_expected" and b["top_p"] >= 0.5
    assert b["action"] == "none" and b["escalate"] is False  # expected, no page


def test_odds_stale_markets_rise_when_nothing_has_refreshed():
    fresh = belief.investigate(ODDS, _odds(6, age=1.0)["health"], [], [], heal_configured=False)
    stale = belief.investigate(ODDS, _odds(6, age=30.0)["health"], [], [], heal_configured=False)
    p = lambda b, c: next(h["p"] for h in b["hypotheses"] if h["cause"] == c)
    assert p(stale, "stale_unrefreshed_markets") > p(fresh, "stale_unrefreshed_markets") * 3
    assert stale["hypotheses"][1]["cause"] == "stale_unrefreshed_markets"


def test_odds_new_flagged_markets_between_scans_count_as_new_breakage():
    trail = [_odds(0), _odds(3, ids=("2:1", "2:2", "2:3")), _odds(3, ids=("2:7", "2:8", "2:9"))]
    b = belief.replay(trail, ODDS, heal_configured=False)[2]
    assert any(e.startswith("new_groups=new_breakage") for e in b["evidence"])


# --- surface<->users catalog (verdict edge) ----------------------------------------------

SURF = "surface<->users"


def _surf(verdict, sessions=500, exceptions=0, chat_err=0, age=None, heal=None, heal_items=None):
    h = {"edge": SURF, "verdict": verdict, "sessions": sessions, "exceptions": exceptions, "chat_err": chat_err}
    if age is not None:
        h["hours_since_refresh"] = age
    v = {"health": h, "verdict": verdict}
    if heal is not None:
        v["healed"] = {"heal_count": heal, "healed": heal_items or [{"season_id": "s1", "status": "executed"}]}
    return v


def test_surface_ok_is_not_an_incident_and_verdict_selects_the_catalog():
    assert belief.investigate(SURF, _surf("ok")["health"], [], [])["incident"] is False
    odds = belief.investigate(SURF, _surf("degraded:odds", age=30.0)["health"], [], [], heal_configured=True)
    errs = belief.investigate(SURF, _surf("degraded:errors", exceptions=40, chat_err=2)["health"], [], [],
                              heal_configured=False)
    assert {h["cause"] for h in odds["hypotheses"]} == {
        "markets_not_refreshed", "bookmaker_api_failure", "widget_regression", "traffic_mix_shift"}
    assert {h["cause"] for h in errs["hypotheses"]} == {
        "frontend_regression", "upstream_chat_failures", "abusive_traffic"}
    assert odds["verdict"] == "degraded:odds" and errs["verdict"] == "degraded:errors"


def test_surface_stale_markets_first_scan_heals():
    b = belief.investigate(SURF, _surf("degraded:odds", age=30.0)["health"], [], [], heal_configured=True)
    assert b["top"] == "markets_not_refreshed" and b["action"] == "heal" and b["escalate"] is False


def test_surface_fresh_markets_after_a_clean_heal_point_at_the_widget():
    trail = [_surf("ok"), _surf("degraded:odds", age=0.5, heal=1), _surf("degraded:odds", age=0.3, heal=1)]
    b = belief.replay(trail, SURF, heal_configured=True)[2]
    labels = [e.split(" (")[0] for e in b["evidence"]]
    assert "progress=stuck_1" in labels and "dispatch=clean" in labels and "refresh_age=fresh" in labels
    assert b["top"] == "widget_regression" and b["top_p"] >= 0.5
    assert b["action"] == "skip_heal" and b["escalate"] is True  # refreshing again will not help


def test_surface_heal_errors_with_stale_markets_point_at_the_bookmaker_api():
    err = [{"season_id": "s1", "error": "HTTP 502"}]
    trail = [_surf("ok"), _surf("degraded:odds", age=30.0, heal=1, heal_items=err),
             _surf("degraded:odds", age=30.5, heal=1, heal_items=err)]
    b = belief.replay(trail, SURF, heal_configured=True)[2]
    assert b["top"] == "bookmaker_api_failure" and b["top_p"] >= 0.7
    assert b["escalate"] is True and "no automatable remedy" in b["escalate_reason"]


def test_surface_session_spike_without_errors_reads_as_traffic_mix():
    trail = [_surf("ok", sessions=300), _surf("degraded:odds", sessions=900, age=0.5)]
    b = belief.replay(trail, SURF, heal_configured=True)[1]
    assert any(e.startswith("sessions=spike") for e in b["evidence"])
    assert b["top"] == "traffic_mix_shift"


def test_surface_error_mix_separates_frontend_from_upstream():
    fe = belief.investigate(SURF, _surf("degraded:errors", exceptions=40, chat_err=2)["health"], [],
                            [_surf("ok", sessions=480)], heal_configured=False)
    up = belief.investigate(SURF, _surf("degraded:errors", exceptions=2, chat_err=40)["health"], [],
                            [_surf("ok", sessions=480)], heal_configured=False)
    assert fe["top"] == "frontend_regression" and fe["top_p"] >= 0.7
    assert up["top"] == "upstream_chat_failures" and up["top_p"] >= 0.7
    assert fe["escalate"] is True and fe["action"] == "none"  # no heal exists for errors


def test_surface_stuck_rounds_count_degraded_scans_with_a_heal():
    hist = [_surf("degraded:odds", heal=1), _surf("degraded:odds", heal=1), _surf("ok")]  # newest first
    assert belief.stuck_rounds(SURF, 1, hist) == 2
