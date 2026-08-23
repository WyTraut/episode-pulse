import hashlib
import json
import re
from typing import Any
from uuid import NAMESPACE_URL, uuid5


def calculate_snapshot_hash(payload: Any) -> str:
    """Return a deterministic SHA-256 hash for a JSON-compatible payload."""

    canonical_payload = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(canonical_payload).hexdigest()


def transform_trending_snapshot(
    snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    """Convert one raw Trakt snapshot into clean observation records."""

    if snapshot["metric_type"] != "trending_24h":
        raise ValueError("Snapshot has an unsupported metric type.")

    payload = snapshot["payload"]
    collection_id = snapshot["collection_id"]
    collection_size = snapshot["collection_size"]
    snapshot_hash = snapshot["snapshot_hash"]

    if (
        not isinstance(collection_size, int)
        or isinstance(collection_size, bool)
        or collection_size <= 0
    ):
        raise ValueError("Collection size must be a positive integer.")

    if collection_size != len(payload):
        raise ValueError("Collection size does not match the payload length.")

    if not isinstance(snapshot_hash, str) or not re.fullmatch(
        r"[0-9a-f]{64}", snapshot_hash
    ):
        raise ValueError("Snapshot hash must be a lowercase SHA-256 value.")

    observations = []

    for rank, item in enumerate(payload, start=1):
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
            "collection_size": collection_size,
            "snapshot_hash": snapshot_hash,
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

    if snapshot_hash != calculate_snapshot_hash(payload):
        raise ValueError("Snapshot hash does not match the payload.")

    return observations
