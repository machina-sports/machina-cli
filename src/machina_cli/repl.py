"""Interactive REPL session for machina-cli.

Opens an interactive shell where commands are entered without the `machina` prefix.
Shows current org/project context in the prompt. Exit with `exit` or Ctrl+D.
"""

import readline
import shlex
import sys
import os

from rich.console import Console
from rich.text import Text

from machina_cli.config import get_config, resolve_auth_token

console = Console()

# Commands available in the REPL (maps to typer subcommands)
REPL_COMMANDS = [
    "org", "project", "workflow", "agent", "template",
    "credentials", "deploy", "config", "auth",
    "help", "exit", "quit", "clear",
]

# Sub-commands for tab completion
SUB_COMMANDS = {
    "org": ["list", "create", "use"],
    "project": ["list", "create", "use", "status"],
    "workflow": ["list", "get"],
    "agent": ["list", "get", "executions"],
    "template": ["list", "search"],
    "credentials": ["list", "generate", "revoke"],
    "deploy": ["start", "status", "restart"],
    "config": ["list", "set", "get"],
    "auth": ["login", "logout", "whoami"],
    "execution": ["get"],
}


def _completer(text, state):
    """Tab completion for REPL commands."""
    line = readline.get_line_buffer()
    parts = line.split()

    if len(parts) <= 1:
        # Complete top-level commands
        options = [c + " " for c in REPL_COMMANDS + list(SUB_COMMANDS.keys()) if c.startswith(text)]
    elif len(parts) == 2 or (len(parts) == 1 and line.endswith(" ")):
        # Complete sub-commands
        cmd = parts[0]
        sub_text = parts[1] if len(parts) > 1 else ""
        subs = SUB_COMMANDS.get(cmd, [])
        options = [s + " " for s in subs if s.startswith(sub_text)]
    else:
        options = []

    return options[state] if state < len(options) else None


def _build_prompt() -> str:
    """Build the REPL prompt string with context."""
    org_name = get_config("default_organization_name") or ""
    proj_name = get_config("default_project_name") or ""

    _, token = resolve_auth_token()
    if not token:
        return "\033[91m✦\033[0m \033[2m(not authenticated)\033[0m > "

    if org_name and proj_name:
        context = f"{org_name}/{proj_name}"
    elif org_name:
        context = org_name
    elif proj_name:
        context = proj_name
    else:
        context = "machina"

    return f"\033[91m✦\033[0m \033[1m{context}\033[0m > "


def _show_repl_banner():
    """Show the REPL welcome banner."""
    from machina_cli import __version__

    console.print()

    title = Text()
    title.append("✦ ", style="bold #FF5C1F")
    title.append("Machina CLI", style="bold")
    title.append(f" v{__version__}", style="dim")
    console.print(f"  ", end="")
    console.print(title)

    _, token = resolve_auth_token()
    if token:
        org_name = get_config("default_organization_name") or get_config("default_organization_id") or ""
        proj_name = get_config("default_project_name") or get_config("default_project_id") or ""
        if org_name:
            console.print(f"  [dim]Organization:[/dim] [bold]{org_name}[/bold]")
        if proj_name:
            console.print(f"  [dim]Project:[/dim]      [bold]{proj_name}[/bold]")
    else:
        console.print("  [yellow]Not authenticated. Type `auth login` to get started.[/yellow]")

    console.print()
    console.print("  [dim]Type a command (e.g. `workflow list`) or `help` for commands.[/dim]")
    console.print("  [dim]Press Ctrl+D or type `exit` to quit.[/dim]")
    console.print()


def _show_help():
    """Show REPL help."""
    console.print()
    console.print("  [bold]Available commands:[/bold]")
    console.print()
    cmds = [
        ("org list|create|use", "Organization management"),
        ("project list|create|use|status", "Project management"),
        ("workflow list|get <name>", "Workflow management"),
        ("agent list|get <name>|executions", "Agent management"),
        ("execution get <id>", "Get execution details"),
        ("template list|search", "Template management"),
        ("credentials list|generate|revoke", "API key management"),
        ("deploy start|status|restart", "Deployment management"),
        ("config list|set|get", "Configuration"),
        ("auth login|logout|whoami", "Authentication"),
        ("clear", "Clear screen"),
        ("exit", "Exit session"),
    ]
    for cmd, desc in cmds:
        console.print(f"    [bold #FF5C1F]{cmd:<38}[/bold #FF5C1F] [dim]{desc}[/dim]")
    console.print()


def _dispatch(line: str):
    """Dispatch a REPL command to the typer app."""
    try:
        args = shlex.split(line)
    except ValueError as e:
        console.print(f"  [red]Parse error: {e}[/red]")
        return

    if not args:
        return

    cmd = args[0].lower()

    if cmd in ("exit", "quit"):
        raise EOFError()

    if cmd == "help":
        _show_help()
        return

    if cmd == "clear":
        os.system("clear" if os.name != "nt" else "cls")
        return

    # Strip "machina" prefix if user types it out of habit
    if cmd == "machina":
        args = args[1:]
        if not args:
            return

    # Dispatch to typer — import the app and invoke programmatically
    from machina_cli.main import app as typer_app

    try:
        typer_app(args, standalone_mode=False)
    except SystemExit:
        # Swallow SystemExit so it doesn't kill the REPL
        pass
    except Exception as e:
        console.print(f"  [red]Error: {e}[/red]")


def start_repl():
    """Start the interactive REPL session."""
    # Set up readline
    readline.set_completer(_completer)
    readline.set_completer_delims(" \t")
    readline.parse_and_bind("tab: complete")

    # History
    history_file = os.path.expanduser("~/.machina/history")
    try:
        os.makedirs(os.path.dirname(history_file), exist_ok=True)
        readline.read_history_file(history_file)
    except FileNotFoundError:
        pass

    _show_repl_banner()

    try:
        while True:
            try:
                prompt = _build_prompt()
                line = input(prompt).strip()
                if line:
                    _dispatch(line)
            except KeyboardInterrupt:
                console.print()  # newline after ^C
                continue
    except EOFError:
        console.print()
        console.print("  [dim]Goodbye.[/dim]")
        console.print()
    finally:
        try:
            readline.write_history_file(history_file)
        except Exception:
            pass
