# Harness Loop + Integração SportsClaw — Handoff

> Resumo do que foi construído, o que está validado, e **como rodar testes reais**.
> Para revisão técnica profunda: [`VALIDATION.md`](VALIDATION.md) e
> [`../agentic-harness-loop.md`](../agentic-harness-loop.md).

---

## 1. O que é (em uma frase)

Construímos o **Harness Loop**: um *loop agêntico durável* que roda **dentro da
Machina** (sobre agents/workflows/connectors/documents + o beat), e o integramos ao
**SportsClaw** via MCP — de modo que o SportsClaw possa **delegar tarefas longas e
resumíveis** ao loop. É a aplicação prática do conceito de **Loop Engineering** (a 4ª
camada acima de prompt → context → harness): *projetar o sistema que faz o agente
rodar sozinho, repetidamente*.

## 2. Por que importa (estratégia)

- **Unificação do stack** — CLI, MCP, SportsClaw e Sports Skills passam a falar a
  mesma língua. O SportsClaw vira o ponto de entrada; o loop vira uma capacidade
  durável que ele aciona. Menos superfícies, onboarding mais fluido.
- **Funil open-source → premium** — a base de Sports Skills alimenta o SportsClaw,
  que delega ao loop na plataforma (tokens premium). A jornada fica contínua.
- **Moat B2B** — o loop durável (estado no pod, retomada via beat, multi-agente sem
  duplicar dados) é exatamente o tipo de robustez que o B2B exige e o B2C não entrega.

## 3. Arquitetura (as duas peças se encaixam invertidas)

```
   SportsClaw  (agente EFÊMERO, MCP-client)            Harness Loop  (DURÁVEL, no pod)
   ─────────────────────────────────────              ──────────────────────────────
   LLM próprio + Sports Skills + entrega   ──MCP──▶    loop-runner / loop-turn
   delega tarefa durável via `machina_loop`            ├─ persiste cada turno (documents)
                                            ◀── resultado ┤─ retoma via beat (loop-beat)
                                                        └─ tools (calculate, fixtures, …)
```

- **SportsClaw** roda o loop dele (rápido, por query/tick) e, para trabalho longo
  ou resumível, **chama o `machina_loop`** (tool nova) que aciona o loop durável no pod.
- **Harness Loop** vive no pod: cada turno é salvo como documento `harness_session`;
  se algo interrompe, o **beat retoma**. É o que sobrevive a crash / tool async / espera.

## 4. Status — o que está pronto

