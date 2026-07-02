#!/usr/bin/env python3
"""
Machina Nodes — a shared, reusable node library for pod workflows.

The Pressbox lesson applied to Machina's own engine: workflows here are already
data (tasks + conditions + $.get() templating) walked by an executor — what was
missing is a REGISTRY of small, composable action nodes, so a new automation is
graph wiring instead of another copy-pasted pyscript. This kit provisions one
connector, `machina-nodes`, whose commands are those nodes:

  slack_notify   post a ready-composed text to the pod's Slack webhook.
                 Resolves the webhook from the `slack-notify-config` document
                 (same doc surface-verify/context-verify already use) or an
                 explicit input. No text / no webhook -> clean no-op.
  github_issue   open a GitHub issue (title/body/labels). Token + default repo
                 come from a `github-issue-config` document ({token, repo}) or
                 explicit inputs. INERT until that doc exists -- provisioning
                 this connector changes nothing until someone drops a token.

Design rules every node follows (and future nodes must too):
  - best-effort: a node NEVER raises -- an automation nicety must never fail
    the workflow that carries it. Failures return {..., "error": "..."}.
  - inert by default: missing config -> {"skipped": "..."}, zero side effects.
  - composition over configuration: nodes take READY inputs (text, title);
    composing them is the calling workflow's job, in task inputs -- that keeps
    each node small and every combination possible.

A `machina-nodes-demo` workflow is provisioned alongside as living
documentation of the pattern (one compose-in-inputs -> post task).

Usage:
    CLIENT_API_URL="https://<org>-<project>.org.machina.gg" \\
    API_TOKEN="<project X-Api-Token>" \\
    python3 nodes.py            # provision the connector + demo workflow
    python3 nodes.py --run      # provision + post one marked smoke message
    python3 nodes.py --teardown # remove
"""

import json
import os
import sys

import urllib.request
import urllib.error

BASE = os.environ.get("CLIENT_API_URL", "").rstrip("/")
TOKEN = os.environ.get("API_TOKEN", "")


def _req(method, path, body=None):
    url = f"{BASE}/{path.lstrip('/')}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"X-Api-Token": TOKEN, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read() or "{}")
    except urllib.error.HTTPError as e:
        return {"status": False, "error": {"message": f"HTTP {e.code}: {e.read()[:200]}"}}
    except Exception as e:  # noqa: BLE001
        return {"status": False, "error": {"message": str(e)}}


def _delete_by_name(kind, name):
    d = _req("GET", f"{kind}/{name}").get("data", {})
    if isinstance(d, dict) and d.get("_id"):
        _req("DELETE", f"{kind}/{d['_id']}")


def _create(kind, body):
    _delete_by_name(kind, body["name"])
    res = _req("POST", kind, body)
    ok = res.get("status") in (True, "success")
    print(f"  {'OK ' if ok else 'ERR'} {kind}/{body['name']}"
          + ("" if ok else f"  -> {json.dumps(res.get('error'))[:120]}"))
    return ok


