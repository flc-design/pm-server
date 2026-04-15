"""CLI entry point for PM Server."""

from __future__ import annotations

import click

from . import __version__


@click.group()
@click.version_option(version=__version__, prog_name="pm-server")
def cli():
    """PM Server — Claude Code Project Management."""


@cli.command()
def install():
    """Register PM Server as an MCP server in Claude Code."""
    from .installer import install_mcp

    msg = install_mcp()
    prefix = "✗" if "not found" in msg or "Failed" in msg else "✓"
    click.echo(f"{prefix} {msg}")


@cli.command()
def uninstall():
    """Remove PM Server from Claude Code MCP servers."""
    from .installer import uninstall_mcp

    msg = uninstall_mcp()
    prefix = "✗" if "not found" in msg or "failed" in msg.lower() else "✓"
    click.echo(f"{prefix} {msg}")


@cli.command()
def serve():
    """Start the MCP server (called by Claude Code via stdio)."""
    from .server import mcp

    mcp.run(transport="stdio")


@cli.command()
@click.argument("scan_path", default=".")
def discover(scan_path: str):
    """Scan for projects and register them."""
    from pathlib import Path

    from .discovery import discover_projects
    from .storage import register_project

    found = discover_projects(Path(scan_path))
    if not found:
        click.echo("No projects with .pm/ found.")
        return

    for proj in found:
        register_project(Path(proj["path"]), proj["name"])
        click.echo(f"  ✓ {proj['name']} ({proj['path']})")

    click.echo(f"\n{len(found)} project(s) registered.")


@cli.command()
def status():
    """Show current project status."""
    from .server import pm_status
    from .utils import resolve_project_path

    try:
        resolve_project_path()
    except Exception as e:
        click.echo(f"Error: {e}")
        return

    result = pm_status()
    proj = result["project"]
    tasks = result["tasks"]

    click.echo(f"\n  {proj['display_name'] or proj['name']} ({proj['status']})")
    click.echo(
        f"  Tasks: {tasks['total']} total — "
        f"todo:{tasks.get('todo', 0)} in_progress:{tasks.get('in_progress', 0)} "
        f"done:{tasks.get('done', 0)} blocked:{tasks.get('blocked', 0)}"
    )

    if result["blockers"]:
        click.echo(f"\n  ⚠ {len(result['blockers'])} blocker(s):")
        for b in result["blockers"]:
            click.echo(f"    {b['id']}: {b['title']}")
    click.echo()


@cli.command()
def migrate():
    """pm-agent からの移行。旧 MCP 登録を解除し pm-server として再登録。"""
    from .installer import migrate_from_pm_agent

    migrate_from_pm_agent()


@cli.command("context-inject")
def context_inject_cmd():
    """Print session context to stdout for Claude Code injection.

    Outputs a context block with previous session summary,
    in-progress task memories, recent decisions, and recent memories.
    Designed for future SessionStart hook integration.
    """
    from .context import inject_context

    inject_context()


@cli.group()
def hook():
    """Manage Claude Code hooks for PM Server."""


@hook.command("post-tool-use")
def hook_post_tool_use():
    """Handle PostToolUse events (called by Claude Code)."""
    from .hooks import handle_post_tool_use

    handle_post_tool_use()


@cli.command("install-hooks")
def install_hooks_cmd():
    """Install PM Server hooks into Claude Code settings."""
    from .hooks import install_hooks

    msg = install_hooks()
    prefix = "✓" if "installed" in msg or "skipped" in msg else "✗"
    click.echo(f"{prefix} {msg}")


@cli.command("uninstall-hooks")
def uninstall_hooks_cmd():
    """Remove PM Server hooks from Claude Code settings."""
    from .hooks import uninstall_hooks

    msg = uninstall_hooks()
    prefix = "✓" if "removed" in msg or "skipped" in msg else "✗"
    click.echo(f"{prefix} {msg}")


@cli.command("update-claudemd")
@click.option("--all", "all_projects", is_flag=True, help="Update all registered projects.")
def update_claudemd_cmd(all_projects: bool):
    """Update PM Server rules in CLAUDE.md.

    Without --all: updates current project only.
    With --all: updates all registered projects.
    """
    from pathlib import Path

    from .claudemd import update_claudemd

    if all_projects:
        from .storage import load_registry

        registry = load_registry()
        if not registry.projects:
            click.echo("No registered projects found.")
            return

        for entry in registry.projects:
            root = Path(entry.path)
            if root.exists():
                result = update_claudemd(root)
                click.echo(f"  {entry.name}: {result}")
            else:
                click.echo(f"  {entry.name}: path not found (skipped)")
    else:
        from .utils import resolve_project_path

        try:
            root = resolve_project_path()
            result = update_claudemd(root)
            click.echo(f"  {result}")
        except Exception as e:
            click.echo(f"Error: {e}")


if __name__ == "__main__":
    cli()
