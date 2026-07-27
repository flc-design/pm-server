# 日本語 FTS ベースライン計測レポート（PMSERV-143 / ADR-039 T5）

- 対象: `MemoryStore.search_ex()`（`src/pmlens/memory.py`）— FTS5 (`tokenize='unicode61'`) →
  0件時に LIKE フォールバック（`content LIKE ? ESCAPE '\' OR tags LIKE ? ESCAPE '\'`、`%`/`_` エスケープ済み）
- 再現テスト: `tests/test_memory_ja_fts.py`（`KNOWN_BASELINE` に対する固定 assert。改善したら更新する運用）
- 計測環境: `sqlite3.sqlite_version = 3.51.0`（Python `sqlite3` 標準ライブラリ経由）。
  **FTS5 unicode61 のトークナイズ挙動は SQLite バージョンで揺れうる**ため、別環境でこのレポートの数値と
  ズレる場合は `tests/test_memory_ja_fts.py` を再実行し、`KNOWN_BASELINE` とこのレポートを実測値に合わせて
  更新すること（テストのassertを緩めて帳尻を合わせない）。
- 起票根拠: `docs/issues/ISSUE_desktop-outbox-one-way.md` P5（「経営戦略 2つのエンジン…」等の複合日本語クエリが
  cross_project 検索で 0 件になった実地インシデント、outbox_id:5）

## 計測方法

`docs/issues/ISSUE_desktop-outbox-one-way.md` の実障害クエリ（「経営戦略」「2つのエンジン」「引き継ぎ」）を含む、
複合語・かな交じり・英日混在を含む日本語メモ 15 件を golden corpus としてローカル `MemoryStore` に保存し
（`tests/test_memory_ja_fts.py::GOLDEN_CORPUS`）、23 個のクエリで `search_ex()` を実行して
`(strategy, hit有無, 件数)` を実測した。true negative コントロール（コーパスに存在しない語・LIKE フォール
バックでも救えない複合語 AND クエリ）を意図的に含め、再現率を実態より高く見せないようにしている。

## 結果（クエリ別）

| クエリ | strategy | hit | 件数 | 備考 |
|---|---|---|---|---|
| 経営戦略 | like_fallback | ✅ | 2 | 文中で助詞に接続され孤立トークンにならない典型例（ISSUE P5 の再現） |
| 2つのエンジン | fts | ✅ | 2 | 括弧/行頭で区切られ単独トークン化されたため直撃 |
| 引き継ぎ | fts | ✅ | 1 | |
| FTS5 | fts | ✅ | 1 | |
| unicode61 | like_fallback | ✅ | 1 | |
| 機械学習 | fts | ✅ | 1 | 「」で囲まれ孤立トークン化 |
| デスクトップ | fts | ✅ | 1 | |
| PMSERV-143 | fts | ✅ | 1 | |
| cross_project | fts | ✅ | 1 | |
| にっぽん | fts | ✅ | 1 | 「」で囲まれ孤立トークン化 |
| アーキテクチャ | fts | ✅ | 2 | |
| outbox | fts | ✅ | 1 | |
| refactor | fts | ✅ | 1 | |
| ADR-028 | like_fallback | ✅ | 1 | |
| ロードマップ | fts | ✅ | 1 | |
| 自然言語処理 | fts | ✅ | 1 | 「」で囲まれ孤立トークン化 |
| 表記ゆれ | fts | ✅ | 1 | tags列がカンマ区切り（ASCII区切り文字）のため孤立トークン化してヒット |
| ハイブリッド設計 | like_fallback | ✅ | 1 | 文中に埋め込まれ孤立トークンにならない |
| セッション継続 | like_fallback | ✅ | 1 | 同上 |
| 引き継ぎ 経営戦略 | like_fallback | ✅ | 1 | **PMSERV-175 で 0→1**。両語が同一行に非隣接で存在するケース。旧実装（クエリ全体を1リテラル）では 0 だった |
| 経営戦略 2つのエンジン | like_fallback | ❌ | 0 | **真の未ヒット**。両語ともコーパスに存在するが**別々の行**にあり、AND を満たす行が無い（PMSERV-175 後も 0 のまま = AND が本物の論理積である証拠） |
| 検索エンジン | like_fallback | ❌ | 0 | **真の未ヒット**（コーパスに当該語が存在しない） |
| 存在しない用語XYZ | like_fallback | ❌ | 0 | ネガティブコントロール |
| OAuth認証 | like_fallback | ❌ | 0 | ネガティブコントロール |

