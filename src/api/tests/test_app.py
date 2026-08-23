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

    response = client.get("/api/trending")

    assert response.status_code == 200
    assert response.json() == document
    assert response.headers["cache-control"] == "public, max-age=60"


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
