import json
import logging
import os
import time
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path
from threading import Lock

from azure.core.exceptions import AzureError, ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobClient, BlobServiceClient
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


CURRENT_TRENDING_BLOB_NAME = "trending/current.json"
RECENT_TRENDING_BLOB_NAME = "trending/recent.json"
RECENT_REVIEWS_BLOB_NAME = "reviews/recent.json"
DEFAULT_HISTORY_RETENTION_POINTS = 288
SIX_HOUR_POINTS = 72
API_RATE_LIMIT_REQUESTS = 120
API_RATE_LIMIT_WINDOW_SECONDS = 60
API_RATE_LIMIT_MAX_CLIENTS = 10_000
STATIC_DIRECTORY = Path(__file__).parent / "static"

logger = logging.getLogger("episodepulse.api")

app = FastAPI(
    title="EpisodePulse API",
    version="1.0.0",
    description="Public read-only API for EpisodePulse dashboard data.",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.mount("/static", StaticFiles(directory=STATIC_DIRECTORY), name="static")


class FixedWindowRateLimiter:
    """Bounded, in-process protection for this small public read-only API."""

    def __init__(
        self,
        requests_per_window: int,
        window_seconds: int,
        max_clients: int,
    ) -> None:
        self.requests_per_window = requests_per_window
        self.window_seconds = window_seconds
        self.max_clients = max_clients
        self._clients: OrderedDict[str, tuple[int, int]] = OrderedDict()
        self._lock = Lock()

    def check(self, client_id: str, now: float | None = None) -> tuple[bool, int, int]:
        current_time = time.time() if now is None else now
        window = int(current_time // self.window_seconds)

        with self._lock:
            previous_window, count = self._clients.pop(client_id, (window, 0))
            if previous_window != window:
                count = 0

            if count >= self.requests_per_window:
                self._clients[client_id] = (window, count)
                retry_after = max(
                    1,
                    int((window + 1) * self.window_seconds - current_time) + 1,
                )
                return False, 0, retry_after

            count += 1
            self._clients[client_id] = (window, count)
            while len(self._clients) > self.max_clients:
                self._clients.popitem(last=False)

            return True, self.requests_per_window - count, 0


_api_rate_limiter = FixedWindowRateLimiter(
    requests_per_window=API_RATE_LIMIT_REQUESTS,
    window_seconds=API_RATE_LIMIT_WINDOW_SECONDS,
    max_clients=API_RATE_LIMIT_MAX_CLIENTS,
)


def _client_identifier(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        # App Service appends the address it observed. Use that final hop so a
        # caller cannot bypass throttling by prepending a forged address.
        return forwarded_for.rsplit(",", 1)[-1].strip()
    return request.client.host if request.client else "unknown"


def _add_security_headers(response: Response) -> Response:
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains"
    )
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
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = (
        "camera=(), geolocation=(), microphone=()"
    )
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.middleware("http")
async def add_security_headers(request: Request, call_next) -> Response:
    rate_limit_headers = {}
    if request.url.path.startswith("/api/"):
        allowed, remaining, retry_after = _api_rate_limiter.check(
            _client_identifier(request)
        )
        rate_limit_headers = {
            "X-RateLimit-Limit": str(API_RATE_LIMIT_REQUESTS),
            "X-RateLimit-Remaining": str(remaining),
        }
        if not allowed:
            response = Response(
                content=json.dumps(
                    {"detail": "Too many requests. Try again shortly."},
                    separators=(",", ":"),
                ),
                status_code=429,
                media_type="application/json",
                headers={
                    **rate_limit_headers,
                    "Retry-After": str(retry_after),
                    "Cache-Control": "no-store",
                },
            )
            return _add_security_headers(response)

    response = await call_next(request)
    response.headers.update(rate_limit_headers)
    return _add_security_headers(response)


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


def _recent_reviews_blob_client() -> BlobClient:
    return _blob_service_client().get_blob_client(
        container=_required_setting("SERVING_CONTAINER_NAME"),
        blob=RECENT_REVIEWS_BLOB_NAME,
    )


def enrich_current_with_history(
    current_document: dict,
    history_document: dict,
) -> dict:
    """Add rolling-window trend fields without replacing five-minute deltas."""

    snapshots = sorted(
        history_document.get("snapshots", []),
        key=lambda snapshot: (
            snapshot.get("checked_at", ""),
            snapshot.get("collection_id", ""),
        ),
    )
    current_collection_id = current_document.get("collection_id")

    if current_collection_id and not any(
        snapshot.get("collection_id") == current_collection_id
        for snapshot in snapshots
    ):
        snapshots.append(
            {
                "collection_id": current_collection_id,
                "snapshot_hash": current_document.get("snapshot_hash"),
                "checked_at": current_document.get("checked_at"),
                "shows": [
                    {
                        "trakt_show_id": show["trakt_show_id"],
                        "rank": show["rank"],
                        "watcher_count": show["watcher_count"],
                    }
                    for show in current_document.get("shows", [])
                ],
            }
        )
        snapshots = snapshots[
            -history_document.get(
                "retention_points",
                DEFAULT_HISTORY_RETENTION_POINTS,
            ) :
        ]

    show_points: dict[str, list[dict]] = {}
    snapshot_show_maps = []
    shows_in_first_snapshot = {
        str(show["trakt_show_id"])
        for show in (snapshots[0].get("shows", []) if snapshots else [])
    }

    for snapshot in snapshots:
        shows_by_id = {
            str(show["trakt_show_id"]): show for show in snapshot.get("shows", [])
        }
        snapshot_show_maps.append(shows_by_id)
        for show_id, show in shows_by_id.items():
            show_points.setdefault(show_id, []).append(show)

    def summarize(points: list[dict], current_show: dict) -> dict:
        ranks = [point["rank"] for point in points]
        watchers = [point["watcher_count"] for point in points]
        first_point = points[0] if points else None

        return {
            "rank_change": (
                first_point["rank"] - current_show["rank"]
                if first_point is not None
                else None
            ),
            "watcher_change": (
                current_show["watcher_count"] - first_point["watcher_count"]
                if first_point is not None
                else None
            ),
            "rank_range": max(ranks) - min(ranks) if ranks else None,
            "watcher_range": max(watchers) - min(watchers) if watchers else None,
            "point_count": len(points),
        }

    for show in current_document.get("shows", []):
        show_id = str(show["trakt_show_id"])
        points = show_points.get(show_id, [])
        six_hour_points = [
            shows_by_id[show_id]
            for shows_by_id in snapshot_show_maps[-SIX_HOUR_POINTS:]
            if show_id in shows_by_id
        ]
        window_metrics = summarize(points, show)
        six_hour_metrics = summarize(six_hour_points, show)
        is_new_in_window = bool(snapshots) and show_id not in shows_in_first_snapshot
        rank_change = window_metrics["rank_change"]
        watcher_change = window_metrics["watcher_change"]
        rank_range = window_metrics["rank_range"]
        watcher_range = window_metrics["watcher_range"]

        if is_new_in_window:
            trend_status = "new"
        elif rank_change is None or len(points) < 2:
            trend_status = "baseline"
        elif rank_change > 0:
            trend_status = "up"
        elif rank_change < 0:
            trend_status = "down"
        elif rank_range:
            trend_status = "mixed"
        elif watcher_change and watcher_change > 0:
            trend_status = "gaining"
        elif watcher_change and watcher_change < 0:
            trend_status = "cooling"
        elif watcher_range:
            trend_status = "mixed"
        else:
            trend_status = "steady"

        show.update(
            {
                "rank_change_6h": six_hour_metrics["rank_change"],
                "watcher_change_6h": six_hour_metrics["watcher_change"],
                "rank_range_6h": six_hour_metrics["rank_range"],
                "watcher_range_6h": six_hour_metrics["watcher_range"],
                "rank_change_window": rank_change,
                "watcher_change_window": watcher_change,
                "rank_range_window": rank_range,
                "watcher_range_window": watcher_range,
                "trend_point_count": window_metrics["point_count"],
                "trend_status": trend_status,
                "is_new_in_window": is_new_in_window,
            }
        )

        if show.get("rank", DEFAULT_HISTORY_RETENTION_POINTS) <= 20:
            show["trend_rank_points"] = [
                shows_by_id.get(show_id, {}).get("rank")
                for shows_by_id in snapshot_show_maps
            ]
            show["trend_watcher_points"] = [
                shows_by_id.get(show_id, {}).get("watcher_count")
                for shows_by_id in snapshot_show_maps
            ]

    source_hashes = [snapshot.get("snapshot_hash") for snapshot in snapshots]
    expected_interval_minutes = history_document.get(
        "expected_interval_minutes",
        5,
    )
    retention_points = history_document.get(
        "retention_points",
        DEFAULT_HISTORY_RETENTION_POINTS,
    )
    current_document["trend_window"] = {
        "point_count": len(snapshots),
        "retention_points": retention_points,
        "expected_interval_minutes": expected_interval_minutes,
        "hours": retention_points * expected_interval_minutes / 60,
        "first_checked_at": snapshots[0].get("checked_at") if snapshots else None,
        "last_checked_at": snapshots[-1].get("checked_at") if snapshots else None,
        "source_change_count": sum(
            current_hash != previous_hash
            for previous_hash, current_hash in zip(source_hashes, source_hashes[1:])
        ),
    }
    return current_document


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
            "rank_change_6h": current_show.get("rank_change_6h"),
            "rank_change_window": current_show.get("rank_change_window"),
            "current_watcher_count": current_show["watcher_count"],
            "watcher_change": current_show.get("watcher_change"),
            "watcher_change_6h": current_show.get("watcher_change_6h"),
            "watcher_change_window": current_show.get("watcher_change_window"),
            "rank_range_6h": current_show.get("rank_range_6h"),
            "watcher_range_6h": current_show.get("watcher_range_6h"),
            "rank_range_window": current_show.get("rank_range_window"),
            "watcher_range_window": current_show.get("watcher_range_window"),
            "trend_status": current_show.get("trend_status"),
            "is_new_in_window": current_show.get("is_new_in_window", False),
            "is_new": current_show.get("is_new", False),
        },
        "window": {
            "point_count": len(points),
            "first_checked_at": points[0]["checked_at"] if points else None,
            "last_checked_at": points[-1]["checked_at"] if points else None,
            "expected_interval_minutes": history_document.get(
                "expected_interval_minutes", 5
            ),
            "hours": history_document.get(
                "retention_points",
                DEFAULT_HISTORY_RETENTION_POINTS,
            )
            * history_document.get("expected_interval_minutes", 5)
            / 60,
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
        document = json.loads(
            _current_trending_blob_client().download_blob().readall()
        )
    except ResourceNotFoundError as error:
        raise HTTPException(
            status_code=503,
            detail="Trending data is not available yet.",
        ) from error
    except (AzureError, json.JSONDecodeError) as error:
        logger.exception("Unable to read the current trending projection.")
        raise HTTPException(
            status_code=502,
            detail="Trending data could not be retrieved.",
        ) from error

    try:
        history_document = json.loads(
            _recent_trending_blob_client().download_blob().readall()
        )
        document = enrich_current_with_history(document, history_document)
    except ResourceNotFoundError:
        logger.info("Recent history is not initialized; returning current data only.")
    except (AzureError, json.JSONDecodeError):
        logger.warning(
            "Recent history could not enrich current trends; returning current data only.",
            exc_info=True,
        )

    return Response(
        content=json.dumps(document, ensure_ascii=False, separators=(",", ":")),
        media_type="application/json",
        headers={"Cache-Control": "public, max-age=60"},
    )


@app.get("/api/reviews")
def recent_reviews(limit: int = Query(default=12, ge=1, le=50)) -> Response:
    """Return the newest spoiler-safe Trakt TV review excerpts."""

    try:
        document = json.loads(
            _recent_reviews_blob_client().download_blob().readall()
        )
    except ResourceNotFoundError as error:
        raise HTTPException(
            status_code=503,
            detail="Recent reviews are not available yet.",
        ) from error
    except (AzureError, json.JSONDecodeError) as error:
        logger.exception("Unable to read the recent review projection.")
        raise HTTPException(
            status_code=502,
            detail="Recent reviews could not be retrieved.",
        ) from error

    response_document = {
        **document,
        "returned_count": min(limit, len(document.get("reviews", []))),
        "reviews": document.get("reviews", [])[:limit],
    }
    return Response(
        content=json.dumps(
            response_document,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        media_type="application/json",
        headers={"Cache-Control": "public, max-age=60"},
    )


@app.get("/api/shows/{trakt_show_id}/history")
def show_history(trakt_show_id: int) -> Response:
    """Return 24 hours of observations for a show in the current collection."""

    try:
        current_document = json.loads(
            _current_trending_blob_client().download_blob().readall()
        )
        history_document = json.loads(
            _recent_trending_blob_client().download_blob().readall()
        )
        enriched_current = enrich_current_with_history(
            current_document=current_document,
            history_document=history_document,
        )
        document = build_show_history_document(
            current_document=enriched_current,
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
