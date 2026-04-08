"""FastMCP server with all PM Server tools."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

from fastmcp import FastMCP

from .discovery import detect_project_info, discover_projects
from .models import (
    Consequences,
    DailyLogEntry,
    Decision,
    LogCategory,
    PhaseStatus,
    Priority,
    Project,
    ProjectNotFoundError,
    ProjectStatus,
    RiskStatus,
    Task,
    TaskStatus,
)
from .storage import (
    add_daily_log,
    add_decision,
    add_task,
    init_pm_directory,
    load_project,
    load_registry,
    load_risks,
    load_tasks,
    next_decision_number,
    next_task_number,
    register_project,
    save_project,
    save_registry,
    update_task,
)
from .utils import (
    aggregate_task_status,
    calculate_phase_progress,
    generate_decision_id,
    generate_task_id,
    resolve_project_path,
)
from .velocity import calculate_velocity, detect_risks

mcp = FastMCP("pm-server")


# ─── Helpers ─────────────────────────────────────────


def _get_pm_path(project_path: str | None) -> Path:
    """Resolve project and return .pm/ path."""
    root = resolve_project_path(project_path)
    return root / ".pm"


def _task_summary(task: Task) -> dict:
    """Convert a Task to a concise dict for tool output."""
    return {
        "id": task.id,
        "title": task.title,
        "status": task.status.value,
        "priority": task.priority.value,
        "phase": task.phase,
        "tags": task.tags,
        "blocked_by": task.blocked_by,
    }


# ─── Project Management ─────────────────────────────


@mcp.tool()
def pm_init(project_path: str | None = None, project_name: str | None = None) -> dict:
    """Initialize PM for a project.

    Creates .pm/ directory, auto-detects project info, and registers in global registry.
    project_path defaults to current directory.
    project_name defaults to directory name or detected from config files.
    """
    root = Path(project_path).resolve() if project_path else Path.cwd().resolve()
    pm_path = init_pm_directory(root)

    # Detect project info
    info = detect_project_info(root)
    if project_name:
        info["name"] = project_name
        info["display_name"] = project_name

    # Only create project.yaml if it doesn't already exist (idempotent)
    project_yaml = pm_path / "project.yaml"
    if project_yaml.exists():
        project = load_project(pm_path)
    else:
        project = Project(
            name=info["name"],
            display_name=info.get("display_name", info["name"]),
            version=info.get("version", "0.1.0"),
            status=ProjectStatus.DEVELOPMENT,
            started=_dt.date.today(),
            repository=info.get("repository"),
            description=info.get("description", ""),
        )
        save_project(pm_path, project)

    # Register in global registry
    register_project(root, project.name)

    return {
        "status": "initialized",
        "path": str(root),
        "project": project.model_dump(mode="json"),
    }


@mcp.tool()
def pm_status(project_path: str | None = None) -> dict:
    """Get current project status.

    Returns phase progress, task counts, blockers, overdue items, and velocity.
    """
    pm_path = _get_pm_path(project_path)
    project = load_project(pm_path)
    tasks = load_tasks(pm_path)

    status_counts = aggregate_task_status(tasks)

    # Phase progress
    phase_info = []
    for phase in project.phases:
        p = calculate_phase_progress(tasks, phase)
        p["progress"] = f"{p['done']}/{p['total']}" if p["total"] > 0 else "0/0"
        p["progress_pct"] = p.pop("pct")
        phase_info.append(p)

    # Blockers
    blockers = [_task_summary(t) for t in tasks if t.status == TaskStatus.BLOCKED]

    return {
        "project": {
            "name": project.name,
            "display_name": project.display_name,
            "version": project.version,
            "status": project.status.value,
        },
        "tasks": {
            "total": len(tasks),
            **status_counts,
        },
        "phases": phase_info,
        "blockers": blockers,
        "health": project.health.model_dump(),
    }


@mcp.tool()
def pm_tasks(
    project_path: str | None = None,
    status: str | None = None,
    phase: str | None = None,
    priority: str | None = None,
    tag: str | None = None,
) -> list:
    """List tasks with optional filters.

    Filter by status (todo/in_progress/review/done/blocked),
    phase ID, priority (P0-P3), or tag.
    """
    pm_path = _get_pm_path(project_path)
    tasks = load_tasks(pm_path)

    if status:
        tasks = [t for t in tasks if t.status.value == status]
    if phase:
        tasks = [t for t in tasks if t.phase == phase]
    if priority:
        tasks = [t for t in tasks if t.priority.value == priority]
    if tag:
        tasks = [t for t in tasks if tag in t.tags]

    return [_task_summary(t) for t in tasks]


@mcp.tool()
def pm_add_task(
    title: str,
    phase: str,
    priority: str = "P1",
    description: str = "",
    project_path: str | None = None,
    depends_on: list[str] | None = None,
    tags: list[str] | None = None,
    estimate_hours: float | None = None,
    acceptance_criteria: list[str] | None = None,
) -> dict:
    """Add a new task. ID is auto-generated.

    priority: P0 (critical) | P1 (important) | P2 (nice-to-have) | P3 (someday)
    """
    pm_path = _get_pm_path(project_path)
    project = load_project(pm_path)
    number = next_task_number(pm_path)
    task_id = generate_task_id(project.name, number)

    task = Task(
        id=task_id,
        title=title,
        phase=phase,
        priority=Priority(priority),
        description=description,
        depends_on=depends_on or [],
        tags=tags or [],
        estimate_hours=estimate_hours,
        acceptance_criteria=acceptance_criteria or [],
    )
    add_task(pm_path, task)

    return {"status": "created", "task": _task_summary(task)}


@mcp.tool()
def pm_update_task(
    task_id: str,
    status: str | None = None,
    priority: str | None = None,
    actual_hours: float | None = None,
    notes: str | None = None,
    blocked_by: list[str] | None = None,
    project_path: str | None = None,
) -> dict:
    """Update a task's fields. task_id format: PREFIX-001."""
    pm_path = _get_pm_path(project_path)

    updates: dict = {}
    if status:
        updates["status"] = TaskStatus(status)
    if priority:
        updates["priority"] = Priority(priority)
    if actual_hours is not None:
        updates["actual_hours"] = actual_hours
    if notes is not None:
        updates["notes"] = notes
    if blocked_by is not None:
        updates["blocked_by"] = blocked_by

    task = update_task(pm_path, task_id, **updates)
    return {"status": "updated", "task": _task_summary(task)}


