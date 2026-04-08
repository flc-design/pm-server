# pm-server — Claude Code プロジェクト管理システム設計書

**Version**: 0.3.0
**Date**: 2026-04-08
**Author**: Shinichi Nakazato / FLC design co., ltd.
**Status**: Implemented (リネーム移行中)
**License**: MIT
**PyPI**: `pm-server` (予定)
**GitHub**: `github.com/code-retriever/pm-server`

---

## 変更履歴

| Version | Date | 変更内容 |
|---|---|---|
| 0.1.0 | 2026-04-03 | 初版設計 |
| 0.2.0 | 2026-04-03 | MCP ツール詳細化、パッケージ構成追加 |
| 0.3.0 | 2026-04-08 | パッケージ名 `pm-agent` → `pm-server` に変更。installer.py を `claude mcp add` 方式に修正。pm_discover デフォルトパス修正。migrate コマンド追加。実装完了状況を反映 |

---

## 1. 概要

### 問題

Claude Code でコードは高速に書けるが、以下が欠如している：

- **進捗の可視化** — 今どこまで進んでいるか分からない
- **タスクの優先順位** — 次に何をやるべきか判断できない
- **プロジェクト横断の俯瞰** — 複数プロジェクトの状態を一覧できない
- **意思決定の記録** — なぜその設計にしたかが消える
- **ブロッカーの検知** — 依存関係で止まっているタスクに気づかない

### 解決策

Claude Code の MCP Server として動作する pm-server。
**ワンコマンドインストール、ゼロ設定で動く。**

```
$ pip install pm-server
$ pm-server install     ← Claude Code MCP 設定を自動注入

# Claude Code で
> PM初期化して
✓ .pm/ 作成
✓ レジストリ自動登録
✓ git/README からプロジェクト情報推定
```

---

## 2. ユーザー体験

### 2.1 インストール（1回だけ）

```bash
pip install pm-server
pm-server install
```

`pm-server install` が実行すること：

1. `~/.pm/` ディレクトリ作成
2. `~/.pm/registry.yaml` 初期化（空のプロジェクトリスト）
3. Claude Code MCP 設定の自動注入（`claude mcp add` コマンド経由）：

```python
subprocess.run([
    "claude", "mcp", "add",
    "--scope", "user",
    "pm-server",
    "--",
    shutil.which("pm-server"), "serve"
], check=True)
```

4. 完了メッセージ：
```
✓ pm-server installed successfully!
  - MCP server registered in Claude Code (user scope)
  - Restart Claude Code to activate
```

### 2.2 プロジェクト初期化（プロジェクトごと）

Claude Code で対象プロジェクトに `cd` して、自然言語で指示するだけ：

```
> PM初期化して
> このプロジェクトのPM始めて
> pm init
```

pm-server が自動でやること：

1. カレントディレクトリに `.pm/` を作成
2. `~/.pm/registry.yaml` にパスを自動登録
3. プロジェクト情報の自動推定：
   - `package.json` / `pyproject.toml` / `Cargo.toml` → プロジェクト名・バージョン
   - `.git` → リポジトリURL
   - `README.md` → プロジェクト概要
4. 推定結果を表示して確認を求める

```yaml
# 自動生成される project.yaml の例
name: my-app
display_name: "My App"
version: 1.2.0
status: development
started: 2026-04-08
repository: https://github.com/user/my-app
description: "Web application with REST API"
```

### 2.3 日常の使い方

```
> 進捗は？              → pm_status（自動でカレントプロジェクトを検出）
> 次にやること           → pm_next
> ダッシュボード見せて    → pm_dashboard（HTMLを生成・表示）
> 全プロジェクトの状態    → pm_dashboard()（横断ビュー）
> タスク追加：○○を実装   → pm_add_task
> MYAPP-003 完了         → pm_update_task
> この設計にした理由を記録 → pm_add_decision
> ブロッカーある？        → pm_blockers
```

### 2.4 自動行動（CLAUDE.md による）

各プロジェクトの CLAUDE.md に自動行動ルールを記述：

- **セッション開始時** — pm_status + pm_next を自動実行
- **タスク着手時** — ステータスを in_progress に変更
- **タスク完了時** — ステータス更新 + pm_log + 次の推薦
- **設計決定時** — ADR 記録を提案
- **ブロッカー発見時** — タスクを blocked に変更 + リスク登録

---

## 3. アーキテクチャ

### 3.1 全体構成

