import { defineConfig } from "vitepress"

export default defineConfig({
  title: "Machina CLI",
  description:
    "The official command-line interface for the Machina Sports AI Agent platform — manage organizations, projects, workflows, agents, skills, and Factory builds from your terminal.",
  lang: "en-US",
  cleanUrls: true,
  lastUpdated: true,
  srcExclude: ["README.md"],
  head: [
    ["link", { rel: "icon", href: "/favicon.ico" }],
    ["meta", { name: "theme-color", content: "#f4623a" }],
    ["meta", { property: "og:title", content: "Machina CLI — Docs" }],
    [
      "meta",
      {
        property: "og:description",
        content: "Drive the Machina Sports platform from your terminal — agents, workflows, skills, and Factory builds.",
      },
    ],
  ],
  themeConfig: {
    logo: {
      light: "/machina-logo-light.png",
      dark: "/machina-logo-dark.png",
    },
    siteTitle: false,
    nav: [
      { text: "Guide", link: "/guide/installation" },
      { text: "Commands", link: "/commands/login" },
      { text: "Open Studio", link: "https://studio.machina.gg/" },
    ],
    sidebar: {
      "/guide/": [
        {
          text: "Get started",
          items: [
            { text: "Introduction", link: "/" },
            { text: "Installation", link: "/guide/installation" },
            { text: "Quickstart", link: "/guide/quickstart" },
            { text: "Authentication", link: "/guide/authentication" },
          ],
        },
        {
          text: "Using the CLI",
          items: [
            { text: "Interactive REPL", link: "/guide/repl" },
            { text: "Running agents & workflows", link: "/guide/running" },
            { text: "Configuration & global flags", link: "/guide/configuration" },
          ],
        },
      ],
      "/commands/": [
        {
          text: "Platform",
          items: [
            { text: "login", link: "/commands/login" },
            { text: "org", link: "/commands/org" },
            { text: "project", link: "/commands/project" },
            { text: "credentials", link: "/commands/credentials" },
          ],
        },
        {
          text: "Resources",
          items: [
            { text: "workflow", link: "/commands/workflow" },
            { text: "agent", link: "/commands/agent" },
            { text: "connector", link: "/commands/connector" },
            { text: "mapping", link: "/commands/mapping" },
            { text: "prompt", link: "/commands/prompt" },
            { text: "document", link: "/commands/document" },
          ],
        },
        {
          text: "Operations",
          items: [
            { text: "execution", link: "/commands/execution" },
            { text: "skills", link: "/commands/skills" },
            { text: "factory", link: "/commands/factory" },
            { text: "loop", link: "/commands/loop" },
            { text: "sports", link: "/commands/sports" },
            { text: "template", link: "/commands/template" },
            { text: "deploy", link: "/commands/deploy" },
            { text: "config", link: "/commands/config" },
            { text: "update", link: "/commands/update" },
          ],
        },
      ],
    },
    socialLinks: [{ icon: "github", link: "https://github.com/machina-sports/machina-cli" }],
    footer: {
      copyright: "© 2026 Machina Sports · machina.gg",
    },
    search: { provider: "local" },
    outline: { level: [2, 3] },
  },
})
