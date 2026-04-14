# 開発の教訓

このドキュメントは、開発中に得られた教訓や反省点をまとめたものです。

---

## 2026-04-06: パッケージ管理の選定

### 問題
Nixをパッケージ管理に使用しようとしたが、以下のエラーが発生した：
```
error: sphinx-9.1.0 not supported for interpreter python3.11
```

`python311Packages.playwright`や`python311Packages.mypy`の依存関係でsphinxが必要になり、Python 3.11との互換性問題が発生。

### 原因
- nixpkgsのパッケージバージョンが固定されており、特定の組み合わせで依存関係の競合が発生
- Nixは再現性が高いが、パッケージの組み合わせによっては予期しないエラーが起きる

### 解決策
Nixを廃止し、**uv**（Astral社製の高速Pythonパッケージマネージャー）に移行した。

### 教訓
1. **シンプルな選択を優先する**: Nixは強力だが、Pythonプロジェクトには過剰な場合がある。uvやpipenvなどのPython専用ツールの方が問題が少ない
2. **早期に検証する**: 新しいツールを導入する前に、実際の依存関係で動作確認を行う
3. **フォールバックプランを持つ**: ツールが動かない場合の代替案を事前に考えておく

---

## 2026-04-06: mypyとPydanticの型チェック

### 問題
Pydanticモデルでデフォルト値を持つフィールドに対して、mypyが「Missing named argument」エラーを出した。

```python
# Photo(id=photo_id) でエラー
# "Missing named argument 'filename' for 'Photo'"
```

### 原因
mypyはデフォルトでPydanticのField定義を理解できない。

### 解決策
`pyproject.toml`にPydantic mypyプラグインを追加：

```toml
[tool.mypy]
plugins = ["pydantic.mypy"]

[tool.pydantic-mypy]
init_forbid_extra = true
init_typed = true
warn_required_dynamic_aliases = true
```

### 教訓
1. **Pydanticを使う場合はmypyプラグインを最初から設定する**
2. **型チェックは早期に導入する**: 後から導入すると大量のエラー修正が必要になる

---

## 2026-04-06: ParamSpecとmypyのstrict mode

### 問題
`typing.ParamSpec`を使ったジェネリックなリトライデコレータで、mypy strict modeでエラーが発生。

```python
# これがエラーになる
async def retry_with_backoff(
    func: Callable[P, Awaitable[T]],
    *args: P.args,
    **kwargs: P.kwargs,
) -> T:
```

### 解決策
ParamSpecの代わりに`Any`を使用：

```python
async def retry_with_backoff(
    func: Callable[..., Awaitable[T]],
    *args: Any,
    **kwargs: Any,
) -> T:
```

### 教訓
1. **ParamSpecは複雑な場合がある**: シンプルなケースでは`Any`で十分
2. **完璧な型付けより動くコードを優先**: 型の精度と実用性のバランスを取る

---

## 2026-04-06: Docker環境でのヘッドレスブラウザ認証

### 問題
Docker内のPlaywrightはヘッドレスモードで動作するため、Googleの対話的ログインができなかった。

### 解決策（当初）
1. ローカルで認証スクリプト（`scripts/authenticate.py`）を実行
2. セッション情報を`state/browser-state/`に保存
3. Docker Composeでそのディレクトリをマウント

```yaml
volumes:
  - ./state/browser-state:/app/state/browser-state
```

### 教訓
1. **認証フローは早期に設計する**: ヘッドレス環境での制約を考慮
2. **セッション共有の仕組みを用意する**: ローカルとコンテナ間でセッションを共有

---

## 2026-04-06: 認証フローの改善（アプリ内認証の追加）

### 問題
認証のために毎回 `python scripts/authenticate.py` を実行するのは手間だった。
delete-gmailアプリではアプリ画面から直接認証できるのに、delete-google-photoでは事前スクリプトが必要だった。

### 原因
- delete-gmail: Google公式OAuth 2.0 APIを使用（Webフローで認証可能）
- delete-google-photo: Playwrightブラウザ自動化を使用（Docker内ではヘッドレスのため画面表示不可）

### 解決策
**ローカル実行をデフォルトに変更**し、アプリ内で認証フローを完結できるようにした。

1. `config.py`: `headless=False` に変更（ブラウザを画面表示）
2. `photos.py`: `/api/photos/auth/login`, `/api/photos/auth/logout` エンドポイント追加
3. `index.html`: 「Googleでログイン」「ログアウト」ボタンを追加
4. `main.js`: ログイン/ログアウト処理を追加

