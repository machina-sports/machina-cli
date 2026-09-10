"""The `surface-verify-tools` connector source, exec'd the way the pod runs it.

Same approach as test_context_verify_connector: exec the surface kit's connector string
(+ the embedded belief.py) against a fake `core.document.controller.document_search`, and
pin the investigator glue for the verdict edge -- the refresh-age evidence, the verdict
selecting the catalog, and the heal gate.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

import pytest

from tests.test_context_verify_connector import FakeStore

_KIT = Path(__file__).resolve().parents[1] / "docs" / "harness-loop-kit"


def _load_surface_kit():
    os.environ.setdefault("CLIENT_API_URL", "https://example.test")
    os.environ.setdefault("API_TOKEN", "test-token")
    spec = importlib.util.spec_from_file_location("kit_surface_verify", _KIT / "surface-verify.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def surface(monkeypatch):
    kit = _load_surface_kit()

    def build(docs):
        store = FakeStore(docs)
        core = types.ModuleType("core")
        document = types.ModuleType("core.document")
        controller = types.ModuleType("core.document.controller")
        controller.document_search = store.document_search
        document.controller = controller
        core.document = document
        for name, mod in (("core", core), ("core.document", document), ("core.document.controller", controller)):
            monkeypatch.setitem(sys.modules, name, mod)
        namespace: dict = {}
        # the pod exec's this source from the DB; running it the same way IS the test
        exec(kit._scan_src_for_tenant() + "\n" + kit._belief_src(), namespace)  # noqa: S102
        return namespace

    return build


def _hours_ago(h):
    return format_datetime(datetime.now(timezone.utc) - timedelta(hours=h))


def market_doc(hours_old):
    return {"name": "entain-markets-tier3", "updated": _hours_ago(hours_old), "created": _hours_ago(hours_old),
            "value": {"bwin_fixture_id": "2:1", "markets_tier3": {}}}


def surface_doc(verdict, heal=None, sessions=500):
    v = {"health": {"edge": "surface<->users", "verdict": verdict, "sessions": sessions, "exceptions": 0, "chat_err": 0},
         "verdict": verdict}
    if heal is not None:
        v["healed"] = {"heal_count": heal, "healed": [{"season_id": "s1", "status": "executed"}]}
    return {"name": "context_graph_surface_health", "created": _hours_ago(1), "value": v}


DEGRADED_ODDS = {"edge": "surface<->users", "verdict": "degraded:odds", "sessions": 500, "odds_per_session": 0.01,
                 "exceptions": 3, "chat_err": 2}


def test_stale_markets_on_a_degraded_odds_surface_point_at_the_refresh(surface):
    ns = surface([market_doc(30)])
    out = ns["investigate_surface"]({"params": {"health": DEGRADED_ODDS, "verdict": "degraded:odds"}})
    assert out["data"]["hours_since_refresh"] >= 29
    b = out["data"]["belief"]
    assert b["incident"] is True and b["verdict"] == "degraded:odds" and b["heal_configured"] is True
    assert b["top"] == "markets_not_refreshed" and b["action"] == "heal"
    assert any(e.startswith("refresh_age=stale") for e in b["evidence"])


def test_fresh_markets_after_a_clean_heal_skip_the_next_heal(surface):
    ns = surface([market_doc(0.2), surface_doc("degraded:odds", heal=1), surface_doc("ok")])
    b = ns["investigate_surface"]({"params": {"health": DEGRADED_ODDS, "verdict": "degraded:odds"}})["data"]["belief"]
    labels = [e.split(" (")[0] for e in b["evidence"]]
    assert "progress=stuck_1" in labels and "dispatch=clean" in labels and "refresh_age=fresh" in labels
    assert b["top"] == "widget_regression" and b["action"] == "skip_heal" and b["escalate"] is True


def test_degraded_errors_uses_the_errors_catalog_without_a_heal(surface):
    ns = surface([])
    health = {"edge": "surface<->users", "verdict": "degraded:errors", "sessions": 500, "exceptions": 40, "chat_err": 3}
    b = ns["investigate_surface"]({"params": {"health": health, "verdict": "degraded:errors"}})["data"]["belief"]
    assert b["heal_configured"] is False
    assert {h["cause"] for h in b["hypotheses"]} == {"frontend_regression", "upstream_chat_failures", "abusive_traffic"}
    assert b["top"] == "frontend_regression" and b["escalate"] is True


def test_ok_surface_is_not_an_incident(surface):
    ns = surface([])
    b = ns["investigate_surface"]({"params": {"health": {"edge": "surface<->users", "verdict": "ok"}, "verdict": "ok"}})["data"]["belief"]
    assert b["incident"] is False and b["action"] == "none"


def test_odds_heal_honours_the_investigator(surface):
    ns = surface([])
    heal = ns["trigger_odds_heal"]
    assert heal({"params": {"heal_needed": False}})["data"]["skipped"] == "verdict not degraded:odds"
    out = heal({"params": {"heal_needed": True, "belief": {"action": "skip_heal", "explain": "widget, not the odds"}}})
    assert out["data"]["heal_count"] == 0 and out["data"]["belief_action"] == "skip_heal"
    assert "widget, not the odds" in out["data"]["skipped"]


def test_markets_refresh_age_is_none_without_markets(surface):
    ns = surface([])
    assert ns["_markets_refresh_age_hours"]() is None
