"""Machina CLI — Command line interface for the Machina AI Agent platform."""

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from machina_cli import __version__
from machina_cli.catalog import CLI_SESSION_COMMANDS, command_catalog
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

console = Console(highlight=False)


def get_version() -> str:
    """Get version from __version__ (works in both pip and PyInstaller builds)."""
    return __version__


def build_wordmark() -> Panel:
    title = Text()
    title.append("MACHINA\n", style="bold italic")
    title.append("✦ ", style="bold #FF5C1F")
    title.append("SPORTS", style="bold italic")

    ver = get_version()
    version = Text()
    version.append("machina-sports CLI ", style="bold")
    version.append(f"v{ver}", style="bold #3C96B4")

    subtitle = Text("AI Agent Platform", style="dim")

    content = Text()
    content.append_text(title)
    content.append("\n\n")
    content.append_text(version)
    content.append("\n")
    content.append_text(subtitle)

    return Panel(
        content,
        border_style="#FF5C1F",
        expand=False,
        padding=(1, 2),
    )


def build_commands_panel() -> Panel:
    return Panel(
        command_catalog(session_commands=CLI_SESSION_COMMANDS),
        border_style="#FF5C1F",
        expand=True,
        padding=(1, 1),
    )


def show_banner():
    wordmark = build_wordmark()
    commands = build_commands_panel()

    console.print()
    if console.width >= 110:
        layout = Table(show_header=False, show_edge=False, box=None, padding=(0, 1), expand=True)
        layout.add_column(width=34, no_wrap=True)
        layout.add_column(ratio=1)
        layout.add_row(wordmark, commands)
        console.print(layout)
    else:
        console.print(wordmark)
        console.print(commands)
    console.print()
    console.print(
        "  [dim]Run[/] [bold]machina[/] [bold magenta]<command>[/] [bold]--help[/] [dim]for more info[/]"
    )
    console.print()


app = typer.Typer(
    name="machina",
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


# Register sub-commands
app.add_typer(
    auth.app, name="auth", help="Authentication (login, logout, whoami)", rich_help_panel="Platform"
)
app.add_typer(
    create.app,
    name="create",
    help="Scaffold deployable Machina apps",
    rich_help_panel="Platform",
)
app.add_typer(org.app, name="org", help="Organization management", rich_help_panel="Platform")
app.add_typer(project.app, name="project", help="Project management", rich_help_panel="Platform")
app.add_typer(
    credentials.app,
    name="credentials",
    help="API key management",
    rich_help_panel="Platform",
)
app.add_typer(
    workflow.app, name="workflow", help="Workflow management", rich_help_panel="Resources"
)
app.add_typer(agent.app, name="agent", help="Agent management", rich_help_panel="Resources")
app.add_typer(
    connector.app, name="connector", help="Connector management", rich_help_panel="Resources"
)
app.add_typer(mapping.app, name="mapping", help="Mapping management", rich_help_panel="Resources")
app.add_typer(prompt.app, name="prompt", help="Prompt management", rich_help_panel="Resources")
app.add_typer(
    document.app, name="document", help="Document management", rich_help_panel="Resources"
)
app.add_typer(
    execution.app, name="execution", help="Execution management", rich_help_panel="Operations"
)
app.add_typer(
    approvals.app,
    name="approvals",
    help="Human approvals (workflow checkpoints)",
    rich_help_panel="Operations",
)
app.add_typer(skills.app, name="skills", help="Skills management", rich_help_panel="Operations")
app.add_typer(
    loop.app,
    name="loop",
    help="Durable agentic turn loop (harness)",
    rich_help_panel="Operations",
)
app.add_typer(
    factory.app,
    name="factory",
    help="Trigger Factory coding-agent builds",
    rich_help_panel="Operations",
)
app.add_typer(
    context_graph.app,
    name="context-graph",
    help="Self-healing / monitoring status across projects",
    rich_help_panel="Operations",
)
app.add_typer(
    template.app, name="template", help="Template management", rich_help_panel="Operations"
)
app.add_typer(deploy.app, name="deploy", help="Deployment management", rich_help_panel="Operations")
app.add_typer(
    config_cmd.app, name="config", help="Configuration management", rich_help_panel="Operations"
)
app.add_typer(
    mcp.app, name="mcp", help="Resolve MCP connection details", rich_help_panel="Operations"
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


@app.command(rich_help_panel="Session")
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


@app.command(name="connect", rich_help_panel="Platform")
def connect_command(
    project_id: str = typer.Argument(None, help="Project ID (defaults to the selected project)"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    reveal: bool = typer.Option(False, "--reveal", help="Show the auth token (masked by default)"),
    probe: bool = typer.Option(False, "--probe", help="Verify the SSE endpoint is reachable"),
    name: str = typer.Option(
        None, "--name", "-n", help="Server name for the agent (defaults to project id)"
    ),
    mint: bool = typer.Option(
        False, "--mint", help="Reuse or create a dedicated project API key for a durable connection"
    ),
    org: str = typer.Option(
        None, "--org", "-o", help="Organization ID for --mint (defaults to the selected org)"
    ),
):
    """Resolve a project's MCP connection for an external agent (e.g. sportsclaw)."""
    connect.run(project_id, json_output, reveal, probe, name, mint, org)


@app.command(rich_help_panel="Session")
def update(
    force: bool = typer.Option(
        False, "--force", "-f", help="Force update even if already on latest"
    ),
    check: bool = typer.Option(False, "--check", help="Check for updates without installing"),
):
    """Update machina-cli to the latest version."""
    from machina_cli.updater import do_update

    do_update(force=force, check=check)


@app.command(rich_help_panel="Session")
def version():
    """Show CLI version."""
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
