import json

import pytest
from azure.core.exceptions import ResourceNotFoundError

from reviews import (
    build_recent_reviews_document,
    normalize_recent_reviews,
    write_recent_reviews,
)


def make_review_item(
    review_id: int = 101,
    created_at: str = "2026-08-23T11:33:42.000Z",
    spoiler: bool = False,
    text: str = "A precise review of a very interesting show.",
) -> dict:
    return {
        "type": "show",
        "comment": {
            "id": review_id,
            "created_at": created_at,
            "updated_at": created_at,
            "comment": text,
            "review": True,
            "spoiler": spoiler,
            "language": "en",
            "likes": 2,
            "user_rating": 8,
            "user": {"name": "Ada Viewer", "username": "ada"},
        },
        "show": {
            "title": "Signal Show",
            "year": 2026,
            "ids": {"trakt": 500, "tmdb": 600},
        },
    }


def make_snapshot(payload: list[dict] | None = None) -> dict:
    items = payload if payload is not None else [make_review_item()]
    return {
        "collection_id": "reviews-collection",
        "collection_size": len(items),
        "metric_type": "recent_show_reviews",
        "source_timestamp": "Sun, 23 Aug 2026 11:34:00 GMT",
        "observed_at": "2026-08-23T11:35:00Z",
        "payload": items,
    }


def test_normalizes_review_and_limits_public_text() -> None:
    long_text = "word " * 100
    review = normalize_recent_reviews([make_review_item(text=long_text)])[0]

    assert review["review_id"] == 101
    assert review["show"] == {
        "trakt_show_id": 500,
        "tmdb_show_id": 600,
        "title": "Signal Show",
        "year": 2026,
    }
    assert review["reviewer"] == {
        "display_name": "Ada Viewer",
        "username": "ada",
    }
    assert len(review["excerpt"]) <= 320
    assert review["excerpt"].endswith("…")
    assert review["url"] == "https://trakt.tv/comments/101"


def test_hides_spoiler_text_from_public_projection() -> None:
    review = normalize_recent_reviews(
        [make_review_item(spoiler=True, text="The ending is the whole secret.")]
    )[0]

    assert review["spoiler"] is True
    assert review["excerpt"] is None


def test_merges_deduplicates_orders_and_counts_new_reviews() -> None:
    previous = build_recent_reviews_document(
        make_snapshot([make_review_item(review_id=100, created_at="2026-08-23T10:00:00Z")])
    )
    document = build_recent_reviews_document(
        make_snapshot(
            [
                make_review_item(review_id=100, created_at="2026-08-23T10:00:00Z"),
                make_review_item(review_id=102, created_at="2026-08-23T12:00:00Z"),
            ]
        ),
        previous_document=previous,
    )

    assert [review["review_id"] for review in document["reviews"]] == [102, 100]
    assert document["new_review_count"] == 1
    assert document["review_count"] == 2
    assert document["latest_review_at"] == "2026-08-23T12:00:00Z"


def test_caps_review_history() -> None:
    payload = [
        make_review_item(
            review_id=review_id,
            created_at=f"2026-08-23T{review_id:02d}:00:00Z",
        )
        for review_id in range(1, 6)
    ]

    document = build_recent_reviews_document(
        make_snapshot(payload),
        retention_count=3,
    )

    assert [review["review_id"] for review in document["reviews"]] == [5, 4, 3]


def test_rejects_invalid_review_ids() -> None:
    with pytest.raises(ValueError, match="review ID"):
        normalize_recent_reviews([make_review_item(review_id=0)])


class FakeDownload:
    def __init__(self, document: dict | None) -> None:
        self.document = document

    def readall(self) -> bytes:
        if self.document is None:
            raise ResourceNotFoundError("Blob does not exist.")
        return json.dumps(self.document).encode("utf-8")


class FakeBlobClient:
    def __init__(self) -> None:
        self.upload = None

    def download_blob(self) -> FakeDownload:
        return FakeDownload(None)

    def upload_blob(self, data: str, **kwargs) -> None:
        self.upload = {"document": json.loads(data), "kwargs": kwargs}


class FakeBlobServiceClient:
    def __init__(self) -> None:
        self.blob_client = FakeBlobClient()
        self.request = None

    def get_blob_client(self, **kwargs) -> FakeBlobClient:
        self.request = kwargs
        return self.blob_client


def test_writes_recent_reviews_blob() -> None:
    blob_service_client = FakeBlobServiceClient()

    document = write_recent_reviews(
        blob_service_client=blob_service_client,
        container_name="serving",
        snapshot=make_snapshot(),
    )

    assert blob_service_client.request == {
        "container": "serving",
        "blob": "reviews/recent.json",
    }
    assert blob_service_client.blob_client.upload["document"] == document
    assert blob_service_client.blob_client.upload["kwargs"]["overwrite"] is True
    assert (
        blob_service_client.blob_client.upload["kwargs"]["content_settings"].content_type
        == "application/json"
    )
