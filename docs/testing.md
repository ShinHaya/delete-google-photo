# テスト方法

## 1. テスト戦略

### 1.1 テストピラミッド

```
           ┌───────────┐
           │  E2E Test │  少数・高コスト
           ├───────────┤
           │Integration│  中程度
           │   Test    │
           ├───────────┤
           │ Unit Test │  多数・低コスト
           └───────────┘
```

### 1.2 テスト種別と目的

| 種別 | 目的 | 対象 |
|------|------|------|
| ユニットテスト | 個別関数の動作検証 | モデル、ユーティリティ、サービス |
| 統合テスト | コンポーネント間連携 | API、サービス層 |
| E2Eテスト | 全体フロー検証 | ブラウザ操作を含む全体 |

## 2. テスト環境

### 2.1 テストフレームワーク
- **pytest**: テスト実行
- **pytest-asyncio**: 非同期テスト
- **pytest-playwright**: Playwrightテスト
- **pytest-cov**: カバレッジ計測

### 2.2 ディレクトリ構成

```
tests/
├── __init__.py
├── conftest.py           # 共通フィクスチャ
├── unit/
│   ├── __init__.py
│   ├── test_models.py
│   ├── test_services.py
│   └── test_utils.py
├── integration/
│   ├── __init__.py
│   ├── test_api.py
│   └── test_state.py
└── e2e/
    ├── __init__.py
    └── test_delete_flow.py
```

## 3. ユニットテスト

### 3.1 対象と方針

| 対象 | 方針 |
|------|------|
| モデル | バリデーション、シリアライズ |
| サービス | ビジネスロジック（外部依存はモック） |
| ユーティリティ | 純粋関数のテスト |

### 3.2 サンプルテスト

```python
# tests/unit/test_models.py
import pytest
from datetime import date
from app.models.state import DeletionState

class TestDeletionState:
    def test_create_state(self):
        state = DeletionState(
            session_id="test-session",
            start_date=date(2020, 1, 1),
            end_date=date(2020, 12, 31),
            total_count=100,
            processed_count=0,
        )
        assert state.session_id == "test-session"
        assert state.progress_percentage == 0.0

    def test_progress_calculation(self):
        state = DeletionState(
            session_id="test-session",
            start_date=date(2020, 1, 1),
            end_date=date(2020, 12, 31),
            total_count=100,
            processed_count=50,
        )
        assert state.progress_percentage == 50.0

    def test_invalid_date_range(self):
        with pytest.raises(ValueError):
            DeletionState(
                session_id="test-session",
                start_date=date(2020, 12, 31),
                end_date=date(2020, 1, 1),  # 終了日が開始日より前
                total_count=100,
                processed_count=0,
            )
```

```python
# tests/unit/test_services.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.photo_service import PhotoService

class TestPhotoService:
    @pytest.fixture
    def mock_browser_client(self):
        return AsyncMock()

    @pytest.fixture
    def photo_service(self, mock_browser_client):
        return PhotoService(browser_client=mock_browser_client)

    @pytest.mark.asyncio
    async def test_count_photos_in_range(self, photo_service, mock_browser_client):
        mock_browser_client.get_photos_in_range.return_value = [
            MagicMock(id="photo1"),
            MagicMock(id="photo2"),
        ]

        count = await photo_service.count_photos_in_range(
            start_date=date(2020, 1, 1),
            end_date=date(2020, 12, 31),
        )

        assert count == 2
```

### 3.3 リトライロジックのテスト

```python
# tests/unit/test_retry.py
import pytest
from app.utils.retry import exponential_backoff

class TestExponentialBackoff:
    @pytest.mark.parametrize("retry_count,expected", [
        (1, 1),   # 1秒
        (2, 2),   # 2秒
        (3, 4),   # 4秒
        (4, 8),   # 8秒
        (5, 10),  # 10秒（上限）
    ])
    def test_backoff_calculation(self, retry_count, expected):
        result = exponential_backoff(retry_count, max_wait=10)
        assert result == expected
```

## 4. 統合テスト

### 4.1 APIテスト

