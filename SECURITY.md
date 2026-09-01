# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 4.x     | ✅        |
| < 4.0   | ❌        |

## Reporting a vulnerability

**Do not open a public issue for security problems.**

Email: **security@jobsdb-wrapper.dev** (or open a GitHub **private** security advisory via *Security → Report a vulnerability*).

Please include:

- Affected version / commit
- Reproduction steps or PoC
- Impact assessment

You will get an acknowledgement within **72 hours**. We aim to ship a fix for
critical issues within 7 days and will credit reporters in the changelog unless
you prefer otherwise.

## Security model & scope

This package is **guest-only**: it holds no credentials, stores no cookies,
and performs no authentication. That removes the most dangerous data classes
by construction.

### 1. Extracted job content
- No personal data; safe to publish. The optional SQLite detail cache is
  content-only (job descriptions keyed by posting id).
- If you enable the detail cache, remember the file contains scraped content
  subject to SEEK's terms of use — keep it out of repos you publish.

### 2. Outbound requests
- The client sends no identifiers beyond what a browser would send to render
  the public site: browser-like headers, a fresh request id per call, and a
  Chrome-consistent TLS fingerprint (via `curl_cffi`).
- Set `JOBSDB_PROXY` only if you control the proxy: all traffic (and any
  job content) flows through it.

## What this package will never do

- No credentials, no login, no session handling — by design since v4.0.0.
- No telemetry, no phoning home, no analytics.
- No automated job apply.

## Known design trade-offs

- `curl_cffi` ships its own TLS stack (BoringSSL-based). Keep the dependency
  pinned (`>=0.13`) and update via normal releases.
- The wrapper targets a private, undocumented API; the failure matrix
  (`docs/FAILURE_MATRIX.md`) documents how every known failure surfaces.

## Scope

In-scope: code in this repository, the published sdist/wheel, and the CLI.
Out-of-scope: SEEK's own infrastructure, th.jobsdb.com availability, and
Cloudflare challenges (report those to SEEK Ltd).
