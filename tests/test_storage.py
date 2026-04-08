"""Tests for YAML storage layer."""

import datetime as _dt

import pytest

from pm_server.models import (
    DailyLogEntry,
    LogCategory,
    Milestone,
    PmServerError,
    ProjectStatus,
    Registry,
    RegistryEntry,
    Risk,
    Task,
    TaskNotFoundError,
    TaskStatus,
)
from pm_server.storage import (
    add_daily_log,
    add_decision,
    add_milestone,
    add_risk,
    add_task,
    init_pm_directory,
    load_daily_log,
    load_decisions,
    load_milestones,
    load_project,
    load_registry,
    load_risks,
    load_tasks,
    next_decision_number,
    next_risk_number,
    next_task_number,
    register_project,
    save_milestones,
    save_project,
    save_registry,
    save_risks,
    save_tasks,
    unregister_project,
    update_task,
)


class TestProjectStorage:
    def test_save_and_load(self, tmp_pm_path, sample_project):
        save_project(tmp_pm_path, sample_project)
        loaded = load_project(tmp_pm_path)
        assert loaded.name == "testproj"
        assert loaded.version == "1.0.0"
        assert len(loaded.phases) == 2

    def test_load_missing_returns_default(self, tmp_pm_path):
        project = load_project(tmp_pm_path)
        assert project.name == tmp_pm_path.parent.name
        assert project.status == ProjectStatus.DEVELOPMENT

    def test_yaml_has_header(self, tmp_pm_path, sample_project):
        save_project(tmp_pm_path, sample_project)
        content = (tmp_pm_path / "project.yaml").read_text()
        assert content.startswith("# PM Agent - project.yaml")


class TestTaskStorage:
    def test_save_and_load(self, tmp_pm_path, sample_tasks):
        save_tasks(tmp_pm_path, sample_tasks)
        loaded = load_tasks(tmp_pm_path)
        assert len(loaded) == 4
        assert loaded[0].id == "TEST-001"

    def test_load_missing_returns_empty(self, tmp_pm_path):
        assert load_tasks(tmp_pm_path) == []

    def test_add_task(self, tmp_pm_path):
        task = Task(id="NEW-001", title="New task", phase="phase-1")
        add_task(tmp_pm_path, task)
        loaded = load_tasks(tmp_pm_path)
        assert len(loaded) == 1
        assert loaded[0].title == "New task"

    def test_update_task(self, tmp_pm_path, sample_tasks):
        save_tasks(tmp_pm_path, sample_tasks)
        updated = update_task(tmp_pm_path, "TEST-002", status=TaskStatus.IN_PROGRESS)
        assert updated.status == TaskStatus.IN_PROGRESS

        # Verify persistence
        loaded = load_tasks(tmp_pm_path)
        t = next(t for t in loaded if t.id == "TEST-002")
        assert t.status == TaskStatus.IN_PROGRESS

    def test_update_nonexistent_raises(self, tmp_pm_path, sample_tasks):
        save_tasks(tmp_pm_path, sample_tasks)
        with pytest.raises(TaskNotFoundError):
            update_task(tmp_pm_path, "NOPE-999", status=TaskStatus.DONE)

    def test_next_task_number(self, tmp_pm_path, sample_tasks):
        save_tasks(tmp_pm_path, sample_tasks)
        assert next_task_number(tmp_pm_path) == 5  # TEST-004 + 1

    def test_next_task_number_empty(self, tmp_pm_path):
        assert next_task_number(tmp_pm_path) == 1


class TestDecisionStorage:
    def test_save_and_load(self, tmp_pm_path, sample_decision):
        add_decision(tmp_pm_path, sample_decision)
        loaded = load_decisions(tmp_pm_path)
        assert len(loaded) == 1
        assert loaded[0].title == "Use YAML for storage"

    def test_load_missing_returns_empty(self, tmp_pm_path):
        assert load_decisions(tmp_pm_path) == []

    def test_next_decision_number(self, tmp_pm_path, sample_decision):
        add_decision(tmp_pm_path, sample_decision)
        assert next_decision_number(tmp_pm_path) == 2


