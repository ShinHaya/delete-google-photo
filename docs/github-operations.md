# GitHub 運用方針

このドキュメントは、Codex / Claude のどちらでも共通で使う
GitHub 運用ルールを定義する。

## 1. 基本方針

- 開発モデルは **トランクベース開発** とする
- `main` を唯一のトランクとする
- 新規 Issue に着手するときは、必ずその Issue 専用の新規ブランチを切る
- 1 Issue 1 branch を原則とする
- AI + AI 運用を前提とし、Issue / PR はやや大きめでもよい
- 未完成機能をマージする必要がある場合は、機能フラグや安全な分割で扱う

## 2. 開始前の同期

作業開始前に、必ず最新の `main` を取り込む。

```bash
git fetch origin
git switch main
git pull --ff-only origin main
```

作業ブランチは、必ず最新の `main` から作る。

```bash
git switch -c <agent>/issue-<number>-<short-english-slug>
```

ブランチ名の例:

- `codex/issue-87-fix-progress-reporting`
- `codex/issue-88-stabilize-auth-status`
- `claude/issue-28-add-api-tests`

ルール:

- 接頭辞は `codex/` または `claude/` を使う
- ブランチ名には必ず Issue 番号を含める
- 英語スラグは Issue のタイトルと内容から、一目で目的が分かる短い表現にする
- 英語スラグは 3〜6 語程度を目安にし、必要以上に長くしない
- ブランチ作成後は、対応する Issue にそのブランチ名をコメントまたは Description 更新で記録し、Issue からブランチを辿れる状態にする

## 3. ブランチ運用

- デフォルトは **短命ブランチ** とする
- ブランチは 1 トピック 1 目的に限定する
- `main` への直接 push は避ける
- 緊急修正でも、原則として短命ブランチか PR を使う
- 作業中に `main` との差分が広がったら、早めに `main` を取り込む
- `main` 反映は merge より rebase を優先する
- Issue とブランチのリンクが切れないよう、ブランチ名変更時も Issue 側の記載を更新する

トランク開発では、ブランチの滞留を防ぎつつ、各 Issue を独立して追跡できることを優先する。

## 4. 実装単位

- AI + AI 運用では、Issue / PR は人間レビュー前提より少し大きめでもよい
- ただし、1 回のレビューで「目的」「変更内容」「主なリスク」を無理なく説明できる範囲に収める
- 巨大すぎてレビュー・再実行・切り戻しが重くなる変更は避ける
- リネーム、リファクタ、挙動変更は可能なら分ける
- 仕様変更を伴う場合は、先に `docs/` を更新する
- UI / API / 状態管理など影響範囲が広い変更は、段階的に分けて出す

補足:

- 人間レビュー前提のように細かく分割しすぎる必要はない
- ただし、コンテキストの肥大化でレビュー品質が落ちるサイズまでは広げない
- ドラフト PR は必須ではない。長時間作業や並行作業で文脈保持が必要なときだけ使う

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

- `app/` や `tests/` などのコード編集時は、format / lint / test がすべて成功したときだけ commit する
- `docs/`、`README.md`、`CLAUDE.md` などのドキュメント編集のみであれば、品質ゲートを回さずに commit してよい
- ドキュメントを更新した場合は、変更内容を確認したらすぐに commit し、可能ならそのまま push する
- 失敗中の状態を一時保存するための commit は作らない
- 実行していない確認項目がある場合は、PR または作業メモに明記する
- ブラウザ自動化や Google Photos の実挙動に影響する変更は、可能なら手動確認も行う

実施順:

1. `uv run ruff format app tests`
2. `uv run ruff check app tests`
3. `uv run pytest`

## 6. コミット運用

- commit は意味のある最小単位で行う
- 自動生成的な雑多 commit を避ける
- commit message は変更の意図が分かるものにする
- 品質ゲートが成功するまでは commit しない

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

- 1 Issue に関わる機能開発が完了したら PR を作成する
- AI + AI 運用では PR はやや大きめでもよい
- タイトルはそのまま squash merge の commit message に使える粒度にする
- 説明には少なくとも「目的」「主な変更」「確認内容」「残課題」を書く
- レビュー前にローカルの競合を解消しておく
- `main` との乖離が大きくなったら merge ではなく rebase を優先する
- ドラフト PR は任意とする。長時間作業や並行作業時のみ使えばよい

PR に最低限含める内容:

- 何を変えたか
- なぜ必要か
- どう確認したか
- 未確認事項があるか

レビュー担当:

- Codex が開発者のときは Claude Code をレビュアーにする
- Claude Code が開発者のときは Codex をレビュアーにする
- レビューコメントが付いたら、開発者はその対応を行う

