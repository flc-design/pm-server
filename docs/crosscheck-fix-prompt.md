# pm-server クロスチェック指摘事項 一括修正

クロスチェックで発見された全12件を修正してください。

## 事前確認

- `pytest` が 133 テスト全パスすること
- `git status` がクリーンであること（未コミット変更なし）

---

## 🔴 Critical（5件）

### C-1: storage.py の _yaml_header が "PM Agent" のまま

`src/pm_server/storage.py` の `_yaml_header` 関数:

```python
# 変更前
return f"# PM Agent - {filename}\n"

# 変更後
return f"# PM Server - {filename}\n"
```

### C-2: dashboard_portfolio.html の <title> が旧名

`src/pm_server/templates/dashboard_portfolio.html`:

```html
<!-- 変更前 -->
<title>PM Agent — Portfolio Dashboard</title>

<!-- 変更後 -->
<title>PM Server — Portfolio Dashboard</title>
```

ファイル内に他にも `PM Agent` がないか `grep` で確認し、あれば全て `PM Server` に修正。

### C-3: test_storage.py のヘッダーアサーション

`tests/test_storage.py` の該当行:

```python
# 変更前
assert content.startswith("# PM Agent - project.yaml")

# 変更後
assert content.startswith("# PM Server - project.yaml")
```

同ファイル内に他にも `"PM Agent"` 文字列がないか確認し、あれば修正。

### C-4: test_storage.py のメソッド名

```python
# 変更前
def test_broken_yaml_raises_pm_agent_error(...)

# 変更後
def test_broken_yaml_raises_pm_server_error(...)
```

### C-5: pm_discover MCP ツールのデフォルトパスが "~"

`src/pm_server/server.py` の `pm_discover`:

```python
# 変更前
def pm_discover(scan_path: str = "~") -> dict:

# 変更後
def pm_discover(scan_path: str = ".") -> dict:
```

---

## 🟡 High（7件）

### H-6: uninstall_mcp() に --scope user 欠落

`src/pm_server/installer.py` の `uninstall_mcp()`:

subprocess の引数に `"--scope", "user"` を追加して install_mcp() と対称にする。

### H-7: migrate_from_pm_agent() の不整合修正

`src/pm_server/installer.py` の `migrate_from_pm_agent()`:

1. 裸の `"claude"` → `shutil.which("claude")` で絶対パス取得（install_mcp と統一）
2. `subprocess.run` に `timeout=10` を追加
3. `shutil.which("claude")` が None の場合のエラーハンドリング追加

### H-8: ドキュメントのツール数を 15 → 16 に更新

以下のファイルで MCP ツール数を更新し、`pm_update_claudemd` を追記:

**README.md**:
- "15 MCP tools" → "16 MCP tools"
- MCP Tools テーブルに pm_update_claudemd を追加（Discovery セクションの後、または新セクション「Maintenance」として）
- CLI Commands に `pm-server update-claudemd` を追加

**README.ja.md**:
- "15の MCP ツール" → "16の MCP ツール"
- 同様にテーブルと CLI に追記

**CLAUDE.md**:
- ツール数の記載があれば更新

**docs/design.md**:
- Section 4.1 のツール一覧に `pm_update_claudemd` を追加
- Section 4.2 の CLI に `update-claudemd` を追加
- Section 8.1 の pyproject.toml 例の version を "0.2.0" に修正

### H-9: pyproject.toml に classifiers 追加

```toml
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
]
```

### H-10: pyproject.toml に dev extras 追加

```toml
[project.optional-dependencies]
dev = ["pytest", "ruff"]
```

### H-11: pm_update_claudemd と update-claudemd CLI のテスト追加

**tests/test_server.py** に追加（既存の server テストに合わせる）:

```python
def test_pm_update_claudemd_creates_new(pm_project):
    """pm_update_claudemd creates CLAUDE.md when it doesn't exist."""
    result = pm_update_claudemd(project_path=str(pm_project))
    assert result["status"] == "updated"
    assert "created" in result["message"]
    assert (pm_project / "CLAUDE.md").exists()

def test_pm_update_claudemd_updates_existing(pm_project):
    """pm_update_claudemd updates existing CLAUDE.md."""
    # 初回
    pm_update_claudemd(project_path=str(pm_project))
    # 2回目
    result = pm_update_claudemd(project_path=str(pm_project))
    assert result["status"] == "updated"
    assert result["after"]["up_to_date"] is True
```

**tests/test_claudemd.py** に追加:

```python
def test_corrupted_begin_only_appends_clean(self, project_dir):
    """begin マーカーのみで end がない場合、古い残骸を含まない形で追記する。"""
    content = "# Header\n\n<!-- pm-server:begin v=0 -->\nold rules without end marker\n\n# Footer\n"
    (project_dir / "CLAUDE.md").write_text(content)
    update_claudemd(project_dir)
    new_content = (project_dir / "CLAUDE.md").read_text()
    assert "# Header" in new_content
    assert "# Footer" in new_content
    assert f"v={TEMPLATE_VERSION}" in new_content
```

### H-12: 破損マーカー時の残骸処理改善

`src/pm_server/claudemd.py` の `_replace_pm_section`:

begin マーカーはあるが end マーカーがない場合、begin マーカーとその下の内容を削除してから新テンプレートを挿入する。

```python
def _replace_pm_section(claude_md: Path, content: str, template: str) -> str:
    begin_match = BEGIN_PATTERN.search(content)
    end_idx = content.find(END_MARKER)

    if begin_match and end_idx != -1:
        # 正常: begin と end の間を差し替え
        before = content[:begin_match.start()]
        after = content[end_idx + len(END_MARKER):]
        new_content = before + template + after
        claude_md.write_text(new_content, encoding="utf-8")
        old_version = int(begin_match.group(1))
        return f"updated PM Server rules in CLAUDE.md (v{old_version} → v{TEMPLATE_VERSION})"

    if begin_match and end_idx == -1:
        # 破損: begin はあるが end がない → begin 以降を削除して置換
        before = content[:begin_match.start()]
        new_content = before.rstrip() + "\n\n" + template + "\n"
        claude_md.write_text(new_content, encoding="utf-8")
        return "replaced corrupted PM Server section in CLAUDE.md"

    # マーカーなし → フォールバック（末尾追記）
    separator = _separator_for(content)
    claude_md.write_text(content + separator + template + "\n", encoding="utf-8")
    return "appended PM Server rules to CLAUDE.md (no markers found)"
```

注意: この変更は破損マーカーの場合に begin 以降の全内容を削除するため、ユーザーが begin の後に書いた内容が消える。しかし、end マーカーがない状態は明らかに破損なので、この動作は許容される。テストで挙動を確認すること。

---

## ガード & 制約

- 既存テスト 133 件を壊さない
- MCP ツール名 `pm_` プレフィックスは維持
- `.pm/` ディレクトリのデータ構造は変更しない
- README の既存セクション構成を大きく変えない（テーブルに行を追加する程度）

## テスト（検証手順）

1. `ruff check src/ tests/` — エラーなし
2. `ruff format --check src/ tests/` — フォーマット済み
3. `pytest -v` — 全テストパス（133 + 新規テスト）
4. `grep -rn "PM Agent" src/` — 残存が installer.py の migrate 関数内のみであること
5. `grep -rn "pm_agent\|pm-agent" src/` — 意図的残存（migrate 関数）以外がないこと
6. `pm-server --help` — install, uninstall, serve, discover, status, migrate, update-claudemd の 7 コマンド
