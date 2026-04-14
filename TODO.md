# TODO

プロジェクトのタスク管理。完了したらチェックを入れる。

---

### 開発環境の起動方法
```bash
# 依存パッケージインストール
uv sync --all-extras

# Playwrightブラウザインストール（初回のみ）
uv run playwright install chromium

# 開発サーバー起動
uv run python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# ブラウザで http://localhost:8000 にアクセス
# 「Googleでログイン」ボタンをクリックして認証

# テスト実行
uv run pytest -v
```

---

## Phase 1: 基盤構築

- [x] プロジェクト初期化
  - [x] ~~shell.nix作成~~ → uvに移行のため削除
  - [x] ~~Dockerfile作成~~ → スコープ外（ローカルMac実行に限定）
  - [x] ~~docker-compose.yml作成~~ → スコープ外
  - [x] ~~requirements.txt作成~~ → `pyproject.toml`に一本化
  - [x] pyproject.toml作成（uv用に依存関係追加）
- [x] 基本ディレクトリ構成作成
  - [x] app/ディレクトリ作成
  - [x] tests/ディレクトリ作成
  - [x] state/ディレクトリ作成
- [x] FastAPI基本構成
  - [x] app/main.py作成
  - [x] app/config.py作成
  - [x] app/exceptions.py作成
- [x] リンター・型チェック設定
  - [x] ruff設定
  - [x] mypy設定（pydantic.mypyプラグイン追加）
- [x] Claude Code Hooks設定
  - [x] リンター自動実行Hook（uv run使用）

## Phase 2: テスト基盤

- [x] テスト環境構築
  - [x] tests/conftest.py作成
  - [x] pytest設定
- [x] モデルのテスト作成
  - [x] tests/unit/test_models.py
- [x] サービスのテスト作成
  - [x] tests/unit/test_state_service.py
  - [x] tests/unit/test_photo_service.py
- [x] APIのテスト作成
  - [x] tests/integration/test_api.py
- [ ] テスト自動実行Hook設定

## Phase 3: 認証・ブラウザ制御

- [x] Playwrightクライアント実装
  - [x] app/browser/client.py
- [x] Google認証フロー実装
  - [x] app/browser/auth.py
  - [x] アプリ内認証機能（/api/photos/auth/login, /api/photos/auth/logout）
  - [x] `scripts/authenticate.py` を削除（アプリ内認証に一本化するため不要）
- [x] セッション管理実装
- [ ] 認証のテスト作成・実行

## Phase 4: コア機能

- [x] データモデル実装
  - [x] app/models/photo.py
  - [x] app/models/state.py
- [x] 写真検索機能実装
  - [x] app/browser/operations.py（検索部分）
- [x] ドライラン機能実装
- [x] 削除機能実装
  - [x] app/browser/operations.py（削除部分）
- [x] リトライ機能実装
  - [x] app/utils/retry.py
- [ ] コア機能のテスト作成・実行

## Phase 5: 状態管理

- [x] 状態保存機能実装
  - [x] app/services/state_service.py
- [x] レジューム機能実装
- [x] 状態管理のテスト作成・実行

## Phase 6: サービス層

- [x] 写真サービス実装
  - [x] app/services/photo_service.py
- [x] サービス層のテスト作成・実行

## Phase 7: API層

- [x] APIルーター実装
  - [x] app/routers/photos.py
  - [x] app/routers/health.py
- [x] ~~CSRF対策実装~~ → **スコープ外**（localhost単一ユーザー前提のため。詳細は `docs/security.md` 5章）
- [ ] API層のテスト作成・実行

## Phase 8: Web UI

- [x] テンプレート作成
  - [x] app/templates/base.html
  - [x] app/templates/index.html
- [x] 静的ファイル作成
  - [x] app/static/css/style.css
  - [x] app/static/js/main.js
- [x] 日付選択UI実装
- [x] 進捗表示UI実装
- [x] 確認ダイアログ実装
- [x] 認証状態表示UI実装
- [x] ~~E2Eテスト作成・実行~~ → **スコープ外**（Google Photos DOM 依存でメンテ困難。手動テストで代替。詳細は `docs/testing.md` 5章）

## バグ修正

