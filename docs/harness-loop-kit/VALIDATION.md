# Machina Harness Loop — Validation Kit

Self-contained kit to stand up the Machina **durable agentic turn loop** ("harness")
in any project pod and validate it against **real project data**, before any code
fusion with SportsClaw.

- `provision.py` — stdlib-only, idempotent provisioner (no deps).
- `VALIDATION.md` — this file: what the loop is, how it maps to the Loop-Engineering
  playbook, how to validate, the verified contracts, and the honest gaps.
- Deep architecture + chapter-by-chapter build: [`../agentic-harness-loop.md`](../agentic-harness-loop.md).
- Dynamic-tool dispatcher reference: [`../loop-tools-connector.py`](../loop-tools-connector.py).

---

## 1. What the loop is

A **server-side** agentic turn loop built entirely on Studio primitives (agent +
workflow + prompt + document + scheduler/beat). The CLI / MCP is a thin driver;
**all loop state lives in the pod** as `harness_session` documents. One turn:

```
load session → ingest(status:active) → reason (decide tool) → run tool → respond → finalize(status:idle)
```

Durable: each turn is persisted before advancing; a session left `active` is
resumed by the beat (survives crash / async tool / awaiting input). Multi-turn:
`say` appends a follow-up; prior turns feed back as context.

Resources provisioned (`provision.py`): prompts `loop-reasoning` + `loop-respond`;
connector `loop-tools` (calculate / get_datetime / echo / **find_fixtures** = real data);
workflows `loop-turn` + `loop-resume`; agents `loop-runner` (executor) + `loop-beat`
(durability tick, **inactive by default**).

---

## 2. How it maps to Loop Engineering (the playbook)

Per *Loop Engineering* (Osmani/Steinberger/Cherny; HuaShu Orange Book), a real loop
realizes **five moves** via **six parts**. Where this loop stands:

| Move (paper) | Part | In this loop | Status |
| --- | --- | --- | --- |
| **Scheduling** | automation | `loop-beat` agent (`status:active` + `config-frequency`); the beat re-dispatches `active` sessions | ✅ |
| **Persistence** | memory | `harness_session` documents (entries appended each turn; `value.status` is the resume gate) | ✅ |
| **Discovery** | skill | reasoning prompt + tool catalog; **input-driven** (no autonomous "what should I do" skill yet) | ◑ partial |
| **Handoff** | worktree | sub-agents via `execute_agent` child sessions (design); **no per-task worktree isolation** | ◑ partial |
| **Verification** | sub-agents | **none — the generator self-approves** | ❌ **GAP** |
| (connectors) | connectors | `loop-tools` + the pod's MCP surface | ✅ |

> **⚠️ The honest gap (read this).** The playbook's central claim is that
> **verification is the floor of a loop** — a *separate* evaluator agent, different
> model, that "assumes broken," acts via MCP, and gates a `/goal`-style stop
> condition judged by a *fresh* model. This loop has no such evaluator: the same
> agent reasons, acts, and effectively self-approves. By the paper's taxonomy that
> makes it a **"Nodding loop"** (verification skipped — the most common failure).
> It is safe to validate and demo, but **must not run unattended at scale** until an
> evaluator is added (see §6). This is the single most important thing for a reviewer
> to know.

**First-Loop Checklist (Table VI) applied:**

| Element | Status here |
| --- | --- |
| Discovery source | tool catalog + user input (no CI/issue auto-discovery) |
| State file | `harness_session` document ✅ |
| **Evaluator** | **missing** ❌ |
| Isolation | sub-agent design; no worktree ◑ |
| Token cap | none yet — add `max_turns` / per-run budget before unattended use ❌ |
| Human review | the CLI `watch`/`say` loop is the open door ✅ |

---

## 3. Prerequisites

- A Machina project pod whose runtime has **Vertex AI credentials** in env
  (`TEMP_CONTEXT_VARIABLE_VERTEX_AI_CREDENTIAL` / `_PROJECT_ID`) — the reasoning
  prompts use `invoke_prompt` (`google-genai`, `gemini-3.1-flash-lite` by default).
- The pod's **Client API URL** (`https://<org>-<project>.org.machina.gg`) and a
  project **`X-Api-Token`**.
- `find_fixtures` returns real data only where `sportradar-fixture` documents exist
  (e.g. an Entain coverage pod). Elsewhere it returns "no fixtures" — harmless.

---

## 4. Provision

