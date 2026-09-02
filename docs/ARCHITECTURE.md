# Architecture

This document describes how `jobsdb-wrapper` is actually structured (v4, guest-only).
It intentionally mirrors the source layout so every claim can be checked against code.

## Dependency direction

```
CLI / stable Python API            <- caller-facing, stable
        │
        ▼
sync + async clients               <- src/jobsdb_wrapper/client.py, async_client.py
        │
        ▼
request construction (shared)      <- src/jobsdb_wrapper/http.py (build_search_params)
        │
        ▼
HTTP transport + classification    <- src/jobsdb_wrapper/http.py
        │
   ┌────┼─────────┬──────────┐
   ▼    ▼         ▼          ▼
rate  failure  GraphQL ops  detail cache
limiter model  (queries.py) (cache.py)
        │
        ▼
undocumented SEEK GraphQL upstream
```

The core rule: **upstream instability stays behind the protocol layer.** Code
outside `http.py`/`queries.py` should not need to know about feature-negotiation
headers, market hosts, or salary-period encoding.

## Public API layer

- `src/jobsdb_wrapper/__init__.py` — re-exports the two clients, domain models,
  filter constants, and the Markdown helpers. This is the stable import surface.
- `src/jobsdb_wrapper/models.py` — dataclasses for search results, job summaries,
  job details, facets/locations and the typed exception hierarchy
  (`JobsDBError` → `JobsDBBlockedError`, `JobsDBHTTPError`). Also defines the
  filter constants (`WORK_TYPES`, `WORK_ARRANGEMENTS`, `SALARY_PERIODS`, `SORT_MODES`).

## Clients

- `src/jobsdb_wrapper/client.py`
  - `_BaseClient` holds shared constructor config: market resolution
    (`resolve_market`), graphql URL, timeout, retries, the `RateLimiter`, and
    the proxy config. It also owns `_headers()` and the search-param plumbing.
  - `JobsDBClient` (sync) adds the `curl_cffi.Session` transport, `search()`,
    lazy `iter_all()`, detail `job()` (with optional SQLite cache), `job_markdown()`,
    and discovery helpers (`locations`, `title_facets`, `location_facets`, `company`).
- `src/jobsdb_wrapper/async_client.py`
  - `AsyncJobsDBClient` mirrors the sync client using `curl_cffi.AsyncSession`
    and `asyncio`. It adds a bounded `asyncio.Semaphore(concurrency)` and
    `fetch_details_many()` for parallel detail retrieval.
  - Both clients inherit the *same* `build_search_params`, so filter semantics
    cannot diverge between sync and async paths.

## Request construction

- `src/jobsdb_wrapper/http.py::build_search_params` — a pure function that turns
  the public filter surface (keywords, location, radius, work type, arrangement,
  salary + period, posting age, categories, advertiser/org, tags, sort, page
  size, facets) into the `JobSearchV7` GraphQL variables. It is shared verbatim by
  sync and async clients.
- `src/jobsdb_wrapper/http.py::_build_v6_base` (defined in `client.py`) — shared
  builder for the `JobSearchV6` facet discovery operations.
- `src/jobsdb_wrapper/queries.py` — the GraphQL operation documents
  (`JobSearchV7`, `JobSearchV6`, `JobDetail`), reverse-engineered from the
  frontend and kept isolated from the rest of the package.

## HTTP transport & response classification

- `src/jobsdb_wrapper/http.py`:
  - market routing (`MARKET_HOSTS`, `resolve_market`);
  - header construction (`build_headers`), including the `x-custom-features`
    feature-negotiation header and a fresh `X-Request-Id` per call;
  - `classify_response` — turns an HTTP response into parsed JSON or a typed
    `RequestError("network" | "http" | "blocked")`;
  - `interpret_body` — validates the GraphQL envelope and raises
    `RequestError("runtime", …)` for soft errors or `JobsDBError` for hard ones;
  - `backoff_sleep` — bounded exponential backoff with jitter.

## Rate limiter

- `src/jobsdb_wrapper/http.py::RateLimiter` — a thread-safe min-interval limiter
  (initial 60 rpm by default). It reads the upstream `seek-bot-score` header via
  `adapt()`: a score ≥ 30 widens the interval (×1.5, capped at 3× the minimum),
  and lower scores let it recover gradually (÷1.2 back toward the minimum).

## Cache

- `src/jobsdb_wrapper/cache.py::DetailCache` — a tiny SQLite store keyed by
  `(job_id, market)`. It stores a SHA-1 of the description content alongside the
  payload; `get_valid()` returns a cached row only when the stored hash matches
  the current content. There is **no TTL** — staleness is detected by content
  change, not elapsed time.

## Contract doctor

- `src/jobsdb_wrapper/doctor.py` — runs live probes against the upstream and
  asserts the field contract the wrapper depends on (basic search, expected
  fields, facets, salary-filter semantics, detail payload, V6 title/location
  facets). `DoctorReport.summary()` is human-readable and the CLI maps a healthy
  report to exit 0 and drift to exit 1, so `jobsdb doctor` is automation-friendly.

## Markdown rendering

- `src/jobsdb_wrapper/markdown.py` — a standard-library `html.parser`
  implementation that converts job-description HTML to Markdown (paragraphs,
  headings, links, emphasis, ordered/unordered/nested lists) plus a job-posting
  renderer (`job_to_markdown`). No extra HTML dependency.

## CLI

- `src/jobsdb_wrapper/cli.py` — argparse front-end over the clients:
  `search`, `job`, `locations`, `facets-v6`, `doctor`. The `jobsdb` entry point
  is declared in `pyproject.toml` (`jobsdb = "jobsdb_wrapper.cli:main"`), and
  each subcommand returns an exit status suitable for scripting.

## Sync vs async

Request construction is shared; only the transport differs. The async path
additionally enforces bounded concurrency for bulk detail retrieval.

## Design tension worth noting

- `build_search_params` is deliberately "wide": it encodes the full public filter
  surface even where the upstream currently ignores some parameters. That keeps
  the public interface stable while the protocol adapter absorbs upstream churn.
- `classify_response` treats a 200 body that fails JSON parsing as `network`
  rather than `runtime` — an unusual choice that reflects the observed symptom
  (a broken/mitm'd connection looks like a network fault, and is retried as such).