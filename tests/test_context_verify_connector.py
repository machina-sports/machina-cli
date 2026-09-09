"""The `context-verify-tools` connector source, exec'd the way the pod runs it.

`docs/harness-loop-kit/context-verify.py` ships the connector as a source string that the
pod exec's from the DB; until now nothing ran it locally. These tests exec the same string
(+ the embedded belief.py) against a fake `core.document.controller.document_search`, and
pin the edge scanner's classification: real misattributions are broken, finished-only and
placeholder-only groups are counted apart, and the heal is only handed team-determined
fixtures (learned live: undetermined bracket slots starved the heal of slots).
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path

import pytest

_KIT = Path(__file__).resolve().parents[1] / "docs" / "harness-loop-kit"


def _load_kit():
    os.environ.setdefault("CLIENT_API_URL", "https://example.test")
    os.environ.setdefault("API_TOKEN", "test-token")
    spec = importlib.util.spec_from_file_location("kit_context_verify", _KIT / "context-verify.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeStore:
    """Stand-in for core.document.controller.document_search (name filter + paging only)."""

    def __init__(self, docs):
        self.docs = docs

    def document_search(self, filters=None, page=1, page_size=50, sorters=None):
        name = (filters or {}).get("name")
        rows = [d for d in self.docs if d.get("name") == name]
        start = (page - 1) * page_size
        return {"data": {"data": rows[start : start + page_size]}}


@pytest.fixture
def connector():
    """exec the connector source with a fake `core` package installed for the test's duration."""
    kit = _load_kit()
    installed: dict = {}

    def build(docs):
        store = FakeStore(docs)
        core = types.ModuleType("core")
        document = types.ModuleType("core.document")
        controller = types.ModuleType("core.document.controller")
        controller.document_search = store.document_search
        document.controller = controller
        core.document = document
        for name, mod in (("core", core), ("core.document", document), ("core.document.controller", controller)):
            installed.setdefault(name, sys.modules.get(name))
            sys.modules[name] = mod
        namespace: dict = {}
        # the pod exec's this source from the DB; running it the same way IS the test
        exec(kit._scan_src_for_tenant() + "\n" + kit._belief_src(), namespace)  # noqa: S102
        return namespace

    yield build
    for name, previous in installed.items():
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous


def fixture(sid, home, away, analysis, status="not_started", research_at="2026-06-28T12:00:00"):
    return {
        "name": "sportradar-fixture",
        "created": "Sun, 28 Jun 2026 12:00:00 GMT",
        "updated": "Sun, 28 Jun 2026 12:00:00 GMT",
        "metadata": {"sport_event_id": sid},
        "value": {
            "sport_event_id": sid,
            "title": f"{home} vs {away} ({sid[-3:]})",
            "home_competitor_name": home,
            "away_competitor_name": away,
            "status": status,
            "has_pre_match_research": True,
            "pre_match_research_at": research_at,
            "pre_match_research": {"team_form": {"home": {"analysis": analysis}}},
        },
    }


SPAIN = "A Espanha demonstra solidez defensiva e controle de jogo."
SLOT = "Ainda não definido. O mandante será o vencedor do jogo 97."
MIXED = "A identidade do mandante (W79) será definida após as quartas."
PLAYED = "O Fluminense busca reabilitação após a eliminação."

DOCS = [
    # real misattribution, written in one batch -> broken, batch signature
    fixture("sr:sport_event:1", "Spain", "Austria", SPAIN),
    fixture("sr:sport_event:2", "USA", "Bosnia and Herzegovina", SPAIN),
    # placeholder-only group: bracket slots sharing the 'not yet known' text -> counted apart
    fixture("sr:sport_event:3", "W95", "W96", SLOT),
    fixture("sr:sport_event:4", "W91", "W92", SLOT),
    # mixed group: a REAL fixture carries a placeholder's text -> broken, heal only the real one
    fixture("sr:sport_event:5", "Brazil", "W78", MIXED),
    fixture("sr:sport_event:6", "W79", "W80", MIXED),
    fixture("sr:sport_event:7", "Colombia", "Ghana", MIXED, research_at="2026-06-29T18:00:00"),
    # finished-only group -> archival debt
    fixture("sr:sport_event:8", "Fluminense", "Vasco", PLAYED, status="closed"),
    fixture("sr:sport_event:9", "Grêmio", "Mirassol", PLAYED, status="closed"),
    # unique analysis -> nothing
    fixture("sr:sport_event:10", "Internacional", "Corinthians", "O Inter oscila na temporada."),
]


def test_scan_edges_classifies_real_placeholder_and_played_groups(connector):
    ns = connector(DOCS)
    out = ns["scan_edges"]({"params": {"limit": 200}})
    h = out["data"]["health"]
    assert h["edge"] == "analysis<->fixture"
    assert h["sampled"] == 10 and h["collapsed_groups"] == 4
    assert h["broken_edges"] == 3  # Spain/USA (1) + the mixed group of 3 titles (2)
    assert h["broken_placeholder_edges"] == 1 and h["placeholder_groups"] == 1
    assert h["broken_played_edges"] == 1
    assert h["live_groups"] == 2
    assert h["live_ids"] == 5 and h["placeholder_ids"] == 2 and h["unknown_status_ids"] == 0
    # Spain/USA share a research stamp (one batch); the mixed group spans a day
    assert h["batch_groups"] == 1
    assert out["data"]["heal_needed"] is True