@mcp.tool()
def pm_next(project_path: str | None = None, count: int = 3) -> list:
    """Recommend next tasks based on priority, dependencies, and phase.

    Returns up to `count` actionable tasks, sorted by urgency.
    """
    pm_path = _get_pm_path(project_path)
    tasks = load_tasks(pm_path)
    project = load_project(pm_path)

    # Only actionable tasks (todo, not blocked by incomplete tasks)
    done_ids = {t.id for t in tasks if t.status == TaskStatus.DONE}
    candidates = []

    for t in tasks:
        if t.status != TaskStatus.TODO:
            continue
        # Skip tasks with explicit blockers
        if t.blocked_by:
            continue
        # Check all dependencies are done
        if t.depends_on and not all(dep in done_ids for dep in t.depends_on):
            continue
        candidates.append(t)

    # Score: P0=100, P1=75, P2=50, P3=25, active phase bonus +50
    priority_scores = {"P0": 100, "P1": 75, "P2": 50, "P3": 25}
    active_phases = {p.id for p in project.phases if p.status == PhaseStatus.ACTIVE}

    def score(task: Task) -> int:
        s = priority_scores.get(task.priority.value, 50)
        if task.phase in active_phases:
            s += 50
        return s

    candidates.sort(key=score, reverse=True)
    return [{**_task_summary(t), "score": score(t)} for t in candidates[:count]]


@mcp.tool()
def pm_blockers(project_path: str | None = None) -> list:
    """List all blocked tasks and their blockers."""
    pm_path = _get_pm_path(project_path)
    tasks = load_tasks(pm_path)
    blocked = [t for t in tasks if t.status == TaskStatus.BLOCKED]
    return [
        {
            **_task_summary(t),
            "blocked_by": t.blocked_by,
            "days_blocked": (_dt.date.today() - t.updated).days,
        }
        for t in blocked
    ]


# ─── Recording ───────────────────────────────────────


@mcp.tool()
def pm_log(
    entry: str,
    category: str = "progress",
    project_path: str | None = None,
) -> dict:
    """Add an entry to today's daily log.

    category: progress | decision | blocker | note | milestone
    """
    pm_path = _get_pm_path(project_path)
    now = _dt.datetime.now()
    log_entry = DailyLogEntry(
        time=now.strftime("%H:%M"),
        category=LogCategory(category),
        entry=entry,
    )
    log = add_daily_log(pm_path, log_entry)
    return {
        "status": "logged",
        "date": log.date.isoformat(),
        "entries_today": len(log.entries),
    }


