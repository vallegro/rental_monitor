# Rental Listing Monitor Plan

## Problem and approach

Build a service that monitors rental listings for configured ZIP codes, detects meaningful changes, and emails a concise summary to the user. The recommended approach is a modular pipeline:

1. Load configuration and credentials.
2. Query a listing data source on a schedule.
3. Normalize listings into an internal schema.
4. Compare the latest snapshot with stored state.
5. Produce a summary of new, changed, and removed listings.
6. Send the summary by email and record delivery results.

Important assumption: direct Zillow scraping may be unreliable or restricted by terms of service, so the ingestion layer should be designed as a provider adapter. Start with a compliant source if available, and keep Zillow-specific logic isolated behind an interface.

## Proposed technology choice

Use Python for the first version:

- strong HTTP, parsing, scheduling, and email libraries
- simple local or server deployment
- easy packaging as a cron job or long-running worker

Recommended runtime options:

- local machine + cron for a personal setup
- small VPS/container if it must run continuously

## Modules to build

### 1. `config`

Responsibility:
- Load app settings from environment variables and a config file.
- Validate ZIP codes, filter criteria, polling interval, and email settings.

Inputs:
- `.env`
- `config.yaml` or `config.json`

Outputs:
- typed `AppConfig`

Public interface:
```python
class AppConfig(TypedDict):
    provider: str
    zip_codes: list[str]
    filters: dict[str, object]
    poll_interval_minutes: int
    email: dict[str, str]
    database_url: str

def load_config() -> AppConfig: ...
```

### 2. `provider_contracts`

Responsibility:
- Define the common interface every listing source must implement.
- Keep the rest of the system independent from Zillow-specific details.

Inputs:
- `SearchRequest`

Outputs:
- raw or normalized listing candidates

Public interface:
```python
class SearchRequest(TypedDict):
    zip_code: str
    min_rent: int | None
    max_rent: int | None
    beds: int | None
    baths: float | None
    property_types: list[str]

class ProviderListing(TypedDict):
    external_id: str
    url: str
    address: str
    zip_code: str
    rent: int | None
    beds: float | None
    baths: float | None
    sqft: int | None
    listed_at: str | None
    provider_payload: dict[str, object]

class ListingProvider(Protocol):
    def search(self, request: SearchRequest) -> list[ProviderListing]: ...
```

### 3. `providers.zillow` or `providers.<source>`

Responsibility:
- Implement source-specific fetch logic.
- Handle pagination, throttling, retries, headers, and source-specific parsing.

Inputs:
- `SearchRequest`

Outputs:
- `list[ProviderListing]`

Public interface:
```python
class ZillowProvider(ListingProvider):
    def __init__(self, http_client: HttpClient): ...
    def search(self, request: SearchRequest) -> list[ProviderListing]: ...
```

Notes:
- This module should be the only place that knows Zillow request/response details.
- If Zillow is not viable, swap in another provider without changing downstream modules.

### 4. `http_client`

Responsibility:
- Centralize outbound HTTP behavior.
- Provide retry, timeout, backoff, rate limiting, and user-agent configuration.

Inputs:
- URL, method, headers, params

Outputs:
- response body / parsed JSON / error

Public interface:
```python
class HttpClient(Protocol):
    def get_json(self, url: str, *, params: dict[str, object] | None = None,
                 headers: dict[str, str] | None = None) -> dict[str, object]: ...
    def get_text(self, url: str, *, params: dict[str, object] | None = None,
                 headers: dict[str, str] | None = None) -> str: ...
```

### 5. `normalizer`

Responsibility:
- Convert provider-specific records into a canonical internal listing schema.
- Standardize addresses, money values, URLs, timestamps, and IDs.

Inputs:
- `ProviderListing`

Outputs:
- `CanonicalListing`

Public interface:
```python
class CanonicalListing(TypedDict):
    listing_id: str
    source: str
    source_listing_id: str
    url: str
    address: str
    zip_code: str
    rent: int | None
    beds: float | None
    baths: float | None
    sqft: int | None
    status: str
    first_seen_at: str | None
    seen_at: str
    fingerprint: str
    raw: dict[str, object]

def normalize_listing(source: str, item: ProviderListing) -> CanonicalListing: ...
```

### 6. `filters`

Responsibility:
- Apply user-defined selection rules after normalization.
- Separate provider search capability from local business rules.

Inputs:
- `CanonicalListing`
- filter settings

Outputs:
- keep/drop decision and optional reason

Public interface:
```python
def matches_filters(listing: CanonicalListing, filters: dict[str, object]) -> bool: ...
```

### 7. `storage`

Responsibility:
- Persist current listings, snapshot history, and notification history.
- Support dedupe and change detection.

Inputs:
- canonical listings
- run metadata
- delivery metadata

Outputs:
- saved records
- prior state for comparison

Recommended schema:
- `listings`
- `listing_snapshots`
- `runs`
- `notifications`

Public interface:
```python
class ListingRepository(Protocol):
    def get_active_by_zip(self, zip_code: str) -> list[CanonicalListing]: ...
    def upsert_listing(self, listing: CanonicalListing) -> None: ...
    def mark_missing(self, source: str, active_ids: set[str], zip_code: str) -> None: ...
    def record_run(self, run_info: dict[str, object]) -> str: ...
    def record_notification(self, payload: dict[str, object]) -> None: ...
```

### 8. `diff_engine`

