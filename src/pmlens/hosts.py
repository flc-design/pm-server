"""Host descriptor table — the single place that knows what a "host" is.

PM Lens supports several AI coding hosts. Before PMSERV-165 each host's
identity was spread across six unsynchronised literals (``utils._KNOWN_HOSTS``,
``utils.TARGET_CHOICES``, ``rules.TARGET_FILES``, ``rules.get_rules_status``'s
hardcoded keys, ``rules.detect_hosts``'s probe ladder, ``__main__._TARGET_CHOICES``)
plus two ``if/elif`` dispatch chains in ``installer`` **with no ``else``** — so a
half-added host produced zero results, no error, and an ``overall_status`` of
``"skipped"``. ADR-007 predicted a third host would just mean "add another
``install_<host>()``"; at four hosts that is six hand-edits per host and a silent
failure mode. Everything now derives from :data:`HOSTS`.

Supported hosts and the facts that differ between them:

===============  ==============  =====================  ==================
host_id          rule file       MCP registration       pmlens hook?
===============  ==============  =====================  ==================
``claude-code``  ``CLAUDE.md``   ``claude mcp add``     yes (SessionStart)
``codex``        ``AGENTS.md``   ``~/.codex/config.toml``  no
``cursor``       ``AGENTS.md``   ``~/.cursor/mcp.json``    no
``grok``         ``AGENTS.md``   ``~/.grok/config.toml``   no
===============  ==============  =====================  ==================

**Three hosts share ``AGENTS.md``.** Rule injection therefore deduplicates by
rule file, not by host — see ``rules.inject_pm_rules``. Order matters: the
first host in :data:`HOSTS` that claims a file is the one reported as having
written it, which is why ``codex`` must stay ahead of ``cursor`` and ``grok``.

**Grok Build reads CLAUDE.md too.** Verified against the docs Grok Build ships
locally (``~/.grok/docs/user-guide/12-project-rules.md``): it scans
``Agents.md``, ``Claude.md``, ``CLAUDE.md``, ``CLAUDE.local.md``, ``AGENT.md``
and ``AGENTS.md``, and "loads every matching file in a directory" — so a repo
carrying both files feeds Grok the PM rules **twice**. Neither file can be
dropped (Claude Code and Codex each need their own), so this is surfaced as a
warning rather than fixed; see :func:`hosts_reading_both_rule_files`.

**Grok Build and Cursor both have session hooks**, but pmlens does not install
one for them — only Claude Code gets a pmlens-installed SessionStart hook
(``hooks.py``). :attr:`HostSpec.pm_hook_support` records that distinction,
because the ADR-028 rule the rule template states ("hosts without a hook must
re-derive the git branch themselves and pass it to ``pm_recall(track=…)``")
keys on *whether pmlens installs a hook*, not on whether the host has hooks.

**Not added, deliberately.** VS Code (``.vscode/mcp.json`` uses a ``servers``
key, not ``mcpServers``, and needs a ``type`` field — a real transform, and its
AGENTS.md support sits behind an opt-in setting); Gemini CLI (must merge into a
shared ``settings.json`` plus a ``context.fileName`` opt-in); the xAI remote-MCP
API (HTTP/SSE only, connected from xAI's infrastructure — pmlens is a local
stdio server over a local ``.pm/`` and SQLite, so exposing it would mean
shipping local project data off the machine).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

#: Every host id pmlens can target. Kept as a Literal so a half-added host is a
#: type error; ``test_host_id_literal_matches_registry`` guards the inverse.
HostId = Literal["claude-code", "codex", "cursor", "grok"]

#: How a host's MCP registration is performed.
#:
#: ``"cli"``   — shell out to the host's own CLI (Claude Code).
#: ``"toml"``  — field-level tomlkit edits to ``[mcp_servers.pmlens]``.
#: ``"json"``  — field-level edits to ``{"mcpServers": {"pmlens": …}}``.
RegistrationKind = Literal["cli", "toml", "json"]


def _codex_config_file() -> Path:
    return Path.home() / ".codex" / "config.toml"


def _cursor_config_file() -> Path:
    return Path.home() / ".cursor" / "mcp.json"


def _grok_config_file() -> Path:
    return Path.home() / ".grok" / "config.toml"


@dataclass(frozen=True)
class HostSpec:
    """Everything that differs between one supported host and another.

    Attributes:
        host_id: Hyphenated identifier used by every ``target=`` argument.
        display_name: Human-facing name used in messages.
        status_key: Underscored form used as a key in
            ``rules.get_rules_status`` output. Separate from ``host_id``
            because that dict shape is a locked API surface — deriving the
            key from ``host_id`` would rename ``claude_code`` to
            ``claude-code`` and break existing consumers.
        rule_file: Basename of the project rule file this host reads.
            Several hosts legitimately share one.
        registration: How MCP registration is performed.
        config_file: The file registration edits, or ``None`` for
            ``registration="cli"``. Lazy so a monkeypatched ``HOME`` is
            honoured by test fixtures.
        install_marker: Path whose existence means "this host is installed
            here", or ``None`` when no such path is a reliable signal. For
            file-registered hosts this is usually the config file itself;
            Cursor is the exception — its ``mcp.json`` may legitimately not
            exist yet on an otherwise-installed Cursor, so the marker is the
            ``~/.cursor`` directory. Claude Code deliberately has **no**
            marker: ``~/.claude`` exists on machines that merely once ran it,
            and several other tools now write there, so PATH + the
            ``CLAUDECODE`` env var remain its only signals (unchanged from
            PMSERV-044).
        config_label: Display form of ``config_file`` for messages
            (``~``-relative, so messages do not leak a home directory).
        mcp_key: Top-level key holding server definitions —
            ``mcp_servers`` (TOML hosts) or ``mcpServers`` (JSON hosts).
        pm_hook_support: True when pmlens installs a session-start hook for
            this host. False does NOT mean the host lacks hooks (Cursor and
            Grok Build both have them) — it means the ADR-028 "re-derive the
            branch yourself" rule applies.
        also_reads_claude_md: True when this host reads ``CLAUDE.md`` in
            addition to its own ``rule_file``, which can duplicate the
            injected rules.
        probe_binaries: Executable names whose presence on PATH is positive
            evidence the host is installed. Probed with ``shutil.which`` only
            — never executed, because detection is reachable from read-only
            MCP tools (RO invariant, ADR-028).

            Only Claude Code uses this, and deliberately so: it is the one
            host with no config path pmlens can look for. The file-registered
            hosts are detected by their config file alone. Adding a PATH probe
            for them would be *less* precise, not more — Grok Build installs
            ``~/.grok/bin/agent`` as a second symlink to its own binary, so a
            probe for ``agent`` reports Grok as some other host; and a `codex`
            or `cursor-agent` on PATH says nothing about whether that host has
            ever been configured on this machine.
    """

    host_id: HostId
    display_name: str
    status_key: str
    rule_file: str
    registration: RegistrationKind
    config_file: Callable[[], Path] | None
    install_marker: Callable[[], Path] | None
    config_label: str
    mcp_key: str
    pm_hook_support: bool
    also_reads_claude_md: bool = False
    probe_binaries: tuple[str, ...] = ()


#: Registry of supported hosts, keyed by ``host_id``.
#:
#: **Insertion order is load-bearing** and is the order orchestrators dispatch
#: in, the CLI prints in, and rule-file deduplication resolves ties in. Keep
#: ``claude-code`` first (it owns ``CLAUDE.md``) and ``codex`` second (it owns
#: ``AGENTS.md``, which ``cursor`` and ``grok`` then share).
HOSTS: dict[str, HostSpec] = {
    "claude-code": HostSpec(
        host_id="claude-code",
        display_name="Claude Code",
        status_key="claude_code",
        rule_file="CLAUDE.md",
        registration="cli",
        config_file=None,
        install_marker=None,
        config_label="`claude mcp add` (user scope)",
        mcp_key="mcpServers",
        pm_hook_support=True,
        probe_binaries=("claude",),
    ),
    "codex": HostSpec(
        host_id="codex",
        display_name="Codex",
        status_key="codex",
        rule_file="AGENTS.md",
        registration="toml",
        config_file=_codex_config_file,
        install_marker=_codex_config_file,
        config_label="~/.codex/config.toml",
        mcp_key="mcp_servers",
        pm_hook_support=False,
    ),
    "cursor": HostSpec(
        host_id="cursor",
        display_name="Cursor",
        status_key="cursor",
        rule_file="AGENTS.md",
        registration="json",
        config_file=_cursor_config_file,
        # The directory, not the file: a freshly installed Cursor has
        # ~/.cursor but no mcp.json until something writes one, and an
        # existing mcp.json can legitimately be an empty (0-byte) file.
        install_marker=lambda: Path.home() / ".cursor",
        config_label="~/.cursor/mcp.json",
        mcp_key="mcpServers",
        pm_hook_support=False,
    ),
    "grok": HostSpec(
        host_id="grok",
        display_name="Grok Build",
        status_key="grok",
        rule_file="AGENTS.md",
        registration="toml",
        config_file=_grok_config_file,
        install_marker=_grok_config_file,
        config_label="~/.grok/config.toml",
        mcp_key="mcp_servers",
        pm_hook_support=False,
        also_reads_claude_md=True,
    ),
}


def rule_files() -> dict[str, str]:
    """``{host_id: rule_file}`` — the shape ``rules.TARGET_FILES`` exposes."""
    return {host_id: spec.rule_file for host_id, spec in HOSTS.items()}


def hosts_for_rule_file(rule_file: str) -> list[str]:
    """Host ids that read ``rule_file``, in registry order."""
    return [h for h, spec in HOSTS.items() if spec.rule_file == rule_file]


def hosts_reading_both_rule_files() -> list[str]:
    """Hosts that read their own rule file *and* ``CLAUDE.md``.

    For these, a project carrying both files gets the injected PM rules twice
    in the model's context. Callers surface this as a warning rather than
    deleting a file — Claude Code and Codex each require their own.
    """
    return [h for h, spec in HOSTS.items() if spec.also_reads_claude_md]
