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

`serving/trending/recent.json` retains the latest 72 collections, representing approximately six hours at the expected five-minute interval. Each history snapshot contains `collection_id`, `snapshot_hash`, `checked_at`, and compact show measurements containing `trakt_show_id`, `rank`, and `watcher_count`.

Repeated source hashes remain as separate collections so flat periods honestly show that EpisodePulse checked the source and received unchanged data. Repeated collection IDs are ignored.

## Validation rules

- `collection_size` must equal the number of items in `shows`.
- Shows must be ordered by ascending `rank`.
- `checked_at` updates after every successful API collection.
- `changed_at` changes only when `snapshot_hash` changes.
- History must remain chronologically ordered and contain at most 72 collections.
- The document must remain private and must not contain Trakt user identities or credentials.