- [x] **バルク削除対応（日付ヘッダー一括選択 + 複数同時ゴミ箱移動）**
      （2026-04-08 実装完了、手動E2E未確認）
  - 背景: 1 枚削除 → トップに戻ってジャンプ → スクロール → 1 枚削除…を
    繰り返すため、125 枚の削除で約 10.4 分かかり、かつ個別クリック由来の
    `PhotoNotFoundError` で 12 枚失敗していた
  - DOM 調査（`dom-inspector` skill + `BrowserClient` で実 DOM を
    2 回ダンプ）で判明したこと:
    - 日付ヘッダーは `div[role="checkbox"].R4HkWb`、aria-label は相対表記
      （"昨日の写真をすべて選択" / "月曜日の写真をすべて選択"）または
      絶対表記（"M月D日(曜日)の写真をすべて選択"、例 "1月27日(火)"）
    - 写真は `div[role="checkbox"].ckGgle`、aria-label に精密な日付
      （"写真 - 縦向き - 2026/04/07 11:31:11"）が入る
    - DOM 上で「ヘッダー → その日の写真群」が連続して並ぶ
    - ヘッダーを click するとその日の写真が一括選択され、ツールバーに
      「ゴミ箱に移動」が即座に現れる
    - 確認ダイアログは単体削除と同形（`[role="dialog"] button:has-text("ゴミ箱に移動")`）
  - 対応: `_bulk_select_visible_in_range` を新設。DOM 順で
    `div[role="checkbox"]` を走査してヘッダーで group 化し、
    **グループ全員が範囲内ならヘッダーを 1 click** で一括選択、
    部分範囲の場合のみ写真個別選択にフォールバック。
    全選択が終わったら `_click_trash_and_confirm` でツールバー
    「ゴミ箱に移動」→ 確認ダイアログ → 完了を待ってから reflow。
    `delete_photos_in_range_streaming` の内側ループを、1 枚ずつの
    `delete_photo` 呼び出しからこの bulk フローに置換
  - 期待される効果: 日付ごとにまとめて削除されるので
    iteration 回数は従来の数十分の一。個別の `select_photo` 呼び出しが
    ほぼ無くなるため、DOM virtualization 由来の取りこぼし /
    PhotoNotFoundError も激減する見込み
  - **未確認**: 実 DOM での動作。次回手動テストで 125 枚規模の削除を
    通し、所要時間と取りこぼし数を前回（10.4 分 / 12 枚失敗）と比較する

- [x] **ストリーミング削除の取りこぼしバグ修正（マルチパス化）**
      （2026-04-08 完了、手動E2E確認済み）
  - 症状: 単日範囲で dry run 5 枚検出 → 削除実行 2 枚しか削除されず、
    再度 dry run すると残り 3 枚が見つかる
  - 原因: Google Photos の仮想化グリッドは下方向にスクロールして通り過
    ぎたタイルを DOM から unload する。`delete_photos_in_range_streaming`
    は 1 パスで完了すると判定していたため、unload された in-range 写真
    を取りこぼしていた
  - 対応: `delete_photos_in_range_streaming` に外側のマルチパスループを
    追加。1 パスが完了しても、そのパスで 1 枚以上削除していれば
    `navigate_to_date_range` からやり直して再走査。0 枚削除のパスが
    出るまで最大 10 回繰り返す
  - 動作確認: 2023-11-28 単日で 4 枚検出 → Pass 0 で 4 枚削除 →
    Pass 1 で 0 枚確認 → 終了 → 再 dry run で 0 枚（段階 1 通過）

- [x] **境界日の写真検出漏れ修正**（2026-04-07 完了）
  - 症状: 単日範囲（例: 2026/4/2〜2026/4/2）で対象7枚中3枚しか検出されない
  - 原因: `_collect_photo_records_in_range` が `earliest_date_in_view < start_date`
    を見た瞬間に `break` していたが、Google Photosは仮想化グリッドで
    DOMに少数しかレンダリングしないため、当日の残り写真がまだ
    レンダリングされていない段階で前日分のタイルを検知して打ち切っていた
  - 対応: 境界突破後すぐ break せず、in-range 写真の追加が
    `post_boundary_stable_threshold` 回連続でゼロになるまでスクロールを継続する
    「boundary-drain mode」を導入

