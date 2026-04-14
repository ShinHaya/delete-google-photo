"""Tests for account service."""

from pathlib import Path

import pytest

from app.models.account import Account
from app.services.account_service import AccountService


@pytest.fixture
def svc(temp_dir: Path) -> AccountService:
    """Create an AccountService backed by temp directories."""
    state_dir = temp_dir / "state"
    browser_state_dir = temp_dir / "browser-state"
    state_dir.mkdir(parents=True)
    browser_state_dir.mkdir(parents=True)
    return AccountService(state_dir=state_dir, browser_state_dir=browser_state_dir)


class TestAccountService:
    def test_create_account(self, svc: AccountService) -> None:
        account = svc.create_account()
        assert account.account_id
        assert account.email is None

        # Profile directory created
        profile = svc.get_profile_dir(account.account_id)
        assert profile.exists()

        # Is the active account (first one)
        assert svc.get_active_account_id() == account.account_id

    def test_list_accounts(self, svc: AccountService) -> None:
        assert svc.list_accounts() == []

        a1 = svc.create_account()
        a2 = svc.create_account()
        accounts = svc.list_accounts()

        assert len(accounts) == 2
        ids = {a.account_id for a in accounts}
        assert a1.account_id in ids
        assert a2.account_id in ids

    def test_set_active_account(self, svc: AccountService) -> None:
        a1 = svc.create_account()
        a2 = svc.create_account()

        assert svc.get_active_account_id() == a1.account_id

        svc.set_active_account(a2.account_id)
        assert svc.get_active_account_id() == a2.account_id

    def test_set_active_account_not_found(self, svc: AccountService) -> None:
        with pytest.raises(ValueError, match="Account not found"):
            svc.set_active_account("nonexistent")

    def test_delete_account(self, svc: AccountService) -> None:
        a1 = svc.create_account()
        a2 = svc.create_account()

        profile_dir = svc.get_profile_dir(a1.account_id)
        assert profile_dir.exists()

        svc.delete_account(a1.account_id)

        assert len(svc.list_accounts()) == 1
        assert not profile_dir.parent.exists()
        # Active switches to remaining account
        assert svc.get_active_account_id() == a2.account_id

    def test_delete_only_account(self, svc: AccountService) -> None:
        a1 = svc.create_account()
        svc.delete_account(a1.account_id)

        assert svc.list_accounts() == []
        assert svc.get_active_account_id() is None

    def test_delete_account_not_found(self, svc: AccountService) -> None:
        with pytest.raises(ValueError, match="Account not found"):
            svc.delete_account("nonexistent")

    def test_update_account(self, svc: AccountService) -> None:
        account = svc.create_account()
        updated = svc.update_account(
            account.account_id, email="test@gmail.com", display_name="Test"
        )

        assert updated.email == "test@gmail.com"
        assert updated.display_name == "Test"

        # Persisted
        loaded = svc.list_accounts()[0]
        assert loaded.email == "test@gmail.com"

    def test_update_account_not_found(self, svc: AccountService) -> None:
        with pytest.raises(ValueError, match="Account not found"):
            svc.update_account("nonexistent", email="test@gmail.com")

    def test_migrate_legacy_profile(self, temp_dir: Path) -> None:
        """Test that an existing chrome-profile is migrated to the new structure."""
        state_dir = temp_dir / "state"
        browser_state_dir = temp_dir / "browser-state"
        state_dir.mkdir(parents=True)
        browser_state_dir.mkdir(parents=True)

        # Create legacy profile
        legacy_profile = browser_state_dir / "chrome-profile"
        legacy_profile.mkdir(parents=True)
        (legacy_profile / "Default" / "Cookies").parent.mkdir(parents=True)
        (legacy_profile / "Default" / "Cookies").write_text("test")

        # Create service — migration happens on first load
        svc = AccountService(state_dir=state_dir, browser_state_dir=browser_state_dir)
        accounts = svc.list_accounts()

        assert len(accounts) == 1
        assert svc.get_active_account_id() == accounts[0].account_id

        # Legacy profile moved
        assert not legacy_profile.exists()

        # New profile has the migrated data
        new_profile = svc.get_profile_dir(accounts[0].account_id)
        assert (new_profile / "Default" / "Cookies").exists()
        assert (new_profile / "Default" / "Cookies").read_text() == "test"

    def test_no_migration_without_legacy(self, svc: AccountService) -> None:
        """No migration if there's no legacy profile."""
        accounts = svc.list_accounts()
        assert accounts == []

    def test_persistence(self, temp_dir: Path) -> None:
        """Registry survives service recreation."""
        state_dir = temp_dir / "state"
        browser_state_dir = temp_dir / "browser-state"
        state_dir.mkdir(parents=True)
        browser_state_dir.mkdir(parents=True)

        svc1 = AccountService(state_dir=state_dir, browser_state_dir=browser_state_dir)
        account = svc1.create_account()
        svc1.update_account(account.account_id, email="persist@test.com")

        # New service instance should load the same data
        svc2 = AccountService(state_dir=state_dir, browser_state_dir=browser_state_dir)
        accounts = svc2.list_accounts()
        assert len(accounts) == 1
        assert accounts[0].email == "persist@test.com"


class TestAccountModel:
    def test_label_with_email(self) -> None:
        account = Account(email="test@gmail.com")
        assert account.label == "test@gmail.com"

    def test_label_with_display_name(self) -> None:
        account = Account(display_name="Test User")
        assert account.label == "Test User"

    def test_label_fallback(self) -> None:
        account = Account()
        assert account.label.startswith("アカウント (")