def test_heal_is_only_handed_team_determined_fixtures(connector):
    ns = connector(DOCS)
    flagged = ns["scan_edges"]({"params": {"limit": 200}})["data"]["flagged"]
    by_analysis = {f["analysis"][:20]: f for f in flagged}
    mixed = by_analysis[MIXED.lower()[:20]]
    assert mixed["fixture_ids"] == ["sr:sport_event:7"]  # Colombia vs Ghana only
    assert mixed["undetermined_ids"] == ["sr:sport_event:5", "sr:sport_event:6"]
    assert all(SLOT.lower()[:20] != f["analysis"][:20] for f in flagged)  # slot-only group never flagged


def test_placeholder_rule_mirrors_the_coverage_controller(connector):
    ns = connector([])
    is_ph = ns["_is_placeholder_name"]
    for name in ("W95", "L96", "1A", "95", "", None):
        assert is_ph(name), name
    for name in ("Portugal", "Real Madrid", "Schalke 04", "Brazil", "USA"):
        assert not is_ph(name), name


def test_status_less_fixtures_are_live_and_counted_as_unknown(connector):
    docs = [fixture("sr:sport_event:1", "Spain", "Austria", SPAIN, status=""),
            fixture("sr:sport_event:2", "USA", "Bosnia and Herzegovina", SPAIN, status="")]
    h = connector(docs)["scan_edges"]({"params": {"limit": 200}})["data"]["health"]
    assert h["broken_edges"] == 1 and h["live_ids"] == 2 and h["unknown_status_ids"] == 2


def test_investigate_edge_runs_the_embedded_investigator(connector):
    ns = connector([])  # no health history -> priors only
    health = {"edge": "analysis<->fixture", "broken_edges": 3, "live_groups": 2, "batch_groups": 2,
              "live_ids": 5, "unknown_status_ids": 0}
    out = ns["investigate_edge"]({"params": {"health": health, "flagged": [], "heal_agent": "context-heal-runner",
                                             "max_heal_attempts": 3}})
    b = out["data"]["belief"]
    assert b["incident"] is True and b["heal_configured"] is True
    assert b["top"] == "pipeline_batch_inheritance"
    assert [e.split(" (")[0] for e in b["evidence"]] == ["status=known_live", "batch=signature"]
    assert b["action"] == "heal" and b["escalate"] is False
    # detect-only pod: heal_agent is the empty DSL literal
    out = ns["investigate_edge"]({"params": {"health": health, "flagged": [], "heal_agent": "", "max_heal_attempts": 3}})
    assert out["data"]["belief"]["heal_configured"] is False and out["data"]["belief"]["escalate"] is True


def test_investigate_edge_reads_only_this_edges_history(connector):
    def health_doc(edge, broken, heal=0):
        return {"name": "context_graph_health", "created": "Sun, 28 Jun 2026 12:00:00 GMT",
                "value": {"health": {"edge": edge, "broken_edges": broken}, "healed": {"heal_count": heal},
                          "flagged": [{"fixture_ids": ["sr:sport_event:1"]}]}}
    ns = connector([health_doc("analysis<->fixture", 3, heal=5), health_doc("odd<->market<->fixture", 9)])
    health = {"edge": "analysis<->fixture", "broken_edges": 3}
    b = ns["investigate_edge"]({"params": {"health": health, "flagged": [{"fixture_ids": ["sr:sport_event:1"]}],
                                          "heal_agent": "context-heal-runner"}})["data"]["belief"]
    assert b["stuck_rounds"] == 1
    labels = [e.split(" (")[0] for e in b["evidence"]]
    assert "progress=stuck_1" in labels and "new_groups=same_set" in labels


def test_trigger_analysis_heal_honours_the_investigator_and_the_config(connector):
    ns = connector([])
    heal = ns["trigger_analysis_heal"]
    base = {"heal_needed": True, "health": {"edge": "analysis<->fixture", "broken_edges": 3},
            "flagged": [{"fixture_ids": ["sr:sport_event:7"]}]}
    # not configured (empty DSL literal) -> nothing dispatched
    assert heal({"params": {**base, "heal_agent": ""}})["data"]["skipped"] == "heal not configured"
    # the investigator said skip -> nothing dispatched, and the reason is carried
    out = heal({"params": {**base, "heal_agent": "context-heal-runner",
                           "belief": {"action": "skip_heal", "explain": "likely not a live defect"}}})
    assert out["data"]["heal_count"] == 0 and out["data"]["belief_action"] == "skip_heal"
    assert "likely not a live defect" in out["data"]["skipped"]
    # clean edge -> nothing to do
    assert heal({"params": {**base, "heal_needed": False, "heal_agent": "x"}})["data"]["skipped"] == "edge is clean"


def test_stuck_heal_attempts_walks_the_trail(connector):
    def health_doc(broken, heal):
        return {"name": "context_graph_health", "created": "x",
                "value": {"health": {"edge": "analysis<->fixture", "broken_edges": broken}, "healed": {"heal_count": heal}}}
    ns = connector([health_doc(13, 5), health_doc(13, 5), health_doc(0, 0)])  # newest first
    assert ns["_stuck_heal_attempts"](13) == 2
    ns = connector([health_doc(7, 5), health_doc(10, 5), health_doc(13, 5)])
    assert ns["_stuck_heal_attempts"](4) == 0
