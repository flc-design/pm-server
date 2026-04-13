"""FastMCP server with all PM Server tools."""

from __future__ import annotations

import datetime as _dt
import uuid
from pathlib import Path

from fastmcp import FastMCP

from . import storage as _storage
from .discovery import detect_project_info, discover_projects
from .memory import MemoryStore
from .models import (
    Consequences,
    DailyLogEntry,
    Decision,
    LogCategory,
    Memory,
    MemoryType,
    PhaseStatus,
    Priority,
    Project,
    ProjectNotFoundError,
    ProjectStatus,
    RiskStatus,
    SessionSummary,
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

# ─── Session ID (one per server process = one per Claude Code session) ───

_current_session_id: str = (
    f"sess-{_dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
)

# ─── Memory store cache (lazy init per project) ─────

_memory_stores: dict[str, MemoryStore] = {}


def _get_memory_store(project_path: str | None) -> MemoryStore:
    """Get or create a MemoryStore for the project."""
    pm_path = _get_pm_path(project_path)
    key = str(pm_path)
    if key not in _memory_stores:
        global_db_path = _storage.GLOBAL_PM_DIR / "memory.db"
        _memory_stores[key] = MemoryStore(pm_path / "memory.db", global_db_path=global_db_path)
    return _memory_stores[key]


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

    # Ensure CLAUDE.md has PM Server rules
    from .claudemd import ensure_claudemd

    claudemd_result = ensure_claudemd(root)

    return {
        "status": "initialized",
        "path": str(root),
        "project": project.model_dump(mode="json"),
        "claudemd": claudemd_result,
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

    # CLAUDE.md status
    from .claudemd import get_claudemd_status

    root = resolve_project_path(project_path)

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
        "claudemd": get_claudemd_status(root),
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


# ─── Memory ──────────────────────────────────────────


@mcp.tool()
def pm_remember(
    content: str,
    type: str = "observation",
    task_id: str | None = None,
    decision_id: str | None = None,
    tags: str | None = None,
    project_path: str | None = None,
) -> dict:
    """Save a memory tied to the current session context.

    Memories are searchable and persist across sessions.
    Link to task_id or decision_id for structured context.
    type: observation | insight | lesson
    tags: comma-separated string (e.g. "auth,api,refactor")
    """
    store = _get_memory_store(project_path)
    pm_path = _get_pm_path(project_path)
    project = load_project(pm_path)

    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    memory = Memory(
        session_id=_current_session_id,
        type=MemoryType(type),
        content=content,
        task_id=task_id,
        decision_id=decision_id,
        tags=tag_list,
        project=project.name,
    )
    memory_id = store.save(memory)
    return {
        "status": "saved",
        "memory_id": memory_id,
        "session_id": _current_session_id,
        "type": type,
    }


@mcp.tool()
def pm_recall(
    query: str | None = None,
    task_id: str | None = None,
    type: str | None = None,
    limit: int = 5,
    cross_project: bool = False,
    project_path: str | None = None,
) -> dict:
    """Recall memories relevant to the current context.

    With no arguments: returns last session summary + recent memories.
    With query: full-text search (FTS5).
    With task_id: memories linked to that task.
    type filter: observation | insight | lesson
    cross_project: search across all projects (Phase 3).
    """
    if cross_project:
        store = _get_memory_store(project_path)
        if not query:
            return {"status": "error", "message": "query is required for cross_project search"}
        results = store.search_global(query, limit=limit)
        return {"query": query, "cross_project": True, "results": results}

    store = _get_memory_store(project_path)

    def _memory_dict(m: Memory) -> dict:
        return {
            "id": m.id,
            "type": m.type.value,
            "content": m.content,
            "task_id": m.task_id,
            "decision_id": m.decision_id,
            "tags": m.tags,
            "created_at": m.created_at,
            "session_id": m.session_id,
        }

    # Default: last session summary + recent memories
    if query is None and task_id is None:
        summary = store.get_latest_summary()
        recent = store.get_recent(limit=limit)
        if type:
            recent = [m for m in recent if m.type.value == type]
        return {
            "last_session": {
                "session_id": summary.session_id,
                "summary": summary.summary,
                "goals": summary.goals,
                "pending": summary.pending,
                "created_at": summary.created_at,
            }
            if summary
            else None,
            "recent_memories": [_memory_dict(m) for m in recent],
        }

    # Search by query
    if query:
        results = store.search(query, type=type, limit=limit)
        return {"query": query, "results": [_memory_dict(m) for m in results]}

    # Search by task_id
    if task_id:
        results = store.get_by_task(task_id)
        if type:
            results = [m for m in results if m.type.value == type]
        return {"task_id": task_id, "results": [_memory_dict(m) for m in results[:limit]]}

    return {"results": []}


@mcp.tool()
def pm_session_summary(
    action: str = "save",
    summary: str | None = None,
    goals: str | None = None,
    pending: str | None = None,
    project_path: str | None = None,
) -> dict:
    """Manage session summaries for cross-session continuity.

    action:
      - save: Store a summary for the current session (summary required)
      - get: Retrieve the most recent session summary
      - list: Show all session summaries
    """
    store = _get_memory_store(project_path)

    match action:
        case "save":
            if not summary:
                return {"status": "error", "message": "summary is required for save action"}
            pm_path = _get_pm_path(project_path)
            project = load_project(pm_path)
            pending_list = [p.strip() for p in pending.split(",") if p.strip()] if pending else []
            sess = SessionSummary(
                session_id=_current_session_id,
                summary=summary,
                goals=goals or "",
                pending=pending_list,
                project=project.name,
            )
            summary_id = store.save_session_summary(sess)
            return {
                "status": "saved",
                "summary_id": summary_id,
                "session_id": _current_session_id,
            }

        case "get":
            latest = store.get_latest_summary()
            if latest is None:
                return {"status": "empty", "message": "No session summaries found"}
            return {
                "session_id": latest.session_id,
                "summary": latest.summary,
                "goals": latest.goals,
                "tasks_done": latest.tasks_done,
                "decisions": latest.decisions,
                "pending": latest.pending,
                "created_at": latest.created_at,
            }

        case "list":
            summaries = store.list_summaries(limit=10)
            return {
                "count": len(summaries),
                "summaries": [
                    {
                        "session_id": s.session_id,
                        "summary": s.summary[:100] + ("..." if len(s.summary) > 100 else ""),
                        "created_at": s.created_at,
                    }
                    for s in summaries
                ],
            }

        case _:
            return {"status": "error", "message": f"Unknown action: {action}. Use save/get/list"}


@mcp.tool()
def pm_memory_search(
    query: str,
    type: str | None = None,
    tags: str | None = None,
    task_id: str | None = None,
    limit: int = 10,
    cross_project: bool = False,
    project_path: str | None = None,
) -> dict:
    """Advanced memory search with multiple filters.

    query: Full-text search query (required).
    type: Filter by memory type (observation | insight | lesson).
    tags: Comma-separated tags for AND filtering.
    task_id: Filter by associated task.
    cross_project: Search across all projects.
    """
    store = _get_memory_store(project_path)

    if cross_project:
        results = store.search_global(query, limit=limit)
        if tags:
            tag_set = {t.strip() for t in tags.split(",") if t.strip()}
            results = [r for r in results if tag_set.issubset(set(r.get("tags", [])))]
        return {"query": query, "cross_project": True, "results": results[:limit]}

    results = store.search(query, type=type, limit=limit * 2)

    # Apply additional filters
    if tags:
        tag_set = {t.strip() for t in tags.split(",") if t.strip()}
        results = [m for m in results if tag_set.issubset(set(m.tags))]
    if task_id:
        results = [m for m in results if m.task_id == task_id]

    def _result_dict(m: Memory) -> dict:
        return {
            "id": m.id,
            "type": m.type.value,
            "content": m.content,
            "task_id": m.task_id,
            "decision_id": m.decision_id,
            "tags": m.tags,
            "created_at": m.created_at,
            "session_id": m.session_id,
        }

    return {
        "query": query,
        "filters": {"type": type, "tags": tags, "task_id": task_id},
        "results": [_result_dict(m) for m in results[:limit]],
    }


# ─── Memory Operations ──────────────────────────────


@mcp.tool()
def pm_memory_stats(project_path: str | None = None) -> dict:
    """Show memory statistics for the current project.

    Returns total count, breakdown by type, session count,
    summary count, date range, and DB size.
    """
    store = _get_memory_store(project_path)
    stats = store.get_stats()

    # Add human-readable DB size
    size = stats["db_size_bytes"]
    if size < 1024:
        stats["db_size"] = f"{size} B"
    elif size < 1024 * 1024:
        stats["db_size"] = f"{size / 1024:.1f} KB"
    else:
        stats["db_size"] = f"{size / (1024 * 1024):.1f} MB"

    return stats


@mcp.tool()
def pm_memory_cleanup(
    older_than_days: int | None = None,
    keep_latest: int | None = None,
    session_id: str | None = None,
    dry_run: bool = True,
    project_path: str | None = None,
) -> dict:
    """Clean up old memories.

    Specify at least one criterion:
      older_than_days: Delete memories older than N days.
      keep_latest: Keep only the latest N memories, delete rest.
      session_id: Delete all memories from a specific session.

    dry_run (default True): Preview what would be deleted without deleting.
    Set dry_run=False to actually delete.
    """
    store = _get_memory_store(project_path)
    return store.cleanup(
        older_than_days=older_than_days,
        keep_latest=keep_latest,
        session_id=session_id,
        dry_run=dry_run,
    )


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
def pm_discover(scan_path: str = ".") -> dict:
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
def pm_update_claudemd(project_path: str | None = None) -> dict:
    """Update the PM Server rules section in CLAUDE.md to the latest version.

    Creates CLAUDE.md if it doesn't exist.
    Uses markers to identify and replace only the PM Server section.
    Other content in CLAUDE.md is preserved.
    """
    from .claudemd import TEMPLATE_VERSION, get_claudemd_status, update_claudemd

    root = resolve_project_path(project_path)
    before = get_claudemd_status(root)
    message = update_claudemd(root)
    after = get_claudemd_status(root)

    return {
        "status": "updated",
        "message": message,
        "template_version": TEMPLATE_VERSION,
        "before": before,
        "after": after,
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
