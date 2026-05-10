# `docs/local-ai-review-plan.md` レビュー結果

レビュー日: 2026-05-10
レビュアー: Claude (Opus 4.7)
対象: `docs/local-ai-review-plan.md` (現状版)
参照した実装ファイル:

- `.claude/settings.local.json`
- `.Codex/settings.local.json`
- `.github/workflows/claude-code-review.yml`
- `.github/workflows/codex-code-review.yml`
- `.github/workflows/claude.yml`
- `.github/workflows/codex.yml`
- `.gitignore`
- `CLAUDE.md` / `AGENTS.md`
- `docs/github-operations.md`

## 総評

ローカル AI 相互レビューへ移行する方向性自体は妥当。現在の GitHub Actions
版は PR 起点で発火するため、push する前のローカル開発中ではレビューが
走らない、という穴を埋められる。

第一段階で「レビューだけ・自動修正なし」に絞ったのも、再帰制御の難所を
避ける順番として正しい。

ただし以下の論点は実装着手前に詰めておかないと、Hook が頻発して開発を
詰まらせる、もしくは想定どおり走らない、という問題が出やすい。重大度
の高い順に整理する。

なお、本仕組みは将来 GitHub Template として他言語プロジェクトにも
横展開する想定がある。そのため計画書の前提となる **「AI ツール固有 Hook
ではなく Git 標準の機構を使う」「Python に依存しない」** という制約も
レビュー観点に含めている。

---

## 重大: 設計の見直しを推奨

### R1. `PostToolUse` ではなく Git の `pre-commit` を使う

**問題**

Claude Code の `PostToolUse` は **Edit/Write が発火するたびに毎回**
fire する。1 つの Issue 対応で Edit/Write が 10〜30 回呼ばれるのは
普通で、その都度 reviewer CLI を起動するとコストと待ち時間が爆発する。

具体的に何が起きるか:

- 1 ターンに 5 ファイル編集 → reviewer CLI を 5 回起動
- 各 reviewer 実行が 30〜120 秒程度かかる前提で、ターンごとの待ち時間が直線的に増える
- diff hash で重複排除しても、1 編集ごとに diff が変わるため hit しない
- uv + reviewer CLI の起動コストだけでも積み上がる

加えて、**`PostToolUse` は Claude Code / Codex CLI 固有の概念**
なので、計画書のもう一つの目的である「テンプレ化して他プロジェクトに
横展開する」と相性が悪い。新しい AI ツールが増えるたびに、その
ツール固有の Hook 仕様で設定を書き直すことになる。

**推奨**

**Git の `pre-commit` hook 一本に統一する。**

採用理由:

1. **commit も AI 自身が行う運用** が前提なので、`pre-commit` の発火
   タイミングは「AI が一区切りの作業を終えた瞬間」と一致する。
   Stop hook と比べて意味的な差が無い
2. **AI ツール非依存**。`.claude/` も `.Codex/` も、将来の別ツールも
   特別扱いしないで済む
3. **commit 単位 = レビュー単位** に揃うので `state/ai-reviews/` の
   記録と git history を commit hash で紐づけられる
4. 人間が手で commit したときも同じ仕組みで守られる
5. GitHub Actions 版の発火条件 (PR の commit) と semantics が近く、
   退避〜削除の判断がしやすい

`PostToolUse` も `Stop` も使わない。

#### R1-1. ツールチェーンは「生 bash + `core.hooksPath`」

`pre-commit` を選ぶときの実装手段は複数ある (pre-commit framework /
husky / lefthook / 生 bash)。今回は **テンプレ化を目的に他言語にも
横展開する** ため、追加ランタイム不要な **生 bash + `core.hooksPath`** を
採用する。

| 案 | 追加ランタイム | テンプレ portable | 採否 |
|----|-----------------|--------------------|------|
| pre-commit framework | Python | ✕ Python 必須 | 不採用 |
| husky | Node.js | ✕ Node 必須 | 不採用 |
| lefthook | Go バイナリ | ◎ ただし要 install | 次点 |
| **生 bash + `core.hooksPath`** | bash + jq のみ | ◎ | **採用** |

具体構成:

```text
.githooks/
├── pre-commit                  # bash, ~30 行 (gate と branch 判定)
└── lib/
    ├── local-ai-review.sh      # bash + jq, ~100 行 (本体)
    └── last-reviewed.sh        # state I/O ユーティリティ
scripts/
└── setup-hooks.sh              # `git config core.hooksPath .githooks`
```