```python
# tests/integration/test_api.py
import pytest
from httpx import AsyncClient
from app.main import app

class TestPhotoAPI:
    @pytest.fixture
    async def client(self):
        async with AsyncClient(app=app, base_url="http://test") as ac:
            yield ac

    @pytest.mark.asyncio
    async def test_health_check(self, client):
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_dry_run_endpoint(self, client, mocker):
        # ブラウザクライアントをモック
        mocker.patch(
            "app.routers.photos.get_browser_client",
            return_value=AsyncMock()
        )

        response = await client.post("/api/photos/dry-run", json={
            "start_date": "2020-01-01",
            "end_date": "2020-12-31"
        })

        assert response.status_code == 200
```

### 4.2 状態管理テスト

```python
# tests/integration/test_state.py
import pytest
import tempfile
from pathlib import Path
from app.services.state_service import StateService

class TestStateService:
    @pytest.fixture
    def temp_state_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def state_service(self, temp_state_dir):
        return StateService(state_dir=temp_state_dir)

    @pytest.mark.asyncio
    async def test_save_and_load_state(self, state_service):
        state = DeletionState(
            session_id="test-session",
            start_date=date(2020, 1, 1),
            end_date=date(2020, 12, 31),
            total_count=100,
            processed_count=50,
        )

        await state_service.save(state)
        loaded = await state_service.load("test-session")

        assert loaded.session_id == state.session_id
        assert loaded.processed_count == 50

    @pytest.mark.asyncio
    async def test_resume_interrupted_state(self, state_service):
        # 中断状態を保存
        state = DeletionState(
            session_id="test-session",
            status="interrupted",
            ...
        )
        await state_service.save(state)

        # 中断状態を検出
        interrupted = await state_service.find_interrupted()
        assert interrupted is not None
        assert interrupted.session_id == "test-session"
```

## 5. E2Eテスト（限定スコープ内・Playwright teardown で復元）

**判断**: 2026-04-08 の方針変更により、**狭い範囲での自動 E2E を
スコープ内に戻した**。ただし CI 実行はしない。ローカル手動起動のみ。

### 5.1 設計方針

削除が不可逆な副作用であることが E2E 自動化の本質的な障害だった。
今回は以下のアプローチでこれを回避する:

1. **teardown で復元する**: テストの削除対象となった写真は、
   Playwright で `/trash` を開き、aria-label の日時文字列で照合して
   「復元」ボタンをクリックすることで元に戻す。これにより同じテスト写真で
   何度でも E2E が回せる
2. **API 復元は不可能**: Google Photos Library API にはゴミ箱からの
   復元エンドポイントが存在せず、さらに 2025-03-31 以降はサードパーティ
   アプリが自アプリ作成以外のメディアに API からアクセスできない。
   したがって「Playwright で消す → API で戻す」案は成立しない
3. **狭い範囲のみ**: 2026-04-01 単日・写真数枚の固定シナリオだけを
   対象にする。大規模シナリオは引き続き手動テスト（`docs/manual-test.md`）で確認

### 5.2 セレクタの要点（2026-04-08 時点で確認済）

`/trash` ページの DOM は `dom-inspector` 相当の手法で実 DOM を直接
調査して確定した。

| 要素 | セレクタ / 備考 |
|------|-------------------|
| trash タイル | `div[role="checkbox"][aria-label^="写真"]` (メインタイムラインと同じ `ckGgle` クラス)。aria-label は `"写真 - 縦向き - YYYY/MM/DD HH:MM:SS"` 形式で、削除前に収集した aria-label とそのまま照合できる |
| 復元ボタン | `button[aria-label="復元"]`。**2 要素存在** するため (hidden 版と visible 版) `getBoundingClientRect` で可視の方を JS 経由でクリック |
| 復元確認ダイアログ | `[role="dialog"]` 内、本文 "ファイルを復元しますか？"。確認ボタンは aria-label=null のテキストボタンなので `[role="dialog"] button:has-text("復元")` でスコープ |
| **絶対クリック禁止** | `button[aria-label="完全に削除"]` (= permanent delete)。選択モードのツールバーに並んでいるので、誤クリック防止のため常に aria-label="復元" に固定する |
| `/photo/<id>` アンカー | **trash ページには存在しない**。したがって photo-id での join は不可能で、aria-label 日時文字列だけが復元時の唯一のキー |

