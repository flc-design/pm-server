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


if __name__ == "__main__":
    cli()