- [x] **`empty_trash` の削除（要件変更）**（2026-04-07）
  - 要件変更により、ツールは「ゴミ箱に移動」までを担当し、
    ゴミ箱を空にする操作はGoogle Photos画面から一括で行うこととした
  - `app/browser/operations.py::empty_trash` を削除

- [x] **日付範囲フィルタのバグ修正**（2026-04-07 完了）
  - 症状: ドライランで実際よりも大幅に少ない枚数しか検出されない
  - 原因1: `_build_search_url` が生成する `/search/YYYY-MM-DD_YYYY-MM-DD` は
    Google Photos のフルテキスト検索であり、日付範囲フィルタではなかった
  - 原因2: `window.scrollBy` は Google Photos の仮想化コンテナでは効かない
  - 原因3: `wait_for_load_state("networkidle")` は Google Photos の常時通信で
    30秒タイムアウトになる
  - 原因4: `logging.basicConfig` 未設定でアプリのログが一切出ていなかった
  - 対応: `app/browser/date_parser.py` を新設、`PhotoOperations` を
    タイムライン走査 + aria-label パース方式に書き換え、
    `page.mouse.wheel()` でスクロール、`app/main.py` にログ設定追加
  - 動作確認: 2023-01-01 〜 2024-12-31 の範囲で 1713 枚を正しく検出（ユーザー確認済み）

- [x] **削除ボタン・ゴミ箱セレクタの修正**（2026-04-07 完了、E2E未確認）
  - 症状: `operations.py` のセレクタが当て推量で書かれており、実際の Google Photos
    DOM にはマッチしない
  - 調査: `dom-inspector` スキルを使い、プロジェクトの `BrowserClient` で
    認証済みブラウザを起動して `/tmp/inspect_gphotos_buttons.py` で実DOMをダンプ。
    メインタイムライン → 写真選択 → 削除ボタン → 確認ダイアログ → `/trash` ページ
    を順に走査して DOM を JSON で出力
  - 判明したこと:
    - Google Photos のロケールは `ja-JP` 固定（`BrowserClient` が `locale="ja-JP"` で起動）
      なので aria-label は **日本語のみ**。英語 (`Delete`, `Empty trash`) は一切ヒットしない
    - 写真タイルには `data-photo-id` / `data-id` 属性は **存在しない**。
      選択は `div[role="checkbox"][aria-label^="写真"]` を直接クリックする
    - 削除ボタンは「削除」ではなく **「ゴミ箱に移動」** (`button[aria-label="ゴミ箱に移動"]`)
    - 確認ダイアログのボタンは `aria-label=null` のテキストボタンで、ツールバーの
      同名ボタンと重複するため `[role="dialog"]` でスコープしないと誤爆する
    - ゴミ箱ページの「ゴミ箱を空にする」ボタンはツールバー側 (`aria-label` 付き) と
      ダイアログ側 (同じく `aria-label` 付き、クラスが別) の2種類がある
    - 同じく `/trash` ページでも `wait_for_load_state("networkidle")` は fire しない
  - 対応: `app/browser/operations.py` の `select_photo`, `select_all_visible_photos`,
    `delete_photo`, `empty_trash` を書き直し。ruff/mypy 通過確認済み
  - **未確認**: 実際の削除フローの通し動作（調査時は破壊操作を避けるため Escape で
    ダイアログを閉じた）。次回は「捨てても良い写真」で手動E2Eを通すこと

- [x] **古い日付範囲での探索が実用不能 → 右側スライダーで高速ジャンプ**
      （2026-04-08 実装完了、手動E2E未確認）
  - 症状: Google Photos は新しい順なので、`start_date` が数年前だと
    `navigate_to_date_range` 後に最上部から wheel スクロールで延々と送る
    必要があり事実上完了しない
  - 対応: `_jump_to_month_via_slider(end_date)` を新設し、
    `navigate_to_date_range` 末尾から best-effort で呼ぶ。
    `div[role="slider"][aria-orientation="vertical"]` の年ラベル位置から
    線形モデルで目標Yを推定 → ドラッグ → `aria-valuetext` 読み取りで
    最大5回補正ループ → 1ヶ月以内に着地で成功。直近60日以内は
    ショートサーキットでスキップ。失敗時は従来の top-down スクロールに
    フォールバック（例外は `contextlib.suppress` で握り潰し）
  - 変更: `app/browser/operations.py` に `_jump_to_month_via_slider`,
    `_drag_slider`, `_parse_ym_from_valuetext`, `_estimate_y_for_month`,
    module-level `_month_diff` を追加。`navigate_to_date_range` 末尾で呼ぶ。
    呼び出し側 2 箇所 (`_collect_photo_records_in_range`,
    `delete_photos_in_range_streaming`) の重複 `asyncio.sleep(2)` を削除
  - **未確認**: 実 DOM での挙動。手動テスト（`docs/manual-test.md` 段階 0.5）
    で古い日付範囲の高速ジャンプ動作を必ず確認すること

