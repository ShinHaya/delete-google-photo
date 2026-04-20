# Google Photos 削除ツール

Google Photosで指定した日付範囲の写真を一括でゴミ箱に移動するWebアプリケーション。

> ゴミ箱を空にする操作（完全削除）はGoogle Photosの画面から一括で実行できるため、本ツールでは行いません。本ツールは「ゴミ箱に移動」までを担当します。

## 前提条件

- Python 3.11+
- uv (Pythonパッケージマネージャー)

### uvのインストール

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# または Homebrew
brew install uv
```

## クイックスタート

### 1. 依存パッケージのインストール

```bash
# 依存パッケージをインストール
uv sync --all-extras

# Playwrightブラウザをインストール（初回のみ）
uv run playwright install chromium
```

### 2. 開発サーバーの起動

```bash
uv run python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 3. ブラウザでアクセス

```
http://localhost:8000
```

### 4. Google認証

1. 「Googleでログイン」ボタンをクリック
2. 自動で開くブラウザでGoogleアカウントにログイン
3. ログイン完了後、自動的に認証状態が更新される

認証情報は `~/.delete-google-photo/browser-state/` （ワークツリー外、パーミッション 0700）に保存され、次回以降は自動でログイン状態が維持されます。環境変数 `BROWSER_STATE_DIR` で保存先を変更できます。

## 使い方

1. ブラウザで http://localhost:8000 にアクセス
2. 「Googleでログイン」ボタンで認証（初回のみ）
3. 開始日と終了日を指定
4. 「ドライラン」ボタンで削除対象の確認
5. 「削除実行」ボタンで実際にゴミ箱へ移動（確認ダイアログあり）

**注意**: 本ツールは写真をゴミ箱に移動するまでを行います。ゴミ箱内の写真は通常Google Photos側で60日後に自動削除されます。即座に完全削除したい場合は、Google Photosの画面で「ゴミ箱を空にする」を実行してください。

## 開発コマンド

### テスト実行

```bash
# 全テスト実行
uv run pytest -v

# カバレッジ付き
uv run pytest --cov=app --cov-report=html

# 特定のテストファイル
uv run pytest tests/unit/test_models.py -v
```

### リンター・型チェック

```bash
# リンター
uv run ruff check app/
uv run ruff format app/

# 型チェック
uv run mypy app/
```

## 実行環境について

本ツールは **ローカルのmacOSでの実行に限定** しています。
Docker / Cloud Run / AWS などのコンテナ・クラウド実行はスコープ外です。

理由: Googleログインは headful ブラウザ + 2段階認証を伴うため、
headless なコンテナ環境では初回認証を突破できません。

## プロジェクト構成

```
delete-google-photo/
├── app/
│   ├── main.py           # FastAPIエントリーポイント
│   ├── config.py         # 設定
│   ├── exceptions.py     # カスタム例外
│   ├── browser/          # Playwright操作
│   ├── models/           # データモデル
│   ├── services/         # ビジネスロジック
│   ├── routers/          # APIエンドポイント
│   ├── templates/        # HTMLテンプレート
│   └── static/           # CSS/JS
├── tests/                # テストコード
├── state/                # 状態保存（セッション、レジューム用）
└── pyproject.toml
```

## トラブルシューティング

### ポートが使用中

```bash
# 8000番ポートを使用しているプロセスを確認
lsof -i :8000

# 別のポートで起動
uv run python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

### Playwrightエラー

```bash
# ブラウザを再インストール
uv run playwright install chromium --with-deps
```

### 認証エラー / セッション切れ

認証状態が「未認証」と表示される場合：

```bash
# 1. 既存のセッションを削除
rm -rf ~/.delete-google-photo/browser-state/

# 2. アプリを再起動して「Googleでログイン」ボタンから再認証
```

### ログイン画面が閉じてしまう

ログイン完了前にブラウザを閉じた場合は、再度「Googleでログイン」ボタンをクリックしてください。

## 技術的な背景

Google Photos APIは写真の削除機能を提供していないため、本ツールはPlaywrightによるブラウザ自動化でWeb版Google Photosを操作して削除を実行します。

## 開発者向けドキュメント

- 共通の GitHub 運用方針: [docs/github-operations.md](docs/github-operations.md)
- AI review workflow も `docs/github-operations.md` の GitHub Actions 運用に従う
- Codex で作業する場合: [docs/codex-onboarding.md](docs/codex-onboarding.md)
- Claude Code で作業する場合: [CLAUDE.md](CLAUDE.md)
