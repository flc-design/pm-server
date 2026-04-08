"""Tests for dashboard generation."""

from unittest.mock import patch

import pytest

from pm_server.dashboard import (
    render_portfolio_dashboard,
    render_project_dashboard,
)
from pm_server.models import (
    Registry,
    RegistryEntry,
)
from pm_server.storage import (
    init_pm_directory,
    save_project,
    save_tasks,
)


@pytest.fixture
def dashboard_project(tmp_path, sample_project, sample_tasks):
    """Create a project with enough data for dashboard rendering."""
    pm_path = init_pm_directory(tmp_path)
    save_project(pm_path, sample_project)
    save_tasks(pm_path, sample_tasks)
    return pm_path


class TestProjectDashboard:
    def test_html_output(self, dashboard_project):
        html = render_project_dashboard(dashboard_project, format="html")
        assert "<!DOCTYPE html>" in html
        assert "Test Project" in html
        assert "Chart" in html

    def test_text_output(self, dashboard_project):
        text = render_project_dashboard(dashboard_project, format="text")
        assert "Test Project" in text
        assert "TODO:" in text or "Todo:" in text or "todo" in text.lower()

    def test_text_shows_blockers(self, dashboard_project):
        text = render_project_dashboard(dashboard_project, format="text")
        assert "TEST-004" in text or "Blocker" in text or "blocked" in text.lower()

    def test_text_shows_velocity(self, dashboard_project):
        text = render_project_dashboard(dashboard_project, format="text")
        assert "Velocity" in text or "velocity" in text


class TestPortfolioDashboard:
    def test_html_empty(self):
        with patch("pm_server.dashboard.load_registry") as mock_reg:
            mock_reg.return_value = Registry()
            html = render_portfolio_dashboard(format="html")
            assert "<!DOCTYPE html>" in html
            assert "pm_init" in html

    def test_text_empty(self):
        with patch("pm_server.dashboard.load_registry") as mock_reg:
            mock_reg.return_value = Registry()
            text = render_portfolio_dashboard(format="text")
            assert "Portfolio" in text
            assert "0 projects" in text

    def test_text_with_projects(self, tmp_path, sample_project, sample_tasks):
        pm_path = init_pm_directory(tmp_path)
        save_project(pm_path, sample_project)
        save_tasks(pm_path, sample_tasks)

        with patch("pm_server.dashboard.load_registry") as mock_reg:
            mock_reg.return_value = Registry(
                projects=[RegistryEntry(path=str(tmp_path), name="testproj")]
            )
            text = render_portfolio_dashboard(format="text")
            assert "Test Project" in text
