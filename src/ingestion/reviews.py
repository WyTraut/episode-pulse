import json
import re
from typing import Any

from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import BlobServiceClient, ContentSettings


RECENT_REVIEWS_BLOB_NAME = "reviews/recent.json"
REVIEW_RETENTION_COUNT = 100
REVIEW_EXCERPT_LENGTH = 320


def _excerpt(text: str, maximum_length: int = REVIEW_EXCERPT_LENGTH) -> str:
    """Return a compact single-line excerpt without cutting a word when possible."""

    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= maximum_length:
        return compact

    shortened = compact[: maximum_length - 1].rsplit(" ", 1)[0].rstrip()
    return f"{shortened or compact[: maximum_length - 1].rstrip()}…"


def normalize_recent_reviews(payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Create the privacy-conscious review records used by the public feed."""

    reviews = []

    for item in payload:
        if item.get("type") != "show":
            continue

        comment = item.get("comment") or {}
        show = item.get("show") or {}
        show_ids = show.get("ids") or {}
        user = comment.get("user") or {}
        review_id = comment.get("id")
        trakt_show_id = show_ids.get("trakt")
        text = comment.get("comment")

        if comment.get("review") is not True:
            continue
        if not isinstance(review_id, int) or isinstance(review_id, bool) or review_id <= 0:
            raise ValueError("Trakt review ID must be a positive integer.")
        if (
            not isinstance(trakt_show_id, int)
            or isinstance(trakt_show_id, bool)
            or trakt_show_id <= 0
        ):
            raise ValueError("Trakt show ID must be a positive integer.")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Trakt review text must be present.")
        if not comment.get("created_at"):
            raise ValueError("Trakt review creation time must be present.")

        spoiler = bool(comment.get("spoiler"))
        username = user.get("username")
        display_name = user.get("name") or username or "Trakt member"

        reviews.append(
            {
                "review_id": review_id,
                "created_at": comment["created_at"],
                "updated_at": comment.get("updated_at"),
                "spoiler": spoiler,
                "language": comment.get("language"),
                "rating": comment.get("user_rating"),
                "likes": comment.get("likes", 0),
                "excerpt": None if spoiler else _excerpt(text),
                "reviewer": {
                    "display_name": display_name,
                    "username": username,
                },
                "show": {
                    "trakt_show_id": trakt_show_id,
                    "tmdb_show_id": show_ids.get("tmdb"),
                    "title": show.get("title") or "Untitled show",
                    "year": show.get("year"),
                },
                "url": f"https://trakt.tv/comments/{review_id}",
            }
        )

    return reviews


def build_recent_reviews_document(
    snapshot: dict[str, Any],
    previous_document: dict[str, Any] | None = None,
    retention_count: int = REVIEW_RETENTION_COUNT,
) -> dict[str, Any]:
    """Merge one Trakt response into a deduplicated rolling review feed."""

    if snapshot.get("metric_type") != "recent_show_reviews":
        raise ValueError("Review snapshot has an unsupported metric type.")

    payload = snapshot.get("payload")
    if not isinstance(payload, list):
        raise ValueError("Review snapshot payload must be a list.")
    if snapshot.get("collection_size") != len(payload):
        raise ValueError("Review collection size does not match the payload length.")

    incoming_reviews = normalize_recent_reviews(payload)
    previous_reviews = (previous_document or {}).get("reviews", [])
    previous_ids = {review.get("review_id") for review in previous_reviews}
    reviews_by_id = {
        review["review_id"]: review
        for review in previous_reviews
        if isinstance(review.get("review_id"), int)
    }

    for review in incoming_reviews:
        reviews_by_id[review["review_id"]] = review

    reviews = sorted(
        reviews_by_id.values(),
        key=lambda review: (review.get("created_at") or "", review["review_id"]),
        reverse=True,
    )[:retention_count]

    return {
        "serving_schema_version": "1.0",
        "metric_type": "recent_show_reviews",
        "checked_at": snapshot["observed_at"],
        "source_timestamp": snapshot.get("source_timestamp"),
        "latest_review_at": reviews[0]["created_at"] if reviews else None,
        "retention_count": retention_count,
        "new_review_count": sum(
            review["review_id"] not in previous_ids for review in incoming_reviews
        ),
        "review_count": len(reviews),
        "reviews": reviews,
    }


def write_recent_reviews(
    blob_service_client: BlobServiceClient,
    container_name: str,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Replace the public review projection while preserving prior review IDs."""

    blob_client = blob_service_client.get_blob_client(
        container=container_name,
        blob=RECENT_REVIEWS_BLOB_NAME,
    )
    previous_document = None

    try:
        previous_document = json.loads(blob_client.download_blob().readall())
    except ResourceNotFoundError:
        pass

    serving_document = build_recent_reviews_document(
        snapshot=snapshot,
        previous_document=previous_document,
    )
    blob_client.upload_blob(
        json.dumps(serving_document, ensure_ascii=False, separators=(",", ":")),
        overwrite=True,
        content_settings=ContentSettings(
            content_type="application/json",
            cache_control="no-cache",
        ),
    )
    return serving_document