| Item | Estado |
| --- | --- |
| `machina loop` na CLI (caps 1–6) + release **v0.3.0** | ✅ merged (machina-cli#23) |
| Kit de provisionamento + doc técnica | ✅ merged (machina-cli#24) |
| Tool `machina_loop` no SportsClaw (delegar via MCP) | ✅ merged (sportsclaw#113, #114, #115) |
| Fixes do teste real: gpt-5.5/Azure via `/responses`, router, erros honestos | ✅ merged (sportsclaw#116) |
| **Loop validado AO VIVO pela CLI** — cálculo + fixtures reais | ✅ testado na máquina |
| **Cap 8 — verificação:** evaluator independente + gate determinístico + budget | ✅ construído e validado ao vivo (staging) |
| SportsClaw + gpt-5.5 (Azure) **dispara o `machina_loop`** | ✅ validado |
| Round-trip completo via SportsClaw (por nome) | ⏳ depende do redeploy do MCP (#287) |
| Redeploy do MCP server da pod (productização) | ⏳ [machina-client-api#287](https://github.com/machina-sports/machina-client-api/issues/287) |

## 5. O que JÁ funciona — prova real

Rodamos o round-trip completo contra um pod de staging com dados reais:

```
SportsClaw → MCP execute_agent → loop-runner → loop-turn → tool calculate → resposta
  user      : Quanto é 6*7?
  assistant : → calculate {"expression": "6*7"}
  tool      : ← 42
  assistant : O resultado de 6 multiplicado por 7 é 42.
```

E direto pela CLI, com **dados reais de futebol** (docs `sportradar-fixture` do pod):

```
$ machina loop run "Quais os próximos 2 jogos? Liste com horário." --watch
  → find_fixtures({"limit": 2})
  ← Senegal vs Iraq (16:00) … + análise pré-jogo
  Os próximos 2 jogos são: 1. Senegal vs Iraq às 16:00 ; 2. …
```

## 6. Testes reais — como validar (3 caminhos)

> **Pré-requisito comum:** um pod Machina (URL do Client API + um `X-Api-Token` do
> projeto) com credenciais Vertex AI no runtime. Tokens **não** vão neste doc — peço
> em separado / use os do ambiente de teste.

### Teste A — Loop sozinho, pela CLI *(mais simples)*
```bash
machina update                      # garante v0.4.1 (verificação + auto-reparo)
# 1) provisiona o loop no pod (idempotente):
CLIENT_API_URL="https://<org>-<projeto>.org.machina.gg" API_TOKEN="<token>" \
  python3 docs/harness-loop-kit/provision.py
# 2) aponta a CLI no pod e roda:
machina config set client_api_url https://<org>-<projeto>.org.machina.gg
export MACHINA_API_KEY=<token>
machina loop run "Quanto é 1234 * 5678?" --watch          # tool calculate
machina loop run "Quais os próximos jogos?" --watch       # dados reais (se houver fixtures)
machina loop say <session_id> "E o próximo da França?" --watch   # multi-turno c/ contexto
```
Valida: turno único, multi-turno com contexto, uso de tool, persistência.

### Teste B — SportsClaw → Loop, via MCP *(a integração)*
```bash
# build do SportsClaw (tool machina_loop já em main: #113–#116)
sportsclaw mcp add https://<org>-<projeto>.org.machina.gg/mcp/sse --name machina --token <token>
sportsclaw "Delega uma tarefa durável: pesquise o próximo jogo e me dê a análise"
#   → o LLM do SportsClaw descobre o loop e chama machina_loop {action:start} / {action:read}
```
Valida: descoberta automática do loop, delegação durável, leitura do resultado.
**Validado** com **gpt-5.5** (Azure AI Foundry, via `/responses`): o SportsClaw raciocina
e chama o `machina_loop`. O **round-trip completa** após o redeploy do MCP (#287) — o MCP
antigo da pod só aceita por **ObjectId** (acionar por nome → 500).

### Teste C — Provisionar o loop num pod novo *(o kit)*
`provision.py` é stdlib puro e parametrizado — sobe o loop inteiro em qualquer pod
(`--teardown` remove). Permite ao revisor rodar **testes isolados com dados reais do
projeto dele** antes de qualquer fusão de código. Passo a passo + contratos em
[`VALIDATION.md`](VALIDATION.md).

### Teste D — Verificação (Cap 8) + auto-reparo (Cap 8.2) *(o "chão")*
Todo turno passa por um **gate determinístico** + um **evaluator independente** antes de
finalizar `idle`. O `--watch` mostra o veredito:
```bash
machina loop run "Quanto é 1234 * 5678?" --watch
#   idle · 1 turns
#   ✓ verified (evaluator: gemini-3.1-flash-lite)

machina loop run "Quanto é 10 / 0?" --watch        # a tool erra → o gate fecha
#   needs_review · 1 turns
#   ⚠ needs review — ...                            # checkpoint humano, nunca um pass silencioso
```
- **Prod:** aponte `EVAL_MODEL` pra um modelo **mais forte que o gerador**
  (`EVAL_MODEL="<modelo>" … python3 provision.py`) — avaliador do mesmo modelo é leniente.
- **Auto-reparo (Cap 8.2):** quando o evaluator reprova uma resposta que passou no gate, o
  loop **conserta 1x** e re-verifica (a CLI mostra `· self-repaired`). Receita determinística
  pra forçar e ver isso em [`VALIDATION.md`](VALIDATION.md) §D.

Valida: gate fail-closed, `needs_review` (checkpoint humano), auto-reparo. Scorecard
completo + resultados ao vivo: [`PLAYBOOK-SCORECARD.md`](PLAYBOOK-SCORECARD.md).

### Teste E — Operator-sync (SportsClaw) *(o loop como 2ª lente)*
O operator daemon do SportsClaw pode rotear cada decisão publicada pro loop durável
(verificação independente). Liga por job em `~/.sportsclaw/operator/<jobId>.json`:
```json
{ "jobId": "studio", "intervalMs": 90000, "operatorSync": { "enabled": true } }
```
Precisa de ≥2 ticks (start-now / read-next-tick) e do pod do loop conectado
(`sportsclaw mcp add <pod>/mcp/sse --token <token>`). Detalhes + como testar:
SportsClaw `docs/advanced/operator.md` (§Operator-sync). *Mesmo gate do #287 no dispatch.*

## 6.5 Context Graph — `context-verify` (a aplicação real)

O mesmo padrão **gerador/avaliador** aplicado a **dados**, não a Q&A: audita **arestas de
contexto** — *está esse dado atribuído à entidade certa?* — e grava um documento
**`context_graph_health`** por aresta (consultável), não um script descartável.

```bash
CLIENT_API_URL="https://<org>-<projeto>.org.machina.gg" API_TOKEN="<token>" \
  python3 docs/harness-loop-kit/context-verify.py --run
```

Provisiona um **connector** (2 scanners determinísticos), um **prompt** avaliador
edge-agnóstico (camada semântica), **2 workflows** e um **agent** que roda todas as auditorias.
Roda 100% server-side no pod (não depende do MCP / #287). **Medido ao vivo (staging):**

| Aresta | Coleção | Resultado |
| --- | --- | --- |
| `análise↔fixture` | `sportradar-fixture.pre_match_research` ([#705](https://github.com/machina-sports/entain-templates/issues/705)) | **13%** quebradas (26/200) |
| `odd↔market↔fixture` | `entain-markets-tier3` | **0%** (consistente, 65) |
| `market→fixture` (linkabilidade) | markets PT ↔ fixtures EN | det. liga **2%**; **semântico recupera ~metade** do resto |

O verificador **localiza onde o contexto quebra** (cobertura), atesta onde não quebra (odds), e
na aresta de **linkabilidade prova por que a camada de LLM é necessária**: um join determinístico
liga só 2% das odds aos jogos (nomes PT vs EN, sem id comum), e o passo semântico recupera as
traduções que ele perde (`Austrália vs Egito` → `Australia vs Egypt`). É o v0 do **Context Graph**.
Próximas arestas (mesmo motor): `stat↔player↔match`, `narrativa↔evento`.

**Self-healing + self-evolving.** A aresta de linkabilidade não só mede — o passo semântico
**resolve e grava a tabela de ids de volta** (docs `context_graph_links`:
`bwin_fixture_id → sport_event_id`, ex.: `2:7826050 → sr:sport_event:53452503` =
`Austrália vs Egito → Australia vs Egypt`). É o **join bwin↔sportradar que não existia**, curado
pelo LLM e persistido pra a montagem de contexto do cliente consumir. O agent
**`context-verify-beat`** (agendado, **inativo por padrão**) roda o sweep contínuo → o grafo se
**cura e evolui sozinho**. É o self-repair do harness loop (Cap 8.2) aplicado aos **dados**:
detect → heal → **resolve ids** → persist → repeat. *(Conservador: só links que resolvem a ids
reais são gravados — o resto fica como órfão.)*

## 7. Pendências honestas (transparência)

1. **Redeploy do MCP** ([#287](https://github.com/machina-sports/machina-client-api/issues/287)):
   o fix que permite acionar agentes **por nome** via MCP está no código (merged), mas
   **nunca foi buildado/deployado** — os pods rodam imagens MCP antigas. É uma ação de
   release multi-tenant da plataforma (não bloqueia os testes acima — usamos o ObjectId).
2. **Verification / evaluator** ✅ **feito (Cap 7).** O loop agora tem um **evaluator
   independente** (`loop-evaluate`, contexto fresco + postura "assume broken", `EVAL_MODEL`)
   + um **gate determinístico**; qualquer falha → `needs_review` (checkpoint humano, nunca
   um "pass" silencioso). Validado ao vivo — ver
   [`PLAYBOOK-SCORECARD.md`](PLAYBOOK-SCORECARD.md). *Restam:* apontar `EVAL_MODEL` para um
   modelo **mais forte que o gerador** em produção (evaluator do mesmo modelo é leniente) e
   um **token cap** por turno antes de rodar 100% sozinho.
3. **Token cap** (orçamento por turno/sessão) antes de qualquer execução não supervisionada
   — já existe o budget de tentativas do resume (`LOOP_MAX_ATTEMPTS`); falta o teto de *tokens*.
4. **Dado de enrichment (a montante — não é do loop):** o teste real expôs `pre_match_research`
   atribuído ao **fixture errado** em vários jogos (cada batch herda a análise do 1º fixture).
   Bug no pipeline de cobertura, registrado em
   [entain-templates#705](https://github.com/machina-sports/entain-templates/issues/705). O loop
   relatou fielmente os docs — e por isso expôs o problema.

## 8. Próximos passos sugeridos

- **Plataforma:** executar o redeploy do MCP (#287) → desbloqueia o `machina_loop` por nome.
- **Fase 2 (faseado, como combinado):** *operator-sync* — rotear as decisões do operator
  daemon do SportsClaw para o loop (heartbeat → beat). É também a casa natural do
  **evaluator** (o operator do SportsClaw já tem os broadcast-safety validators).

---

### Referências
- Conceito: *Loop Engineering — The Anthropic Playbook* (Osmani/Steinberger/Cherny).
- Arquitetura e build capítulo a capítulo: [`../agentic-harness-loop.md`](../agentic-harness-loop.md).
- PRs: machina-cli#23, #24 · sportsclaw#113, #114 · client-api#287.
