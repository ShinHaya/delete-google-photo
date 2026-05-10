# ローカル AI 相互レビュー移行計画

## 目的

現在の Codex / Claude 相互レビューは GitHub Actions 上で動作している。
これをローカル PC 上の Git Hooks ベースに移行し、commit 単位で必ず相手側
AI にレビューさせる仕組みに変更する。

第一段階では **自動修正は行わず、レビュー結果をローカルに保存する** ところまでを
対象にする。自動修正まで Hook に含めると、Codex 修正、Claude レビュー、
Claude 修正、Codex レビューの再帰制御が難しくなるため、まずはレビューの確実な
実行と記録を優先する。

## 設計方針

AI ツール固有の `PostToolUse` / `Stop` Hook は使わず、Git 標準の
`post-commit` hook を使う。理由は次の通り。

- Edit / Write のたびに reviewer CLI を起動すると待ち時間とコストが増える
- commit は AI が一区切りの作業を終えたタイミングなのでレビュー単位に合う
- Claude Code / Codex CLI 以外の AI ツールにも横展開しやすい
- 人間が手で commit した場合も同じ仕組みで守れる
- 既存 GitHub Actions 版の PR / commit 起点の運用に近い

`pre-commit` ではなく `post-commit` を選ぶ理由は、`[skip-review]` マーカーの
判定に commit message 全文を読む必要があるため。`pre-commit` にはまだ
コミットメッセージが確定していないので `git log -1 --format=%B` 相当の
情報が得られない。一方で本ツールは reviewer をバックグラウンド起動して
commit 自体は止めない設計のため、「commit を block する」という pre-commit
特有の利点は不要であり、post-commit でも要件を完全に満たせる。

実装は追加ランタイムを避けるため、**生 bash + `core.hooksPath`** を基本にする。
Python / Node.js / Go など特定言語のツールチェーンには依存しない。

## 現状

GitHub Actions 版では次の構成になっている。

- `codex/` で始まるブランチの PR では Claude Code review を実行する
- `claude/` で始まるブランチの PR では Codex review を実行する
- レビュー末尾の `@codex` / `@claude` メンションで相手側 AI に修正を依頼する
- 修正コミットの commit message に `[skip-review]` を入れて無限ループを抑止する

ローカル版では PR / メンション / GitHub Actions を前提にせず、次の考え方に
置き換える。

- ローカルの branch diff をレビュー対象にする
- `codex/*` ブランチの commit では Claude CLI がレビューする
- `claude/*` ブランチの commit では Codex CLI がレビューする
- それ以外のブランチでは何もしない
- レビュー結果は Git 管理外の `state/ai-reviews/` に保存する
- `post-commit` は reviewer CLI をバックグラウンド起動し、commit を止めない

## ディレクトリ構成

追加候補:

```text
.githooks/
├── config
├── post-commit
├── lib/
│   ├── local-ai-review.sh
│   └── last-reviewed.sh
└── prompts/
    ├── local-review-codex.md
    └── local-review-claude.md
scripts/
└── setup-hooks.sh
```

役割:

- `.githooks/post-commit`
  - Git から直接呼ばれる入口
  - branch 判定、skip 条件、バックグラウンド起動だけを担当する
- `.githooks/lib/local-ai-review.sh`
  - diff 取得、reviewer CLI 起動、レビュー結果保存を担当する
- `.githooks/lib/last-reviewed.sh`
  - `last-reviewed.json` の read / write と atomic update を担当する
- `.githooks/config`
  - レビュー対象パス、branch prefix、CLI コマンドなどのプロジェクト固有値を定義する
- `scripts/setup-hooks.sh`
  - `git config core.hooksPath .githooks` を設定する

## セットアップ

初回セットアップは次のコマンドで行う。

```bash
bash scripts/setup-hooks.sh
```

`scripts/setup-hooks.sh` は内部で次を実行する。

```bash
git config core.hooksPath .githooks
```

テンプレート化を見据え、README には次の前提を明記する。

- 必須コマンド: `bash`, `git`, `jq`
- checksum: macOS では `shasum -a 256`、Linux では `sha256sum`
- timeout: macOS では `gtimeout`、Linux では `timeout`
- 必須 CLI: `claude`, `codex`
- 動作確認: テスト用 commit 後に `state/ai-reviews/` に結果が出ること

## 対象範囲

レビュー対象にするファイルは `.githooks/config` で定義する。
本プロジェクトでは次を基本とする。

- `app/`
- `tests/`
- `docs/`
- `scripts/`
- `.githooks/`
- `.github/`
- `.Codex/`
- `.claude/`
- `README.md`
- `AGENTS.md`
- `CLAUDE.md`
- `pyproject.toml`
- `uv.lock`

対象外にするものは次の通り。

- `state/`
- `.venv/`
- `__pycache__/`
- `.pytest_cache/`
- `.mypy_cache/`
- log files
- coverage や build artifacts

## Author / Reviewer 判定

`post-commit` には「どの AI が編集したか」の文脈が無い。
既存の branch 命名規約を使って reviewer を決める。