Responsibility:
- Compare current normalized listings with previously stored state.
- Detect new listings, price changes, returned listings, and removals.

Inputs:
- current listing set
- previous listing set

Outputs:
- `DiffResult`

Public interface:
```python
class DiffResult(TypedDict):
    new: list[CanonicalListing]
    changed: list[dict[str, object]]
    removed: list[CanonicalListing]
    unchanged: list[CanonicalListing]

def diff_listings(previous: list[CanonicalListing],
                  current: list[CanonicalListing]) -> DiffResult: ...
```

### 9. `summary`

Responsibility:
- Turn diffs into a human-readable digest.
- Keep summaries short, scannable, and useful.

Inputs:
- `DiffResult`
- run metadata

Outputs:
- subject line
- plain text and/or HTML email body

Public interface:
```python
class EmailSummary(TypedDict):
    subject: str
    text_body: str
    html_body: str | None

def build_summary(diff: DiffResult, *, zip_code: str) -> EmailSummary: ...
```

### 10. `emailer`

Responsibility:
- Send email using SMTP or an email API.
- Surface delivery failures clearly.

Inputs:
- recipient
- `EmailSummary`

Outputs:
- send result / error

Public interface:
```python
class EmailSender(Protocol):
    def send(self, *, to: str, subject: str, text_body: str,
             html_body: str | None = None) -> str: ...
```

### 11. `scheduler`

Responsibility:
- Run the monitor at the configured interval.
- Support both one-shot execution and continuous mode.

Inputs:
- `AppConfig`

Outputs:
- scheduled run triggers

Public interface:
```python
def run_once(config: AppConfig) -> None: ...
def run_forever(config: AppConfig) -> None: ...
```

### 12. `orchestrator`

Responsibility:
- Coordinate one full monitoring cycle.
- This is the application workflow entry point.

Inputs:
- config
- provider
- repository
- email sender

Outputs:
- persisted state
- optional email notification

Public interface:
```python
def execute_monitoring_run(config: AppConfig) -> dict[str, object]: ...
```

### 13. `logging_and_metrics`

Responsibility:
- Structured logs for fetches, diffs, and email sends.
- Metrics and run summaries for troubleshooting.

Inputs:
- events from all modules

Outputs:
- logs / counters / alerts

Public interface:
```python
def get_logger(name: str) -> Logger: ...
def record_metric(name: str, value: int | float, **tags: str) -> None: ...
```

## Interface between modules

### End-to-end flow

```text
config
  -> orchestrator
  -> scheduler

orchestrator
  -> provider_contracts / providers.<source>
  -> normalizer
  -> filters
  -> storage
  -> diff_engine
  -> summary
  -> emailer
  -> logging_and_metrics
```

### Primary contracts

1. `config -> orchestrator`
- passes a validated `AppConfig`

2. `orchestrator -> provider`
- calls `search(SearchRequest)` once per ZIP code or per query variant

3. `provider -> normalizer`
- returns `ProviderListing` records that still contain source-specific raw payloads

4. `normalizer -> filters`
- passes `CanonicalListing`

5. `filters -> storage`
- only accepted canonical listings are persisted as current observations

6. `storage -> diff_engine`
- repository returns previous state for the same source and ZIP code

7. `diff_engine -> summary`
- emits `DiffResult`

8. `summary -> emailer`
- emits `EmailSummary`

9. `emailer -> storage`
- returns provider message ID or delivery metadata to persist in `notifications`

## Suggested database model

### `runs`
- `id`
- `started_at`
- `finished_at`
- `status`
- `zip_code`
- `provider`
- `fetched_count`
- `matched_count`
- `new_count`
- `changed_count`
- `removed_count`
- `error_message`

### `listings`
- `listing_id` primary key
- `source`
- `source_listing_id`
- `zip_code`
- `address`
- `url`
- `rent`
- `beds`
- `baths`
- `sqft`
- `status`
- `first_seen_at`
- `last_seen_at`
- `fingerprint`

### `listing_snapshots`
- `id`
- `listing_id`
- `run_id`
- `observed_at`
- `rent`
- `beds`
- `baths`
- `sqft`
- `raw_json`

### `notifications`
- `id`
- `run_id`
- `recipient`
- `subject`
- `provider_message_id`
- `sent_at`
- `status`
- `error_message`

## Failure handling

- Provider fetch failures should fail the run clearly and log the ZIP code and provider.
- Email send failures should not delete fetched data; they should record a failed notification for retry or inspection.
- Parsing failures should be visible in logs with enough context to diagnose schema drift.
- Rate limits and anti-bot responses should be treated as first-class operational errors.

## Delivery phases

### Phase 1: vertical slice
- config loading
- one provider adapter
- normalization
- SQLite storage
- diff detection
- SMTP email
- one-shot CLI command

### Phase 2: operational hardening
- scheduler
- retries and backoff
- better HTML summaries
- richer change detection
- delivery history
- logging and metrics

### Phase 3: extensibility
- alternate providers
- web UI or admin page
- multi-user support
- cloud deployment packaging

## Todos

1. Define architecture and constraints around listing ingestion.
2. Specify module boundaries and interfaces.
3. Write the executable implementation plan.

## Notes

- The riskiest area is the listing source. Keep the provider adapter isolated and replaceable.
- For a personal tool, SQLite is sufficient to start.
- Email should default to digest mode to reduce noise, with immediate alerts as a later option.
