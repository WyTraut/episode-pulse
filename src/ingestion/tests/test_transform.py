from uuid import UUID

import pytest

from transform import transform_trending_snapshot


@pytest.fixture
def trending_snapshot() -> dict:
    return {
        "collection_id": "collection-123",
        "schema_version": "1.0",
        "metric_type": "trending_24h",
        "source_timestamp": "Fri, 21 Aug 2026 04:00:00 GMT",
        "observed_at": "2026-08-21T04:05:00Z",
        "ingested_at": "2026-08-21T04:05:01Z",
        "payload": [
            {
                "watchers": 1200,
                "show": {
                    "title": "First Show",
                    "ids": {
                        "trakt": 101,
                        "tmdb": 1001,
                    },
                },
            },
            {
                "watchers": 900,
                "show": {
                    "title": "Second Show",
                    "ids": {
                        "trakt": 202,
                    },
                },
            },
        ],
    }


def test_transforms_snapshot_into_ranked_observations(
    trending_snapshot: dict,
) -> None:
    observations = transform_trending_snapshot(trending_snapshot)

    assert len(observations) == 2
    assert observations[0] == {
        "event_id": observations[0]["event_id"],
        "collection_id": "collection-123",
        "schema_version": "1.0",
        "metric_type": "trending_24h",
        "trakt_show_id": 101,
        "tmdb_show_id": 1001,
        "title": "First Show",
        "watcher_count": 1200,
        "rank": 1,
        "source_timestamp": "Fri, 21 Aug 2026 04:00:00 GMT",
        "observed_at": "2026-08-21T04:05:00Z",
        "ingested_at": "2026-08-21T04:05:01Z",
    }
    assert observations[1]["rank"] == 2
    assert observations[1]["tmdb_show_id"] is None
    UUID(observations[0]["event_id"])


def test_event_ids_are_deterministic(trending_snapshot: dict) -> None:
    first_run = transform_trending_snapshot(trending_snapshot)
    second_run = transform_trending_snapshot(trending_snapshot)

    assert [item["event_id"] for item in first_run] == [
        item["event_id"] for item in second_run
    ]


def test_rejects_negative_watcher_count(trending_snapshot: dict) -> None:
    trending_snapshot["payload"][0]["watchers"] = -1

    with pytest.raises(ValueError, match="Watcher count cannot be negative"):
        transform_trending_snapshot(trending_snapshot)


def test_rejects_unsupported_metric_type(trending_snapshot: dict) -> None:
    trending_snapshot["metric_type"] = "current_watchers"

    with pytest.raises(ValueError, match="unsupported metric type"):
        transform_trending_snapshot(trending_snapshot)
