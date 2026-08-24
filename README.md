# EpisodePulse

EpisodePulse is a cloud-based television attention observatory. It captures changing viewing signals from the Trakt community, enriches them with television metadata, and shows which programs are gaining or losing momentum.

The project has two goals:

1. Build and operate an end-to-end cloud data platform using Azure and Microsoft Fabric.
2. Demonstrate practical data engineering skills while preparing for the Microsoft DP-700 certification.

## 1. What problem does the application solve?

Most television discovery and review products emphasize static ratings, reviews, and recommendation lists. Those views do not clearly explain how audience attention is changing over time.

EpisodePulse will preserve a history of frequently collected viewing signals and turn changes between observations into useful events. This will make it possible to identify accelerating shows, release-driven spikes, unexpected resurgences, and differences between short-term momentum and longer-term popularity.

## 2. Who would use it?

The initial audience is television fans who want to understand what is attracting attention now rather than only what has the highest historical rating.

The project is also intended for data engineers and hiring managers evaluating the design, implementation, operation, and documentation of a cloud data platform.

## 3. What continuously changing data will it collect?

The first version will collect timestamped snapshots of Trakt television activity, including:

- Trending shows and their watcher counts
- Users currently watching selected shows, stored only as aggregate counts
- Daily, weekly, and monthly watched-show statistics
- Show and episode metadata used to interpret the activity

The pipeline will compare each observation with previous observations and create derived events such as rank changes, watcher-count changes, momentum spikes, and newly trending shows.

TMDB metadata will enrich the activity with information such as titles, genres, release dates, episode information, and artwork references.

## 4. What questions should the dashboard answer?

1. Which shows are gaining or losing attention right now?
2. Which premieres, finales, or older titles are producing the largest changes in viewing activity?
3. How does a show's recent momentum compare with its daily, weekly, and longer-term popularity?

## 5. What does the data not represent?

EpisodePulse does not represent the complete worldwide television audience. Trakt activity reflects the behavior of Trakt users who make their viewing activity available through the platform.

The data is not official viewership information from Netflix, Hulu, Disney+, broadcasters, or other streaming providers. Results must therefore be described as **Trakt viewing activity**, not total audience measurements.

The initial pipeline will collect API snapshots rather than receive a complete provider-owned event stream. Derived events describe changes observed between snapshots and should not be presented as exact causal explanations for viewer behavior.

## Initial MVP

The first usable version will:

- Collect a small, controlled set of Trakt television endpoints on a schedule
- Preserve every raw response with collection timestamps
- Validate and deduplicate incoming observations
- Produce historical tables and current momentum calculations
- Display top gaining, top declining, newly trending, and unexpectedly resurfacing shows
- Include monitoring for ingestion failures, stale data, and malformed records

## Initial non-goals

The first version will not:

- Recommend what an individual user should watch
- Scrape Letterboxd, Serializd, streaming services, or review websites
- Store or display identifiable Trakt user activity
- Claim to measure total worldwide viewership
- Perform review-text sentiment analysis
- Support commercial usage or high-volume public traffic

## Current cloud architecture

The running flow is:

1. Trakt provides the source television activity data.
2. Azure Functions collects and timestamps a 200-show snapshot every five minutes.
3. Private Azure Blob Storage preserves raw responses and a compact current-state serving projection.
4. Azure Event Hubs buffers normalized observations.
5. Microsoft Fabric Eventstream routes the observations into Eventhouse.
6. Fabric Eventhouse and a Real-Time Dashboard support current-state, momentum, and pipeline-health analysis.
7. An HTTPS-only Azure App Service API uses managed identity to read the private serving projection for the future public dashboard.

The live dashboard is available at [app-epulse-dev-wt2026.azurewebsites.net](https://app-epulse-dev-wt2026.azurewebsites.net). Its same-origin read-only API and security model are described in [docs/api.md](docs/api.md).

The next serving milestone is the browser dashboard. A OneLake Lakehouse and medallion layers remain planned DP-700 extensions rather than completed components.

Infrastructure, application code, data contracts, tests, and deployment workflows will be maintained in this repository.
