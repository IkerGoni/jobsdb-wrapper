"""Shared request/response plumbing for sync and async clients."""

from __future__ import annotations

import json
import random
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from .models import (
    SALARY_PERIODS,
    SORT_MODES,
    WORK_ARRANGEMENTS,
    WORK_TYPES,
    JobsDBError,
)

GRAPHQL_PATH = "/graphql"
MARKET_HOSTS = {
    "th": ("th.jobsdb.com", "TH", "en-TH"),
    "hk": ("hk.jobsdb.com", "HK", "en-HK"),
    "my": ("my.jobstreet.com", "MY", "en-MY"),
    "sg": ("sg.jobstreet.com", "SG", "en-SG"),
    "ph": ("ph.jobstreet.com", "PH", "en-PH"),
    "id": ("id.jobstreet.com", "ID", "en-ID"),
}
FEATURES_HEADER = "application/features.seek.all+json"
CHALLENGE_MARKERS = ("Just a moment", "cf-mitigated", "challenge-platform")


def resolve_market(country: str, locale: str | None = None) -> tuple[str, str, str]:
    key = country.lower()
    if key not in MARKET_HOSTS:
        raise JobsDBError(f"Unsupported country {country!r}; use one of {list(MARKET_HOSTS)}")
    host, cc, default_locale = MARKET_HOSTS[key]
    return host, cc, locale or default_locale


def resolve_work_type(value: str | int) -> str | None:
    v = str(value).strip().lower()
    return WORK_TYPES.get(v) or (str(value) if str(value).isdigit() else None)


def resolve_arrangement(value: str | int) -> str | None:
    v = str(value).strip().lower()
    return WORK_ARRANGEMENTS.get(v) or (str(value) if str(value).isdigit() else None)


class RequestError(RuntimeError):
    """Signals the caller should retry with a fresh session context.

    Attributes:
        kind: One of 'network' | 'http' | 'runtime' | 'blocked'
        status: HTTP status code if applicable (None for network errors)
        body_snippet: First 200 chars of response body for diagnostics
    """

    def __init__(self, kind: str, message: str, status: int | None = None, body_snippet: str | None = None):
        self.kind = kind  # 'network' | 'http' | 'runtime' | 'blocked'
        self.status = status
        self.body_snippet = body_snippet
        super().__init__(message)


def build_headers(
    origin: str, referer: str, locale: str, extra: dict[str, str] | None = None
) -> dict[str, str]:
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": origin,
        "Referer": referer,
        "Accept-Language": f"{locale},en;q=0.9",
        "X-Request-Id": str(uuid.uuid4()),
        "x-custom-features": FEATURES_HEADER,
    }
    if extra:
        h.update(extra)
    return h


def classify_response(status: int, text: str) -> Any | RequestError:
    """Turn an HTTP response into parsed JSON or a typed retry signal."""
    if status == 200:
        head = text[:3000]
        if any(m.lower() in head.lower() for m in CHALLENGE_MARKERS) and "jobSearch" not in head:
            return RequestError("blocked", "Cloudflare challenge intercepted the API route", status=200, body_snippet=text[:200])
        try:
            return json.loads(text)
        except Exception:
            return RequestError("network", f"non-JSON 200 body ({len(text)}b)", status=200, body_snippet=text[:200])
    if status == 403:
        return RequestError("blocked", "HTTP 403 (possible Cloudflare block)", status=403, body_snippet=text[:200])
    if status in (429, 502, 503, 504):
        return RequestError("http", f"HTTP {status}", status=status, body_snippet=text[:200])
    return RequestError("http", f"HTTP {status}: {text[:150]}", status=status, body_snippet=text[:200])


def interpret_body(body: dict[str, Any], op: str) -> dict[str, Any]:
    """Validate GraphQL envelope; flag soft runtime errors for session-retry.

    The GraphQL response uses camelCase for operation names:
    - JobSearchV7 -> jobSearchV7
    - JobDetail -> jobDetails  (note: plural in response)
    """
    errors = body.get("errors") or []
    hard = [e for e in errors if e.get("message") != "An error occurred"]
    data = body.get("data") or {}

    # Map operationName to response key (camelCase, with known special cases)
    if op == "JobDetail":
        op_key = "jobDetails"
    else:
        op_key = op[:1].lower() + op[1:] if op else op

    node = data.get(op_key)
    # Missing key entirely = contract drift
    if node is None and op_key not in data:
        if any(e.get("extensions", {}).get("code") == "UNSTABLE_QUERY_ERROR" for e in errors):
            raise RequestError("runtime", "UNSTABLE_QUERY_ERROR (soft backend rejection)")
        if hard:
            raise JobsDBError(
                f"GraphQL error: {hard[0]['message'][:300]}",
                kind="http",
                operation=op,
            )
        raise JobsDBError(
            f"Response 200 missing data.{op_key} (contract drift?)",
            kind="runtime",
            operation=op,
        )

    # Key exists but is None/empty = valid response, caller handles empty payload
    return body


def backoff_sleep(attempt: int, base: float = 2.0, cap: float = 15.0) -> None:
    time.sleep(min(base**attempt + random.random(), cap))


