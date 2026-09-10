"""Re-provisioning must not switch a live beat off.

`_create` recreates every resource by name from the kit's INACTIVE defaults. On a pod
where a beat was promoted to active, that used to silently disable the loop. Both kits
now remember an agent's live activation before deleting it and restore it afterwards.
The REST layer is faked here; the sequence of calls is what these tests pin.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

_KIT = Path(__file__).resolve().parents[1] / "docs" / "harness-loop-kit"


def _load(name):
    os.environ.setdefault("CLIENT_API_URL", "https://example.test")
    os.environ.setdefault("API_TOKEN", "test-token")
    spec = importlib.util.spec_from_file_location("kit_" + name.replace("-", "_").replace(".py", ""), _KIT / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeApi:
    """Records every call; serves an existing agent with the activation you give it."""

    def __init__(self, existing=None):
        self.existing = existing  # dict of the pre-existing agent, or None
        self.calls = []
        self.recreated = False

    def req(self, method, path, body=None):
        self.calls.append((method, path, body))
        if method == "GET" and path.startswith("agent/"):
            if self.existing is None and not self.recreated:
                return {"status": True, "data": {}}
            return {"status": True, "data": {"_id": "new-id" if self.recreated else "old-id",
                                              **({} if self.recreated else (self.existing or {})),
                                              "context": {"config-frequency": 60}}}
        if method == "DELETE":
            return {"status": True}
        if method == "POST":
            self.recreated = True
            return {"status": True, "data": {"_id": "new-id"}}
        if method == "PUT":
            return {"status": True}
        return {"status": True, "data": {}}


BEAT = {"name": "context-verify-beat", "status": "inactive", "scheduled": False,
        "context": {"config-frequency": 60}, "workflows": []}


@pytest.mark.parametrize("kit", ["context-verify.py", "surface-verify.py"])
def test_active_beat_is_restored_after_recreation(kit, monkeypatch, capsys):
    mod = _load(kit)
    api = FakeApi(existing={"status": "active", "scheduled": False})
    monkeypatch.setattr(mod, "_req", api.req)
    assert mod._create("agent", dict(BEAT)) is True
    puts = [c for c in api.calls if c[0] == "PUT"]
    assert len(puts) == 1
    _, path, body = puts[0]
    assert path == "agent/new-id" and body["status"] == "active" and body["scheduled"] is False
    assert body["context"]["config-frequency"] == 60
    assert "activation restored" in capsys.readouterr().out


@pytest.mark.parametrize("kit", ["context-verify.py", "surface-verify.py"])
def test_inactive_or_missing_agents_are_left_at_their_defaults(kit, monkeypatch):
    mod = _load(kit)
    for existing in (None, {"status": "inactive", "scheduled": False}):
        api = FakeApi(existing=existing)
        monkeypatch.setattr(mod, "_req", api.req)
        assert mod._create("agent", dict(BEAT)) is True
        assert not [c for c in api.calls if c[0] == "PUT"]


def test_non_agent_resources_never_look_up_activation(monkeypatch):
    mod = _load("context-verify.py")
    api = FakeApi()
    monkeypatch.setattr(mod, "_req", api.req)
    assert mod._create("workflow", {"name": "context-verify"}) is True
    assert [c[0] for c in api.calls] == ["GET", "POST"]  # _delete_by_name's GET, then the create
