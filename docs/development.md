# 開発方法

## 1. 開発方針

### 1.1 仕様駆動開発（Specification-Driven Development）
本プロジェクトは仕様駆動開発で進める。

1. **仕様を先に定義**: 実装前に要件定義書で機能を明確化
2. **テストを先に書く**: 仕様に基づいてテストを作成
3. **実装**: テストをパスするコードを実装
4. **リファクタリング**: コード品質を向上

### 1.2 実行環境スコープ

本ツールは **ローカルのmacOSで実行することに限定** する。
Docker / Google Cloud Run / AWS などのコンテナ・クラウド実行環境は
スコープ外とする。

**理由**:
- Googleログインは headful ブラウザ + 2段階認証 / reCAPTCHA を伴うため、
  headless なコンテナ環境で初回認証を完結させるのは現実的でない
- iCloud側に原本があり、削除は一度〜数回のバッチ作業なので
  ローカル実行で十分に要件を満たせる
- セッション情報を外部（Secret Manager等）に保管するリスクを避けられる

### 1.3 開発フェーズ

```
Phase 1: 基盤構築
├── uv環境設定
├── Claude Code Hooks設定
└── 基本的なFastAPI構成

Phase 2: テスト基盤
├── テスト環境構築
├── モデルのテスト作成
├── サービスのテスト作成
└── APIのテスト作成

Phase 3: 認証・ブラウザ制御
├── Playwright設定
├── アプリ内Google認証フロー
└── セッション管理

Phase 4: コア機能
├── 日付範囲による写真検索
├── ドライラン実装
└── 削除処理実装

Phase 5: 状態管理
├── 状態保存
└── レジューム機能

Phase 6-8: サービス・API・UI
├── サービス層実装
├── API実装
└── Web UI実装

Phase 9: 仕上げ
├── エラーハンドリング強化
├── セキュリティチェック
└── 手動テスト
```

## 2. 環境構築

### 2.1 パッケージ管理

本プロジェクトは **uv** を使用してローカル実行する。依存関係は
`pyproject.toml` に一元化されている。

```
┌────────────────────────────┐
│  uv（ローカルmacOS）       │
│  - FastAPI                 │
│  - Playwright（headful）   │
│  - ruff / mypy             │
│  - pytest                  │
└────────────────────────────┘
   アプリ画面からGoogle認証が可能
```

### 2.2 必要なツール
- uv（Pythonパッケージマネージャー）
- Git

### 2.3 初回セットアップ手順

```bash
# 1. uvがインストールされていない場合
curl -LsSf https://astral.sh/uv/install.sh | sh
# または: brew install uv

# 2. 依存パッケージをインストール
uv sync --all-extras

# 3. Playwrightブラウザインストール
uv run playwright install chromium

# 4. 開発サーバー起動
uv run python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 5. ブラウザで http://localhost:8000 にアクセス
# 6. 「Googleでログイン」ボタンをクリックして認証
```

### 2.4 依存パッケージ

依存関係は `pyproject.toml` で管理:

```toml
[project]
dependencies = [
    "fastapi>=0.109.0",
    "uvicorn[standard]>=0.27.0",
    "playwright>=1.41.0",
    "pydantic>=2.5.0",
    "pydantic-settings>=2.1.0",
    "jinja2>=3.1.0",
    "python-multipart>=0.0.6",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4.0",
    "pytest-asyncio>=0.23.0",
    "pytest-playwright>=0.4.0",
    "pytest-cov>=4.1.0",
    "mypy>=1.8.0",
    "ruff>=0.1.0",
    "httpx>=0.26.0",
]
```

## 3. Claude Code Hooks

### 3.1 Hooksの概要
Claude Codeのコード修正後に自動でリンターやテストを実行する。

### 3.2 設定ファイル

`.claude/settings.local.json`:
```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "if [[ \"$CLAUDE_FILE_PATH\" == *.py ]]; then uv run ruff check --fix \"$CLAUDE_FILE_PATH\" && uv run ruff format \"$CLAUDE_FILE_PATH\"; fi"
          }
        ]
      }
    ]
  }
}
```

### 3.3 テストフェーズ以降のHooks

テストコード完成後、以下を追加:
```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "if [[ \"$CLAUDE_FILE_PATH\" == *.py ]]; then uv run ruff check --fix \"$CLAUDE_FILE_PATH\" && uv run ruff format \"$CLAUDE_FILE_PATH\"; fi"
          },
          {
            "type": "command",
            "command": "if [[ \"$CLAUDE_FILE_PATH\" == app/*.py ]]; then uv run pytest -x -q; fi"
          }
        ]
      }
    ]
  }
}
```

## 4. コーディング規約

### 4.1 スタイルガイド
- **フォーマッター**: ruff format
- **リンター**: ruff check
- **型チェック**: mypy（strict mode）

### 4.2 命名規則
```python
# クラス: PascalCase
class PhotoDeleter:
    pass

# 関数・メソッド: snake_case
def delete_photos_by_date_range():
    pass

# 定数: UPPER_SNAKE_CASE
MAX_RETRY_COUNT = 3

# プライベート: 先頭にアンダースコア
def _internal_helper():
    pass
```

### 4.3 型ヒント
すべての関数に型ヒントを付ける。

