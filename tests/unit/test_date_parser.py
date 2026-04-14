"""Unit tests for Google Photos aria-label date parser."""

from datetime import date

import pytest

from app.browser.date_parser import parse_date_from_aria_label


class TestParseDateFromAriaLabel:
    """Tests for parse_date_from_aria_label."""

    # Japanese formats (locale=ja-JP)

    @pytest.mark.parametrize(
        "label,expected",
        [
            ("写真 - 2020年1月1日 22:30:45", date(2020, 1, 1)),
            ("写真 - 2023年12月31日 23:59:59", date(2023, 12, 31)),
            ("2020年1月1日", date(2020, 1, 1)),
            ("2020 年 1 月 1 日", date(2020, 1, 1)),  # tolerant to spaces
            ("写真 - 人物 - 2021年6月15日 12:00:00 GMT+9", date(2021, 6, 15)),
        ],
    )
    def test_japanese_full(self, label: str, expected: date) -> None:
        assert parse_date_from_aria_label(label) == expected

    # Slash YMD (actually observed in ja-JP Google Photos aria-labels)

    @pytest.mark.parametrize(
        "label,expected",
        [
            ("写真 - 縦向き - 2024/01/08 12:18:12", date(2024, 1, 8)),
            ("写真 - 2024/12/31 23:59:59", date(2024, 12, 31)),
            ("2020/01/01", date(2020, 1, 1)),
            ("写真 - 横向き - 2023/6/15 9:00:00", date(2023, 6, 15)),
        ],
    )
    def test_slash_ymd(self, label: str, expected: date) -> None:
        assert parse_date_from_aria_label(label) == expected

    # English formats (locale=en-US)

    @pytest.mark.parametrize(
        "label,expected",
        [
            ("Photo - Jan 1, 2020, 10:30:45 PM", date(2020, 1, 1)),
            ("Photo - January 1, 2020, 10:30 PM", date(2020, 1, 1)),
            ("Photo - Dec 31, 2023", date(2023, 12, 31)),
            ("Photo - Sept 5, 2022", date(2022, 9, 5)),
            ("Photo - Feb. 14, 2021", date(2021, 2, 14)),
        ],
    )
    def test_english_full(self, label: str, expected: date) -> None:
        assert parse_date_from_aria_label(label) == expected

    # ISO format

    @pytest.mark.parametrize(
        "label,expected",
        [
            ("2020-01-01", date(2020, 1, 1)),
            ("Photo 2023-12-31 12:00", date(2023, 12, 31)),
        ],
    )
    def test_iso(self, label: str, expected: date) -> None:
        assert parse_date_from_aria_label(label) == expected

    # Unparseable / edge cases

    @pytest.mark.parametrize(
        "label",
        [
            None,
            "",
            "Photo",
            "写真",
            "1月1日",  # no year, currently unsupported
            "random text with no date",
            "Photo - 13/45/2020",  # invalid numbers
        ],
    )
    def test_unparseable_returns_none(self, label: str | None) -> None:
        assert parse_date_from_aria_label(label) is None

    def test_invalid_date_values(self) -> None:
        """Invalid dates like Feb 30 should return None, not raise."""
        assert parse_date_from_aria_label("2020年2月30日") is None
        assert parse_date_from_aria_label("2020-02-30") is None
        assert parse_date_from_aria_label("Feb 30, 2020") is None

    def test_prefers_iso_over_other_matches(self) -> None:
        """When multiple formats appear, ISO takes precedence."""
        label = "2020-01-01 (2021年12月31日)"
        # ISO is checked first
        assert parse_date_from_aria_label(label) == date(2020, 1, 1)
