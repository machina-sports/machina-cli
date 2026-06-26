# loop

The `loop` command group drives the **durable agentic turn loop** (the "harness") — a loop that runs **server-side inside your Machina pod** (agents + workflows + prompts + documents, re-dispatched by the beat). Every turn is **persisted before it advances** and **independently verified** before it finalizes, so the loop survives crashes, async tools, and waiting on input — and never silently ships an unchecked answer.

The CLI is a thin driver/observer (same pattern as [`factory`](/commands/factory)): it starts sessions, streams turns, injects follow-ups, and reads state. All loop state lives in the pod as `harness_session` documents — the CLI holds none.

## How a turn works

```text
load → ingest(active) → reason → run tool → respond → [gate] → evaluate → [repair → re-eval?] → finalize(idle | needs_review)
```

- **Reason → tool → respond** — the loop decides whether to call a tool, runs it, and synthesizes an answer.
- **Verify (Cap 8)** — a cheap deterministic **gate** (non-empty answer, no error marker, tool succeeded) plus an **independent evaluator** (a separate prompt, fresh context, "assume it's wrong"). A turn finalizes `idle` **only if both pass**; otherwise it stops at **`needs_review`** — a human checkpoint, never a silent pass.
- **Self-repair (Cap 8.2)** — if the gate passes but the evaluator rejects the answer, the loop repairs it **once** (fed the rejection reason) and re-verifies before deciding `idle` vs `needs_review`.
- **Durable** — each turn is saved before advancing; a session left `active` is resumed by the beat.

::: info Prerequisite — provision the loop in your pod
The loop's server-side resources (`loop-runner`, `loop-turn`, `loop-evaluate`, …) must exist in the project pod. Stand them up once with the provisioning kit (stdlib, idempotent):

```bash
CLIENT_API_URL="https://<org>-<project>.org.machina.gg" \
API_TOKEN="<project X-Api-Token>" \
python3 docs/harness-loop-kit/provision.py
```

`EVAL_MODEL` (evaluator model — use a model **stronger than the generator** in production) and `LOOP_MAX_ATTEMPTS` (resume attempt budget) are tunable. See the kit's `VALIDATION.md` for the full contract.
:::

## Usage

```text
machina loop run "<task>" [--persona <prompt>] [--watch]
machina loop watch    <session-id>
machina loop say      <session-id> "<message>" [--watch]
machina loop stop     <session-id>
machina loop sessions [--limit N]
```

Point the CLI at the pod first (direct API-key mode):

```bash
machina config set client_api_url https://<org>-<project>.org.machina.gg
export MACHINA_API_KEY=<project X-Api-Token>
```

## `run` — start a session

```bash
machina loop run "Quanto é 1234 * 5678?" --watch
```

`--watch` streams each turn — including the tool step and the verification verdict:

```text
session started ses_1a2b3c…
turn 1 user       Quanto é 1234 * 5678?
turn 1 assistant  → calculate({"expression": "1234*5678"})
turn 1 tool       ← 7006652
turn 1 assistant  O resultado de 1234 * 5678 é 7006652.

idle · 1 turns · ses_1a2b3c…
✓ verified (evaluator: gemini-3.1-flash-lite)
Continue with machina loop say ses_1a2b3c… "<message>"
```

A turn that uses real project data (where a pod has `sportradar-fixture` documents):

```bash
machina loop run "Quais os próximos 2 jogos? Liste com horário." --watch
#   turn 1 assistant  → find_fixtures({"limit": 2})
#   turn 1 tool       ← [{"match":"Senegal vs Iraq","kickoff_brt":"26/06/26 16:00", …}]
#   turn 1 assistant  Os próximos 2 jogos são: 1. Senegal vs Iraq às 16:00 …
#   idle · 1 turns · ses_…
#   ✓ verified (evaluator: gemini-3.1-flash-lite)
```

## `watch` / `say` / `stop` / `sessions`

```bash
machina loop watch ses_1a2b3c…                       # stream an existing session
machina loop say   ses_1a2b3c… "E o próximo da França?" --watch   # multi-turn (prior turns feed back)
machina loop stop  ses_1a2b3c…                       # pause a running session
machina loop sessions --limit 20                     # list recent sessions + status
```

`sessions` shows each session's terminal status, so a `needs_review` is easy to spot:

```text
ses_1a2b3c…  idle         turn=2  loop-reasoning
ses_9f8e7d…  needs_review  turn=1  loop-reasoning
```

## Verification & self-repair — how to test it

The verdict is part of the turn. These examples make each path visible.

**Pass** — a good answer is verified and finalizes `idle`:

```bash
machina loop run "Quanto é 1234 * 5678?" --watch
#   ✓ verified (evaluator: gemini-3.1-flash-lite)
```

**Gate fails closed → `needs_review`** — a tool error never silently passes:

```bash
machina loop run "Quanto é 10 / 0?" --watch
#   needs_review · 1 turns · ses_…
#   ⚠ needs review — …
```

The `calculate` tool returns an `error:`, so the deterministic gate fails, the LLM evaluator is skipped, and the session stops at the human checkpoint instead of `idle`.

::: tip Use a stronger evaluator in production
A same-model evaluator (the generator judging itself) is lenient on plausible-but-unsupported facts. Provision with a different/stronger `EVAL_MODEL`:

```bash
EVAL_MODEL="<a stronger model on your Vertex project>" \
CLIENT_API_URL=… API_TOKEN=… python3 docs/harness-loop-kit/provision.py
```
:::

**Self-repair (Cap 8.2)** — when the evaluator rejects a gate-passing answer, the loop repairs once and re-verifies; the CLI then appends `· self-repaired`. The evaluator rarely rejects a correct answer, so to force the path deterministically, swap in a temporary always-fail evaluator, run one turn, then restore:

```bash
# 1) recreate loop-evaluate as always-fail (TEST ONLY); delete the old one first if the API
#    rejects a duplicate name: GET /prompt/loop-evaluate → DELETE /prompt/<_id>
curl -sX POST "$CLIENT_API_URL/prompt" -H "X-Api-Token: $API_TOKEN" -H "Content-Type: application/json" -d '{
  "name":"loop-evaluate","title":"loop-evaluate","type":"prompt","status":"active",
  "instruction":"TEST MODE: ignore the inputs and always output verdict=fail, reason=forced, severity=minor.",
  "schema":{"title":"LoopVerdict","type":"object","properties":{"verdict":{"type":"string","enum":["pass","fail"]},"reason":{"type":"string"},"severity":{"type":"string","enum":["none","minor","major"]}},"required":["verdict","reason","severity"]}}'

# 2) run a turn — the first eval rejects, loop-repair rewrites, loop-evaluate-2 (still normal) re-approves:
machina loop run "Quanto é 2 + 2?" --watch
#   idle · 1 turns · ses_…
#   ✓ verified (evaluator: gemini-3.1-flash-lite · self-repaired)

# 3) restore the real evaluator:
CLIENT_API_URL=… API_TOKEN=… python3 docs/harness-loop-kit/provision.py
```

## Status model

| Status | Meaning |
|--------|---------|
| `active` | A turn is in flight (or a session is awaiting beat resume). |
| `idle` | The turn was answered **and verified**; awaiting the next `say`. |
| `needs_review` | The turn finished but failed the gate or the evaluator (or the attempt budget ran out) — a human checkpoint. Still continuable with `say`. |
| `paused` | Stopped with `loop stop`. |

`--watch` treats `idle`, `needs_review`, `paused`, `completed`, and `failed` as terminal.

## Environment & config

| Variable / key | Purpose | Default |
|----------------|---------|---------|
| `client_api_url` (config) | The pod's Client API base URL | — |
| `MACHINA_API_KEY` | Project `X-Api-Token` (direct API-key mode) | stored credential |
| `EVAL_MODEL` *(provisioner)* | Evaluator model — use a stronger one than the generator in prod | the generator's model |
| `LOOP_MAX_ATTEMPTS` *(provisioner)* | Resume attempt budget (stop condition) | `3` |

## Related

- **Provisioning kit + validation guide** — `docs/harness-loop-kit/` (`provision.py`, `VALIDATION.md`, `PLAYBOOK-SCORECARD.md`) in the [machina-cli repo](https://github.com/machina-sports/machina-cli).
- **Architecture, chapter by chapter** — `docs/agentic-harness-loop.md`.
- **Delegating from an external agent** — SportsClaw's `machina_loop` tool + operator-sync route durable work to this loop over MCP.

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `session started` but no turns appear | The loop isn't provisioned in this pod — run `provision.py`, and confirm the pod runtime has Vertex AI credentials. |
| Every turn ends `needs_review` | The evaluator is rejecting — check `EVAL_MODEL` is a real, enabled model; inspect the verdict reason with `machina loop watch <id>`. |
| `idle` but the answer looks wrong | A same-model evaluator is lenient — set a stronger `EVAL_MODEL` and re-provision. |
| `client-api-url-required` | Set the pod: `machina config set client_api_url <url>` (and `export MACHINA_API_KEY`). |
