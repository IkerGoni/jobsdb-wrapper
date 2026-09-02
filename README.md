# jobsdb-wrapper

> **A resilient, pure-HTTP Python client for the undocumented JobsDB / JobStreet GraphQL backend.**

`jobsdb-wrapper` turns an unstable, undocumented external API into a small, typed and testable Python interface for job-market research.

It supports six SEEK markets with:

- synchronous and asynchronous clients;
- structured search and filtering;
- lazy pagination;
- bounded-concurrency detail fetching;
- SQLite caching with content validation;
- adaptive rate limiting;
- typed response/failure classification;
- live contract-drift detection;
- Markdown rendering of job postings;
- a CLI and Python API.

The project is deliberately **guest-only**: it does not implement login, account access, profile mutation, automated applications, or bookmark operations.

```text
                    Undocumented upstream
                            │
                            ▼
                 ┌──────────────────────┐
                 │ Protocol adapter     │
                 │ GraphQL operations   │
                 │ request construction │
                 └──────────┬───────────┘
                            │
          ┌─────────────────┼──────────────────┐
          ▼                 ▼                  ▼
     Failure model     Rate limiting       Cache
          │                 │                  │
          └─────────────────┼──────────────────┘
                            ▼
                 ┌──────────────────────┐
                 │ Stable Python API    │
                 │ sync + async         │
                 └──────────┬───────────┘
                            │
                 ┌──────────┴───────────┐
                 ▼                      ▼
               CLI                  Downstream
                              analysis / automation
```

**Python 3.10+ · `curl_cffi` · GraphQL · SQLite · sync/async · pytest**