```
┌──────────────────────────────────────────────┐
│  Claude Code Session                         │
│                                              │
│  ┌──────────────┐    ┌────────────────────┐  │
│  │  CLAUDE.md   │    │  PM MCP Server     │  │
│  │  自動行動    │───▶│ (pm-server serve)  │  │
│  │  ルール      │    │                    │  │
│  │              │    │  FastMCP (stdio)   │  │
│  └──────────────┘    └─────────┬──────────┘  │
│                                │              │
└────────────────────────────────┼──────────────┘
                                 │
                    ┌────────────┴────────────┐
                    ▼                         ▼
        project-A/.pm/              project-B/.pm/
        ├── project.yaml            ├── project.yaml
        ├── tasks.yaml              ├── tasks.yaml
        ├── decisions.yaml          ├── decisions.yaml
        └── daily/                  └── daily/
                    ▲
                    │
            ~/.pm/registry.yaml
            (全プロジェクトのインデックス)
```

### 3.2 プロジェクトパスの自動検出

MCP ツールの `project_path` を省略可能にする。省略時のフォールバック：

```python
def resolve_project_path(project_path: str | None = None) -> Path:
    if project_path:
        return Path(project_path)
    
    # 1. 環境変数 PM_PROJECT_PATH
    if env_path := os.environ.get("PM_PROJECT_PATH"):
        return Path(env_path)
    
    # 2. カレントディレクトリから上方向に .pm/ を探索
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".pm").is_dir():
            return parent
    
    # 3. 見つからなければエラー
    raise ProjectNotFoundError("No .pm/ directory found. Run pm_init first.")
```

### 3.3 データモデル

```
.pm/
├── project.yaml        # プロジェクトメタ情報
├── tasks.yaml          # タスク一覧・状態
├── decisions.yaml      # ADR (Architecture Decision Records)
├── milestones.yaml     # マイルストーン定義
├── risks.yaml          # リスク・ブロッカー
└── daily/
    └── 2026-04-08.yaml # 日次ログ（自動生成）
```

#### project.yaml

```yaml
name: my-app
display_name: "My App — Web Application"
version: 1.2.0
status: development  # design | development | testing | maintenance | archived
started: 2026-04-08
owner: user
repository: https://github.com/user/my-app
description: "REST API を持つ Web アプリケーション"

phases:
  - id: phase-1
    name: "Backend API"
    status: active    # planned | active | completed
    target_date: 2026-05-15
  - id: phase-2
    name: "Frontend"
    status: planned
    target_date: 2026-06-15

health:
  velocity: null
  blockers: 0
  overdue: 0
```

#### tasks.yaml

```yaml
tasks:
  - id: MYAPP-001
    title: "ユーザー認証 API 実装"
    phase: phase-1
    status: todo      # todo | in_progress | review | done | blocked
    priority: P0      # P0 | P1 | P2 | P3
    assignee: claude-code
    estimate_hours: 8
    actual_hours: null
    depends_on: []
    blocked_by: []
    tags: [api, auth]
    created: 2026-04-08
    updated: 2026-04-08
    description: |
      JWT ベースのユーザー認証エンドポイント実装。
    acceptance_criteria:
      - POST /auth/login でトークン発行
      - トークンの有効期限と更新フロー
```

#### decisions.yaml

```yaml
decisions:
  - id: ADR-001
    title: "認証方式に JWT を採用"
    date: 2026-04-08
    status: accepted  # proposed | accepted | deprecated | superseded
    context: |
      セッションベース認証と JWT 認証を比較検討。
      マイクロサービス化を見据えてステートレスな方式が望ましい。
    decision: |
      JWT (RS256) を採用。リフレッシュトークンで長期セッションに対応。
    consequences:
      positive:
        - サーバー側でセッション状態を保持しない
        - マイクロサービス間の認証が容易
      negative:
        - トークン失効の即時反映が困難
      mitigations:
        - 短い有効期限（15分）+ リフレッシュトークンで緩和
```

---

## 4. MCP Server 設計

### 4.1 ツール一覧

