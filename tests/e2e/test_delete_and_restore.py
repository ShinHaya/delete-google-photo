"""End-to-end test: delete photos for a date range, then restore them.

This test talks to the **real** Google Photos. It uses a single-day
range (2026-04-01) containing a small, throwaway set of photos so the
test is cheap to run and the blast radius of a bug is bounded.

Why this test exists (despite docs/testing.md section 5 previously
declaring E2E out of scope):

- Google Photos' DOM drifts over time. The bulk-delete / bulk-restore
  flows are fragile against aria-label or class-name changes.
- The Google Photos Library API does NOT expose a restore endpoint (or
  even a delete endpoint), and since 2025-03-31 it only reads photos
  created by the calling app — so API-based teardown is impossible.
- The workaround is: drive the delete flow end-to-end with Playwright,
  and in teardown drive the /trash restore flow with Playwright as
  well, matching trashed tiles back to pre-delete photos via their
  aria-label datetime strings (the /trash page has no photo-id
  anchors, so datetime is the only join key).

The test is guarded by the ``e2e`` pytest marker so the default test
run does not hit Google Photos. Run explicitly with:

    uv run pytest tests/e2e/test_delete_and_restore.py -v -m e2e
"""

from datetime import date

import pytest

from app.browser.client import BrowserClient
from app.browser.operations import PhotoOperations

# Single-day range with a handful of throwaway photos the user has
# confirmed are safe to delete and re-create.
TARGET_DATE = date(2026, 4, 1)


@pytest.mark.e2e
async def test_delete_and_restore_single_day() -> None:
    """Delete all photos on TARGET_DATE then restore them from /trash.

    Steps:
    1. Scan TARGET_DATE, record aria-labels of every photo present.
    2. Assert at least 1 photo exists (otherwise the test is a no-op).
    3. Run ``delete_photos_in_range_streaming`` for the single-day range.
    4. Assert the post-delete count is 0.
    5. In a try/finally teardown, always call
       ``restore_photos_from_trash_by_labels`` with the captured labels.
    6. Assert the post-restore count equals the original count.

    The test uses ``headless=False`` because Google's sign-in requires
    an interactive login that has already been completed in the
    persistent browser profile at ``state/browser-state/chrome-profile``.
    """
    client = BrowserClient(headless=False)
    await client.start()
    try:
        ops = PhotoOperations(client)

        # --- Capture ---
        labels_before = await ops.get_photo_labels_in_range(TARGET_DATE, TARGET_DATE)
        pre_count = len(labels_before)
        assert pre_count > 0, (
            f"No photos on {TARGET_DATE} — cannot run E2E. "
            "Upload a couple of throwaway photos to this date first."
        )
        labels_set = set(labels_before)
        # Labels must be unique for the restore match to be reliable.
        # If the user has photos with colliding timestamps on this date
        # the test can still work, but restore counts become ambiguous.
        assert len(labels_set) == pre_count, (
            f"Duplicate aria-labels on {TARGET_DATE} — pick a different "
            "test date so each photo has a unique timestamp."
        )

        deleted = 0
        try:
            # --- Delete ---
            deleted, failed = await ops.delete_photos_in_range_streaming(
                TARGET_DATE,
                TARGET_DATE,
                expected_total=pre_count,
            )
            assert failed == [], f"Delete reported failures: {failed}"
            assert deleted == pre_count, (
                f"Delete count mismatch: deleted={deleted} expected={pre_count}"
            )

            post_delete_count = await ops.count_photos_in_range(
                TARGET_DATE, TARGET_DATE
            )
            assert post_delete_count == 0, (
                f"Photos still visible on {TARGET_DATE} after delete: "
                f"{post_delete_count}"
            )
        finally:
            # --- Restore (always, even if delete asserts failed) ---
            # We always attempt restore — even on a delete-phase failure
            # there may be partial trash state to recover.
            _ = deleted  # silence "unused variable" when delete raised
            restored, unrestored = await ops.restore_photos_from_trash_by_labels(
                labels_set
            )
            if unrestored:
                pytest.fail(
                    f"Restore incomplete: {len(unrestored)} label(s) "
                    f"could not be restored from /trash: {unrestored}"
                )
            assert restored == pre_count, (
                f"Restore count mismatch: restored={restored} expected={pre_count}"
            )

        # --- Verify restore by re-scanning the date range ---
        post_restore_count = await ops.count_photos_in_range(TARGET_DATE, TARGET_DATE)
        assert post_restore_count == pre_count, (
            f"Post-restore count {post_restore_count} != pre-count {pre_count}"
        )
    finally:
        await client.stop()
