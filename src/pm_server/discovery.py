"""Project auto-detection and information inference."""

from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path


def detect_project_info(project_path: Path) -> dict:
    """Detect project metadata from common config files.

    Checks Cargo.toml, package.json, pyproject.toml, git remote, and README.md
    to infer project name, version, description, and repository URL.
    """
    info: dict = {
        "name": project_path.name,
        "display_name": project_path.name.replace("-", " ").replace("_", " ").title(),
        "version": "0.1.0",
        "repository": None,
        "description": "",
    }

    # Cargo.toml (Rust)
    cargo_toml = project_path / "Cargo.toml"
    if cargo_toml.exists():
        try:
            with open(cargo_toml, "rb") as f:
                cargo = tomllib.load(f)
            pkg = cargo.get("package", cargo.get("workspace", {}).get("package", {}))
            if pkg:
                info["name"] = pkg.get("name", info["name"])
                info["version"] = pkg.get("version", info["version"])
                info["description"] = pkg.get("description", "") or ""
        except Exception:
            pass

    # package.json (Node.js)
    pkg_json = project_path / "package.json"
    if pkg_json.exists():
        try:
            pkg = json.loads(pkg_json.read_text(encoding="utf-8"))
            info["name"] = pkg.get("name", info["name"])
            info["version"] = pkg.get("version", info["version"])
            info["description"] = pkg.get("description", "") or ""
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

    # pyproject.toml (Python)
    pyproject = project_path / "pyproject.toml"
    if pyproject.exists():
        try:
            with open(pyproject, "rb") as f:
                pyp = tomllib.load(f)
            proj = pyp.get("project", {})
            if proj:
                info["name"] = proj.get("name", info["name"])
                info["version"] = proj.get("version", info["version"])
                info["description"] = proj.get("description", "") or ""
        except Exception:
            pass

    # Git remote URL
    try:
        result = subprocess.run(
            ["git", "-C", str(project_path), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            info["repository"] = result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # README.md fallback for description
    readme = project_path / "README.md"
    if readme.exists() and not info["description"]:
        try:
            lines = readme.read_text(encoding="utf-8").splitlines()
            for line in lines:
                stripped = line.strip().lstrip("# ").strip()
                if stripped and not stripped.startswith("!") and len(stripped) > 10:
                    info["description"] = stripped[:200]
                    break
        except UnicodeDecodeError:
            pass

    return info


def discover_projects(scan_path: Path) -> list[dict]:
    """Recursively scan for projects with .pm/ directories."""
    found: list[dict] = []
    scan_path = scan_path.expanduser().resolve()

    if not scan_path.is_dir():
        return found

    for pm_dir in scan_path.rglob(".pm"):
        if pm_dir.is_dir() and (pm_dir / "project.yaml").exists():
            project_path = pm_dir.parent
            found.append({"path": str(project_path), "name": project_path.name})

    return found
