# pm-server クロスチェック依頼

以下のプロジェクトのクロスチェックを実施してください。

## プロジェクト概要

pm-server は Claude Code 用のプロジェクト管理 MCP Server です。
Python / FastMCP で構築し、15 の MCP ツール + CLAUDE.md 自動管理機能を提供します。
GitHub 公開（MIT ライセンス）+ PyPI 公開を予定しています。

## 確認すべきドキュメント

以下を順に読んでからクロスチェックしてください:

1. `docs/design.md` — 設計書 v0.3.0（アーキテクチャ、データモデル、全ツール仕様）
2. `README.md` — 英語版 README（公開用）
3. `README.ja.md` — 日本語版 README
4. `pyproject.toml` — パッケージ定義
5. `src/pm_server/` — ソースコード全体（特に server.py, claudemd.py, installer.py）
6. `tests/` — テストスイート
7. `CLAUDE.md` — プロジェクト自身の Claude Code 設定
8. `CHANGELOG.md` — 変更履歴
9. `LICENSE` — ライセンスファイル

## 特に注意してほしいポイント

### 1. パッケージリネーム（pm-agent → pm-server）の完全性
- `pm_agent` / `pm-agent` / `PmAgentError` の残存がないか
- 意図的な残存（migrate 関数内、CHANGELOG 内）は許容

### 2. CLAUDE.md 自動管理機能（新機能）
- `claudemd.py` のマーカー方式の堅牢性
- `pm_init` → `ensure_claudemd` の統合が正しいか
- `pm_update_claudemd` MCP ツールの動作
- エッジケース: マーカー破損、エンコーディング、既存内容の保持

### 3. installer.py の安全性
- `subprocess.run` で `claude mcp add/remove` を呼ぶ方式の安全性
- `shutil.which()` で実行パスを取得する方式の信頼性
- `migrate_from_pm_agent()` のエラーハンドリング

### 4. セキュリティ
- `pm_discover` のデフォルトスキャンパス（現在 `"~"`）
- YAML 読み込みに `safe_load` を使っているか
- registry.yaml に機密情報が含まれないか
- subprocess 呼び出しのインジェクションリスク

### 5. 設計書と実装の整合性
- `docs/design.md` v0.3.0 と実際のコードに矛盾がないか
- README に書かれている機能が実際に動作するか
- MCP ツールの数（README では15と記載、実際は16個になっているはず）

### 6. PyPI 公開の準備状況
- `pyproject.toml` の必須フィールド（description, license, requires-python, classifiers）
- `[project.scripts]` のエントリポイント
- `.gitignore` に不要ファイルが含まれているか

### 7. テストの網羅性
- 133テストの内訳とカバレッジ
- テストの registry 隔離（本番の `~/.pm/` を汚染しないか）
- claudemd.py のエッジケーステスト

## 出力形式

cross-check スキルのフォーマットに従って出力してください:
- 🔴 Critical（即対応必要）
- 🟡 High（早期対応推奨）
- 🟢 確認済み・問題なし
- 📋 アクションリスト
