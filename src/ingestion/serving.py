import json
from typing import Any

from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import BlobServiceClient, ContentSettings


CURRENT_TRENDING_BLOB_NAME = "trending/current.json"


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

    shows = [
        {
            "rank": observation["rank"],
            "trakt_show_id": observation["trakt_show_id"],
            "tmdb_show_id": observation["tmdb_show_id"],
            "title": observation["title"],
            "watcher_count": observation["watcher_count"],
        }
        for observation in sorted(
            observations,
            key=lambda item: item["rank"],
        )
    ]

    return {
        "serving_schema_version": "1.0",
        "observation_schema_version": snapshot["schema_version"],
        "collection_id": snapshot["collection_id"],
        "collection_size": snapshot["collection_size"],
        "snapshot_hash": snapshot["snapshot_hash"],
        "metric_type": snapshot["metric_type"],
        "source_timestamp": snapshot.get("source_timestamp"),
        "checked_at": checked_at,
        "changed_at": changed_at,
        "published_at": snapshot["ingested_at"],
        "shows": shows,
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
