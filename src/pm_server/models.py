"""Pydantic v2 data models for PM Server."""

import datetime as _dt
from enum import StrEnum

from pydantic import BaseModel, Field

# Alias to avoid field-name collisions (e.g. Decision.date vs date type)
_Date = _dt.date


# ─── Enums ───────────────────────────────────────────


class ProjectStatus(StrEnum):
    """Project lifecycle status."""

    DESIGN = "design"
    DEVELOPMENT = "development"
    TESTING = "testing"
    MAINTENANCE = "maintenance"
    ARCHIVED = "archived"


class TaskStatus(StrEnum):
    """Task workflow status."""

    TODO = "todo"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    DONE = "done"
    BLOCKED = "blocked"


class Priority(StrEnum):
    """Task priority level."""

    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class PhaseStatus(StrEnum):
    """Phase lifecycle status."""

    PLANNED = "planned"
    ACTIVE = "active"
    COMPLETED = "completed"


class RiskSeverity(StrEnum):
    """Risk severity level."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskStatus(StrEnum):
    """Risk tracking status."""

    OPEN = "open"
    MITIGATED = "mitigated"
    CLOSED = "closed"


class DecisionStatus(StrEnum):
    """ADR decision status."""

    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    DEPRECATED = "deprecated"
    SUPERSEDED = "superseded"


class LogCategory(StrEnum):
    """Daily log entry category."""

    PROGRESS = "progress"
    DECISION = "decision"
    BLOCKER = "blocker"
    NOTE = "note"
    MILESTONE = "milestone"


class MemoryType(StrEnum):
    """Memory observation type."""

    OBSERVATION = "observation"
    INSIGHT = "insight"
    LESSON = "lesson"


# ─── Exceptions ──────────────────────────────────────


class PmServerError(Exception):
    """Base exception for PM Server."""


class ProjectNotFoundError(PmServerError):
    """No .pm/ directory found."""


class TaskNotFoundError(PmServerError):
    """Task ID does not exist."""


class DecisionNotFoundError(PmServerError):
    """Decision ID does not exist."""


# ─── Data Models ─────────────────────────────────────


class Phase(BaseModel):
    """Project phase definition."""

    id: str
    name: str
    status: PhaseStatus = PhaseStatus.PLANNED
    target_date: _Date | None = None


class ProjectHealth(BaseModel):
    """Computed project health metrics."""

    velocity: float | None = None
    blockers: int = 0
    overdue: int = 0


class Task(BaseModel):
    """A single task within a project."""

    id: str
    title: str
    phase: str
    status: TaskStatus = TaskStatus.TODO
    priority: Priority = Priority.P1
    assignee: str = "claude-code"
    estimate_hours: float | None = None
    actual_hours: float | None = None
    depends_on: list[str] = Field(default_factory=list)
    blocked_by: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    created: _Date = Field(default_factory=_dt.date.today)
    updated: _Date = Field(default_factory=_dt.date.today)
    description: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    notes: str = ""


class Consequences(BaseModel):
    """ADR consequences structure."""

    positive: list[str] = Field(default_factory=list)
    negative: list[str] = Field(default_factory=list)
    mitigations: list[str] = Field(default_factory=list)


class Decision(BaseModel):
    """Architecture Decision Record (ADR)."""

    id: str
    title: str
    date: _Date = Field(default_factory=_dt.date.today)
    status: DecisionStatus = DecisionStatus.ACCEPTED
    context: str = ""
    decision: str = ""
    consequences: Consequences = Field(default_factory=Consequences)


class Milestone(BaseModel):
    """Project milestone."""

    id: str
    name: str
    target_date: _Date | None = None
    status: PhaseStatus = PhaseStatus.PLANNED
    deliverables: list[str] = Field(default_factory=list)


class Risk(BaseModel):
    """Risk or issue tracking entry."""

    id: str
    title: str
    severity: RiskSeverity = RiskSeverity.MEDIUM
    status: RiskStatus = RiskStatus.OPEN
    description: str = ""
    mitigation: str = ""
    related_tasks: list[str] = Field(default_factory=list)
    created: _Date = Field(default_factory=_dt.date.today)


class DailyLogEntry(BaseModel):
    """Single entry in a daily log."""

    time: str  # HH:MM format
    category: LogCategory = LogCategory.PROGRESS
    entry: str = ""


class DailyLog(BaseModel):
    """A day's log entries."""

    date: _Date
    entries: list[DailyLogEntry] = Field(default_factory=list)


class Project(BaseModel):
    """Root model for project.yaml."""

    name: str
    display_name: str = ""
    version: str = "0.1.0"
    status: ProjectStatus = ProjectStatus.DEVELOPMENT
    started: _Date = Field(default_factory=_dt.date.today)
    owner: str = ""
    repository: str | None = None
    description: str = ""
    phases: list[Phase] = Field(default_factory=list)
    health: ProjectHealth = Field(default_factory=ProjectHealth)


class RegistryEntry(BaseModel):
    """Single project entry in the global registry."""

    path: str
    name: str
    registered: _Date = Field(default_factory=_dt.date.today)


class Registry(BaseModel):
    """Root model for ~/.pm/registry.yaml."""

    projects: list[RegistryEntry] = Field(default_factory=list)


# ─── Memory Layer Models ───────────���────────────


class Memory(BaseModel):
    """A single memory entry stored in SQLite."""

    id: int | None = None
    session_id: str
    type: MemoryType = MemoryType.OBSERVATION
    content: str
    task_id: str | None = None
    decision_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    created_at: str = ""
    project: str = ""


class SessionSummary(BaseModel):
    """Session summary for cross-session continuity."""

    id: int | None = None
    session_id: str
    summary: str
    goals: str = ""
    tasks_done: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    pending: list[str] = Field(default_factory=list)
    created_at: str = ""
    project: str = ""