```python
from datetime import date
from typing import AsyncGenerator

async def get_photos_in_range(
    start_date: date,
    end_date: date,
) -> AsyncGenerator[Photo, None]:
    ...
```

### 4.4 エラーハンドリング
カスタム例外を定義して使用する。

```python
# app/exceptions.py
class GooglePhotoDeleteError(Exception):
    """Base exception for this application"""
    pass

class AuthenticationError(GooglePhotoDeleteError):
    """Authentication failed"""
    pass

class PhotoNotFoundError(GooglePhotoDeleteError):
    """Photo not found"""
    pass

class RateLimitError(GooglePhotoDeleteError):
    """Rate limit exceeded"""
    pass
```

## 5. アーキテクチャ

### 5.1 レイヤー構成

```
┌─────────────────────────────────────┐
│           Presentation Layer         │
│  (FastAPI Routes, Jinja Templates)   │
├─────────────────────────────────────┤
│           Application Layer          │
│    (Use Cases, Business Logic)       │
├─────────────────────────────────────┤
│           Domain Layer               │
│      (Models, Exceptions)            │
├─────────────────────────────────────┤
│         Infrastructure Layer         │
│   (Playwright, File System, State)   │
└─────────────────────────────────────┘
```

### 5.2 ディレクトリ構成詳細

```
app/
├── __init__.py
├── main.py                 # FastAPIアプリケーション
├── config.py               # 設定管理
├── exceptions.py           # カスタム例外
├── models/
│   ├── __init__.py
│   ├── photo.py            # Photoモデル
│   └── state.py            # 状態管理モデル
├── browser/
│   ├── __init__.py
│   ├── client.py           # Playwrightクライアント
│   ├── auth.py             # Google認証（アプリ内認証フロー）
│   └── operations.py       # 写真操作（検索・削除）
├── services/
│   ├── __init__.py
│   ├── photo_service.py    # 写真サービス
│   └── state_service.py    # 状態管理サービス
├── routers/
│   ├── __init__.py
│   ├── photos.py           # 写真関連エンドポイント
│   └── health.py           # ヘルスチェック
├── templates/
│   ├── base.html
│   ├── index.html
│   └── components/
└── static/
    ├── css/
    └── js/
```

### 5.3 主要コンポーネント

```
┌──────────┐     ┌──────────────┐     ┌─────────────┐
│  Web UI  │────▶│  FastAPI     │────▶│  Service    │
└──────────┘     │  Router      │     │  Layer      │
                 └──────────────┘     └─────────────┘
                                            │
                        ┌───────────────────┼───────────────────┐
                        ▼                   ▼                   ▼
                 ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
                 │  Playwright │     │  State      │     │  Config     │
                 │  Client     │     │  Manager    │     │             │
                 └─────────────┘     └─────────────┘     └─────────────┘
```

## 6. Git運用

### 6.1 ブランチ戦略
- GitHub 運用は `docs/github-operations.md` を正とする
- 開発モデルは **トランクベース開発** とし、`main` を唯一のトランクとする
- 新規 Issue に着手するときは、最新の `main` から Issue 専用ブランチを切る
- ブランチ名は `codex/issue-<number>-<short-english-slug>` または
  `claude/issue-<number>-<short-english-slug>` を使う

### 6.2 コミットメッセージ
```
feat: 新機能追加
fix: バグ修正
docs: ドキュメント更新
refactor: リファクタリング
test: テスト追加・修正
chore: ビルド・設定変更
```

コミット前の品質ゲート、PR 作成、レビュー担当ルールは
`docs/github-operations.md` に従う。

## 7. 実行方法

### 7.1 開発サーバー起動
```bash
uv run python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# ブラウザでアクセス
open http://localhost:8000
```

認証は画面上の「Googleでログイン」ボタンから行う。ターミナルで
認証スクリプトを実行する必要はない。

### 7.2 テスト実行
```bash
# 全テスト実行
uv run pytest -v

# 特定のテスト実行
uv run pytest tests/unit/test_models.py -v

# カバレッジ付き
uv run pytest --cov=app --cov-report=html
```

### 7.3 リンター・型チェック
```bash
# リンター
uv run ruff check app/
uv run ruff format app/

# 型チェック
uv run mypy app/
```

## 8. デバッグ

### 8.1 Playwrightデバッグモード
```python
# ヘッドフルモードで実行（ブラウザが表示される）
browser = await playwright.chromium.launch(headless=False)

# スロー実行
browser = await playwright.chromium.launch(slow_mo=1000)
```

### 8.2 ログ設定
```python
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
```

## 9. トラブルシューティング

### 9.1 uv環境の問題
```bash
# キャッシュをクリア
uv cache clean

# 依存関係を再インストール
rm -rf .venv
uv sync --all-extras
```

### 9.2 Playwrightブラウザが起動しない
```bash
# ブラウザを再インストール
uv run playwright install chromium --with-deps
```

### 9.3 Google認証が失敗する
- 画面の「Googleでログイン」ボタンを再クリック
- 既存のセッションを削除: `rm -rf ~/.delete-google-photo/browser-state/`
- 2段階認証の確認
- セッションCookieの有効期限確認

### 9.4 レート制限に引っかかる
- 削除間隔を長くする（設定で調整）
- 一度に処理する枚数を減らす
