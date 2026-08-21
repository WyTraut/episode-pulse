# Observation Data Contract

Status: Draft

Contract version: 1.0

## Purpose

One observation represents one television show from one Trakt API collection. Observations preserve what EpisodePulse knew at a specific time so changes can be calculated later.

## Fields

| Field | Meaning | Required |
| --- | --- | --- |
| `event_id` | Unique identifier for this observation | Yes |
| `collection_id` | Identifier shared by every observation created from the same API response | Yes |
| `schema_version` | Version of this contract used to create the observation | Yes |
| `metric_type` | Either `trending_24h` or `current_watchers` | Yes |
| `trakt_show_id` | Stable Trakt identifier for the show | Yes |
| `tmdb_show_id` | TMDB identifier used for metadata enrichment | No |
| `title` | Show title returned by Trakt | Yes |
| `watcher_count` | Non-negative watcher count for the selected metric | Yes |
| `rank` | Position in the trending response | Only for `trending_24h` |
| `source_timestamp` | Trakt's `Last-Modified` timestamp, when provided | No |
| `observed_at` | UTC time when the collector received the API response | Yes |
| `ingested_at` | UTC time when the event entered the cloud ingestion platform | Yes |

## Metric definitions

### `trending_24h`

The watcher count returned by Trakt's trending-shows endpoint for its rolling 24-hour period. The count can rise or fall as the rolling window changes. Rank is required.

### `current_watchers`

The number of users returned by Trakt's watching-now endpoint at collection time. Rank is not applicable.

The collector must count the response in memory and immediately discard all member identities. Raw watching-now responses must never be logged, stored, or published.

## Timestamp definitions

- `source_timestamp` describes when Trakt last modified the source response.
- `observed_at` describes when EpisodePulse received the response.
- `ingested_at` describes when the observation entered the cloud data platform.

All timestamps must use UTC. Keeping these timestamps separate allows EpisodePulse to measure source freshness and ingestion delay without presenting cached data as newly created data.

## Validation rules

- `event_id` must be unique.
- `collection_id` must be identical for observations from the same API response.
- `watcher_count` must be zero or greater.
- `trakt_show_id` must be present and greater than zero.
- `rank` must be greater than zero for `trending_24h` and empty for `current_watchers`.
- Invalid observations must be rejected or quarantined rather than silently corrected.

## Versioning

Compatible additions may use a new minor version. Removing a field, changing a field's meaning, or changing a required field requires a new major version.