```python
from fastmcp import FastMCP

mcp = FastMCP("pm-server")

# ─── プロジェクト管理 ───

@mcp.tool()
def pm_init(project_path: str | None = None, project_name: str | None = None) -> dict:
    """プロジェクトの PM を初期化する。
    .pm/ ディレクトリを作成し、グローバルレジストリに自動登録する。
    project_path 省略時はカレントディレクトリ。
    project_name 省略時はディレクトリ名 or package.json/pyproject.toml から推定。
    git リポジトリURLやREADMEからの情報も自動収集する。"""

@mcp.tool()
def pm_status(project_path: str | None = None) -> dict:
    """プロジェクトの現在状態を返す。
    フェーズ進捗率、タスク集計、ブロッカー数、期限超過数、ベロシティを含む。"""

@mcp.tool()
def pm_tasks(project_path: str | None = None, status: str | None = None,
             phase: str | None = None, priority: str | None = None,
             tag: str | None = None) -> list:
    """タスク一覧をフィルタ付きで返す。"""

@mcp.tool()
def pm_add_task(title: str, phase: str, priority: str = "P1",
                description: str = "", project_path: str | None = None,
                depends_on: list[str] | None = None, tags: list[str] | None = None,
                estimate_hours: float | None = None,
                acceptance_criteria: list[str] | None = None) -> dict:
    """新規タスクを追加。IDは自動採番（{PROJECT_PREFIX}-{連番}）。"""

@mcp.tool()
def pm_update_task(task_id: str, status: str | None = None,
                   priority: str | None = None, actual_hours: float | None = None,
                   notes: str | None = None, blocked_by: list[str] | None = None,
                   project_path: str | None = None) -> dict:
    """タスクのフィールドを更新。task_id は 'MYAPP-001' 形式。"""

@mcp.tool()
def pm_next(project_path: str | None = None, count: int = 3) -> list:
    """次にやるべきタスクを優先度・依存関係・フェーズから推薦。
    blocked なタスクは除外。depends_on が未完了のタスクも除外。"""

@mcp.tool()
def pm_blockers(project_path: str | None = None) -> list:
    """ブロッカーと blocked 状態のタスクを一覧。
    project_path=None の場合は全プロジェクトのブロッカーを集計。"""

# ─── 記録 ───

@mcp.tool()
def pm_log(entry: str, category: str = "progress",
           project_path: str | None = None) -> dict:
    """日次ログにエントリを追加。
    category: progress | decision | blocker | note | milestone"""

@mcp.tool()
def pm_add_decision(title: str, context: str, decision: str,
                    consequences_positive: list[str] | None = None,
                    consequences_negative: list[str] | None = None,
                    project_path: str | None = None) -> dict:
    """ADR（Architecture Decision Record）を追加。IDは自動採番。"""

# ─── 分析 ───

@mcp.tool()
def pm_velocity(project_path: str | None = None, weeks: int = 4) -> dict:
    """過去N週のベロシティ（完了タスク数/週）を計算。
    トレンド（上昇/下降/横ばい）も判定。"""

@mcp.tool()
def pm_risks(project_path: str | None = None) -> list:
    """リスク・課題を一覧。期限超過タスク、長期blocked、
    フェーズ遅延を自動検知して含める。"""

# ─── ビジュアライゼーション ───

@mcp.tool()
def pm_dashboard(project_path: str | None = None, format: str = "html") -> str:
    """ダッシュボードを生成。
    project_path 指定時: 単体プロジェクトビュー
    project_path=None: 全プロジェクト横断ビュー
    format: html | text"""

# ─── ディスカバリー & 管理 ───

@mcp.tool()
def pm_discover(scan_path: str = ".") -> list:
    """指定パス配下を再帰スキャンし、
    .pm/ を持つ未登録プロジェクトを自動でレジストリに追加。
    デフォルトはカレントディレクトリ。"""

@mcp.tool()
def pm_cleanup() -> dict:
    """レジストリのヘルスチェック。
    パスが存在しないプロジェクトを検出し、除去を提案。"""

@mcp.tool()
def pm_list() -> list:
    """レジストリに登録された全プロジェクトの一覧と概要を返す。"""

# ─── メンテナンス ───

@mcp.tool()
def pm_update_claudemd(project_path: str | None = None) -> dict:
    """CLAUDE.md の PM Server ルールセクションを最新テンプレートに更新。
    CLAUDE.md がなければ新規作成。マーカーで識別して PM Server セクションのみ置換。"""
```

### 4.2 CLI エントリポイント

