#!/usr/bin/env python3
"""
Machina Nodes — a shared, reusable node library for pod workflows.

The Pressbox lesson applied to Machina's own engine: workflows here are already
data (tasks + conditions + $.get() templating) walked by an executor — what was
missing is a REGISTRY of small, composable action nodes, so a new automation is
graph wiring instead of another copy-pasted pyscript. This kit provisions one
connector, `machina-nodes`, whose commands are those nodes:

  slack_notify      post a ready-composed text to the pod's Slack webhook.
                    Resolves the webhook from the `slack-notify-config` document
                    (same doc surface-verify/context-verify already use) or an
                    explicit input. No text / no webhook -> clean no-op.
  github_issue      open a GitHub issue (title/body/labels). Token + default repo
                    come from a `github-issue-config` document ({token, repo}) or
                    explicit inputs. INERT until that doc exists -- provisioning
                    this connector changes nothing until someone drops a token.
  compose_approval  build an approval request (an `approval-request` document
                    value + the Slack ask) for content/actions that need a human
                    before executing -- the "keep one door open" checkpoint as a
                    node. The CARRIER workflow saves the doc and posts the ask
                    (see machina-approval-demo); this node only composes.
  resolve_approval  act on a human's decision: approve -> dispatch the stored
                    action workflow (in-pod), reject -> just record it. Guarded
                    against double-resolution. Wired into the provisioned
                    `machina-approval-resolve` workflow, which any surface (CLI
                    `machina approvals`, Studio, MCP) executes with
                    {request_id, decision}.

Design rules every node follows (and future nodes must too):
  - best-effort: a node NEVER raises -- an automation nicety must never fail
    the workflow that carries it. Failures return {..., "error": "..."}.
  - inert by default: missing config -> {"skipped": "..."}, zero side effects.
  - composition over configuration: nodes take READY inputs (text, title);
    composing them is the calling workflow's job, in task inputs -- that keeps
    each node small and every combination possible.

`machina-nodes-demo` (compose-in-inputs -> post) and `machina-approval-demo`
(compose_approval -> save doc -> slack ask; the approved action itself runs
machina-nodes-demo) are provisioned as living documentation of the patterns.

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
import json, os, urllib.request, urllib.error


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


def compose_approval(request_data: dict) -> dict:
    """Build an approval request: the `approval-request` document value + the Slack ask.
    Pure composition -- the carrier workflow saves the doc and posts the text (see the
    machina-approval-demo graph). action_workflow/action_inputs describe what runs IF a
    human approves; nothing executes here."""
    import uuid
    from datetime import datetime, timezone
    p = request_data.get("params", {}) or request_data
    title = (p.get("title") or "").strip()
    if not title or title.startswith("$"):
        return {"status": True, "data": {"composed": False, "skipped": "no title"}}
    request_id = uuid.uuid4().hex[:10]
    preview = str(p.get("preview") or "")[:2000]
    action_workflow = (p.get("action_workflow") or "").strip()
    action_inputs = p.get("action_inputs") if isinstance(p.get("action_inputs"), dict) else {}
    approval = {"request_id": request_id, "title": title, "preview": preview,
                "action": {"workflow": action_workflow, "inputs": action_inputs},
                "status": "pending", "requested_by": p.get("requested_by") or "workflow",
                "requested_at": datetime.now(timezone.utc).isoformat()}
    lines = [":raised_hand: *Approval requested* (`%s`)" % request_id, ">*%s*" % title]
    if preview:
        lines.append(">%s" % preview[:600].replace("\n", "\n>"))
    lines.append(">Approve: `machina approvals approve %s` . Reject: `machina approvals reject %s`"
                 % (request_id, request_id))
    return {"status": True, "data": {"composed": True, "approval": approval,
                                      "slack_text": "\n".join(lines)}}


def resolve_approval(request_data: dict) -> dict:
    """Act on a human decision for an approval request. approve -> dispatch the stored
    action workflow in-pod; reject -> just record. Guarded against double-resolution.
    Returns the updated doc value for the carrier workflow's document-update task --
    this node does not write documents itself."""
    from datetime import datetime, timezone
    p = request_data.get("params", {}) or request_data
    request_id = (p.get("request_id") or "").strip()
    decision = (p.get("decision") or "").strip().lower()
    if not request_id or request_id.startswith("$"):
        return {"status": True, "data": {"resolved": False, "error": "no request_id"}}
    if decision not in ("approve", "reject"):
        return {"status": True, "data": {"resolved": False, "error": "decision must be approve|reject"}}

    doc_id, value = None, None
    try:
        from core.document.controller import document_search
        r = document_search(filters={"name": "approval-request", "value.request_id": request_id},
                             page=1, page_size=1)
        dd = r.get("data") if isinstance(r, dict) else None
        rows = dd.get("data") if isinstance(dd, dict) else (dd if isinstance(dd, list) else [])
        if rows:
            doc_id = rows[0].get("_id")
            value = rows[0].get("value") or {}
    except Exception as e:
        return {"status": True, "data": {"resolved": False, "error": "lookup failed: %s" % str(e)[:120]}}
    if not doc_id:
        return {"status": True, "data": {"resolved": False, "error": "request %s not found" % request_id}}
    if value.get("status") != "pending":
        return {"status": True, "data": {"resolved": False,
                                          "skipped": "already %s" % value.get("status")}}

    dispatch = {"dispatched": False}
    if decision == "approve":
        action = value.get("action") or {}
        wf = (action.get("workflow") or "").strip()
        if wf:
            token = os.environ.get("MACHINA_PROJECT_KEY", "")
            try:
                req = urllib.request.Request("http://localhost:5003/workflow/execute/" + wf,
                    data=json.dumps(action.get("inputs") or {}).encode(), method="POST",
                    headers={"X-Api-Token": token, "Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    r.read()
                dispatch = {"dispatched": True, "workflow": wf}
            except Exception as e:
                # the human approved; record the decision but surface the dispatch failure
                dispatch = {"dispatched": False, "workflow": wf, "error": str(e)[:150]}

    new_value = dict(value)
    new_value["status"] = "approved" if decision == "approve" else "rejected"
    new_value["resolved_at"] = datetime.now(timezone.utc).isoformat()
    new_value["resolved_by"] = p.get("resolver") or "unknown"
    new_value["dispatch"] = dispatch
    icon = ":white_check_mark:" if decision == "approve" else ":no_entry_sign:"
    note = ""
    if decision == "approve":
        note = (" -- action `%s` dispatched" % dispatch.get("workflow")) if dispatch.get("dispatched") \
            else ((" -- action dispatch FAILED: %s" % dispatch.get("error")) if dispatch.get("workflow") else "")
    slack_text = "%s *Approval %s* (`%s`) -- %s%s" % (
        icon, new_value["status"], request_id, value.get("title", ""), note)
    return {"status": True, "data": {"resolved": True, "doc_id": doc_id, "new_value": new_value,
                                      "dispatch": dispatch, "slack_text": slack_text}}
'''


APPROVAL_DOC_VAL = "$.get('ap_approval', {})"
APPROVAL_UPDATED_VAL = "$.get('ap_new_value', {})"


def definitions():
    connector = {"name": "machina-nodes", "title": "Machina Nodes", "status": "active",
                 "description": "shared action-node registry (slack_notify, github_issue, approvals) for workflow composition",
                 "filename": "machina_nodes.py", "filetype": "pyscript", "filecontent": NODES_SRC,
                 "commands": [{"name": "SlackNotify", "value": "slack_notify"},
                              {"name": "GithubIssue", "value": "github_issue"},
                              {"name": "ComposeApproval", "value": "compose_approval"},
                              {"name": "ResolveApproval", "value": "resolve_approval"}]}
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
    # The REQUEST pattern: compose -> save the approval-request doc -> post the ask.
    # Any producer pipeline copies these three tasks (with its own title/preview/action)
    # to gate an action behind a human -- the "keep one door open" checkpoint.
    approval_demo = {
        "name": "machina-approval-demo", "title": "Machina Approval Demo", "status": "active",
        "description": "request pattern: compose_approval -> save doc -> slack ask (approved action runs machina-nodes-demo)",
        "context-variables": {"debugger": {"enabled": True}},
        "inputs": {"title": "$.get('title', 'Demo approval request')",
                   "preview": "$.get('preview', 'Approve to post a confirmation message via machina-nodes-demo.')",
                   "action_workflow": "$.get('action_workflow', 'machina-nodes-demo')",
                   "action_inputs": "$.get('action_inputs', {'text': ':white_check_mark: approved action executed -- this message was gated behind a human approval.'})"},
        "outputs": {"request": "$.get('ap_approval', {})", "workflow-status": "'executed'"},
        "tasks": [
            {"name": "compose", "type": "connector",
             "connector": {"command": "compose_approval", "name": "machina-nodes"},
             "inputs": {"title": "$.get('title')", "preview": "$.get('preview')",
                        "action_workflow": "$.get('action_workflow')",
                        "action_inputs": "$.get('action_inputs')"},
             "outputs": {"ap_approval": "$.get('approval')", "ap_slack": "$.get('slack_text')",
                         "ap_composed": "$.get('composed', False)"}},
            {"name": "save-request", "type": "document",
             "condition": "$.get('ap_composed', False) == True",
             "config": {"action": "save", "embed-vector": False, "force-update": True},
             "documents": {"approval-request": APPROVAL_DOC_VAL}},
            {"name": "ask", "type": "connector",
             "condition": "$.get('ap_composed', False) == True",
             "connector": {"command": "slack_notify", "name": "machina-nodes"},
             "inputs": {"text": "$.get('ap_slack', '')"},
             "outputs": {"ap_notified": "$"}},
        ]}
    # The RESOLVE surface: any client (CLI `machina approvals`, Studio, MCP) executes
    # this with {request_id, decision, resolver} -- the in-pod logic stays shared.
    approval_resolve = {
        "name": "machina-approval-resolve", "title": "Machina Approval Resolve", "status": "active",
        "description": "resolve an approval request: approve -> dispatch stored action; reject -> record",
        "context-variables": {"debugger": {"enabled": True}},
        "inputs": {"request_id": "$.get('request_id', '')", "decision": "$.get('decision', '')",
                   "resolver": "$.get('resolver', 'unknown')"},
        "outputs": {"resolved": "$.get('ap_resolved', False)", "dispatch": "$.get('ap_dispatch', {})",
                    "error": "$.get('ap_error', '')", "workflow-status": "'executed'"},
        "tasks": [
            {"name": "resolve", "type": "connector",
             "connector": {"command": "resolve_approval", "name": "machina-nodes"},
             "inputs": {"request_id": "$.get('request_id')", "decision": "$.get('decision')",
                        "resolver": "$.get('resolver')"},
             "outputs": {"ap_resolved": "$.get('resolved', False)", "ap_doc_id": "$.get('doc_id')",
                         "ap_new_value": "$.get('new_value', {})", "ap_dispatch": "$.get('dispatch', {})",
                         "ap_slack": "$.get('slack_text', '')",
                         "ap_error": "$.get('error', $.get('skipped', ''))"}},
            {"name": "mark-resolved", "type": "document",
             "condition": "$.get('ap_resolved', False) == True",
             "config": {"action": "update", "embed-vector": False, "force-update": True},
             "filters": {"document_id": "$.get('ap_doc_id')"},
             "documents": {"approval-request": APPROVAL_UPDATED_VAL}},
            {"name": "confirm", "type": "connector",
             "condition": "$.get('ap_resolved', False) == True",
             "connector": {"command": "slack_notify", "name": "machina-nodes"},
             "inputs": {"text": "$.get('ap_slack', '')"},
             "outputs": {"ap_notified": "$"}},
        ]}
    return [("connector", connector), ("workflow", demo),
            ("workflow", approval_demo), ("workflow", approval_resolve)]


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
