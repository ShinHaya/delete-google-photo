# セキュリティチェック

## 1. セキュリティ方針

### 1.1 基本原則
- **最小権限の原則**: 必要最小限のアクセス権限のみを使用
- **多層防御**: 複数のセキュリティ対策を組み合わせる
- **ローカル実行限定**: 機密情報は外部に送信しない。ツール自体がローカル
  macOSでの実行に限定されており、Cloud Run等のリモート実行はスコープ外

### 1.2 脅威モデル

| 脅威 | 影響度 | 対策 |
|------|--------|------|
| セッション漏洩 | 高 | ローカル保存、暗号化 |
| 不正アクセス | 高 | localhost限定 |
| 誤削除 | 高 | ドライラン、確認プロンプト |
| CSRF攻撃 | 中 | CSRFトークン |
| XSS攻撃 | 中 | 入力サニタイズ |

## 2. 認証・認可

### 2.1 Google認証

**リスク**: Googleアカウントのセッション情報が漏洩すると、アカウントへの不正アクセスが可能になる。

**対策**:
```python
# Playwrightのセッション保存はローカルディレクトリに限定
BROWSER_STATE_DIR = Path.home() / ".delete-google-photo" / "browser-state"
BROWSER_STATE_DIR.mkdir(parents=True, exist_ok=True)
BROWSER_STATE_DIR.chmod(0o700)  # 所有者のみアクセス可能
```

### 2.2 セッション管理

```python
# セッションファイルのパーミッション設定
import os
import stat

def secure_save(filepath: Path, content: str) -> None:
    """セキュアにファイルを保存"""
    filepath.write_text(content)
    os.chmod(filepath, stat.S_IRUSR | stat.S_IWUSR)  # 600
```

## 3. ネットワークセキュリティ

### 3.1 ローカルホスト限定

```python
# app/main.py
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",  # localhostのみ
        port=8000,
    )
```

**チェックリスト**:
- [ ] `0.0.0.0` でリッスンしていない
- [ ] 外部からのアクセスを受け付けない
- [ ] ファイアウォール設定を確認

### 3.2 HTTPS

本ツールはローカルの `127.0.0.1:8000` でのみリッスンするため、
HTTPSは不要。クラウド実行はスコープ外のため考慮しない。

## 4. 入力検証

### 4.1 日付入力の検証

```python
from datetime import date
from pydantic import BaseModel, field_validator

class DateRangeRequest(BaseModel):
    start_date: date
    end_date: date

    @field_validator("end_date")
    @classmethod
    def validate_date_range(cls, v: date, info) -> date:
        start = info.data.get("start_date")
        if start and v < start:
            raise ValueError("終了日は開始日以降である必要があります")
        return v

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_reasonable_date(cls, v: date) -> date:
        # 2000年以降、未来の日付でないことを確認
        if v.year < 2000:
            raise ValueError("2000年以降の日付を指定してください")
        if v > date.today():
            raise ValueError("未来の日付は指定できません")
        return v
```

### 4.2 XSS対策

```python
# Jinja2テンプレートで自動エスケープを有効化
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(
    directory="app/templates",
    autoescape=True,  # デフォルトで有効だが明示的に指定
)
```

## 5. CSRF対策（スコープ外）

**判断**: 本ツールでは CSRF 対策を実装しない。

### 5.1 スコープ外とした理由

| 要素 | 内容 |
|------|------|
| 待ち受けアドレス | `127.0.0.1` のみ。外部ネットワークからは到達不可 |
| 利用形態 | 単一ユーザーが手元のブラウザから操作するバッチツール |
| 実行頻度 | 数万枚を一度〜数回削除する一回限りの作業 |
| 攻撃シナリオ | 攻撃者サイトが `http://127.0.0.1:8000/api/photos/delete` に対して CSRF 攻撃を試みるには、被害者がツールを起動中であり、かつ Google 認証を済ませた状態である必要がある。さらに削除対象の日付範囲も攻撃者には未知 |
| 影響 | 仮に成立しても削除は「ゴミ箱に移動」までで完全削除ではない（ツール側の要件変更により）。Google Photos の通常仕様で60日以内なら復元可能 |

CSRF 対策の実装コスト（CSRF ミドルウェア + フロントエンド改修 + テスト）は、
上記リスクに対して過剰と判断した。

### 5.2 もし将来スコープが変わったら

以下のいずれかが変わった場合、CSRF 対策の再検討が必要:

- 待ち受けを `0.0.0.0` や LAN に開放する
- 複数ユーザーが同一ホストで利用する
- 削除以外の不可逆操作（完全削除等）をツール内で行う