class RateLimiter:
    """Min-interval limiter with optional adaptive slowdown on bot-score headers.

    Thread-safe: `wait()`/`adapt()` may be called from multiple threads
    (the async client runs the limiter in worker threads via asyncio.to_thread).

    Time and sleep are injectable for deterministic testing:
        now_fn: callable returning current monotonic time (default: time.monotonic)
        sleep_fn: callable(seconds) that sleeps (default: time.sleep)
    """

    def __init__(
        self,
        rpm: float,
        now_fn: Callable[[], float] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ):
        self._min_interval = 60.0 / max(rpm, 0.1)
        self._interval = self._min_interval
        self._last = 0.0
        self._lock = threading.Lock()
        self._now = now_fn or time.monotonic
        self._sleep = sleep_fn or time.sleep

    def wait(self) -> None:
        with self._lock:
            now = self._now()
            delta = self._interval - (now - self._last)
            # Reserve the slot while sleeping so concurrent callers serialize
            # instead of all waking at the same instant.
            self._last = max(now, self._last + self._interval)
        if delta > 0:
            self._sleep(delta)

    def adapt(self, headers: dict[str, str]) -> None:
        score = headers.get("seek-bot-score") or headers.get("Seek-Bot-Score")
        if score is None:
            return
        try:
            value = float(score)
        except ValueError:
            return
        with self._lock:
            if value >= 30:
                self._interval = min(self._min_interval * 3, self._interval * 1.5)
            else:
                self._interval = max(self._min_interval, self._interval / 1.2)


# ---------------------------------------------------------------------------
# Search params builder — pure function shared by sync/async clients

VALID_FACETS_V7 = ("categoryV1",)
VALID_SUGGESTIONS_V7 = ("locationV1", "queryParamLabelsV1")


def build_search_params(
    *,
    country_code: str,
    locale: str,
    keywords: str | None = None,
    where: str | list[str] | None = None,
    distance_km: int | None = None,
    work_types: list[str] | None = None,
    work_arrangements: list[str] | None = None,
    salary_min: int | float | None = None,
    salary_max: int | float | None = None,
    salary_period: str = "monthly",
    posted_within_days: int | None = None,
    categories: list[str] | None = None,
    advertiser_id: str | None = None,
    organisation_ids: list[str] | None = None,
    company: str | None = None,
    tags: list[str] | None = None,
    sort: str = "score",
    page: int = 1,
    page_size: int = 20,
    include_facets: bool = False,
    include_suggestions: bool = False,
    session_id: str | None = None,
) -> dict[str, Any]:
    flt: dict[str, Any] = {}
    wts = [w for w in (_resolve_list(work_types, resolve_work_type)) if w]
    if wts:
        flt["workTypeId"] = wts
    arrs = [a for a in (_resolve_list(work_arrangements, resolve_arrangement)) if a]
    if arrs:
        flt["workArrangementId"] = arrs
    suffix = SALARY_PERIODS.get((salary_period or "").lower())
    if salary_min is not None or salary_max is not None:
        if suffix is None:
            raise JobsDBError(f"salary_period must be one of {list(SALARY_PERIODS)}")
        if salary_min is not None:
            flt["salaryMin"] = f"{int(salary_min)}{suffix}"
        if salary_max is not None:
            flt["salaryMax"] = f"{int(salary_max)}{suffix}"
    elif suffix is None and salary_period:
        raise JobsDBError(f"salary_period must be one of {list(SALARY_PERIODS)}")
    if posted_within_days:
        flt["listedAt"] = f"{int(posted_within_days)}d"
    if categories:
        flt["categoryId"] = [str(c) for c in categories]
    if advertiser_id:
        flt["advertiserId"] = [str(advertiser_id)]
    if organisation_ids:
        flt["organisationId"] = [str(o) for o in organisation_ids]
    if company:
        flt["organisationName"] = [company]
    known_tags = {"new", "seen", "viewed", "applied", "applystarted", "sab"}
    tg = [t.lower() for t in (tags or []) if t.lower() in known_tags]
    if tg:
        flt["tags"] = tg

    sm = SORT_MODES.get((sort or "").lower())
    if sm is None:
        raise JobsDBError(f"sort must be one of {list(SORT_MODES)}")

    intent: dict[str, Any] = {
        "text": keywords or "",
        "country": country_code,
        "locale": locale,
        "sort": sm,
    }
    if where:
        intent["where"] = [where] if isinstance(where, str) else list(where)
    if distance_km:
        intent["distanceKms"] = int(distance_km)
    if flt:
        intent["filter"] = flt

    rc: dict[str, Any] = {
        "results": ["jobs"],
        "representations": ["uiV1"],
        "page": max(1, page),
        "pageSize": min(max(1, page_size), 30),
    }
    enrichment: dict[str, Any] = {}
    if include_facets:
        enrichment["facets"] = list(VALID_FACETS_V7)
    if include_suggestions:
        enrichment["suggestions"] = list(VALID_SUGGESTIONS_V7)
    if enrichment:
        rc["enrichment"] = enrichment

    return {
        "sessionId": session_id or str(uuid.uuid4()),
        "searchContext": {
            "brand": "seek",
            "channel": "web",
            "intent": "SEARCH",
            "source": "OTHER",
        },
        "responseConfig": rc,
        "searchIntent": intent,
    }


def _resolve_list(values: list[str] | None, fn) -> list[str | None]:
    return [fn(v) for v in (values or [])]
