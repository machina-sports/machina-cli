# Machina Harness Loop — Validation Kit

Self-contained kit to stand up the Machina **durable agentic turn loop** ("harness")
in any project pod and validate it against **real project data**, before any code
fusion with SportsClaw.

- `provision.py` — stdlib-only, idempotent provisioner (no deps).
- `VALIDATION.md` — this file: what the loop is, how it maps to the Loop-Engineering
  playbook, how to validate, the verified contracts, and the honest gaps.
- `PLAYBOOK-SCORECARD.md` — the loop scored against the playbook (5 failure modes,
  First-Loop Checklist, Minions pattern) + the **live verification of Cap 8**.
- Deep architecture + chapter-by-chapter build: [`../agentic-harness-loop.md`](../agentic-harness-loop.md).
- Dynamic-tool dispatcher reference: [`../loop-tools-connector.py`](../loop-tools-connector.py).

---

## 1. What the loop is

A **server-side** agentic turn loop built entirely on Studio primitives (agent +
workflow + prompt + document + scheduler/beat). The CLI / MCP is a thin driver;
**all loop state lives in the pod** as `harness_session` documents. One turn:

```
load → ingest → reason → tool → respond → [gate] → evaluate → [repair → re-eval if rejected] → finalize(idle | needs_review)
```

Durable: each turn is persisted before advancing; a session left `active` is
resumed by the beat (survives crash / async tool / awaiting input). Multi-turn:
`say` appends a follow-up; prior turns feed back as context. **Verified:** a turn
reaches `idle` only after clearing a deterministic gate **and** an independent
evaluator; otherwise it stops at `needs_review` (see §2 and `PLAYBOOK-SCORECARD.md`).

Resources provisioned (`provision.py`): prompts `loop-reasoning` + `loop-respond` +
`loop-evaluate` (the independent verifier); connector `loop-tools` (calculate /
get_datetime / echo / **find_fixtures** = real data); workflows `loop-turn` +
`loop-resume`; agents `loop-runner` (executor) + `loop-beat` (durability tick,
**inactive by default**).

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
| **Verification** | sub-agents | `loop-evaluate` (separate context + "assume broken" posture) **+** a deterministic gate; any failure → `needs_review` | ✅ **(Cap 8)** |
| (connectors) | connectors | `loop-tools` + the pod's MCP surface | ✅ |

> **✅ The gap that mattered is closed (Cap 8).** The playbook's central claim is that
> **verification is the floor of a loop** — a *separate* evaluator that "assumes broken"
> and gates the stop condition. This loop used to skip it (a textbook **"Nodding loop"**:
> reason → act → self-approve). Cap 8 adds `loop-evaluate` — an independent verifier with a
> *fresh context* and a skeptical posture (its own `EVAL_MODEL`, ideally stronger than the
> generator) — in front of a cheap **deterministic gate**. A turn is finalized `idle` only
> if it clears **both**; otherwise it stops at `needs_review` (the human checkpoint).
> **Verified live** — see `PLAYBOOK-SCORECARD.md` §6. *Remaining caveat:* run a
> **different/stronger `EVAL_MODEL`** in production (a same-model evaluator is lenient), and
> add a per-turn token cap before fully unattended runs.

**First-Loop Checklist (Table VI) applied:**

| Element | Status here |
| --- | --- |
| Discovery source | tool catalog + user input (no CI/issue auto-discovery) |
| State file | `harness_session` document ✅ |
| **Evaluator** | `loop-evaluate` + deterministic gate ✅ **(verified live)** |
| Isolation | per-session doc; `needs_review` quarantines a bad turn ✅ (no worktree needed server-side) |
| Token cap | resume attempt budget (`LOOP_MAX_ATTEMPTS`) ✅ · per-turn token cap ⚠️ TODO |
| Human review | `needs_review` + the CLI `watch`/`say` loop ✅ |

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
- **Verification fails closed.** The deterministic gate (non-trivial answer, no error
  marker, tool succeeded if used) is the evaluator task's `condition` — if it fails, the
  LLM evaluator is *skipped* and the turn goes straight to `needs_review` (cheaper + safer).
  `EVAL_MODEL` sets the evaluator's model (defaults to the generator's; **use a stronger one
  in prod**). The resume path carries an `attempts` budget (`LOOP_MAX_ATTEMPTS`) → `needs_review`
  when exhausted, so the beat can't re-run a stuck session forever.

---

## 7. Gaps & roadmap (for code fusion)

1. **Verification / evaluator** ✅ **done (Cap 8)** — `loop-evaluate` (separate context,
   "assume broken" posture, `EVAL_MODEL`) + a deterministic gate; any failure → `needs_review`.
   Verified live (`PLAYBOOK-SCORECARD.md` §6). **Cap 8.2 — retry-with-critique** ✅ **done too:**
   a rejected (gate-passing) answer is repaired once (`loop-repair`) and re-verified
   (`loop-evaluate-2`) before idle/needs_review. *Next:* point `EVAL_MODEL` at a
   stronger-than-generator model in prod.
2. **Token cap.** Have the resume attempt budget (`LOOP_MAX_ATTEMPTS`); add a per-turn /
   per-session *token* ceiling before any fully unattended run.
3. **Handoff isolation.** Real sub-agent isolation (worktree-equivalent) for parallel
   child sessions.
4. **SportsClaw integration (phased):**
   - PR-1 ✅ `machina_loop` tool — delegate durable tasks to this loop via MCP (sportsclaw#113).
   - PR-2 — operator-sync: route the operator daemon's heartbeat/tick decisions into the
     loop (`OperatorSink → execute_agent`). The operator's broadcast-safety validators are a
     natural *second* evaluator lens on top of Cap 8.