セットアップ:

```bash
git config core.hooksPath .githooks
```

これを `scripts/setup-hooks.sh` として README で叩いてもらう。
忘れ防止が気になるなら CI で `git config --get core.hooksPath` が
`.githooks` であることを assert する 1 ステップを足す。

#### R1-2. オーケストレーター言語も bash + jq

計画書原案では Python (`scripts/local_ai_review.py`) が
オーケストレーターになっていたが、これも **bash + jq に置き換える**。

理由:

- テンプレ化先が Python 非対応の言語 (Go / Rust / TS など) になり得る
- pre-commit hook 本体が bash になる以上、サブプロセス起動コスト的にも
  bash 直書きの方がシンプル
- 必要な処理 (diff 取得 / sha256 / state JSON read-write / reviewer CLI
  起動) は bash + jq で 100 行程度に収まる

bash で書きづらい部分 (細かいテスト・型) は割り切る。
`set -euo pipefail` + `shellcheck` で最低限の品質を担保する。

#### R1-3. Author 判定は branch 名で行う

`pre-commit` には「どの AI が編集したか」の文脈が無い。既存運用
(`codex/*` / `claude/*` ブランチ命名) を流用する:

- `codex/*` から commit → Claude を reviewer として呼ぶ
- `claude/*` から commit → Codex を reviewer として呼ぶ
- それ以外のブランチでは何もしない (テンプレ展開先で命名規約が違う
  場合は `.githooks/config` 的なファイルで上書きできるようにする)

GitHub Actions 版の判定ロジックと完全に揃うので、移行コストが小さい。

#### R1-4. commit を block しない

`pre-commit` は同期で commit を待たせる。reviewer CLI が 1〜2 分
かかると commit ごとに 1〜2 分待ち、になる。これは UX 上厳しい。

**`pre-commit` は reviewer CLI をバックグラウンド (`nohup ... &` 等)
で起動して即 exit 0** で抜け、結果は `state/ai-reviews/` に書くだけに
する。レビュー失敗で commit を止めない、というポリシーを明文化する
(R5 と整合)。

#### R1-5. fire するべきでない commit を弾く

`pre-commit` は次のケースでも発火するので、ガードを入れる:

- merge commit (`git rev-parse -q --verify MERGE_HEAD` がヒット)
- rebase 中 (`.git/rebase-merge` / `.git/rebase-apply` が存在)
- cherry-pick 中 (`.git/CHERRY_PICK_HEAD` が存在)
- commit message に `[skip-review]` が含まれる場合 (auto-fix commit を
  想定。GitHub Actions 版と同じ marker)

これらでは reviewer を呼ばずに即 exit 0。R3 の diff 算出が壊れるため。

### R2. 再帰防止の `LOCAL_AI_REVIEW_RUNNING` が効かないケースがある

**問題**

計画書の意図は次のとおり:

1. AI が編集 → AI Hooks が `local_ai_review` を起動
2. スクリプトが `LOCAL_AI_REVIEW_RUNNING=1` を立てて相手 AI CLI を呼ぶ
3. 相手 AI CLI が編集 → その Hooks が起動するが、env var を見て即終了

`pre-commit` 主体に切り替えると、再帰の経路が変わる:

- AI が commit → `pre-commit` が reviewer CLI を起動
- reviewer CLI 内部で git 操作 (例: `git diff`) は問題ないが、
  reviewer がリポジトリ内のファイルを編集して **自分で commit を作る**
  と再帰が起きる

**推奨**

- 第一段階の「reviewer は read-only」はドキュメント上の方針ではなく、
  reviewer CLI の起動オプションで強制する
  - Claude CLI: `--allowed-tools Read,Grep,Glob,Bash(git diff:*)` 等で
    Edit/Write/commit 系を外す
  - Codex CLI: `sandbox: read-only` または `safety-strategy: drop-write`
    系を使う (具体名は実装時に `codex --help` で確認)
- 加えて、`LOCAL_AI_REVIEW_RUNNING=1` を `pre-commit` から起動する
  reviewer CLI に環境変数で渡し、もし reviewer 内部から再 commit が
  走った場合は `pre-commit` 側で env var を見て即 exit 0
- diff hash の last-reviewed 比較を **「直前と同じ差分なら何もしない」
  の最終防御** として位置づける、と計画書に明記する

### R3. レビュー対象 diff の取り方があいまい

**問題**

> `git diff -- <対象パス>` でレビュー対象差分を取得する