```python
# pm_server/__main__.py
import click

@click.group()
def cli():
    """pm-server — Claude Code Project Management"""
    pass

@cli.command()
def install():
    """Claude Code にMCPサーバーを登録する。
    内部で `claude mcp add --scope user pm-server -- <path> serve` を実行。"""

@cli.command()
def uninstall():
    """Claude Code からMCPサーバー登録を解除する。
    内部で `claude mcp remove pm-server --scope user` を実行。"""

@cli.command()
def serve():
    """MCP Server を起動（Claude Code から呼ばれる）。"""
    mcp.run(transport="stdio")

@cli.command()
@click.argument("scan_path", default=".")
def discover(scan_path):
    """ローカルプロジェクトをスキャンしてレジストリに登録。"""

@cli.command()
def status():
    """CLI から直接プロジェクト状態を確認（MCP不要）。"""

@cli.command()
def migrate():
    """pm-agent からの移行。旧 MCP 登録を解除し、新 pm-server として再登録。
    1. claude mcp remove pm-agent --scope user
    2. claude mcp add --scope user pm-server -- <path> serve
    3. ~/.pm/registry.yaml の整合性チェック
    4. CLAUDE.md 内の pm-agent 言及を警告"""

@cli.command("update-claudemd")
@click.option("--all", "all_projects", is_flag=True, help="Update all registered projects.")
def update_claudemd_cmd(all_projects):
    """CLAUDE.md の PM Server ルールを最新版に更新。"""

if __name__ == "__main__":
    cli()
```

---

## 5. installer.py 設計

### 5.1 `claude mcp add` 方式（実装済み）

設計書 v0.2.0 では `~/.claude/settings.json` を直接編集する方式だったが、
実運用で Claude Code が MCP 設定を `~/.claude.json` で管理していることが判明。
公式の `claude mcp add` コマンド経由に修正済み。

```python
"""Claude Code MCP 設定の自動インストーラー。"""

import shutil
import subprocess
from pathlib import Path

def install_mcp():
    """pm-server を Claude Code の MCP サーバーとして登録。
    claude mcp add --scope user コマンドを使用。"""
    pm_server_path = shutil.which("pm-server")
    if pm_server_path is None:
        raise RuntimeError("pm-server command not found in PATH")
    
    try:
        subprocess.run(
            ["claude", "mcp", "add", "--scope", "user",
             "pm-server", "--", pm_server_path, "serve"],
            check=True, capture_output=True, text=True
        )
        print("✓ pm-server registered in Claude Code (user scope)")
        print("  Restart Claude Code to activate")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to register MCP server: {e.stderr}")
    except FileNotFoundError:
        raise RuntimeError("'claude' command not found. Is Claude Code installed?")

def uninstall_mcp():
    """pm-server の MCP 登録を解除。"""
    try:
        subprocess.run(
            ["claude", "mcp", "remove", "pm-server", "--scope", "user"],
            check=True, capture_output=True, text=True
        )
        print("✓ pm-server unregistered from Claude Code")
    except subprocess.CalledProcessError:
        print("pm-server was not registered")
    except FileNotFoundError:
        print("'claude' command not found")

def migrate_from_pm_agent():
    """pm-agent から pm-server への移行。
    1. 旧 pm-agent の MCP 登録を解除
    2. 新 pm-server を MCP サーバーとして登録
    3. registry.yaml の整合性チェック
    4. 各プロジェクトの CLAUDE.md に pm-agent 言及があれば警告
    """
    # 1. 旧登録解除
    try:
        subprocess.run(
            ["claude", "mcp", "remove", "pm-agent", "--scope", "user"],
            check=True, capture_output=True, text=True
        )
        print("✓ Old pm-agent MCP registration removed")
    except subprocess.CalledProcessError:
        print("  pm-agent was not registered (skipping)")
    
    # 2. 新登録
    install_mcp()
    
    # 3. registry チェック
    registry_path = Path.home() / ".pm" / "registry.yaml"
    if registry_path.exists():
        print(f"✓ Registry at {registry_path} is intact")
    else:
        print("⚠ Registry not found at ~/.pm/registry.yaml")
    
    # 4. CLAUDE.md 警告
    if registry_path.exists():
        import yaml
        registry = yaml.safe_load(registry_path.read_text()) or {}
        projects = registry.get("projects", [])
        for proj in projects:
            claude_md = Path(proj["path"]) / "CLAUDE.md"
            if claude_md.exists():
                content = claude_md.read_text()
                if "pm-agent" in content or "pm_agent" in content:
                    print(f"⚠ {claude_md} contains 'pm-agent' references — please update manually")
    
    print("\n✓ Migration complete. Restart Claude Code to activate.")
```

---

## 6. discovery.py 設計

