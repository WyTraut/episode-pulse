# EpisodePulse API

The App Service API is the public boundary between the dashboard and the private serving container.

## Endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /` | Serves the public EpisodePulse dashboard |
| `GET /health` | Confirms that the web process is running |
| `GET /api/trending` | Returns the latest serving document enriched with six-hour trends |
| `GET /api/shows/{trakt_show_id}/history` | Returns six hours of rank and watcher observations for a current show |

## Security model

- Blob Storage remains private.
- App Service uses its system-assigned managed identity.
- That identity receives `Storage Blob Data Reader` only on the `serving` container.
- No storage account key or connection string is stored in the web application.

The history endpoint returns explicit gaps with `present: false` when a show was outside the trending collection. Its `source_changed` field distinguishes a newly returned Trakt payload from a repeated cached payload.

The trending endpoint preserves the five-minute delta fields and additively joins the rolling history. Each show receives `rank_change_6h`, `watcher_change_6h`, rank/watcher ranges, point count, `trend_status`, and `is_new_in_window`. The top-level `trend_window` reports the observations and genuine source changes used by the dashboard.

## Hosting tiers

The Bicep defaults to the free `F1` App Service tier for development. Change `appServiceSkuName` to `B1` when the public portfolio application needs Always On and dedicated compute.
