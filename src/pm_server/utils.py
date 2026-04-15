"""Shared utilities for PM Server."""

from __future__ import annotations

import os
from pathlib import Path

from .models import Phase, ProjectNotFoundError, Task, TaskStatus


def _is_project_pm_dir(pm_dir: Path) -> bool:
    """Check if a .pm/ directory belongs to an actual project.

    A project .pm/ always contains project.yaml (created by pm_init).
    The global ~/.pm/ only has registry.yaml and memory.db, so it is
    excluded by this check.
    """
    return pm_dir.is_dir() and (pm_dir / "project.yaml").exists()


def resolve_project_path(project_path: str | None = None) -> Path:
    """Resolve the project root directory.

    Priority:
    1. Explicit project_path argument
    2. PM_PROJECT_PATH environment variable
    3. Walk up from cwd looking for .pm/ with project.yaml

    The cwd walk-up skips .pm/ directories without project.yaml
    (e.g. the global ~/.pm/ used for registry).
    """
    if project_path:
        p = Path(project_path).resolve()
        if not (p / ".pm").is_dir():
            raise ProjectNotFoundError(f"No .pm/ directory found at {p}. Run pm_init first.")
        return p

    if env_path := os.environ.get("PM_PROJECT_PATH"):
        p = Path(env_path).resolve()
        if (p / ".pm").is_dir():
            return p

    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if _is_project_pm_dir(parent / ".pm"):
            return parent

    raise ProjectNotFoundError(
        "No .pm/ directory found in current directory tree. "
        "Provide project_path or run pm_init first."
    )


def generate_task_id(project_name: str, number: int) -> str:
    """Generate a task ID like PROJ-001 from project name and sequence number."""
    prefix = project_name.upper().replace("-", "").replace("_", "")[:6]
    return f"{prefix}-{number:03d}"


def generate_decision_id(number: int) -> str:
    """Generate an ADR ID like ADR-001."""
    return f"ADR-{number:03d}"


def generate_risk_id(number: int) -> str:
    """Generate a risk ID like RISK-001."""
    return f"RISK-{number:03d}"


def aggregate_task_status(tasks: list[Task]) -> dict[str, int]:
    """Count tasks by status. Returns {status_value: count}."""
    counts = {s.value: 0 for s in TaskStatus}
    for t in tasks:
        counts[t.status.value] += 1
    return counts


def calculate_phase_progress(tasks: list[Task], phase: Phase) -> dict:
    """Calculate progress for a single phase."""
    phase_tasks = [t for t in tasks if t.phase == phase.id]
    done = sum(1 for t in phase_tasks if t.status == TaskStatus.DONE)
    total = len(phase_tasks)
    return {
        "id": phase.id,
        "name": phase.name,
        "status": phase.status.value,
        "done": done,
        "total": total,
        "pct": round(done / total * 100) if total > 0 else 0,
        "target_date": phase.target_date.isoformat() if phase.target_date else None,
    }
