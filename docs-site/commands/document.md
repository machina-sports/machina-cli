# document

Documents are the structured records stored in your project — threads, datasets, and any data your agents read or write.

## Usage

```bash
machina document list                  # list documents
machina document list --limit 50       # paginate
machina document list --json           # output as JSON
machina document get <id>              # get a document with a content preview
```

## Subcommands

| Command | Description |
|---------|-------------|
| `document list` | List documents in the project |
| `document get <id>` | Show a document with a content preview |