```bash
CLIENT_API_URL="https://<org>-<project>.org.machina.gg" \
API_TOKEN="<project X-Api-Token>" \
python3 provision.py            # idempotent: delete-by-name + recreate
python3 provision.py --teardown # remove all loop resources
```
Idempotent because this Client API does a **shallow merge on PUT** (nested
`tasks`/`instruction` don't update) — the kit deletes-by-name then creates.

---

## 5. Validate

### A. Via the CLI (recommended)
Point `machina` at the pod (direct API-key mode) and drive the loop:
```bash
machina config set client_api_url https://<org>-<project>.org.machina.gg
export MACHINA_API_KEY=<project X-Api-Token>

machina loop run "Quais os próximos 2 jogos? Liste com horário." --watch   # real data tool
machina loop run "Quanto é 1234 * 5678?" --watch                            # calculate tool
machina loop run "Explique em uma frase o que é um durable loop." --watch   # no tool
machina loop sessions
machina loop say <session_id> "E o próximo da França?" --watch              # multi-turn
```
Expected (real-data example):
```
turn 1 user       Quais os próximos 2 jogos? ...
turn 1 assistant  → find_fixtures({"limit": 2})
turn 1 tool       ← [{"match":"Senegal vs Iraq", "kickoff_brt":"26/06/26 16:00", "home_analysis":"..."} ...]
turn 1 assistant  Os próximos 2 jogos são: 1. Senegal vs Iraq às 16:00 ...
idle · 1 turns
```

### B. Via MCP (how SportsClaw drives it)
The loop is just `execute_agent` + `search_documents` on the pod's MCP server:
```jsonc
// start a durable session
execute_agent(name="loop-runner",
  context={"context-agent": {"op":"start","session_id":"ses_X","input_message":"<task>","persona_agent":"loop-reasoning"}})
// read its state
search_documents(filters={"name":"harness_session","value.session_id":"ses_X"})
```
This is exactly what the SportsClaw `machina_loop` tool wraps (PR sportsclaw#113).

### C. Durability (optional — enables the beat)
By default `loop-beat` is **inactive**. To validate beat-driven resume: set
`loop-beat.status = "active"`, plant a `harness_session` doc with
`value.status:"active"` and an unanswered user entry, and watch the beat resume it
(~10–30s). Re-set to `inactive` when done (shared pod). See `../agentic-harness-loop.md` §Cap 4.

---

## 6. Verified contracts & gotchas (why it's built this way)

- **`execute_agent` async + flat context.** `agent/executor` flattens `context-agent`,
  so workflow `$.get('input_message')` resolves. (Direct `workflow/execute` needs a
  FLAT body — wrapping in `context-workflow` double-nests and inputs don't resolve.)
- **Documents nest payload under `value`.** Workflow `document save` writes `value.*`;
  filter by dot-notation `value.session_id` / `value.status`.
- **Connector contract: return `{"status": true, "data": {...}}`.** A bare dict is
  treated as a FAILED connector. Inputs arrive under `request_data["params"]`.
  Connectors are exec'd from DB `filecontent` at call time — **no code deploy needed**
  (only third-party *deps* must already be in the client-api runtime; stdlib is fine).
- **Two agents for durability.** `loop-runner` (inactive, executor path) + `loop-beat`
  (active+scheduled, beat path). Agent-level workflow `condition` does NOT gate
  reliably — separate the executor and beat paths into distinct agents. The beat
  dispatches by the agent's **top-level `status:active`**.
- **Prompt task name = prompt name** (`invoke_prompt` selects by task name) → two
  reasoning passes need two prompts (`loop-reasoning`, `loop-respond`).

---

## 7. Gaps & roadmap (for code fusion)

1. **Verification / evaluator (highest priority).** Add a separate evaluator —
   different model, "assume broken," acts via MCP — plus a `/goal`-style stop
   condition judged by a *fresh* model. This turns the Nodding loop into a real loop.
2. **Token cap.** Add `max_turns` per burst + a per-session budget before any
   unattended run.
3. **Handoff isolation.** Real sub-agent isolation (worktree-equivalent) for parallel
   child sessions.
4. **SportsClaw integration (phased):**
   - PR-1 ✅ `machina_loop` tool — delegate durable tasks to this loop via MCP (sportsclaw#113).
   - PR-2 — operator-sync: route the operator daemon's heartbeat/tick decisions into the
     loop (`OperatorSink → execute_agent`). This is also the natural home for the evaluator
     (SportsClaw's operator already has broadcast-safety validators).
