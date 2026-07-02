# approvals

The `approvals` command group is the **human side of workflow checkpoints** — the "keep one door open" principle as a first-class primitive. A workflow that produces something risky or publishable (an AI-written article, a bulk data change) can **gate the final action behind a human**: it files an approval request and stops. You list what's waiting, read it, and approve or reject. On approve, the stored action runs **in-pod**.

## Usage

```text
machina approvals list    [--project <id>] [--all] [--json]
machina approvals approve <request-id> [--project <id>] [--json]
machina approvals reject  <request-id> [--project <id>] [--json]
```

| Flag | Purpose |
|------|---------|
| `--project`, `-p` | A specific project (defaults to the selected project). |
| `--all`, `-a` | (`list`) Include already-resolved requests. |
| `--json`, `-j` | Machine-readable output. |

## The flow

```text
producer workflow ──> approval-request doc + Slack ask ──> human ──> approve/reject
                                                                   │
                                              approve: stored action workflow runs in-pod
```

1. A producer workflow composes a request with the `compose_approval` node (title, preview, and **what should run if approved** — a workflow name + inputs), saves it as an `approval-request` document, and posts the ask to the pod's Slack channel.
2. A human sees it (Slack or `approvals list`) and decides.
3. `approve`/`reject` execute the pod's `machina-approval-resolve` workflow — approve dispatches the stored action; reject just records the decision. Double-resolution is guarded: a request resolves exactly once.

```text
$ machina approvals list

              Approval requests — pending
┏━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┓
┃ Request    ┃ Title                    ┃ Status  ┃ On approve, runs ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━┩
│ a1b2c3d4e5 │ Publish: Flamengo x Vasco│ pending │ publish-article  │
└────────────┴──────────────────────────┴─────────┴──────────────────┘

$ machina approvals approve a1b2c3d4e5
Request a1b2c3d4e5 approved.
  action dispatched: publish-article
```

::: tip Resolution logic lives in the pod, not the CLI
`approve`/`reject` just execute the `machina-approval-resolve` workflow with `{request_id, decision}`. Any surface — this CLI, the Studio, an MCP agent — resolves through the same workflow, so the guard rails (double-resolution, dispatch recording) are shared.
:::

## Gating your own workflow

The request side is three tasks from the [`machina-nodes`](https://github.com/machina-sports/machina-cli/blob/main/docs/harness-loop-kit/nodes.py) library (see the provisioned `machina-approval-demo` workflow for a copyable example):

1. `compose_approval` — inputs: `title`, `preview`, `action_workflow`, `action_inputs`.
2. A `document` save task for the composed `approval-request`.
3. `slack_notify` with the composed ask.

An **actionless** request (empty `action_workflow`) is also valid — a pure human acknowledgment gate.

## Related

- [`loop`](/commands/loop) — the harness loop's `needs_review` is the same principle at the conversation level; `approvals` brings it to any workflow.
- Provisioning: `docs/harness-loop-kit/nodes.py` in the [machina-cli repo](https://github.com/machina-sports/machina-cli) (`python3 nodes.py` against the pod).
