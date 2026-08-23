import json
import logging
import os
import uuid
from datetime import datetime, timezone

import azure.functions as func
import requests
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from azure.storage.blob import BlobServiceClient, ContentSettings

from publisher import publish_observations
from reviews import write_recent_reviews
from serving import write_current_trending, write_recent_trending
from transform import calculate_snapshot_hash, transform_trending_snapshot

app = func.FunctionApp()


def _collect_recent_reviews(
    trakt_client_id: str,
    blob_service: BlobServiceClient,
    raw_container_name: str,
    serving_container_name: str,
) -> None:
    """Collect and project recent TV reviews independently of trending data."""

    response = requests.get(
        "https://api.trakt.tv/comments/recent/reviews/shows",
        params={"limit": 50},
        headers={
            "trakt-api-key": trakt_client_id,
            "trakt-api-version": "2",
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    response.raise_for_status()

    observed_at = datetime.now(timezone.utc)
    ingested_at = datetime.now(timezone.utc)
    payload = response.json()
    collection_id = str(uuid.uuid4())
    snapshot = {
        "collection_id": collection_id,
        "collection_size": len(payload),
        "snapshot_hash": calculate_snapshot_hash(payload),
        "schema_version": "1.0",
        "metric_type": "recent_show_reviews",
        "source_timestamp": response.headers.get("Date"),
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "ingested_at": ingested_at.isoformat().replace("+00:00", "Z"),
        "payload": payload,
    }
    blob_name = (
        f"trakt/reviews/year={observed_at:%Y}/month={observed_at:%m}/"
        f"day={observed_at:%d}/hour={observed_at:%H}/"
        f"{observed_at:%Y%m%dT%H%M%S.%fZ}_{collection_id}.json"
    )
    blob_service.get_blob_client(
        container=raw_container_name,
        blob=blob_name,
    ).upload_blob(
        json.dumps(snapshot, ensure_ascii=False),
        overwrite=False,
        content_settings=ContentSettings(content_type="application/json"),
    )
    serving_document = write_recent_reviews(
        blob_service_client=blob_service,
        container_name=serving_container_name,
        snapshot=snapshot,
    )
    logging.info(
        "Stored %d recent Trakt reviews; %d were new to the serving feed.",
        serving_document["review_count"],
        serving_document["new_review_count"],
    )


@app.timer_trigger(
    schedule="0 */5 * * * *",
    arg_name="timer",
    run_on_startup=False,
    use_monitor=True,
)
def collect_trakt(timer: func.TimerRequest) -> None:
    if timer.past_due:
        logging.warning("The timer is past due.")

    key_vault_uri = os.environ["KEY_VAULT_URI"]
    secret_name = os.environ["TRAKT_CLIENT_ID_SECRET_NAME"]

    credential = DefaultAzureCredential()
    secret_client = SecretClient(
        vault_url=key_vault_uri,
        credential=credential,
    )

    trakt_client_id = secret_client.get_secret(secret_name).value

    logging.info("Trakt client ID retrieved securely.")

    storage_account_name = os.environ["DATA_STORAGE_ACCOUNT_NAME"]
    container_name = os.environ["RAW_CONTAINER_NAME"]
    account_url = f"https://{storage_account_name}.blob.core.windows.net"
    blob_service = BlobServiceClient(
        account_url=account_url,
        credential=credential,
    )

    try:
        _collect_recent_reviews(
            trakt_client_id=trakt_client_id,
            blob_service=blob_service,
            raw_container_name=container_name,
            serving_container_name=os.environ["SERVING_CONTAINER_NAME"],
        )
    except Exception:
        logging.exception(
            "Failed to collect recent Trakt reviews; trending ingestion will continue."
        )

    response = requests.get(
        "https://api.trakt.tv/shows/trending",
        params={"limit": 200},
        headers={
            "trakt-api-key": trakt_client_id,
            "trakt-api-version": "2",
            "Content-Type": "application/json",
        },
        timeout=30,
    )

    response.raise_for_status()
    observed_at = datetime.now(timezone.utc)
    trending_shows = response.json()

    logging.info("Retrieved %d trending shows from Trakt.", len(trending_shows))

    collection_id = str(uuid.uuid4())
    ingested_at = datetime.now(timezone.utc)

    snapshot = {
        "collection_id": collection_id,
        "collection_size": len(trending_shows),
        "snapshot_hash": calculate_snapshot_hash(trending_shows),
        "schema_version": "1.1",
        "metric_type": "trending_24h",
        "source_timestamp": response.headers.get("Last-Modified"),
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "ingested_at": ingested_at.isoformat().replace("+00:00", "Z"),
        "payload": trending_shows,
    }

    blob_name = (
        f"trakt/trending/year={observed_at:%Y}/month={observed_at:%m}/"
        f"day={observed_at:%d}/hour={observed_at:%H}/"
        f"{observed_at:%Y%m%dT%H%M%S.%fZ}_{collection_id}.json"
    )

    blob_client = blob_service.get_blob_client(
        container=container_name,
        blob=blob_name,
    )
    blob_client.upload_blob(
        json.dumps(snapshot, ensure_ascii=False),
        overwrite=False,
        content_settings=ContentSettings(content_type="application/json"),
    )

    logging.info("Stored raw Trakt snapshot at %s.", blob_name)

    observations = transform_trending_snapshot(snapshot)

    logging.info(
        "Transformed raw snapshot into %d clean observations.",
        len(observations),
    )

    published_count = publish_observations(
        observations=observations,
        fully_qualified_namespace=os.environ[
            "EVENT_HUB_FULLY_QUALIFIED_NAMESPACE"
        ],
        event_hub_name=os.environ["EVENT_HUB_NAME"],
        credential=credential,
    )

    logging.info(
        "Published %d observations to Azure Event Hubs.",
        published_count,
    )

    try:
        serving_document = write_current_trending(
            blob_service_client=blob_service,
            container_name=os.environ["SERVING_CONTAINER_NAME"],
            snapshot=snapshot,
            observations=observations,
        )
        logging.info(
            "Updated dashboard serving data for collection %s.",
            serving_document["collection_id"],
        )
    except Exception:
        logging.exception(
            "Failed to update current dashboard data; analytics ingestion succeeded."
        )

    try:
        history_document = write_recent_trending(
            blob_service_client=blob_service,
            container_name=os.environ["SERVING_CONTAINER_NAME"],
            snapshot=snapshot,
            observations=observations,
        )
        logging.info(
            "Updated dashboard history with %d collections.",
            len(history_document["snapshots"]),
        )
    except Exception:
        logging.exception(
            "Failed to update dashboard history; analytics ingestion succeeded."
        )
