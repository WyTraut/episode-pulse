import logging
import os
from functools import lru_cache

from azure.core.exceptions import AzureError, ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobClient, BlobServiceClient
from fastapi import FastAPI, HTTPException, Response


CURRENT_TRENDING_BLOB_NAME = "trending/current.json"

logger = logging.getLogger("episodepulse.api")

app = FastAPI(
    title="EpisodePulse API",
    version="1.0.0",
    description="Public read-only API for EpisodePulse dashboard data.",
)


def _required_setting(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Required application setting {name} is missing.")
    return value


@lru_cache
def _blob_service_client() -> BlobServiceClient:
    account_name = _required_setting("DATA_STORAGE_ACCOUNT_NAME")
    account_url = f"https://{account_name}.blob.core.windows.net"

    return BlobServiceClient(
        account_url=account_url,
        credential=DefaultAzureCredential(),
    )


def _current_trending_blob_client() -> BlobClient:
    return _blob_service_client().get_blob_client(
        container=_required_setting("SERVING_CONTAINER_NAME"),
        blob=CURRENT_TRENDING_BLOB_NAME,
    )


@app.get("/")
def root() -> dict[str, str]:
    return {
        "service": "EpisodePulse API",
        "trending_endpoint": "/api/trending",
        "health_endpoint": "/health",
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/trending")
def current_trending() -> Response:
    """Return the latest compact projection while the source blob stays private."""

    try:
        document = _current_trending_blob_client().download_blob().readall()
    except ResourceNotFoundError as error:
        raise HTTPException(
            status_code=503,
            detail="Trending data is not available yet.",
        ) from error
    except AzureError as error:
        logger.exception("Unable to read the current trending projection.")
        raise HTTPException(
            status_code=502,
            detail="Trending data could not be retrieved.",
        ) from error

    return Response(
        content=document,
        media_type="application/json",
        headers={"Cache-Control": "public, max-age=60"},
    )
