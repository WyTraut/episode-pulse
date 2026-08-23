from datetime import datetime, timezone

from backfill_history import build_history_from_snapshots, hourly_prefixes
from transform import calculate_snapshot_hash


def make_raw_snapshot(collection_id: str, observed_at: str) -> dict:
    payload = [
        {
            "watchers": 1200,
            "show": {
                "title": "First Show",
                "ids": {"trakt": 101, "tmdb": 1001},
            },
        }
    ]
    return {
        "collection_id": collection_id,
        "collection_size": 1,
        "snapshot_hash": calculate_snapshot_hash(payload),
        "schema_version": "1.1",
        "metric_type": "trending_24h",
        "source_timestamp": None,
        "observed_at": observed_at,
        "ingested_at": observed_at,
        "payload": payload,
    }


def test_hourly_prefixes_cross_date_boundaries() -> None:
    prefixes = hourly_prefixes(
        datetime(2026, 8, 22, 23, 30, tzinfo=timezone.utc),
        datetime(2026, 8, 23, 1, 5, tzinfo=timezone.utc),
    )

    assert prefixes == [
        "trakt/trending/year=2026/month=08/day=22/hour=23/",
        "trakt/trending/year=2026/month=08/day=23/hour=00/",
        "trakt/trending/year=2026/month=08/day=23/hour=01/",
    ]


def test_backfill_builder_is_idempotent() -> None:
    snapshots = [
        make_raw_snapshot("collection-1", "2026-08-23T02:55:00Z"),
        make_raw_snapshot("collection-2", "2026-08-23T03:00:00Z"),
    ]

    first = build_history_from_snapshots(snapshots)
    second = build_history_from_snapshots(snapshots, previous_document=first)

    assert len(first["snapshots"]) == 2
    assert second == first