GitHub Actions 自動化:

- Claude Code review は `.github/workflows/claude-code-review.yml` で行う
- Codex review は `.github/workflows/codex-code-review.yml` で行う
- 開発者判定は PR author login ではなく **head branch 名の接頭辞** を使う
- `codex/` で始まるブランチの PR では Claude Code review を走らせる
- `claude/` で始まるブランチの PR では Codex review を走らせる
- 接頭辞に一致しないブランチでは、どちらの review workflow も走らせない

レビュー結果からの自動修正（cross-AI auto-fix）:

- レビュー本文の末尾には、相手側 AI への `@codex` / `@claude` メンションを必ず付ける
  - Claude Code review は本文末尾に `@codex` を含める（プロンプトで強制）
  - Codex review は本文末尾に `@claude` を含める（プロンプトおよび post-feedback ジョブで強制）
- 開発者 AI は対応するメンション ワークフローで起動する
  - `@codex` メンション → `.github/workflows/codex.yml` が PR の head ブランチに修正コミットを push
  - `@claude` メンション → `.github/workflows/claude.yml` が同様に修正コミットを push
- 修正コミットの commit message には必ず `[skip-review]` を含める
  - Claude Code review / Codex Code review は head commit message に `[skip-review]` がある場合は skip-check ジョブで早期 skip する
  - これにより「レビュー → 修正 → 再レビュー → ...」の無限ループを抑止する
- `codex.yml` は安全のため次の制約を持つ
  - fork 由来の PR では起動しない
  - head ブランチが `codex/*` でない場合は起動しない
  - Claude Code review が App (`claude[bot]`) として投稿した `@codex` コメントでも動くよう、`openai/codex-action` では bot 実行を許可する

@claude メンションの起動には PAT が必要:

- GitHub Actions の仕様で、`GITHUB_TOKEN` が authored した PR コメントは
  後続ワークフローを起動しない（recursion-prevention ルール）
- `codex-code-review.yml` の `post-feedback` ジョブは `github-script` で
  コメントを投稿しているため、既定の `GITHUB_TOKEN` のままでは
  コメントが `github-actions[bot]` 名義となり、`claude.yml` の
  `issue_comment` トリガーが発火しない
- これを解決するため、`post-feedback` は secret `AI_REVIEW_TRIGGER_PAT`
  を優先して使う。未設定時は `GITHUB_TOKEN` にフォールバックするので
  コメント投稿自体は成功するが、`@claude` 自動修正は動かない
- `@codex` メンションは claude-code-action が App (`claude[bot]`) として
  投稿するため PAT なしでも `codex.yml` を起動できる。`codex.yml` 側では
  `openai/codex-action` の `allow-bots` を有効にして、GitHub App 投稿の
  コメントでも write-access check で落ちないようにする

mention trigger の確認手順:

1. `codex/*` または `claude/*` 接頭辞の head branch を持つテスト用 PR を作る
2. 対応する review workflow がレビューコメント末尾に `@codex` または `@claude` を投稿することを確認する
3. `gh run list --workflow codex.yml` または `gh run list --workflow claude.yml` で、対象 mention を受けた workflow run が作成されていることを確認する
4. run が failed の場合は `gh run view <run-id> --log-failed` で、event 条件不一致・branch guard・bot / permission check のどこで止まったかを確認する

必要な secret:

- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`
- `AI_REVIEW_TRIGGER_PAT` (cross-AI auto-fix を有効化する場合のみ)

`AI_REVIEW_TRIGGER_PAT` の条件:

- Classic PAT であれば `repo` スコープ
- Fine-grained PAT であれば対象 repository に対し
  `Pull requests: write` と `Issues: write` を付与
- repository admin が発行したトークンで問題ない。個別の GitHub App を
  用意する必要はない

例:

```text
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
AI_REVIEW_TRIGGER_PAT=ghp_... もしくは github_pat_...
```

設定手順:

1. GitHub で対象 repository を開く
2. `Settings` > `Secrets and variables` > `Actions` を開く
3. `Secrets` タブで上記の Actions secrets を追加する
4. `codex/` または `claude/` 接頭辞のブランチからテスト用 PR を作成する
5. 想定した AI review workflow が動くことを確認する
6. PAT 設定後の確認方法として、`claude/` 接頭辞のブランチで PR を作り
   Codex review 実行後に post された `@claude` コメントから
   `claude.yml` が起動することを `gh run list --workflow=claude.yml`
   で確かめる

## 8. マージ方針

- `main` への取り込みは **Squash merge** を基本とする
- マージ前にステータスチェックが通っていることを確認する
- レビュー指摘を取り込んだあと、最終状態でも再度品質ゲートを満たす
- マージ後は不要ブランチを削除する
- レビュー未解決のままマージしない

Issue の close タイミング:

- **Issue は原則、PR 作成前に閉じない。** 通常は PR が merge されたタイミングで close する
- PR 本文に `Closes #<issue>` / `Fixes #<issue>` を含め、squash merge 時に GitHub 側で自動 close させるのを基本とする
- 自動 close が効かないケース（PR と Issue の対応がずれた、複数 Issue を 1 PR でまとめた、など）は、merge 完了後に `gh issue close <n>` で明示的に閉じる
- ローカルでドキュメント修正だけ行って commit した段階では Issue を閉じない。push → PR 作成 → merge という一連の流れが完了して初めて close してよい
- 「実装は完了したが PR をまだ作っていない」状態で Issue を閉じない。該当 Issue が PR 前に閉じていると、レビューや自動化（AI レビュー、`gh` ベースの状態確認など）からそのタスクが追えなくなる

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