このコマンドは「working tree と直近 commit の差分」しか拾わない。
トランクベース開発で 1 Issue = 1 branch を回しているので、
`pre-commit` の起動時点では:

- `git diff --cached` → これから commit する staged 差分
- `git diff $(git merge-base origin/main HEAD)` → ブランチ全体の差分

の 2 つを区別する必要がある。

PR レビューと感覚を揃えるなら **後者 (branch 全体)** が望ましい。
今 commit する分だけを見ても、過去 commit の文脈が抜けて指摘の質が
落ちる。

**推奨**

`pre-commit` 内で次のように差分を取る:

```bash
BASE=$(git merge-base origin/main HEAD)
git diff "$BASE" -- <対象パス>
```

加えて、`pre-commit` は staged 差分も合わせて含めたいので
`git diff "$BASE"` のあとに staged 内容も add 済みなので
`git diff "$BASE" --cached -- <対象パス>` で十分。
計画書の §1 と §2 のサンプルでこのコマンドを明示する。

`origin/main` が無い (fresh clone 直後) ケースも考え、
`git fetch --no-tags origin main` を先に走らせる、または
`origin/main` が存在しない場合は何もしない、というガードを入れる。

---

## 中程度: 実装着手前に詰めるべき

### R4. Lock file の stale 検出と timeout が無い

`state/ai-reviews/.lock` を使う方針は妥当だが、以下が未定義:

- reviewer CLI が長時間ハングした場合の上限 (タイムアウト)
- プロセス kill / クラッシュで lock が残ったときの掃除

最低限:

- `flock` (macOS なら `flock(1)` 相当が必要なので Homebrew の
  `util-linux` を入れるか、PID ファイル方式にフォールバック)、
  もしくは PID + 起動時刻 を lock file に書き、N 分以上経過していれば
  stale と見なす
- reviewer CLI の subprocess に明示的に `timeout(1)` (GNU coreutils)
  を被せる (e.g. 10 分超えたら kill する)

をスクリプト側で実装する、と §3 に追記する。テンプレで配ることを
考えると、macOS 標準の bash 3.2 + 標準コマンドだけで動くか、
`brew install coreutils flock` を README に書くかをはっきりさせる。

### R5. reviewer CLI の失敗を Hook 側でどう扱うかが未定義

reviewer CLI が

- 認証切れで失敗
- ネットワーク不調で 5xx
- API rate limit
- そもそも CLI 未インストール

した場合、`pre-commit` は **non-zero で抜けるべきか、warn して 0 で抜ける
べきか** が決まっていない。`pre-commit` が non-zero で抜けると
**commit がブロックされる**。レビュー失敗で commit が止まるのは
過剰なので、設計方針を明示する。

**推奨**

- reviewer CLI の失敗は基本 **non-blocking**: stderr に warning を出して
  exit 0 で抜ける
- ただしユーザーが気づける形で残す: `state/ai-reviews/last-error.log` 等
- 検証項目に「reviewer CLI が起動できなかったとき、commit 自体は成功する」
  を追加する
- R1-4 と整合: そもそもバックグラウンド起動なので失敗しても
  `pre-commit` 本体には伝わらない設計にする

### R6. `.githooks/` と `scripts/` がレビュー対象範囲に入っていない

§「対象範囲」のリストに `.githooks/` も `scripts/` も無い。今回の実装で
`.githooks/pre-commit` `.githooks/lib/*.sh` `scripts/setup-hooks.sh`
を新設するので、**この実装自体が将来の自分自身のレビュー対象から外れる**。

**推奨**

`.githooks/` と `scripts/` を対象範囲に追加する。`pyproject.toml`
(あるいは他言語での lockfile) も足しておくと、依存変更時に相互レビューが
走る。

### R7. `state/ai-reviews/` の retention 方針が無い

レビューファイルが timestamp 単位で増え続ける。半年使えば数百ファイルに
なって grep もしづらくなる。

**推奨**

最低限のいずれかを §2 に追記:

- 直近 N 件 (例: 50) だけ残す
- M 日 (例: 30) より古いものは消す
- ブランチがマージされた時点で当該ブランチ分はクリアする

第一段階では「自動掃除はしない」でも構わないが、**そう決めた、と
明示的に書く** こと。

### R8. `last-reviewed.json` の atomic write / 構造が未定義

複数 `pre-commit` が同時に走ること (例: 別ターミナルで commit) や、
バックグラウンドの reviewer 完了通知と次の commit が衝突したときに
`last-reviewed.json` が壊れるとレビュー記録が崩壊する。

