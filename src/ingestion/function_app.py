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

app = func.FunctionApp()


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

    response = requests.get(
        "https://api.trakt.tv/shows/trending",
        params={"limit": 10},
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
        "schema_version": "1.0",
        "metric_type": "trending_24h",
        "source_timestamp": response.headers.get("Last-Modified"),
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "ingested_at": ingested_at.isoformat().replace("+00:00", "Z"),
        "payload": trending_shows,
    }

    storage_account_name = os.environ["DATA_STORAGE_ACCOUNT_NAME"]
    container_name = os.environ["RAW_CONTAINER_NAME"]
    account_url = f"https://{storage_account_name}.blob.core.windows.net"

    blob_service = BlobServiceClient(
        account_url=account_url,
        credential=credential,
    )

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
