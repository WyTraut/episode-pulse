import json

from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from fastapi.testclient import TestClient

import app as api_module


client = TestClient(api_module.app)


class FakeDownload:
    def __init__(self, payload: bytes | None = None, error: Exception | None = None):
        self.payload = payload
        self.error = error

    def readall(self) -> bytes:
        if self.error:
            raise self.error
        return self.payload or b""


class FakeBlobClient:
    def __init__(self, download: FakeDownload):
        self.download = download

    def download_blob(self) -> FakeDownload:
        return self.download


def test_health_endpoint() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_serves_dashboard() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "TV attention." in response.text
    assert "Shows drawing the most attention." in response.text
    assert "Reviews arriving now." in response.text
    assert 'class="page-third intro-third"' in response.text
    assert 'class="page-third signal-third"' in response.text
    assert 'class="page-third archive-third"' in response.text
    assert '<dialog class="show-drawer"' in response.text
    assert '<canvas id="history-chart"' in response.text
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["strict-transport-security"] == (
        "max-age=31536000; includeSubDomains"
    )
    assert response.headers["cross-origin-opener-policy"] == "same-origin"
    assert response.headers["permissions-policy"] == (
        "camera=(), geolocation=(), microphone=()"
    )


def test_generated_api_documentation_is_not_public() -> None:
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_static_dashboard_assets_are_available() -> None:
    stylesheet = client.get("/static/styles.css")
    javascript = client.get("/static/dashboard.js")

    assert stylesheet.status_code == 200
    assert javascript.status_code == 200
    assert 'fetch("/api/trending"' in javascript.text
    assert 'fetch("/api/reviews?limit=6"' in javascript.text
    assert "`/api/shows/${showId}/history`" in javascript.text
    assert "createTrendSparkline" in javascript.text
    assert "smoothSparklinePoints" in javascript.text
    assert "show.trend_watcher_points" in javascript.text
    assert ".trend-sparkline:hover .trend-tooltip" in stylesheet.text
    assert "createSignal" not in javascript.text


def test_returns_current_trending_document(monkeypatch) -> None:
    document = {
        "serving_schema_version": "1.0",
        "collection_size": 1,
        "shows": [{"rank": 1, "title": "Silo"}],
    }
    fake_blob_client = FakeBlobClient(
        FakeDownload(payload=json.dumps(document).encode("utf-8"))
    )
    monkeypatch.setattr(
        api_module,
        "_current_trending_blob_client",
        lambda: fake_blob_client,
    )
    monkeypatch.setattr(
        api_module,
        "_recent_trending_blob_client",
        lambda: FakeBlobClient(
            FakeDownload(error=ResourceNotFoundError("Missing"))
        ),
    )

    response = client.get("/api/trending")

    assert response.status_code == 200
    assert response.json() == document
    assert response.headers["cache-control"] == "public, max-age=60"


def make_reviews_document() -> dict:
    return {
        "serving_schema_version": "1.0",
        "metric_type": "recent_show_reviews",
        "checked_at": "2026-08-23T12:00:00Z",
        "new_review_count": 1,
        "review_count": 2,
        "reviews": [
            {"review_id": 2, "excerpt": "Newest review"},
            {"review_id": 1, "excerpt": "Older review"},
        ],
    }


def test_returns_limited_recent_reviews(monkeypatch) -> None:
    monkeypatch.setattr(
        api_module,
        "_recent_reviews_blob_client",
        lambda: FakeBlobClient(
            FakeDownload(payload=json.dumps(make_reviews_document()).encode())
        ),
    )

    response = client.get("/api/reviews?limit=1")

    assert response.status_code == 200
    assert response.json()["returned_count"] == 1
    assert response.json()["review_count"] == 2
    assert response.json()["reviews"] == [
        {"review_id": 2, "excerpt": "Newest review"}
    ]
    assert response.headers["cache-control"] == "public, max-age=60"


def test_recent_reviews_rejects_invalid_limit() -> None:
    response = client.get("/api/reviews?limit=51")

    assert response.status_code == 422


def test_recent_reviews_returns_service_unavailable_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        api_module,
        "_recent_reviews_blob_client",
        lambda: FakeBlobClient(
            FakeDownload(error=ResourceNotFoundError("Missing"))
        ),
    )

    response = client.get("/api/reviews")

    assert response.status_code == 503
    assert response.json() == {"detail": "Recent reviews are not available yet."}


def test_recent_reviews_returns_bad_gateway_on_storage_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        api_module,
        "_recent_reviews_blob_client",
        lambda: FakeBlobClient(
            FakeDownload(error=HttpResponseError(message="Storage failed"))
        ),
    )

    response = client.get("/api/reviews")

    assert response.status_code == 502
    assert response.json() == {"detail": "Recent reviews could not be retrieved."}


