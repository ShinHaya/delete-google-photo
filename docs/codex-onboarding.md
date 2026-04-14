# Codex 開発ガイド

このドキュメントは、**Codex でこのリポジトリを開発する人向け**の
最初の案内です。

`CLAUDE.md` は **Claude Code 向けの運用資料としてそのまま残します**。
今後も Claude Code を併用する前提で、Codex 側ではこのドキュメントを
入口として使ってください。

## 1. このプロジェクトの概要

Google Photos で指定した日付範囲の写真を一括でゴミ箱に移動する
ローカル向け Web アプリケーションです。

- 写真の**完全削除**はスコープ外
- Google Photos API では削除できないため、**Playwright によるブラウザ自動化**
  を使う
- 実行環境は **ローカル macOS 限定**
- Google 認証は **アプリ画面から headful Chromium で手動ログイン**

## 2. Codex で最初に読むべきファイル

Codex で作業を始めるときは、まず以下を読む想定です。

1. `README.md`
2. `docs/github-operations.md`
3. `TODO.md`
4. `docs/requirements.md`
5. `docs/development.md`
6. `docs/testing.md`
7. `docs/manual-test.md`
8. 必要に応じて `app/main.py`, `app/services/`, `app/browser/`, `app/routers/`

優先度としては、まず `README.md` と `TODO.md` で現在地を把握し、
次に `docs/` と実装を読むのが効率的です。

## 3. Claude Code との違い

このリポジトリには Claude Code 向けの設定が残っています。

- `CLAUDE.md`
- `.claude/settings.local.json`

これらは **Claude Code 固有の運用情報**です。Codex では特に以下に注意してください。

- Claude Code Hooks は Codex では自動実行されない
- そのため、lint / format / typecheck / test は **明示的に実行**する
- Claude 用ドキュメントは削除せず、必要なら参照してよい

## 4. Codex での標準作業フロー

Codex では、以下の流れで進めるのが基本です。

1. ドキュメントと関連コードを読む
2. 変更対象と影響範囲を整理する
3. 実装する
4. 必要な lint / test を自分で実行する
5. ドキュメントや `TODO.md` の更新要否を確認する

Claude Code の Hook に頼らず、**変更後の確認を毎回明示的に行う**のが重要です。

## 5. 開発コマンド

初回セットアップ:

```bash
uv sync --all-extras
uv run playwright install chromium
```

開発サーバー起動:

```bash
uv run python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

品質チェック:

```bash
uv run ruff check app tests
uv run ruff format app tests
uv run mypy app
uv run pytest
```

E2E テストはデフォルトで除外されています。明示的に実行する場合:

```bash
uv run pytest tests/e2e/ -v -m e2e
```

## 6. テスト運用の考え方

このプロジェクトのテストは大きく 3 種類あります。

- unit test
- integration test
- e2e test

注意点:

- `e2e` は **実 Google Photos** を操作する
- 認証済みプロファイルと headful ブラウザが必要
- 普段の変更では、まず unit / integration を優先する
- Google Photos の DOM 依存の変更を入れたときは、`docs/manual-test.md` も参照する

## 7. 状態管理と認証で知っておくこと

- 中断セッションなどの状態は `state/` に保存される
- ブラウザの認証状態は既定で `~/.delete-google-photo/browser-state/` に保存される
- 認証は API キーや OAuth トークンではなく、**Playwright の永続プロファイル**
  を使って維持する

そのため、通常の API クライアント開発とは違って、**ブラウザ状態の継続性**が
重要です。

## 8. 重要ディレクトリ

- `app/main.py`: FastAPI エントリーポイント
- `app/config.py`: 設定
- `app/browser/`: Google Photos のブラウザ自動化
- `app/services/`: ビジネスロジック
- `app/routers/`: API エンドポイント
- `app/models/`: Pydantic モデル
- `tests/`: テスト
- `docs/`: 仕様・開発・テスト手順
- `TODO.md`: 開発タスクと現在の進捗

## 9. 現在の主要タスク

`TODO.md` の最新内容に従って進めてください。

現時点では、次の大きな作業対象は **マルチアカウント対応**です。
着手前に `TODO.md` の要件と既存実装を必ず確認してください。

## 10. Codex への依頼テンプレート

初回調査:

```text
README.md、TODO.md、docs/、関連コードを先に読んで、
現在の状態と次にやるべきことを整理してください。
その後、必要な実装とテストを進めてください。
```

実装依頼:

```text
TODO.md の「マルチアカウント対応」のうち、
まず service と router を実装してください。
変更後は関連テストを実行し、必要ならドキュメントも更新してください。
```

レビュー依頼:

```text
この変更をコードレビューしてください。
バグ、回帰リスク、テスト不足を優先して指摘してください。
```

## 11. Codex で作業するときの注意点

- Claude Code 向けの自動 Hook 実行を前提にしない
- `TODO.md` の更新ルールを守る
- 手動テストが必要な変更では `docs/manual-test.md` を確認する
- Google Photos の DOM は変わるため、ブラウザ自動化コードの変更時は慎重に検証する
- 認証やブラウザ状態を不用意に消さない

## 12. 補足

このリポジトリは **Claude Code で作られたが、構成自体は一般的な Python/FastAPI
/ Playwright プロジェクト**です。Codex でも通常の実装・修正・テスト・レビュー
は問題なく進められます。

Codex 固有で必要なのは、Claude 固有機能に依存していた運用を
**明示的なコマンド実行とドキュメント確認に置き換えること**です。
