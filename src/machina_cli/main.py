"""Machina CLI — Command line interface for the Machina AI Agent platform."""

import typer
from rich.text import Text
from typer.core import TyperGroup

from machina_cli import __version__, brand
from machina_cli.catalog import PANEL_BY_COMMAND, print_command_catalog
from machina_cli.commands import (
    agent,
    approvals,
    auth,
    config_cmd,
    connect,
    connector,
    context_graph,
    create,
    credentials,
    deploy,
    document,
    execution,
    factory,
    loop,
    mapping,
    mcp,
    org,
    project,
    prompt,
    skills,
    sports,
    template,
    workflow,
)
from machina_cli.commands.auth import do_login
from machina_cli.theme import INK, MUTED, console


def get_version() -> str:
    """Get version from __version__ (works in both pip and PyInstaller builds)."""
    return __version__


def show_banner():
    """The first thing anyone sees: the mark, where you are, what you can run."""
    console.print()
    console.print(brand.lockup(console.width or 100))
    console.print()

    meta = Text("  ")
    meta.append("AI Agent Platform", style=MUTED)
    meta.append("   ")
    meta.append(f"v{get_version()}", style=INK)
    console.print(meta)
    console.print()

    print_command_catalog(console)
    console.print()


class MachinaGroup(TyperGroup):
    """Give the root exactly one help surface.

    Typer orders its ``--help`` panels by where a command happens to be
    registered -- top-level commands first, then groups -- which no amount of
    reordering can bend into the catalog's order, because no top-level command
    lives in `Resources`. So the root renders the catalog itself and the two
    screens are the same screen. Sub-groups keep Typer's own rich help, which
    is where the actions and flags belong.
    """

    def format_help(self, ctx, formatter):
        show_banner()


app = typer.Typer(
    name="machina",
    cls=MachinaGroup,
    help="CLI for the Machina AI Agent platform",
    invoke_without_command=True,
)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    no_interactive: bool = typer.Option(
        False, "--no-interactive", hidden=True, help="Show banner instead of REPL"
    ),
):
    """CLI for the Machina AI Agent platform."""
    if not ctx.invoked_subcommand:
        if no_interactive:
            show_banner()
        else:
            from machina_cli.repl import start_repl

            start_repl()


def _panel(name: str) -> str:
    """The help panel a command belongs to, straight from the catalog.

    Registration order below follows ``catalog.PANEL_ORDER`` so that Typer's
    ``--help`` lists its panels in the same order the banner does. The two
    screens used to carry independent groupings and disagreed about it.
    """
    return PANEL_BY_COMMAND[name]


# --- Session ---------------------------------------------------------------
app.add_typer(auth.app, name="auth", help="Identity and sign-out", rich_help_panel=_panel("auth"))
app.add_typer(
    org.app, name="org", help="Organizations and consumption", rich_help_panel=_panel("org")
)
app.add_typer(
    project.app,
    name="project",
    help="Projects and the active context",
    rich_help_panel=_panel("project"),
)
app.add_typer(
    config_cmd.app, name="config", help="CLI configuration", rich_help_panel=_panel("config")
)

# --- Resources -------------------------------------------------------------
app.add_typer(workflow.app, name="workflow", help="Workflows", rich_help_panel=_panel("workflow"))
app.add_typer(
    agent.app, name="agent", help="Agents and their executions", rich_help_panel=_panel("agent")
)
app.add_typer(
    connector.app, name="connector", help="Connectors", rich_help_panel=_panel("connector")
)
app.add_typer(mapping.app, name="mapping", help="Mappings", rich_help_panel=_panel("mapping"))
app.add_typer(prompt.app, name="prompt", help="Prompts", rich_help_panel=_panel("prompt"))
app.add_typer(document.app, name="document", help="Documents", rich_help_panel=_panel("document"))

# --- Run & watch -----------------------------------------------------------
app.add_typer(
    execution.app,
    name="execution",
    help="Execution history and outcomes",
    rich_help_panel=_panel("execution"),
)
app.add_typer(
    approvals.app,
    name="approvals",
    help="Human approval checkpoints",
    rich_help_panel=_panel("approvals"),
)
app.add_typer(
    loop.app, name="loop", help="Durable agentic turn loop", rich_help_panel=_panel("loop")
)
app.add_typer(deploy.app, name="deploy", help="Deployments", rich_help_panel=_panel("deploy"))
app.add_typer(
    context_graph.app,
    name="context-graph",
    help="Self-healing, drift and health",
    rich_help_panel=_panel("context-graph"),
)

