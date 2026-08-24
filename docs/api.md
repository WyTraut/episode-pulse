# EpisodePulse API

The App Service API is the public boundary between the dashboard and the private serving container.

## Endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /` | Serves the public EpisodePulse dashboard |
| `GET /health` | Confirms that the web process is running |
| `GET /api/trending` | Returns the latest serving document enriched with 24-hour trends and compact sparklines |
| `GET /api/reviews?limit=12` | Returns up to 50 of the newest spoiler-safe Trakt TV review excerpts |
| `GET /api/shows/{trakt_show_id}/history` | Returns 24 hours of rank and watcher observations for a current show |

## Security model

- Blob Storage remains private.
- App Service uses its system-assigned managed identity.
- That identity receives `Storage Blob Data Reader` only on the `serving` container.
- No storage account key or connection string is stored in the web application.
- HTTP is redirected to HTTPS and successful/error responses include HSTS, a restrictive Content Security Policy, browser capability restrictions, and MIME-sniffing protection.
- Public API endpoints are limited to 120 requests per client per minute. Rate-limited responses return `429`, `Retry-After`, and `Cache-Control: no-store`.
- FastAPI's generated `/docs`, `/redoc`, and `/openapi.json` endpoints are disabled on the public application. Maintained API documentation lives in this repository.
- SCM and FTP basic publishing credentials are disabled. Azure deployments require Microsoft Entra authorization, and the SCM endpoint accepts traffic only from the Azure service network.
- Direct local deployments additionally require the operator's current public `/32` CIDR through the `scmDeploymentClientIpCidr` Bicep parameter. The value belongs in deployment parameters, not source control.
- App Service HTTP, console, application, authentication, audit, IP security, platform, and metric telemetry is sent to the existing Log Analytics workspace.

The history endpoint returns explicit gaps with `present: false` when a show was outside the trending collection. Its `source_changed` field distinguishes a newly returned Trakt payload from a repeated cached payload.

The review endpoint reads the deduplicated `reviews/recent.json` serving projection. It returns public reviewer attribution, show identifiers, ratings, timestamps, and short excerpts. Review text flagged as a spoiler is never copied into the public projection. Successful responses are cached for 60 seconds; missing projections return `503` and storage failures return `502`.

The trending endpoint preserves the five-minute and legacy six-hour delta fields while additively joining the full rolling window. Current top-20 shows receive compact rank/watcher point arrays for sparklines plus window-level change, range, point count, `trend_status`, and `is_new_in_window`. The top-level `trend_window` reports the hours, observations, and genuine source changes used by the dashboard.

## Hosting tiers

The Bicep defaults to the free `F1` App Service tier for development. Change `appServiceSkuName` to `B1` when the public portfolio application needs Always On and dedicated compute.