**推奨**

- write は tmpfile + `mv` (POSIX `rename(2)`) で atomic に行う
- 構造を §3 で明示する。例:

```json
{
  "branch": "claude/issue-87-async-progress-and-interrupt",
  "merge_base": "abc123...",
  "last_diff_sha256": "deadbeef...",
  "last_reviewed_at": "2026-05-10T15:30:00+09:00",
  "last_reviewer": "codex"
}
```

- jq で書き換える際は `jq '...' last.json > last.json.tmp && mv last.json.tmp last.json` パターンを使う
- `merge_base` と `branch` を含めることで、**ブランチを切り替えると
  自動的に「未レビュー扱い」** になる

### R9. 同期実行で開発体験が劣化する

`pre-commit` は同期で commit を待たせる。reviewer CLI が 1〜2 分走ると
commit ごとに待たされる。R1-4 と重複するが、強調のため独立項目で残す。

**推奨**

- reviewer CLI の起動を **バックグラウンド (`nohup ... &` または
  `setsid ... &`)** にし、結果は `state/ai-reviews/` に書くだけにする
- `pre-commit` の前面では「review queued」「review finished」を
  一行ログで残す程度にする
- 検証項目に「`git commit` が reviewer 完了を待たずに即返る」を追加する

ただしバックグラウンド化すると lock との整合 (R4) を厳密にする必要が
あるので、R4 とセットで設計する。

---

## 軽微: 文章 / 表現上の指摘

### R10. GitHub Actions 版を残す期間が抽象的

> 一定期間問題がなければ削除を検討する

「一定期間」が抽象的。具体的な切り戻し目安を入れる。例:

- ローカル Hooks 版が **2 週間 / 5 PR 連続で安定** したら削除
- 期間中に 1 度でも reviewer CLI が固まる等の事故があれば期間をリセット

### R11. 検証項目に追加してほしい観点

§「検証項目」に以下を追記すると抜け漏れが減る:

- `git commit` が reviewer 完了を待たずに即返る (R9)
- reviewer CLI 失敗時に commit 自体は成功する (R5)
- ブランチ切り替えで前ブランチの diff hash が再 hit しない (R8)
- 大きな差分 (e.g. 100 ファイル) でも reviewer CLI に渡す前に
  一定サイズで足切りされる、または warn が出る
- 複数の `git commit` が同時実行されても二重起動しない (R4)
- merge / rebase / cherry-pick / `[skip-review]` 付き commit で
  reviewer が走らない (R1-5)
- `core.hooksPath` 未設定の clone でも明示的に分かる形で fail する
  (テンプレ運用観点)

### R12. 「Claude に確認してほしい論点」への回答

計画書末尾の論点に答える形でメモを残す。

1. **Hook の発火タイミングを `PostToolUse` のままにするべきか**
   → No。Git の `pre-commit` (生 bash + `core.hooksPath`) を採用 (R1)。
   テンプレ化で他言語に展開する前提なので AI ツール固有 Hook は使わない。

2. **レビュー対象を `git diff` 全体にするか、編集ファイル単位にするか**
   → 全体推奨。`git merge-base origin/main HEAD` 起点の branch diff
   一括で十分。編集ファイル単位はレビューの文脈が削れて指摘の質が落ちる。

3. **reviewer CLI に read-only 相当の制限をかける方法**
   → Claude CLI: `--allowed-tools Read,Grep,Glob,Bash(git diff:*)` で
   Edit/Write/commit 系を外す。Codex CLI: `sandbox: read-only`
   または `safety-strategy: drop-write` 系を使う (具体名は実装時に
   `codex --help` で確認)。`docs/github-operations.md` に追記する。

4. **`last-reviewed.json` の粒度**
   → R8 で示した 5 フィールド (`branch`, `merge_base`,
   `last_diff_sha256`, `last_reviewed_at`, `last_reviewer`) を最小限と
   する。

5. **GitHub Actions 版を `workflow_dispatch` に退避する方針で十分か**
   → Yes、ただし R10 の通り基準を具体化する。退避中は `workflow_dispatch`
   を手動で叩いて「ローカル版で見落とした観点が無いか」を月 1 で
   サンプリングする運用にすると安全。

6. **CLI 非対話実行コマンド**
   → 計画段階で確定させる必要は無いが、最低限:
   - Claude CLI: `claude -p "<prompt>" --output-format json` または
     `--print` 系
   - Codex CLI: `codex exec --prompt-file ... --output-file ...`
   実装時に最新の `--help` で確認する旨を §1 に明記。

