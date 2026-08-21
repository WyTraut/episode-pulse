from typing import Any
from uuid import NAMESPACE_URL, uuid5


def transform_trending_snapshot(
    snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    """Convert one raw Trakt snapshot into clean observation records."""

    if snapshot["metric_type"] != "trending_24h":
        raise ValueError("Snapshot has an unsupported metric type.")

    collection_id = snapshot["collection_id"]
    observations = []

    for rank, item in enumerate(snapshot["payload"], start=1):
        show = item["show"]
        trakt_show_id = show["ids"]["trakt"]
        watcher_count = item["watchers"]

        if trakt_show_id <= 0:
            raise ValueError("Trakt show ID must be positive.")

        if watcher_count < 0:
            raise ValueError("Watcher count cannot be negative.")

        event_key = (
            f"episodepulse:{collection_id}:"
            f"trending_24h:{trakt_show_id}"
        )

        observation = {
            "event_id": str(uuid5(NAMESPACE_URL, event_key)),
            "collection_id": collection_id,
            "schema_version": snapshot["schema_version"],
            "metric_type": "trending_24h",
            "trakt_show_id": trakt_show_id,
            "tmdb_show_id": show["ids"].get("tmdb"),
            "title": show["title"],
            "watcher_count": watcher_count,
            "rank": rank,
            "source_timestamp": snapshot.get("source_timestamp"),
            "observed_at": snapshot["observed_at"],
            "ingested_at": snapshot["ingested_at"],
        }

        observations.append(observation)

    return observations
