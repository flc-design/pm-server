# pm-server

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)

**[English README](README.md)**

**Claude Code 用プロジェクト管理 MCP Server**

タスク管理・進捗可視化・意思決定記録を、Claude Code セッション内の自然言語で。

```
> 進捗は？
✓ Phase 1 "Backend API": 60% 完了 (12/20 タスク)
  - 3件 作業中、1件 ブロック中
  - ベロシティ: 8 タスク/週 (↑ 上昇傾向)

> 次にやること
1. [P0] MYAPP-014: ユーザー認証エンドポイントの追加
2. [P1] MYAPP-015: レートリミット実装
3. [P1] MYAPP-018: インテグレーションテスト作成

> MYAPP-014 に着手
✓ MYAPP-014 → in_progress
```

---

## 特徴

- **23の MCP ツール** — タスク CRUD、子イシュー、ステータス、ブロッカー、ベロシティ、ダッシュボード、ADR、セッションメモリ等
- **セッションメモリ** — SQLite + FTS5 全文検索。記憶はセッションを跨いで永続化し、タスク・決定に紐付け可能
- **横断検索** — グローバルインデックスを使って全プロジェクトの記憶を横断検索
- **自然言語で操作** — 「進捗は？」「次にやること」と言うだけ
- **ゼロ設定** — `pip install` + `pm-server install` で完了。あとは「PM初期化して」と言うだけ
- **マルチプロジェクト** — グローバルレジストリで全プロジェクトを横断管理
- **Git フレンドリー** — `.pm/` ディレクトリにプレーン YAML で保存、`git diff` で追跡可能
- **非侵入的** — プロジェクトに `.pm/` を追加するだけ。`rm -rf .pm/` で完全除去

---

## クイックスタート

### インストール（初回のみ）

```bash
pip install pm-server
pm-server install       # Claude Code に MCP サーバーを登録
# Claude Code を再起動
```

### アップデート

```bash
pip install --upgrade pm-server
# Claude Code を再起動
```

> **注意:** `pip install pm-server`（`--upgrade` なし）では既存バージョンは更新されません。最新版にするには必ず `--upgrade`（または `-U`）を付けてください。

アップグレード後、各プロジェクトの CLAUDE.md 自動行動ルールは自動的に更新されます:

1. 次のセッション開始時に `pm_status` がテンプレートバージョンの不一致を検出
2. Claude Code が `pm_update_claudemd` を実行してルールセクションを更新
3. 新機能（子イシューワークフロー等）が即座に有効化

手動で更新することもできます:
```
> CLAUDE.md を更新して    # または: pm_update_claudemd
```

### プロジェクト初期化

```
# Claude Code で対象プロジェクトに cd して
> PM初期化して
✓ .pm/ 作成
✓ グローバルレジストリに登録
✓ 検出: name=my-app, version=1.2.0 (package.json から)
```

`package.json`、`pyproject.toml`、`Cargo.toml`、`.git/config`、`README.md` からプロジェクト情報を自動検出します。

### 使い方

| 発話例 | 実行される処理 |
|---|---|
| `進捗は？` | プロジェクトの進捗サマリを表示 |
| `次にやること` | 優先度・依存関係から推薦タスクを表示 |
| `タスク追加：○○を実装` | 新規タスク追加（ID自動採番） |
| `MYAPP-003 完了` | タスクを done に更新 |
| `MYAPP-003 に課題がある` | タスクに子イシューを追加（phase 自動継承） |
| `ブロッカーある？` | ブロック中のタスクを一覧表示 |
| `ダッシュボード見せて` | HTML ダッシュボード生成（Chart.js、ダークテーマ） |
| `この設計にした理由を記録` | ADR（Architecture Decision Record）を追加 |
| `全プロジェクトの状態` | プロジェクト横断ポートフォリオビュー |

---

## MCP ツール一覧（23ツール）

### プロジェクト管理