```python
"""プロジェクトの自動検出と情報推定。"""

from pathlib import Path
import tomllib, json, subprocess

def detect_project_info(project_path: Path) -> dict:
    """プロジェクトディレクトリからメタ情報を自動推定。
    package.json, pyproject.toml, Cargo.toml, .git, README.md を読む。"""
    info = {
        "name": project_path.name,
        "display_name": project_path.name,
        "version": "0.1.0",
        "repository": None,
        "description": "",
    }
    
    # package.json (Node.js)
    pkg_json = project_path / "package.json"
    if pkg_json.exists():
        pkg = json.loads(pkg_json.read_text())
        info["name"] = pkg.get("name", info["name"])
        info["version"] = pkg.get("version", info["version"])
        info["description"] = pkg.get("description", "")
    
    # pyproject.toml (Python)
    pyproject = project_path / "pyproject.toml"
    if pyproject.exists():
        with open(pyproject, "rb") as f:
            pyp = tomllib.load(f)
        proj = pyp.get("project", {})
        info["name"] = proj.get("name", info["name"])
        info["version"] = proj.get("version", info["version"])
        info["description"] = proj.get("description", "")
    
    # Cargo.toml (Rust)
    cargo_toml = project_path / "Cargo.toml"
    if cargo_toml.exists():
        with open(cargo_toml, "rb") as f:
            cargo = tomllib.load(f)
        pkg = cargo.get("package", cargo.get("workspace", {}).get("package", {}))
        info["name"] = pkg.get("name", info["name"])
        info["version"] = pkg.get("version", info["version"])
        info["description"] = pkg.get("description", "")
    
    # Git remote URL
    try:
        result = subprocess.run(
            ["git", "-C", str(project_path), "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            info["repository"] = result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    
    # README.md
    readme = project_path / "README.md"
    if readme.exists() and not info["description"]:
        lines = readme.read_text().splitlines()
        for line in lines:
            stripped = line.strip().lstrip("# ").strip()
            if stripped and not stripped.startswith("!") and len(stripped) > 10:
                info["description"] = stripped[:200]
                break
    
    return info


def discover_projects(scan_path: Path) -> list[dict]:
    """指定パス配下を再帰スキャンし、.pm/ を持つプロジェクトを発見。
    デフォルトはカレントディレクトリ（v0.2.0 ではホームディレクトリだったが修正）。"""
    found = []
    scan_path = scan_path.expanduser().resolve()
    for pm_dir in scan_path.rglob(".pm"):
        if pm_dir.is_dir() and (pm_dir / "project.yaml").exists():
            project_path = pm_dir.parent
            found.append({"path": str(project_path), "name": project_path.name})
    return found
```

---

## 7. ダッシュボード仕様

### 7.1 HTML ダッシュボード

Chart.js CDN + ダークテーマ（Jinja2 テンプレート）。

**単体プロジェクトビュー:**
- プロジェクトヘッダー（名前、ステータス、全体進捗バー）
- フェーズ進捗テーブル（各フェーズの完了率）
- カンバンボード（todo / in_progress / review / done のカード）
- ベロシティチャート（棒グラフ、週次）
- ブロッカー・リスクセクション（赤ハイライト）
- 直近アクティビティ（日次ログの最新5件）
- ADR 一覧

**全プロジェクト横断ビュー:**
- プロジェクト一覧テーブル（名前、ステータス、進捗率、健康度アイコン）
- グローバル集計（アクティブタスク数、ブロッカー数、今週完了数）
- Attention Required セクション（期限超過、長期ブロック）
- プロジェクト別ミニチャート

### 7.2 テキストフォールバック

`format="text"` 指定時は ASCII アートで簡易表示。

---

## 8. パッケージ構成