def test_api_rate_limit_returns_retryable_response(monkeypatch) -> None:
    monkeypatch.setattr(
        api_module,
        "_api_rate_limiter",
        api_module.FixedWindowRateLimiter(
            requests_per_window=2,
            window_seconds=60,
            max_clients=10,
        ),
    )
    monkeypatch.setattr(
        api_module,
        "_recent_reviews_blob_client",
        lambda: FakeBlobClient(
            FakeDownload(payload=json.dumps(make_reviews_document()).encode())
        ),
    )
    first_headers = {"X-Forwarded-For": "198.51.100.1, 203.0.113.10"}
    second_headers = {"X-Forwarded-For": "198.51.100.2, 203.0.113.10"}

    assert client.get("/api/reviews", headers=first_headers).status_code == 200
    assert client.get("/api/reviews", headers=second_headers).status_code == 200
    response = client.get("/api/reviews", headers=second_headers)

    assert response.status_code == 429
    assert response.json() == {"detail": "Too many requests. Try again shortly."}
    assert response.headers["retry-after"]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["strict-transport-security"]


def make_current_document() -> dict:
    return {
        "serving_schema_version": "1.1",
        "shows": [
            {
                "trakt_show_id": 101,
                "tmdb_show_id": 1001,
                "title": "Silo",
                "rank": 2,
                "rank_change": 1,
                "watcher_count": 1200,
                "watcher_change": 100,
                "is_new": False,
            }
        ],
    }


def make_history_document() -> dict:
    return {
        "history_schema_version": "1.0",
        "expected_interval_minutes": 5,
        "snapshots": [
            {
                "collection_id": "one",
                "snapshot_hash": "a" * 64,
                "checked_at": "2026-08-23T02:50:00Z",
                "shows": [
                    {"trakt_show_id": 101, "rank": 3, "watcher_count": 1100}
                ],
            },
            {
                "collection_id": "two",
                "snapshot_hash": "a" * 64,
                "checked_at": "2026-08-23T02:55:00Z",
                "shows": [],
            },
            {
                "collection_id": "three",
                "snapshot_hash": "b" * 64,
                "checked_at": "2026-08-23T03:00:00Z",
                "shows": [
                    {"trakt_show_id": 101, "rank": 2, "watcher_count": 1200}
                ],
            },
        ],
    }


def patch_history_clients(monkeypatch, current_download, history_download) -> None:
    monkeypatch.setattr(
        api_module,
        "_current_trending_blob_client",
        lambda: FakeBlobClient(current_download),
    )
    monkeypatch.setattr(
        api_module,
        "_recent_trending_blob_client",
        lambda: FakeBlobClient(history_download),
    )


def test_returns_show_history_with_explicit_gaps(monkeypatch) -> None:
    patch_history_clients(
        monkeypatch,
        FakeDownload(payload=json.dumps(make_current_document()).encode()),
        FakeDownload(payload=json.dumps(make_history_document()).encode()),
    )

    response = client.get("/api/shows/101/history")

    assert response.status_code == 200
    document = response.json()
    assert document["show"]["title"] == "Silo"
    assert document["show"]["rank_change"] == 1
    assert document["show"]["rank_change_6h"] == 1
    assert document["show"]["watcher_change_6h"] == 100
    assert document["show"]["rank_change_window"] == 1
    assert document["show"]["watcher_change_window"] == 100
    assert document["show"]["trend_status"] == "up"
    assert document["window"]["point_count"] == 3
    assert document["points"][0]["source_changed"] is None
    assert document["points"][1] == {
        "checked_at": "2026-08-23T02:55:00Z",
        "rank": None,
        "watcher_count": None,
        "present": False,
        "source_changed": False,
    }
    assert document["points"][2]["source_changed"] is True
    assert response.headers["cache-control"] == "public, max-age=60"


