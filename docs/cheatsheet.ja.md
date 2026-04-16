# PM Server チートシート

> Claude Code 用プロジェクト管理 MCP Server — **30 ツール**
> Version 0.3.3+ | Python 3.11+ | PyPI: `pm-server`

---

## クイックスタート

```bash
pip install pm-server
pm-server install          # Claude Code に MCP サーバーを登録
```

Claude Code セッション:
```
> PM初期化して              → pm_init
> 現在の進捗は？            → pm_status
> 次にやるべきことは？      → pm_next
```

---

## ツールリファレンス

### セットアップ・プロジェクト管理

| ツール | 説明 | 主要パラメータ |
|--------|------|----------------|
| `pm_init` | .pm/ ディレクトリ初期化、プロジェクト情報を自動検出 | `project_path?`, `project_name?` |
| `pm_status` | プロジェクト状況: フェーズ進捗、タスク数、ブロッカー | `project_path?` |
| `pm_list` | 登録済み全プロジェクト一覧 | _(なし)_ |
| `pm_discover` | プロジェクトをスキャンして自動登録 | `scan_path="."` |
| `pm_cleanup` | レジストリの健全性チェック、無効エントリ削除 | _(なし)_ |
| `pm_update_claudemd` | CLAUDE.md のルールセクションを最新版に更新 | `project_path?` |
| `pm_dashboard` | HTML/テキスト ダッシュボード生成 | `format="html"` |

### タスク管理

| ツール | 説明 | 主要パラメータ |
|--------|------|----------------|
| `pm_add_task` | タスク作成（ID自動採番） | `title`, `phase`, `priority="P1"` |
| `pm_update_task` | タスクのステータス・フィールド更新 | `task_id`, `status?`, `priority?`, `notes?` |
| `pm_tasks` | タスク一覧（フィルタ可能） | `status?`, `phase?`, `priority?`, `tag?`, `parent_id?` |
| `pm_next` | 次に着手すべきタスクを推薦 | `count=3` |
| `pm_blockers` | ブロックされているタスク一覧 | `project_path?` |
| `pm_add_issue` | タスクに子イシュー（課題）を追加 | `parent_id`, `title`, `priority="P1"` |

### メモリ（セッション記憶）

| ツール | 説明 | 主要パラメータ |
|--------|------|----------------|
| `pm_remember` | 記憶を保存（作業中タスクに自動紐付け） | `content`, `type="observation"`, `tags?` |
| `pm_recall` | 記憶を想起 / 前回セッション取得 | `query?`, `task_id?`, `limit=5` |
| `pm_memory_search` | 詳細検索（複数フィルタ対応） | `query`, `type?`, `tags?`, `cross_project?` |
| `pm_memory_stats` | メモリDB統計情報 | `project_path?` |
| `pm_memory_cleanup` | 古い記憶の削除 | `older_than_days?`, `keep_latest?`, `dry_run=True` |
| `pm_session_summary` | セッション要約の保存/取得/一覧 | `action="save"`, `summary?` |

### 記録・分析

| ツール | 説明 | 主要パラメータ |
|--------|------|----------------|
| `pm_log` | デイリーログに記録（作業中タスクに自動紐付け） | `entry`, `category="progress"` |
| `pm_add_decision` | ADR（設計判断記録）を保存（ID自動採番） | `title`, `context`, `decision` |
| `pm_velocity` | ベロシティとトレンド分析 | `weeks=4` |
| `pm_risks` | 自動検出 + 手動登録リスク一覧 | `project_path?` |

### 知識レコード

| ツール | 説明 | 主要パラメータ |
|--------|------|----------------|
| `pm_record` | 構造化された知識を記録 | `category`, `title`, `findings?`, `confidence="medium"` |
| `pm_knowledge` | 知識レコードの検索・更新 | `action="list"`, `category?`, `status?`, `tag?` |

### ワークフロー

