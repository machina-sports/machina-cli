"""Machina CLI — Command line interface for the Machina AI Agent platform."""

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from machina_cli import __version__
from machina_cli.commands import (
    auth, org, project, credentials, deploy, config_cmd,
    workflow, agent, template, execution, skills,
    connector, mapping, prompt, document, sports,
)
from machina_cli.commands.auth import do_login

console = Console()

CMD_GROUPS = [
    ("Platform", [
        ("login", "Authenticate"),
        ("org", "Organizations"),
        ("project", "Projects"),
        ("credentials", "API keys"),
    ]),
    ("Resources", [
        ("workflow", "Workflows"),
        ("agent", "Agents"),
        ("connector", "Connectors"),
        ("mapping", "Mappings"),
        ("prompt", "Prompts"),
        ("document", "Documents"),
    ]),
    ("Operations", [
        ("execution", "Executions"),
        ("skills", "Skills"),
        ("sports", "Sports-skills passthrough"),
        ("template", "Templates (compat)"),
        ("deploy", "Deployments"),
        ("update", "Self-update"),
    ]),
]


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
    lines = Text()
    for gi, (group_name, cmds) in enumerate(CMD_GROUPS):
        lines.append(f"{group_name}\n", style="bold underline")
        for name, desc in cmds:
            lines.append(f"  {name:<14}", style="bold #FF5C1F")
            lines.append(f"{desc}\n", style="dim")
        if gi < len(CMD_GROUPS) - 1:
            lines.append("\n")
    return Panel(
        lines,
        border_style="#FF5C1F",
        expand=False,
        padding=(1, 1),
    )


def show_banner():
    wordmark = build_wordmark()
    commands = build_commands_panel()

    layout = Table(show_header=False, show_edge=False, box=None, padding=(0, 1))
    layout.add_column(no_wrap=True)
    layout.add_column(no_wrap=True)
    layout.add_row(wordmark, commands)

    console.print()
    console.print(layout)
    console.print()
    console.print("  [dim]Run[/] [bold]machina[/] [bold magenta]<command>[/] [bold]--help[/] [dim]for more info[/]")
    console.print()


app = typer.Typer(
    name="machina",
    help="CLI for the Machina AI Agent platform",
    invoke_without_command=True,
)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    no_interactive: bool = typer.Option(False, "--no-interactive", hidden=True, help="Show banner instead of REPL"),
):
    """CLI for the Machina AI Agent platform."""
    if not ctx.invoked_subcommand:
        if no_interactive:
            show_banner()
        else:
            from machina_cli.repl import start_repl
            start_repl()


# Register sub-commands
app.add_typer(auth.app, name="auth", help="Authentication (login, logout, whoami)")
app.add_typer(org.app, name="org", help="Organization management")
app.add_typer(project.app, name="project", help="Project management")
app.add_typer(workflow.app, name="workflow", help="Workflow management")
app.add_typer(agent.app, name="agent", help="Agent management")
app.add_typer(template.app, name="template", help="Template management")
app.add_typer(skills.app, name="skills", help="Skills management")
app.add_typer(execution.app, name="execution", help="Execution management")
app.add_typer(connector.app, name="connector", help="Connector management")
app.add_typer(mapping.app, name="mapping", help="Mapping management")
app.add_typer(prompt.app, name="prompt", help="Prompt management")
app.add_typer(document.app, name="document", help="Document management")
app.add_typer(credentials.app, name="credentials", help="API key management")
app.add_typer(deploy.app, name="deploy", help="Deployment management")
app.add_typer(config_cmd.app, name="config", help="Configuration management")

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


@app.command()
def login(
    api_key: str = typer.Option(None, "--api-key", "-k", help="Authenticate with an API key"),
    with_credentials: bool = typer.Option(False, "--with-credentials", help="Use username/password instead of browser"),
    no_interactive: bool = typer.Option(False, "--no-interactive", hidden=True, help="Don't start REPL after login"),
):
    """Login to the Machina platform. Opens browser by default."""
    do_login(api_key=api_key, with_credentials=with_credentials)

    # After successful login, start the REPL so the user lands inside the CLI
    if not no_interactive:
        from machina_cli.repl import start_repl
        start_repl()


@app.command()
def update(
    force: bool = typer.Option(False, "--force", "-f", help="Force update even if already on latest"),
):
    """Update machina-cli to the latest version."""
    from machina_cli.updater import do_update
    do_update(force=force)


@app.command()
def version():
    """Show CLI version."""
    console.print(f"machina-cli v{get_version()}")


if __name__ == "__main__":
    app()
