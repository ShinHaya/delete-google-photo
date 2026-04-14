"""Parse dates from Google Photos aria-label strings.

Google Photos renders each photo as an anchor element with an ``aria-label``
that contains a human-readable timestamp, for example:

    Japanese (locale=ja-JP): "写真 - 2020年1月1日 22:30:45"
    English  (locale=en-US): "Photo - Jan 1, 2020, 10:30:45 PM"

This module extracts a ``datetime.date`` from such labels. It is intentionally
permissive: it tries multiple known formats and returns ``None`` if none match.
"""

from __future__ import annotations

import re
from datetime import date

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Japanese full date: 2020年1月1日
_JA_FULL = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")

# ISO date: 2020-01-01 (may appear in some accessible labels)
_ISO = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")

# Slash-separated YMD: 2024/01/08 (observed in actual Google Photos
# aria-labels with locale=ja-JP, e.g. "写真 - 縦向き - 2024/01/08 12:18:12")
_SLASH_YMD = re.compile(r"\b(\d{4})/(\d{1,2})/(\d{1,2})\b")

# English month names
_EN_MONTHS: dict[str, int] = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

# English full date: "Jan 1, 2020" / "January 1, 2020" / "Jan. 1 2020"
_EN_FULL = re.compile(
    r"\b("
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?"
    r")\.?\s+(\d{1,2}),?\s+(\d{4})\b",
    re.IGNORECASE,
)


def parse_date_from_aria_label(label: str | None) -> date | None:
    """Extract a ``date`` from a Google Photos ``aria-label`` string.

    Tries multiple known formats in order of specificity:

    1. ISO: ``2020-01-01``
    2. Slash YMD: ``2024/01/08`` (observed in real ja-JP aria-labels)
    3. Japanese: ``2020年1月1日``
    4. English: ``Jan 1, 2020`` / ``January 1, 2020``

    Args:
        label: The aria-label text (may be ``None`` or empty).

    Returns:
        A ``date`` if a known format matched and the values form a valid
        date; otherwise ``None``.
    """
    if not label:
        return None

    # 1. ISO
    m = _ISO.search(label)
    if m:
        result = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if result is not None:
            return result

    # 2. Slash-separated YMD (e.g. "2024/01/08")
    m = _SLASH_YMD.search(label)
    if m:
        result = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if result is not None:
            return result

    # 3. Japanese
    m = _JA_FULL.search(label)
    if m:
        result = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if result is not None:
            return result

    # 4. English
    m = _EN_FULL.search(label)
    if m:
        month_name = m.group(1).lower().rstrip(".")
        month = _EN_MONTHS.get(month_name)
        if month is not None:
            result = _safe_date(int(m.group(3)), month, int(m.group(2)))
            if result is not None:
                return result

    return None


def _safe_date(year: int, month: int, day: int) -> date | None:
    """Return ``date(year, month, day)`` or ``None`` if the values are invalid."""
    try:
        return date(year, month, day)
    except ValueError:
        return None
