# EpisodePulse API

The App Service API is the public boundary between the dashboard and the private serving container.

## Endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /` | Serves the public EpisodePulse dashboard |
| `GET /health` | Confirms that the web process is running |
| `GET /api/trending` | Returns the latest `trending/current.json` serving document |
| `GET /api/shows/{trakt_show_id}/history` | Returns six hours of rank and watcher observations for a current show |

## Security model

- Blob Storage remains private.
- App Service uses its system-assigned managed identity.
- That identity receives `Storage Blob Data Reader` only on the `serving` container.
- No storage account key or connection string is stored in the web application.

The history endpoint returns explicit gaps with `present: false` when a show was outside the trending collection. Its `source_changed` field distinguishes a newly returned Trakt payload from a repeated cached payload.

## Hosting tiers

The Bicep defaults to the free `F1` App Service tier for development. Change `appServiceSkuName` to `B1` when the public portfolio application needs Always On and dedicated compute.
