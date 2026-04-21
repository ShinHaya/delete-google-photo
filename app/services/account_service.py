"""Account management service for multiple Google accounts."""

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path

from app.config import settings
from app.models.account import Account, AccountRegistry

logger = logging.getLogger(__name__)


class AccountService:
    """Manages multiple Google account profiles."""

    def __init__(
        self,
        state_dir: Path | None = None,
        browser_state_dir: Path | None = None,
    ) -> None:
        self.state_dir = state_dir or settings.state_dir
        self.browser_state_dir = browser_state_dir or settings.browser_state_dir
        self._registry_file = self.state_dir / "accounts.json"
        self._registry: AccountRegistry | None = None

    def _load_registry(self) -> AccountRegistry:
        """Load the account registry from disk."""
        if self._registry is not None:
            return self._registry

        if self._registry_file.exists():
            with self._registry_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
            self._registry = AccountRegistry(**data)
        else:
            self._registry = AccountRegistry()
            # Migrate legacy single-profile if it exists
            self._migrate_legacy_profile()

        return self._registry

    def _save_registry(self) -> None:
        """Save the account registry to disk."""
        if self._registry is None:
            return
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with self._registry_file.open("w", encoding="utf-8") as f:
            json.dump(self._registry.model_dump(mode="json"), f, indent=2, default=str)
        self._registry_file.chmod(0o600)

    def _migrate_legacy_profile(self) -> None:
        """Migrate the legacy single chrome-profile to the new multi-account structure."""
        legacy_profile = self.browser_state_dir / "chrome-profile"
        if not legacy_profile.exists():
            return

        assert self._registry is not None
        account = Account()
        new_profile_dir = self.get_profile_dir(account.account_id)
        new_profile_dir.parent.mkdir(parents=True, exist_ok=True)

        shutil.move(str(legacy_profile), str(new_profile_dir))
        logger.info(
            "Migrated legacy profile to account %s at %s",
            account.account_id,
            new_profile_dir,
        )

        self._registry.accounts.append(account)
        self._registry.active_account_id = account.account_id
        self._save_registry()

    def get_profile_dir(self, account_id: str) -> Path:
        """Get the browser profile directory for an account."""
        return self.browser_state_dir / f"account-{account_id}" / "chrome-profile"

    def list_accounts(self) -> list[Account]:
        """List all registered accounts."""
        registry = self._load_registry()
        return list(registry.accounts)

    @staticmethod
    def is_placeholder_account(account: Account) -> bool:
        """Whether the account is still an unlabeled placeholder."""
        return not account.email and not account.display_name

    def list_visible_accounts(self) -> list[Account]:
        """List accounts that should be shown in the UI.

        Placeholder accounts can be created transiently before login
        succeeds. They should not be shown in the account dropdown once
        at least one labeled account exists.
        """
        accounts = self.list_accounts()
        visible = [a for a in accounts if not self.is_placeholder_account(a)]
        return visible if visible else accounts

    def get_active_account(self) -> Account | None:
        """Get the currently active account."""
        registry = self._load_registry()
        return registry.get_active_account()

    def get_active_account_id(self) -> str | None:
        """Get the currently active account ID."""
        registry = self._load_registry()
        return registry.active_account_id

    def ensure_visible_active_account(self) -> str | None:
        """Prefer a labeled account as active when available.

        Returns the effective active account id after normalization.
        """
        registry = self._load_registry()
        active = registry.get_active_account()
        if active is not None and not self.is_placeholder_account(active):
            return active.account_id

        visible = [a for a in registry.accounts if not self.is_placeholder_account(a)]
        if not visible:
            return registry.active_account_id

        registry.active_account_id = visible[0].account_id
        self._save_registry()
        logger.info(
            "Normalized active account to visible account %s",
            registry.active_account_id,
        )
        return registry.active_account_id

    def set_active_account(self, account_id: str) -> Account:
        """Set the active account.

        Raises:
            ValueError: If account_id is not found.
        """
        registry = self._load_registry()
        account = registry.get_account(account_id)
        if account is None:
            raise ValueError(f"Account not found: {account_id}")

        registry.active_account_id = account_id
        account.last_used_at = datetime.now()
        self._save_registry()
        logger.info("Active account set to %s (%s)", account.label, account_id)
        return account

    def create_account(self) -> Account:
        """Create a new account entry and its profile directory."""
        registry = self._load_registry()
        account = Account()

        profile_dir = self.get_profile_dir(account.account_id)
        profile_dir.mkdir(parents=True, exist_ok=True)

        registry.accounts.append(account)
        # If this is the first account, make it active
        if registry.active_account_id is None:
            registry.active_account_id = account.account_id

        self._save_registry()
        logger.info("Created account %s", account.account_id)
        return account

    def delete_account(self, account_id: str) -> bool:
        """Delete an account and its profile directory.

        Raises:
            ValueError: If account_id is not found.
        """
        registry = self._load_registry()
        account = registry.get_account(account_id)
        if account is None:
            raise ValueError(f"Account not found: {account_id}")

        # Remove profile directory
        profile_dir = self.get_profile_dir(account_id)
        account_dir = profile_dir.parent
        if account_dir.exists():
            shutil.rmtree(account_dir)
            logger.info("Removed profile directory: %s", account_dir)

        # Remove from registry
        registry.accounts = [a for a in registry.accounts if a.account_id != account_id]

        # Update active account if needed
        if registry.active_account_id == account_id:
            if registry.accounts:
                registry.active_account_id = registry.accounts[0].account_id
            else:
                registry.active_account_id = None

        self._save_registry()
        logger.info("Deleted account %s", account_id)
        return True

    def update_account(
        self,
        account_id: str,
        *,
        email: str | None = None,
        display_name: str | None = None,
    ) -> Account:
        """Update account metadata (email, display name).

        Raises:
            ValueError: If account_id is not found.
        """
        registry = self._load_registry()
        account = registry.get_account(account_id)
        if account is None:
            raise ValueError(f"Account not found: {account_id}")

        if email is not None:
            account.email = email
        if display_name is not None:
            account.display_name = display_name

        self._save_registry()
        return account
