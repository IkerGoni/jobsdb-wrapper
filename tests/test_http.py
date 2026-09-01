import sys
from pathlib import Path

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