| ツール | 説明 | 主要パラメータ |
|--------|------|----------------|
| `pm_workflow_start` | テンプレートからワークフローを開始 | `feature`, `template="development"` |
| `pm_workflow_status` | ワークフロー進捗とガイダンスを取得 | `workflow_id?`（自動検出） |
| `pm_workflow_advance` | ステップを進める/ループ/スキップ | `proceed=True`, `artifacts?`, `skip?` |
| `pm_workflow_list` | ワークフローインスタンス一覧 | `status?` |
| `pm_workflow_templates` | 利用可能なテンプレート一覧 | `project_path?` |

---

## よくある使い方

### タスクのライフサイクル

```
pm_add_task(title="認証機能追加", phase="phase-1", priority="P0")
  → PROJ-001 作成 (todo)

pm_update_task(task_id="PROJ-001", status="in_progress")
  → 作業開始

pm_update_task(task_id="PROJ-001", status="done")
  → 完了

pm_log(entry="JWT認証を実装完了")
  → デイリーログに記録
```

### レビュー中にイシューを発見した場合

```
pm_add_issue(parent_id="PROJ-001", title="JWTトークンの期限切れが未処理")
  → PROJ-005 作成、PROJ-001 は自動で "review" に戻る

pm_update_task(task_id="PROJ-005", status="done")
  → all_issues_resolved=True、PROJ-001 の完了を提案
```

### 3層ナレッジ管理システム

```
# Layer 1: カジュアル — 作業中の気づきメモ
pm_remember(content="FastMCP v2 は Python 3.11+ が必須", type="observation")

# Layer 2: 構造化 — 調査結果、トレードオフ分析
pm_record(category="tradeoff", title="JWT vs セッション認証",
          findings="JWT: ステートレスだがペイロードが大きい...",
          conclusion="API は JWT、Web はセッション",
          confidence="high")

# Layer 3: フォーマル — 設計判断（ADR）
pm_add_decision(title="API認証に JWT を採用",
                context="マイクロサービスにステートレス認証が必要",
                decision="JWT + RS256、有効期限15分")
```

### 知識レコードのカテゴリ

| カテゴリ | 用途 |
|----------|------|
| `research` | 一般的な調査結果 |
| `market` | 市場分析、競合調査 |
| `spike` | 技術スパイク / プロトタイプ結果 |
| `requirement` | 要件定義 |
| `constraint` | 技術的・ビジネス上の制約 |
| `tradeoff` | トレードオフ分析（A vs B） |
| `risk_analysis` | リスク評価結果 |
| `spec` | 機能仕様 |
| `api_design` | API 設計ドキュメント |

### 知識レコードのライフサイクル

```
pm_record(category="research", title="認証方式の調査", confidence="low")
  → KR-001 (draft, 信頼度: low)

pm_knowledge(action="update", record_id="KR-001",
             new_status="validated", confidence="high",
             conclusion="JWT が最適")
  → KR-001 (validated, 信頼度: high)

pm_knowledge(action="update", record_id="KR-001",
             new_status="superseded")
  → KR-001 (superseded — 新しい調査結果に置き換え)
```

---

## ワークフロー

### 組み込みテンプレート

#### Discovery（5ステップ、完了後 Development に連鎖）

```
research ──→ fact_check ──→ proposal ──→ cross_check ──→ confirm
   ↑              ↑             ↑
   └──── brainstorm loop ───────┘
         (proceed=false でループ)
```

- **research**: トピックを調査（ループ対象）
- **fact_check**: 調査結果を検証（ループ対象）
- **proposal**: ユーザーに提案（ループ対象、ゲート: user_approval）
- **cross_check**: 独立した妥当性検証
- **confirm**: 方向性を確定、ADR 記録（ゲート: user_approval）

#### Development（9ステップ）

```
decision → tasks → spec → plan → check → implement → test → quality → issues
                                   ↑                          ↑
                              ゲート: user_approval      ゲート: user_approval
```

- **decision**: ADR を記録
- **tasks**: タスクに分解
- **spec**: 仕様書を作成
- **plan**: 実装プランを設計
- **check**: クロスチェック（ゲート: user_approval）
- **implement**: コードを実装
- **test**: テストの作成・実行
- **quality**: 最終品質レビュー（ゲート: user_approval）
- **issues**: 残課題の登録（オプション）

### ワークフローの使い方