[![CI](https://github.com/IkerGoni/jobsdb-wrapper/actions/workflows/ci.yml/badge.svg)](https://github.com/IkerGoni/jobsdb-wrapper/actions)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

> **Portfolio status:** this is an engineering/research project built around an undocumented upstream service. It is not presented as an official SEEK SDK or as a production guarantee against upstream changes.

---

## Why this project?

Interacting with a modern job-search platform is rarely just:

```text
HTTP request → JSON → Python object
```

When the public interface is backed by an undocumented frontend API, the real engineering problems become:

- discovering the actual protocol contract;
- reproducing request semantics without a browser;
- keeping sync and async implementations consistent;
- handling different classes of failure correctly;
- avoiding unnecessary upstream load;
- detecting schema drift before downstream code silently breaks;
- validating cached content;
- maintaining a stable public Python API while the upstream changes.

This project treats those problems as first-class engineering concerns.

The result is a small adapter around a deliberately unstable dependency.

---

# Engineering highlights

| Problem | Engineering approach |
|---|---|
| Undocumented GraphQL API | Reverse-engineered protocol adapter |
| Multiple markets | Centralized market/locale routing |
| Sync + async clients | Shared request construction with separate transports |
| Upstream failures | Typed failure taxonomy |
| Rate pressure | Adaptive throttling |
| Repeated detail requests | SQLite cache with content validation |
| Contract changes | `jobsdb doctor` live probes |
| HTML job descriptions | Standard-library HTML → Markdown renderer |
| Large result sets | Lazy pagination |
| Bulk details | Bounded asynchronous concurrency |
| Public API stability | Small typed/domain-oriented client surface |
| Safety / scope | Guest-only design; no automated account actions |

---

# Quick demo

Install:

```bash
pip install jobsdb-wrapper
```

Search:

```bash
jobsdb search "python developer" \
  --where Bangkok \
  --page-size 5
```

Fetch a complete posting as Markdown:

```bash
jobsdb job 94162495 -o job.md
```

Check the live upstream contract:

```bash
jobsdb doctor
```

The important part of the project is not the CLI itself.

It is what happens underneath:

```text
CLI
 │
 ▼
JobsDBClient
 │
 ▼
request builder
 │
 ▼
GraphQL operation
 │
 ▼
HTTP transport
 │
 ├── response classification
 ├── adaptive rate limiting
 └── session handling
 │
 ▼
typed model / failure
```

---

# Architecture

The architecture deliberately separates the unstable external protocol from the stable Python-facing API.

```text
┌─────────────────────────────────────────────────────────┐
│                     Public interface                    │
│                                                         │
│       CLI                  JobsDBClient                 │
│                              │                          │
│                         AsyncJobsDBClient               │
└──────────────────────────────┬──────────────────────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ Request construction │
                    │                      │
                    │ build_search_params  │
                    │ GraphQL operations   │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ HTTP / protocol layer │
                    │                      │
                    │ market routing       │
                    │ headers              │
                    │ TLS configuration     │
                    │ response parsing     │
                    └──────────┬───────────┘
                               │
               ┌───────────────┼────────────────┐
               ▼               ▼                ▼
          Rate limiter    Failure model       Cache
               │               │                │
               └───────────────┼────────────────┘
                               ▼
                     Undocumented GraphQL
                          upstream API
```

A core design principle is:

> **The unstable protocol belongs behind a small adapter boundary.**

That keeps upstream-specific behavior from leaking throughout the rest of the package.

---

# The protocol problem

The JobsDB / JobStreet frontend uses a private GraphQL interface rather than a documented public API.

The client was built by analyzing the frontend's production request behavior and reconstructing the parts of the protocol required for anonymous job search and retrieval.

Examples include:

- GraphQL operation documents;
- market-specific hosts;
- feature negotiation;
- request headers;
- search parameter encoding;
- salary-period encoding;
- posting-age semantics;
- job-detail payloads;
- V6/V7 search/facet operations.

The implementation therefore intentionally treats the upstream protocol as **reverse-engineered and unstable**.

It should never be confused with an official SEEK API.

---

# Why pure HTTP?

A common way to automate a modern web application is:

```text
browser
  ↓
JavaScript application
  ↓
network requests
```

This project instead isolates the underlying HTTP protocol:

```text
Python
  ↓
curl_cffi
  ↓
GraphQL
```

That removes the need for:

- browser automation;
- DOM extraction;
- JavaScript execution;
- browser session management.

The result is a much smaller runtime surface and a client that can be used as a normal Python dependency.

The transport uses `curl_cffi` for browser-compatible TLS behavior where required by the upstream service.

---

# Failure model

Network errors are not equivalent to HTTP errors, application errors, or upstream blocking.

The client therefore classifies outcomes into explicit categories:

```text
ok
network
http
runtime
blocked
```

These outcomes drive different behavior.

Conceptually:

```text
                  response
                     │
                     ▼
             classify_response()
                     │
        ┌────────────┼─────────────┐
        ▼            ▼             ▼
     network        http         blocked
        │            │             │
     retry /      inspect /     explicit
     backoff      classify      blocked error
        │
        ▼
      runtime
```

This makes failure behavior part of the public engineering model rather than an implementation detail hidden inside exception handling.

---

# Adaptive rate limiting

The client does not treat rate limiting as a fixed sleep between requests.

The limiter maintains a minimum request interval and adapts it according to upstream signals.

Conceptually:

```text
normal traffic
      │
      ▼
stable interval
      │
      ▼
upstream pressure
      │
      ▼
increase interval
      │
      ▼
pressure falls
      │
      ▼
gradual recovery
```

The default limiter is intentionally conservative.

The objective is not to maximize request volume.

The objective is:

> **retrieve useful data while respecting upstream limits and reducing unnecessary pressure.**

---

# Caching

Job-detail retrieval is cacheable, so the client includes a SQLite-backed detail cache.

The cache stores content-derived validation information.

Conceptually:

```text
request job
    │
    ▼
cache lookup
    │
 ┌──┴───────────────┐
 │                  │
valid              invalid/missing
 │                  │
 ▼                  ▼
return cache       fetch upstream
                      │
                      ▼
                store + hash
```

This avoids blindly trusting stale cached descriptions.

The cache is especially useful for:

- repeated analysis;
- pagination workflows;
- bulk extraction;
- downstream job-market processing.

---

# Contract-drift detection

One of the most important features is:

```bash
jobsdb doctor
```

The upstream API is undocumented and can change independently of this package.

A normal test suite cannot detect every live upstream change because the tests intentionally run offline.

`jobsdb doctor` complements those tests with live contract probes.

It checks assumptions such as:

- basic search behavior;
- expected fields;
- facet availability;
- salary semantics;
- job-detail payloads;
- V6 facet behavior.

The model is:

```text
offline regression tests
          +
live contract probes
          ↓
       confidence
```

The distinction is important:

> **Tests protect the implementation. `doctor` protects the integration boundary.**

`doctor` cannot prevent upstream changes. It makes them visible earlier.

---

# Sync and async APIs

The package exposes both synchronous and asynchronous interfaces.

A key design decision is that request construction is shared.

```text
                 build_search_params()
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
        JobsDBClient         AsyncJobsDBClient
              │                     │
              ▼                     ▼
          sync HTTP             async HTTP
```

This prevents the two clients from independently implementing filter semantics.

For bulk detail retrieval, the async client supports bounded concurrency:

```python
async with AsyncJobsDBClient(concurrency=5) as client:
    result = await client.search(
        keywords="python",
        page_size=30,
    )

    details = await client.fetch_details_many(
        [job.id for job in result.jobs]
    )
```

Concurrency is bounded deliberately rather than allowing an unbounded task fan-out.

---

# Search

The client supports the filter surface required by the current upstream contract.

Examples:

```bash
jobsdb search "data analyst" \
  --where Bangkok \
  --posted-within 7 \
  --salary-min 50000 \
  --salary-period monthly \
  --work-type full_time \
  --arrangement remote \
  --sort date \
  --facets
```

Machine-readable output:

```bash
jobsdb search "accountant" \
  --where "Hong Kong" \
  --country hk \
  --json
```

Supported search dimensions include:

- keywords;
- location;
- radius;
- work type;
- work arrangement;
- salary range;
- salary period;
- posting age;
- categories;
- advertiser;
- organisation;
- tags;
- sort order;
- facets.

The upstream page size is currently capped at 30 results.

---

# Six markets

| Code | Market |
|---|---|
| `th` | Thailand |
| `hk` | Hong Kong |
| `my` | Malaysia |
| `sg` | Singapore |
| `ph` | Philippines |
| `id` | Indonesia |

Example:

```python
from jobsdb_wrapper import JobsDBClient

with JobsDBClient(country="th") as client:
    result = client.search(
        keywords="python developer",
        where="Bangkok",
    )

    for job in result.jobs:
        print(job.id, job.title)
```

Market-specific routing and locale behavior are isolated inside the protocol layer.

---

# Full job postings

Job details can be rendered into Markdown:

```python
from jobsdb_wrapper import JobsDBClient

with JobsDBClient() as client:
    markdown = client.job_markdown("94162495")
```

Or from the CLI:

```bash
jobsdb job 94162495 -o job.md
```

The renderer intentionally uses the Python standard library rather than introducing a heavyweight HTML parsing dependency.

It handles common job-description structures such as:

- headings;
- paragraphs;
- links;
- emphasis;
- ordered lists;
- unordered lists;
- nested lists.

---

# Python API

Basic search:

```python
from jobsdb_wrapper import JobsDBClient

with JobsDBClient() as client:
    result = client.search(
        keywords="python developer",
        where="Bangkok",
        distance_km=25,
        work_types=["full_time"],
        work_arrangements=["remote"],
        salary_min=50000,
        salary_max=90000,
        salary_period="monthly",
        posted_within_days=14,
        sort="date",
        include_facets=True,
    )

    print(result.total)

    for job in result.jobs:
        print(job.title)
```

Lazy pagination:

```python
with JobsDBClient() as client:
    for job in client.iter_all(
        keywords="react",
        max_pages=10,
    ):
        print(job.id, job.title)
```

Discovery helpers:

```python
with JobsDBClient() as client:
    client.title_facets(keywords="developer")
    client.location_facets()
    client.company("Pandora")
```

---

# Installation

Requires Python 3.10+.

```bash
pip install jobsdb-wrapper
```

From source:

```bash
git clone https://github.com/IkerGoni/jobsdb-wrapper.git
cd jobsdb-wrapper
pip install -e .
```

Then:

```bash
jobsdb --help
```

---

# Testing strategy

The test suite is intentionally offline.

Tests use recorded fixtures rather than requiring live access to the upstream service.

This allows deterministic CI while `jobsdb doctor` handles live contract validation separately.

Tests cover areas including:

```text
request/filter encoding
        ↓
response classification
        ↓
GraphQL → model mapping
        ↓
cache behavior
        ↓
Markdown conversion
        ↓
client behavior
```

Run:

```bash
pytest
```

The repository contains a substantial regression suite. The exact test count is intentionally treated as a secondary metric; the important question is what the tests protect.

The project should not use a test-count number as its primary marketing claim.

---

# Engineering evidence

The most important implementation areas are easy to inspect:

| Concern | Implementation |
|---|---|
| Sync client | `src/jobsdb_wrapper/client.py` |
| Async client | `src/jobsdb_wrapper/async_client.py` |
| Protocol / transport | `src/jobsdb_wrapper/http.py` |
| GraphQL operations | `src/jobsdb_wrapper/queries.py` |
| Domain models | `src/jobsdb_wrapper/models.py` |
| Cache | `src/jobsdb_wrapper/cache.py` |
| HTML → Markdown | `src/jobsdb_wrapper/markdown.py` |
| Contract probes | `src/jobsdb_wrapper/doctor.py` |
| CLI | `src/jobsdb_wrapper/cli.py` |
| Regression tests | `tests/` |

This is intentional:

> **The repository's claims should be verifiable by reading the implementation and tests.**

---

# Deliberate scope reduction

Earlier versions of the project experimented with authenticated functionality.

That surface was intentionally removed in v4.

The public package is now guest-only.

Not implemented:

- login;
- account sessions;
- profile read/write;
- skills;
- experience;
- education;
- job applications;
- automated saves/bookmarks.

This is a deliberate architectural decision.

The rationale is:

```text
broader authenticated surface
             ↓
higher maintenance burden
             ↓
higher security / privacy risk
             ↓
unclear public contract
             ↓
remove it
             ↓
small guest-only client
```

The result is a narrower but clearer package focused on anonymous search and extraction.

If authenticated SEEK operations are required, use an appropriate official channel or browser-based workflow rather than extending this package with credential automation.

---

# What this project does not try to be

This is not:

- an official SEEK SDK;
- a browser automation framework;
- a CAPTCHA-solving service;
- an account automation tool;
- an automated job-application system;
- a guarantee that the upstream API will remain stable.

The project deliberately stops at the guest search/extraction boundary.

---

# Limitations

The upstream service is private and undocumented.

SEEK can change:

- GraphQL operations;
- schemas;
- field names;
- feature flags;
- request requirements;
- rate policies;
- anti-automation behavior;
- market-specific behavior.

`jobsdb doctor` can detect many contract assumptions, but it cannot prevent upstream changes.

The upstream page size is currently capped at 30.

Bulk use should remain bounded and respectful of server-side rate policies.

The package is intended for personal research and job-market analysis. Users are responsible for complying with applicable terms and policies before using the software against the upstream services.

See:

- [`TERMS_OF_USE.md`](TERMS_OF_USE.md)
- [`SECURITY.md`](SECURITY.md)

---

# Project structure

```text
jobsdb-wrapper/
│
├── src/
│   └── jobsdb_wrapper/
│       ├── client.py
│       ├── async_client.py
│       ├── http.py
│       ├── queries.py
│       ├── models.py
│       ├── cache.py
│       ├── markdown.py
│       ├── doctor.py
│       ├── cli.py
│       └── USER_GUIDE.md
│
├── tests/
│   └── offline regression tests
│
├── docs/
│   └── engineering documentation
│
├── .github/
│   └── workflows/
│
├── CHANGELOG.md
├── CONTRIBUTING.md
├── SECURITY.md
├── TERMS_OF_USE.md
├── pyproject.toml
└── LICENSE
```

---

# Development

Clone the repository:

```bash
git clone https://github.com/IkerGoni/jobsdb-wrapper.git
cd jobsdb-wrapper
```

Install development dependencies according to the project configuration, then run:

```bash
pytest
```

Before opening a pull request, verify:

```text
tests
lint
packaging
documentation
security-sensitive changes
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md).

---

# AI-assisted development

This repository was developed using AI-assisted engineering tools.

AI was used as an implementation and research accelerator across activities such as:

- code exploration;
- reverse-engineering assistance;
- implementation;
- refactoring;
- test generation;
- debugging;
- documentation;
- architecture review.

The important engineering boundary is:

```text
AI assistance
     ↓
human-defined architecture
     ↓
typed interfaces
     ↓
deterministic tests
     ↓
CI validation
     ↓
security review
     ↓
human engineering judgment
```

AI-generated code is therefore treated as implementation material that must pass the same engineering controls as manually written code.

The repository's public contract is the code, tests and documentation — not the output of an AI tool.

---

# Design principles

### 1. Isolate instability

Upstream-specific behavior belongs in the protocol adapter.

### 2. Share semantics

Sync and async clients should not independently implement request semantics.

### 3. Make failures explicit

Network, HTTP, runtime and blocking conditions should not collapse into one generic exception.

### 4. Respect upstream constraints

Rate limiting is part of the client design, not an afterthought.

### 5. Never blindly trust stale data

Cached job descriptions are validated using content-derived state.

### 6. Detect drift early

Live contract probes complement offline regression tests.

### 7. Keep the public scope narrow

Guest search and extraction are enough to make the package useful.

---

# Documentation

- [`src/jobsdb_wrapper/USER_GUIDE.md`](src/jobsdb_wrapper/USER_GUIDE.md)
- [`CHANGELOG.md`](CHANGELOG.md)
- [`CONTRIBUTING.md`](CONTRIBUTING.md)
- [`SECURITY.md`](SECURITY.md)
- [`TERMS_OF_USE.md`](TERMS_OF_USE.md)

---

# Author

**Iker Goñi**

Software engineer working across:

- AI systems;
- automation;
- Python/backend engineering;
- full-stack development;
- product-oriented engineering.

[LinkedIn](https://www.linkedin.com/in/iker-goni/)

---

# License

MIT — see [`LICENSE`](LICENSE).
