# Dashboard Serving Contract

Status: Draft

Contract version: 1.1

## Purpose

The serving layer exposes a compact current-state document for the public EpisodePulse dashboard. It is stored privately at `serving/trending/current.json` and can be read by trusted applications using Azure identity.

## Top-level fields

| Field | Meaning |
| --- | --- |
| `serving_schema_version` | Version of this serving contract |
| `observation_schema_version` | Version of the source observation contract |
| `collection_id` | Identifier of the most recent API collection |
| `collection_size` | Expected number of shows in the document |
| `snapshot_hash` | SHA-256 fingerprint of the source API payload |
| `metric_type` | Metric represented by the watcher count |
| `source_timestamp` | Trakt's source timestamp, when provided |
| `checked_at` | Latest UTC time EpisodePulse checked Trakt |
| `previous_checked_at` | UTC time of the preceding serving collection, when available |
| `changed_at` | UTC time EpisodePulse first observed this payload hash |
| `published_at` | UTC time the collection entered the cloud pipeline |
| `shows` | Rank-ordered list of current show measurements |

## Show fields

Each item in `shows` contains the current identifiers, title, rank, and watcher count plus `previous_rank`, `rank_change`, `previous_watcher_count`, `watcher_change`, and `is_new`.

Positive `rank_change` means the show moved upward. `watcher_change` is the current count minus the preceding count. Both values are `null` when the show was absent from the preceding collection.

## Recent history document

`serving/trending/recent.json` retains the latest 288 collections, representing approximately 24 hours at the expected five-minute interval. Each history snapshot contains `collection_id`, `snapshot_hash`, `checked_at`, and compact show measurements containing `trakt_show_id`, `rank`, and `watcher_count`.

Repeated source hashes remain as separate collections so flat periods honestly show that EpisodePulse checked the source and received unchanged data. Repeated collection IDs are ignored.

The public API joins this history to the current document at read time. This keeps the original five-minute and six-hour fields backward compatible while exposing full-window net change, movement range, observation count, trend status, and top-20 sparkline points.

## Recent review document

`serving/reviews/recent.json` retains the latest 100 unique TV reviews returned by Trakt's recently-created review endpoint. Review IDs are the deduplication key. A repeated review updates its public metadata without creating a second feed item, and reviews are ordered by descending `created_at`.

Each review contains its Trakt review ID and URL, creation/update timestamps, spoiler and language flags, rating and like count, public reviewer name/username, and show identifiers. Non-spoiler text is normalized and limited to a 320-character excerpt. Spoiler text remains only in immutable private raw storage and is represented as `excerpt: null` in this document.

The top-level document records `checked_at`, `latest_review_at`, `new_review_count`, `review_count`, and the configured retention count. Collection failures are isolated from the trending pipeline.

## Validation rules

- `collection_size` must equal the number of items in `shows`.
- Shows must be ordered by ascending `rank`.
- `checked_at` updates after every successful API collection.
- `changed_at` changes only when `snapshot_hash` changes.
- History must remain chronologically ordered and contain at most 288 collections.
- The document must remain private and must not contain Trakt user identities or credentials.
- Review IDs must be positive and unique in the recent-review document.
- Public review excerpts must not exceed 320 characters or expose spoiler text.
- Credentials and nonessential Trakt profile fields must never enter the review serving projection.