```
pm-server/                         # ← pm-agent から改名
├── pyproject.toml
├── README.md                      # 英語版
├── README.ja.md                   # 日本語版
├── LICENSE (MIT)
├── CHANGELOG.md
├── CLAUDE.md
├── .github/
│   └── workflows/
│       ├── test.yml
│       └── publish.yml
├── src/
│   └── pm_server/                 # ← pm_agent から改名
│       ├── __init__.py
│       ├── __main__.py            # CLI (click)
│       ├── server.py              # FastMCP Server (16ツール)
│       ├── models.py              # Pydantic v2 (12モデル, 9 Enum)
│       ├── storage.py             # YAML CRUD
│       ├── installer.py           # claude mcp add ラッパー + migrate
│       ├── discovery.py           # プロジェクト情報自動推定
│       ├── dashboard.py           # HTML/テキスト ダッシュボード
│       ├── velocity.py            # ベロシティ・リスク検知
│       ├── utils.py               # パス解決・ID生成・集計
│       └── templates/
│           ├── dashboard_single.html
│           └── dashboard_portfolio.html
├── skill/
│   └── SKILL.md
├── tests/
│   ├── conftest.py                # registry 隔離フィクスチャ
│   ├── test_models.py
│   ├── test_storage.py
│   ├── test_server.py
│   ├── test_installer.py          # subprocess mock
│   ├── test_discovery.py
│   ├── test_dashboard.py
│   └── test_velocity.py
└── docs/
    ├── design.md                  # この設計書
    ├── status.md
    └── handoff.md
```

### 8.1 pyproject.toml

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "pm-server"
version = "0.2.0"
description = "Project management MCP Server for Claude Code — track tasks, visualize progress, manage decisions"
readme = "README.md"
license = "MIT"
requires-python = ">=3.11"
authors = [
    { name = "Shinichi Nakazato", email = "..." }
]
keywords = ["claude-code", "project-management", "mcp", "mcp-server"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
]
dependencies = [
    "fastmcp>=2.0",
    "pydantic>=2.0",
    "pyyaml>=6.0",
    "click>=8.0",
    "jinja2>=3.0",
]

[project.scripts]
pm-server = "pm_server.__main__:cli"

[project.urls]
Homepage = "https://github.com/code-retriever/pm-server"
Repository = "https://github.com/code-retriever/pm-server"
Issues = "https://github.com/code-retriever/pm-server/issues"
```

---

## 9. 実装計画と現在の状態

### Phase 1〜4: 完了済み ✅

全15 MCP ツール実装、115テスト全パス、4プロジェクトで実運用中。
詳細は `docs/status.md` を参照。

### Phase 5: リネーム + 公開（現在進行中）

- [x] README.md 書き直し（英語版 + 日本語版）
- [x] 設計書更新（この文書）
- [ ] パッケージリネーム（pm_agent → pm_server）
- [ ] migrate コマンド実装
- [ ] Git コミット整理
- [ ] GitHub リポジトリ push（github.com/code-retriever/pm-server）
- [ ] `.github/workflows/test.yml` (pytest CI)
- [ ] PyPI 公開

#### リネーム作業詳細

以下を一括で変更する：

| 対象 | 変更前 | 変更後 |
|---|---|---|
| ディレクトリ | `src/pm_agent/` | `src/pm_server/` |
| pyproject.toml name | `pm-agent` | `pm-server` |
| pyproject.toml scripts | `pm-agent = "pm_agent.__main__:cli"` | `pm-server = "pm_server.__main__:cli"` |
| pyproject.toml URLs | `nakashin/pm-agent` | `code-retriever/pm-server` |
| 全 import 文 | `from pm_agent` / `import pm_agent` | `from pm_server` / `import pm_server` |
| server.py FastMCP 名 | `FastMCP("pm-agent")` | `FastMCP("pm-server")` |
| テスト内参照 | `pm_agent` | `pm_server` |
| CLAUDE.md | `pm-agent` 言及 | `pm-server` に更新 |
| skill/SKILL.md | `pm-agent` 言及 | `pm-server` に更新 |

#### migrate コマンド実装

```python
@cli.command()
def migrate():
    """pm-agent からの移行。"""
    from .installer import migrate_from_pm_agent
    migrate_from_pm_agent()
```

実行内容:
1. `claude mcp remove pm-agent --scope user`
2. `claude mcp add --scope user pm-server -- <path> serve`
3. `~/.pm/registry.yaml` の整合性チェック
4. 各プロジェクトの `CLAUDE.md` 内の `pm-agent` 言及を警告

---

## 10. 設計原則

1. **Zero Configuration** — `pip install` + `pm-server install` で完了
2. **Auto-everything** — 登録・検出・推定は全自動
3. **Git-friendly** — plain text YAML、git diff で追跡可能
4. **Human-readable** — YAML を手動編集しても壊れない
5. **AI-native** — Claude Code が自然に読み書きできるフォーマット
6. **Visual-first** — 数字よりグラフ、テキストよりカンバン
7. **Incremental** — 最小限から始めて段階的に機能追加
8. **Non-invasive** — プロジェクトの構造を変更しない（.pm/ を追加するだけ）