| ツール | 説明 |
|---|---|
| `pm_init` | `.pm/` 作成 + レジストリ登録 + プロジェクト情報推定 |
| `pm_status` | フェーズ進捗、タスク集計、ブロッカー、ベロシティ |
| `pm_tasks` | タスク一覧（status / phase / priority / tag でフィルタ） |
| `pm_add_task` | タスク追加（ID自動採番: `MYAPP-001` 形式） |
| `pm_update_task` | ステータス・優先度・ノート・blocked_by を更新 |
| `pm_next` | 推薦タスク（blocked / 依存未完了を除外） |
| `pm_blockers` | ブロック中のタスクを全プロジェクトから一覧 |
| `pm_add_issue` | タスクに子イシューを追加（phase 自動継承、親タスクは自動で review に戻る） |

### 記録

| ツール | 説明 |
|---|---|
| `pm_log` | 日次ログ記録（progress / decision / blocker / note / milestone） |
| `pm_add_decision` | ADR 追加（context、decision、consequences を構造化） |

### 分析

| ツール | 説明 |
|---|---|
| `pm_velocity` | 週次ベロシティ + トレンド判定（上昇 / 下降 / 横ばい） |
| `pm_risks` | リスク自動検知：期限超過、長期未更新、長期ブロック |

### 可視化

| ツール | 説明 |
|---|---|
| `pm_dashboard` | HTML ダッシュボード（単体プロジェクト or ポートフォリオ） |

### ディスカバリー

| ツール | 説明 |
|---|---|
| `pm_discover` | ディレクトリ配下の `.pm/` プロジェクトをスキャン・自動登録 |
| `pm_cleanup` | レジストリの無効パスを除去 |
| `pm_list` | 登録プロジェクト一覧 |

### メモリ（セッション継続）

| ツール | 説明 |
|---|---|
| `pm_remember` | セッションに紐付く記憶を保存（observation / insight / lesson） |
| `pm_recall` | 記憶を呼び出し — FTS5 検索、タスク別、横断検索に対応 |
| `pm_session_summary` | セッション要約の保存・取得・一覧 |
| `pm_memory_search` | type・tag・task_id フィルター付き高度な検索 |
| `pm_memory_stats` | メモリ DB の統計情報（件数・種別・DB サイズ） |
| `pm_memory_cleanup` | 古い記憶のクリーンアップ（dry-run 対応） |

### メンテナンス

| ツール | 説明 |
|---|---|
| `pm_update_claudemd` | CLAUDE.md の PM Server ルールセクションを最新版に更新 |

---

## データ構造

タスクデータはプレーン YAML、記憶は SQLite で保存:

```
your-project/
└── .pm/
    ├── project.yaml        # プロジェクトメタ情報
    ├── tasks.yaml          # タスク（ステータス・優先度・依存関係）
    ├── decisions.yaml      # ADR (Architecture Decision Records)
    ├── milestones.yaml     # マイルストーン定義
    ├── risks.yaml          # リスク・ブロッカー
    ├── memory.db           # セッション記憶（SQLite + FTS5）
    └── daily/
        └── 2026-04-08.yaml # 日次ログ（自動生成）

~/.pm/
├── registry.yaml           # グローバルプロジェクトインデックス
└── memory.db               # 横断検索用メモリインデックス
```

YAML ファイルは人間が読め、手動編集しても壊れません。メモリ DB はセッションデータの正本で、`~/.pm/memory.db` が横断検索を可能にします。

---

## CLAUDE.md 統合

プロジェクトの `CLAUDE.md` に以下を追加すると、セッション中の PM 操作が自動化されます（`pm-server update-claudemd` で自動追加も可能）:

```markdown
## PM Server 自動行動ルール（必ず従うこと）

### セッション開始時（最初の応答の前に必ず実行）
1. pm_status を MCP ツールとして実行し、現在の進捗を表示する
2. pm_next で次に着手すべきタスクを3件表示する
3. pm_recall で前回セッションの文脈を取得する
4. ブロッカーや期限超過があれば警告する
5. pm_status の claudemd.other_rule_sections に他のルールセクションが報告された場合、この CLAUDE.md 内の該当セクションのルールも全て実行する

### タスクに着手する前
1. 該当タスクを pm_update_task で in_progress に変更する

### 作業中に重要な発見・判断があった時
1. pm_remember で記憶を保存する（関連タスクIDがあれば task_id で紐付け）

### コンテキスト保全（Compaction / Clear 対策）
Claude Code はセッションが長くなるとコンテキストを自動圧縮（compaction）する。
圧縮のタイミングは予測できないため、重要な情報は随時保存すること。
1. 重要な発見・技術的判断は発生時点で即座に pm_remember で保存する（セッション終了を待たない）
2. 複雑な議論や設計検討の後は、結論を pm_remember でまとめて保存する
3. 3往復以上のやり取りで未記録の知見があれば、チェックポイントとして pm_remember で保存する
4. ユーザーが /clear する前は必ず pm_session_summary を実行する
5. Compaction 後にコンテキストが失われていると感じたら pm_recall で復元する

### タスク完了時（コードが動作確認できたら）
1. pm_update_task で done に変更する
2. all_issues_resolved フラグが返された場合、親タスクの完了もユーザーに提案する
3. pm_log に完了内容を記録する
4. 次の推薦タスクを pm_next で表示する
5. アトミックコミットを作成する

### タスク完了確認中にイシュー（課題）が見つかった時
1. pm_add_issue で親タスクに紐づくイシュー（子タスク）を作成する
   - phase は親タスクから自動継承される
   - 親タスクが done だった場合、自動で review に戻される
2. イシューを解消したら pm_update_task で done に変更する
3. 全イシューが解消されると all_issues_resolved フラグが返される
4. 親タスクの完了をユーザーに提案する

### 設計上の意思決定が発生した時
1. ユーザーに「ADRとして記録しますか？」と確認する
2. 承認されたら pm_add_decision で保存する

### コーディングセッション終了時
1. 進行中のタスクの状態を確認し、必要に応じて更新する
2. pm_log にセッションの成果を記録する
3. pm_session_summary で要約を保存する
4. 未コミットの変更があればコミットする
```

---

## Tips: pm-server を最大限に活用するために

### 推奨ワークフロー

```
1. インストール＆登録      →  pip install pm-server && pm-server install
2. Claude Code を起動      →  (インストール後に再起動)
3. プロジェクト初期化      →  「PM初期化して」
4. タスク追加              →  「タスク追加：ユーザー認証を実装」
5. タスクに着手            →  「MYAPP-001 に着手」
6. タスク完了              →  「MYAPP-001 完了」
7. レビューで課題発見      →  「MYAPP-001 に課題がある：…」（子イシュー作成）
8. セッション終了          →  「セッションまとめて」（要約＋ログを自動保存）
```

### Compaction（コンテキスト圧縮）対策

Claude Code はセッションが長くなると、会話のコンテキストを自動的に圧縮（compact）します。これにより、前半のやり取りの詳細が失われる場合があります。pm-server のメモリ機能でこれを防げます：

| 状況 | やるべきこと |
|---|---|
| 重要な発見をした | `pm_remember` で即座に記録 — セッション終了を待たない |
| 設計の議論が終わった | 結論を `pm_remember` でまとめて保存 |
| `/clear` する前 | 先に `pm_session_summary` を実行 |
| Compaction 後にコンテキストが薄い | `pm_recall` で前の文脈を復元 |
| 新しいセッションを開始 | `pm_recall` + `pm_status`（CLAUDE.md ルール設定済みなら自動） |

**基本原則:** 早めに、こまめに保存する。Compaction のタイミングは予測できません — 残す価値のある情報は、その場で記録しましょう。

### セッション継続性

pm-server のメモリ層が、セッション間の情報断絶を防ぎます：

```
セッション 1                          セッション 2
  │                                     │
  ├─ pm_remember（発見を記録）           ├─ pm_recall ← コンテキスト復元
  ├─ pm_remember（判断を記録）           ├─ pm_status ← 現在の状態
  ├─ pm_session_summary                 │
  └─ （セッション終了）                  └─ （シームレスに継続）
```

