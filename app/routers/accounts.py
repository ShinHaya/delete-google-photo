"""Account management API router."""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.browser.manager import BrowserManager
from app.services.account_service import AccountService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


def _raise_if_session_active() -> None:
    """Reject account ops that would disrupt a running deletion.

    Imported lazily to avoid a circular import between ``accounts`` and
    ``photos``.
    """
    from app.routers.photos import is_session_active

    if is_session_active():
        raise HTTPException(
            status_code=409,
            detail="削除セッションを実行中のため、アカウントは切り替えできません。中断するか、完了までお待ちください。",
        )


# Module-level singletons, initialized by init_account_dependencies()
_account_service: AccountService | None = None
_browser_manager: BrowserManager | None = None


def init_account_dependencies(
    account_service: AccountService,
    browser_manager: BrowserManager,
) -> None:
    """Initialize module-level dependencies. Called from app lifespan."""
    global _account_service, _browser_manager  # noqa: PLW0603
    _account_service = account_service
    _browser_manager = browser_manager


def get_account_service() -> AccountService:
    if _account_service is None:
        raise RuntimeError("AccountService not initialized")
    return _account_service


def get_browser_manager() -> BrowserManager:
    if _browser_manager is None:
        raise RuntimeError("BrowserManager not initialized")
    return _browser_manager


# --- Response models ---


class AccountResponse(BaseModel):
    account_id: str
    email: str | None
    display_name: str | None
    label: str
    is_active: bool


class AccountListResponse(BaseModel):
    accounts: list[AccountResponse]
    active_account_id: str | None


# --- Endpoints ---


@router.get("", response_model=AccountListResponse)
async def list_accounts() -> AccountListResponse:
    """List all registered accounts."""
    svc = get_account_service()
    active_id = svc.ensure_visible_active_account()
    accounts = svc.list_visible_accounts()

    return AccountListResponse(
        accounts=[
            AccountResponse(
                account_id=a.account_id,
                email=a.email,
                display_name=a.display_name,
                label=a.label,
                is_active=(a.account_id == active_id),
            )
            for a in accounts
        ],
        active_account_id=active_id,
    )


@router.post("", response_model=AccountResponse)
async def create_account() -> AccountResponse:
    """Create a new account entry (does not start login)."""
    _raise_if_session_active()
    svc = get_account_service()
    account = svc.create_account()
    active_id = svc.get_active_account_id()

    return AccountResponse(
        account_id=account.account_id,
        email=account.email,
        display_name=account.display_name,
        label=account.label,
        is_active=(account.account_id == active_id),
    )


@router.post("/{account_id}/activate", response_model=AccountResponse)
async def activate_account(account_id: str) -> AccountResponse:
    """Switch the active account."""
    _raise_if_session_active()
    svc = get_account_service()
    mgr = get_browser_manager()

    try:
        account = svc.set_active_account(account_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    # Stop current browser so the next operation uses the new profile
    await mgr.stop_current()

    return AccountResponse(
        account_id=account.account_id,
        email=account.email,
        display_name=account.display_name,
        label=account.label,
        is_active=True,
    )


@router.delete("/{account_id}")
async def delete_account(account_id: str) -> dict[str, bool]:
    """Delete an account and its browser profile."""
    _raise_if_session_active()
    svc = get_account_service()
    mgr = get_browser_manager()

    # If deleting the currently active browser, stop it first
    if mgr.current_account_id == account_id:
        await mgr.stop_current()

    try:
        svc.delete_account(account_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    return {"deleted": True}


@router.post("/{account_id}/login")
async def login_account(account_id: str) -> dict[str, bool | str]:
    """Start login flow for a specific account."""
    from app.browser.auth import GoogleAuthenticator

    _raise_if_session_active()
    svc = get_account_service()
    mgr = get_browser_manager()

    account = svc.get_active_account() if account_id == "active" else None
    if account is None:
        accounts = svc.list_accounts()
        account = next((a for a in accounts if a.account_id == account_id), None)
    if account is None:
        raise HTTPException(status_code=404, detail=f"Account not found: {account_id}")

    # Activate this account so the browser uses the right profile
    svc.set_active_account(account.account_id)
    await mgr.stop_current()

    try:
        client = await mgr.get_client(account.account_id)
        authenticator = GoogleAuthenticator(client)
        success = await authenticator.wait_for_manual_login(timeout=300)

        if success:
            # Try to extract email
            email = await authenticator.extract_account_email()
            if email:
                # De-duplicate: if another account already uses this email,
                # keep the freshly-logged-in slot (it has a valid session)
                # and delete the older duplicate(s). This covers both
                # "added a new slot and logged into an existing email" and
                # "logged into slot A with email that slot B already had".
                duplicates = [
                    a
                    for a in svc.list_accounts()
                    if a.email == email and a.account_id != account.account_id
                ]
                if duplicates:
                    # Release any browser using the duplicate before deleting
                    for dup in duplicates:
                        if mgr.current_account_id == dup.account_id:
                            await mgr.stop_current()
                        svc.delete_account(dup.account_id)
                    logger.info(
                        "Merged %d duplicate account(s) for %s",
                        len(duplicates),
                        email,
                    )
                svc.update_account(account.account_id, email=email)
                svc.set_active_account(account.account_id)
            return {"success": True, "message": "ログインに成功しました"}

        return {"success": False, "message": "ログインがタイムアウトしました"}
    except Exception as e:
        return {"success": False, "message": f"ログインエラー: {e!s}"}


@router.post("/{account_id}/logout")
async def logout_account(account_id: str) -> dict[str, bool]:
    """Logout from a specific account (clears its browser session)."""
    _raise_if_session_active()
    svc = get_account_service()
    mgr = get_browser_manager()

    accounts = svc.list_accounts()
    account = next((a for a in accounts if a.account_id == account_id), None)
    if account is None:
        raise HTTPException(status_code=404, detail=f"Account not found: {account_id}")

    # Stop browser if this is the active one
    if mgr.current_account_id == account_id:
        await mgr.stop_current()

    # Clear the profile
    from app.browser.client import BrowserClient

    profile_dir = svc.get_profile_dir(account_id)
    temp_client = BrowserClient(user_data_dir=profile_dir)
    await temp_client.clear_state()

    # Clear email since session is gone
    svc.update_account(account_id, email=None)

    return {"success": True}


@router.get("/{account_id}/auth/status")
async def get_account_auth_status(account_id: str) -> dict[str, bool]:
    """Check authentication status for a specific account."""
    svc = get_account_service()
    mgr = get_browser_manager()

    accounts = svc.list_accounts()
    account = next((a for a in accounts if a.account_id == account_id), None)
    if account is None:
        raise HTTPException(status_code=404, detail=f"Account not found: {account_id}")

    try:
        client = await mgr.get_client(account_id)
        is_logged_in = await client.is_logged_in()
        return {"authenticated": is_logged_in}
    except Exception as e:
        logger.warning("Auth status check failed for %s: %s", account_id, e)
        return {"authenticated": False}