---

## テンプレ化を見据えた追加観点

本仕組みを GitHub Template として他言語プロジェクトに横展開する前提を
踏まえ、計画書に以下のセクションを追加することを推奨する。

### T1. テンプレ抽出時に分離する成果物

- `.githooks/` ディレクトリ一式 (bash スクリプト群)
- `scripts/setup-hooks.sh`
- `.githooks/prompts/local-review-codex.md` / `local-review-claude.md`
- `docs/local-ai-review.md` (運用説明、テンプレ展開先 README 用)

### T2. プロジェクト固有設定の外出し

テンプレを言語非依存にするため、プロジェクト固有の値は環境変数か
設定ファイルに分離する:

- レビュー対象パス (例: `app/` `tests/` は本プロジェクト固有)
- ブランチ命名規約 (`codex/*` / `claude/*` を別ツールに合わせる場合)
- reviewer CLI のコマンド名 / オプション

具体的には `.githooks/config` をリポジトリ管理対象として置き、
`pre-commit` から `source .githooks/config` で読む形が portable。

### T3. 動作前提を README に明記する

テンプレ展開先で `pre-commit` が空振りしないために、以下を README に
列挙する:

- 必須コマンド: `bash` (>=3.2)、`git`、`jq`、`sha256sum` (macOS なら
  `shasum -a 256`)、`timeout` (macOS なら `gtimeout` or `coreutils`)
- 必須 CLI: `claude`、`codex` (使う側のみ)
- セットアップ: `bash scripts/setup-hooks.sh` (= `git config core.hooksPath .githooks`)
- 動作確認: テスト用 commit を作り `state/ai-reviews/` に出力されるか確認

### T4. テンプレ自身の CI

テンプレ用リポジトリでは、以下を CI で守る:

- `shellcheck .githooks/**/*.sh scripts/*.sh`
- `bats` などで bash の最低限のテスト (diff hash 算出、stale lock 判定)
- 実際の reviewer CLI 起動はスタブで代替し、I/O 規約だけ確認する

これらはテンプレ抽出時に決めれば良いが、本プロジェクトでも
**最初から bash 部分に shellcheck をかけられる構造で書いておく** と
あとで楽になる。

---

## 優先度サマリ

| ID  | 重大度 | 内容                                                       |
| --- | ------ | ---------------------------------------------------------- |
| R1  | 重大   | `PostToolUse` をやめ、生 bash + `core.hooksPath` の `pre-commit` に統一 |
| R2  | 重大   | reviewer の read-only 制限を CLI オプションで強制する      |
| R3  | 重大   | diff の起点を `merge-base origin/main` に統一する          |
| R4  | 中     | Lock の stale 検出と reviewer の timeout                   |
| R5  | 中     | reviewer 失敗時の non-blocking 方針を明示                  |
| R6  | 中     | `.githooks/` `scripts/` を対象範囲に追加                   |
| R7  | 中     | `state/ai-reviews/` の retention 方針                      |
| R8  | 中     | `last-reviewed.json` の atomic write (`mv`) と構造定義     |
| R9  | 中     | reviewer CLI のバックグラウンド実行                        |
| R10 | 軽微   | GitHub Actions 退避期間を具体化                            |
| R11 | 軽微   | 検証項目の追加                                             |
| R12 | 軽微   | 論点への回答                                               |
| T1  | 軽微   | テンプレ抽出時の成果物リスト                               |
| T2  | 軽微   | プロジェクト固有設定の外出し                               |
| T3  | 軽微   | 動作前提を README に明記                                   |
| T4  | 軽微   | テンプレ自身の CI (shellcheck / bats)                      |

## 結論

計画の **方向性は OK**。ただし R1〜R3 (Hook 種別、reviewer の権限制御、
diff 起点) は実装着手前に計画書を更新してから進めるべき。これらは
後から直すと Hook 設定とスクリプトの両方を書き直す必要があり、
コストが大きい。

特に R1 については、テンプレ化を見据えて **最初から生 bash +
`core.hooksPath` で組む** ことを強く推奨する。Python で書いて後で
bash に書き直す道筋はテストごと作り直しになるので、初手から bash で
書く方が総コストが低い。

R4〜R9 は実装中に詰めて構わないが、計画書の §3 に「実装時に決める」
と明記すると抜けが減る。T1〜T4 はテンプレ抽出フェーズの作業項目として
別途トラッキングする。