```
# 開始
pm_workflow_start(feature="ユーザー認証", template="discovery")
  → WF-001 開始、ステップ 1: research

# 通常の進行
pm_workflow_advance(artifacts=["KR-001"])
  → ステップ完了、次: fact_check

# ループバック（ブレーンストーミング）
pm_workflow_advance(proceed=False)
  → research に戻る（イテレーション 2）

# オプションのステップをスキップ
pm_workflow_advance(skip=True)
  → ステップをスキップ、次のステップへ

# 進捗確認
pm_workflow_status()
  → progress: 3/5, current: proposal, knowledge: {count: 2}

# 連鎖: Discovery 完了 → Development を提案
pm_workflow_advance()
  → workflow_completed, chain_to: "development"
pm_workflow_start(feature="ユーザー認証", template="development")
  → WF-002 開始
```

### カスタムテンプレート

`.pm/workflow_templates/` に YAML ファイルを配置すると、
組み込みテンプレートの上書きや独自テンプレートの追加が可能:

```yaml
# .pm/workflow_templates/my-workflow.yaml
name: 独自ワークフロー
description: チーム専用のワークフロー
chain_to: development  # 省略可

steps:
  - id: research
    name: 調査
    tool_hint: pm_record
    loop: true
    loop_group: investigate

  - id: review
    name: レビュー
    gate: user_approval

  - id: implement
    name: 実装
    skill_hint: プランモードを使用
    optional: false
```

---

## セッションのライフサイクル

```
# セッション開始（CLAUDE.md ルールにより自動実行）
pm_status()                    # 現在の状態
pm_next()                      # 推薦タスク
pm_recall()                    # 前回セッションの文脈

# 作業中
pm_update_task(status="in_progress")   # タスク着手
pm_remember(content="...")             # 発見を記録
pm_record(category="...", title="...")  # 知識を記録
pm_workflow_advance()                  # ワークフロー進行

# セッション終了
pm_log(entry="認証機能を実装完了")
pm_session_summary(action="save", summary="...")
```

---

## CLI コマンド

```bash
pm-server install              # MCP サーバー登録
pm-server uninstall            # MCP サーバー削除
pm-server serve                # MCP サーバー起動（stdio）
pm-server status               # プロジェクト状況表示
pm-server discover [path]      # プロジェクト検出・登録
pm-server update-claudemd      # CLAUDE.md ルール更新
pm-server hook post-tool-use   # PostToolUse フックハンドラ
```

---

## データ保存先

```
.pm/                            # プロジェクトごと
├── project.yaml                # プロジェクトメタデータ
├── tasks.yaml                  # 全タスク
├── decisions.yaml              # ADR（設計判断記録）
├── knowledge.yaml              # 知識レコード
├── workflows.yaml              # ワークフローインスタンス
├── risks.yaml                  # 手動リスク
├── milestones.yaml             # マイルストーン
├── memory.db                   # SQLite + FTS5 メモリ
├── daily/                      # デイリーログ
│   └── 2026-04-16.yaml
└── workflow_templates/         # カスタムテンプレート（任意）
    └── my-workflow.yaml

~/.pm/                          # グローバル
├── registry.yaml               # プロジェクトレジストリ
└── memory.db                   # 横断メモリインデックス
```

---

## Enum リファレンス

| 型 | 値 |
|----|----|
| TaskStatus | `todo`, `in_progress`, `review`, `done`, `blocked` |
| Priority | `P0`（最重要）, `P1`（重要）, `P2`（あれば良い）, `P3`（いつか） |
| DecisionStatus | `proposed`, `accepted`, `deprecated`, `superseded` |
| LogCategory | `progress`, `decision`, `blocker`, `note`, `milestone` |
| MemoryType | `observation`, `insight`, `lesson` |
| KnowledgeCategory | `research`, `market`, `spike`, `requirement`, `constraint`, `tradeoff`, `risk_analysis`, `spec`, `api_design` |
| KnowledgeStatus | `draft`（下書き）, `validated`（検証済）, `superseded`（置換済） |
| ConfidenceLevel | `high`（高）, `medium`（中）, `low`（低） |
| WorkflowStepStatus | `pending`, `active`, `done`, `skipped` |
| WorkflowStatus | `active`, `completed`, `paused`, `abandoned` |
