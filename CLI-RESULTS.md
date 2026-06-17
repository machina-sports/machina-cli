# Machina CLI Results

## 1. machina agent list < /dev/null

```text
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

## 2. machina agent get podcast-digest-agent < /dev/null

```text
╭──────────────────────── Agent: podcast-digest-agent ─────────────────────────╮
│ Title: Podcast Digest Agent                                                  │
│ Name: podcast-digest-agent                                                   │
│ Status: active  Scheduled: no  Processing: no  Frequency: N/A                │
│ ID: 69e0c2a8657cbc1eadad442b                                                 │
│ Description: Agent to discover and summarize sports podcasts from Spotify    │
│ and generate a digest.                                                       │
│ Last Execution: Thu, 16 Apr 2026 15:43:29                                    │
│ Created: Thu, 16 Apr 2026 11:06:16                                           │
╰──────────────────────────────────────────────────────────────────────────────╯
                                 Workflows (1)                                  
┏━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┓
┃ #   ┃ Name                    ┃ Description                      ┃ Condition ┃
┡━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━┩
│ 1   │ podcast-digest-workflow │ Searches for sports podcasts,    │           │
│     │                         │ fetches latest episodes, and g   │           │
└─────┴─────────────────────────┴──────────────────────────────────┴───────────┘
Context Variables
└── query: $.get('query')
```

## 3. machina agent run podcast-digest-agent query="NBA playoffs" --sync --json < /dev/null

```json

  Running agent: podcast-digest-agent
  query=NBA playoffs

{
  "agent_run_id": "69e12b176d8ef32c11d0235e",
  "digest": "",
  "query": "NBA playoffs",
  "workflow-status": "failed"
}
```

## 4. machina workflow list < /dev/null

```text
                                   Workflows                                    
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Name                              ┃ Slug ┃ Status ┃ ID                       ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ adapters-check-training           │      │ active │ 69e02c71d987fd684b85c347 │
│ adapters-dataset-annotate         │      │ active │ 69e02c70d987fd684b85c342 │
│ adapters-dataset-build            │      │ active │ 69e02c70d987fd684b85c343 │
│ adapters-dataset-checkin          │      │ active │ 69e02c70d987fd684b85c340 │
│ adapters-dataset-checkout         │      │ active │ 69e02c71d987fd684b85c346 │
│ adapters-dataset-generate         │      │ active │ 69e02c70d987fd684b85c341 │
│ adapters-dataset-train            │      │ active │ 69e02c71d987fd684b85c345 │
│ adapters-dataset-upload           │      │ active │ 69e02c70d987fd684b85c344 │
│ adapters-engine-deploy            │      │ active │ 69e02c71d987fd684b85c34a │
│ adapters-engine-deploy-status     │      │ active │ 69e02c71d987fd684b85c34b │
│ adapters-test-inference           │      │ active │ 69e02c71d987fd684b85c349 │
│ adapters-test-report              │      │ active │ 69e02c71d987fd684b85c348 │
│ assistant-chat-reasoning          │      │ active │ 69e0d89d6d8ef32c11d02354 │
│ assistant-chat-response           │      │ active │ 69e0d89d6d8ef32c11d02355 │
│ assistant-chat-update             │      │ active │ 69e0d89d6d8ef32c11d02356 │
│ assistant-market-translations-es  │      │ active │ 69e0d89d6d8ef32c11d02359 │
│ assistant-market-translations-pt… │      │ active │ 69e0d89d6d8ef32c11d02358 │
│ assistant-tools-event-matcher     │      │ active │ 69e0d89d6d8ef32c11d0234d │
│ assistant-tools-find-faq          │      │ active │ 69e0d89d6d8ef32c11d0234e │
│ assistant-tools-find-historical   │      │ active │ 69e0d89d6d8ef32c11d0234f │
└───────────────────────────────────┴──────┴────────┴──────────────────────────┘
```
