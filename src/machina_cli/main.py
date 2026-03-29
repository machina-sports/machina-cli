"""Machina CLI — Command line interface for the Machina AI Agent platform."""

import typer
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from machina_cli import __version__
from machina_cli.commands import auth, org, project, credentials, deploy, config_cmd
from machina_cli.commands.auth import do_login

console = Console()

CMDS = [
    ("login", "Authenticate with the platform"),
    ("org", "Organization management"),
    ("project", "Project management"),
    ("credentials", "API key management"),
    ("deploy", "Deployment management"),
    ("config", "Configuration management"),
    ("update", "Update CLI to latest version"),
]


def get_version() -> str:
    """Get version dynamically: importlib.metadata > __version__ fallback."""
    try:
        from importlib.metadata import version as pkg_version
        return pkg_version("machina-cli")
    except Exception:
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
    for i, (name, desc) in enumerate(CMDS):
        cmd = Text(f"machina {name:<14}", style="bold bright_red")
        d = Text(f" {desc}", style="dim")
        lines.append_text(cmd)
        lines.append_text(d)
        if i < len(CMDS) - 1:
            lines.append("\n")
    return Panel(
        lines,
        border_style="#FF5C1F",
        expand=False,
        padding=(1, 2),
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
def main(ctx: typer.Context):
    """CLI for the Machina AI Agent platform."""
    if not ctx.invoked_subcommand:
        show_banner()


# Register sub-commands
app.add_typer(auth.app, name="auth", help="Authentication (login, logout, whoami)")
app.add_typer(org.app, name="org", help="Organization management")
app.add_typer(project.app, name="project", help="Project management")
app.add_typer(credentials.app, name="credentials", help="API key management")
app.add_typer(deploy.app, name="deploy", help="Deployment management")
app.add_typer(config_cmd.app, name="config", help="Configuration management")


@app.command()
def login(
    api_key: str = typer.Option(None, "--api-key", "-k", help="Authenticate with an API key"),
    with_credentials: bool = typer.Option(False, "--with-credentials", help="Use username/password instead of browser"),
):
    """Login to the Machina platform. Opens browser by default."""
    do_login(api_key=api_key, with_credentials=with_credentials)


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
