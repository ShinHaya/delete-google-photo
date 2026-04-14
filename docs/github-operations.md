# GitHub 運用方針

このドキュメントは、Codex / Claude のどちらでも共通で使う
GitHub 運用ルールを定義する。

## 1. 基本方針

- 開発モデルは **トランクベース開発** とする
- `main` を唯一のトランクとする
- 変更は小さく保ち、長寿命ブランチを作らない
- 未完成機能をマージする必要がある場合は、機能フラグや安全な分割で扱う

## 2. 開始前の同期

作業開始前に、必ず最新の `main` を取り込む。

```bash
git fetch origin
git switch main
git pull --ff-only origin main
```

作業ブランチを切る場合は、最新の `main` から作る。

```bash
git switch -c <type>/<short-description>
```

ブランチ名の例:

- `feat/multi-account`
- `fix/date-parser`
- `docs/github-operations`
- `refactor/photo-service`
- `test/api-error-cases`

## 3. ブランチ運用

- デフォルトは **短命ブランチ** とする
- ブランチは 1 トピック 1 目的に限定する
- 1 日以上育つブランチは避ける
- 途中で大きくなる場合は、先に分割して段階的にマージする
- `main` への直接 push は避ける
- 緊急修正でも、原則として短命ブランチか PR を使う

小さな変更を高頻度で `main` に戻すことを優先し、ブランチの滞留を防ぐ。

## 4. 実装単位

- 1 回の変更はレビュー可能なサイズに保つ
- リネーム、リファクタ、挙動変更は可能なら分ける
- 仕様変更を伴う場合は、先に `docs/` を更新する
- UI / API / 状態管理など影響範囲が広い変更は、段階的に分けて出す

## 5. 品質ゲート

コードを編集した場合は、コミット前に少なくとも以下を通す。

```bash
uv run ruff check app tests
uv run ruff format app tests
uv run pytest
```

必要に応じて追加で実行する。

```bash
uv run mypy app
uv run pytest tests/e2e/ -v -m e2e
```

ルール:

- `app/` や `tests/` などのコード編集時は、lint / format / test がすべて成功したときだけ commit する
- `docs/`、`README.md`、`CLAUDE.md` などのドキュメント編集のみであれば、品質ゲートを回さずに commit してよい
- 失敗中の状態を一時保存するための commit は作らない
- 実行していない確認項目がある場合は、PR または作業メモに明記する
- ブラウザ自動化や Google Photos の実挙動に影響する変更は、可能なら手動確認も行う

## 6. コミット運用

- commit は意味のある最小単位で行う
- 自動生成的な雑多 commit を避ける
- commit message は変更の意図が分かるものにする

推奨形式:

```text
<type>: <summary>
```

`type` の例:

- `feat`
- `fix`
- `docs`
- `refactor`
- `test`
- `chore`

例:

- `feat: add multi-account session switching`
- `fix: handle missing date labels in photo list`
- `docs: define trunk-based github workflow`

## 7. Pull Request 運用

- PR は小さく保つ
- タイトルはそのまま squash merge の commit message に使える粒度にする
- 説明には少なくとも「目的」「主な変更」「確認内容」「残課題」を書く
- レビュー前にローカルの競合を解消しておく
- `main` との乖離が大きくなったら merge ではなく rebase を優先する

PR に最低限含める内容:

- 何を変えたか
- なぜ必要か
- どう確認したか
- 未確認事項があるか

## 8. マージ方針

- `main` への取り込みは **Squash merge** を基本とする
- マージ前にステータスチェックが通っていることを確認する
- レビュー指摘を取り込んだあと、最終状態でも再度品質ゲートを満たす
- マージ後は不要ブランチを削除する

## 9. 競合解消

- コンフリクト解消時は、両方の変更意図を確認してから解決する
- 機械的に片側を捨てない
- 競合解消後は影響範囲の test を再実行する

## 10. リリースとロールバック

- 破壊的変更は段階的に入れる
- リスクが高い変更は rollback しやすい構成でマージする
- 障害時は trunk を最優先で正常化する
- 修正が長引く場合は revert を優先し、その後に再実装する

## 11. セキュリティと機密情報

以下は commit しない:

- `state/`
- `~/.delete-google-photo/browser-state/`
- `.env*`
- 認証情報、Cookie、セッショントークン
- 手動取得した本番データ

運用ルール:

- 秘密情報をコードや Issue、PR コメントに貼らない
- スクリーンショット共有時は個人情報やメールアドレスを確認する
- Google Photos の実データを使う確認では、最小限の範囲だけ扱う

## 12. gh コマンド運用

`gh` は補助として使うが、運用ルール自体は Git の基本動作に依存させる。

例:

```bash
gh repo view
gh pr status
gh pr create
gh pr view --web
gh pr merge --squash --delete-branch
```

ポイント:

- `gh` がなくても成立するルールにする
- ただし PR 作成、レビュー確認、merge は `gh` で統一すると運用がぶれにくい

## 13. エージェント共通ルール

- Codex / Claude のどちらも、このドキュメントを GitHub 運用の正とする
- 変更後は、実行した確認コマンドと結果を明示する
- 変更に対応するドキュメント更新が必要なら同じ変更セットに含める
- コード変更時は品質ゲートを満たしたうえで、Git 管理下なら適切な commit message で commit する
- ドキュメント変更のみなら、Git 管理下であればそのまま適切な commit message で commit する
- Git 管理下でない場合は、その事実を明示し commit は行わない
