"""CLAUDE.md auto-management for PM Server.

Manages a marker-delimited section in CLAUDE.md that contains
PM Server auto-action rules for Claude Code sessions.
"""

from __future__ import annotations

import re
from pathlib import Path

TEMPLATE_VERSION = 1
BEGIN_MARKER = "<!-- pm-server:begin v={version} -->"
END_MARKER = "<!-- pm-server:end -->"
BEGIN_PATTERN = re.compile(r"<!-- pm-server:begin v=(\d+) -->")

CLAUDEMD_TEMPLATE = """\
<!-- pm-server:begin v={version} -->
## PM Server 自動行動ルール（必ず従うこと）

### セッション開始時（最初の応答の前に必ず実行）
1. pm_status を MCP ツールとして実行し、現在の進捗を表示する
2. pm_next で次に着手すべきタスクを3件表示する
3. ブロッカーや期限超過があれば警告する

### タスクに着手する前
1. 該当タスクを pm_update_task で in_progress に変更する

### タスク完了時（コードが動作確認できたら）
1. pm_update_task で done に変更する
2. pm_log に完了内容を記録する
3. 次の推薦タスクを pm_next で表示する
4. アトミックコミットを作成する

### 設計上の意思決定が発生した時
1. ユーザーに「ADRとして記録しますか？」と確認する
2. 承認されたら pm_add_decision で保存する

### コーディングセッション終了時
1. 進行中のタスクの状態を確認し、必要に応じて更新する
2. pm_log にセッションの成果を記録する
3. 未コミットの変更があればコミットする
<!-- pm-server:end -->"""


def get_claudemd_status(project_root: Path) -> dict:
    """Return the PM Server section status in CLAUDE.md.

    Returns:
        dict with keys: exists, has_pm_section, version, up_to_date
    """
    claude_md = project_root / "CLAUDE.md"
    result: dict = {
        "exists": claude_md.exists(),
        "has_pm_section": False,
        "version": None,
        "up_to_date": False,
    }
    if not claude_md.exists():
        return result

    content = claude_md.read_text(encoding="utf-8")
    match = BEGIN_PATTERN.search(content)
    if match:
        result["has_pm_section"] = True
        result["version"] = int(match.group(1))
        result["up_to_date"] = result["version"] >= TEMPLATE_VERSION

    return result


def _render_template() -> str:
    """Render the template with the current version."""
    return CLAUDEMD_TEMPLATE.format(version=TEMPLATE_VERSION)


def _separator_for(content: str) -> str:
    """Choose the right separator to append content."""
    if not content:
        return ""
    if content.endswith("\n\n"):
        return ""
    if content.endswith("\n"):
        return "\n"
    return "\n\n"


def ensure_claudemd(project_root: Path) -> str:
    """Ensure CLAUDE.md has the PM Server rules section.

    Called from pm_init. Behavior:
    - No CLAUDE.md -> create with PM section
    - No markers -> append PM section
    - Same version -> skip
    - Old version -> replace PM section

    Returns:
        Status message describing what was done.
    """
    status = get_claudemd_status(project_root)
    claude_md = project_root / "CLAUDE.md"
    template = _render_template()

    if not status["exists"]:
        claude_md.write_text(template + "\n", encoding="utf-8")
        return "created CLAUDE.md with PM Server rules"

    content = claude_md.read_text(encoding="utf-8")

    if not status["has_pm_section"]:
        separator = _separator_for(content)
        claude_md.write_text(content + separator + template + "\n", encoding="utf-8")
        return "appended PM Server rules to CLAUDE.md"

    if status["up_to_date"]:
        return "CLAUDE.md already has up-to-date PM Server rules (skipped)"

    # Old version -> replace
    return _replace_pm_section(claude_md, content, template)


def update_claudemd(project_root: Path) -> str:
    """Update the PM Server rules section to the latest template.

    Called from the pm_update_claudemd MCP tool. Unlike ensure_claudemd,
    this always replaces regardless of version.

    Returns:
        Status message describing what was done.
    """
    status = get_claudemd_status(project_root)
    claude_md = project_root / "CLAUDE.md"
    template = _render_template()

    if not status["exists"]:
        claude_md.write_text(template + "\n", encoding="utf-8")
        return "created CLAUDE.md with PM Server rules"

    content = claude_md.read_text(encoding="utf-8")

    if not status["has_pm_section"]:
        separator = _separator_for(content)
        claude_md.write_text(content + separator + template + "\n", encoding="utf-8")
        return "appended PM Server rules to CLAUDE.md"

    return _replace_pm_section(claude_md, content, template)


def _replace_pm_section(claude_md: Path, content: str, template: str) -> str:
    """Replace the marker-delimited PM section with new template."""
    begin_match = BEGIN_PATTERN.search(content)
    end_idx = content.find(END_MARKER)

    if begin_match and end_idx != -1:
        # Normal: replace between begin and end markers
        before = content[: begin_match.start()]
        after = content[end_idx + len(END_MARKER) :]
        new_content = before + template + after
        claude_md.write_text(new_content, encoding="utf-8")
        old_version = int(begin_match.group(1))
        return f"updated PM Server rules in CLAUDE.md (v{old_version} → v{TEMPLATE_VERSION})"

    if begin_match and end_idx == -1:
        # Corrupted: begin marker exists but no end marker — remove begin and everything after it
        before = content[: begin_match.start()]
        new_content = before.rstrip() + "\n\n" + template + "\n"
        claude_md.write_text(new_content, encoding="utf-8")
        return "replaced corrupted PM Server section in CLAUDE.md"

    # No markers at all — fallback to append
    separator = _separator_for(content)
    claude_md.write_text(content + separator + template + "\n", encoding="utf-8")
    return "appended PM Server rules to CLAUDE.md (no markers found)"
