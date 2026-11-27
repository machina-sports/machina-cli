# Machina CLI End-to-End Test Results

## 1. `machina version < /dev/null`
```
machina-cli v0.2.23
```

## 2. `machina config list < /dev/null`
```
                                 Configuration                                  
┏━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Key                     ┃ Value                                              ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ api_url                 │ https://api.machina.gg                             │
│ client_api_url          │ https://machina-podcasts-machina-sports-podcast.o… │
│ default_organization_id │ 6876c6e319689bf880aa80b7                           │
│ default_project_id      │ 690d5c76ed71f2d5f9908108                           │
│ output_format           │ table                                              │
│ session_url             │ https://session.machina.gg                         │
└─────────────────────────┴────────────────────────────────────────────────────┘
```

## 3. `machina agent list < /dev/null`
```
                                     Agents                                     
┏━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━━┓
┃             ┃             ┃          ┃           ┃ Last        ┃             ┃
┃ Name        ┃ Title       ┃ Status   ┃ Scheduled ┃ Execution   ┃ ID          ┃
┡━━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━━┩
│ adapters-d… │ Adapters -  │ inactive │    no     │             │ 69e02c71d9… │
│             │ Dataset     │          │           │             │             │
│             │ Pipeline    │          │           │             │             │
│ agent-test… │ Agent Test  │ inactive │    no     │             │ 69e02c71d9… │
│             │ Engine      │          │           │             │             │
│ assistant-… │ Assistant - │ inactive │    no     │             │ 69e0d89d6d… │
│             │ Chat        │          │           │             │             │
│             │ Executor    │          │           │             │             │
│ machina-as… │ Machina     │ inactive │    no     │             │ 69e0d8933d… │
│             │ Assistant - │          │           │             │             │
│             │ Chat        │          │           │             │             │
│             │ Executor    │          │           │             │             │
│ meme-agent  │ Meme Agent  │ active   │    no     │             │ 69e02de00e… │
│ personaliz… │ Personaliz… │ inactive │    no     │ Mon, 09 Feb │ 690d617a13… │
│             │ Podcast     │          │           │ 2026 19     │             │
│             │ Agent       │          │           │             │             │
│ podcast-di… │ Podcast     │ active   │    no     │ Thu, 16 Apr │ 69e0c2a865… │
│             │ Digest      │          │           │ 2026 15     │             │
│             │ Agent       │          │           │             │             │
│ social-med… │ Social      │ active   │    yes    │ Tue, 14 Apr │ 694b4fe21a… │
│             │ Media       │          │           │ 2026 09     │             │
│             │ Content     │          │           │             │             │
│             │ Generator   │          │           │             │             │
└─────────────┴─────────────┴──────────┴───────────┴─────────────┴─────────────┘
```

## 4. `machina agent run podcast-digest-agent query="Brasileirao futebol" --sync --json < /dev/null`
```json

  Running agent: podcast-digest-agent
  query=Brasileirao futebol

{
  "agent_run_id": "69e10393ec1f7952e7867b37",
  "digest": "Here's a digest of sports podcasts, primarily focusing on football:\n\n### General Football Podcasts\n\n*   **Futebol no Mundo**: From ESPN Brasil, hosted by Alex Tseng, Gustavo Hofman, Leonardo Bertozzi, and Ubiratan Leal, this podcast (originally an electronic magazine) delves into international football. It covers major European leagues, global championships, alternative football, and highlights Brazilian players abroad, all presented with information and a relaxed style.\n*   **Bate-Pronto**: Produced by Jovem Pan, this program gathers expert commentators to discuss significant topics in both Brazilian and international football.\n*   **AG Placar do Brasileirão**: Hosted by Francisco Geovane and published by Arena Geral, this podcast provides a concise summary (10 minutes or less) of the previous weekend's Brasileirão matches every Tuesday.\n*   **noticias do brasileirão de futebol.**: Ramon Oliva presents this podcast, offering news and updates on the Brasileirão.\n*   **Brasileirão de Boteco**: A straightforward podcast dedicated to football, described as \"a podcast about sport that is futebol!\"\n\n### Specialized Football Podcasts\n\n*   **O Bola nas Costas**: A daily podcast from Rede Atlântida, releasing new episodes every day at 11h. It features debates on daily football news with a blend of humor, opinion, and information, embodying the spirit of \"Resenha, corneta e futebol!\"\n*   **Futebol e Ditadura**: A documentary audio series by João Malaia, this podcast investigates the Brazilian military regime (1964-1985) through the lens of football. It explores how the sport intersected with national changes, historical events, and the roles of players and clubs during that period.\n*   **Rasgando a Bola Futebol Polêmica**: This podcast focuses exclusively on football controversies, explicitly stating that it does not cover the rounds of the Brasileirão or the English league.",
  "query": "Brasileirao futebol",
  "workflow-status": true
}
```
