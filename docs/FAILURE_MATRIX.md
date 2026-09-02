# Failure Matrix

How the client behaves for each known failure condition. The taxonomy lives in
`src/jobsdb_wrapper/http.py` (`classify_response` / `interpret_body` /
`RequestError.kind`) and every condition maps to either a typed exception in
`src/jobsdb_wrapper/models.py` or a `RequestError.kind`.

> This is an engineering document, not a promise that every category below has
> identical retry behavior. It is kept synchronized with the actual code — when
> the code changes, update this table.

| Failure class | Typical detection | Desired handling | Retry policy | Testing |
|---|---|---|---|---|
| `network` | transport exception in `Session.post()` (timeout, refused, DNS), or 200 body that is not valid JSON | classify explicitly; bounded backoff then raise `JobsDBError` | bounded: `min(2^attempt + jitter, 15s)` × `retries` (default 3) | deterministic transport fixture (patched session raising) |
| `http` | non-success HTTP status (4xx/5xx); 429/502/503/504 classified explicitly as `http` | classify using status; retry per policy then raise | `429, 502, 503, 504` → backoff ×`retries`; other statuses → same bounded backoff | mocked response per status |
| `blocked` | HTTP 403, or 200 body containing a Cloudflare challenge marker and no `jobSearch` payload | stop after one retry; surface explicit `JobsDBBlockedError` | normally **one** retry only — retrying an active challenge worsens IP reputation | blocking fixture (challenge HTML / 403) |
| `runtime` | parser/model/application exception; `UNSTABLE_QUERY_ERROR` (soft GraphQL rejection) | fail explicitly; for soft runtime errors retry once with a fresh `sessionId` | `UNSTABLE_QUERY_ERROR` → 1 retry with regenerated session; hard GraphQL errors → no retry | malformed fixture / errors payload |
| `ok` | valid 200 JSON with expected `data.<operation>` | parse and map to domain model | none | normal fixture |
| contract drift | `jobsdb doctor` probe/assertion mismatch | report the exact failed assumption; exit code 1 | no blind retry | doctor test/mock (offline) |

## Verified implementation notes

These are the concrete behaviors reachable in the current code (`v4.x`, guest-only):

| # | Condition | Detection | Retry | Final outcome | User mitigation |
|---|---|---|---|---|---|
| F1 | Timeout / connection refused / DNS | transport exception in `post()` | exponential backoff (base 2s, cap 15s) ×`retries` | `JobsDBError("Request failed after N retries: …")` | check network/proxy; raise `timeout` |
| F2 | HTTP 403 with Cloudflare challenge ("Just a moment") | HTML body + status | **1** retry, then abort | `JobsDBBlockedError` | rotate IP (`JOBSDB_PROXY`), slow down, retry later |
| F3 | HTTP 403/429 without challenge | status code | backoff ×`retries` | `JobsDBBlockedError` (403) / `JobsDBError` (others) | reduce `rate_limit_rpm`; proxy |
| F4 | HTTP 5xx (502/503/504) | status code | backoff ×`retries` | `JobsDBError` | retry later |
| F5 | 200 body is not valid JSON | JSON parse failure in `classify_response` | treated as `network`, backoff ×`retries` | `JobsDBError` | transient upstream; retry |
| F6 | GraphQL `UNSTABLE_QUERY_ERROR` (soft) | `extensions.code` in `errors[]` | 1 retry with a new `sessionId` (`runtime_retry=True` on search) | `JobsDBError` if it persists | transient upstream; retry |
| F7 | Hard GraphQL error (invalid op / schema drift) | `errors[]` with message ≠ `"An error occurred"` | no | `JobsDBError("GraphQL error: …")` | run `jobsdb doctor` to detect drift |
| F8 | Response 200 without `data.<operation>` | `interpret_body` empty node | no | `JobsDBError` | verify `operationName`/contract with `doctor` |
| F9 | Job nonexistent / empty detail payload | `data.jobDetails.job` is null | no | `JobsDBError("Job <id> not found or empty payload")` | verify id; may be expired |
| F10 | High bot-score (`seek-bot-score ≥ 30`) | response header | — (does not raise) | `RateLimiter` widens the interval (×1.5, cap 3×) then recovers gradually (÷1.2) | — |
| F11 | 0 results | `pagination.resultCount == 0` | — | not an error: `SearchResult(total=0, jobs=[])` | — |
| F12 | Search payload shifts shape (drift) | explicit `KeyError` / None-guard in mapping | no | `JobsDBError` or empty fields | `jobsdb doctor` validates the live contract |

## Retry semantics

- `retries` (default 3) applies to F1/F3/F4/F5/F6 (network + http + soft runtime).
  Each attempt sleeps `min(2^attempt + jitter, 15s)`.
- Blocked responses (F2) abort after **one** attempt — retrying an active
  challenge only hurts the IP's reputation.
- Soft runtime errors (F6) retry once with a regenerated `sessionId` because the
  SEEK backend intermittently rejects stale search sessions.
- The `RateLimiter` is thread-safe (uses an internal lock) and its `adapt()`
  method is fed each response's headers so it can widen the interval under pressure.

## Live contract validation

```bash
jobsdb doctor   # exit 0 = contract healthy; exit 1 = drift detected (see summary)
```

The doctor keeps live upstream checks out of the deterministic test suite; the
suite stays offline and green regardless of upstream state.