# --- Build -----------------------------------------------------------------
app.add_typer(
    create.app, name="create", help="Scaffold a deployable app", rich_help_panel=_panel("create")
)
app.add_typer(
    factory.app,
    name="factory",
    help="Build with the coding agent",
    rich_help_panel=_panel("factory"),
)
app.add_typer(
    skills.app,
    name="skills",
    help="Install, run and publish skills",
    rich_help_panel=_panel("skills"),
)
app.add_typer(
    template.app,
    name="template",
    help="Legacy alias for skills",
    rich_help_panel=_panel("template"),
)

# --- Connect ---------------------------------------------------------------
app.add_typer(mcp.app, name="mcp", help="Inspect an MCP endpoint", rich_help_panel=_panel("mcp"))
app.add_typer(
    credentials.app, name="credentials", help="API keys", rich_help_panel=_panel("credentials")
)

# Mount the sports-skills CLI dynamically under `machina sports …`.
sports.register(app)


@app.command(hidden=True)
def shell_prompt():
    """Output current session info for shell prompt integration.

    Add to your .zshrc / .bashrc:
        export MACHINA_PROMPT=$(machina shell-prompt 2>/dev/null)

    Or for dynamic prompt (slower, runs each time):
        machina_prompt() { machina shell-prompt 2>/dev/null; }
        PROMPT='$(machina_prompt) %~ %# '
    """
    from machina_cli.config import get_config, resolve_auth_token

    _, token = resolve_auth_token()
    if not token:
        return

    org_name = get_config("default_organization_name") or ""
    proj_name = get_config("default_project_name") or ""

    if org_name and proj_name:
        print(f"✦ {org_name}/{proj_name}")
    elif org_name:
        print(f"✦ {org_name}")
    elif proj_name:
        print(f"✦ {proj_name}")
    else:
        print("✦ machina")


@app.command(rich_help_panel=PANEL_BY_COMMAND["login"])
def login(
    api_key: str = typer.Option(None, "--api-key", "-k", help="Authenticate with an API key"),
    with_credentials: bool = typer.Option(
        False, "--with-credentials", help="Use username/password instead of browser"
    ),
    no_interactive: bool = typer.Option(
        False, "--no-interactive", hidden=True, help="Don't start REPL after login"
    ),
):
    """Login to the Machina platform. Opens browser by default."""
    do_login(api_key=api_key, with_credentials=with_credentials)

    # After successful login, start the REPL so the user lands inside the CLI
    if not no_interactive:
        from machina_cli.repl import start_repl

        start_repl()


@app.command(name="connect", rich_help_panel=PANEL_BY_COMMAND["connect"])
def connect_command(
    project_id: str = typer.Argument(None, help="Project ID (defaults to the selected project)"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    reveal: bool = typer.Option(False, "--reveal", help="Show the auth token (masked by default)"),
    probe: bool = typer.Option(
        False, "--probe", help="Verify readiness: MCP handshake, tools/list and a health_check read"
    ),
    name: str = typer.Option(
        None, "--name", "-n", help="Server name for the agent (defaults to project id)"
    ),
    mint: bool = typer.Option(
        False, "--mint", help="Reuse or create a dedicated project API key for a durable connection"
    ),
    org: str = typer.Option(
        None, "--org", "-o", help="Organization ID for --mint (defaults to the selected org)"
    ),
    timeout: float = typer.Option(15.0, "--timeout", help="Probe timeout in seconds"),
):
    """Resolve a project's MCP connection for an external agent (e.g. sportsclaw)."""
    connect.run(project_id, json_output, reveal, probe, name, mint, org, timeout)


@app.command(rich_help_panel=PANEL_BY_COMMAND["update"])
def update(
    force: bool = typer.Option(
        False, "--force", "-f", help="Force update even if already on latest"
    ),
    check: bool = typer.Option(False, "--check", help="Check for updates without installing"),
):
    """Update machina-cli to the latest version."""
    from machina_cli.updater import do_update

    do_update(force=force, check=check)


@app.command(rich_help_panel=PANEL_BY_COMMAND["version"])
def version(
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Show CLI version."""
    if json_output:
        from machina_cli.ui import emit_json

        emit_json({"name": "machina-cli", "version": get_version()})
        return
    console.print(f"machina-cli v{get_version()}")


def run():
    """Real entrypoint for both the pip console-script and the PyInstaller
    binary (which freezes this file and runs it as __main__ -- see
    if __name__ == "__main__" below). Click/Typer's standalone_mode raises
    SystemExit from app() on every path (success, error, --help), so the
    update check needs `finally`, not code placed after a plain call."""
    try:
        app()
    finally:
        from machina_cli.update_check import maybe_notify_update

        maybe_notify_update()


if __name__ == "__main__":
    run()