## 集計

- 総クエリ数: 24
- FTS5単独でのヒット数: 14/24 （約 58.3%）
- FTS5 + LIKEフォールバック合算でのヒット数: 20/24 （約 83.3%）
- **LIKEフォールバックによる改善**: +6クエリ（+25.0ポイント）— 5件は「文中に助詞・接続語を挟んで埋め込まれ、
  unicode61 が単独トークンとして切り出せなかった複合語」の救済（「経営戦略」「unicode61」「ADR-028」
  「ハイブリッド設計」「セッション継続」）、1件（「引き継ぎ 経営戦略」）は PMSERV-175 の語分割 AND 化による
  複数語クエリの救済
- フォールバック後も未ヒットのまま: 4/24 — うち3件はコーパスに元々存在しない語（ネガティブコントロール）、
  1件（「経営戦略 2つのエンジン」）は両語が別々の行にあり AND を満たす行が存在しない真の未ヒット
- **FTS 単独の 14 件は PMSERV-175 で変動していない**。この変更はフォールバックのみを広げたので、
  FTS 単独数が動いたらそれは改善ではなくトークナイザの挙動変化を意味する（テストで固定済み）

## 観察された失敗モード（unicode61 の挙動)

`memories_fts` は `tokenize='unicode61'` を使用しており、句読点・カッコ・ASCIIスペース等の区切り文字が無い限り、
連続する漢字・かな・カタカナの並びは**1つの巨大トークン**として扱われる。日本語は分かち書き（単語間スペース）
をしないため、文中に自然に埋め込まれた複合語（例:「経営戦略セッションで…」の「経営戦略」）は、文全体（または
句読点区切りの節全体）を覆う1つのトークンの一部でしかなく、クエリ側の「経営戦略」という短いトークンとは
完全一致しない → MATCH 失敗、という構造的な取りこぼしが起きる。

一方で、次のケースは孤立トークン化されFTS5で直撃する:
- クエリ語が「」括弧・句読点・行頭/行末などのASCII/記号区切り文字に隣接している場合（「2つのエンジン」「機械学習」等）
- tags 列はカンマ区切り（`_tags_to_str` がASCIIカンマで結合）で保存されるため、タグとして登録された複合語は
  区切り文字に挟まれ孤立トークン化されやすく、content列より仮名文字列の複合語検索に強い

LIKEフォールバックはこの構造的な取りこぼしに対する**計測された安全網**であり、根本修正（トークナイザー変更）
ではない。

## PMSERV-175 — 安全網が「最も必要な場面」で機能していなかった問題の修正

### 動機（実インシデント）

別プロジェクト（WFLLM）のセッションが `pm_memory_search` / `pm_recall(query=...)` で 0 件を得て
「検索経路の不調」と誤認し、`.pm/memory.db` を sqlite3 で直読みして回避、さらにその未検証の断定を memory に
書き込んだ。切り分け調査（2026-07-27）の結果、索引は健全（`memories_fts` 行数 = `memories` 行数）で
挙動は仕様どおりと確定した。しかし調査の過程で、**安全網の設計意図と実効性の乖離**が明らかになった:

- 旧実装のフォールバックは `pattern = f"%{query}%"` で**クエリ文字列全体を 1 個のリテラルとして部分一致**させ、
  語分割も AND もしていなかった