class TestDailyLog:
    def test_add_and_load(self, tmp_pm_path):
        entry = DailyLogEntry(time="14:30", category=LogCategory.PROGRESS, entry="Did stuff")
        log = add_daily_log(tmp_pm_path, entry, log_date=_dt.date(2026, 4, 3))
        assert len(log.entries) == 1

        loaded = load_daily_log(tmp_pm_path, log_date=_dt.date(2026, 4, 3))
        assert len(loaded.entries) == 1
        assert loaded.entries[0].entry == "Did stuff"

    def test_append_to_existing_log(self, tmp_pm_path):
        d = _dt.date(2026, 4, 3)
        add_daily_log(tmp_pm_path, DailyLogEntry(time="10:00", entry="Morning"), log_date=d)
        add_daily_log(tmp_pm_path, DailyLogEntry(time="14:00", entry="Afternoon"), log_date=d)
        loaded = load_daily_log(tmp_pm_path, log_date=d)
        assert len(loaded.entries) == 2


class TestRegistry:
    def test_save_and_load(self, tmp_registry_dir):
        registry = Registry(projects=[RegistryEntry(path="/a/b", name="proj1")])
        save_registry(registry, tmp_registry_dir)
        loaded = load_registry(tmp_registry_dir)
        assert len(loaded.projects) == 1

    def test_load_missing_returns_empty(self, tmp_registry_dir):
        reg = load_registry(tmp_registry_dir)
        assert reg.projects == []

    def test_register_project(self, tmp_registry_dir, tmp_project):
        register_project(tmp_project, "myproj", tmp_registry_dir)
        reg = load_registry(tmp_registry_dir)
        assert len(reg.projects) == 1
        assert reg.projects[0].name == "myproj"

    def test_register_idempotent(self, tmp_registry_dir, tmp_project):
        register_project(tmp_project, "myproj", tmp_registry_dir)
        register_project(tmp_project, "myproj", tmp_registry_dir)
        reg = load_registry(tmp_registry_dir)
        assert len(reg.projects) == 1

    def test_unregister(self, tmp_registry_dir, tmp_project):
        register_project(tmp_project, "myproj", tmp_registry_dir)
        unregister_project(tmp_project, tmp_registry_dir)
        reg = load_registry(tmp_registry_dir)
        assert len(reg.projects) == 0


class TestInitPmDirectory:
    def test_creates_structure(self, tmp_path):
        pm_path = init_pm_directory(tmp_path)
        assert pm_path.is_dir()
        assert (pm_path / "daily").is_dir()

    def test_idempotent(self, tmp_path):
        init_pm_directory(tmp_path)
        init_pm_directory(tmp_path)
        assert (tmp_path / ".pm").is_dir()


class TestRisksAndMilestones:
    def test_risks_roundtrip(self, tmp_pm_path):
        risks = [Risk(id="RISK-001", title="Deadline risk")]
        save_risks(tmp_pm_path, risks)
        loaded = load_risks(tmp_pm_path)
        assert len(loaded) == 1
        assert loaded[0].title == "Deadline risk"

    def test_milestones_roundtrip(self, tmp_pm_path):
        milestones = [Milestone(id="MS-001", name="MVP")]
        save_milestones(tmp_pm_path, milestones)
        loaded = load_milestones(tmp_pm_path)
        assert len(loaded) == 1
        assert loaded[0].name == "MVP"

    def test_add_risk(self, tmp_pm_path):
        risk = Risk(id="RISK-001", title="Test risk")
        add_risk(tmp_pm_path, risk)
        loaded = load_risks(tmp_pm_path)
        assert len(loaded) == 1
        assert loaded[0].id == "RISK-001"

    def test_next_risk_number(self, tmp_pm_path):
        add_risk(tmp_pm_path, Risk(id="RISK-001", title="A"))
        add_risk(tmp_pm_path, Risk(id="RISK-002", title="B"))
        assert next_risk_number(tmp_pm_path) == 3

    def test_next_risk_number_empty(self, tmp_pm_path):
        assert next_risk_number(tmp_pm_path) == 1

    def test_add_milestone(self, tmp_pm_path):
        ms = Milestone(id="MS-001", name="Alpha")
        add_milestone(tmp_pm_path, ms)
        loaded = load_milestones(tmp_pm_path)
        assert len(loaded) == 1
        assert loaded[0].name == "Alpha"


class TestBrokenYaml:
    def test_broken_yaml_raises_pm_agent_error(self, tmp_pm_path):
        broken = tmp_pm_path / "project.yaml"
        broken.write_text("name: [invalid\n  yaml: {broken", encoding="utf-8")
        with pytest.raises(PmServerError, match="Failed to parse"):
            load_project(tmp_pm_path)

    def test_broken_tasks_yaml(self, tmp_pm_path):
        broken = tmp_pm_path / "tasks.yaml"
        broken.write_text("tasks:\n  - id: [bad", encoding="utf-8")
        with pytest.raises(PmServerError, match="Failed to parse"):
            load_tasks(tmp_pm_path)