## Phase 9: 仕上げ

- [x] エラーハンドリング強化（停止ダイアログ・選択モード残留からの自己回復、
      ストリーミング削除での failure 個別記録、state の都度保存）
- [x] セキュリティチェック実施
  - [x] pip-audit実行（脆弱性なし）
  - [x] bandit実行（全 severity で 0 件）
- [x] 手動テスト実施（`docs/manual-test.md` 参照。段階 0.5〜5 通過）
- [x] ドキュメント最終確認

## リリース

- [x] 全テストパス確認
- [x] セキュリティチェックリスト完了
- [x] 手動テストチェックリスト完了（段階 0.5〜5 通過）

---

## リリース後バグ修正

リリース後〜マルチアカウント対応完了までの改修履歴（2026-04-07 〜 2026-04-14）。
詳細な調査メモや DOM セレクタの経緯は git log を参照。

### 削除ロジック大幅改修（2026-04-07〜08）

- [x] 日付範囲フィルタの実装やり直し（検索URL → タイムライン走査 + aria-label
      パース方式。`wait_for_load_state("networkidle")` は Google Photos では
      発火しないため page.mouse.wheel ベースに）
- [x] 境界日の写真検出漏れ修正（boundary-drain モード。仮想化グリッド末端で
      即 break せず、in-range 追加が閾値回連続ゼロになるまで継続）
- [x] ストリーミング削除のマルチパス化（仮想化で unload された in-range
      タイルを拾い直すため、0 枚パスが出るまで最大 10 回やり直し）
- [x] バルク削除（日付ヘッダー click で一日分を一括選択 → ツールバー
      「ゴミ箱に移動」→ 確認ダイアログ）を `_bulk_select_visible_in_range` +
      `_click_trash_and_confirm` として実装。所要時間を10分超 → 数分規模に短縮
- [x] 古い日付範囲向けに右側スライダー高速ジャンプ
      （`_jump_to_month_via_slider` + 線形モデル推定 + 補正ループ）
- [x] セレクタを実DOM調査ベースで全面刷新（ja-JP の aria-label 限定。
      `div[role="checkbox"][aria-label^="写真"]`, `button[aria-label="ゴミ箱に移動"]`,
      `[role="dialog"]` スコープ等）
- [x] `empty_trash` を削除（要件変更：完全削除は Google Photos 画面から実施）
- [x] エラーハンドリング強化（停止ダイアログ／選択モード残留からの自己回復、
      失敗個別記録、都度 state 保存）

### 手動テスト（全段階通過）

- [x] 段階 0.5：スライダー高速ジャンプ確認
- [x] 段階 1：最小（単日・数枚）
- [x] 段階 2：中規模（127枚 / 126枚削除）
- [x] 段階 3：レジューム動作（中断 → 再開 → 完了）
- [x] 段階 4：大規模（4247枚 / 4242枚削除 = 99.9%）
- [x] 段階 5：本番削除

### E2Eテスト自動化（限定スコープ、2026-04-08）

- [x] `/trash` DOM 調査で復元フローのセレクタ確定
      （`button[aria-label="復元"]` 可視要素を JS click、
      `[role="dialog"] button:has-text("復元")`、
      `button[aria-label="完全に削除"]` は絶対クリック禁止）
- [x] `PhotoOperations.restore_photos_from_trash_by_labels` /
      `get_photo_labels_in_range` 実装
- [x] `tests/e2e/test_delete_and_restore.py`（単日 delete→restore ラウンドトリップ）
- [x] pyproject に `e2e` マーカー + デフォルト除外
- [x] 実 Google Photos で PASSED 確認（148s）
- [x] `docs/testing.md` 5章を限定スコープ内に更新

