"""Tests for project discovery and info detection."""

import json

from pm_server.discovery import detect_project_info, discover_projects


class TestDetectProjectInfo:
    def test_bare_directory(self, tmp_path):
        info = detect_project_info(tmp_path)
        assert info["name"] == tmp_path.name
        assert info["version"] == "0.1.0"

    def test_pyproject_toml(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "my-pkg"\nversion = "2.0.0"\ndescription = "A package"\n'
        )
        info = detect_project_info(tmp_path)
        assert info["name"] == "my-pkg"
        assert info["version"] == "2.0.0"
        assert info["description"] == "A package"

    def test_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text(
            json.dumps({"name": "my-app", "version": "3.1.0", "description": "A JS app"})
        )
        info = detect_project_info(tmp_path)
        assert info["name"] == "my-app"
        assert info["version"] == "3.1.0"

    def test_cargo_toml(self, tmp_path):
        (tmp_path / "Cargo.toml").write_bytes(b'[package]\nname = "rvim"\nversion = "0.2.0"\n')
        info = detect_project_info(tmp_path)
        assert info["name"] == "rvim"
        assert info["version"] == "0.2.0"

    def test_readme_fallback(self, tmp_path):
        (tmp_path / "README.md").write_text(
            "# My Project\n\nThis is a longer description of the project.\n"
        )
        info = detect_project_info(tmp_path)
        assert "longer description" in info["description"]

    def test_display_name_generated(self, tmp_path):
        info = detect_project_info(tmp_path)
        # tmp directories have random names, just check it's set
        assert info["display_name"]


class TestDiscoverProjects:
    def test_finds_projects(self, tmp_path):
        # Create two projects
        for name in ["proj-a", "proj-b"]:
            p = tmp_path / name / ".pm"
            p.mkdir(parents=True)
            (p / "project.yaml").write_text("name: " + name)

        found = discover_projects(tmp_path)
        assert len(found) == 2
        names = {f["name"] for f in found}
        assert "proj-a" in names
        assert "proj-b" in names

    def test_skips_without_project_yaml(self, tmp_path):
        (tmp_path / "bad" / ".pm").mkdir(parents=True)
        # No project.yaml
        found = discover_projects(tmp_path)
        assert len(found) == 0

    def test_empty_directory(self, tmp_path):
        found = discover_projects(tmp_path)
        assert found == []

    def test_nonexistent_path(self, tmp_path):
        found = discover_projects(tmp_path / "nope")
        assert found == []
