# CLAUDE.md 自動管理機能 — 設計 + 実装プロンプト

## 設計概要

### マーカー方式

CLAUDE.md 内の PM Server セクションをマーカーで囲み、識別・差し替え可能にする:

```markdown
<!-- pm-server:begin v=1 -->
## PM Server 自動行動ルール（必ず従うこと）
...内容...
<!-- pm-server:end -->
```

- `v=1` はテンプレートバージョン。pm-server 更新時にバージョンを上げれば差分を検知できる
- マーカー外のユーザー記述には一切触れない

### 動作仕様

| 状況 | pm_init の動作 | pm_update_claudemd の動作 |
|---|---|---|
| CLAUDE.md が存在しない | 新規作成（PM セクションのみ） | 新規作成（PM セクションのみ） |
| CLAUDE.md あり、マーカーなし | 末尾に追記 | 末尾に追記 |
| CLAUDE.md あり、マーカーあり、同バージョン | 何もしない（スキップ） | 強制上書き（--force なしでもOK） |
| CLAUDE.md あり、マーカーあり、旧バージョン | 自動更新 | 自動更新 |

### 新ファイル: claudemd.py

```
src/pm_server/
├── claudemd.py    ← 新規
│   ├── TEMPLATE_VERSION = 1
│   ├── CLAUDEMD_TEMPLATE = "..."
│   ├── BEGIN_MARKER / END_MARKER
│   ├── ensure_claudemd(project_root: Path) → str   # pm_init から呼ぶ
│   ├── update_claudemd(project_root: Path) → str    # MCP ツールから呼ぶ
│   └── get_claudemd_status(project_root: Path) → dict  # バージョン確認
```

### pm_status への統合

`pm_status` のレスポンスに `claudemd` フィールドを追加:
```json
{
  "claudemd": {
    "exists": true,
    "has_pm_section": true,
    "version": 1,
    "up_to_date": true
  }
}
```

バージョンが古い場合、Claude Code が自然言語で「CLAUDE.md の PM Server ルールが古いバージョンです。`pm_update_claudemd` で更新できます」と案内できる。

---

## Claude Code 実装プロンプト

以下を Claude Code にコピペ:

````
# CLAUDE.md 自動管理機能の実装

pm_init 時に CLAUDE.md へ PM Server 自動行動ルールを自動追記する機能と、
バージョンアップ時にルールを更新する pm_update_claudemd MCP ツールを実装する。

## 事前確認

- `pytest` が全パスすること
- `src/pm_server/` の構成を確認

## 設計

### マーカー方式

CLAUDE.md 内の PM Server セクションをマーカーで囲む:

```markdown
<!-- pm-server:begin v=1 -->
## PM Server 自動行動ルール（必ず従うこと）
...
<!-- pm-server:end -->
```

- `v=1` はテンプレートバージョン番号
- マーカー外のユーザー記述には一切触れない

### テンプレート内容

```
<!-- pm-server:begin v=1 -->
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
<!-- pm-server:end -->
```

## タスク

### タスク 1: claudemd.py 新規作成

`src/pm_server/claudemd.py` を作成。以下の関数を実装:

