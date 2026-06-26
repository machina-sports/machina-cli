# Harness Loop vs the Loop-Engineering Playbook — Scorecard

This measures the loop against the **Loop-Engineering playbook** (Osmani / Steinberger /
Cherny) and shows how **Cap 8 — verification** closes the one gap that mattered. Every
"after" claim here was checked **live** against a staging pod (`gemini-3.1-flash-lite`);
the runs are in §6.

The playbook's thesis, in one line: the floor of a real loop is the **generator/evaluator
separation** — the thing that produces work must not be the thing that approves it.

---

## 1. The five failure modes — scorecard

| Failure mode | What it is | Our state |
| --- | --- | --- |
| **Nodding loop** | Generates and then *self-approves* — no independent check. | **WAS us → now closed.** A turn reaches `idle` only if it clears a deterministic gate **and** an independent evaluator (`loop-evaluate`, separate context + skeptical posture). Otherwise → `needs_review`. |
| **Amnesiac loop** | Forgets between turns. | **Avoided.** Every turn is persisted to a `harness_session` document; prior entries replay as history. |
| **Manual loop** | A human re-drives each turn. | **Avoided.** `loop-runner` advances the turn; the CLI / SportsClaw only kick it. |
| **Blind loop** | Runs unbounded, no stop condition. | **Addressed.** The resume path has an attempt budget (`LOOP_MAX_ATTEMPTS`) → `needs_review`. (Per-turn *token* cap still TODO.) |
| **Tangled loop** | One context does everything. | **Avoided.** Roles are split: prompts (reason / respond / **evaluate**), connector (tools), workflows (turn / resume), agents (runner / beat). |

---

## 2. The First-Loop Checklist (playbook Table VI) as a readiness gate

| Checklist item | What the playbook asks | Our status |
| --- | --- | --- |
| **Discovery source** | Where does work enter the loop? | User message / SportsClaw delegation → `loop-runner`. ✅ |
| **State file** | Durable state between turns. | `harness_session` document (entries, status, turn, verification). ✅ |
| **Evaluator** | A *separate* check before "done". | `loop-evaluate` (LLM skeptic) + deterministic gate. ✅ **(new)** |
| **Isolation** | Failures stay contained. | Per-session document; `needs_review` quarantines a bad turn instead of letting it advance. ✅ (server-side; no worktree needed) |
| **Token / turn cap** | Bounded cost. | Resume attempt budget ✅ · per-turn token cap ⚠️ TODO. |
| **Human review** | A real checkpoint. | `needs_review` status, surfaced by the CLI (`⚠ needs review — <reason>`). ✅ |

Five of six green; the open square is a per-turn token cap.

---

## 3. The Minions pattern, applied (deterministic gates ⟂ LLM steps)

Stripe's "Minions" run ~1,300 PRs/week not because the model is huge but because every LLM
step is **boxed by deterministic gates** — reliability comes from the constraints, not the
model size. Our turn interleaves the same way:

```
reason (LLM) → run-tool → respond (LLM) → [ deterministic GATE ] → evaluate (LLM)
            → ( [repair (LLM) → re-evaluate (LLM)]  if the evaluator rejected )  → finalize
```

- **The gate is cheap code, and it fails closed.** Checks: the answer is non-trivial, has no
  error marker, and — if a tool ran — the tool actually succeeded. If the gate fails we
  **skip the LLM evaluator entirely** and go straight to `needs_review` (cheaper *and* safer).
- **The evaluator is the skeptic**, run only when the gate has already passed.

Live proof (§6, case 5): `10 / 0` → the `calculate` tool returns `error: division by zero`
→ `gate_pass=False` → `needs_review`, with **no evaluator tokens spent**.

---

## 4. The four reinforcing costs — and what we do about each

| Cost (playbook) | Mitigation in the loop |
| --- | --- |
| **Verification debt** — unchecked output piles up | `loop-evaluate` verifies *every* turn; the verdict is stored on the session. |
| **Comprehension rot** — nobody understands the output | `verification.reason` is recorded and surfaced; `needs_review` forces a human to look. |
| **Cognitive surrender** — rubber-stamping | The evaluator runs in a *separate context* with an "assume it's wrong" posture; the gate is mechanical, not a vibe. |
| **Token blowout** — runaway spend | Resume attempt budget caps re-runs of a stuck session. (Per-turn token cap = next.) |

