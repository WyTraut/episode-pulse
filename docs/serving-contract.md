# Dashboard Serving Contract

Status: Draft

Contract version: 1.0

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
| `changed_at` | UTC time EpisodePulse first observed this payload hash |
| `published_at` | UTC time the collection entered the cloud pipeline |
| `shows` | Rank-ordered list of current show measurements |

## Show fields

Each item in `shows` contains `rank`, `trakt_show_id`, `tmdb_show_id`, `title`, and `watcher_count`.

## Validation rules

- `collection_size` must equal the number of items in `shows`.
- Shows must be ordered by ascending `rank`.
- `checked_at` updates after every successful API collection.
- `changed_at` changes only when `snapshot_hash` changes.
- The document must remain private and must not contain Trakt user identities or credentials.