```python
"""CLAUDE.md auto-management for PM Server."""

from __future__ import annotations

import re
from pathlib import Path

TEMPLATE_VERSION = 1
BEGIN_MARKER = "<!-- pm-server:begin v={version} -->"
END_MARKER = "<!-- pm-server:end -->"
BEGIN_PATTERN = re.compile(r"<!-- pm-server:begin v=(\d+) -->")

CLAUDEMD_TEMPLATE = """<!-- pm-server:begin v={version} -->
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
    """CLAUDE.md の PM Server セクションの状態を返す。"""
    claude_md = project_root / "CLAUDE.md"
    result = {
        "exists": claude_md.exists(),
        "has_pm_section": False,
        "version": None,
        "up_to_date": False,
    }
    if not claude_md.exists():
        return result

    content = claude_md.read_text()
    match = BEGIN_PATTERN.search(content)
    if match:
        result["has_pm_section"] = True
        result["version"] = int(match.group(1))
        result["up_to_date"] = result["version"] >= TEMPLATE_VERSION

    return result


def _render_template() -> str:
    """現在のバージョンでテンプレートをレンダリング。"""
    return CLAUDEMD_TEMPLATE.format(version=TEMPLATE_VERSION)


def ensure_claudemd(project_root: Path) -> str:
    """pm_init から呼ばれる。CLAUDE.md に PM Server セクションを確保する。
    
    - CLAUDE.md がない → 新規作成
    - マーカーがない → 末尾に追記
    - マーカーあり同バージョン → スキップ
    - マーカーあり旧バージョン → 自動更新
    
    Returns: 実行結果メッセージ
    """
    status = get_claudemd_status(project_root)
    claude_md = project_root / "CLAUDE.md"
    template = _render_template()

    if not status["exists"]:
        claude_md.write_text(template + "\n")
        return "created CLAUDE.md with PM Server rules"

    content = claude_md.read_text()

    if not status["has_pm_section"]:
        # 末尾に追記（空行で区切る）
        separator = "\n\n" if content and not content.endswith("\n\n") else "\n" if content and not content.endswith("\n") else ""
        claude_md.write_text(content + separator + template + "\n")
        return "appended PM Server rules to CLAUDE.md"

    if status["up_to_date"]:
        return "CLAUDE.md already has up-to-date PM Server rules (skipped)"

    # 旧バージョン → 差し替え
    return _replace_pm_section(claude_md, content, template)


def update_claudemd(project_root: Path) -> str:
    """MCP ツールから呼ばれる。PM Server セクションを最新テンプレートで更新する。
    
    - CLAUDE.md がない → 新規作成
    - マーカーがない → 末尾に追記
    - マーカーあり → 差し替え（バージョン問わず）
    
    Returns: 実行結果メッセージ
    """
    status = get_claudemd_status(project_root)
    claude_md = project_root / "CLAUDE.md"
    template = _render_template()

    if not status["exists"]:
        claude_md.write_text(template + "\n")
        return "created CLAUDE.md with PM Server rules"

    content = claude_md.read_text()

    if not status["has_pm_section"]:
        separator = "\n\n" if content and not content.endswith("\n\n") else "\n" if content and not content.endswith("\n") else ""
        claude_md.write_text(content + separator + template + "\n")
        return "appended PM Server rules to CLAUDE.md"

    return _replace_pm_section(claude_md, content, template)


def _replace_pm_section(claude_md: Path, content: str, template: str) -> str:
    """マーカー間のコンテンツを新しいテンプレートで差し替え。"""
    begin_match = BEGIN_PATTERN.search(content)
    end_idx = content.find(END_MARKER)

    if begin_match and end_idx != -1:
        before = content[:begin_match.start()]
        after = content[end_idx + len(END_MARKER):]
        new_content = before + template + after
        claude_md.write_text(new_content)
        old_version = int(begin_match.group(1))
        return f"updated PM Server rules in CLAUDE.md (v{old_version} → v{TEMPLATE_VERSION})"

    # マーカーが壊れている場合はフォールバック（末尾追記）
    separator = "\n\n" if content and not content.endswith("\n\n") else ""
    claude_md.write_text(content + separator + template + "\n")
    return "appended PM Server rules to CLAUDE.md (markers were corrupted)"
```

### タスク 2: pm_init に ensure_claudemd を統合

`server.py` の `pm_init` 関数の末尾に追加:

```python
# pm_init 内、return の前に追加
from .claudemd import ensure_claudemd
claudemd_result = ensure_claudemd(root)
```

return の dict に `"claudemd": claudemd_result` を追加する。

### タスク 3: pm_update_claudemd MCP ツール追加

`server.py` に新しい MCP ツールを追加:

```python
@mcp.tool()
def pm_update_claudemd(project_path: str | None = None) -> dict:
    """Update the PM Server rules section in CLAUDE.md to the latest version.
    
    Creates CLAUDE.md if it doesn't exist.
    Uses markers to identify and replace only the PM Server section.
    Other content in CLAUDE.md is preserved.
    """
    from .claudemd import update_claudemd, get_claudemd_status, TEMPLATE_VERSION

    root = resolve_project_path(project_path)
    before = get_claudemd_status(root)
    message = update_claudemd(root)
    after = get_claudemd_status(root)

    return {
        "status": "updated",
        "message": message,
        "template_version": TEMPLATE_VERSION,
        "before": before,
        "after": after,
    }
```

### タスク 4: pm_status に claudemd ステータスを追加

`server.py` の `pm_status` 関数の return dict に追加:

```python
from .claudemd import get_claudemd_status
root = resolve_project_path(project_path)

# return dict に追加
"claudemd": get_claudemd_status(root),
```

### タスク 5: テスト作成

`tests/test_claudemd.py` を新規作成:

```python
"""Tests for CLAUDE.md auto-management."""

import pytest
from pm_server.claudemd import (
    TEMPLATE_VERSION,
    ensure_claudemd,
    get_claudemd_status,
    update_claudemd,
)


@pytest.fixture
def project_dir(tmp_path):
    """Create a minimal project directory with .pm/."""
    pm_dir = tmp_path / ".pm"
    pm_dir.mkdir()
    (pm_dir / "project.yaml").write_text("name: test\n")
    return tmp_path


class TestGetClaudemdStatus:
    def test_no_claudemd(self, project_dir):
        status = get_claudemd_status(project_dir)
        assert status["exists"] is False
        assert status["has_pm_section"] is False

    def test_claudemd_without_markers(self, project_dir):
        (project_dir / "CLAUDE.md").write_text("# My Project\n")
        status = get_claudemd_status(project_dir)
        assert status["exists"] is True
        assert status["has_pm_section"] is False

    def test_claudemd_with_current_markers(self, project_dir):
        content = f"# My Project\n\n<!-- pm-server:begin v={TEMPLATE_VERSION} -->\nrules\n<!-- pm-server:end -->\n"
        (project_dir / "CLAUDE.md").write_text(content)
        status = get_claudemd_status(project_dir)
        assert status["has_pm_section"] is True
        assert status["version"] == TEMPLATE_VERSION
        assert status["up_to_date"] is True

    def test_claudemd_with_old_markers(self, project_dir):
        content = "<!-- pm-server:begin v=0 -->\nold rules\n<!-- pm-server:end -->\n"
        (project_dir / "CLAUDE.md").write_text(content)
        status = get_claudemd_status(project_dir)
        assert status["has_pm_section"] is True
        assert status["version"] == 0
        assert status["up_to_date"] is False


class TestEnsureClaudemd:
    def test_creates_new_file(self, project_dir):
        result = ensure_claudemd(project_dir)
        assert "created" in result
        content = (project_dir / "CLAUDE.md").read_text()
        assert f"v={TEMPLATE_VERSION}" in content
        assert "pm_status" in content

    def test_appends_to_existing(self, project_dir):
        (project_dir / "CLAUDE.md").write_text("# My Project\n\nExisting content.\n")
        result = ensure_claudemd(project_dir)
        assert "appended" in result
        content = (project_dir / "CLAUDE.md").read_text()
        assert "# My Project" in content  # 既存内容が保持
        assert "pm_status" in content       # PM セクションが追加

    def test_skips_if_up_to_date(self, project_dir):
        ensure_claudemd(project_dir)  # 初回
        result = ensure_claudemd(project_dir)  # 2回目
        assert "skipped" in result

    def test_updates_old_version(self, project_dir):
        old = "# My Project\n\n<!-- pm-server:begin v=0 -->\nold\n<!-- pm-server:end -->\n\n# Other\n"
        (project_dir / "CLAUDE.md").write_text(old)
        result = ensure_claudemd(project_dir)
        assert "updated" in result
        content = (project_dir / "CLAUDE.md").read_text()
        assert f"v={TEMPLATE_VERSION}" in content
        assert "# My Project" in content   # 前の内容保持
        assert "# Other" in content         # 後の内容保持
        assert "v=0" not in content         # 旧バージョン消えた


class TestUpdateClaudemd:
    def test_creates_new_file(self, project_dir):
        result = update_claudemd(project_dir)
        assert "created" in result

    def test_replaces_even_if_current(self, project_dir):
        ensure_claudemd(project_dir)
        # update は同バージョンでも差し替える
        result = update_claudemd(project_dir)
        assert "updated" in result or "appended" in result

    def test_preserves_surrounding_content(self, project_dir):
        content = "# Header\n\n<!-- pm-server:begin v=0 -->\nold\n<!-- pm-server:end -->\n\n# Footer\n"
        (project_dir / "CLAUDE.md").write_text(content)
        update_claudemd(project_dir)
        new_content = (project_dir / "CLAUDE.md").read_text()
        assert "# Header" in new_content
        assert "# Footer" in new_content
        assert f"v={TEMPLATE_VERSION}" in new_content
```

### タスク 6: migrate 関数の PM Agent 検知を改善

`installer.py` の `migrate_from_pm_agent()` 内で、大文字小文字・スペースを含むパターンにも対応:

```python
# 変更前
if "pm-agent" in content or "pm_agent" in content:

# 変更後（大文字小文字不問で検索）
content_lower = content.lower()
if "pm-agent" in content_lower or "pm_agent" in content_lower or "pm agent" in content_lower:
```

### タスク 7: 既存4プロジェクトに対して pm_update_claudemd を実行する方法を用意

`__main__.py` に `update-claudemd` CLI コマンドを追加:

```python
@cli.command("update-claudemd")
@click.option("--all", "all_projects", is_flag=True, help="Update all registered projects.")
def update_claudemd_cmd(all_projects: bool):
    """Update PM Server rules in CLAUDE.md.
    
    Without --all: updates current project only.
    With --all: updates all registered projects.
    """
    from .claudemd import update_claudemd
    from .storage import load_registry

    if all_projects:
        registry = load_registry()
        for entry in registry.projects:
            root = Path(entry.path)
            if root.exists():
                result = update_claudemd(root)
                click.echo(f"  {entry.name}: {result}")
            else:
                click.echo(f"  {entry.name}: path not found (skipped)")
    else:
        from .utils import resolve_project_path
        try:
            root = resolve_project_path()
            result = update_claudemd(root)
            click.echo(f"✓ {result}")
        except Exception as e:
            click.echo(f"✗ {e}")
```

## ガード & 制約

- CLAUDE.md のマーカー外の内容は絶対に変更しない
- マーカーが壊れている場合（begin はあるが end がない等）は安全にフォールバック
- CLAUDE.md のエンコーディングは UTF-8 前提
- MCP ツール名は `pm_update_claudemd` （snake_case、`pm_` プレフィックス維持）
- CLI コマンド名は `pm-server update-claudemd`（ハイフン区切り）

## テスト

1. `ruff check src/ tests/`
2. `pytest` — 既存 116 + 新規テスト全パス
3. pm_init のテストが CLAUDE.md 作成を確認
4. 既存の test_server.py の pm_init テストが壊れていないこと
5. `pm-server update-claudemd --all` の動作確認（全プロジェクトに適用）
````
