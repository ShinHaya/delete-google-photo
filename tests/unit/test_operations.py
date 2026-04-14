"""Unit tests for PhotoOperations helpers that don't need a live browser."""

from app.browser.operations import PhotoOperations


class TestExtractPhotoId:
    """Tests for PhotoOperations._extract_photo_id."""

    def test_relative_href(self) -> None:
        assert (
            PhotoOperations._extract_photo_id("./photo/AF1QipXyz123") == "AF1QipXyz123"
        )

    def test_absolute_href(self) -> None:
        assert (
            PhotoOperations._extract_photo_id("/photo/AF1QipXyz123") == "AF1QipXyz123"
        )

    def test_full_url(self) -> None:
        assert (
            PhotoOperations._extract_photo_id(
                "https://photos.google.com/photo/AF1QipXyz123"
            )
            == "AF1QipXyz123"
        )

    def test_strips_query_string(self) -> None:
        assert (
            PhotoOperations._extract_photo_id("./photo/AF1QipXyz123?foo=bar")
            == "AF1QipXyz123"
        )

    def test_strips_fragment(self) -> None:
        assert (
            PhotoOperations._extract_photo_id("./photo/AF1QipXyz123#section")
            == "AF1QipXyz123"
        )

    def test_strips_trailing_slash(self) -> None:
        assert (
            PhotoOperations._extract_photo_id("./photo/AF1QipXyz123/") == "AF1QipXyz123"
        )

    def test_no_photo_segment(self) -> None:
        assert PhotoOperations._extract_photo_id("./albums/foo") is None

    def test_empty(self) -> None:
        assert PhotoOperations._extract_photo_id("") is None