@mcp.tool()
def pm_add_decision(
    title: str,
    context: str,
    decision: str,
    consequences_positive: list[str] | None = None,
    consequences_negative: list[str] | None = None,
    project_path: str | None = None,
) -> dict:
    """Record an Architecture Decision Record (ADR). ID is auto-generated."""
    pm_path = _get_pm_path(project_path)
    number = next_decision_number(pm_path)
    decision_id = generate_decision_id(number)

    adr = Decision(
        id=decision_id,
        title=title,
        context=context,
        decision=decision,
        consequences=Consequences(
            positive=consequences_positive or [],
            negative=consequences_negative or [],
        ),
    )
    add_decision(pm_path, adr)
    return {"status": "recorded", "decision_id": decision_id, "title": title}


# ─── Analysis ────────────────────────────────────────


@mcp.tool()
def pm_velocity(project_path: str | None = None, weeks: int = 4) -> dict:
    """Calculate velocity over the past N weeks. Includes trend analysis."""
    pm_path = _get_pm_path(project_path)
    return calculate_velocity(pm_path, weeks)


@mcp.tool()
def pm_risks(project_path: str | None = None) -> list:
    """List all risks and auto-detected issues.

    Auto-detects: blocked tasks, stale in-progress tasks, overdue estimates.
    Also includes manually registered risks.
    """
    pm_path = _get_pm_path(project_path)

    # Auto-detected risks
    auto_risks = detect_risks(pm_path)

    # Manually registered risks
    manual_risks = load_risks(pm_path)
    manual = [
        {
            "type": "manual",
            "risk_id": r.id,
            "title": r.title,
            "severity": r.severity.value,
            "status": r.status.value,
            "description": r.description,
        }
        for r in manual_risks
        if r.status == RiskStatus.OPEN
    ]

    return auto_risks + manual


# ─── Visualization ───────────────────────────────────


@mcp.tool()
def pm_dashboard(project_path: str | None = None, format: str = "html") -> str:
    """Generate a project dashboard.

    project_path specified: single project view.
    project_path=None with no .pm/ in cwd: portfolio view of all registered projects.
    format: html | text
    """
    from .dashboard import render_portfolio_dashboard, render_project_dashboard

    if format == "text":
        if project_path or _has_pm_dir():
            pm_path = _get_pm_path(project_path)
            return render_project_dashboard(pm_path, format="text")
        return render_portfolio_dashboard(format="text")

    # HTML
    if project_path or _has_pm_dir():
        pm_path = _get_pm_path(project_path)
        return render_project_dashboard(pm_path, format="html")
    return render_portfolio_dashboard(format="html")


def _has_pm_dir() -> bool:
    """Check if there's a .pm/ directory accessible from cwd."""
    try:
        resolve_project_path()
        return True
    except ProjectNotFoundError:
        return False


# ─── Discovery & Management ──────────────────────────


@mcp.tool()
def pm_discover(scan_path: str = "~") -> dict:
    """Scan for projects with .pm/ directories and register them."""
    found = discover_projects(Path(scan_path))
    newly_registered = []

    registry = load_registry()
    registered_paths = {p.path for p in registry.projects}

    for proj in found:
        if proj["path"] not in registered_paths:
            register_project(Path(proj["path"]), proj["name"])
            newly_registered.append(proj)

    return {
        "scanned": scan_path,
        "found": len(found),
        "newly_registered": len(newly_registered),
        "projects": newly_registered,
    }


@mcp.tool()
def pm_cleanup() -> dict:
    """Health-check the registry. Detect and remove invalid paths."""
    registry = load_registry()
    valid = []
    invalid = []

    for entry in registry.projects:
        pm_path = Path(entry.path) / ".pm"
        if pm_path.is_dir() and (pm_path / "project.yaml").exists():
            valid.append(entry)
        else:
            invalid.append({"path": entry.path, "name": entry.name})

    if invalid:
        registry.projects = valid
        save_registry(registry)

    return {
        "valid": len(valid),
        "removed": len(invalid),
        "invalid_entries": invalid,
    }


@mcp.tool()
def pm_list() -> list:
    """List all registered projects with summary info."""
    registry = load_registry()
    projects = []

    for entry in registry.projects:
        pm_path = Path(entry.path) / ".pm"
        info: dict = {
            "path": entry.path,
            "name": entry.name,
            "registered": entry.registered.isoformat(),
        }

        if (pm_path / "project.yaml").exists():
            project = load_project(pm_path)
            tasks = load_tasks(pm_path)
            done = sum(1 for t in tasks if t.status == TaskStatus.DONE)
            info.update(
                {
                    "display_name": project.display_name,
                    "status": project.status.value,
                    "tasks_total": len(tasks),
                    "tasks_done": done,
                    "blockers": sum(1 for t in tasks if t.status == TaskStatus.BLOCKED),
                }
            )
        else:
            info["status"] = "missing_data"

        projects.append(info)

    return projects
