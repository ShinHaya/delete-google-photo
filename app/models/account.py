"""Account model for managing multiple Google accounts."""

from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, Field


class Account(BaseModel):
    """A Google account with its own browser profile."""

    account_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique account identifier",
    )
    email: str | None = Field(None, description="Google account email address")
    display_name: str | None = Field(None, description="Display name for the account")
    created_at: datetime = Field(
        default_factory=datetime.now,
        description="Account creation timestamp",
    )
    last_used_at: datetime | None = Field(
        None, description="Last time this account was used"
    )

    @property
    def label(self) -> str:
        """Human-readable label for the account."""
        if self.email:
            return self.email
        if self.display_name:
            return self.display_name
        return f"アカウント ({self.account_id[:8]})"


class AccountRegistry(BaseModel):
    """Registry of all managed Google accounts."""

    accounts: list[Account] = Field(default_factory=list)
    active_account_id: str | None = Field(
        None, description="Currently active account ID"
    )

    def get_account(self, account_id: str) -> Account | None:
        """Get an account by ID."""
        for account in self.accounts:
            if account.account_id == account_id:
                return account
        return None

    def get_active_account(self) -> Account | None:
        """Get the currently active account."""
        if self.active_account_id is None:
            return None
        return self.get_account(self.active_account_id)
