"""Claude Code MCP auto-installer.

Registers pm-server as an MCP server via `claude mcp add` (user scope).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def install_mcp() -> str:
    """Register pm-server as a Claude Code MCP server (user scope).

    Returns a status message.
    """
    pm_server_path = shutil.which("pm-server")
    if pm_server_path is None:
        return "pm-server command not found in PATH"

    claude_path = shutil.which("claude")
    if claude_path is None:
        return "claude command not found. Install Claude Code first."

    # Check if already registered
    result = subprocess.run(
        [claude_path, "mcp", "get", "pm-server"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode == 0:
        return "PM Server is already registered in Claude Code"

    # Register via claude mcp add
    result = subprocess.run(
        [
            claude_path,
            "mcp",
            "add",
            "--transport",
            "stdio",
            "--scope",
            "user",
            "pm-server",
            "--",
            pm_server_path,
            "serve",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode == 0:
        return "PM Server registered in Claude Code (user scope). Restart Claude Code to activate."

    return f"Failed to register: {result.stderr}"


def uninstall_mcp() -> str:
    """Remove pm-server from Claude Code MCP servers.

    Returns a status message.
    """
    claude_path = shutil.which("claude")
    if claude_path is None:
        return "claude command not found"

    result = subprocess.run(
        [claude_path, "mcp", "remove", "pm-server", "--scope", "user"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode == 0:
        return "PM Server unregistered from Claude Code"

    return "PM Server was not registered or removal failed"


def migrate_from_pm_agent():
    """pm-agent から pm-server への移行。"""
    claude_path = shutil.which("claude")
    if claude_path is None:
        print("✗ 'claude' command not found. Install Claude Code first.")
        return

    # 1. 旧 pm-agent の MCP 登録を解除
    try:
        subprocess.run(
            [claude_path, "mcp", "remove", "pm-agent", "--scope", "user"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        print("✓ Old pm-agent MCP registration removed")
    except subprocess.CalledProcessError:
        print("  pm-agent was not registered (skipping)")

    # 2. 新 pm-server を登録
    install_mcp()

    # 3. registry チェック
    registry_path = Path.home() / ".pm" / "registry.yaml"
    if registry_path.exists():
        print(f"✓ Registry at {registry_path} is intact")
    else:
        print("⚠ Registry not found at ~/.pm/registry.yaml")

    # 4. CLAUDE.md 内の pm-agent 言及を警告
    if registry_path.exists():
        import yaml

        data = yaml.safe_load(registry_path.read_text()) or {}
        projects = data.get("projects", [])
        for proj in projects:
            proj_path = proj.get("path", "")
            claude_md = Path(proj_path) / "CLAUDE.md"
            if claude_md.exists():
                content = claude_md.read_text()
                content_lower = content.lower()
                has_ref = any(kw in content_lower for kw in ("pm-agent", "pm_agent", "pm agent"))
                if has_ref:
                    print(f"⚠ {claude_md} contains 'pm-agent' references — please update manually")

    print("\n✓ Migration complete. Restart Claude Code to activate.")