- `codex/*` ブランチ: Claude CLI を reviewer として起動する
- `claude/*` ブランチ: Codex CLI を reviewer として起動する
- その他のブランチ: reviewer を起動しない

この判定は `.githooks/config` に切り出し、テンプレート展開先で別の
命名規約に置き換えられるようにする。

## Diff の取り方

レビュー対象は単一ファイルや staged diff だけではなく、branch 全体の差分にする。
PR レビューの感覚に近づけ、過去 commit の文脈を含めるため。

基本形:

```bash
BASE=$(git merge-base origin/main HEAD)
git diff "$BASE" -- <対象パス>
```

`post-commit` は HEAD が更新されたあとに動くので、`--cached` は不要で
HEAD までの差分をそのまま使える。

```bash
git diff "$BASE" -- <対象パス>
```

`origin/main` が存在しない場合は、reviewer を起動せず warning を出して exit 0
にする。必要なら `git fetch --no-tags origin main` を実行するかは、実装時に
ネットワーク依存を避ける方針と合わせて決める。

## Skip 条件

次のケースでは reviewer を起動せず exit 0 で抜ける。

- `LOCAL_AI_REVIEW_RUNNING=1` が設定されている
- branch が `codex/*` / `claude/*` に一致しない
- 対象パスの diff が空
- merge commit 中
- rebase 中
- cherry-pick 中
- commit message に `[skip-review]` が含まれる
- `origin/main` との merge-base が取れない
- 直近レビュー済みの branch / merge-base / diff hash と同一

`[skip-review]` は GitHub Actions 版と同じ marker として維持する。

## Reviewer CLI の実行

`post-commit` は commit をブロックしない（そもそも post-commit は exit code を
返しても commit に影響しない）。reviewer CLI はバックグラウンドで起動し、
`post-commit` 本体は即 exit 0 で返す。

macOS では Codex の非対話 command session から `nohup ... &` だけで起動した
background child が完了前に終了することがあるため、`post-commit` はまず
one-shot LaunchAgent plist を作り、`launchctl bootstrap gui/<uid>` で
user launchd に登録する。
`launchctl` が使えない環境では portable fallback として `nohup` を使う。

想定:

```bash
launchctl bootstrap "gui/$(id -u)" "state/ai-reviews/.launch.<sha>.$$.plist"

# fallback
nohup .githooks/lib/local-ai-review-launch.sh "$repo_root" "$githooks_dir" "$state_dir" \
  "$reviewer" "$branch" "$sha" >/dev/null 2>> state/ai-reviews/last-error.log </dev/null &
```

reviewer CLI の失敗は non-blocking とする。
認証切れ、ネットワーク不調、rate limit、CLI 未インストールが起きても commit
自体は成功させ、失敗理由を `state/ai-reviews/last-error.log` に残す。

CLI は read-only 相当で起動する。

- Claude CLI:
  - `claude -p` / `--print` 系で非対話実行する
  - `--allowed-tools Read,Grep,Glob,Bash(git diff:*)` のように Edit / Write / commit 系を外す
- Codex CLI:
  - `codex exec` 系で非対話実行する
  - `--sandbox read-only` など write 不可の設定を使う

正確な option は実装時に `claude --help` / `codex --help` で確認して決める。

## 再帰防止

再帰防止は複数層で行う。

- `post-commit` 起動時に `LOCAL_AI_REVIEW_RUNNING=1` があれば即 exit 0
- reviewer CLI 起動時に `LOCAL_AI_REVIEW_RUNNING=1` を環境変数として渡す
- reviewer CLI は read-only 相当で起動し、ファイル編集や commit を許可しない
- `state/ai-reviews/.lock` で多重起動を防ぐ
- `last-reviewed.json` の diff hash 比較を最終防御にする

lock file は PID と起動時刻を含める。
一定時間を超えた lock は stale と見なして掃除する。timeout は初期値 10 分を
候補にし、`.githooks/config` で変更可能にする。

macOS 標準コマンドだけで動かすため、`gtimeout` / `flock` など Homebrew
依存は必須にしない。PID file + timestamp 方式で stale lock を検出し、
dead PID / malformed lock は `last-run.log` に記録して削除する。
dead PID に紐づく temp file や orphan temp file も同時に回収する。
reviewer 起動後は phase marker、reviewer PID、watchdog PID、signal trap、
cleanup 結果を `state/ai-reviews/last-run.log` / `last-error.log` に残す。

## State 管理

保存先:

```text
state/ai-reviews/
```

ファイル名例:

```text
20260510-153000-claude.md
20260510-153215-codex.md
```

保存内容:

- 実行日時
- branch
- author 判定結果
- reviewer
- merge-base
- diff hash
- 変更ファイル一覧
- reviewer の exit status
- reviewer の出力本文

`last-reviewed.json` の最小構造:

```json
{
  "branch": "claude/issue-87-async-progress-and-interrupt",
  "merge_base": "abc123",
  "last_diff_sha256": "deadbeef",
  "last_reviewed_at": "2026-05-10T15:30:00+09:00",
  "last_reviewer": "codex"
}
```

