import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jobsdb_wrapper.http import (  # noqa: E402
    RateLimiter,
    RequestError,
    build_headers,
    build_search_params,
    classify_response,
    resolve_market,
)
from jobsdb_wrapper.models import JobsDBError  # noqa: E402


def test_resolve_market():
    host, cc, loc = resolve_market("sg")
    assert host == "sg.jobstreet.com" and cc == "SG" and loc == "en-SG"
    host, cc, loc = resolve_market("th", "th-TH")
    assert loc == "th-TH"
    try:
        resolve_market("us")
        raised = False
    except JobsDBError:
        raised = True
    assert raised


def test_build_headers_contract():
    h = build_headers("https://th.jobsdb.com", "https://th.jobsdb.com/th/jobs", "en-TH")
    assert h["x-custom-features"] == "application/features.seek.all+json"
    assert "X-Request-Id" in h and "Origin" in h


def test_classify_challenge():
    err = classify_response(200, "<html>Just a moment...</html>")
    assert isinstance(err, RequestError) and err.kind == "blocked"
    err2 = classify_response(403, "denied")
    assert err2.kind == "blocked"
    err3 = classify_response(429, "")
    assert err3.kind == "http"
    ok = classify_response(200, '{"data":{}}')
    assert isinstance(ok, dict)


def test_search_params_full_surface():
    p = build_search_params(
        country_code="TH",
        locale="en-TH",
        keywords="dev",
        where=["Bangkok"],
        distance_km=25,
        work_types=["full_time", "244"],
        work_arrangements=["remote"],
        salary_min=50000,
        salary_max=90000,
        salary_period="monthly",
        posted_within_days=14,
        categories=["6281"],
        advertiser_id="1",
        organisation_ids=["2"],
        company="ACME",
        tags=["NEW", "bogus"],
        sort="date",
        page=2,
        page_size=99,
        include_facets=True,
        include_suggestions=True,
        session_id="fixed",
    )
    intent = p["searchIntent"]
    flt = intent["filter"]
    assert flt["workTypeId"] == ["242", "244"]
    assert flt["workArrangementId"] == ["3"]
    assert flt["salaryMin"] == "50000m" and flt["salaryMax"] == "90000m"
    assert flt["listedAt"] == "14d"
    assert flt["categoryId"] == ["6281"]
    assert flt["advertiserId"] == ["1"]
    assert flt["organisationId"] == ["2"]
    assert flt["organisationName"] == ["ACME"]
    assert flt["tags"] == ["new"]  # bogus dropped
    assert intent["sort"] == "listedAt"
    assert intent["where"] == ["Bangkok"] and intent["distanceKms"] == 25
    rc = p["responseConfig"]
    assert rc["pageSize"] == 30  # clamped
    assert rc["enrichment"]["facets"] == ["categoryV1"]
    assert "locationV1" in rc["enrichment"]["suggestions"]
    assert p["sessionId"] == "fixed"


def test_salary_period_required_only_when_used():
    p = build_search_params(country_code="TH", locale="en-TH")
    assert "filter" not in p["searchIntent"]
    try:
        build_search_params(
            country_code="TH", locale="en-TH", salary_min=100, salary_period="weekly"
        )
        raised = False
    except JobsDBError:
        raised = True
    assert raised


def test_rate_limiter_adaptive():
    rl = RateLimiter(rpm=6000)  # tiny interval for test speed
    rl.wait()
    before = rl._interval
    rl.adapt({"seek-bot-score": "80"})
    assert rl._interval > before
    rl.adapt({"seek-bot-score": "5"})
    assert rl._interval < before * 3


def test_rate_limiter_initial_interval_from_rpm():
    rl = RateLimiter(rpm=120)
    assert rl._min_interval == 0.5
    assert rl._interval == 0.5
    rl2 = RateLimiter(rpm=6000)
    assert rl2._min_interval == 60 / 6000


def test_rate_limiter_noop_without_seek_bot_score():
    rl = RateLimiter(rpm=6000)
    before = rl._interval
    rl.adapt({"content-type": "application/json"})  # no seek-bot-score header
    assert rl._interval == before


def test_rate_limiter_ignores_non_numeric_score():
    rl = RateLimiter(rpm=6000)
    before = rl._interval
    rl.adapt({"seek-bot-score": "NaN"})
    assert rl._interval == before


def test_rate_limiter_caps_at_3x_minimum():
    rl = RateLimiter(rpm=6000)
    for _ in range(10):
        rl.adapt({"seek-bot-score": "99"})
    assert rl._interval <= rl._min_interval * 3


