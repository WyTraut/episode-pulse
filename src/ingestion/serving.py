import json
from typing import Any

from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import BlobServiceClient, ContentSettings


CURRENT_TRENDING_BLOB_NAME = "trending/current.json"
RECENT_TRENDING_BLOB_NAME = "trending/recent.json"
HISTORY_RETENTION_POINTS = 72


def build_current_trending_document(
    snapshot: dict[str, Any],
    observations: list[dict[str, Any]],
    previous_document: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the compact document consumed by the public dashboard."""

    if len(observations) != snapshot["collection_size"]:
        raise ValueError("Serving observations do not match the collection size.")

    checked_at = snapshot["observed_at"]
    changed_at = checked_at

    if (
        previous_document
        and previous_document.get("snapshot_hash") == snapshot["snapshot_hash"]
    ):
        changed_at = previous_document.get("changed_at", checked_at)

    previous_shows = {
        str(show["trakt_show_id"]): show
        for show in (previous_document or {}).get("shows", [])
    }
    shows = []

    for observation in sorted(observations, key=lambda item: item["rank"]):
        previous_show = previous_shows.get(str(observation["trakt_show_id"]))
        previous_rank = previous_show.get("rank") if previous_show else None
        previous_watcher_count = (
            previous_show.get("watcher_count") if previous_show else None
        )

        shows.append(
            {
                "rank": observation["rank"],
                "previous_rank": previous_rank,
                "rank_change": (
                    previous_rank - observation["rank"]
                    if previous_rank is not None
                    else None
                ),
                "trakt_show_id": observation["trakt_show_id"],
                "tmdb_show_id": observation["tmdb_show_id"],
                "title": observation["title"],
                "watcher_count": observation["watcher_count"],
                "previous_watcher_count": previous_watcher_count,
                "watcher_change": (
                    observation["watcher_count"] - previous_watcher_count
                    if previous_watcher_count is not None
                    else None
                ),
                "is_new": previous_show is None,
            }
        )

    return {
        "serving_schema_version": "1.1",
        "observation_schema_version": snapshot["schema_version"],
        "collection_id": snapshot["collection_id"],
        "collection_size": snapshot["collection_size"],
        "snapshot_hash": snapshot["snapshot_hash"],
        "metric_type": snapshot["metric_type"],
        "source_timestamp": snapshot.get("source_timestamp"),
        "checked_at": checked_at,
        "previous_checked_at": (
            previous_document.get("checked_at") if previous_document else None
        ),
        "changed_at": changed_at,
        "published_at": snapshot["ingested_at"],
        "shows": shows,
    }


def build_recent_trending_document(
    snapshot: dict[str, Any],
    observations: list[dict[str, Any]],
    previous_document: dict[str, Any] | None = None,
    retention_points: int = HISTORY_RETENTION_POINTS,
) -> dict[str, Any]:
    """Append one collection to the compact rolling dashboard history."""

    if len(observations) != snapshot["collection_size"]:
        raise ValueError("History observations do not match the collection size.")

    snapshots = list((previous_document or {}).get("snapshots", []))
    collection_id = snapshot["collection_id"]

    if not any(item.get("collection_id") == collection_id for item in snapshots):
        snapshots.append(
            {
                "collection_id": collection_id,
                "snapshot_hash": snapshot["snapshot_hash"],
                "checked_at": snapshot["observed_at"],
                "shows": [
                    {
                        "trakt_show_id": observation["trakt_show_id"],
                        "rank": observation["rank"],
                        "watcher_count": observation["watcher_count"],
                    }
                    for observation in sorted(
                        observations,
                        key=lambda item: item["rank"],
                    )
                ],
            }
        )

    snapshots.sort(key=lambda item: (item["checked_at"], item["collection_id"]))
    snapshots = snapshots[-retention_points:]

    return {
        "history_schema_version": "1.0",
        "observation_schema_version": snapshot["schema_version"],
        "retention_points": retention_points,
        "expected_interval_minutes": 5,
        "updated_at": snapshots[-1]["checked_at"] if snapshots else None,
        "snapshots": snapshots,
    }


def write_current_trending(
    blob_service_client: BlobServiceClient,
    container_name: str,
    snapshot: dict[str, Any],
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Replace the dashboard's current trending document in Blob Storage."""

    blob_client = blob_service_client.get_blob_client(
        container=container_name,
        blob=CURRENT_TRENDING_BLOB_NAME,
    )

    previous_document = None

    try:
        previous_document = json.loads(blob_client.download_blob().readall())
    except ResourceNotFoundError:
        pass

    serving_document = build_current_trending_document(
        snapshot=snapshot,
        observations=observations,
        previous_document=previous_document,
    )

    blob_client.upload_blob(
        json.dumps(
            serving_document,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        overwrite=True,
        content_settings=ContentSettings(
            content_type="application/json",
            cache_control="no-cache",
        ),
    )

    return serving_document


def write_recent_trending(
    blob_service_client: BlobServiceClient,
    container_name: str,
    snapshot: dict[str, Any],
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Append a collection to the rolling dashboard history in Blob Storage."""

    blob_client = blob_service_client.get_blob_client(
        container=container_name,
        blob=RECENT_TRENDING_BLOB_NAME,
    )

    previous_document = None

    try:
        previous_document = json.loads(blob_client.download_blob().readall())
    except ResourceNotFoundError:
        pass

    history_document = build_recent_trending_document(
        snapshot=snapshot,
        observations=observations,
        previous_document=previous_document,
    )

    blob_client.upload_blob(
        json.dumps(
            history_document,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        overwrite=True,
        content_settings=ContentSettings(
            content_type="application/json",
            cache_control="no-cache",
        ),
    )

    return history_document