### マルチプロジェクト管理

```
> 「~/projects 以下のプロジェクトを探して」    # 自動スキャン＆登録
> 「全プロジェクトの状態」                      # ポートフォリオ一覧
> 「'auth' で横断検索して」                     # 全プロジェクト横断検索
> 「全プロジェクトのダッシュボード」             # ポートフォリオ HTML
```

---

## CLI コマンド

```bash
pm-server install          # Claude Code に MCP サーバーを登録
pm-server uninstall        # MCP サーバー登録を解除
pm-server serve            # MCP Server 起動（Claude Code が自動で呼び出す）
pm-server discover .       # .pm/ を持つプロジェクトをスキャン
pm-server status           # ターミナルからステータス確認
pm-server context-inject   # セッションコンテキストを stdout に出力（hook 連携用）
pm-server migrate          # pm-agent からの移行（MCP 登録の切り替え）
pm-server update-claudemd  # CLAUDE.md の PM Server ルールを更新
```

---

## アーキテクチャ

```
Claude Code Session
  │
  ├── CLAUDE.md 自動行動ルール
  │
  └── MCP Server (stdio)
        └── pm-server serve
              │
              ├── server.py    → 23 MCP ツール (FastMCP)
              ├── models.py    → Pydantic v2 データモデル
              ├── storage.py   → YAML 読み書き
              ├── memory.py    → SQLite メモリストア + FTS5 検索
              ├── recall.py    → セッションコンテキスト構築（トークン予算制御）
              ├── context.py   → CLI コンテキスト注入
              ├── velocity.py  → ベロシティ計算・リスク検知
              ├── dashboard.py → HTML/テキスト ダッシュボード (Jinja2)
              ├── discovery.py → プロジェクト情報自動推定
              └── installer.py → claude mcp add ラッパー
                    │
                    ├── project-A/.pm/ (YAML + memory.db)
                    ├── project-B/.pm/ (YAML + memory.db)
                    └── ~/.pm/registry.yaml + memory.db
```

---

## pm-agent からの移行

以前の `pm-agent` パッケージから移行する場合:

```bash
pip uninstall pm-agent
pip install pm-server
pm-server migrate       # MCP 登録を pm-agent → pm-server に切り替え
# Claude Code を再起動
```

`migrate` コマンドの実行内容:
- 旧 `pm-agent` の MCP 登録を解除
- 新 `pm-server` を MCP サーバーとして登録
- `~/.pm/registry.yaml` の整合性チェック
- `CLAUDE.md` 内の `pm-agent` への言及があれば警告

`.pm/` ディレクトリのデータは**そのまま使えます** — データ移行は不要です。

---

## 動作要件

- Python 3.11+
- Claude Code（MCP サポート付き）

### 依存パッケージ

- [FastMCP](https://github.com/jlowin/fastmcp) — MCP サーバーフレームワーク
- [Pydantic](https://docs.pydantic.dev/) v2 — データバリデーション
- [PyYAML](https://pyyaml.org/) — データ永続化
- [Click](https://click.palletsprojects.com/) — CLI フレームワーク
- [Jinja2](https://jinja.palletsprojects.com/) — ダッシュボードテンプレート

---

## 開発

```bash
git clone https://github.com/flc-design/pm-server.git
cd pm-server
pip install -e ".[dev]"
pytest                  # 260+ テスト
ruff check src/         # リント
ruff format src/        # フォーマット
```

---

## 設計原則

1. **Zero Configuration** — `pip install` + 1コマンドで完了
2. **Auto-everything** — 検出・登録・推定はすべて自動
3. **Git-friendly** — プレーンテキスト YAML、`git diff` で追跡可能
4. **Human-readable** — 手動編集しても壊れない
5. **AI-native** — Claude Code が自然に読み書きできるフォーマット
6. **Non-invasive** — `.pm/` を追加するだけ。プロジェクト構造を変更しない

---

## ライセンス

MIT — Shinichi Nakazato / FLC design co., ltd.