### 5.3 実行方法

```bash
# デフォルトの pytest は e2e マーカーを除外するので、通常の
# unit+integration テストには影響しない
uv run pytest -v   # → 107 tests, 1 deselected

# E2E テストを明示的に実行
uv run pytest tests/e2e/test_delete_and_restore.py -v -m e2e
```

前提:

- `state/browser-state/chrome-profile` に認証済みセッションがあること
  （事前に `uv run python -m uvicorn app.main:app ...` で「Googleでログイン」を実行）
- テスト日 **2026-04-01** に少なくとも 1 枚の写真が存在すること。
  1 枚もない場合はテストは明示的に fail する。aria-label の timestamp が
  衝突しないことも前提（衝突すると復元照合が曖昧になる）

### 5.4 範囲内・範囲外

| スコープ | 対応状況 |
|----------|-----------|
| 単日・数枚の削除 → 復元ラウンドトリップ | **E2E 自動化済み** (`tests/e2e/test_delete_and_restore.py`) |
| 中規模 (100枚〜) / 大規模 (1000枚〜) | 手動テスト継続 (`docs/manual-test.md` 段階 2〜4) |
| 本番削除 | 手動テスト (段階 5) |
| CI での E2E 実行 | **しない**。Google 認証が headful 前提で unattended 実行不可 |

### 5.5 将来の DOM 変更への追随

`/trash` の DOM が変わった場合、以下の順で対応する:

1. `/tmp/inspect_trash_final.py` と同じ要領で `dom-inspector` を再実行し、
   `div[role="checkbox"]` の aria-label prefix や「復元」ボタンの aria-label を確認
2. `app/browser/operations.py` の `restore_photos_from_trash_by_labels` の
   JS 内セレクタを更新
3. 本ドキュメント 5.2 のセレクタ表を更新

## 6. テスト実行

### 6.1 コマンド

```bash
# 全テスト実行
pytest

# ユニットテストのみ
pytest tests/unit/

# 統合テストのみ
pytest tests/integration/

# 特定のテストファイル
pytest tests/unit/test_models.py

# 特定のテスト関数
pytest tests/unit/test_models.py::TestDeletionState::test_create_state -v

# カバレッジ付き
pytest --cov=app --cov-report=html

# 詳細出力
pytest -v --tb=long
```

### 6.2 継続的テスト（開発中）

```bash
# ファイル変更時に自動実行
pytest-watch -- tests/unit/
```

## 7. テストカバレッジ目標

| レイヤー | 目標カバレッジ |
|----------|----------------|
| モデル | 90%以上 |
| サービス | 80%以上 |
| ユーティリティ | 90%以上 |
| API | 70%以上 |
| 全体 | 75%以上 |

## 8. 手動テストチェックリスト

実際のGoogle Photosを使用する手動テストは以下を確認：

### 8.1 認証フロー
- [ ] Googleアカウントでログインできる
- [ ] セッションが維持される
- [ ] ログアウト後に再認証できる

### 8.2 ドライラン
- [ ] 日付範囲を指定できる
- [ ] 削除対象の一覧が表示される
- [ ] 正しい枚数が表示される
- [ ] 日付範囲外の写真は含まれない

### 8.3 削除実行
- [ ] 確認ダイアログが表示される
- [ ] キャンセルで処理が中止される
- [ ] 進捗がリアルタイムで更新される
- [ ] 全対象写真がゴミ箱に移動される
- [ ] ゴミ箱を空にする操作はツールでは実行しない（Google Photos側で行う）

### 8.4 エラーハンドリング
- [ ] ネットワークエラー時にリトライされる
- [ ] リトライ上限後にエラー表示される
- [ ] 中断後にレジュームできる

### 8.5 境界値テスト
- [ ] 0枚の場合の動作
- [ ] 1枚の場合の動作
- [ ] 大量（1000枚以上）の場合の動作

## 9. テストデータ

### 9.1 テスト用Googleアカウント
本番データを保護するため、テスト専用のGoogleアカウントを使用することを推奨。

### 9.2 テストデータの準備
```bash
# テスト用に少数の写真をアップロード
# 削除しても問題ない写真を用意
```