### マルチアカウント対応（2026-04-14 完了）

- [x] アカウント管理モデル（`app/models/account.py`）
- [x] アカウント管理サービス（`app/services/account_service.py`：一覧／作成／削除／アクティブ切替）
- [x] `BrowserClient` をマルチプロファイル対応（account ID ごとにプロファイル分離）
- [x] 認証フローを `accounts.google.com/signin` ベースに変更。
      ERR_ABORTED を `contextlib.suppress` + `domcontentloaded` で回避、
      `_check_logged_in_state` をホスト名判定 + `client.is_logged_in()` 委譲に刷新
- [x] API エンドポイント（`/api/accounts` 一覧／追加／切替／削除／login／logout／status）
- [x] フロントエンド UI（ドロップダウン／追加／削除／アカウント表示）
- [x] 重複アカウント統合（email 一致スロットをログイン時に自動マージ）
- [x] アカウント切替直後の認証確認中 UI を中立化（誤操作防止）
- [x] `extract_account_email` を aria-label 優先の多段戦略に強化
- [x] テスト追加（`tests/unit/test_account_service.py`）

### ブラウザ起動の安定化（2026-04-14）

- [x] 残留 `SingletonLock` / `SingletonCookie` / `SingletonSocket` を
      起動前に削除する自己修復ロジック（`BrowserClient._remove_stale_singleton_locks`）
- [x] lifespan を try/finally でガードし、crash / reload でも
      `browser_manager.shutdown()` を必ず実行

### ブラウザセッション保存先をワークツリー外に移動（2026-04-14）

- [x] 既定値を `~/.delete-google-photo/browser-state/` に変更。
      `BROWSER_STATE_DIR` で上書き可
- [x] 起動時に `chmod 0700`
- [x] 旧 `state/browser-state/` からの自動マイグレーション
- [x] `docs/security.md` / `development.md` / `README.md` / `manual-test.md` /
      `CLAUDE.md` のパス記述を更新

---

## レビューで追加した改善TODO（2026-04-09）

- [x] **ブラウザセッション保存先の見直し**（2026-04-14 完了）
  - 既定値を `~/.delete-google-photo/browser-state/` に変更（ワークツリー外）。
    `BROWSER_STATE_DIR` 環境変数で上書き可能
  - 起動時に `chmod 0700` を適用（`app/main.py::_prepare_browser_state_dir`）
  - 旧来の `state/browser-state/` があり新規保存先が空なら初回起動時に自動
    マイグレーション
  - `.gitignore` は引き続き `state/` を除外。保存先がワークツリー外のため
    誤コミットのリスクが構造的に消えた
  - `docs/security.md` / `development.md` / `README.md` / `manual-test.md` /
    `CLAUDE.md` のパス記述を更新

- [ ] **進捗表示を実態に合わせて修正**
  - 現状の `/api/photos/delete` は同期実行なので、UI の「リアルタイム進捗」
    表示は要件未達。WebSocket / SSE / ポーリングのいずれかで実進捗を出すか、
    要件・UI文言を現実に合わせて下げる
  - 削除中の「中断」ボタンは未実装なので、実装するか UI から外す

- [ ] **認証判定の安定化**
  - `BrowserClient.is_logged_in()` の `networkidle` 待ちを見直す。
    Google Photos の継続通信で誤判定しうるため、他の画面判定ロジックと
    方針を揃える

- [ ] **完了済みセッションの後始末**
  - 削除完了後に state JSON を消すか、保持ポリシーを明文化する
  - `StateService.cleanup_completed()` の利用有無を整理し、
    要件・実装・UI の挙動を一致させる

- [ ] **ドキュメントとUI文言の不整合解消**
  - footer の「削除した写真は復元できません」を、実際の仕様
    （ゴミ箱移動・60日以内は Google Photos 側で復元可能）に合わせて修正
  - `docs/manual-test.md` の「自動E2Eはスコープ外」記述を、
    `docs/testing.md` の現状方針と一致させる
  - セキュリティ資料内の CSRF 記述、保存先パス、対策例について
    実装済み/スコープ外の境界を整理する