## 6. 機密情報の管理

### 6.1 保存される情報

| 情報 | 保存場所 | 保護方法 |
|------|----------|----------|
| ブラウザセッション | `~/.delete-google-photo/browser-state/` | ディレクトリ権限 0700（起動時に適用） |
| 処理状態 | `./state/` | ファイル権限 600 |

起動時に `~/.delete-google-photo/browser-state/` を作成し `chmod 0700` を
適用する。旧来のプロジェクト配下 `state/browser-state/` にセッションが
残っている場合は初回起動時に自動マイグレーションされる
（`app/main.py::_prepare_browser_state_dir`）。保存先は環境変数
`BROWSER_STATE_DIR` で上書き可能。

### 6.2 .gitignoreの設定

```gitignore
# .gitignore
# ブラウザ状態
.delete-google-photo/

# 処理状態
state/

# 環境変数
.env
.env.local

# セッション
*.session
```

### 6.3 環境変数の使用

```python
# app/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    environment: str = "development"
    debug: bool = False
    browser_state_dir: str = "~/.delete-google-photo/browser-state"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
```

## 7. 誤操作防止

### 7.1 削除前の多重確認

```python
# app/services/photo_service.py
class PhotoService:
    async def delete_photos(
        self,
        photos: list[Photo],
        *,
        dry_run: bool = True,  # デフォルトはドライラン
        confirmed: bool = False,
    ) -> DeletionResult:
        if not dry_run and not confirmed:
            raise ValueError("削除実行には明示的な確認が必要です")

        if dry_run:
            return DeletionResult(
                mode="dry_run",
                target_count=len(photos),
                deleted_count=0,
            )

        # 実際の削除処理
        ...
```

### 7.2 確認ダイアログ

```javascript
// static/js/main.js
async function executeDelete() {
    const count = document.getElementById('target-count').textContent;

    const confirmed = confirm(
        `${count} 枚の写真をゴミ箱に移動します。よろしいですか？\n` +
        `（ゴミ箱内の写真はGoogle Photos側で60日後に自動削除されます）`
    );

    if (!confirmed) {
        return;
    }

    // 二重確認
    const doubleConfirmed = confirm(
        `最終確認：削除を実行します。よろしいですか？`
    );

    if (!doubleConfirmed) {
        return;
    }

    // 削除実行
    ...
}
```

## 8. ログとモニタリング

### 8.1 セキュリティログ

```python
import logging

security_logger = logging.getLogger("security")

def log_security_event(event_type: str, details: dict) -> None:
    security_logger.info(
        f"SECURITY_EVENT: {event_type}",
        extra={"details": details}
    )

# 使用例
log_security_event("DELETE_EXECUTED", {
    "photo_count": 100,
    "date_range": "2020-01-01 to 2020-12-31",
    "timestamp": datetime.now().isoformat(),
})
```

### 8.2 ログに含めない情報
- Googleセッション情報
- アクセストークン
- Cookie値

## 9. セキュリティチェックリスト

### 9.1 開発時
- [ ] 依存パッケージの脆弱性チェック（`pip-audit`）
- [ ] 静的解析（`bandit`）
- [ ] 型チェック（`mypy`）

```bash
# 脆弱性チェック
pip install pip-audit
pip-audit

# セキュリティ静的解析
pip install bandit
bandit -r app/
```

### 9.2 リリース前
- [ ] すべての入力に検証が行われている
- [x] ~~CSRFトークンが実装されている~~ → スコープ外（5章参照）
- [ ] XSS対策（エスケープ）が有効
- [ ] セッション情報が安全に保存されている
- [ ] localhostのみでリッスンしている
- [ ] .gitignoreが適切に設定されている
- [ ] エラーメッセージに機密情報が含まれていない

### 9.3 運用時
- [ ] 定期的な依存パッケージ更新
- [ ] セキュリティパッチの適用
- [ ] ブラウザ（Chromium）の更新

## 10. インシデント対応

### 10.1 セッション漏洩時
1. 即座にGoogleアカウントのセキュリティ設定を確認
2. 不審なアクティビティがないか確認
3. 必要に応じてパスワード変更
4. ローカルのセッションデータを削除

```bash
# セッションデータの削除
rm -rf ~/.delete-google-photo/browser-state/
```

### 10.2 誤削除時
- 本ツールの操作は「ゴミ箱に移動」までなので、Google Photosの「ゴミ箱」画面から60日以内であれば復元可能
- 完全削除後は復元不可。事前にiCloudにバックアップがあることを確認済み（本プロジェクトの前提条件）
