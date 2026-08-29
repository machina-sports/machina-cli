"""Single source of truth for the human-facing command catalog."""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Console, Group
from rich.table import Table
from rich.text import Text

from machina_cli.ui import ACCENT, MUTED


@dataclass(frozen=True)
class CommandSpec:
    name: str
    actions: tuple[str, ...]
    description: str
    usage: str | None = None

    @property
    def synopsis(self) -> str:
        if self.usage:
            return self.usage
        return f"{self.name} {'|'.join(self.actions)}" if self.actions else self.name


COMMAND_GROUPS: tuple[tuple[str, tuple[CommandSpec, ...]], ...] = (
    (
        "Platform",
        (
            CommandSpec("create", ("ai-app",), "Scaffold deployable apps"),
            CommandSpec("org", ("list", "create", "use", "usage"), "Organizations"),
            CommandSpec("project", ("list", "create", "use", "status"), "Projects"),
            CommandSpec("credentials", ("list", "generate", "revoke"), "API keys"),
            CommandSpec("auth", ("login", "logout", "whoami", "clear-session"), "Authentication"),
            CommandSpec(
                "connect", (), "Wire an agent to a project's MCP", "connect [project] [--mint]"
            ),
        ),
    ),
    (
        "Resources",
        (
            CommandSpec("workflow", ("list", "get", "run"), "Workflows"),
            CommandSpec("agent", ("list", "get", "run", "executions"), "Agents"),
            CommandSpec("connector", ("list", "get"), "Connectors"),
            CommandSpec("mapping", ("list", "get"), "Mappings"),
            CommandSpec("prompt", ("list", "get"), "Prompts"),
            CommandSpec("document", ("list", "get"), "Documents"),
        ),
    ),
    (
        "Operations",
        (
            CommandSpec("execution", ("list", "get"), "Execution history"),
            CommandSpec("approvals", ("list", "approve", "reject"), "Human approval checkpoints"),
            CommandSpec(
                "skills",
                ("list", "install", "info", "run", "push", "constructor"),
                "Skills-first surface",
            ),
            CommandSpec(
                "loop", ("run", "watch", "say", "stop", "sessions"), "Durable agentic turn loop"
            ),
            CommandSpec(
                "factory",
                (
                    "run",
                    "status",
                    "watch",
                    "logs",
                    "follow-up",
                    "cancel",
                    "open-pr",
                    "list",
                    "whoami",
                ),
                "Build apps with the coding agent",
                "factory run|status|watch|logs|list",
            ),
            CommandSpec("context-graph", ("status", "timeline"), "Self-healing and monitoring"),
            CommandSpec("sports", (), "Sports-skills passthrough", "sports <module> <command>"),
            CommandSpec("template", ("list", "install", "push"), "Template compatibility surface"),
            CommandSpec("deploy", ("start", "status", "restart"), "Deployments"),
            CommandSpec("config", ("list", "set", "get"), "Configuration"),
            CommandSpec("mcp", ("url",), "Resolve an MCP endpoint"),
        ),
    ),
)

CLI_SESSION_COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec("login", (), "Authenticate in the browser"),
    CommandSpec("update", (), "Check for and install CLI updates", "update [--check] [--force]"),
    CommandSpec("version", (), "Show CLI version"),
)

SESSION_COMMANDS: tuple[CommandSpec, ...] = (
    *CLI_SESSION_COMMANDS,
    CommandSpec("clear", (), "Clear the screen"),
    CommandSpec("exit", (), "Exit the session"),
)

ALL_COMMANDS = tuple(spec for _, specs in COMMAND_GROUPS for spec in specs)
COMMAND_BY_NAME = {spec.name: spec for spec in (*ALL_COMMANDS, *SESSION_COMMANDS)}
SUB_COMMANDS = {spec.name: list(spec.actions) for spec in ALL_COMMANDS if spec.actions}
REPL_COMMANDS = tuple(
    dict.fromkeys(
        [
            *(spec.name for spec in ALL_COMMANDS),
            *(spec.name for spec in SESSION_COMMANDS),
            "help",
            "quit",
        ]
    )
)


def command_catalog(
    *,
    include_session: bool = True,
    session_commands: tuple[CommandSpec, ...] = SESSION_COMMANDS,
) -> Group:
    """Build a responsive command list; long synopses wrap within their cell."""
    groups = list(COMMAND_GROUPS)
    if include_session:
        groups.append(("Session", session_commands))

    renderables = []
    for group_name, commands in groups:
        renderables.append(Text(group_name, style="bold underline"))
        table = Table.grid(padding=(0, 3), expand=True)
        table.add_column(style=f"bold {ACCENT}", ratio=3, min_width=24, overflow="fold")
        table.add_column(style=MUTED, ratio=2, min_width=20, overflow="fold")
        for spec in commands:
            table.add_row(Text(spec.synopsis), Text(spec.description))
        renderables.extend((table, Text()))
    return Group(*renderables)


def print_command_catalog(console: Console, *, include_session: bool = True) -> None:
    console.print(command_catalog(include_session=include_session))
    console.print(
        Text.assemble(
            ("Tip  ", f"bold {ACCENT}"),
            ("<command> --help", "bold"),
            (" shows arguments and options. Paginated lists accept ", MUTED),
            ("--limit", "bold"),
            (", ", MUTED),
            ("--page", "bold"),
            (" and ", MUTED),
            ("--json", "bold"),
            (".", MUTED),
        )
    )
