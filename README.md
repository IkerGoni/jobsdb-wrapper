# jobsdb-wrapper

[![PyPI version](https://img.shields.io/pypi/v/jobsdb-wrapper.svg)](https://pypi.org/project/jobsdb-wrapper/)
[![Python versions](https://img.shields.io/pypi/pyversions/jobsdb-wrapper.svg)](https://pypi.org/project/jobsdb-wrapper/)
[![License](https://img.shields.io/pypi/l/jobsdb-wrapper.svg)](https://pypi.org/project/jobsdb-wrapper/)
[![CI](https://github.com/igoni/jobsdb-wrapper/actions/workflows/ci.yml/badge.svg)](https://github.com/igoni/jobsdb-wrapper/actions/workflows/ci.yml)
[![Downloads](https://img.shields.io/pypi/dm/jobsdb-wrapper.svg)](https://pypi.org/project/jobsdb-wrapper/)

**Pure-HTTP Python client for JobsDB & JobStreet (6 SEEK markets)** — search with every filter the website offers, download full postings as Markdown. Zero browser, zero CAPTCHA, zero credentials.

```bash
pip install jobsdb-wrapper
jobsdb search "python developer" --where Bangkok --page-size 5
jobsdb job 94162495 -o job.md
```

---

## Why jobsdb-wrapper?

The SEEK platform (th/hk.jobsdb.com, my/sg/ph/id.jobstreet.com) sits behind Cloudflare. Most scraping approaches pay twice: a headless browser stack + CAPTCHA-solving budget.

This package reverse-engineers the SPA's private Apollo GraphQL endpoint (`/graphql`) — Cloudflare doesn't challenge it when requests carry the right feature-negotiation header and a browser-consistent TLS fingerprint.

- **Zero browser automation** — plain HTTP via `curl_cffi` (Chrome TLS impersonation)
- **Zero credentials** — guest endpoint, no accounts, no cookies
- **Full filter surface** — 15+ params, all verified against live API
- **Six markets, one client** — TH, HK, MY, SG, PH, ID with correct locales
- **Bulk-ready** — lazy pagination, bounded-concurrency async, SQLite cache with content-hash invalidation
- **Self-monitoring** — `jobsdb doctor` runs live contract probes against the API

```text
┌────────────────────────────────────────────────┐
│  CLI (argparse)      Python API                │
│     │                   │                      │
│  JobsDBClient ─── AsyncJobsDBClient            │
│     └───────┬───────┘                          │
│             ▼                                  │
│  build_search_params()   ← pure function,      │
│  (filter dict → V7 params)  shared sync/async  │
│             │                                  │
│             ▼                                  │
│  classify_response / interpret_body            │
│  typed outcomes: ok | network | http |         │
│                  runtime | blocked             │
│             │                                  │
│             ▼                                  │
│  curl_cffi Session (chrome131 impersonate)     │
│  POST https://{market-host}/graphql            │
│  ops: JobSearchV7 · JobSearchV6 · JobDetail    │
└────────────────────────────────────────────────┘
```

Key request ingredients (from `ca-search-ui` production bundles):
- Header `x-custom-features: application/features.seek.all+json` unlocks full SEEK API surface
- Browser-like headers (`Origin`, `Referer`, `Accept-Language`, fresh `X-Request-Id`) + Chrome TLS fingerprint
- Salary encodes period as suffix (`50000m` = 50k monthly); posting age → `listedAt: "Nd"`

---

## Install

Requires Python 3.10+. Single dependency: `curl_cffi>=0.13`.

```bash
pip install jobsdb-wrapper

# Or from source
git clone https://github.com/igoni/jobsdb-wrapper.git
cd jobsdb-wrapper
pip install -e .
```

After install, the `jobsdb` CLI is available:

```bash
jobsdb --help
jobsdb search "python developer" --where Bangkok --page-size 5
```

---

## CLI Usage

```bash
# Search with filters + facet counts
jobsdb search "data analyst" \
  --where Bangkok --posted-within 7 --salary-min 50000 \
  --salary-period monthly --work-type full_time --arrangement remote \
  --sort date --facets

# Machine-readable JSON
jobsdb search "accountant" --where "Hong Kong" --country hk --json

# Full posting as Markdown
jobsdb job 94197120 -o job.md
jobsdb job <ID> --country sg

# Discovery helpers (autocomplete ids + kind: SEEK_AREA, REGION, …)
jobsdb locations "Chiang"
jobsdb facets-v6 "developer" --kind titles

# Proxy support (or JOBSDB_PROXY env var)
jobsdb search "qa engineer" --proxy http://user:pass@host:port

# Live contract check against API
jobsdb doctor
```

---

## Python API

```python
from jobsdb_wrapper import JobsDBClient

with JobsDBClient() as c:
    res = c.search(
        keywords="python developer",
        where="Bangkok", distance_km=25,
        work_types=["full_time"],
        work_arrangements=["remote"],
        salary_min=50000, salary_max=90000,
        salary_period="monthly",
        posted_within_days=14,
        sort="date",
        include_facets=True,
    )
    print(res.total, [j.title for j in res.jobs])

    # Full posting as Markdown
    md = c.job_markdown("94162495")

    # Discovery helpers
    c.title_facets(keywords="developer")
    c.location_facets()
    c.company("Pandora")
```

### Bulk crawl (async + cache)

```python
import asyncio
from jobsdb_wrapper import JobsDBClient
from jobsdb_wrapper.async_client import AsyncJobsDBClient

# Sync: lazy pagination + cached details
with JobsDBClient(detail_cache="~/.cache/jobsdb.db") as c:
    for job in c.iter_all(keywords="react", max_pages=10):
        print(job.id, job.title)

# Async: parallel detail fetching
async def bulk():
    async with AsyncJobsDBClient(concurrency=5) as ac:
        res = await ac.search(keywords="python", page_size=30)
        details = await ac.fetch_details_many([j.id for j in res.jobs])
        print(len(details))

asyncio.run(bulk())
```

---

## Features

- **6 markets**: Thailand, Hong Kong, Malaysia, Singapore, Philippines, Indonesia
- **Full filter surface**: keywords, location+radius, work type, arrangement, salary+period, posting age, categories, advertiser/org, tags, sort
- **Bulk-ready**: `iter_all()`, async `fetch_details_many()`, SQLite cache with SHA-1 content-hash invalidation
- **Contract drift detection**: `jobsdb doctor` — live probes (search basics, field presence, facets, salary semantics, detail payload, V6 facets)
- **Adaptive rate limiting**: reads `seek-bot-score` header, backs off automatically

---

## Filter Reference (verified live 2026-08-25)

| Filter | Values |
|---|---|
| `keywords` | free text |
| `where` | location text (`Bangkok`, `Chiang Mai`, …) |
| `distance_km` | radius around `where` |
| `work_types` | `full_time`(242) `part_time`(243) `contract`(244) `casual`(245) |
| `work_arrangements` | `on_site`(1) `hybrid`(2) `remote`(3) |
| `salary_min/max` + `salary_period` | encoded `<amount>h\|m\|y>` upstream |
| `posted_within_days` | `listedAt: "Nd"` |
| `categories` | facet ids from `include_facets=True` |
| `advertiser_id` / `organisation_ids` / `company` | target specific employers |
| `tags` | `new` `seen` `viewed` `applied` `applyStarted` `sab` |
| `sort` | relevance(score) \| date(listedAt) |
| `page_size` | ≤30 (upstream cap) |

Markets: `JobsDBClient(country="th"\|"hk"\|"my"\|"sg"\|"ph"\|"id")`.

---

## What is deliberately NOT implemented

Since v4.0.0 this package is **guest-only**:

- **Login / accounts** — SEEK has no email/password or magic-link GraphQL login; sessions are server-side and cannot be created safely from a third-party client.
- **Profile read/write, skills, experience, education** — authenticated surface, removed in v4.0.0. (The v3 implementation worked, but its maintenance and safety burden outweighed its value for a guest-scraping library.)
- **Job apply / save / bookmarks** — no captured guest contract; automated apply is high-risk.

If you need authenticated SEEK operations, use the browser (or an official channel).

---

## Design Notes

- **One request builder, two transports** — `build_search_params()` is a pure function shared by sync/async clients; filter behavior cannot diverge
- **Typed failure taxonomy** — every response classified as `ok | network | http | runtime | blocked` with distinct strategies (exponential backoff, session replay, immediate `JobsDBBlockedError`)
- **Adaptive throttling** — min-interval limiter (~60 rpm) reads `seek-bot-score`, widens interval under pressure, recovers gradually (TCP congestion control analogy)
- **Cache you can trust** — SQLite store keeps SHA-1 of description content; `get_valid()` returns cached rows only when hash matches
- **Drift detection as first-class feature** — API is undocumented and versioned by operation name; `doctor.py` asserts exact fields wrapper depends on
- **Stdlib-only rendering** — ~120-line `html.parser` implementation (nested lists, links, emphasis, heading promotion for JD sections); no heavy deps

---

## Limitations

- Targets a **private, undocumented API** reverse-engineered from frontend bundles. SEEK can change schemas, add challenges to `/graphql`, or deprecate operations at any time. The doctor command detects this; it cannot prevent it.
- `page_size` capped at 30 results per page upstream; deep crawls paginate.
- Adaptive limiter defaults to ~60 rpm per IP. Sustained bulk crawling should use proxies (`JOBSDB_PROXY`) and stays subject to SEEK's server-side rate policy.
- Intended for personal research and job-market analysis. Check SEEK's terms of service before commercial or high-volume use.

---

## Project Layout

```
src/jobsdb_wrapper/
├── client.py         sync client: search, iter_all, job, discovery, company
├── async_client.py   async mirror: bounded-concurrency bulk detail fetch
├── http.py           market routing, headers, response classification, adaptive RateLimiter
├── queries.py        GraphQL operation documents (V7, V6, JobDetail)
├── models.py         dataclasses + GraphQL → model mappers
├── cache.py          SQLite detail cache with content-hash validation
├── markdown.py       stdlib HTML→Markdown + posting renderer
├── doctor.py         live contract-drift checks
├── USER_GUIDE.md     usage guide
└── cli.py            argparse front-end (search/job/locations/facets-v6/doctor)

tests/               offline unit tests — no network required
```

Unit tests cover filter encoding, response classification, GraphQL mapping, cache behavior and Markdown conversion — using recorded fixtures, no network.

---

## Limits & conduct

Automated use of SEEK sites is subject to their Terms of Service — see
[TERMS_OF_USE.md](TERMS_OF_USE.md) for rate-limit expectations and an
allowed/not-allowed summary. Security model and vulnerability reporting:
[SECURITY.md](SECURITY.md). Community standards:
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

---

## Links

[Changelog](CHANGELOG.md) • [Contributing](CONTRIBUTING.md) • [Security](SECURITY.md) • [Terms of Use](TERMS_OF_USE.md) • [Code of Conduct](CODE_OF_CONDUCT.md) • [License](LICENSE)
