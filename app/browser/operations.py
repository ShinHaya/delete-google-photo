"""Browser operations for Google Photos photo management."""

import asyncio
import contextlib
import logging
import re
from collections.abc import AsyncGenerator, Callable, Coroutine
from datetime import date, datetime, time, timedelta
from typing import Any

from playwright._impl._errors import TimeoutError as PlaywrightTimeoutError

from app.browser.client import BrowserClient
from app.browser.date_parser import parse_date_from_aria_label
from app.config import settings
from app.exceptions import PhotoDeletionError, PhotoNotFoundError, RateLimitError
from app.models.photo import Photo, PhotoSummary
from app.utils.retry import with_retry

# Type alias for progress callback
ProgressCallback = Callable[[int, int, str], Coroutine[Any, Any, None]]

logger = logging.getLogger(__name__)


def _month_diff(a: tuple[int, int], b: tuple[int, int]) -> int:
    """Return ``a - b`` in months. Positive means ``a`` is newer than ``b``.

    Each tuple is ``(year, month)`` with month in 1-12.
    """
    return (a[0] - b[0]) * 12 + (a[1] - b[1])


class PhotoOperations:
    """Handles photo search and deletion operations in Google Photos."""

    def __init__(self, browser_client: BrowserClient) -> None:
        """Initialize photo operations.

        Args:
            browser_client: Browser client instance
        """
        self.client = browser_client

    async def navigate_to_date_range(self, start_date: date, end_date: date) -> None:
        """Navigate to the Google Photos main timeline.

        Note: Google Photos has no public URL format for date-range filtering.
        The ``/search/<query>`` endpoint is a full-text search and treats
        strings like ``2020-01-01_2020-12-31`` as literal text (matching
        filenames / OCR text only). The correct approach is to traverse the
        main timeline and filter client-side using dates parsed from each
        photo's ``aria-label``. See ``_collect_photo_records_in_range``.

        Args:
            start_date: Start date of range (used only for logging)
            end_date: End date of range (used only for logging)
        """
        logger.info(
            "Navigating to main timeline for date range %s to %s",
            start_date,
            end_date,
        )
        # `navigate_to_photos` calls `page.goto`, which already waits for
        # the `load` event. We deliberately do NOT wait for `networkidle`
        # here: Google Photos has continuous background traffic (polling,
        # telemetry) so the `networkidle` event may never fire, causing a
        # 30s timeout. Initial render settling is handled by the
        # `asyncio.sleep(2)` below.
        await self.client.navigate_to_photos()
        await asyncio.sleep(2)

        # Fast-jump via the right-side date slider. Google Photos shows
        # photos newest-first, so without a jump we would wheel-scroll from
        # the top for *years* to reach an old ``start_date`` — unusable in
        # practice. The slider lets us land near ``end_date`` in one drag.
        # This is best-effort: on any failure we silently fall back to the
        # old top-down scroll, which is slow but still correct.
        jumped = False
        with contextlib.suppress(Exception):
            jumped = await self._jump_to_month_via_slider(end_date)
        if not jumped:
            # A failed slider correction loop leaves the viewport wherever
            # the last bad drag dropped it — which may be well below
            # end_date. Re-navigate to the top so the caller's downward
            # scan starts from the newest photo and can reach end_date
            # via plain wheel scroll.
            logger.info(
                "Slider jump did not succeed; resetting to top for "
                "plain-scroll fallback"
            )
            await self.client.navigate_to_photos()
            await asyncio.sleep(2)

    async def _jump_to_month_via_slider(self, target: date) -> bool:
        """Drag the right-side date slider to jump near ``target``'s month.

        Google Photos renders a vertical slider on the right edge of the
        timeline (``div[role="slider"][aria-orientation="vertical"]``) whose
        thumb shows the currently-centered year-month (``aria-valuetext``
        e.g. ``"2024年10月"``). Inside the slider track are year labels
        (``div.HrGXnb``) positioned at pixel offsets that correlate with
        the photo-count density for that year. We drag the thumb to a Y
        coordinate interpolated between bracketing year labels, then read
        ``aria-valuetext`` and do up to a few correction drags to land
        within 1 month of the target.

        This is *best-effort*. On any failure (slider not visible, DOM
        shape changed, correction loop didn't converge) we return ``False``
        and the caller silently falls back to the top-down wheel-scroll
        path. That path is slow for old dates but still correct, so this
        helper never raises into the main flow.

        Args:
            target: The date to jump near. We aim at ``(target.year,
                target.month)``; day-of-month is ignored. We intentionally
                land slightly *newer* than the target month so that the
                subsequent top-down scroll naturally sweeps through
                ``target`` without missing the boundary day.

        Returns:
            ``True`` if the slider was operated and the final
            ``aria-valuetext`` is within 1 month of ``target``.
            ``False`` otherwise (including all skip / fallback cases).
        """
        page = self.client.page

        # Short-circuit: within the last ~60 days, the top of the timeline
        # is effectively the target. Dragging the slider adds no value and
        # risks overshooting backwards.
        today = date.today()
        if target >= today - timedelta(days=60):
            logger.info("Slider jump skipped: target %s within recent 60 days", target)
            return False

        # Reveal the slider. Google Photos only shows the slider thumb
        # while the cursor is near the right edge of the viewport.
        viewport = page.viewport_size
        if viewport is None:
            logger.warning("Slider jump skipped: viewport size unknown")
            return False
        await page.mouse.move(
            viewport["width"] - 10,
            viewport["height"] / 2,
        )

        slider_locator = page.locator('div[role="slider"][aria-orientation="vertical"]')
        try:
            await slider_locator.first.wait_for(state="attached", timeout=3000)
        except Exception as e:
            logger.warning("Slider jump skipped: slider not found (%s)", e)
            return False

        # Snapshot the slider geometry and year ticks in one round-trip.
        try:
            snapshot: dict[str, Any] = await page.evaluate(
                """
                () => {
                    const slider = document.querySelector(
                        'div[role="slider"][aria-orientation="vertical"]'
                    );
                    if (!slider) return null;
                    const bb = slider.getBoundingClientRect();
                    const ticks = [];
                    // Use the HrGXnb (year label) element directly rather
                    // than its .JRRmBc wrapper. Some wrappers collapse into
                    // a zero-rect stacked state which breaks interpolation.
                    for (const el of slider.querySelectorAll('div.HrGXnb')) {
                        const year = parseInt((el.textContent || '').trim(), 10);
                        if (!Number.isFinite(year)) continue;
                        const pbb = el.getBoundingClientRect();
                        // Skip ticks clearly outside the slider box (e.g.,
                        // collapsed / hidden year dividers that return
                        // pageY ~= 0).
                        const pageY = pbb.top + pbb.height / 2;
                        if (pageY < bb.top - 2 || pageY > bb.bottom + 2) {
                            continue;
                        }
                        ticks.push({ year: year, pageY: pageY });
                    }
                    // Thumb label position, if present
                    let thumbY = null;
                    const thumb = slider.querySelector('.lVKXif');
                    if (thumb) {
                        const tbb = thumb.getBoundingClientRect();
                        thumbY = tbb.top + tbb.height / 2;
                    }
                    return {
                        sliderTop: bb.top,
                        sliderBottom: bb.bottom,
                        sliderCenterX: bb.left + bb.width / 2,
                        ariaValueNow: parseFloat(
                            slider.getAttribute('aria-valuenow') || '0'
                        ),
                        ariaValueText: slider.getAttribute('aria-valuetext') || '',
                        thumbY: thumbY,
                        ticks: ticks,
                    };
                }
                """
            )
        except Exception as e:
            logger.warning("Slider jump skipped: snapshot failed (%s)", e)
            return False

        if not snapshot:
            logger.warning("Slider jump skipped: snapshot returned null")
            return False

        ticks: list[dict[str, float]] = snapshot.get("ticks", []) or []
        if not ticks:
            logger.warning("Slider jump skipped: no year ticks in slider")
            return False

        slider_top: float = float(snapshot["sliderTop"])
        slider_bottom: float = float(snapshot["sliderBottom"])
        slider_x: float = float(snapshot["sliderCenterX"])
        initial_valuetext: str = snapshot.get("ariaValueText") or ""

        # Accept criterion: the slider thumb label must represent a month
        # that is **at or newer than** the target (so the subsequent
        # top-down wheel-scroll sweeps through the target in a handful of
        # iterations). Landing even 1 month older is fatal because wheel
        # scroll only goes newest→oldest, so the target month's photos
        # would be above the viewport and permanently unreachable.
        # We allow up to 6 months newer — that's cheap for wheel scroll
        # to sweep through.
        def _is_close_enough(ym_: tuple[int, int]) -> bool:
            d = _month_diff(ym_, (target.year, target.month))
            return 0 <= d <= 6

        # Early exit: already near the target month.
        current_ym = self._parse_ym_from_valuetext(initial_valuetext)
        if current_ym is not None and _is_close_enough(current_ym):
            logger.info(
                "Slider jump skipped: already near target (%s, target=%s)",
                initial_valuetext,
                target,
            )
            return True

        # Sort ticks newest-first (large year = smaller pageY expected).
        ticks_sorted = sorted(ticks, key=lambda t: -int(t["year"]))
        logger.info(
            "Slider snapshot: top=%.1f bottom=%.1f x=%.1f valuetext=%r ticks=%s",
            slider_top,
            slider_bottom,
            slider_x,
            initial_valuetext,
            [(int(t["year"]), round(float(t["pageY"]), 1)) for t in ticks_sorted],
        )

        # --- Initial target Y via linear interpolation between ticks. ---
        # Aim one month *newer* than the exact target so the subsequent
        # wheel-scroll (which goes newest→oldest) still sweeps through the
        # real boundary day without clipping.
        target_months = target.year * 12 + target.month + 1  # bias +1 month newer
        initial_target_y = self._estimate_y_for_month(
            ticks_sorted, target_months, slider_top, slider_bottom
        )
        logger.info(
            "Slider initial drag: target=%s target_y=%.1f from_thumb_y=%.1f",
            target,
            initial_target_y,
            float(snapshot.get("thumbY") or 0.0),
        )

        # --- Drag from current thumb position to target Y ---
        thumb_y = snapshot.get("thumbY")
        if thumb_y is None:
            # Fallback: compute thumb Y from aria-valuenow.
            aria_now = float(snapshot.get("ariaValueNow") or 0.0)
            thumb_y = slider_top + aria_now * (slider_bottom - slider_top)
        thumb_y = float(thumb_y)

        try:
            await self._drag_slider(slider_x, thumb_y, initial_target_y)
        except Exception as e:
            logger.warning("Slider jump failed: initial drag error (%s)", e)
            return False

        # --- Correction loop: read aria-valuetext, adjust. ---
        # Track the previous (drag_y, ym) so we can compute an *instantaneous*
        # px-per-month gradient from the last step only. Using a cumulative
        # gradient mixes density-varying regions of the slider and produces
        # bad corrections.
        prev_drag_y: float = thumb_y
        prev_ym: tuple[int, int] | None = current_ym
        last_drag_y = initial_target_y
        max_attempts = 8
        for attempt in range(max_attempts):
            await asyncio.sleep(0.4)
            try:
                valuetext = await slider_locator.first.get_attribute("aria-valuetext")
            except Exception as e:
                logger.warning("Slider jump failed: reading aria-valuetext (%s)", e)
                return False
            ym = self._parse_ym_from_valuetext(valuetext or "")
            if ym is None:
                logger.warning(
                    "Slider jump failed: could not parse aria-valuetext=%r",
                    valuetext,
                )
                return False

            diff = _month_diff(ym, (target.year, target.month))
            logger.info(
                "Slider correction attempt %d: valuetext=%s diff=%+d months "
                "last_drag_y=%.1f",
                attempt,
                valuetext,
                diff,
                last_drag_y,
            )
            if _is_close_enough(ym):
                logger.info(
                    "Slider jump to %d-%02d OK (aria-valuetext=%s, attempts=%d)",
                    target.year,
                    target.month,
                    valuetext,
                    attempt + 1,
                )
                # Give Google Photos time to actually load the tiles at
                # the new slider position. Without this, the caller's
                # DOM extraction can still see stale tiles from the
                # previous position, forcing it to wheel-scroll through
                # content that hasn't updated yet. 1.5 sec is conservative.
                await asyncio.sleep(1.5)
                return True

            # Estimate px_per_month from the last step's gradient.
            # Note: step might be 0 if the slider didn't respond to the
            # drag (e.g., target_y was outside the track bounds) — fall
            # back to a global estimate in that case.
            step_months = (
                _month_diff(prev_ym, ym) if prev_ym is not None else 0
            )  # positive = moved older
            step_px = last_drag_y - prev_drag_y
            if abs(step_months) >= 1 and abs(step_px) >= 3:
                px_per_month = abs(step_px) / abs(step_months)
            else:
                # Fallback: crude estimate from the whole slider span.
                # Assume ~120 months covered across the full track.
                px_per_month = max((slider_bottom - slider_top) / 120.0, 3.0)

            # diff > 0 means current is NEWER than target → need to drag DOWN
            # (increase Y). diff < 0 means current is OLDER → drag UP.
            # Apply damping because slider density varies drastically
            # between year regions (e.g. 50 px/month in a dense year vs
            # 1 px/month in sparse years). Undershooting is cheap
            # (next iter corrects it); overshooting can fly past the
            # target into an entirely different decade.
            damping = 0.6
            correction_px = diff * px_per_month * damping
            new_target_y = max(
                slider_top + 5,
                min(slider_bottom - 5, last_drag_y + correction_px),
            )
            # If the slider didn't budge at all this step, jump further
            # past the last drag point to escape a dead zone.
            if abs(step_px) < 3 and step_months == 0:
                new_target_y = max(
                    slider_top + 5,
                    min(
                        slider_bottom - 5,
                        last_drag_y + (50.0 if diff > 0 else -50.0),
                    ),
                )
            if abs(new_target_y - last_drag_y) < 3:
                logger.warning(
                    "Slider correction step too small (%.1fpx); giving up",
                    new_target_y - last_drag_y,
                )
                return False
            try:
                await self._drag_slider(slider_x, last_drag_y, new_target_y)
            except Exception as e:
                logger.warning("Slider correction drag failed (%s)", e)
                return False
            prev_drag_y = last_drag_y
            prev_ym = ym
            last_drag_y = new_target_y

        logger.warning(
            "Slider jump did not converge within %d attempts; falling back",
            max_attempts,
        )
        return False

    async def _drag_slider(self, slider_x: float, from_y: float, to_y: float) -> None:
        """Perform a single vertical click-and-drag on the slider.

        Uses multi-step mouse movement so Google's slider controller picks
        up the drag as a real user gesture rather than a teleport.
        """
        page = self.client.page
        await page.mouse.move(slider_x, from_y)
        await page.mouse.down()
        # Small pause so the mousedown is handled before the move starts.
        await asyncio.sleep(0.1)
        await page.mouse.move(slider_x, to_y, steps=15)
        await asyncio.sleep(0.1)
        await page.mouse.up()

    @staticmethod
    def _parse_ym_from_valuetext(valuetext: str) -> tuple[int, int] | None:
        """Parse ``"YYYY年M月"`` into ``(year, month)``; ``None`` on failure."""
        if not valuetext:
            return None
        m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月", valuetext)
        if not m:
            return None
        return int(m.group(1)), int(m.group(2))

    @staticmethod
    def _estimate_y_for_month(
        ticks_sorted: list[dict[str, float]],
        target_months: int,
        slider_top: float,
        slider_bottom: float,
    ) -> float:
        """Linear-interpolate a Y coordinate for a target year-month.

        ``ticks_sorted`` must be ordered newest-first (descending year).
        Each tick is ``{"year": int, "pageY": float}``. The year label is
        assumed to sit at the start (January) of that year — Google Photos'
        actual anchoring varies but any bias is absorbed by the correction
        loop.

        ``target_months`` = ``year * 12 + month - 1`` (0-indexed months).
        """
        if not ticks_sorted:
            return (slider_top + slider_bottom) / 2

        newest_year = int(ticks_sorted[0]["year"])
        oldest_year = int(ticks_sorted[-1]["year"])
        # target_months is year*12 + month (1-indexed). Year recovery:
        target_year = (target_months - 1) // 12

        # Clamp above newest year → slider top.
        if target_year >= newest_year:
            return slider_top + 5.0
        # Clamp below oldest year → slider bottom.
        if target_year < oldest_year:
            return slider_bottom - 5.0

        # Find bracketing ticks such that upper.year > target_year
        # (strictly newer) and lower.year <= target_year.
        upper: dict[str, float] | None = None
        lower: dict[str, float] | None = None
        for i, tick in enumerate(ticks_sorted):
            year = int(tick["year"])
            if year > target_year:
                upper = tick
                if i + 1 < len(ticks_sorted):
                    lower = ticks_sorted[i + 1]
            else:
                # year <= target_year. This is the lower bracket.
                if lower is None:
                    lower = tick
                break
        if upper is None or lower is None:
            return (slider_top + slider_bottom) / 2

        # Year labels are assumed to sit at January of that year.
        upper_months = int(upper["year"]) * 12 + 1
        lower_months = int(lower["year"]) * 12 + 1
        span = upper_months - lower_months
        if span <= 0:
            return float(upper["pageY"])
        # Fraction: 0 at upper tick, 1 at lower tick.
        frac = (upper_months - target_months) / span
        frac = max(0.0, min(1.0, frac))
        return float(upper["pageY"]) + frac * (
            float(lower["pageY"]) - float(upper["pageY"])
        )

    async def _scroll_timeline(self, scroll_amount: int = 1500) -> None:
        """Scroll the Google Photos timeline downward.

        Google Photos uses a virtualized scrollable container inside the
        page — ``window`` itself has no scrollbar, so ``window.scrollBy``
        has no effect. The reliable way to trigger lazy-load is to dispatch
        a real wheel event via the mouse, which propagates to whichever
        container is actually handling the scroll. We also press ``PageDown``
        as a fallback because some virtualized layouts react to keyboard
        scroll but not synthetic wheel events.

        ``scroll_amount`` is intentionally moderate (~1500 px ≈ a few rows
        of thumbnails). Larger jumps risk skipping past tiles before they
        get a chance to render into the DOM, which causes boundary-day
        photos to be missed.
        """
        page = self.client.page
        viewport = page.viewport_size
        if viewport is not None:
            await page.mouse.move(
                viewport["width"] / 2,
                viewport["height"] / 2,
            )
        await page.mouse.wheel(0, scroll_amount)
        # Keyboard fallback in case wheel events do not propagate to the
        # virtualized scroller (some Google Photos builds only honor
        # keyboard scroll once a tile has focus).
        with contextlib.suppress(Exception):
            await page.keyboard.press("PageDown")

    async def _collect_photo_records_in_range(
        self,
        start_date: date,
        end_date: date,
        *,
        max_scrolls: int = 2000,
        scroll_pause: float = 1.2,
        stability_threshold: int = 5,
        post_boundary_stable_threshold: int = 5,
        aria_labels_out: dict[str, str] | None = None,
    ) -> list[tuple[str, date]]:
        """Scroll the main timeline and collect photos within a date range.

        Google Photos shows photos newest-first. This method scrolls downward,
        extracting each rendered photo anchor's ``href`` (for the id) and
        ``aria-label`` (for the date), and keeps only those in range.

        Scrolling stops when either:
        - We have scrolled past ``start_date`` AND the in-range collection
          has been stable (no new in-range photos added) for
          ``post_boundary_stable_threshold`` consecutive iterations, or
        - No new photos have been rendered at all for ``stability_threshold``
          consecutive scrolls (end of the timeline), or
        - ``max_scrolls`` is reached (safety cap).

        We deliberately do NOT stop the moment ``earliest_date_in_view``
        drops below ``start_date``: Google Photos virtualizes its grid and
        only renders a small DOM window at a time, so it is common for the
        boundary day's tiles to still be loading even after a tile from the
        previous day has scrolled into view. Stopping eagerly there caused
        the boundary day to be undercounted (e.g. 3/7 photos detected for
        a single-day range due to Google Photos grid virtualization).

        Args:
            start_date: Start of the date range (inclusive)
            end_date: End of the date range (inclusive)
            max_scrolls: Safety cap on scroll iterations
            scroll_pause: Seconds to wait after each scroll for new content
            stability_threshold: Consecutive unchanged scrolls before stopping
            post_boundary_stable_threshold: After ``earliest_date_in_view``
                first drops below ``start_date``, how many additional
                iterations of zero new in-range photos to require before
                stopping.

        Returns:
            List of (photo_id, photo_date) tuples within the range. IDs are
            deduplicated; order is not guaranteed.
        """
        await self.navigate_to_date_range(start_date, end_date)
        page = self.client.page

        collected: dict[str, date] = {}
        all_seen_ids: set[str] = set()
        no_new_id_iterations = 0
        total_unparsed = 0
        seen_before_start = False
        post_boundary_stable = 0
        previous_in_range_count = 0

        for scroll_i in range(max_scrolls):
            # Extract all currently rendered photo anchors and their labels.
            # Google Photos photo anchors have href containing "/photo/" and
            # an aria-label with a human-readable timestamp.
            raw_items: list[dict[str, str]] = await page.evaluate(
                """
                () => {
                    const out = [];
                    const anchors = document.querySelectorAll('a[href*="/photo/"]');
                    for (const a of anchors) {
                        out.push({
                            label: a.getAttribute('aria-label') || '',
                            href: a.getAttribute('href') || '',
                        });
                    }
                    return out;
                }
                """
            )

            earliest_date_in_view: date | None = None
            unparsed_this_batch = 0
            new_unique_ids_this_iter = 0

            for item in raw_items:
                label = item.get("label", "")
                href = item.get("href", "")
                photo_id = self._extract_photo_id(href)
                photo_date = parse_date_from_aria_label(label)

                if photo_id and photo_id not in all_seen_ids:
                    all_seen_ids.add(photo_id)
                    new_unique_ids_this_iter += 1

                if photo_date is None:
                    if label:
                        unparsed_this_batch += 1
                    continue

                if earliest_date_in_view is None or photo_date < earliest_date_in_view:
                    earliest_date_in_view = photo_date

                if photo_id and start_date <= photo_date <= end_date:
                    collected[photo_id] = photo_date
                    # Capture the aria-label while the tile is still in
                    # the DOM — after the scroll passes the target day,
                    # the virtualized grid unloads the tile and its
                    # label cannot be re-fetched later.
                    if aria_labels_out is not None and label:
                        aria_labels_out[photo_id] = label

            total_unparsed += unparsed_this_batch

            new_in_range_added = len(collected) - previous_in_range_count
            previous_in_range_count = len(collected)

            log_fn = logger.info if scroll_i == 0 else logger.debug
            log_fn(
                "Scroll %d: rendered=%d new_unique=%d in_range=%d (+%d) "
                "earliest_visible=%s unparsed=%d",
                scroll_i,
                len(raw_items),
                new_unique_ids_this_iter,
                len(collected),
                new_in_range_added,
                earliest_date_in_view,
                unparsed_this_batch,
            )

            # End-of-timeline detection. We CANNOT use ``len(raw_items)``
            # for this: Google Photos virtualizes its grid and recycles
            # tiles, so the rendered DOM count stays roughly constant even
            # as we scroll through thousands of photos. Instead, track the
            # set of photo ids we have ever seen across all iterations and
            # stop only when no new ids appear for several iterations in a
            # row.
            if new_unique_ids_this_iter == 0:
                no_new_id_iterations += 1
            else:
                no_new_id_iterations = 0

            if no_new_id_iterations >= stability_threshold:
                logger.info(
                    "No new photo ids for %d iterations; assuming end of "
                    "timeline at iteration %d (total seen: %d)",
                    no_new_id_iterations,
                    scroll_i,
                    len(all_seen_ids),
                )
                break

            # Once we've seen any photo older than start_date, we know the
            # target range is at least partially behind us. We do NOT stop
            # immediately though — Google Photos virtualizes the grid and
            # boundary-day tiles may still be paging in. Keep scrolling
            # until no new in-range photos have been added for several
            # consecutive iterations.
            if earliest_date_in_view is not None and earliest_date_in_view < start_date:
                if not seen_before_start:
                    logger.info(
                        "Earliest visible date (%s) dropped below start_date "
                        "(%s) at iteration %d; entering boundary-drain mode",
                        earliest_date_in_view,
                        start_date,
                        scroll_i,
                    )
                    seen_before_start = True

                if new_in_range_added == 0:
                    post_boundary_stable += 1
                else:
                    post_boundary_stable = 0

                if post_boundary_stable >= post_boundary_stable_threshold:
                    logger.info(
                        "No new in-range photos for %d iterations after "
                        "passing start_date; stopping at iteration %d "
                        "(total in-range collected: %d)",
                        post_boundary_stable,
                        scroll_i,
                        len(collected),
                    )
                    break

            # Scroll down via a real wheel event (window.scrollBy doesn't
            # work because Google Photos uses a virtualized inner container).
            await self._scroll_timeline()
            await asyncio.sleep(scroll_pause)
        else:
            logger.warning(
                "Reached max_scrolls=%d without hitting a stop condition", max_scrolls
            )

        if total_unparsed > 0:
            logger.warning(
                "Could not parse a date from %d aria-labels during collection. "
                "If the in-range count looks wrong, the label format may have "
                "changed — check one of the unparsed labels with browser devtools.",
                total_unparsed,
            )

        logger.info(
            "Collected %d photos in range %s to %s",
            len(collected),
            start_date,
            end_date,
        )
        return list(collected.items())

    @staticmethod
    def _extract_photo_id(href: str) -> str | None:
        """Extract a photo id from an anchor ``href``.

        Google Photos photo links look like ``./photo/AF1QipXYZ...`` or
        ``/photo/AF1QipXYZ...``. We take the segment after ``/photo/`` and
        strip any query / fragment.
        """
        if not href or "/photo/" not in href:
            return None
        segment = href.split("/photo/", 1)[1]
        segment = segment.split("?", 1)[0].split("#", 1)[0].strip("/")
        return segment or None

    async def count_photos_in_range(self, start_date: date, end_date: date) -> int:
        """Count photos in a date range.

        Args:
            start_date: Start date of range
            end_date: End date of range

        Returns:
            Number of photos in the range
        """
        records = await self._collect_photo_records_in_range(start_date, end_date)
        logger.info(
            "Found %d photos in date range %s to %s",
            len(records),
            start_date,
            end_date,
        )
        return len(records)

    async def get_photos_in_range(
        self,
        start_date: date,
        end_date: date,
    ) -> AsyncGenerator[Photo, None]:
        """Get all photos in a date range.

        Args:
            start_date: Start date of range
            end_date: End date of range

        Yields:
            Photo objects with ``created_at`` set to midnight of the parsed
            date (time-of-day is not currently extracted from aria-labels).
        """
        records = await self._collect_photo_records_in_range(start_date, end_date)
        for photo_id, photo_date in records:
            yield Photo(
                id=photo_id,
                created_at=datetime.combine(photo_date, time.min),
            )

    async def get_photo_summary_by_date(
        self,
        start_date: date,
        end_date: date,
    ) -> list[PhotoSummary]:
        """Get photo count summary grouped by date.

        Args:
            start_date: Start date of range
            end_date: End date of range

        Returns:
            List of ``PhotoSummary`` objects sorted by date ascending.
        """
        records = await self._collect_photo_records_in_range(start_date, end_date)

        counts: dict[date, int] = {}
        for _photo_id, photo_date in records:
            counts[photo_date] = counts.get(photo_date, 0) + 1

        return [
            PhotoSummary(date=d.isoformat(), count=c) for d, c in sorted(counts.items())
        ]

    async def _dismiss_open_dialog(self) -> None:
        """Close any modal dialog that might be left open from a previous step.

        Stuck dialogs are the most common cause of cascading failures in a
        long deletion run: a transient network error during the
        confirm-button click leaves the dialog open, and every subsequent
        ``select_photo`` click is then absorbed by the dialog's overlay.
        Pressing Escape is the safest cleanup — it dismisses dialogs without
        triggering any destructive default action.
        """
        page = self.client.page
        try:
            dialog = await page.query_selector('[role="dialog"]')
            if dialog is not None:
                logger.debug("Dismissing leftover dialog with Escape")
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.3)
        except Exception as e:  # noqa: BLE001 — recovery path, swallow
            logger.debug("Dialog dismiss check failed (non-fatal): %s", e)

    async def _exit_selection_mode(self) -> None:
        """Exit Google Photos selection mode if it is currently active.

        After a successful deletion Google Photos usually drops out of
        selection mode automatically, but on flaky deletes the previous
        selection can persist and cause the next ``select_photo`` to be
        interpreted as "add to selection" instead of "start a fresh
        selection". Pressing Escape clears it without side effects.
        """
        page = self.client.page
        with contextlib.suppress(Exception):
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.2)

    async def select_photo(self, photo_id: str) -> bool:
        """Select a photo by ID.

        Google Photos has no ``data-photo-id`` / ``data-id`` attributes on
        tiles. Each photo tile contains an ``<a href=".../photo/<id>">``
        anchor (opens the detail view on click) and a sibling
        ``<div role="checkbox" aria-label="写真 - ...">`` overlay that
        toggles selection mode. We locate the anchor by its href and then
        click the checkbox found within the nearest common ancestor — that
        puts the app into selection mode without leaving the grid.

        Args:
            photo_id: Photo ID to select

        Returns:
            True if photo was selected

        Raises:
            PhotoNotFoundError: If photo cannot be found
        """
        page = self.client.page

        try:
            clicked = await page.evaluate(
                """
                (photoId) => {
                    const anchor = document.querySelector(
                        `a[href*="/photo/${photoId}"]`
                    );
                    if (!anchor) return false;
                    // Walk up until we find a subtree that also contains
                    // the selection checkbox overlay for this tile.
                    let el = anchor;
                    for (let i = 0; i < 6 && el.parentElement; i++) {
                        el = el.parentElement;
                        const cb = el.querySelector(
                            'div[role="checkbox"][aria-label^="写真"]'
                        );
                        if (cb) {
                            cb.click();
                            return true;
                        }
                    }
                    return false;
                }
                """,
                photo_id,
            )

            if not clicked:
                raise PhotoNotFoundError(photo_id)

            await asyncio.sleep(0.5)
            return True

        except PhotoNotFoundError:
            raise
        except Exception as e:
            raise PhotoNotFoundError(photo_id) from e

    async def select_all_visible_photos(self) -> int:
        """Select all currently rendered photo tiles.

        Clicks every per-photo selection checkbox overlay
        (``div[role="checkbox"][aria-label^="写真"]``). The first click
        enters selection mode; subsequent clicks add to the selection.

        Returns:
            Number of photos selected
        """
        page = self.client.page

        count = await page.evaluate(
            """
            () => {
                const boxes = document.querySelectorAll(
                    'div[role="checkbox"][aria-label^="写真"]'
                );
                for (const cb of boxes) cb.click();
                return boxes.length;
            }
            """
        )

        if count:
            await asyncio.sleep(0.5)

        return int(count)

    @with_retry(retryable_exceptions=(PhotoDeletionError, RateLimitError))
    async def delete_photo(self, photo_id: str) -> bool:
        """Delete a single photo.

        Args:
            photo_id: Photo ID to delete

        Returns:
            True if deletion was successful

        Raises:
            PhotoDeletionError: If deletion fails
        """
        page = self.client.page

        try:
            # Recover from any UI state left over from a previous attempt:
            # a stuck dialog or lingering selection would otherwise cause
            # this attempt to fail in confusing ways.
            await self._dismiss_open_dialog()
            await self._exit_selection_mode()

            # Enter selection mode by clicking the photo's checkbox overlay.
            await self.select_photo(photo_id)

            # Wait for the selection-mode toolbar to render.
            await asyncio.sleep(1)

            # Click the "ゴミ箱に移動" (Move to trash) button in the top
            # toolbar. The aria-label is locale-specific: the app launches
            # Chromium with locale="ja-JP", so the label is always Japanese.
            delete_button = await page.wait_for_selector(
                'button[aria-label="ゴミ箱に移動"]',
                timeout=5000,
            )

            if delete_button is None:
                raise PhotoDeletionError(photo_id, "Delete button not found")

            await delete_button.click()
            await asyncio.sleep(1)

            # Confirm in the dialog. The dialog's buttons have aria-label=null
            # (text-only), and the same "ゴミ箱に移動" label exists on the
            # toolbar button too — scope the lookup to [role="dialog"] so we
            # hit the confirmation button and not the toolbar one.
            confirm_button = await page.wait_for_selector(
                '[role="dialog"] button:has-text("ゴミ箱に移動")',
                timeout=5000,
            )

            if confirm_button:
                await confirm_button.click()
                # Wait for the dialog to actually close. Without this the
                # next iteration may still see the closing dialog and trip
                # the dismiss-on-entry recovery path.
                with contextlib.suppress(Exception):
                    await page.wait_for_selector(
                        '[role="dialog"]', state="detached", timeout=5000
                    )

            logger.info("Deleted photo: %s", photo_id)

            # Rate limiting delay
            await asyncio.sleep(settings.delete_interval)

            return True

        except PhotoNotFoundError:
            raise
        except Exception as e:
            raise PhotoDeletionError(photo_id, str(e)) from e

    async def delete_photos_batch(
        self,
        photo_ids: list[str],
        on_progress: ProgressCallback | None = None,
    ) -> tuple[int, list[str]]:
        """Delete multiple photos by ID (legacy pre-collected mode).

        .. warning::
            This method only works reliably for **small** photo sets where
            every photo in ``photo_ids`` is still in the rendered DOM at
            the moment we try to delete it. Google Photos virtualizes its
            grid and unloads off-screen tiles, so for large ranges this
            method will see ``PhotoNotFoundError`` for most ids. For any
            real deletion run use :py:meth:`delete_photos_in_range_streaming`
            instead — it interleaves scrolling and deletion so each photo
            is always in the DOM at delete-time.

        Args:
            photo_ids: List of photo IDs to delete
            on_progress: Optional callback for progress updates

        Returns:
            Tuple of (deleted_count, failed_photo_ids)
        """
        deleted_count = 0
        failed_ids: list[str] = []

        for i, photo_id in enumerate(photo_ids):
            try:
                await self.delete_photo(photo_id)
                deleted_count += 1
            except (PhotoDeletionError, PhotoNotFoundError) as e:
                logger.error("Failed to delete photo %s: %s", photo_id, e)
                failed_ids.append(photo_id)

            if on_progress:
                await on_progress(i + 1, len(photo_ids), photo_id)

        return deleted_count, failed_ids

    async def _bulk_select_visible_in_range(
        self,
        start_date: date,
        end_date: date,
        skip_ids: set[str],
    ) -> dict[str, Any]:
        """Select all in-range photos currently rendered in the DOM.

        Walks the ``div[role="checkbox"]`` list in document order, grouping
        photo checkboxes (class ``ckGgle``) under their preceding date-header
        checkbox (class ``R4HkWb``). For each group:

        - If **all** photos in the group are inside the target range and a
          header exists, click the header — this bulk-selects the entire
          date in a single click.
        - Otherwise, click individual in-range photo checkboxes.

        Returns a dict with:
            selectedIds: list[str] — photo ids that were clicked
            earliest: str | None — earliest photo date seen, ISO format
            groupCount: int
        """
        page = self.client.page
        result: dict[str, Any] = await page.evaluate(
            """
            (args) => {
                const { startIso, endIso, skipIds } = args;
                const start = new Date(startIso + 'T00:00:00');
                const end = new Date(endIso + 'T23:59:59.999');
                const skip = new Set(skipIds);

                const parseDate = (label) => {
                    // Handles "写真 - 縦向き - 2026/04/07 11:31:11" and
                    // "写真 - 2020年1月1日 22:30:45" style labels.
                    let m = label.match(/(\\d{4})\\/(\\d{1,2})\\/(\\d{1,2})/);
                    if (m) return new Date(
                        parseInt(m[1]), parseInt(m[2]) - 1, parseInt(m[3])
                    );
                    m = label.match(/(\\d{4})年(\\d{1,2})月(\\d{1,2})日/);
                    if (m) return new Date(
                        parseInt(m[1]), parseInt(m[2]) - 1, parseInt(m[3])
                    );
                    m = label.match(/(\\d{4})-(\\d{1,2})-(\\d{1,2})/);
                    if (m) return new Date(
                        parseInt(m[1]), parseInt(m[2]) - 1, parseInt(m[3])
                    );
                    return null;
                };

                const extractId = (href) => {
                    if (!href || !href.includes('/photo/')) return null;
                    let seg = href.split('/photo/')[1];
                    seg = seg.split('?')[0].split('#')[0];
                    return seg.split('/')[0] || null;
                };

                const findAnchorHref = (cb) => {
                    let el = cb.parentElement;
                    for (let i = 0; i < 6 && el; i++) {
                        const a = el.querySelector('a[href*="/photo/"]');
                        if (a) return a.getAttribute('href');
                        el = el.parentElement;
                    }
                    return null;
                };

                const toIso = (d) => {
                    const y = d.getFullYear();
                    const m = String(d.getMonth() + 1).padStart(2, '0');
                    const day = String(d.getDate()).padStart(2, '0');
                    return `${y}-${m}-${day}`;
                };

                // Phase 1: walk DOM checkboxes and build "raw groups"
                // (header + following photos until the next header). Then
                // split each raw group into per-photo-date buckets. This
                // handles the case where Google Photos omits the date
                // header for dates that have only one photo — those lone
                // photos appear INSIDE a preceding header's raw group in
                // DOM order but belong to a different date. Without the
                // split, we would mis-click the preceding header (which
                // only selects its own date) and incorrectly mark the
                // lone photo as deleted.
                const cbs = document.querySelectorAll('div[role="checkbox"]');
                const rawGroups = [];
                let current = null;
                for (const cb of cbs) {
                    const cls = cb.className || '';
                    if (cls.includes('R4HkWb')) {
                        if (current) rawGroups.push(current);
                        current = { header: cb, photos: [] };
                    } else if (cls.includes('ckGgle')) {
                        const label = cb.getAttribute('aria-label') || '';
                        const d = parseDate(label);
                        const href = findAnchorHref(cb);
                        const id = extractId(href);
                        if (current === null) {
                            current = { header: null, photos: [] };
                        }
                        current.photos.push({ cb, d, id });
                    }
                }
                if (current) rawGroups.push(current);

                // Phase 2: bucket photos by date within each raw group.
                // The FIRST photo's date is treated as the header-owned
                // date: clicking the header selects exactly those photos
                // (and only those, even offscreen ones). All other date
                // buckets in the same raw group are "orphan" single-photo
                // dates and must be clicked individually.
                const groups = [];
                for (const rg of rawGroups) {
                    if (rg.photos.length === 0) {
                        // Header with no photos — skip
                        continue;
                    }
                    const firstDateKey = rg.photos[0].d ? toIso(rg.photos[0].d) : null;
                    const buckets = new Map();
                    for (const p of rg.photos) {
                        const k = p.d ? toIso(p.d) : '__nodate__';
                        if (!buckets.has(k)) buckets.set(k, []);
                        buckets.get(k).push(p);
                    }
                    for (const [k, photos] of buckets) {
                        const isHeaderOwned = (k === firstDateKey && rg.header !== null);
                        groups.push({
                            header: isHeaderOwned ? rg.header : null,
                            photos: photos,
                            dateKey: k,
                        });
                    }
                }

                // Earliest date in view across all dated photos
                let earliest = null;
                for (const g of groups) {
                    for (const p of g.photos) {
                        if (p.d && (!earliest || p.d < earliest)) earliest = p.d;
                    }
                }

                const selectedIds = [];
                let headerClickCount = 0;
                let individualClickCount = 0;
                for (const g of groups) {
                    const dated = g.photos.filter(p => p.d && p.id && !skip.has(p.id));
                    if (dated.length === 0) continue;
                    const inRange = dated.filter(p => p.d >= start && p.d <= end);
                    if (inRange.length === 0) continue;
                    const allIn = inRange.length === dated.length;
                    if (allIn && g.header) {
                        // Bulk-select entire date group via header click.
                        // NOTE: This also selects any offscreen photos for
                        // this date that are not in the current DOM, so
                        // the actual deletion count may exceed the size
                        // of selectedIds. The caller compensates with a
                        // final re-count pass at the end.
                        g.header.click();
                        headerClickCount++;
                        for (const p of inRange) selectedIds.push(p.id);
                    } else {
                        // Individual clicks for in-range photos only
                        // (orphan single-photo dates with no header, or
                        // partial range overlap).
                        for (const p of inRange) {
                            p.cb.click();
                            individualClickCount++;
                            selectedIds.push(p.id);
                        }
                    }
                }

                return {
                    selectedIds,
                    earliest: earliest ? toIso(earliest) : null,
                    groupCount: groups.length,
                    headerClickCount,
                    individualClickCount,
                };
            }
            """,
            {
                "startIso": start_date.isoformat(),
                "endIso": end_date.isoformat(),
                "skipIds": list(skip_ids),
            },
        )
        return result

    async def _click_trash_and_confirm(self) -> None:
        """Click the "ゴミ箱に移動" toolbar button and confirm the dialog.

        Assumes at least one photo is currently selected. Raises
        ``PhotoDeletionError`` (generic id "bulk") if the toolbar button or
        confirm dialog cannot be found.
        """
        page = self.client.page

        # Dismiss any leftover dialog/overlay that may be blocking the
        # toolbar button (e.g. from a prior interrupted operation).
        await self._dismiss_open_dialog()

        delete_button = await page.wait_for_selector(
            'button[aria-label="ゴミ箱に移動"]',
            timeout=5000,
        )
        if delete_button is None:
            raise PhotoDeletionError("bulk", "Trash toolbar button not found")

        # Use JS click to bypass overlay/scrim elements that may intercept
        # pointer events (e.g. Google Photos' dialog backdrop).
        try:
            await delete_button.click(timeout=5000)
        except PlaywrightTimeoutError:
            logger.warning(
                "Trash button click intercepted by overlay; retrying with JS dispatch"
            )
            await page.evaluate("el => el.click()", delete_button)
        await asyncio.sleep(0.8)

        confirm_button = await page.wait_for_selector(
            '[role="dialog"] button:has-text("ゴミ箱に移動")',
            timeout=5000,
        )
        if confirm_button is None:
            raise PhotoDeletionError("bulk", "Confirm dialog button not found")

        try:
            await confirm_button.click(timeout=5000)
        except PlaywrightTimeoutError:
            logger.warning(
                "Confirm button click intercepted; retrying with JS dispatch"
            )
            await page.evaluate("el => el.click()", confirm_button)

        # Wait for the dialog to actually close before returning.
        with contextlib.suppress(Exception):
            await page.wait_for_selector(
                '[role="dialog"]', state="detached", timeout=5000
            )
        await asyncio.sleep(settings.delete_interval)

    async def delete_photos_in_range_streaming(
        self,
        start_date: date,
        end_date: date,
        *,
        expected_total: int | None = None,
        on_progress: ProgressCallback | None = None,
        on_photo_deleted: Callable[[str], Coroutine[Any, Any, None]] | None = None,
        max_iterations: int = 10000,
        scroll_pause: float = 1.2,
        post_boundary_stable_threshold: int = 5,
    ) -> tuple[int, list[str]]:
        """Stream-delete photos in a date range.

        Unlike :py:meth:`delete_photos_batch`, this method does NOT pre-
        collect every photo id up front. Instead, it interleaves DOM
        extraction, deletion, and scrolling:

        1. Extract photos currently rendered in the DOM.
        2. If any are within the date range, delete the first one.
        3. Re-extract (the DOM has shifted) and repeat.
        4. If no in-range photos are visible, scroll and re-extract.
        5. Stop after the boundary day has been drained.

        This guarantees the photo we want to delete is always in the DOM
        at the moment we click it — which is the failure mode that breaks
        ``delete_photos_batch`` for any non-trivial range.

        Args:
            start_date: Start of the range (inclusive)
            end_date: End of the range (inclusive)
            expected_total: Optional pre-computed total (from a dry run)
                used to drive ``on_progress``. If ``None``, the progress
                callback will report ``-1`` for total.
            on_progress: Optional callback ``(processed, total, photo_id)``
                invoked after each successful deletion.
            on_photo_deleted: Optional callback invoked with the deleted
                photo id immediately after a successful deletion. Use this
                to update persistent state for resume support.
            max_iterations: Safety cap on the main loop iterations.
            scroll_pause: Seconds to wait after a scroll for new content.
            post_boundary_stable_threshold: After we have seen any photo
                older than ``start_date`` AND there are no more in-range
                photos in the DOM, how many additional empty iterations to
                tolerate before declaring the run finished.

        Returns:
            Tuple of (deleted_count, failed_photo_ids).
        """
        deleted_ids: set[str] = set()
        failed_ids: list[str] = []
        # Track ids we have permanently given up on so we don't retry them
        # forever in the same run.
        skip_ids: set[str] = set()
        total = expected_total if expected_total is not None else -1

        # Multi-pass loop: Google Photos virtualizes the grid, so a single
        # top-down scroll pass can miss photos that were unloaded from the
        # DOM after we scrolled past them. We re-navigate and re-scan after
        # each pass that deleted at least one photo, until a fresh pass
        # finds zero in-range photos.
        max_passes = 10
        for pass_num in range(max_passes):
            await self.navigate_to_date_range(start_date, end_date)
            deleted_in_pass = 0
            seen_before_start = False
            post_boundary_empty = 0

            for iteration in range(max_iterations):
                # Recover any UI state from a prior failure before extracting.
                await self._dismiss_open_dialog()
                await self._exit_selection_mode()

                # Bulk-select everything in range currently visible.
                selection = await self._bulk_select_visible_in_range(
                    start_date, end_date, skip_ids | deleted_ids
                )
                selected_ids: list[str] = selection.get("selectedIds") or []
                earliest_iso = selection.get("earliest")
                earliest_date_in_view: date | None = (
                    date.fromisoformat(earliest_iso) if earliest_iso else None
                )

                logger.debug(
                    "Streaming pass %d iter %d: groups=%d earliest=%s "
                    "selected_this_iter=%d total_deleted=%d failed=%d",
                    pass_num,
                    iteration,
                    selection.get("groupCount", 0),
                    earliest_date_in_view,
                    len(selected_ids),
                    len(deleted_ids),
                    len(failed_ids),
                )

                if selected_ids:
                    # Fresh ids this round (defense in depth — the JS already
                    # filters skip_ids|deleted_ids, but we de-dupe once more).
                    fresh_ids = [pid for pid in selected_ids if pid not in deleted_ids]
                    if not fresh_ids:
                        # All already deleted — treat as empty round, clear
                        # selection and scroll.
                        await self._exit_selection_mode()
                        await self._scroll_timeline()
                        await asyncio.sleep(scroll_pause)
                        continue

                    post_boundary_empty = 0
                    try:
                        # Give the toolbar a moment to render after the
                        # selection clicks.
                        await asyncio.sleep(0.6)
                        await self._click_trash_and_confirm()
                        deleted_ids.update(fresh_ids)
                        deleted_in_pass += len(fresh_ids)
                        if on_photo_deleted is not None:
                            for pid in fresh_ids:
                                await on_photo_deleted(pid)
                        if on_progress is not None:
                            await on_progress(len(deleted_ids), total, fresh_ids[-1])
                        logger.info(
                            "Bulk-deleted %d photo(s) in one shot "
                            "(pass=%d iter=%d total_deleted=%d)",
                            len(fresh_ids),
                            pass_num,
                            iteration,
                            len(deleted_ids),
                        )
                        # Layout reflow after bulk delete.
                        await asyncio.sleep(1.0)
                    except (PhotoDeletionError, PhotoNotFoundError) as e:
                        logger.error(
                            "Bulk delete failed for %d photo(s): %s",
                            len(fresh_ids),
                            e,
                        )
                        failed_ids.extend(fresh_ids)
                        skip_ids.update(fresh_ids)
                        await self._dismiss_open_dialog()
                        await self._exit_selection_mode()
                    # Loop back: re-extract the (now-shifted) DOM.
                    continue

                # No in-range photo currently in DOM.
                if (
                    earliest_date_in_view is not None
                    and earliest_date_in_view < start_date
                ):
                    if not seen_before_start:
                        logger.info(
                            "Pass %d: earliest visible date (%s) dropped "
                            "below start_date (%s) at iter %d; "
                            "entering boundary-drain mode",
                            pass_num,
                            earliest_date_in_view,
                            start_date,
                            iteration,
                        )
                        seen_before_start = True
                    post_boundary_empty += 1
                    if post_boundary_empty >= post_boundary_stable_threshold:
                        logger.info(
                            "Pass %d complete: no in-range photos for %d "
                            "iterations after passing start_date "
                            "(pass_deleted=%d total_deleted=%d failed=%d)",
                            pass_num,
                            post_boundary_empty,
                            deleted_in_pass,
                            len(deleted_ids),
                            len(failed_ids),
                        )
                        break

                # Scroll to fetch more photos.
                await self._scroll_timeline()
                await asyncio.sleep(scroll_pause)
            else:
                logger.warning(
                    "Streaming delete pass %d reached max_iterations=%d "
                    "without natural stop (total_deleted=%d failed=%d)",
                    pass_num,
                    max_iterations,
                    len(deleted_ids),
                    len(failed_ids),
                )

            # If this pass deleted nothing, we're truly done — a fresh
            # top-down scan of the range found zero in-range photos.
            if deleted_in_pass == 0:
                logger.info(
                    "Multi-pass streaming delete finished after %d pass(es) "
                    "(total_deleted=%d failed=%d)",
                    pass_num + 1,
                    len(deleted_ids),
                    len(failed_ids),
                )
                break
            logger.info(
                "Pass %d deleted %d photo(s); re-navigating for another "
                "pass to catch any photos missed due to virtualization",
                pass_num,
                deleted_in_pass,
            )
        else:
            logger.warning(
                "Streaming delete reached max_passes=%d without natural "
                "stop (total_deleted=%d failed=%d)",
                max_passes,
                len(deleted_ids),
                len(failed_ids),
            )

        # Final reconciliation: bulk header clicks also delete photos that
        # were virtualized out of the DOM at JS-click time, so they never
        # made it into ``deleted_ids``. The tracked count can therefore
        # undershoot the actual deletions (observed: 98 tracked vs 121
        # real). Do one more scan of the range — whatever is still there
        # is what we failed to delete; the rest must have been deleted.
        if expected_total is not None and expected_total > 0:
            try:
                remaining = await self.count_photos_in_range(start_date, end_date)
                actual_deleted = max(0, expected_total - remaining)
                logger.info(
                    "Final recount: expected=%d remaining=%d "
                    "actual_deleted=%d (tracked_ids=%d failed=%d)",
                    expected_total,
                    remaining,
                    actual_deleted,
                    len(deleted_ids),
                    len(failed_ids),
                )
                return actual_deleted, failed_ids
            except Exception as e:  # noqa: BLE001 — best-effort recount
                logger.warning(
                    "Final recount failed (%s); falling back to tracked id count %d",
                    e,
                    len(deleted_ids),
                )

        return len(deleted_ids), failed_ids

    # ------------------------------------------------------------------
    # Trash / restore — used exclusively by the E2E test suite to put
    # photos back after a delete run so the test is safely repeatable.
    # The production code path never calls these methods.
    # ------------------------------------------------------------------

    TRASH_URL = "https://photos.google.com/trash"

    async def get_photo_labels_in_range(
        self,
        start_date: date,
        end_date: date,
    ) -> list[str]:
        """Return the ``aria-label`` strings of photos in a date range.

        Unlike :py:meth:`get_photos_in_range` (which returns stable photo
        IDs), this returns the human-readable aria-labels — needed because
        the ``/trash`` page does NOT render ``/photo/<id>`` anchors, so
        the only way to match a trashed tile back to a pre-delete photo
        is via the aria-label datetime string (e.g.
        ``"写真 - 縦向き - 2026/04/01 10:23:45"``).

        Labels are captured **during** the scroll pass via the
        ``aria_labels_out`` parameter on
        :py:meth:`_collect_photo_records_in_range`. A post-scroll DOM
        re-scrape does NOT work: Google Photos virtualizes its grid and
        unloads tiles after the scroll moves past them, so by the time
        the collection loop returns the target-day tiles are already
        gone from the DOM.

        Args:
            start_date: Start of range (inclusive)
            end_date: End of range (inclusive)

        Returns:
            Deduplicated list of aria-labels. Order is not guaranteed.
        """
        labels_by_id: dict[str, str] = {}
        records = await self._collect_photo_records_in_range(
            start_date, end_date, aria_labels_out=labels_by_id
        )
        in_range_ids = {pid for pid, _ in records}

        missing = in_range_ids - labels_by_id.keys()
        if missing:
            logger.warning(
                "get_photo_labels_in_range: %d/%d photo IDs had no "
                "aria-label captured during scroll — these cannot be "
                "matched during restore.",
                len(missing),
                len(in_range_ids),
            )
        return list(labels_by_id.values())

    async def restore_photos_from_trash_by_labels(
        self,
        target_labels: set[str],
        *,
        max_iterations: int = 100,
    ) -> tuple[int, list[str]]:
        """Restore photos in the /trash page whose ``aria-label`` matches.

        Used by the E2E test teardown to put test photos back after a
        delete run. Only tiles whose aria-label is in ``target_labels``
        are touched — other trash items (from prior user actions) are
        left alone.

        The restore flow per the DOM probe on 2026-04-08:

        1. ``div[role="checkbox"][aria-label^="写真"]`` — trash tiles
           (identical selector to the main timeline).
        2. Click matching tile(s) to enter selection mode.
        3. ``button[aria-label="復元"]`` — restore button in the toolbar.
           NOTE: Google Photos renders **two** such buttons (one hidden
           pre-rendered, one visible). We always click the visible one
           via JS ``getBoundingClientRect`` check.
        4. Confirm dialog "ファイルを復元しますか？" — click the dialog's
           ``button:has-text("復元")`` (aria-label is null on dialog
           buttons, same pattern as the delete confirm dialog).
        5. Repeat until no matching tiles remain. A single pass is not
           enough because Google Photos may only render the first few
           tiles; after a batch is restored, previously-unrendered tiles
           may scroll into view.

        Args:
            target_labels: Set of aria-label strings to match exactly.
            max_iterations: Safety cap on the outer restore loop.

        Returns:
            Tuple of ``(restored_count, unrestored_labels)``.
        """
        page = self.client.page
        restored = 0
        remaining_targets = set(target_labels)

        for iteration in range(max_iterations):
            if not remaining_targets:
                break

            await page.goto(self.TRASH_URL)
            await asyncio.sleep(3)

            # Recover from any leftover UI state.
            await self._dismiss_open_dialog()
            await self._exit_selection_mode()

            # Find all visible trash tiles whose aria-label is in our
            # target set, and click them to enter selection mode.
            select_result = await page.evaluate(
                """(targets) => {
                    const set = new Set(targets);
                    const out = [];
                    const cbs = document.querySelectorAll(
                        'div[role="checkbox"][aria-label^="写真"]'
                    );
                    for (const cb of cbs) {
                        const aria = cb.getAttribute('aria-label') || '';
                        if (!set.has(aria)) continue;
                        const r = cb.getBoundingClientRect();
                        if (r.width === 0 && r.height === 0) continue;
                        cb.click();
                        out.push(aria);
                    }
                    return out;
                }""",
                list(remaining_targets),
            )

            selected_labels: list[str] = list(select_result or [])
            logger.info(
                "Restore iter %d: selected %d tile(s) in /trash (remaining targets=%d)",
                iteration,
                len(selected_labels),
                len(remaining_targets),
            )

            if not selected_labels:
                # None of our targets are visible in the current trash
                # view. Try scrolling once to fetch more before giving up.
                await self._scroll_timeline()
                await asyncio.sleep(1.2)
                rescan = await page.evaluate(
                    """(targets) => {
                        const set = new Set(targets);
                        let hit = 0;
                        const cbs = document.querySelectorAll(
                            'div[role="checkbox"][aria-label^="写真"]'
                        );
                        for (const cb of cbs) {
                            if (set.has(cb.getAttribute('aria-label') || '')) hit++;
                        }
                        return hit;
                    }""",
                    list(remaining_targets),
                )
                if rescan == 0:
                    logger.warning(
                        "Restore: %d target(s) not found in /trash after "
                        "scroll; giving up on iteration %d",
                        len(remaining_targets),
                        iteration,
                    )
                    break
                continue

            # Give the selection-mode toolbar a moment to render.
            await asyncio.sleep(0.8)

            # Click the visible 復元 button (there are 2 — the other is
            # hidden / pre-rendered).
            clicked = await page.evaluate(
                """() => {
                    const btns = document.querySelectorAll(
                        'button[aria-label="復元"]'
                    );
                    for (const b of btns) {
                        const r = b.getBoundingClientRect();
                        if (r.width > 0 && r.height > 0) {
                            b.click();
                            return true;
                        }
                    }
                    return false;
                }"""
            )
            if not clicked:
                logger.error(
                    "Restore: no visible 復元 button found after selecting "
                    "%d tile(s); aborting",
                    len(selected_labels),
                )
                await self._exit_selection_mode()
                break

            # Confirm dialog — "ファイルを復元しますか？" with a text-only
            # 復元 button (aria-label is null; scope via [role="dialog"]).
            try:
                confirm = await page.wait_for_selector(
                    '[role="dialog"] button:has-text("復元")',
                    timeout=5000,
                )
            except Exception as e:  # noqa: BLE001 — dialog may have been skipped
                logger.error("Restore: confirm dialog did not appear: %s", e)
                await self._exit_selection_mode()
                break

            if confirm is None:
                logger.error("Restore: confirm button not found in dialog")
                await self._exit_selection_mode()
                break

            await confirm.click()
            with contextlib.suppress(Exception):
                await page.wait_for_selector(
                    '[role="dialog"]', state="detached", timeout=5000
                )
            await asyncio.sleep(1.2)

            restored += len(selected_labels)
            remaining_targets.difference_update(selected_labels)
            logger.info(
                "Restore iter %d: restored %d tile(s) (total restored=%d remaining=%d)",
                iteration,
                len(selected_labels),
                restored,
                len(remaining_targets),
            )

        return restored, sorted(remaining_targets)
