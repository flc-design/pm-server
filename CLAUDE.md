# PM Server — Claude Code Project Management System

## プロジェクト概要

Claude Code 用のプロジェクト管理 MCP Server。
タスク追跡・進捗可視化・ブロッカー検知・ADR記録・全プロジェクト横断ダッシュボードを提供する。

- **言語**: Python 3.11+
- **フレームワーク**: FastMCP, Pydantic v2, Click, Jinja2
- **データ形式**: YAML（human-readable, git-friendly）
- **配布**: PyPI (`pm-server`)
- **ライセンス**: MIT

## 設計書

実装の前に必ず `docs/design.md` を読むこと。
これがすべてのアーキテクチャ判断の根拠となる。

## ディレクトリ構成

```
pm-server/
├── pyproject.toml
├── README.md
├── LICENSE
├── src/
│   └── pm_server/
│       ├── __init__.py
│       ├── __main__.py       # CLI (click)
│       ├── server.py          # FastMCP サーバー (22 tools)
│       ├── models.py          # Pydantic データモデル (14 models, 10 enums)
│       ├── storage.py         # YAML 読み書き
│       ├── memory.py          # SQLite メモリストア + FTS5 検索
│       ├── recall.py          # セッションコンテキスト構築
│       ├── context.py         # CLI コンテキスト注入
│       ├── claudemd.py        # CLAUDE.md テンプレート管理
│       ├── installer.py       # Claude Code MCP 自動登録
│       ├── discovery.py       # プロジェクト自動検出・情報推定
│       ├── dashboard.py       # HTML/テキスト ダッシュボード生成
│       ├── velocity.py        # ベロシティ・分析・リスク検知
│       ├── utils.py           # パス解決、ID生成、集計ヘルパー
│       └── templates/         # Jinja2 HTML テンプレート
│           ├── dashboard_single.html
│           └── dashboard_portfolio.html
├── skill/
│   └── SKILL.md               # Claude Code 用スキル定義
├── tests/
│   ├── conftest.py
│   ├── test_models.py
│   ├── test_storage.py
│   ├── test_server.py
│   ├── test_installer.py
│   ├── test_discovery.py
│   ├── test_dashboard.py
│   ├── test_velocity.py
│   ├── test_memory.py
│   ├── test_recall.py
│   ├── test_context.py
│   └── test_memory_ops.py
└── docs/
    ├── design.md
    ├── memory-layer-design.md
    └── memory-layer-prompt.md
```

## コーディング規約

### Python スタイル
- Python 3.11+ の機能を積極利用（`str | None`, `match-case` 等）
- 型ヒントを全関数に記述
- docstring は Google style
- フォーマッター: ruff
- リンター: ruff
- テスト: pytest

### 命名規則
- モジュール: snake_case
- クラス: PascalCase
- 関数/変数: snake_case
- 定数: UPPER_SNAKE_CASE
- MCP ツール名: `pm_` プレフィクス（例: `pm_status`, `pm_add_task`）

### エラーハンドリング
- カスタム例外クラス: `PmServerError`, `ProjectNotFoundError`, `TaskNotFoundError`, `DecisionNotFoundError`
- MCP ツールはエラー時に明確なメッセージを返す
- YAML パースエラーは `PmServerError` にラップして伝播

### YAML 規約
- `pyyaml` の `safe_load` / `safe_dump` のみ使用
- 出力は `default_flow_style=False`, `allow_unicode=True`, `sort_keys=False`
- ファイル先頭にコメントヘッダーを付与

### テスト規約
- 各モジュールに対応する test ファイルを作成
- `tmp_path` fixture で一時ディレクトリを使用
- 正常系・異常系・エッジケースを網羅
- テストデータは conftest.py に fixture として定義

## セキュリティ上の注意

- YAML は `safe_load` のみ（任意コード実行を防止）
- installer.py は既存の settings.json の他のキーを絶対に壊さない
- ファイルパスは `resolve()` で正規化（パストラバーサル防止）
- subprocess に `shell=True` を使用しない
- Jinja2 テンプレートは `autoescape` 有効

## よくある間違い

- ❌ `yaml.load()` を使う → ✅ `yaml.safe_load()` を使う
- ❌ `Path("~/.pm")` → ✅ `Path.home() / ".pm"` or `Path("~/.pm").expanduser()`
- ❌ settings.json を丸ごと上書き → ✅ 必要なキーのみ追加
- ❌ project_path を必須引数にする → ✅ オプションにして自動検出
- ❌ タスクIDをユーザーに手入力させる → ✅ 自動採番

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

<!-- synaptic-ledger:begin v=1 -->
## Synaptic Ledger 自動行動ルール

### 知識の記録
- 重要なパターン・解決策を発見したら `synaptic_add` で記録する
- セッション中の作業メモは `synaptic_remember` で素早くキャプチャ

### セッション管理
- 作業開始時: `synaptic_session_start` でゴールを設定
- 判断・タスクの記録: `synaptic_session_log`
- Compaction後の復元: `synaptic_session_restore`

### 検索・想起
- コンテキストが必要なら `synaptic_recall` で取得
- 詳細な多面検索は `synaptic_multisearch` を使用

### キュレーション
- 重要な知識は `synaptic_curate` で品質検証してから保存
<!-- synaptic-ledger:end -->
