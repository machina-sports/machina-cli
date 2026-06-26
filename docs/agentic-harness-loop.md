# Machina Harness — Durable Agentic Turn Loop

> Plano de arquitetura/implementação. Inspirado no `harness` do iii.dev
> (*"thin durable turn loop that wires session-manager, context-manager, and
> llm-router into an agent loop"*) e na metodologia incremental do tutorial
> Linkly (capítulos aditivos, sem reescrever o que já existe).

---

## 0. A ideia em uma frase

Construir um **loop de turnos durável** que roda sobre as primitivas que a
Machina Studio **já tem** (agents, workflows, connectors, prompts, documents,
scheduler/beat), com a `machina-cli` como superfície de *driver* e
*observabilidade* — o mesmo papel que `machina factory` cumpre hoje para o
Factory.

A palavra que define tudo é **durável**: o loop não pode viver só na memória de
um processo. Cada turno é persistido antes de avançar, e a *retomada* depende do
beat — não de o processo continuar vivo.

---

## 1. O modelo iii → Machina (a espinha)

No iii, "um sistema real é um conjunto de workers pequenos que invocam funções
uns dos outros através da engine". Na Machina, a "engine" é a Core API + Client
API, e os "workers" são connectors/agents/workflows. O mapeamento:

| iii (worker)                         | Equivalente na Machina                                                     |
| ------------------------------------ | -------------------------------------------------------------------------- |
| **engine** (workers via funções)     | Core API (`api.machina.gg`) + Client API por projeto (`{org}-{proj}…`)     |
| **harness** (durable turn loop)      | **NOVO** — o que este plano constrói                                       |
| **session-manager** (entries+triggers)| coleção `documents` (`harness_session`) com entries tipados + branching    |
| **context-manager**                  | composição `prompt` + `mapping` + `search_documents` (retrieval/RAG)       |
| **llm-router** (front door p/ providers)| camada multi-provider que a Studio já tem (`execute_prompt` / model config) |
| **shell / iii-sandbox** (exec)       | Factory (jobs sandboxed) + connectors pyscript (exec no client-api)        |
| **iii-queue** (durabilidade)         | **scheduler/beat** — re-dispatch por `status:active` de topo               |
| **iii-pubsub** (triggers)            | transições de status do scheduler / eventos de nó de workflow             |
| **iii-directory** (introspecção)     | `connector_search` / `search_agents` / `search_workflows`                  |
| **sub-agents as child sessions**     | `execute_agent` com link `parent_session_id`                               |

A peça crítica e específica da Machina: **o beat despacha por `status:active` de
topo, não por `context.status`** (ver memória `machina-scheduler-toplevel-status`).
Isso é o nosso `iii-queue` — é o que torna o loop durável de graça.

---

## 2. As três peças do harness, na Machina

### 2.1 session-manager → coleção `harness_session` (documents)
Store durável de *turn entries* tipados:

```jsonc
// documento da coleção `harness_session`
{
  "session_id": "ses_…",
  "parent_session_id": null,        // != null => child session (sub-agente)
  "agent": "research-agent",        // qual agent/persona roda os turnos
  "status": "active",               // TOPO: active|completed|failed|paused  → o beat lê isto
  "turn": 7,                        // contador idempotente
  "entries": [                      // append-only; branching por entry.parent
    { "id": "e1", "role": "user",      "type": "message", "content": "…" },
    { "id": "e2", "role": "assistant", "type": "message", "content": "…" },
    { "id": "e3", "role": "assistant", "type": "tool_call", "tool": "espn.scores", "args": {…} },
    { "id": "e4", "role": "tool",      "type": "tool_result", "ref": "e3", "content": {…} }
  ],
  "updated_at": "…"
}
```

Os "six emitted trigger types" do iii viram, aqui, transições de status +
escrita de entries que o scheduler observa.

### 2.2 context-manager → prompt + mapping + retrieval
Antes de cada chamada de LLM, monta a janela de contexto:
- system/persona via `prompt` (`get_prompt_by_name` / `execute_prompt`);
- histórico recente das `entries` (com poda/summarização quando estoura);
- retrieval via `search_documents` (RAG) quando o agent precisa de conhecimento.
- `mapping` para transformar saída do LLM ↔ formato de tool/connector.

### 2.3 llm-router → multi-provider da Studio
Reusar a camada multi-provider que a plataforma já expõe (a topologia já é
multi-provider). Cada turno escolhe modelo/provider por config do `agent` ou
override por turno. Não reinventar — `execute_prompt`/`execute_agent` já é a
"front door".

### 2.4 tools (o que o loop pode *fazer* entre turnos)
- **connectors** como ferramentas: `connector_search` (descobrir = iii-directory)
  + `connector_executor` (executar). Cada tool-call do LLM resolve para um
  connector.
- **Factory/sandbox** para execução de código (análogo `shell`/`iii-sandbox`):
  dispara job via a superfície de customers (`/c/api/projects`), observa por
  chain + SSE.
- **sub-agentes**: `execute_agent` criando uma *child session*
  (`parent_session_id` aponta pra sessão-mãe) — espelha "spawns sub-agents as
  child sessions".

---

## 3. A máquina de estados do turn loop

Um "turno" é uma iteração do loop. O *tick* é o beat.

```
        ┌──────────────────────────── beat tick (status == active) ───────────────────────────┐
        ▼                                                                                       │
  [active] ──► 1. assemble context (context-manager)                                            │
              2. call LLM (llm-router) ──► assistant message (+ tool_calls?)                     │
              3. persist entries (session-manager)  ◄── ponto de durabilidade                    │
              4a. tem tool_calls?  ──► executa connectors/factory/sub-agentes ──► persist results┘
              4b. sem tool_calls + resposta final ──► status = completed
              5. estourou max_turns / erro irrecuperável ──► status = failed | paused
```

Regras:
- **Persistir antes de avançar.** As entries do turno N vão pro documento *antes*
  de marcar o próximo tick. Se o processo morre no meio, nada se perde — o último
  estado consistente é o documento.
- **Idempotência por `turn`.** Cada turno carrega `turn_id`; ao retomar, o loop lê
  o último turno persistido e não reprocessa.
- **O status de topo é a verdade.** `active` ⇒ o beat vai pegar de novo. `completed`/
  `failed`/`paused` ⇒ o beat ignora. (Cuidado com a pegadinha da memória: ativar
  via `context.status` é silenciosamente morto — tem que ser o status de topo.)

---

## 4. Durabilidade & retomada (o coração)

| Preocupação            | Como resolvemos                                                                 |
| ---------------------- | ------------------------------------------------------------------------------- |
| Processo cai mid-turn  | Estado vive no documento `harness_session`, não na CLI. Re-dispatch pelo beat.  |
| Quem "tica" o loop     | **scheduler/beat**: sessões com `status:active` de topo são re-despachadas.     |
| Não reprocessar turno  | `turn` counter + entries append-only; retomada lê o último turno persistido.    |
| CLI offline            | Irrelevante — o loop server-side continua. CLI só observa (igual factory watch).|
| Continuação humana     | `harness say` injeta um entry `user` e re-seta `status:active` (≈ factory follow-up). |

Isto é o equivalente Machina do `iii-queue` (durabilidade) + do modelo de
*job-chain/continuation* que o Factory já tem (root/ancestors/current/descendants
+ `turn-divider` no SSE).

> **Decisão central (ver §9):** o loop roda **server-side** (um agent/workflow que
> se reagenda via beat) para ser de fato durável. A CLI client-side só orquestraria
> turnos enquanto estivesse viva — não é "durable", é o anti-padrão que o harness
> existe pra evitar.

---

## 5. Superfície CLI — `machina harness` (alias `machina loop`)

Novo subapp Typer, modelado nos padrões que já existem em `commands/factory.py`
(`_watch` por poll de 3s + `stream()` SSE) e na persistência local de
`config.py`.

| Comando                                   | O que faz                                                | Espelha                  |
| ----------------------------------------- | -------------------------------------------------------- | ------------------------ |
| `machina harness run "<prompt>" --agent X`| cria sessão, status=active, retorna `session_id`         | `factory run`            |
| `machina harness watch <id>`              | poll do loop até terminal (3s, cap configurável)         | `factory watch` / `_watch` |
| `machina harness logs <id> --follow`      | stream de turnos/entries (SSE ou poll)                   | `factory logs --follow`  |
| `machina harness say <id> "<msg>"`        | injeta turno do usuário + reativa (continuação)          | `factory follow-up`      |
| `machina harness stop <id>`               | status → paused/terminal                                 | `factory cancel`         |
| `machina harness sessions`                | lista sessões ativas/recentes                            | `factory list`           |

Arquivos:
- `src/machina_cli/commands/harness.py` — subapp Typer.
- `src/machina_cli/harness_client.py` — fala com a Client API + scheduler
  (reusar `ProjectClient`/`MachinaClient`; **não** mandar `mf_` keys).
- `main.py` — `app.add_typer(harness.app, name="harness")` (+ alias `loop`).
- `repl.py` — adicionar a `REPL_COMMANDS`/`SUB_COMMANDS` e ao `_completer`.
- `~/.machina/` — ponteiro opcional `last_session` (padrão `store_credential`).

---

## 6. Plano incremental (estilo Linkly — capítulos aditivos)

Cada capítulo soma **uma** capacidade e roda ponta-a-ponta sem reescrever o
anterior. Mesmo arco do tutorial: do mínimo viável ao loop durável completo.

| Cap | Adiciona                  | Entregável rodando                                              | Análogo Linkly            |
| --- | ------------------------- | -------------------------------------------------------------- | ------------------------- |
| 1   | **Single-turn**           | `harness run` → 1 chamada de LLM, sem tools, sem persistência   | cap 1 (link worker + http)|
| 2   | **Observability**         | entries persistidas em `documents`; `harness logs`             | cap 2 (iii-observability) |
| 3   | **Session multi-turn**    | retomada de sessão + `harness say`                             | cap 3 (state/persistence) |
| 4   | **Durability (beat)**     | scheduler re-despacha por `status:active`; sobrevive a crash   | cap 4 (queue/durability)  |
| 5   | **Tools (connectors)**    | tool-calls → `connector_executor`; descoberta via search       | cap 5 (streaming/pubsub)  |
| 6   | **Sub-agentes**           | child sessions via `execute_agent` (`parent_session_id`)        | cap 6 (bulk/channels)     |
| 7   | **Sandbox/Factory**       | tool de exec de código via job do Factory                      | cap 7 (browser worker)    |

Recomendação: **cap 1–4 são o MVP durável**. 5–7 são extensões. Dá pra entregar
o cap 4 e já ter um harness de verdade.

---

## 7. Formas de dado / contratos (rascunho)

**tool-call protocol (LLM ↔ connector):** o LLM emite `{tool, args}`; o harness
resolve `tool` → connector (via `mapping` ou convenção de nome), chama
`connector_executor`, e devolve o resultado como entry `tool_result` referenciando
o `tool_call`. As tools disponíveis num turno = catálogo derivado de
`connector_search` filtrado pelo agent (iii-directory).

**child session:** `execute_agent(agent=…, input=…, parent_session_id=ses_…)`;
o resultado da criança vira um entry na mãe quando ela completa
(trigger/poll). Profundidade limitada (evitar recursão infinita).

---

## 8. Riscos / pegadinhas conhecidas (das memórias)

- **status de topo vs context.status**: ativar sessão só via `context` é morto
  silenciosamente — o beat lê o status de topo. (`machina-scheduler-toplevel-status`)
- **factory ≠ pod MCP**: dois "factory" diferentes (Jobs API `mf_` vs pod MCP
  `X-Api-Token`). O cap 7 usa a superfície de *customers*, não a Jobs API crua.
  (`factory-vs-pod-mcp`, `machina-cli-factory-integration`)
- **connectors pyscript**: deps de terceiros de um connector precisam estar no
  runtime do `machina-client-api` (são `exec()`'d in-process).
  (`pyscript-connector-deps-in-client-api`)
- **CLI é 100% síncrona** (httpx + sleep-poll, sem asyncio). O harness server-side
  não muda isso; a CLI só faz poll/SSE como já faz em `factory`.

---

## 9. Decisões em aberto (pra você bater o martelo)

1. **Onde o loop roda?** Server-side durável (agent/workflow que se reagenda via
   beat) **[recomendado]** vs CLI orquestrando cada turno (simples, mas não
   durável). Isto define todo o resto.
2. **Session store:** coleção `documents` nova (`harness_session`) vs reaproveitar
   os registros de execução de agent. Coleção dedicada dá branching/trigger mais
   limpo.
3. **llm-router:** fixar provider por agent vs permitir override por turno.
4. **tool protocol:** convenção de nome `connector.function` vs `mapping` explícito
   pra resolver tool-call → connector.
5. **Nome do comando:** `machina harness` vs `machina loop` (ou um como alias do
   outro).

---
---

# Parte II — MVP durável (cap 1–4) em nível de implementação

> **Decisão batida:** o loop roda **server-side**. A CLI é um driver fino.
> Contratos abaixo são os **reais** que a `machina-cli` já usa contra a Client API
> (verificados em `agent.py`, `workflow.py`, `document.py`, `execution.py`,
> `project_client.py`). A CLI **não** cria/edita documents nem agents — então toda
> escrita e durabilidade vive server-side, dentro do `harness-runner`.

## A. Topologia de despacho (quem roda o quê)

```
  machina-cli (driver fino)                      Client API (engine)                 beat
  ─────────────────────────                      ───────────────────                ──────
  harness run  ──POST agent/executor──►  ┌──────────────────────┐
  harness say  ──POST agent/executor──►  │   harness-runner      │ ◄── tick a cada config-frequency
                                         │   (agent scheduled)   │     (enquanto status:active)
  harness watch ─POST document/search─►  │                       │
  harness logs  ─POST document/search─►  │  por execução:        │
  harness stop  ──POST agent/executor──► │  1. carrega sessões   │
                                         │     active            │
                                         │  2. roda um BURST de  │──► connector_executor (tools)
                                         │     turnos            │──► execute_agent     (sub-agentes)
                                         │  3. persiste cada     │
                                         │     turno (document)  │
                                         │  4. completa/pausa    │
                                         └──────────┬────────────┘
                                                    │ escreve
                                                    ▼
                                         documents: type="harness_session"
```

Dois caminhos chegam ao mesmo runner: **execute_agent** (interativo, da CLI) e o
**beat** (resumption durável). O burst é o caminho rápido; o beat é a rede de
segurança (crash, tool async, espera por humano).

## B. Endpoints reais (o que a CLI chama) — verificados

Tudo na **Client API** (`https://{org}-{proj}.org.machina.gg`), via `ProjectClient`.
Auth: `X-Session-Token` + `X-Project-Token` (ou `X-Api-Token` em modo direto).

| Operação                  | Método + path                               | Body / notas                                                        |
| ------------------------- | ------------------------------------------- | ------------------------------------------------------------------- |
| Executar runner (async)   | `POST agent/executor/harness-runner`        | `{"context-agent": {op…}, "agent-config": {"delay": true}}`         |
| Poll de execução          | `GET execution/agent-run/{id}?compact=true` | terminal: `agent-executed` / `completed` / `failed`                 |
| Ler sessão                | `POST document/search`                      | `{"filters": {"type":"harness_session","session_id":"…"}}`          |
| Listar sessões            | `POST document/search`                      | `{"filters": {"type":"harness_session"}, "sorters":["updated",-1]}` |

> Escritas (criar/atualizar o documento de sessão, alternar `status` do agent) **não**
> têm endpoint exposto na CLI hoje — e **não precisam ter**. Elas acontecem
> *dentro* do `harness-runner` via as primitivas server-side (`create_document` /
> `update_document` / `update_agent`, que a Studio já tem). A CLI nunca escreve
> estado do loop; só dispara o runner e lê o documento.

## C. Schema do documento de sessão (`type: "harness_session"`)

Documento simples (a Studio guarda `content` espalhado no doc + `filters`
MongoDB-style pra buscar). Campos-chave em **topo** pra `document/search` filtrar:

```jsonc
{
  "name": "harness:ses_01J…",          // único; usado pra get rápido
  "type": "harness_session",            // filtro primário
  "session_id": "ses_01J…",
  "parent_session_id": null,            // != null  => child session (sub-agente)
  "persona_agent": "research-agent",    // qual persona/prompt roda os turnos
  "status": "active",                   // active|completed|failed|paused  (do DOCUMENTO)
  "turn": 7,                            // contador idempotente
  "last_turn_id": "t_07",               // âncora de retomada
  "entries": [
    {"id":"e1","turn":1,"role":"user","type":"message","content":"…"},
    {"id":"e2","turn":1,"role":"assistant","type":"message","content":"…"},
    {"id":"e3","turn":2,"role":"assistant","type":"tool_call","tool":"espn.scores","args":{}},
    {"id":"e4","turn":2,"role":"tool","type":"tool_result","ref":"e3","content":{}}
  ],
  "created": "…",
  "updated": "…"
}
```

> ⚠️ **Dois `status` diferentes** (a pegadinha das memórias, agora concreta):
> - `harness_session.status` = estado **do trabalho** (esse documento).
> - `harness-runner.status` (`active`/`inactive`) no **registro do agent** = o que o
>   **beat lê** pra decidir re-despachar. É *top-level no agent*, não no `context`.
>   O runner alterna o próprio `status` do agent: `active` enquanto houver sessão
>   `active`; `inactive` quando todas terminam. Ativar via `context` é morto
>   silenciosamente.

## D. Precedente real: `copilot-executor` (já roda em produção)

> **Não estamos inventando o loop — estamos tornando o que já existe durável.**
> O agent `copilot-executor` já é um harness: 3 workflows com `condition`
> (reason → respond → update). Verificado na Studio (sbot-prd).

Anatomia (campos reais):
- **agent** = lista ordenada de `workflows`, cada um com `condition` (gate),
  `inputs`/`outputs` por expressão `$.get(...)`. `copilot-executor`:
  `copilot-reasoning` (decide tools) → `copilot-response` (sintetiza) →
  `copilot-update` (persiste no doc de thread).
- **workflow** = lista ordenada de `tasks` (nós), cada nó com `type` + `condition`.
  Tipos observados: **`document`** e **`prompt`**.
- **nó `type: "document"`** = persistência. Ex. carregar a sessão:
  ```jsonc
  { "type": "document", "name": "load-session",
    "config": { "action": "search", "search-limit": 1 },
    "filters": { "document_id": "$.get('session_id')", "name": "'harness_session'" },
    "outputs": { "exists": "len($.get('documents', [])) > 0" } }
  ```
  `action` ∈ `search | save | update` — é o nosso `create/update_document`.
  **Persistência verificada** (`copilot-update`): o conteúdo mora sob `value`
  (ex. `value.messages`); o append é uma expressão de dict-spread num nó
  `action: update, force-update: true`, com a chave do mapa `documents` = o `name`
  do doc:
  ```jsonc
  { "type": "document", "name": "append-turn",
    "config": { "action": "update", "force-update": true },
    "filters": { "document_id": "$.get('document_id')" },
    "documents": { "harness_session": "{**$.get('document_value', {}), 'entries': [*$.get('entries', []), *$.get('new_entries', [])], 'status': $.get('next_status'), 'turn': $.get('turn', 0) + 1}" } }
  ```
  ⚠️ Filtro é por `document_id`/`name` (não por campo arbitrário) → a sessão deve
  ser localizável por `name`, ex. `name: "harness_session:ses_xxx"`. O `LoopClient`
  já minta o `session_id` client-side, então dá pra derivar o `name` direto.
- **nó `type: "prompt"`** = chamada de LLM (o `llm-router`, já pronto):
  ```jsonc
  { "type": "prompt", "name": "harness-reasoning-prompt",
    "connector": { "command": "invoke_prompt", "provider": "vertex_ai",
                   "model": "gemini-2.5-flash", "name": "google-genai", "location": "global" },
    "inputs": { "_1-message-history": "$.get('messages', [])[-5:]",
                "_2-user-message": "$.get('input_message')",
                "_3-available-tools": "$.get('available_tools', [])" },
    "outputs": { "reasoning": "$" } }
  ```
  O structured output (o array `tool_calls`) vem do `schema` do prompt — exatamente
  o `copilot-reasoning-prompt`, que já emite
  `{needs_tool_call, tool_calls:[{name, arguments_json}], assistant_message, short_message}`.
- **context-manager** = a fatia `messages[-5:]` (janela deslizante). Já existe.

## D2. O `harness-runner` = `copilot-executor` + durabilidade

O harness é o copilot-executor com 3 adições: (a) **documento de sessão com
`status`**, (b) **`scheduled:true` + `config-frequency`** pra retomada via beat,
(c) **iteração multi-turno** (condition que re-roda enquanto não terminou).

**Registro do agent (campos reais):**
```jsonc
{
  "name": "harness-runner",
  "status": "active",                      // beat só pega se "active" (top-level!)
  "scheduled": true,                       // entra no ciclo do beat
  "context": { "config-frequency": 0.5 },  // 0.5 min = 30s (valor real em produção)
  "context-agent": {                       // schema de entrada (ops da CLI)
    "op":         "$.get('op', 'advance')",       // start | say | advance | stop
    "session_id": "$.get('session_id', None)",
    "input_message": "$.get('input_message', None)",
    "persona_agent": "$.get('persona_agent', 'research-agent')"
  }
}
```

**Workflows do runner (cada um = ordered tasks, gated por `condition`):**

| Workflow            | Gate (`condition`)                              | Tasks (nós)                                                            |
| ------------------- | ----------------------------------------------- | --------------------------------------------------------------------- |
| `harness-bootstrap` | `op == 'start'`                                 | `document(save)` cria sessão com `status:active`, entry seed do user   |
| `harness-ingest`    | `op == 'say'`                                   | `document(update)` anexa entry user, seta `status:active`              |
| `harness-load`      | `session_id is not None`                        | `document(search)` carrega sessão + monta `messages[-N:]`              |
| `harness-reason`    | `session.status == 'active'`                    | `prompt(invoke_prompt)` → `tool_calls` (schema) ; `document(update)` salva entry assistant |
| `harness-act`       | `len(tool_calls) > 0`                            | dispatch tools (connector / `execute_agent`) ; `document(update)` salva `tool_result` |
| `harness-finalize`  | `needs_tool_call == false`                      | `document(update)` seta `status:completed`                             |
| `harness-halt`      | `op == 'stop'`                                  | `document(update)` seta `status:paused`                                |

**Durabilidade sem mexer em `agent.status`:** o runner fica sempre `scheduled` e
`active`; quando ocioso, `harness-load`/`harness-reason` simplesmente **skipam**
pela `condition` (igual o copilot skipa quando `input_message is None`). Tick ocioso
= no-op barato a cada 30s. Sessão `active` ⇒ o próximo tick avança; crash no meio ⇒
último `document(update)` é a verdade e o beat retoma. **Não precisa alternar o
status do agent** — a `condition` na sessão faz o gating (resolve a lacuna 3).

> O **único trabalho server-side novo** é montar esses workflows/prompts (declarativo,
> via templates/MCP) — não há infra de LLM nem de loop pra escrever. `invoke_prompt`,
> nós `document`, `condition` e `execute_agent` já existem e já rodam no copilot.

## E. Durabilidade & retomada (amarrado aos campos reais)

| Falha                        | O que segura                                                                       |
| ---------------------------- | ---------------------------------------------------------------------------------- |
| Processo morre mid-burst     | Último `save(sess)` é a verdade. `agent.status` segue `active` → beat re-despacha.  |
| Tool async / sub-agente lento| Burst sai com `break`; sessão fica `active`; beat retoma e reavalia o tool_result. |
| Espera por humano            | `harness say` injeta entry e re-ativa; sessão `active` → próximo tick avança.      |
| CLI offline                  | Irrelevante — runner é server-side. CLI só faz poll quando volta.                  |
| Não reprocessar turno        | `turn` + `last_turn_id`; retomada lê o último turno persistido das `entries`.      |

## F. CLI — `harness_client.py` (esqueleto, reusa `ProjectClient`)

```python
# src/machina_cli/harness_client.py
from .project_client import ProjectClient

RUNNER = "harness-runner"
SESSION_TYPE = "harness_session"

class HarnessClient:
    def __init__(self) -> None:
        self._pc = ProjectClient()                      # mesmo auth/URL de agent/workflow

    def _exec(self, op: str, **ctx) -> dict:
        body = {"context-agent": {"op": op, **{k: v for k, v in ctx.items() if v is not None}},
                "agent-config": {"delay": True}}        # async; durabilidade é do runner
        return self._pc.post(f"agent/executor/{RUNNER}", json=body)["data"]

    def start(self, prompt: str, persona_agent: str) -> dict:
        return self._exec("start", content=prompt, persona_agent=persona_agent)

    def say(self, session_id: str, content: str) -> dict:
        return self._exec("say", session_id=session_id, content=content)

    def stop(self, session_id: str) -> dict:
        return self._exec("stop", session_id=session_id)

    def get_session(self, session_id: str) -> dict | None:
        body = {"filters": {"type": SESSION_TYPE, "session_id": session_id}, "page_size": 1}
        data = self._pc.post("document/search", json=body)["data"]
        return data[0] if data else None

    def list_sessions(self, limit: int = 30) -> list[dict]:
        body = {"filters": {"type": SESSION_TYPE}, "sorters": ["updated", -1], "page_size": limit}
        return self._pc.post("document/search", json=body)["data"]
```

## G. CLI — `commands/harness.py` (esqueleto, padrão `factory._watch`)

```python
# src/machina_cli/commands/harness.py
import time, typer
from rich.console import Console
from ..harness_client import HarnessClient

app = typer.Typer(help="Durable agentic turn loop (harness)")
console = Console()
TERMINAL = {"completed", "failed", "paused"}

@app.command()
def run(prompt: str, agent: str = typer.Option("research-agent", "--agent", "-a"),
        watch: bool = typer.Option(False, "--watch", "-w")):
    res = HarnessClient().start(prompt, agent)
    sid = res.get("session_id") or res.get("agent_run_id")
    console.print(f"[green]session[/] {sid}")
    if watch:
        _watch(sid)

@app.command()
def watch(session_id: str):
    _watch(session_id)

def _watch(session_id: str, interval: int = 3, timeout: int = 1800):
    hc, elapsed, seen = HarnessClient(), 0, 0
    with console.status("running turns…"):
        while elapsed < timeout:
            sess = hc.get_session(session_id) or {}
            entries = sess.get("entries", [])
            for e in entries[seen:]:                     # render só o que é novo (estilo logs --follow)
                console.print(f"[dim]turn {e.get('turn')}[/] {e.get('role')}: {e.get('content','')}")
            seen = len(entries)
            if sess.get("status") in TERMINAL:
                console.print(f"[bold]{sess.get('status')}[/] · {sess.get('turn')} turns"); return
            time.sleep(interval); elapsed += interval

@app.command()
def say(session_id: str, message: str):
    HarnessClient().say(session_id, message); console.print("[green]queued[/]")

@app.command()
def stop(session_id: str):
    HarnessClient().stop(session_id); console.print("[yellow]stopped[/]")

@app.command()
def sessions():
    for s in HarnessClient().list_sessions():
        console.print(f"{s.get('session_id')}  {s.get('status'):10} turn={s.get('turn')}  {s.get('persona_agent')}")
```

Registrar em `main.py`: `app.add_typer(harness.app, name="harness")` (+ alias
`loop`). Em `repl.py`: somar a `REPL_COMMANDS`/`SUB_COMMANDS` e ao `_completer`.

## H. Os capítulos 1–4 mapeados nesta implementação

| Cap | Escopo                | O que entra de novo                                                                 | Como testar                                        |
| --- | --------------------- | ----------------------------------------------------------------------------------- | -------------------------------------------------- |
| 1   | **Single-turn**       | `harness-runner` op=`start`, 1 turno, `delay:false`, sem persistência. `harness run`.| `machina harness run "oi"` imprime resposta inline |
| 2   | **Observability**     | `create_document`/`update_document` da sessão; `entries` por turno; `harness logs`.  | doc aparece em `document/search`; logs renderiza   |
| 3   | **Session multi-turn**| burst > 1 turno; `op=say` (continuação); âncora `last_turn_id`.                       | `harness say` continua a mesma sessão              |
| 4   | **Durability (beat)** | `runner.status=active` + `scheduled` + `config-frequency`; retomada por tick; `watch`.| mata o burst no meio → beat retoma do último turno |

**Cap 1–4 = harness durável de verdade.** Tools (cap 5), sub-agentes (cap 6) e
sandbox/Factory (cap 7) plugam no `run_tool`/`execute_agent` sem mexer no loop.

## I. Lacunas — status após inspeção da Studio (sbot-prd)

1. ~~**Onde mora o `run()`**~~ ✅ **RESOLVIDO.** Não é pyscript connector — é um
   **agent = workflows ordenados de tasks** (`type: document` + `type: prompt`),
   exatamente o `copilot-executor`. Declarativo, sem código de loop.
2. ~~**Primitiva de LLM**~~ ✅ **RESOLVIDO.** Nó `type: prompt` com
   `connector.command: invoke_prompt` (`provider: vertex_ai`, `model:
   gemini-2.5-flash`); structured output pelo `schema` do prompt. Já é o `llm-router`.
3. ~~**`update_agent` pra alternar `status`**~~ ✅ **DISPENSADO.** Runner fica sempre
   `active`+`scheduled`; gating é por `condition` na **sessão** (igual copilot gateia
   por `input_message`). Tick ocioso = no-op. Sem toggle de status do agent.
4. ~~**Granularidade do beat**~~ ✅ **RESOLVIDO.** `config-frequency: 0.5` (30s) roda
   em produção (`sportingbot-coverage-nba-matchday-hot`). Sub-minuto OK.

**Restam decisões de produto (não de viabilidade):**
- **Reusar `copilot-thread` ou criar `harness_session`?** O copilot já tem doc de
  thread com `output_status`. Recomendo coleção própria (`name: 'harness_session'`)
  pra não acoplar ao chat da Studio.
- **`tool_calls` → como resolver pra connector/sub-agente.** O copilot já tem um
  catálogo `_3-available-tools` com `params_hint` e `arguments_json` (string JSON).
  Reusar esse contrato no `harness-act`.
- **Nome do comando:** `machina harness` vs `machina loop`.
- **persona_agent:** fixo no runner vs parametrizado por sessão (qual `prompt`/`schema`
  cada sessão usa pra raciocinar).

---
---

# Parte III — Cap 1 IMPLEMENTADO e verificado (dev)

> Provisionado e testado ponta-a-ponta no projeto **dev**
> (`entain-organization-sbot-dev.org.machina.gg`) em 2026-06-26. A CLI real
> (`machina loop run --watch`) cria sessão, raciocina via LLM, persiste e renderiza
> os turnos. Status: **completed**.

## O que está rodando no dev

| Recurso              | Tipo     | Papel                                                              |
| -------------------- | -------- | ----------------------------------------------------------------- |
| `loop-reasoning`     | prompt   | reasoning step; schema `{needs_tool_call, tool_calls[], assistant_message, short_message}` |
| `loop-respond`       | prompt   | síntese pós-tool (cap 5): resposta final usando `tool_result`       |
| `loop-tools`         | connector| meta-dispatcher pyscript: `dispatch(tool_name)` → calculate/get_datetime/echo |
| `loop-turn`          | workflow | `load → ingest(active) → loop-reasoning → run-tool (loop-tools) → loop-respond → finalize(idle)` |
| `loop-resume`        | workflow | beat path: acha sessão `active` órfã → responde última msg → `idle` |
| `loop-runner`        | agent    | `status:inactive`; CLI invoca via executor; roda `loop-turn`       |
| `loop-beat`          | agent    | `status:active` + `scheduled` + `config-frequency:0.5`; o beat tica; roda `loop-resume` |

Prova: `machina loop run "Reply with exactly the phrase: HARNESS LIVE" --watch`
→ `turn 1 user … / turn 1 assistant HARNESS LIVE / completed · 1 turns`.

## Contratos REST verificados (Client API, `X-Api-Token`)

| Ação                      | Verbo + path                          | Corpo / nota                                            |
| ------------------------- | ------------------------------------- | ------------------------------------------------------- |
| Criar prompt/doc/wf/agent | `POST /{prompt|document|workflow|agent}` | campos **no topo** (`name` obrigatório); não usa `data` wrapper p/ prompt/doc/agent |
| Atualizar workflow        | `PUT /workflow/{id}`                   | `{"data": {...workflow completo...}}` — **substitui** (tasks aninhados precisam do doc inteiro) |
| Deletar                   | `DELETE /{resource}/{id}`             | —                                                       |
| Executar workflow direto  | `POST /workflow/execute/{name}`       | ⚠️ corpo **FLAT** (`{input_message:…}`) — o executor já embrulha; mandar `context-workflow` causa double-nesting e os inputs não resolvem |
| Executar via agent (CLI)  | `POST /agent/executor/{name}`         | `{"context-agent": {...}, "agent-config": {"delay": true}}` — o agent **achata** o context-agent, então `$.get('input_message')` resolve nos workflows ✓ |
| Buscar sessão             | `POST /document/search`               | filtro `{"name":"harness_session","value.session_id":"…"}` (dot-notation Mongo) |

## Pegadinhas do workflow DSL (custaram iterações — anotadas)

1. **Payload do `document save` mora sob `value`**, não `content`. (`content` é a
   convenção do create REST/MCP; workflows gravam em `value`.) → CLI lê `value` via
   `_payload()`.
2. **Identidade por `value.session_id`**: a chave do mapa `documents` é o **nome
   literal** do doc (`harness_session`) — não dá nome dinâmico. O `metadata`
   top-level **não** é setado pela expressão inline; filtra-se por `value.session_id`.
3. **Nome do task `type:prompt` = nome do prompt** (`loop-reasoning`). Inputs em
   chaves numeradas (`_1-message-history`, `_2-user-message`).
4. **Modelo no dev:** `gemini-3.1-flash-lite` (vertex_ai, location `global`).
   `gemini-2.0-flash-001` **não** está disponível nesse projeto. Bloco
   `context-variables.google-genai` = `{credential: $TEMP_CONTEXT_VARIABLE_VERTEX_AI_CREDENTIAL, project_id: $TEMP_CONTEXT_VARIABLE_VERTEX_AI_PROJECT_ID}`.

## Cap 3 IMPLEMENTADO — multi-turn + `say` (dev)

Verificado: `loop run … --watch` → turno 1 (`idle`); `loop say <id> "…" --watch`
→ turno 2 que **lembra o contexto** do turno 1 (codeword/favorite-number tests).

O que mudou no `loop-turn` (sem reescrever — só novos tasks):
1. **Roteamento por existência, não por `op`.** `load-session` busca por
   `{name:'harness_session', value.session_id}`. Se existe → append; senão → create.
   `start` e `say` percorrem o mesmo caminho (start tem id novo → cria; say tem id
   existente → anexa). Elimina conditions por `op`.
2. **Histórico no prompt:** `_1-message-history` = `existing_entries` → o LLM mantém
   contexto entre turnos.
3. **`persist-new`** (`action:save`, `condition: exists is not True`) vs
   **`persist-append`** (`action:update`, `condition: exists is True`) com dict-spread
   `{**existing_value, 'entries':[*existing_entries, novo_user, novo_assistant], 'turn': next_turn, 'status':'idle'}`.
4. **Status `idle`** após responder = turno concluído, aguardando humano. `say` o
   reabre implicitamente (novo turno).

⚠️ **Corrida do `say` (resolvida client-side):** `say` é async; o `_watch` veria o
`idle` do turno anterior e pararia cedo. Fix: `_watch(min_turn=prior_turn+1)` —
só termina quando `turn` avança. `since_entries` evita re-renderizar o histórico.

## Cap 4 IMPLEMENTADO — durabilidade via beat (dev)

**Prova:** plantei uma sessão `value.status:'active'` (user sem resposta, simulando
crash pós-ingest) e **NÃO disparei nada**. O beat real resumiu sozinho em ~11–17s
→ respondeu corretamente (`Tokyo`, `ORNITHORYNQUE`, …).

### O que mudou
1. **`loop-turn` em duas fases** (escreve antes de avançar):
   `load-session` → `ingest` (append user + `status:'active'`) → `loop-reasoning` →
   `finalize` (append assistant + `status:'idle'`). Crash entre ingest e finalize
   deixa a sessão `active` ⇒ recuperável.
2. **`loop-resume`** (workflow do beat): `find-active` (`{name:'harness_session',
   value.status:'active'}`, limit 1) → raciocina sobre a **última entry do user** →
   `finalize` `idle`.
3. **DOIS agents** (decisão de design forçada — ver pegadinha):
   - `loop-runner` — `status:inactive`, não-scheduled. A CLI invoca via
     `agent/executor` (funciona em agent inativo). Roda só `loop-turn`.
   - `loop-beat` — `status:active`, `scheduled:true`, `config-frequency:0.5` (30s).
     O beat tica. Roda só `loop-resume`.

### ⚠️ Pegadinhas verificadas (cap 4)
- **`condition` no nível do workflow do agent NÃO gateou** de forma confiável: num
  tick sem `session_id`, o agent rodou `loop-turn` mesmo com
  `condition: session_id is not None`, corrompendo a sessão (entry `user` nula +
  `session_id` nulo). **Solução: separar em dois agents** (um por caminho). Não
  misturar caminho-executor e caminho-beat no mesmo agent.
- **O gate do beat é o `status:active` top-level do agent** (confirma
  [[machina-scheduler-toplevel-status]]) — `scheduled` por si não basta/não é o gate.
  Por isso `loop-runner` fica `inactive` (fora do beat) e ainda assim é invocável via
  executor; `loop-beat` fica `active` pra ser ticado.
- **Plantar sessão de teste:** `POST /document` aceita um campo `value` (convenção
  workflow) e ele fica consultável por `value.*` — útil pra semear órfãs. (O create
  REST "normal" usa `content`; workflows leem `value`.)
- Tick ocioso é no-op barato: `loop-resume` só age se achar `value.status:'active'`;
  sessões `idle` são ignoradas.

### O loop está durável de verdade
CLI offline / processo morto / tool async → a sessão fica `active` e o beat retoma.
A CLI não muda (o `_watch` já trata `active` como não-terminal e só para em `idle`).

## Cap 5 IMPLEMENTADO — tools (dev)

**Prova (pela CLI real):**
```
turn 1 user       What is the current date and time in BRT right now?
turn 1 assistant  → get_datetime({})
turn 1 tool       ← Sexta-feira, 26 de Junho de 2026, 10:59 (Horário de Brasília)
turn 1 assistant  The current date and time in BRT is Friday, June 26, 2026, 10:59 AM.
idle · 1 turns
```

### O ciclo reason → tool → respond
`loop-turn` agora: `load → ingest(active) → loop-reasoning → run-tool → loop-respond → finalize`.
- **`loop-reasoning`** recebe o catálogo em `_3-available-tools` e decide
  (`needs_tool_call` + `tool_calls[{name, arguments_json}]`).
- **`run-tool`** (`type:"connector"`, `condition: needs_tool_call`) executa o
  connector. Shape do nó: `{"type":"connector","connector":{"command":…,"name":…},"inputs":{…},"outputs":{…}}`.
  Demo usa `get_current_datetime_brt` (determinístico).
- **`loop-respond`** (novo prompt, `condition: needs_tool_call`) sintetiza a
  resposta final com o `tool_result`.
- **`finalize`** anexa entries condicionalmente: `[user] (+ [tool_call, tool_result] se tool) + [assistant]`;
  o `assistant.content` = `loop-respond` se houve tool, senão `loop-reasoning`.

### ⚠️ Limitações/pegadinhas (cap 5)
- **Dispatch dinâmico não existe em workflow puro:** `connector.name` no nó é
  **literal** (não expressão) — não dá pra executar um connector escolhido pelo LLM
  em runtime. Cap 5 **cabela uma tool**. Multi-tool / dispatch dinâmico exigiria um
  connector "meta-dispatcher" (que recebe `{name, args}` e chama o connector certo)
  — provavelmente o que o orquestrador do `copilot` faz fora do workflow. **Próximo passo.**
- **Dois invokes de prompt = dois nomes de task distintos** (`invoke_prompt`
  seleciona o prompt pelo NOME do task) → precisei do prompt extra `loop-respond`.
- **Interação com cap 4:** se um turno-com-tool morre entre `ingest` e `finalize`,
  o `loop-resume` re-raciocina do zero (re-decide a tool). OK pra tools idempotentes;
  tools com efeito colateral precisariam de dedupe por `tool_call id` (futuro).

## Cap 6 IMPLEMENTADO — multi-tool / dispatch dinâmico (dev, SEM deploy)

**Prova (pela CLI real):**
```
What is 1234 * 5678?  → calculate({"expression":"1234 * 5678"}) → ← 7006652 → "7,006,652"
Echo exactly: …       → echo({"text":"…"})                       → ← …       → "…"
Name a planet.        → (sem tool)                               → "Mars"
```
O LLM escolhe a tool em runtime, o dispatcher roteia, e a resposta usa o resultado.

**Solução:** como `connector.name` no nó é literal, um connector **meta-dispatcher**
`loop-tools` (nome estático) roteia por um argumento `tool_name` → tools internas
(`calculate`/`get_datetime`/`echo`). `run-tool` chama `loop-tools::dispatch` com
`tool_name`/`args_json` vindos de `reasoning.tool_calls[0]`. Código:
[docs/loop-tools-connector.py](docs/loop-tools-connector.py).

### ✅ Correção de um achado anterior (importante)
Eu havia concluído que "connector criado via API precisa de deploy do client-api".
**Estava errado.** Lendo o `machina-client-api` (`core/connector/executor.py`):
- `connector_script` faz `exec(connector_filecontent)` (do DB) + `eval(connector_command)`
  no call time → **connectors rodam dinâmicos do DB; não há deploy de código**.
- O que travava o `loop-tools`: `connector_execute` trata como **falha** qualquer
  retorno sem `status: True`. Meu `dispatch` retornava `{tool_result, tool_ok}` sem
  `status`. **Contrato:** retornar `{"status": True, "data": {...}}` — o `data` é
  mesclado no contexto do workflow (por isso `run-tool` lê `$.get('tool_result')`).

Ou seja: a memória [[pyscript-connector-deps-in-client-api]] vale só para as **deps**
de terceiros (essas sim no runtime); o **código** do connector é dinâmico do DB.

### Próximo (opcional)
Catálogo (`_3-available-tools`) derivado de `connector_search` = o iii-directory
(hoje é estático com 3 tools). Tool async → encaixa no modelo `waiting`/beat do cap 7.

## Cap 7 — sub-agentes (PRIMITIVO provado, orquestração async é o design)

**Objetivo:** o loop delega uma sub-tarefa a um sub-agente = uma **child session**
(`parent_session_id` → sessão-mãe), espelhando "spawns sub-agents as child sessions".

### ✅ Provado
O runner-filho `loop-subturn` roda standalone e cria uma child session linkada:
`session_id=ses_child`, `parent_session_id=ses_PARENT`, responde "Paris". Ou seja,
o **primitivo** (child session + linkagem por `parent_session_id`) funciona com os
mecanismos já dominados (`document save`).

### ⚠️ O que travou
A invocação **síncrona** do filho via o task type `workflow` (parent chamando
`loop-subturn` como sub-workflow) retornou vazio / `schedule` não-JSON — contrato do
`workflow`-task não resolvido às cegas (mesma classe do muro do cap 6; precisa de
docs/logs da plataforma). Não insisti no blind-debug.

### Design recomendado (durável, só mecanismos provados — sem sub-invocação síncrona)
1. **Spawn** (na delegação): `loop-turn` grava um **child doc** via `document save`
   — `{session_id: child, parent_session_id: parent, status:'active', entries:[{user: subtask}]}`
   — e seta a **mãe** para `status:'waiting'` (registrando `child_session_id`).
2. **Processa o filho:** o beat (`loop-resume`) já pega sessões `active` → responde.
3. **Merge de volta:** um fluxo `loop-merge` (no beat) acha mães `waiting` cujo filho
   está `idle` → anexa a resposta do filho na mãe → mãe `idle`.

Tudo isso reusa o que já existe (document save/update + beat + status como gate).
Async por natureza → encaixa no modelo durável (a mãe espera em `waiting`; o beat
costura). É a evolução natural; ficou como design pra não acumular mais DSL às cegas.

### Cap 8+ (futuro)
Factory como tool de execução de código (job sandboxed via a superfície de customers),
encaixando como uma tool async no mesmo modelo `waiting`/beat.
