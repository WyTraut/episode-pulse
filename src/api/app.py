import json
import logging
import os
from functools import lru_cache
from pathlib import Path

from azure.core.exceptions import AzureError, ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobClient, BlobServiceClient
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


CURRENT_TRENDING_BLOB_NAME = "trending/current.json"
RECENT_TRENDING_BLOB_NAME = "trending/recent.json"
STATIC_DIRECTORY = Path(__file__).parent / "static"

logger = logging.getLogger("episodepulse.api")

app = FastAPI(
    title="EpisodePulse API",
    version="1.0.0",
    description="Public read-only API for EpisodePulse dashboard data.",
)

app.mount("/static", StaticFiles(directory=STATIC_DIRECTORY), name="static")


@app.middleware("http")
async def add_security_headers(request: Request, call_next) -> Response:
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "style-src 'self'; "
        "script-src 'self'; "
        "connect-src 'self'; "
        "img-src 'self' data:; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'"
    )
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


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


def _recent_trending_blob_client() -> BlobClient:
    return _blob_service_client().get_blob_client(
        container=_required_setting("SERVING_CONTAINER_NAME"),
        blob=RECENT_TRENDING_BLOB_NAME,
    )


def build_show_history_document(
    current_document: dict,
    history_document: dict,
    trakt_show_id: int,
) -> dict:
    current_show = next(
        (
            show
            for show in current_document.get("shows", [])
            if int(show["trakt_show_id"]) == trakt_show_id
        ),
        None,
    )
    if current_show is None:
        raise KeyError(trakt_show_id)

    points = []
    previous_hash = None

    for snapshot in history_document.get("snapshots", []):
        observation = next(
            (
                show
                for show in snapshot.get("shows", [])
                if int(show["trakt_show_id"]) == trakt_show_id
            ),
            None,
        )
        snapshot_hash = snapshot.get("snapshot_hash")
        points.append(
            {
                "checked_at": snapshot["checked_at"],
                "rank": observation.get("rank") if observation else None,
                "watcher_count": (
                    observation.get("watcher_count") if observation else None
                ),
                "present": observation is not None,
                "source_changed": (
                    snapshot_hash != previous_hash if previous_hash is not None else None
                ),
            }
        )
        previous_hash = snapshot_hash

    return {
        "history_schema_version": history_document.get(
            "history_schema_version", "1.0"
        ),
        "show": {
            "trakt_show_id": current_show["trakt_show_id"],
            "tmdb_show_id": current_show.get("tmdb_show_id"),
            "title": current_show["title"],
            "current_rank": current_show["rank"],
            "rank_change": current_show.get("rank_change"),
            "current_watcher_count": current_show["watcher_count"],
            "watcher_change": current_show.get("watcher_change"),
            "is_new": current_show.get("is_new", False),
        },
        "window": {
            "point_count": len(points),
            "first_checked_at": points[0]["checked_at"] if points else None,
            "last_checked_at": points[-1]["checked_at"] if points else None,
            "expected_interval_minutes": history_document.get(
                "expected_interval_minutes", 5
            ),
        },
        "points": points,
    }


@app.get("/")
def root() -> FileResponse:
    return FileResponse(STATIC_DIRECTORY / "index.html")


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


@app.get("/api/shows/{trakt_show_id}/history")
def show_history(trakt_show_id: int) -> Response:
    """Return six hours of observations for a show in the current collection."""

    try:
        current_document = json.loads(
            _current_trending_blob_client().download_blob().readall()
        )
        history_document = json.loads(
            _recent_trending_blob_client().download_blob().readall()
        )
        document = build_show_history_document(
            current_document=current_document,
            history_document=history_document,
            trakt_show_id=trakt_show_id,
        )
    except KeyError as error:
        raise HTTPException(
            status_code=404,
            detail="The show is not in the current trending collection.",
        ) from error
    except ResourceNotFoundError as error:
        raise HTTPException(
            status_code=503,
            detail="Recent show history is not available yet.",
        ) from error
    except (AzureError, json.JSONDecodeError) as error:
        logger.exception("Unable to read recent history for show %s.", trakt_show_id)
        raise HTTPException(
            status_code=502,
            detail="Recent show history could not be retrieved.",
        ) from error

    return Response(
        content=json.dumps(document, ensure_ascii=False, separators=(",", ":")),
        media_type="application/json",
        headers={"Cache-Control": "public, max-age=60"},
    )