NODES_SRC = r'''"""machina-nodes: small, composable action nodes for pod workflows."""
import json, urllib.request, urllib.error


def _config_doc(name):
    """Read a single config document's value by name; {} when absent/unreadable."""
    try:
        from core.document.controller import document_search
        r = document_search(filters={"name": name}, page=1, page_size=1)
        dd = r.get("data") if isinstance(r, dict) else None
        rows = dd.get("data") if isinstance(dd, dict) else (dd if isinstance(dd, list) else [])
        if rows:
            return rows[0].get("value") or {}
    except Exception:
        pass
    return {}


def slack_notify(request_data: dict) -> dict:
    """Post a ready-composed text to Slack. Webhook: explicit input, else the pod's
    slack-notify-config document. No text / unresolved template / no webhook -> no-op.
    Best-effort: never raises."""
    p = request_data.get("params", {}) or request_data
    text = (p.get("text") or "").strip()
    if not text or text.startswith("$"):
        return {"status": True, "data": {"notified": False, "skipped": "no text"}}
    webhook = (p.get("webhook_url") or "").strip()
    if not webhook or webhook.startswith("$"):
        webhook = (_config_doc("slack-notify-config").get("webhook_url") or "").strip()
    if not webhook:
        return {"status": True, "data": {"notified": False, "skipped": "no webhook configured"}}
    try:
        req = urllib.request.Request(webhook, data=json.dumps({"text": text}).encode(),
                                     method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            r.read()
        return {"status": True, "data": {"notified": True}}
    except Exception as e:
        return {"status": True, "data": {"notified": False, "error": str(e)[:150]}}


def github_issue(request_data: dict) -> dict:
    """Open a GitHub issue. Token + default repo come from the github-issue-config
    document ({token, repo}) or explicit inputs -- INERT until configured. Repo is
    "owner/name". Best-effort: never raises."""
    p = request_data.get("params", {}) or request_data
    title = (p.get("title") or "").strip()
    if not title or title.startswith("$"):
        return {"status": True, "data": {"filed": False, "skipped": "no title"}}
    token = (p.get("token") or "").strip()
    repo = (p.get("repo") or "").strip()
    if not token or not repo or repo.startswith("$"):
        cfg = _config_doc("github-issue-config")
        token = token if token and not token.startswith("$") else (cfg.get("token") or "").strip()
        repo = repo if repo and not repo.startswith("$") else (cfg.get("repo") or "").strip()
    if not token or not repo:
        return {"status": True, "data": {"filed": False, "skipped": "not configured (github-issue-config)"}}
    payload = {"title": title, "body": p.get("body") or ""}
    labels = p.get("labels")
    if isinstance(labels, list) and labels:
        payload["labels"] = labels
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/%s/issues" % repo,
            data=json.dumps(payload).encode(), method="POST",
            headers={"Authorization": "Bearer " + token,
                     "Accept": "application/vnd.github+json",
                     # GitHub's API rejects requests without a User-Agent.
                     "User-Agent": "machina-nodes",
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read() or "{}")
        return {"status": True, "data": {"filed": True, "issue_url": d.get("html_url"),
                                          "number": d.get("number")}}
    except Exception as e:
        return {"status": True, "data": {"filed": False, "error": str(e)[:150]}}
'''


def definitions():
    connector = {"name": "machina-nodes", "title": "Machina Nodes", "status": "active",
                 "description": "shared action-node registry (slack_notify, github_issue) for workflow composition",
                 "filename": "machina_nodes.py", "filetype": "pyscript", "filecontent": NODES_SRC,
                 "commands": [{"name": "SlackNotify", "value": "slack_notify"},
                              {"name": "GithubIssue", "value": "github_issue"}]}
    # Living documentation of the composition pattern: the workflow composes the
    # message in task INPUTS; the node just posts it. Any workflow can copy this task.
    demo = {"name": "machina-nodes-demo", "title": "Machina Nodes Demo", "status": "active",
            "description": "composition demo: compose in inputs -> slack_notify node",
            "context-variables": {"debugger": {"enabled": True}},
            "inputs": {"text": "$.get('text', '')"},
            "outputs": {"notified": "$.get('nd_out', {})", "workflow-status": "'executed'"},
            "tasks": [
                {"name": "post", "type": "connector",
                 "connector": {"command": "slack_notify", "name": "machina-nodes"},
                 "inputs": {"text": "$.get('text', '')"},
                 "outputs": {"nd_out": "$"}},
            ]}
    return [("connector", connector), ("workflow", demo)]


def main():
    if not BASE or not TOKEN:
        sys.exit("Set CLIENT_API_URL and API_TOKEN environment variables.")
    defs = definitions()
    if "--teardown" in sys.argv:
        print(f"Tearing down machina-nodes on {BASE} ...")
        for kind, body in reversed(defs):
            _delete_by_name(kind, body["name"])
            print(f"  removed {kind}/{body['name']}")
        return
    print(f"Provisioning machina-nodes on {BASE} ...")
    ok = all(_create(kind, body) for kind, body in defs)
    print("Done." if ok else "Done with errors — check output above.")
    if "--run" in sys.argv:
        print("\nSmoke: posting one marked message via the demo workflow ...")
        r = _req("POST", "workflow/execute/machina-nodes-demo",
                 {"text": ":test_tube: machina-nodes — shared node library is live in this pod "
                          "(slack_notify + github_issue registered)."})
        print("  execute status:", r.get("status"), "| error:", r.get("error"))


if __name__ == "__main__":
    main()
