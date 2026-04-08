"""Dashboard generation — HTML (Jinja2 + Chart.js) and text fallback for PM Server."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import TaskStatus
from .storage import (
    load_decisions,
    load_project,
    load_registry,
    load_risks,
    load_tasks,
)
from .utils import aggregate_task_status, calculate_phase_progress
from .velocity import calculate_velocity, detect_risks

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _get_jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )


# ─── Single Project Dashboard ────────────────────────


def render_project_dashboard(pm_path: Path, format: str = "html") -> str:
    """Render a single project dashboard."""
    project = load_project(pm_path)
    tasks = load_tasks(pm_path)
    decisions = load_decisions(pm_path)
    risks_manual = load_risks(pm_path)
    velocity = calculate_velocity(pm_path)
    auto_risks = detect_risks(pm_path)

    status_counts = aggregate_task_status(tasks)

    # Phase progress
    phases = []
    for phase in project.phases:
        p = calculate_phase_progress(tasks, phase)
        p["target_date"] = p["target_date"] or "—"
        phases.append(p)

    # Blocked tasks
    blocked = [t for t in tasks if t.status == TaskStatus.BLOCKED]

    context = {
        "project": project,
        "tasks": tasks,
        "status_counts": status_counts,
        "phases": phases,
        "blocked": blocked,
        "decisions": decisions,
        "velocity": velocity,
        "risks": auto_risks
        + [
            {"type": "manual", "title": r.title, "severity": r.severity.value} for r in risks_manual
        ],
        "today": date.today().isoformat(),
    }

    if format == "text":
        return _render_project_text(context)

    env = _get_jinja_env()
    template = env.get_template("dashboard_single.html")
    return template.render(**context)


def _render_project_text(ctx: dict) -> str:
    """Plain-text dashboard for a single project."""
    project = ctx["project"]
    sc = ctx["status_counts"]
    lines = [
        f"{'=' * 50}",
        f"  {project.display_name or project.name}",
        f"  Status: {project.status.value} | v{project.version}",
        f"{'=' * 50}",
        "",
        "Tasks:",
        f"  TODO: {sc.get('todo', 0)}  |  In Progress: {sc.get('in_progress', 0)}  |  "
        f"Review: {sc.get('review', 0)}  |  Done: {sc.get('done', 0)}  |  "
        f"Blocked: {sc.get('blocked', 0)}",
        "",
    ]

    if ctx["phases"]:
        lines.append("Phases:")
        for p in ctx["phases"]:
            bar_len = 20
            filled = round(p["pct"] / 100 * bar_len)
            bar = "█" * filled + "░" * (bar_len - filled)
            lines.append(f"  [{bar}] {p['pct']:3d}% {p['name']} ({p['done']}/{p['total']})")
        lines.append("")

    if ctx["blocked"]:
        lines.append("Blockers:")
        for t in ctx["blocked"]:
            lines.append(f"  ! {t.id}: {t.title} (blocked by: {', '.join(t.blocked_by) or '?'})")
        lines.append("")

    vel = ctx["velocity"]
    lines.append(f"Velocity: {vel['average']} tasks/week ({vel['trend']})")

    if ctx["risks"]:
        lines.append("")
        lines.append("Risks:")
        for r in ctx["risks"]:
            lines.append(f"  [{r.get('severity', 'medium')}] {r['title']}")

    return "\n".join(lines)


# ─── Portfolio Dashboard ─────────────────────────────


def render_portfolio_dashboard(format: str = "html") -> str:
    """Render a portfolio dashboard across all registered projects."""
    registry = load_registry()
    projects_data = []

    for entry in registry.projects:
        pm_path = Path(entry.path) / ".pm"
        if not (pm_path / "project.yaml").exists():
            continue

        project = load_project(pm_path)
        tasks = load_tasks(pm_path)
        done = sum(1 for t in tasks if t.status == TaskStatus.DONE)
        blocked = sum(1 for t in tasks if t.status == TaskStatus.BLOCKED)
        total = len(tasks)

        projects_data.append(
            {
                "name": project.name,
                "display_name": project.display_name or project.name,
                "status": project.status.value,
                "path": entry.path,
                "tasks_total": total,
                "tasks_done": done,
                "tasks_blocked": blocked,
                "progress_pct": round(done / total * 100) if total > 0 else 0,
            }
        )

    context = {
        "projects": projects_data,
        "total_projects": len(projects_data),
        "today": date.today().isoformat(),
    }

    if format == "text":
        return _render_portfolio_text(context)

    env = _get_jinja_env()
    template = env.get_template("dashboard_portfolio.html")
    return template.render(**context)


def _render_portfolio_text(ctx: dict) -> str:
    """Plain-text portfolio dashboard."""
    lines = [
        f"{'=' * 60}",
        f"  PM Server — Portfolio Dashboard ({ctx['today']})",
        f"  {ctx['total_projects']} projects registered",
        f"{'=' * 60}",
        "",
    ]

    if not ctx["projects"]:
        lines.append("  No projects registered. Run pm_init to get started.")
        return "\n".join(lines)

    # Header
    lines.append(f"  {'Project':<25} {'Status':<14} {'Progress':<12} {'Blocked':>7}")
    lines.append(f"  {'─' * 25} {'─' * 14} {'─' * 12} {'─' * 7}")

    for p in ctx["projects"]:
        name = (p["display_name"] or p["name"])[:24]
        prog = f"{p['tasks_done']}/{p['tasks_total']}"
        lines.append(f"  {name:<25} {p['status']:<14} {prog:<12} {p['tasks_blocked']:>7}")

    return "\n".join(lines)