write は tmpfile + `mv` で atomic に行う。

```bash
jq '...' last-reviewed.json > last-reviewed.json.tmp
mv last-reviewed.json.tmp last-reviewed.json
```

`branch` と `merge_base` を含めることで、ブランチ切り替え後は別差分として扱う。

retention は第一段階では自動削除しない。
運用が安定した後、直近 50 件または 30 日より古いレビュー結果を削除する方針を
追加検討する。

## ローカルレビュー用プロンプト

GitHub Actions 版のプロンプトには PR やメンションを前提にした指示が含まれるため、
ローカルレビュー専用のプロンプトを分ける。

追加候補:

```text
.githooks/prompts/local-review-codex.md
.githooks/prompts/local-review-claude.md
```

プロンプト方針:

- ローカル branch diff をレビューする
- findings first の形式にする
- correctness / regression / security / missing tests / docs consistency を重視する
- 具体的な file / line を可能な範囲で示す
- 問題がなければその旨を明確に書く
- `@codex` / `@claude` メンションは使わない
- commit message や PR コメントを前提にしない
- 自動修正は行わない

## ドキュメント更新

実装時に更新するドキュメント:

- `docs/github-operations.md`
  - GitHub Actions 版の相互レビューを主経路から外す
  - ローカル Git Hooks 版を正本として記載する
- `AGENTS.md`
  - Codex 作業時も commit 時の Claude review が走ることを記載する
- `CLAUDE.md`
  - Claude 作業時も commit 時の Codex review が走ることを記載する
- `docs/development.md`
  - セットアップ、動作確認、レビュー結果の見方を追記する
- `README.md`
  - `bash scripts/setup-hooks.sh` を初回セットアップに追加する

## GitHub Actions の扱い

移行は段階的に行う。

推奨手順:

1. ローカル Git Hooks 版を実装する
2. ローカルで相互レビューが動くことを確認する
3. `.github/workflows/*code-review.yml` を `workflow_dispatch` のみに変更する
4. ローカル版が 2 週間または 5 PR 連続で安定したら削除を検討する

期間中に reviewer CLI のハング、重複起動、レビュー結果の破損が起きた場合は
安定期間をリセットする。退避期間中は月 1 回程度、手動で GitHub Actions 版を
動かしてローカル版との差分を確認する。

## 検証項目

- `bash scripts/setup-hooks.sh` で `core.hooksPath` が `.githooks` になる
- `core.hooksPath` 未設定の clone でセットアップ漏れが分かる
- `codex/*` ブランチの commit で Claude review が queue される
- `claude/*` ブランチの commit で Codex review が queue される
- その他のブランチでは reviewer が走らない
- docs のみを変更した commit でも相手側 AI review が走る
- Python ファイルを変更した commit でも相手側 AI review が走る
- `git commit` が reviewer 完了を待たずに即返る
- reviewer CLI 失敗時に commit 自体は成功する
- `state/ai-reviews/` にレビュー結果または error log が保存される
- 同じ branch / merge-base / diff hash では重複レビューされない
- ブランチ切り替えで前ブランチの diff hash が再 hit しない
- reviewer CLI 実行中に commit が再帰起動しない
- 複数の `git commit` が同時実行されても二重起動しない
- merge / rebase / cherry-pick 中は reviewer が走らない
- `[skip-review]` 付き commit では reviewer が走らない
- 大きな差分では reviewer CLI に渡す前に warn する、またはサイズ上限で skip する
- `state/ai-reviews/` の出力が Git 管理対象にならない

## テンプレート化の追加作業

将来 GitHub Template として他言語プロジェクトへ横展開する場合、次を別作業として
追跡する。

- `.githooks/` ディレクトリ一式をテンプレート成果物にする
- `scripts/setup-hooks.sh` をテンプレート成果物にする
- `.githooks/config` にプロジェクト固有値を集約する
- README 用の `docs/local-ai-review.md` を作る
- `shellcheck .githooks/**/*.sh scripts/*.sh` を CI に追加する
- reviewer CLI 起動部分を stub 化した bash テストを検討する

## Claude レビューへの反映結果

Claude からのレビュー指摘に対し、次を計画へ反映した。

- `PostToolUse` ではなく Git の commit hook を採用する（最終的に
  `[skip-review]` 判定のため `pre-commit` ではなく `post-commit` で実装）
- Python オーケストレーターではなく bash + `core.hooksPath` を採用する
- author 判定は branch prefix で行う
- reviewer CLI は background 起動し、commit を block しない
- merge / rebase / cherry-pick / `[skip-review]` を skip 条件に入れる
- reviewer CLI は read-only 相当で起動する
- diff 起点は `merge-base origin/main` にする
- lock の stale 検出、timeout、atomic write、state 構造を明記する
- `.githooks/`, `scripts/`, `pyproject.toml`, `uv.lock` をレビュー対象に追加する
- GitHub Actions 版の退避期間を具体化する
