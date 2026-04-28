"""MCP auto-installer for pm-server.

Registers (or unregisters) pm-server as an MCP server in supported hosts.

Hosts:
    - Claude Code: implemented (uses ``claude mcp add`` user scope).
    - Codex CLI: stub only — the real implementation lands in PMSERV-038
      (edits ``~/.codex/config.toml`` via tomlkit with backup + idempotency).

Public surface:
    - ``install(target="claude-code") / uninstall(target="claude-code")``:
      orchestrators that dispatch to per-host installers and isolate any
      failure into a structured ``InstallResult`` entry.
    - ``install_claude_code() / uninstall_claude_code()``: per-host
      functions returning ``InstallResult``.
    - ``install_codex() / uninstall_codex()``: no-op stubs (PMSERV-038).
    - ``install_mcp() / uninstall_mcp()``: backward-compat wrappers
      preserved from v0.4.x; return the Claude Code message string.
    - ``migrate_from_pm_agent()``: unchanged migration helper.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

# --- Result types ---------------------------------------------------------


@dataclass(frozen=True)
class InstallResult:
    """Outcome of (un)registering pm-server in a single host.

    Attributes:
        target: Host identifier (e.g. ``"claude-code"`` or ``"codex"``).
        status: One of ``"installed"``, ``"uninstalled"``,
            ``"already_registered"``, ``"skipped"``, ``"failed"``.
        message: Human-readable detail. Backward-compat-sensitive
            substrings (``"already registered"``, ``"user scope"``,
            ``"Failed to register"``) are preserved here.
        backup_path: Path to a config-file backup if the host required
            file editing. ``None`` for hosts that mutate via a CLI
            command (such as Claude Code).
    """

    target: str
    status: str
    message: str
    backup_path: str | None = None


@dataclass(frozen=True)
class InstallSummary:
    """Aggregated results across hosts processed by ``install``/``uninstall``."""

    results: list[InstallResult] = field(default_factory=list)

    @property
    def overall_status(self) -> str:
        """Aggregate status across hosts.

        Priority order:
            failed > installed > uninstalled > already_registered > skipped.
        """
        for level in ("failed", "installed", "uninstalled", "already_registered", "skipped"):
            if any(r.status == level for r in self.results):
                return level
        return "skipped"

    @property
    def message(self) -> str:
        """Joined human-readable summary across all targets."""
        if not self.results:
            return "no targets processed"
        return "\n".join(f"[{r.target}] {r.message}" for r in self.results)


# --- Host: Claude Code ----------------------------------------------------


def install_claude_code() -> InstallResult:
    """Register pm-server as a Claude Code MCP server (user scope).

    Idempotent: if ``claude mcp get pm-server`` already succeeds, the
    call short-circuits with ``status="already_registered"``.

    Returns:
        ``InstallResult`` with ``target="claude-code"``.
    """
    pm_server_path = shutil.which("pm-server")
    if pm_server_path is None:
        return InstallResult(
            target="claude-code",
            status="failed",
            message="pm-server command not found in PATH",
        )

    claude_path = shutil.which("claude")
    if claude_path is None:
        return InstallResult(
            target="claude-code",
            status="skipped",
            message="claude command not found. Install Claude Code first.",
        )

    result = subprocess.run(
        [claude_path, "mcp", "get", "pm-server"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode == 0:
        return InstallResult(
            target="claude-code",
            status="already_registered",
            message="PM Server is already registered in Claude Code",
        )

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
        return InstallResult(
            target="claude-code",
            status="installed",
            message=(
                "PM Server registered in Claude Code (user scope). Restart Claude Code to activate."
            ),
        )

    return InstallResult(
        target="claude-code",
        status="failed",
        message=f"Failed to register: {result.stderr}",
    )


def uninstall_claude_code() -> InstallResult:
    """Remove pm-server from Claude Code MCP servers (user scope).

    Returns:
        ``InstallResult`` with ``target="claude-code"``.
    """
    claude_path = shutil.which("claude")
    if claude_path is None:
        return InstallResult(
            target="claude-code",
            status="skipped",
            message="claude command not found",
        )

    result = subprocess.run(
        [claude_path, "mcp", "remove", "pm-server", "--scope", "user"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode == 0:
        return InstallResult(
            target="claude-code",
            status="uninstalled",
            message="PM Server unregistered from Claude Code",
        )

    return InstallResult(
        target="claude-code",
        status="failed",
        message="PM Server was not registered or removal failed",
    )


# --- Host: Codex CLI (stubs; real implementation in PMSERV-038) -----------


def install_codex() -> InstallResult:
    """Stub for Codex CLI installation.

    Until PMSERV-038 lands the tomlkit-based ``~/.codex/config.toml``
    editor, this returns ``status="skipped"``.
    """
    return InstallResult(
        target="codex",
        status="skipped",
        message="codex installer not yet implemented (PMSERV-038)",
    )


def uninstall_codex() -> InstallResult:
    """Stub for Codex CLI uninstall. Real impl: PMSERV-038."""
    return InstallResult(
        target="codex",
        status="skipped",
        message="codex uninstaller not yet implemented (PMSERV-038)",
    )


# --- Orchestrator ---------------------------------------------------------


_KNOWN_HOSTS: tuple[str, ...] = ("claude-code", "codex")


def _resolve_targets(target: str) -> list[str]:
    """Expand a target spec into a concrete list of host identifiers."""
    if target == "auto":
        return list(_KNOWN_HOSTS)
    if target in _KNOWN_HOSTS:
        return [target]
    valid = ("auto", *_KNOWN_HOSTS)
    raise ValueError(f"unknown target: {target!r}. Expected one of {valid}.")


def _safe_call(fn: Callable[[], InstallResult], host: str) -> InstallResult:
    """Run a host-specific installer, isolating exceptions per host.

    A failure in one host MUST NOT abort sibling hosts (ADR-007 case C).
    """
    try:
        return fn()
    except Exception as e:
        return InstallResult(
            target=host,
            status="failed",
            message=f"unexpected error: {e}",
        )


def install(target: str = "claude-code") -> InstallSummary:
    """Register pm-server with one or more host MCP clients.

    Args:
        target: ``"claude-code"`` (default), ``"codex"``, or ``"auto"``
            (run all known hosts; missing or unimplemented hosts return
            a skipped result rather than raising).

    Returns:
        ``InstallSummary`` with one ``InstallResult`` per processed host.
    """
    results: list[InstallResult] = []
    for host in _resolve_targets(target):
        if host == "claude-code":
            results.append(_safe_call(install_claude_code, host))
        elif host == "codex":
            results.append(_safe_call(install_codex, host))
    return InstallSummary(results=results)


def uninstall(target: str = "claude-code") -> InstallSummary:
    """Remove pm-server registrations from one or more host MCP clients.

    Symmetric to :func:`install`. Same target semantics.
    """
    results: list[InstallResult] = []
    for host in _resolve_targets(target):
        if host == "claude-code":
            results.append(_safe_call(uninstall_claude_code, host))
        elif host == "codex":
            results.append(_safe_call(uninstall_codex, host))
    return InstallSummary(results=results)


# --- Backward-compat wrappers (v0.4.x public API) -------------------------


def install_mcp() -> str:
    """Backward-compat wrapper kept from v0.4.x.

    Returns the human-readable message from :func:`install_claude_code`.
    The structured form is ``install(target="claude-code")`` which yields
    an :class:`InstallSummary`.
    """
    return install_claude_code().message


def uninstall_mcp() -> str:
    """Backward-compat wrapper kept from v0.4.x.

    Returns the message from :func:`uninstall_claude_code`.
    """
    return uninstall_claude_code().message


# --- pm-agent migration ---------------------------------------------------


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
