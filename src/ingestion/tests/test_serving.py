import json

import pytest
from azure.core.exceptions import ResourceNotFoundError

from serving import (
    build_current_trending_document,
    build_recent_trending_document,
    write_current_trending,
    write_recent_trending,
)


def make_snapshot(
    snapshot_hash: str = "a" * 64,
    collection_id: str = "collection-123",
    observed_at: str = "2026-08-23T03:00:00Z",
) -> dict:
    return {
        "collection_id": collection_id,
        "collection_size": 1,
        "snapshot_hash": snapshot_hash,
        "schema_version": "1.1",
        "metric_type": "trending_24h",
        "source_timestamp": None,
        "observed_at": observed_at,
        "ingested_at": "2026-08-23T03:00:01Z",
    }


def make_observations() -> list[dict]:
    return [
        {
            "rank": 1,
            "trakt_show_id": 101,
            "tmdb_show_id": 1001,
            "title": "First Show",
            "watcher_count": 1200,
        }
    ]


def test_builds_compact_current_trending_document() -> None:
    document = build_current_trending_document(
        snapshot=make_snapshot(),
        observations=make_observations(),
    )

    assert document["collection_id"] == "collection-123"
    assert document["serving_schema_version"] == "1.1"
    assert document["checked_at"] == "2026-08-23T03:00:00Z"
    assert document["changed_at"] == "2026-08-23T03:00:00Z"
    assert document["shows"] == [
        {
            "rank": 1,
            "previous_rank": None,
            "rank_change": None,
            "trakt_show_id": 101,
            "tmdb_show_id": 1001,
            "title": "First Show",
            "watcher_count": 1200,
            "previous_watcher_count": None,
            "watcher_change": None,
            "is_new": True,
        }
    ]


def test_preserves_changed_at_when_payload_is_repeated() -> None:
    previous_document = {
        "snapshot_hash": "a" * 64,
        "changed_at": "2026-08-23T02:30:00Z",
        "checked_at": "2026-08-23T02:55:00Z",
        "shows": make_observations(),
    }

    document = build_current_trending_document(
        snapshot=make_snapshot(),
        observations=make_observations(),
        previous_document=previous_document,
    )

    assert document["changed_at"] == "2026-08-23T02:30:00Z"
    assert document["shows"][0]["rank_change"] == 0
    assert document["shows"][0]["watcher_change"] == 0
    assert document["shows"][0]["is_new"] is False


def test_resets_changed_at_when_payload_changes() -> None:
    previous_document = {
        "snapshot_hash": "b" * 64,
        "changed_at": "2026-08-23T02:30:00Z",
        "checked_at": "2026-08-23T02:55:00Z",
        "shows": make_observations(),
    }

    document = build_current_trending_document(
        snapshot=make_snapshot(),
        observations=make_observations(),
        previous_document=previous_document,
    )

    assert document["changed_at"] == "2026-08-23T03:00:00Z"


def test_calculates_positive_rank_and_watcher_changes() -> None:
    previous_document = {
        "snapshot_hash": "b" * 64,
        "changed_at": "2026-08-23T02:55:00Z",
        "checked_at": "2026-08-23T02:55:00Z",
        "shows": [
            {
                "trakt_show_id": 101,
                "rank": 4,
                "watcher_count": 1100,
            }
        ],
    }

    document = build_current_trending_document(
        snapshot=make_snapshot(),
        observations=make_observations(),
        previous_document=previous_document,
    )

    assert document["previous_checked_at"] == "2026-08-23T02:55:00Z"
    assert document["shows"][0]["previous_rank"] == 4
    assert document["shows"][0]["rank_change"] == 3
    assert document["shows"][0]["previous_watcher_count"] == 1100
    assert document["shows"][0]["watcher_change"] == 100


def test_orders_serving_shows_by_rank() -> None:
    observations = make_observations()
    observations.append(
        {
            "rank": 2,
            "trakt_show_id": 202,
            "tmdb_show_id": None,
            "title": "Second Show",
            "watcher_count": 900,
        }
    )
    observations.reverse()
    snapshot = make_snapshot()
    snapshot["collection_size"] = 2

    document = build_current_trending_document(
        snapshot=snapshot,
        observations=observations,
    )

    assert [show["rank"] for show in document["shows"]] == [1, 2]


