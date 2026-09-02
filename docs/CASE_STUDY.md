# jobsdb-wrapper — Engineering Case Study

## Overview

`jobsdb-wrapper` is a Python client around an undocumented GraphQL backend used by the JobsDB / JobStreet job-search experience.

The interesting engineering problem is not extracting job postings.

It is creating a stable, testable software boundary around an unstable external protocol.

The project therefore focuses on:

- protocol reconstruction;
- typed domain models;
- explicit failure semantics;
- adaptive throttling;
- caching;
- sync/async access;
- bounded concurrency;
- contract-drift detection;
- deterministic regression testing.

---

## 1. Problem

A public website can expose a rich search experience without exposing an equivalent public API.

The frontend may depend on:

- GraphQL operations;
- undocumented request fields;
- feature negotiation;
- market-specific routing;
- undocumented response structures;
- request headers;
- anti-automation controls.

A simple scraper tightly couples business logic to those details.

The design goal was different:

> isolate the upstream protocol behind a small Python-facing abstraction.

---

## 2. Constraints

The implementation has to deal with:

1. An undocumented upstream contract.
2. Multiple geographic markets.
3. Search and detail operations.
4. Upstream rate pressure.
5. Network failures.
6. HTTP failures.
7. Blocked responses.
8. Schema/contract drift.
9. Repeated detail requests.
10. Both synchronous and asynchronous callers.
11. Deterministic CI.

There is an additional product constraint:

> The public project should remain guest-only.

That deliberately excludes authentication and account mutation.

---

## 3. Protocol discovery

The client was developed by analyzing the behavior of the frontend and reconstructing the protocol required for anonymous search and job retrieval.

The resulting adapter contains upstream-specific knowledge such as:

- GraphQL operation documents;
- request variables;
- market routing;
- feature negotiation;
- salary encoding;
- search semantics;
- detail payload mapping.

This knowledge is intentionally kept close to the protocol layer.

---

## 4. Architecture

The public surface is deliberately small:

```text
CLI / Python API
       │
       ▼
sync / async client
       │
       ▼
request construction
       │
       ▼
HTTP / protocol adapter
       │
 ┌─────┼─────────┐
 ▼     ▼         ▼
rate  failure   cache
limit model
       │
       ▼
undocumented upstream
```

The key architectural principle is:

> upstream instability should not leak into every part of the application.

---

## 5. Failure model

The client distinguishes:

```text
ok
network
http
runtime
blocked
```

This matters because these states imply different recovery strategies.

A timeout is not the same as a malformed response.

A server error is not the same as an explicit block.

A parser failure is not the same as network instability.

Making those distinctions explicit makes the system easier to test and reason about.

---

## 6. Adaptive rate limiting

A fixed sleep between requests is simple but does not react to changing upstream conditions.

The limiter instead adjusts request pacing according to observed pressure.

The goal is not maximum throughput.

The goal is useful retrieval while minimizing unnecessary upstream pressure.

This is particularly important for a client that may be used for bulk job-detail retrieval.

---

## 7. Cache correctness

Job details are expensive relative to local cache access.

SQLite provides a small persistent cache without requiring another service.

The cache is not treated as automatically authoritative.

Content-derived validation is used so that changed data is not silently treated as identical.

The engineering principle is:

> performance optimization must not silently become data corruption.

---

## 8. Contract drift

Offline tests answer:

> Does our implementation still behave correctly against known fixtures?

They cannot answer:

> Has the real upstream contract changed?

`jobsdb doctor` exists for the second question.

This produces a two-layer validation model:

```text
offline tests
    +
live contract probes
    =
better integration confidence
```

The doctor does not make the undocumented API stable.

It makes instability observable.

---

## 9. Sync and async

Both sync and async interfaces are useful for different consumers.

The important design constraint is semantic consistency.

Search filters, request variables and market behavior should not silently diverge between clients.

Where appropriate, request construction is shared while transport execution differs.

The async path additionally supports bounded concurrency for detail retrieval.

---

## 10. Bounded concurrency

Bulk fetching can easily become:

```text
N jobs
↓
N tasks
↓
N simultaneous requests
```

That is undesirable for both reliability and upstream pressure.

The client therefore uses bounded concurrency.

Conceptually:

```text
100 jobs
   │
   ▼
queue
   │
   ├── worker
   ├── worker
   ├── worker
   ├── worker
   └── worker
```

The exact bound should remain configurable and conservative.

---

## 11. Scope reduction

Earlier versions explored authenticated functionality.

The public v4 design intentionally removes:

- login;
- cookies;
- profile operations;
- job application;
- bookmark/save operations.

This is not merely feature removal.

It is architecture simplification.

A smaller public scope means:

- fewer secrets;
- less privacy risk;
- fewer stateful workflows;
- fewer failure modes;
- smaller maintenance surface;
- clearer package responsibilities.

The resulting package is easier to explain and audit.

---

## 12. Testing strategy

The test suite is offline.

Fixtures allow protocol and mapping behavior to be tested deterministically.

The suite focuses on behavior such as:

- request/filter encoding;
- response classification;
- model mapping;
- cache behavior;
- Markdown conversion;
- client behavior.

Live integration is intentionally separated into the doctor command.

This separation keeps CI deterministic.

---

## 13. Trade-offs

### Why pure HTTP?

It reduces runtime complexity and avoids browser automation for a protocol that can be represented as HTTP requests.

### Why SQLite?

It provides persistence without requiring another service.

### Why a custom failure model?

Because recovery decisions depend on failure type.

### Why live doctor checks?

Because offline fixtures cannot detect upstream drift.

### Why guest-only?

Because the core value of the library does not require account automation, while authenticated workflows substantially increase security and maintenance burden.

---

## 14. Productionization

A larger production system would require additional concerns, depending on scale and use case:

- stronger observability;
- metrics;
- structured logging;
- distributed caching;
- persistent job state;
- circuit breaking;
- deployment-level rate coordination;
- stronger schema validation;
- alerting around contract drift;
- formal upstream/legal review;
- operational ownership of protocol changes.

Those are deliberately outside the scope of this package.

---

## 15. Lessons

The main lesson is that an API wrapper is not fundamentally about translating JSON into Python objects.

The difficult part is managing uncertainty at the integration boundary.

A useful wrapper therefore needs:

```text
protocol isolation
      +
failure semantics
      +
rate control
      +
cache correctness
      +
contract validation
      +
deterministic tests
```

That is the engineering value of `jobsdb-wrapper`.