- 日本語で FTS が落ちるのはまさに複合語・複数語のケースなので、**安全網が最も必要な場面でだけ機能しない**
- 実例: `egress ホスティング形態` は両語とも同一 memory に存在するのに 0 件。本文が
  「ホスティング形態でegress宣言」と逆順・空白なしで、連続部分文字列として存在しないため

### 変更内容

1. **語分割 AND 化**: クエリを `_split_query_terms()` で語に分割し、各語に
   `(content LIKE ? OR tags LIKE ?)` を 1 節ずつ与えて AND 結合する。分割規則は `_sanitize_fts_query` と
   **同一の `_QUERY_TOKEN_RE` を共有**する（別実装にすると FTS 経路と語の切れ目がズレ、報告する
   `matched_terms` が「FTS が実際に試した分割」と食い違って誤誘導になる）。引用符付きフレーズは 1 語のまま。
2. **診断情報の追加**: `SearchDiagnostics`（`strategy` / `fallback_reason` / `matched_terms` /
   `unmatched_terms` / `dropped_terms`）を新設し、`search_full()` / `search_global_full()` が返す。
   `search_ex()` / `search_global_ex()` は**シグネチャ不変のまま薄い委譲**に変更（後方互換）。
3. **語数上限**: `_MAX_FALLBACK_TERMS = 12`。超過分は `dropped_terms` で報告し、サイレントに切り捨てない。
4. **共通化**: per-project と cross-project は `_like_fallback()` を共有する。両者は同じ理由
   （unicode61 対 CJK）で縮退するので、同じ挙動で縮退しなければならない。

### 効果（実データ = WFLLM の `.pm/memory.db` 複製に対する実測）

| クエリ | 変更前 | 変更後 |
|---|---|---|
| `egress ホスティング形態` | 0 件 | **1 件（id=5）** |
| `egress 粒度` | 0 件（理由不明） | 0 件 + `unmatched_terms=['粒度']` |
| 元の失敗クエリ（8語） | 0 件（理由不明） | 0 件 + `unmatched_terms=['粒度']`（他 7 語は matched） |

最後の行が本変更の核心。元の失敗クエリは「**`粒度` を外せば当たる**」と機械可読に自己申告するようになった。

### 0 件の 2 つの意味を呼び出し側が区別できるようになった

- `unmatched_terms` が非空 → その語がストアのどこにも無い。**外して再試行すればよい**
- `unmatched_terms` が空なのに 0 件 → 全語が存在するが**単一の memory に共起しない**。語を減らす

`fallback_reason` は `fts_no_match`（MATCH が空でフォールバックが走った）/ `global_index_absent` /
`fts_error`。後者2つは後方互換のため `strategy="fts"` のままなので、`fallback_reason` が**唯一の識別手段**。

## クロスプロジェクト計測（PMSERV-153, ADR-039 followup）

PMSERV-143 では別 issue 送りとしていた `search_global`（cross_project 横断検索）の日本語計測 + LIKE
フォールバック適用を、PMSERV-153 で実施した。

- 対象: `MemoryStore.search_global_ex(query, limit=...) -> tuple[list[dict], str]` を新設
  （`src/pmlens/memory.py`）。グローバル索引 `memory_index_fts` も per-project の `memories_fts` と同じ
  `tokenize='unicode61'` を使うため、`search_ex` と同じ FTS→LIKE フォールバック（`content LIKE ? ESCAPE '\'
  OR tags LIKE ? ESCAPE '\'`）を持たせた。既存 `search_global()` はシグネチャ不変のまま
  `search_global_ex(...)[0]` への薄い委譲に変更（後方互換）。
- 計測: golden corpus（同一 15 件）をグローバル索引へ同期し、per-project と同じ 24 クエリで `search_global_ex`
  を実測（`tests/test_memory_ja_fts.py::TestJapaneseGoldenBaselineCrossProject`）。