def test_rejects_incomplete_serving_collection() -> None:
    snapshot = make_snapshot()
    snapshot["collection_size"] = 2

    with pytest.raises(ValueError, match="do not match"):
        build_current_trending_document(
            snapshot=snapshot,
            observations=make_observations(),
        )


def test_recent_history_keeps_repeated_hashes_from_distinct_collections() -> None:
    first = build_recent_trending_document(
        snapshot=make_snapshot(
            collection_id="collection-1",
            observed_at="2026-08-23T02:55:00Z",
        ),
        observations=make_observations(),
    )
    second = build_recent_trending_document(
        snapshot=make_snapshot(
            collection_id="collection-2",
            observed_at="2026-08-23T03:00:00Z",
        ),
        observations=make_observations(),
        previous_document=first,
    )

    assert len(second["snapshots"]) == 2
    assert second["snapshots"][0]["snapshot_hash"] == "a" * 64
    assert second["snapshots"][1]["snapshot_hash"] == "a" * 64


def test_recent_history_ignores_duplicate_collection_ids() -> None:
    snapshot = make_snapshot(collection_id="same-collection")
    first = build_recent_trending_document(snapshot, make_observations())
    second = build_recent_trending_document(
        snapshot,
        make_observations(),
        previous_document=first,
    )

    assert len(second["snapshots"]) == 1


def test_recent_history_orders_and_caps_collections() -> None:
    history = None
    for index in reversed(range(75)):
        history = build_recent_trending_document(
            snapshot=make_snapshot(
                collection_id=f"collection-{index:02d}",
                observed_at=f"2026-08-23T{index // 12:02d}:{(index % 12) * 5:02d}:00Z",
            ),
            observations=make_observations(),
            previous_document=history,
        )

    assert len(history["snapshots"]) == 72
    assert history["snapshots"][0]["collection_id"] == "collection-03"
    assert history["snapshots"][-1]["collection_id"] == "collection-74"


class FakeDownload:
    def __init__(self, document: dict | None) -> None:
        self.document = document

    def readall(self) -> bytes:
        if self.document is None:
            raise ResourceNotFoundError("Blob does not exist.")

        return json.dumps(self.document).encode("utf-8")


class FakeBlobClient:
    def __init__(self, previous_document: dict | None = None) -> None:
        self.previous_document = previous_document
        self.upload = None

    def download_blob(self) -> FakeDownload:
        return FakeDownload(self.previous_document)

    def upload_blob(self, data: str, **kwargs) -> None:
        self.upload = {
            "document": json.loads(data),
            "kwargs": kwargs,
        }


class FakeBlobServiceClient:
    def __init__(self, blob_client: FakeBlobClient) -> None:
        self.blob_client = blob_client
        self.request = None

    def get_blob_client(self, **kwargs) -> FakeBlobClient:
        self.request = kwargs
        return self.blob_client


def test_writes_current_trending_blob() -> None:
    blob_client = FakeBlobClient()
    blob_service_client = FakeBlobServiceClient(blob_client)

    document = write_current_trending(
        blob_service_client=blob_service_client,
        container_name="serving",
        snapshot=make_snapshot(),
        observations=make_observations(),
    )

    assert blob_service_client.request == {
        "container": "serving",
        "blob": "trending/current.json",
    }
    assert blob_client.upload["document"] == document
    assert blob_client.upload["kwargs"]["overwrite"] is True
    assert blob_client.upload["kwargs"]["content_settings"].content_type == (
        "application/json"
    )


def test_writes_recent_trending_blob() -> None:
    blob_client = FakeBlobClient()
    blob_service_client = FakeBlobServiceClient(blob_client)

    document = write_recent_trending(
        blob_service_client=blob_service_client,
        container_name="serving",
        snapshot=make_snapshot(),
        observations=make_observations(),
    )

    assert blob_service_client.request == {
        "container": "serving",
        "blob": "trending/recent.json",
    }
    assert blob_client.upload["document"] == document
    assert len(document["snapshots"]) == 1
