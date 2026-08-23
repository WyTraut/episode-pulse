"""Build the six-hour public serving history from immutable raw snapshots."""

import argparse
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings

from serving import (
    RECENT_TRENDING_BLOB_NAME,
    build_recent_trending_document,
)
from transform import transform_trending_snapshot


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def hourly_prefixes(start: datetime, end: datetime) -> list[str]:
    current = start.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    end_hour = end.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    prefixes = []

    while current <= end_hour:
        prefixes.append(
            f"trakt/trending/year={current:%Y}/month={current:%m}/"
            f"day={current:%d}/hour={current:%H}/"
        )
        current += timedelta(hours=1)

    return prefixes


def build_history_from_snapshots(
    snapshots: Iterable[dict[str, Any]],
    previous_document: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    history_document = previous_document

    for snapshot in sorted(
        snapshots,
        key=lambda item: (item["observed_at"], item["collection_id"]),
    ):
        history_document = build_recent_trending_document(
            snapshot=snapshot,
            observations=transform_trending_snapshot(snapshot),
            previous_document=history_document,
        )

    return history_document


def backfill(
    account_name: str,
    raw_container_name: str,
    serving_container_name: str,
    hours: int,
) -> dict[str, Any]:
    credential = DefaultAzureCredential()
    blob_service = BlobServiceClient(
        account_url=f"https://{account_name}.blob.core.windows.net",
        credential=credential,
    )
    raw_container = blob_service.get_container_client(raw_container_name)
    history_blob = blob_service.get_blob_client(
        container=serving_container_name,
        blob=RECENT_TRENDING_BLOB_NAME,
    )

    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)
    snapshots_by_collection: dict[str, dict[str, Any]] = {}

    for prefix in hourly_prefixes(start, end):
        for blob in raw_container.list_blobs(name_starts_with=prefix):
            snapshot = json.loads(
                raw_container.get_blob_client(blob.name).download_blob().readall()
            )
            observed_at = parse_utc(snapshot["observed_at"])
            if start <= observed_at <= end:
                snapshots_by_collection[snapshot["collection_id"]] = snapshot

    existing_document = None
    try:
        existing_document = json.loads(history_blob.download_blob().readall())
    except ResourceNotFoundError:
        pass

    history_document = build_history_from_snapshots(
        snapshots_by_collection.values(),
        previous_document=existing_document,
    )
    if history_document is None:
        raise RuntimeError("No raw snapshots were found in the requested window.")

    history_blob.upload_blob(
        json.dumps(history_document, ensure_ascii=False, separators=(",", ":")),
        overwrite=True,
        content_settings=ContentSettings(
            content_type="application/json",
            cache_control="no-cache",
        ),
    )

    return history_document


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account-name", required=True)
    parser.add_argument("--raw-container", default="raw")
    parser.add_argument("--serving-container", default="serving")
    parser.add_argument("--hours", type=int, default=6)
    args = parser.parse_args()

    document = backfill(
        account_name=args.account_name,
        raw_container_name=args.raw_container,
        serving_container_name=args.serving_container,
        hours=args.hours,
    )
    print(
        json.dumps(
            {
                "snapshots": len(document["snapshots"]),
                "first_checked_at": document["snapshots"][0]["checked_at"],
                "last_checked_at": document["snapshots"][-1]["checked_at"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