```python
# 新しい認証エンドポイント
@router.post("/auth/login")
async def login():
    async with get_browser_client(headless=False) as client:
        authenticator = GoogleAuthenticator(client)
        success = await authenticator.wait_for_manual_login(timeout=300)
        return {"success": success}
```

### 教訓
1. **ユーザー体験を優先する**: 技術的な制約（Docker + ヘッドレス）よりもシンプルな操作性を優先
2. **類似プロジェクトを参考にする**: delete-gmailの認証フローと比較することで改善点を発見
3. **実行環境を見直す**: Dockerが必須でないなら、ローカル実行の方がシンプルな場合がある
4. **事前スクリプトは最小限に**: 毎回必要な操作はアプリ内に統合する

---

## 2026-04-07: Google Photos の日付範囲検索には公開URLが存在しない

### 問題
Web UI からドライランを実行したところ、実際よりも大幅に少ない枚数の写真しか
検出されなかった。

### 原因
`app/browser/operations.py` の `_build_search_url` が
`https://photos.google.com/search/2020-01-01_2020-12-31` というURLを生成していた。

Google Photos の `/search/<query>` エンドポイントは **フルテキスト検索** であり、
構造化された日付範囲フィルタではない。`"2020-01-01_2020-12-31"` という文字列は
そのままテキストクエリとして扱われ、ファイル名・キャプション・OCR結果などに
リテラル文字列が偶然含まれる写真だけがヒットしていた。

### 解決策
URLベースのフィルタを諦め、**メインタイムラインを走査して、各写真の
`aria-label` から日付をパースしてクライアント側でフィルタする方式** に変更。

1. `app/browser/date_parser.py` を新設し、`aria-label` から日付を抽出する
   ピュア関数 `parse_date_from_aria_label` を実装
   - 日本語（`2020年1月1日`）、英語（`Jan 1, 2020`）、ISO（`2020-01-01`）に対応
2. `PhotoOperations._collect_photo_records_in_range` を新設
   - `photos.google.com` メインタイムラインに遷移
   - 下方向にスクロールしながら `a[href*="/photo/"]` の `aria-label` を収集
   - パースした日付で範囲フィルタ
   - 「DOMに表示されている最古の写真 < start_date」になったら走査を打ち切り
     （新しい順→古い順なので、以降は範囲外が続くだけ）
3. `count_photos_in_range` / `get_photos_in_range` / `get_photo_summary_by_date`
   を新ヘルパー経由に置き換え

### 教訓
1. **外部サービスのURL形式は推測しない**: Web UIの動作とURL形式を実際に
   確認してから使う。`<query>` 部分がフルテキスト検索になるのはよくあるパターン
2. **DOMから情報を取る方が堅牢な場合がある**: Google Photos のように公式APIが
   不足している場合、レンダリング済みDOMの `aria-label` は意外と安定した
   情報源になる（アクセシビリティ用なので後方互換性が保たれやすい）
3. **範囲フィルタは「打ち切り条件」を持たせる**: 全スクロールせずに済むよう、
   目的の範囲を通り過ぎたら打ち切る実装にすることで大規模ライブラリにも対応
4. **パース失敗時は握りつぶさずに警告ログを出す**: DOM形式が変わったときに
   気付けるよう、`aria-label` のパース失敗数をログに出す

---

## 一般的な教訓

### 環境構築
- **最初から動作確認を頻繁に行う**: 大きな変更を加える前に小さく検証
- **ドキュメントを同時に更新する**: 環境構築手順は変更と同時に更新

### ツール選定
- **枯れた技術を優先**: 新しいツールは魅力的だが、問題解決に時間がかかる
- **代替案を常に持つ**: メインツールが動かない場合のプランB

### 型チェック
- **プロジェクト初期から導入する**: 後から追加すると修正コストが高い
- **必要なプラグインを最初から設定**: Pydantic、SQLAlchemy等のプラグイン

### テスト
- **テストを書いてから実装**: テストがあると安心してリファクタリングできる
- **CI/CDでテストを自動化**: 手動テストに頼らない

---

## 次回プロジェクトへの推奨事項

1. **Python環境**: uv + pyproject.toml を標準とする
2. **型チェック**: mypy + pydantic.mypy プラグインを最初から設定
3. **リンター**: ruff（高速で多機能）
4. **実行環境**: ローカル実行をデフォルトに、Docker はオプション
5. **認証フロー**: アプリ内で完結する設計を優先（事前スクリプトは避ける）
6. **ブラウザ自動化**: ヘッドフルモードをデフォルトにして、ユーザー操作を可能に
7. **Claude Code Hooks**: `uv run` コマンドでツールを実行