def test_enriches_current_shows_from_the_full_history_window() -> None:
    current = {
        "collection_id": "three",
        "checked_at": "2026-08-23T03:00:00Z",
        "snapshot_hash": "c" * 64,
        "shows": [
            {"trakt_show_id": 1, "rank": 2, "watcher_count": 150},
            {"trakt_show_id": 2, "rank": 5, "watcher_count": 150},
            {"trakt_show_id": 3, "rank": 3, "watcher_count": 150},
            {"trakt_show_id": 4, "rank": 1, "watcher_count": 200},
            {"trakt_show_id": 5, "rank": 8, "watcher_count": 80},
            {"trakt_show_id": 6, "rank": 6, "watcher_count": 60},
        ],
    }
    history = {
        "retention_points": 72,
        "snapshots": [
            {
                "collection_id": "one",
                "snapshot_hash": "a" * 64,
                "checked_at": "2026-08-23T02:50:00Z",
                "shows": [
                    {"trakt_show_id": 1, "rank": 5, "watcher_count": 100},
                    {"trakt_show_id": 2, "rank": 2, "watcher_count": 200},
                    {"trakt_show_id": 3, "rank": 3, "watcher_count": 150},
                    {"trakt_show_id": 4, "rank": 1, "watcher_count": 100},
                    {"trakt_show_id": 6, "rank": 6, "watcher_count": 60},
                ],
            },
            {
                "collection_id": "two",
                "snapshot_hash": "b" * 64,
                "checked_at": "2026-08-23T02:55:00Z",
                "shows": [
                    {"trakt_show_id": 1, "rank": 3, "watcher_count": 125},
                    {"trakt_show_id": 2, "rank": 4, "watcher_count": 175},
                    {"trakt_show_id": 3, "rank": 1, "watcher_count": 175},
                    {"trakt_show_id": 4, "rank": 1, "watcher_count": 150},
                    {"trakt_show_id": 5, "rank": 10, "watcher_count": 50},
                    {"trakt_show_id": 6, "rank": 6, "watcher_count": 60},
                ],
            },
            {
                "collection_id": "three",
                "snapshot_hash": "c" * 64,
                "checked_at": "2026-08-23T03:00:00Z",
                "shows": current["shows"],
            },
        ],
    }

    document = api_module.enrich_current_with_history(current, history)
    shows = {show["trakt_show_id"]: show for show in document["shows"]}

    assert shows[1]["trend_status"] == "up"
    assert shows[1]["rank_change_6h"] == 3
    assert shows[1]["watcher_change_6h"] == 50
    assert shows[1]["rank_change_window"] == 3
    assert shows[1]["trend_rank_points"] == [5, 3, 2]
    assert shows[1]["trend_watcher_points"] == [100, 125, 150]
    assert shows[2]["trend_status"] == "down"
    assert shows[2]["rank_change_6h"] == -3
    assert shows[3]["trend_status"] == "mixed"
    assert shows[3]["rank_range_6h"] == 2
    assert shows[4]["trend_status"] == "gaining"
    assert shows[4]["watcher_change_6h"] == 100
    assert shows[5]["trend_status"] == "new"
    assert shows[5]["is_new_in_window"] is True
    assert shows[6]["trend_status"] == "steady"
    assert document["trend_window"] == {
        "point_count": 3,
        "retention_points": 72,
        "expected_interval_minutes": 5,
        "hours": 6.0,
        "first_checked_at": "2026-08-23T02:50:00Z",
        "last_checked_at": "2026-08-23T03:00:00Z",
        "source_change_count": 2,
    }


def test_show_history_returns_not_found_for_unknown_current_show(monkeypatch) -> None:
    patch_history_clients(
        monkeypatch,
        FakeDownload(payload=json.dumps(make_current_document()).encode()),
        FakeDownload(payload=json.dumps(make_history_document()).encode()),
    )

    response = client.get("/api/shows/999/history")

    assert response.status_code == 404


def test_show_history_returns_service_unavailable_when_history_is_missing(
    monkeypatch,
) -> None:
    patch_history_clients(
        monkeypatch,
        FakeDownload(payload=json.dumps(make_current_document()).encode()),
        FakeDownload(error=ResourceNotFoundError("Missing")),
    )

    response = client.get("/api/shows/101/history")

    assert response.status_code == 503


def test_show_history_returns_bad_gateway_when_storage_fails(monkeypatch) -> None:
    patch_history_clients(
        monkeypatch,
        FakeDownload(payload=json.dumps(make_current_document()).encode()),
        FakeDownload(error=HttpResponseError(message="Storage failed")),
    )

    response = client.get("/api/shows/101/history")

    assert response.status_code == 502


def test_returns_service_unavailable_when_projection_is_missing(monkeypatch) -> None:
    fake_blob_client = FakeBlobClient(
        FakeDownload(error=ResourceNotFoundError("Missing"))
    )
    monkeypatch.setattr(
        api_module,
        "_current_trending_blob_client",
        lambda: fake_blob_client,
    )

    response = client.get("/api/trending")

    assert response.status_code == 503
    assert response.json() == {"detail": "Trending data is not available yet."}


def test_returns_bad_gateway_when_storage_fails(monkeypatch) -> None:
    fake_blob_client = FakeBlobClient(
        FakeDownload(error=HttpResponseError(message="Storage failed"))
    )
    monkeypatch.setattr(
        api_module,
        "_current_trending_blob_client",
        lambda: fake_blob_client,
    )

    response = client.get("/api/trending")

    assert response.status_code == 502
    assert response.json() == {"detail": "Trending data could not be retrieved."}
