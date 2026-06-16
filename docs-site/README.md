# machina-cli docs

The documentation site for [`machina-cli`](https://github.com/machina-sports/machina-cli), built with [VitePress](https://vitepress.dev) — the same stack and theme as [`worldcup-api-docs`](https://github.com/machina-sports/worldcup-api-docs).

## Develop

```bash
cd docs-site
npm install
npm run dev        # local dev server with hot reload
npm run build      # static build → .vitepress/dist
npm run preview    # preview the production build
```

## Structure

```
docs-site/
├── .vitepress/
│   ├── config.mts        # site config: nav, sidebar, search, theme
│   └── theme/            # DefaultTheme + custom.css (Machina brand orange)
├── public/               # logos + favicon (served at /)
├── index.md              # home page (layout: home — hero + feature cards)
├── guide/                # Guide nav section
└── commands/             # Commands nav section (one page per command group)
```

## Add or edit a page

1. Add a Markdown file under `guide/` or `commands/` starting with an `# H1`.
2. Register it in `.vitepress/config.mts` under the matching `sidebar` group.

VitePress gives you native callouts (`::: tip`, `::: info`, `::: warning`), tables, code blocks with syntax highlighting, and a right-hand "On this page" outline for free.

## Deploy

Vercel, with the project **Root Directory** set to `docs-site/`:

- Build command: `npm run build`
- Output directory: `.vitepress/dist`

`vercel.json` already pins these. Live at **https://cli-docs.machina.gg**.
