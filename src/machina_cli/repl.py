"""Interactive REPL session for machina-cli.

Opens an interactive shell where commands are entered without the `machina` prefix.
Shows current org/project context in the prompt. Exit with `exit` or Ctrl+D.
"""

import readline
import shlex
import os

from rich.console import Console
from rich.text import Text

from machina_cli.config import get_config, resolve_auth_token

console = Console()

# Commands available in the REPL (maps to typer subcommands)
REPL_COMMANDS = [
    "org", "project", "workflow", "agent", "connector",
    "mapping", "prompt", "document", "skills", "template", "execution",
    "credentials", "deploy", "config", "auth",
    "help", "exit", "quit", "clear",
]

# Sub-commands for tab completion
SUB_COMMANDS = {
    "org": ["list", "create", "use"],
    "project": ["list", "create", "use", "status"],
    "workflow": ["list", "get", "run"],
    "agent": ["list", "get", "run", "executions"],
    "connector": ["list", "get"],
    "mapping": ["list", "get"],
    "prompt": ["list", "get"],
    "document": ["list", "get"],
    "skills": ["list", "install", "info", "run", "push"],
    "template": ["list", "install", "push"],
    "execution": ["get", "list"],
    "credentials": ["list", "generate", "revoke"],
    "deploy": ["start", "status", "restart"],
    "config": ["list", "set", "get"],
    "auth": ["login", "logout", "whoami"],
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
    console.print("  ", end="")
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
    groups = [
        ("Platform", [
            ("org list|create|use", "Organizations"),
            ("project list|create|use|status", "Projects"),
            ("credentials list|generate|revoke", "API keys"),
            ("auth login|logout|whoami", "Authentication"),
        ]),
        ("Resources", [
            ("workflow list|get|run <name>", "Workflows"),
            ("agent list|get|run <name>", "Agents"),
            ("connector list|get <name>", "Connectors"),
            ("mapping list|get <name>", "Mappings"),
            ("prompt list|get <name>", "Prompts"),
            ("document list|get <id>", "Documents"),
        ]),
        ("Operations", [
            ("execution list|get <id>", "Execution history"),
            ("skills list|install|info|run|push", "Skills-first surface"),
            ("template list|install|push", "Template compatibility surface"),
            ("deploy start|status|restart", "Deployments"),
            ("config list|set|get", "Configuration"),
        ]),
        ("Session", [
            ("clear", "Clear screen"),
            ("exit", "Exit session"),
        ]),
    ]
    console.print()
    for group_name, cmds in groups:
        console.print(f"  [bold underline]{group_name}[/bold underline]")
        for cmd, desc in cmds:
            console.print(f"    [bold #FF5C1F]{cmd:<38}[/bold #FF5C1F] [dim]{desc}[/dim]")
        console.print()
    console.print("  [dim]All list commands support:[/dim] --limit N  --page N  --json")
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

    if cmd in ("help", "--help", "-h"):
        _show_help()
        return

    if cmd == "clear":
        os.system("clear" if os.name != "nt" else "cls")
        return

    # Shortcuts — common commands that users expect to work directly
    SHORTCUTS = {
        "logout": ["auth", "logout"],
        "whoami": ["auth", "whoami"],
        "login": ["auth", "login"],
    }
    if cmd in SHORTCUTS:
        args = SHORTCUTS[cmd] + args[1:]

    # Strip "machina" prefix if user types it out of habit
    if cmd == "machina":
        args = args[1:]
        if not args:
            return

    # Auto-fix bare flags: "limit 50" → "--limit 50", "json" → "--json", etc.
    # This lets users type `workflow list limit 50` instead of `workflow list --limit 50`
    # Only apply AFTER the subcommand (first 2 args are command + subcommand)
    KNOWN_FLAGS = {
        "limit", "page", "json", "compact", "sync", "watch",
        "show-keys", "copy", "repo", "branch", "private", "force",
        "api-key", "with-credentials", "username", "password",
        "slug", "level",
    }
    # Find where flags start (skip command words like "project list", "workflow get")
    flag_start = min(2, len(args))
    fixed_args = list(args[:flag_start])
    for arg in args[flag_start:]:
        if arg.lower() in KNOWN_FLAGS and not arg.startswith("-"):
            fixed_args.append(f"--{arg.lower()}")
        else:
            fixed_args.append(arg)
    args = fixed_args

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