def test_rate_limiter_recovers_but_never_below_minimum():
    rl = RateLimiter(rpm=6000)
    rl.adapt({"seek-bot-score": "99"})  # widen
    assert rl._interval > rl._min_interval
    for _ in range(50):
        rl.adapt({"seek-bot-score": "1"})  # recover
    assert rl._interval == pytest.approx(rl._min_interval)
    assert rl._interval >= rl._min_interval


def test_rate_limiter_wait_respects_interval_deterministic():
    """wait() enforces min interval using injectable time/sleep — no real sleep."""
    clock = [0.0]
    sleeps = []

    def now_fn() -> float:
        return clock[0]

    def sleep_fn(delta: float) -> None:
        sleeps.append(delta)
        clock[0] += delta

    rl = RateLimiter(rpm=60, now_fn=now_fn, sleep_fn=sleep_fn)  # 1.0s interval
    rl.wait()  # first call, _last=0 -> delta = 1.0 - 0 = 1.0
    assert sleeps == [1.0]
    assert clock[0] == 1.0

    clock[0] = 1.5  # advance time 0.5s past the reserved slot
    rl.wait()  # delta = 1.0 - (1.5 - 1.0) = 0.5
    assert sleeps == [1.0, 0.5]
    assert clock[0] == 2.0


def test_rate_limiter_wait_no_sleep_when_past_due():
    """wait() sleeps 0 when enough time has already elapsed."""
    clock = [10.0]
    sleeps = []

    def now_fn() -> float:
        return clock[0]

    def sleep_fn(delta: float) -> None:
        sleeps.append(delta)
        clock[0] += delta

    rl = RateLimiter(rpm=60, now_fn=now_fn, sleep_fn=sleep_fn)  # 1.0s interval
    # Simulate that a request already happened at t=0 (so _last=0, interval=1)
    # Now at t=10, wait() should see delta = 1 - (10 - 0) = -9 -> no sleep
    rl.wait()
    assert sleeps == []


def test_rate_limiter_concurrent_wait_serializes_with_fake_time():
    """Concurrent wait() calls serialize correctly (using lock) with fake time."""
    import threading

    clock = [0.0]
    sleeps = []
    lock = threading.Lock()

    def now_fn() -> float:
        return clock[0]

    def sleep_fn(delta: float) -> None:
        with lock:
            sleeps.append(delta)
        clock[0] += delta

    rl = RateLimiter(rpm=6000, now_fn=now_fn, sleep_fn=sleep_fn)  # 0.01s interval

    def worker():
        rl.wait()

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 5 calls -> 5 sleeps of 0.01 each (serialized)
    assert len(sleeps) == 5
    assert all(s == pytest.approx(0.01) for s in sleeps)
    assert clock[0] == pytest.approx(0.05)


def test_classify_response_diagnostic_fields():
    """RequestError should carry status and body_snippet for diagnostics."""
    # Cloudflare challenge in 200
    err = classify_response(200, "<html>Just a moment...</html>")
    assert err.kind == "blocked"
    assert err.status == 200
    assert "Just a moment" in err.body_snippet

    # HTTP 403
    err = classify_response(403, "forbidden access")
    assert err.kind == "blocked"
    assert err.status == 403
    assert "forbidden" in err.body_snippet

    # HTTP 429
    err = classify_response(429, "rate limited")
    assert err.kind == "http"
    assert err.status == 429
    assert "rate limited" in err.body_snippet

    # Non-JSON 200
    err = classify_response(200, "not json at all")
    assert err.kind == "network"
    assert err.status == 200
    assert "not json at all" == err.body_snippet

    # 500
    err = classify_response(500, "server error")
    assert err.kind == "http"
    assert err.status == 500


def test_zero_results_not_error():
    """F11: 0 results is not an error, returns empty SearchResult."""
    import json
    from unittest.mock import MagicMock

    from jobsdb_wrapper.client import JobsDBClient

    def _fake_response(status=200, json_body=None):
        r = MagicMock()
        r.status_code = status
        r.headers = {}
        if json_body is not None:
            r.text = json.dumps(json_body)
            r.json = lambda: json_body
        else:
            r.text = ""
        return r

    def _patch_session(client, response):
        """Patch the client's session post() to return a canned response."""
        _ = MagicMock()
        _.post.return_value = response
        _.close = MagicMock()
        client._session = _

    body = {
        "data": {
            "jobSearchV7": {
                "results": {
                    "jobs": [],
                    "pagination": {"page": 1, "pageSize": 20, "resultCount": 0},
                }
            }
        }
    }

    with JobsDBClient() as c:
        _patch_session(c, _fake_response(200, body))
        res = c.search(keywords="nonexistent")
        assert res.total == 0
        assert res.jobs == []