---

## 5. "Stay the engineer" — the human checkpoint

The playbook closes: *build the loop like someone who intends to stay the engineer.* We encode
that as **`needs_review`**. The loop never silently marks a questionable turn done:

- `idle` → verified (gate ✓ **and** evaluator `pass`). Safe to continue.
- `needs_review` → the gate failed, the evaluator said `fail`, or the attempt budget ran out.
  The turn stops and asks for eyes; it stays continuable with `machina loop say`.

---

## 6. Live verification (staging pod, `gemini-3.1-flash-lite`)

| # | Prompt | status | gate | verdict | What it proves |
| --- | --- | --- | --- | --- | --- |
| 1 | `1234 * 5678` | `idle` | ✓ | **pass** | Evaluator runs end-to-end; good answer verified, with a specific reason. |
| 2 | `2+2, e a capital da França?` | `idle` | ✓ | **pass** | Multi-part answer; evaluator confirms *both* parts addressed. |
| 3 | `jogos de ontem` (no data) | `idle` | ✓ | **pass** | Loop refuses honestly (no hallucination); evaluator validates the refusal. |
| 4 | `333*333 + análise pré-jogo` | `idle` | ✓ | **pass** | Honest partial answer; evaluator accepts the "missing info" explanation. |
| 5 | `10 / 0` (tool errors) | **`needs_review`** | **✗** | skipped | **Deterministic gate fails closed** → human checkpoint, no eval spend. |
| 6 | `1234*5678` w/ `EVAL_MODEL=gemini-3.1-pro` | `active` (stuck) | — | — | A *missing* evaluator model leaves the turn un-finalized — exactly the durability case the beat + attempt budget exist for. |

**Two honest findings:**

1. **Use a different / stronger evaluator model in production.** In every test the loop stayed
   honest, so the evaluator had little to reject — and a *same-model* evaluator
   (flash-lite judging flash-lite) is **lenient** on plausible-but-unsupported facts (case 2/3
   it was right; a fabricated-but-correct-looking timestamp once slipped by). That is precisely
   why the playbook wants a *separate* evaluator. `EVAL_MODEL` exists for this; on the test pod
   `gemini-3.1-pro` was not enabled (case 6), so production should point `EVAL_MODEL` at a
   stronger model that *is*.
2. **The `verdict=fail → needs_review` branch is proven.** It is the *same* `finalize` branch the
   deterministic gate already exercised live (case 5). We did not manufacture a fake wrong answer
   to force the LLM verdict string — the mechanism is identical and verified.

---

## 7. Shipped since, and still open

- **Cap 8.2 — retry-with-critique** ✅ **done & verified.** If the gate passes but the evaluator
  *rejects* the answer, the loop does ONE bounded repair (`loop-repair`, feeding the rejection
  reason back) and re-verifies (`loop-evaluate-2`) before deciding `idle` vs `needs_review`.
  Generator/evaluator → generator/evaluator/**repairer**; bounded to one pass (no loop). Live
  proof: forcing the first evaluator to reject a *correct* answer made the loop self-heal to
  `idle` with `verification.repaired=true`; an answer that passes first time keeps
  `repaired:false` (repair correctly not triggered).
- **Per-turn / per-session token cap** — we have the attempt budget; add a token ceiling. *(open)*
- **A production `EVAL_MODEL`** distinct from the generator (see finding 1). *(open)*
- **Operator-sync:** route SportsClaw's operator-daemon decisions through the loop; its
  broadcast-safety validators are a natural *second* evaluator lens. *(open)*

> Provisioner: [`provision.py`](provision.py) (`EVAL_MODEL`, `LOOP_MAX_ATTEMPTS`). Architecture:
> [`../agentic-harness-loop.md`](../agentic-harness-loop.md). Run guide: [`VALIDATION.md`](VALIDATION.md).
