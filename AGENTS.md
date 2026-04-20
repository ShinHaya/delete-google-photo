# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## プロジェクト概要

Google Photosで指定した日付範囲の写真を一括でゴミ箱に移動するWebアプリケーション。
ゴミ箱を空にする操作（完全削除）はGoogle Photosの画面から一括で行えるため、
本ツールのスコープには含めない。本ツールは「ゴミ箱に移動」までを担当する。

### 背景
iCloudに写真が保存されている状態で誤ってGoogle Photos同期をONにしてしまい、Googleストレージが逼迫したため、不要な写真を一括削除する必要がある。

### 技術的アプローチ
Google Photos APIは写真の削除をサポートしていないため、**Playwright**によるブラウザ自動化でWeb版Google Photosを操作して削除を実行する。

## 技術スタック

- **言語**: Python 3.11+
- **パッケージ管理**: uv
- **ブラウザ自動化**: Playwright（headfulモード）
- **Webフレームワーク**: FastAPI
- **フロントエンド**: HTML + JavaScript（シンプルなUI）
- **実行環境**: ローカルのmacOSのみ（Cloud Run等のコンテナ実行はスコープ外）

### スコープ方針

本ツールは **ローカルMacでの実行に限定** する。Cloud Run / AWS 等の
コンテナ実行環境はスコープ外とする。理由:

- Google ログインは headful ブラウザ + 2段階認証 / reCAPTCHA を伴うため、
  headless コンテナ環境で初回認証を完結させるのは現実的でない
- iCloud 側に原本があり、削除は一度きり〜数回のバッチ作業なので、
  ローカル実行で十分に要件を満たせる
- セッション情報の外部保管（Secret Manager等）を避けることで
  セキュリティリスクを最小化できる

## 主要機能

1. **日付範囲指定**: Web UIから開始日・終了日を指定
2. **ドライラン**: 削除対象の一覧表示（実際には削除しない）
3. **確認プロンプト**: 削除実行前の最終確認
4. **ゴミ箱へ移動**: 対象写真を一括でゴミ箱に移動（完全削除はGoogle Photos側で行う）
5. **レジューム機能**: エラー発生時に途中から再開可能
6. **進捗表示**: 処理済み枚数のカウント表示

## コマンド

```bash
# 依存パッケージインストール（初回のみ）
uv sync --all-extras

# Playwrightブラウザインストール（初回のみ）
uv run playwright install chromium

# 開発サーバー起動
uv run python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# テスト実行
uv run pytest -v

# リンター実行
uv run ruff check app/
uv run ruff format app/

# 型チェック
uv run mypy app/

# 単一テスト実行
uv run pytest tests/test_specific.py::test_function_name -v
```

## Google認証

認証は **アプリ画面から一本化** されている。ターミナルでの認証スクリプト
実行は不要（かつ非推奨）。

1. 開発サーバーを起動
2. ブラウザで http://localhost:8000 にアクセス
3. 「Googleでログイン」ボタンをクリック
4. 自動で開くブラウザ（headful Chromium）でGoogleアカウントにログイン
5. ログイン完了後、セッションが `~/.delete-google-photo/browser-state/` に保存される（ワークツリー外、パーミッション 0700）

## Codex Hooks

このプロジェクトではCodex Hooksを使用して自動化を行う。

### 設定済みHooks

1. **PostToolUse（Edit/Write後）**: リンター自動実行
   - Pythonファイル編集後に `uv run ruff check` と `uv run ruff format` を実行

2. **PostToolUse（テストフェーズ以降）**: テスト自動実行
   - コード変更後に `uv run pytest` を実行
   - テストコード完成後に有効化

### Hooks設定ファイル
- `.Codex/settings.local.json` - ローカルHooks設定

## ディレクトリ構成

```
delete-google-photo/
├── app/
│   ├── main.py           # FastAPIエントリーポイント
│   ├── browser/          # Playwright操作
│   ├── models/           # データモデル
│   └── templates/        # HTMLテンプレート
├── tests/
├── docs/
│   ├── requirements.md   # 要件定義
│   ├── development.md    # 開発方法
│   ├── testing.md        # テスト方法
│   └── security.md       # セキュリティチェック
├── state/                # レジューム用の状態保存
├── .Codex/
│   └── settings.local.json  # Hooks設定
├── pyproject.toml        # プロジェクト設定・依存関係
```

## 関連ドキュメント

- GitHub Issues - タスク管理
- @docs/github-operations.md - Codex / Codex 共通の GitHub 運用方針
- @docs/issue-implementation-plan-template.md - Issue に記載する実装方針テンプレート
- @docs/requirements.md - 要件定義書
- @docs/development.md - 開発方法
- @docs/testing.md - テスト方法
- @docs/security.md - セキュリティチェック

## 開発ルール

1. **タスク完了時**: 対応する GitHub Issue の状態・コメント・チェックリストを更新する
   実装方針の正本も GitHub Issue に置き、ローカル専用メモだけにしない
2. **コード修正時**: Hooksによりリンターが自動実行される
3. **テストフェーズ以降**: コード修正時に `uv run pytest` が自動実行される

## 注意事項

- **ゴミ箱移動後は60日でGoogle Photos側が完全削除**: 実行前に必ずドライランで確認すること
- **Google認証**: 初回実行時にブラウザでGoogleアカウントにログインが必要
- **レート制限**: 大量削除時はGoogle側のレート制限に注意