- 結果: **全 24 クエリで per-project ベースライン（上表）と strategy・hit・件数が完全一致（乖離 0）**。
  同一コーパス・同一トークナイザ・同一フォールバックであり、グローバル索引が追加で持つ `project` 列
  （本コーパスでは全行 `"pm-server"`）は日本語クエリにヒットしないため。集計も同一（FTS 単独 14/24 ≈ 58.3%、
  フォールバック込み 20/24 ≈ 83.3%）。PMSERV-175 で両者は `_like_fallback()` を共有する実装になったため、
  この parity は「たまたま一致している」から「構造的に一致する」へ強化された（診断情報の一致もテストで固定）。
- テスト戦略: 24 個の数値を複製せず「per-project `search_ex` との parity」を assert する。両索引は unicode61 が
  SQLite バージョンで揺れても連動して動くため、parity が rot しない固定になる（絶対再現率 20/24・14/24 は
  集計テストで別途固定）。
- ISSUE P5 の実障害（outbox_id:5「経営戦略 2つのエンジン…」）はこの cross_project 経路で発生していたが、
  「経営戦略」単体は LIKE フォールバックで救済される（hit=2）ようになった。複数語クエリ
  「経営戦略 2つのエンジン」は PMSERV-175 後も未ヒットだが、理由が変わった: もはや「フォールバックが複数語を
  扱えない」からではなく「**両語が別々の行にあり AND を満たす行が無い**」から。`matched_terms` に両語が並び
  `unmatched_terms` が空になるので、呼び出し側はその区別を応答から読み取れる。

## スコープ外（明記）

- **trigram tokenizer への移行は本タスクの対象外**（ADR-039 AD-8、C16 → PMSERV-150 として別 issue 化）。
  インデックスサイズの倍増・SQLiteバージョン依存・RO Lens 経路との互換性まで波及するため。今回計測した再現率
  （FTS単独 58.3% / フォールバック込み 83.3%、per-project / cross-project 共通）が、trigram 移行の投資判断材料になる。
  なお PMSERV-175 の語分割 AND 化は **trigram 移行なしで再現率を上げる安価な改善**であり、PMSERV-150 の
  代替ではなく前倒しの部分解。trigram が解くのは「FTS 単独 58.3%」の側であって、フォールバック側ではない。

## 実装への反映

- `MemoryStore.search_ex(query, type=None, limit=...) -> tuple[list[Memory], str]` を新設
  （`src/pmlens/memory.py`）。既存 `search()` はシグネチャ不変のまま `search_ex(...)[0]` への薄い委譲に変更。
- `pm_recall` のクエリ経路、`pm_memory_search` を `search_ex` に切り替え、レスポンスへ additive キー
  `search_strategy`（`"fts"` | `"like_fallback"`）を追加。
- `type` フィルタは FTS・LIKE いずれの分岐でも既存 `search()` と同じ「LIMIT 適用後のポストフィルタ」のまま
  変更していない（挙動の一貫性を優先）。
- **PMSERV-175 追加分**: `MemoryStore.search_full()` / `search_global_full()` を新設し
  `-> tuple[..., SearchDiagnostics]` を返す。`search_ex()` / `search_global_ex()` は 2-tuple のまま
  薄い委譲へ（既存の呼び出し側・テストは 1 行も変更不要）。`pm_recall` / `pm_memory_search` は
  additive キー `fallback_reason` / `matched_terms` / `unmatched_terms` / `dropped_terms` を返す。
  これらは情報を持つときだけ現れる（FTS 直撃時は `search_strategy` のみで従来と同一形状）。
- ツール説明（MCP から見える docstring）にも呼び出し指針を明記した。今回のインシデントの真因は
  「文書が無い」ではなく「**文書の高度が間違っていた**」こと — 挙動は本レポート・ゴールデンテスト・
  実装 docstring の 3 箇所に既出だったが、呼び出し側エージェントが実行時に見る唯一の面には無かった。
