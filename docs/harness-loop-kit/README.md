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
| Tool `machina_loop` no SportsClaw (delegar via MCP) | ✅ merged (sportsclaw#113) |
| Fixes de descoberta de pod + wiring (do teste e2e) | ✅ merged (sportsclaw#114) |
| **Integração ponta a ponta validada** (ver §6) | ✅ provado |
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
machina update                      # garante v0.3.0
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
# build do SportsClaw com a tool machina_loop (já em main: #113/#114)
sportsclaw mcp add https://<org>-<projeto>.org.machina.gg/mcp/sse --name machina --token <token>
sportsclaw "Delega uma tarefa durável: pesquise o próximo jogo e me dê a análise"
#   → o LLM do SportsClaw descobre o loop e chama machina_loop {action:start} / {action:read}
```
Valida: descoberta automática do loop, delegação durável, leitura do resultado.
**Nota:** hoje funciona acionando o `loop-runner` pelo **ObjectId** (workaround
comprovado); **por nome** passa a funcionar após o redeploy do MCP (#287).

### Teste C — Provisionar o loop num pod novo *(o kit)*
`provision.py` é stdlib puro e parametrizado — sobe o loop inteiro em qualquer pod
(`--teardown` remove). Permite ao revisor rodar **testes isolados com dados reais do
projeto dele** antes de qualquer fusão de código. Passo a passo + contratos em
[`VALIDATION.md`](VALIDATION.md).

## 7. Pendências honestas (transparência)

1. **Redeploy do MCP** ([#287](https://github.com/machina-sports/machina-client-api/issues/287)):
   o fix que permite acionar agentes **por nome** via MCP está no código (merged), mas
   **nunca foi buildado/deployado** — os pods rodam imagens MCP antigas. É uma ação de
   release multi-tenant da plataforma (não bloqueia os testes acima — usamos o ObjectId).
2. **Verification / evaluator** (o ponto central do paper de Loop Engineering): hoje o
   loop **raciocina e se auto-aprova** — é um *"Nodding loop"*. Falta um **evaluator
   separado** (modelo diferente, "assume broken") + um stop condition julgado por modelo
   fresh. **Recomendação:** próximo PR. Sem isso, o loop é seguro para validar/demo, mas
   **não deve rodar sozinho em escala**.
3. **Token cap** (orçamento por turno/sessão) antes de qualquer execução não supervisionada.

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