GitHub 上の operation（Issue / PR / review / merge など）をローカルから
行う場合は、**原則として `gh` コマンドを使う**。ブラウザ UI でも可能だが、
Codex / Claude を含むエージェント運用では手順再現性のために `gh` を基本とする。

運用ルール:

- Issue の参照・コメント・close、PR の作成・レビュー取得・merge は `gh` から行うのを基本とする
- `git push` など Git そのものの操作は従来どおり `git` コマンドを使う
- `gh` が使えない環境（一時的に未インストール、認証切れなど）では、Web UI で代替してよいが、その旨を作業ログ / PR 本文に明示する

よく使うコマンド:

```bash
gh repo view
gh issue view <number>
gh issue comment <number> --body "..."
gh issue close <number>
gh pr status
gh pr create
gh pr view --web
gh pr review <number> --comment --body "..."
gh pr merge --squash --delete-branch
```

ポイント:

- ルール自体は Git の基本動作（branch / commit / push）で成り立つように書く
- その上で GitHub 固有の状態変更（Issue / PR / review / merge）は `gh` で統一し、運用をぶらさない

## 13. エージェント共通ルール

- Codex / Claude のどちらも、このドキュメントを GitHub 運用の正とする
- 変更後は、実行した確認コマンドと結果を明示する
- 変更に対応するドキュメント更新が必要なら同じ変更セットに含める
- コード変更時は品質ゲートを満たしたうえで、Git 管理下なら適切な commit message で commit する
- ドキュメント変更のみなら、Git 管理下であればそのまま適切な commit message で commit し、続けて push する
- Git 管理下でない場合は、その事実を明示し commit は行わない
- GitHub Issue の状態管理をタスク管理の正とし、ローカルの TODO ファイルには依存しない
- Issue の close タイミングは § 8 に従う（原則として PR 作成前に閉じず、merge 時に自動 close させる）
- ローカルから GitHub に対して行う operation（Issue / PR / review / merge）は § 12 に従って `gh` コマンドを基本とする

## 14. 実装方針の置き場所

- 実装方針の正本は GitHub Issue に置く
- 少なくとも「スコープ」「実装方針」「判定ルール」「未解決事項」は Issue の Description または Issue コメントで共有する
- レビュアーや別エージェントが読む前提の情報は、ローカル専用メモだけに置かない
- ローカルの計画ファイルは補助用途に限る。Issue に書かれていない内容を正本扱いしない
- 長文の設計が必要なら、リポジトリ内の `docs/` に設計メモを置き、そのリンクを Issue に貼る

運用ルール:

1. 実装前に Issue の Description またはコメントへ方針を記載する
2. 方針変更があったら、最新の方針が分かるように Issue を更新する
3. PR 作成時は、参照した Issue の方針と差分がないか確認する

Issue に書く実装方針のテンプレートは
`docs/issue-implementation-plan-template.md` を使う。

## 15. Plan モード運用

- Codex / Claude Code の Plan モードや内部プランは、作業を進めるための補助として使ってよい
- ただし、Plan モードの内容そのものを共有の正本とみなさない
- 別エージェントやレビュアーに読んでほしい内容は、Issue またはリポジトリ内ファイルへ転記する
- ワークスペース外のローカルファイル、ツール固有の内部状態、個人専用メモにだけ残した情報には依存しない

補足:

- Codex の Plan は進行管理・段取り整理のために使う
- Claude Code 側でローカルに計画ファイルを書き出す運用があっても、そのファイルが共有可能である保証はない
- 共有したい計画は Git 管理下のファイルか GitHub Issue に置く
