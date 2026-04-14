"""Application configuration."""

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    app_name: str = "Delete Google Photo"
    debug: bool = False
    environment: str = "development"

    # Server
    host: str = "127.0.0.1"
    port: int = 8000

    # Paths
    # state_dir holds non-sensitive app state (interrupted session JSON, etc.)
    # and is kept inside the project for easy inspection. It is already
    # .gitignore'd.
    state_dir: Path = Path("state")
    # browser_state_dir holds persistent Chrome profiles (cookies, tokens).
    # Default to a dedicated directory OUTSIDE the worktree so Google session
    # material cannot be accidentally committed. Override with env var
    # BROWSER_STATE_DIR if needed.
    browser_state_dir: Path = Path.home() / ".delete-google-photo" / "browser-state"

    # Browser
    headless: bool = False  # ローカル実行ではヘッドフルモード
    slow_mo: int = 0  # milliseconds

    # Retry
    max_retry_count: int = 3
    initial_retry_delay: float = 1.0  # seconds
    max_retry_delay: float = 10.0  # seconds

    # Rate limiting
    delete_interval: float = 0.5  # seconds between deletes

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
