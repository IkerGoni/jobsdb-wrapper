"""Critical-path tests for the core group (client / http / doctor / cli).

All network access is faked at the curl_cffi Session boundary so these run
offline and fast. Focus: the sync client lifecycle, graphql interpretation,
search param wiring, and CLI smoke paths.
"""
from __future__ import annotations

import argparse
import json
from unittest.mock import MagicMock

import pytest

import jobsdb_wrapper
from jobsdb_wrapper import JobsDBError
from jobsdb_wrapper.client import JobsDBClient
from jobsdb_wrapper.http import (
    RateLimiter,
    RequestError,
    build_search_params,
    classify_response,
    interpret_body,
)

# --------------------------------------------------------------------- fixtures

def _fake_response(status=200, json_body=None, text=None):
    r = MagicMock()
    r.status_code = status
    r.headers = {}
    if json_body is not None:
        r.text = json.dumps(json_body)
        r.json = lambda: json_body
    else:
        r.text = text or ""
    return r


def _search_body(n_jobs=2, total=50, suggestions=None):
    jobs = [{
        "id": str(1000 + i),
        "title": f"Job {i}",
        "advertiser": {"name": f"Company {i}"},
        "location": {"displayName": {"text": "Bangkok"}},
        "listedAt": {"dateTimeUtc": "2026-08-30T00:00:00Z"},
        "salary": {"min": 30000, "max": 50000, "currency": "THB",
                   "period": "monthly"},
        "workArrangements": [{"label": {"text": "remote"}}],
        "abstract": "abstract",
        "categories": [{"id": 6227, "label": "IT"}],
    } for i in range(n_jobs)]
    enrichment = {}
    if suggestions is not None:
        enrichment["suggestions"] = {"locationV1": suggestions}
    return {"data": {"jobSearchV7": {
        "results": {"jobs": jobs,
                    "pagination": {"page": 1, "pageSize": 20,
                                   "resultCount": total}},
        "enrichment": enrichment}}}


def _patch_session(client, response):
    """Patch the client's session post() to return a canned response."""
    sess = MagicMock()
    sess.post.return_value = response
    sess.close = MagicMock()
    client._session = sess
    return sess


# ------------------------------------------------------------------- lifecycle

class TestClientLifecycle:
    def test_init_resolves_market(self):
        with JobsDBClient() as c:
            assert c.host == "th.jobsdb.com"
            assert c.country_code == "TH"
            assert c.graphql_url == "https://th.jobsdb.com/graphql"

    def test_unknown_market_raises(self):
        with pytest.raises(JobsDBError):
            JobsDBClient(country="zz")

    def test_context_manager_closes_session(self):
        with JobsDBClient() as c:
            c._session = MagicMock()
            sess = c._session
        sess.close.assert_called_once()
        assert c._session is None

    def test_headers_guest_mode(self):
        with JobsDBClient() as c:
            anon = c._headers()
            assert "x-seek-site" not in anon
            assert "Cookie" not in anon


# ------------------------------------------------------------------- graphql

class TestGraphqlRetry:
    def test_graphql_happy_path(self):
        with JobsDBClient() as c:
            sess = _patch_session(c, _fake_response(200, _search_body(1)))
            body = c.graphql("query Q {}", {}, "JobSearchV7")
            assert body["data"]["jobSearchV7"]["results"]["jobs"]
            assert sess.post.call_count == 1

    def test_graphql_retries_on_block_then_raises(self):
        with JobsDBClient() as c:
            _patch_session(c, _fake_response(403, "<html>Just a moment</html>"))
            c.retries = 1
            with pytest.raises(JobsDBError):
                c.graphql("query Q {}", {}, "JobSearchV7")

    def test_hard_graphql_error_raises(self):
        with JobsDBClient() as c:
            _patch_session(c, _fake_response(200, {
                "errors": [{"message": "bad op"}]}))
            with pytest.raises(JobsDBError, match="bad op"):
                c.graphql("query Q {}", {}, "JobSearchV7")


# --------------------------------------------------------------------- search

class TestSearch:
    def test_search_parses_summaries(self):
        with JobsDBClient() as c:
            _patch_session(c, _fake_response(200, _search_body(2, total=7)))
            res = c.search(keywords="python")
            assert res.total == 7
            assert len(res.jobs) == 2
            assert res.jobs[0].title == "Job 0"
            assert res.jobs[0].company == "Company 0"
            assert res.jobs[0].location == "Bangkok"

    def test_search_passes_filters_to_params(self):
        with JobsDBClient() as c:
            sess = _patch_session(c, _fake_response(200, _search_body(0)))
            c.search(keywords="dev", where="Bangkok", salary_min=1000,
                     posted_within_days=7)
            payload = sess.post.call_args.kwargs["json"]
            params = payload["variables"]["params"]
            assert params["searchIntent"]["text"] == "dev"
            assert params["searchIntent"]["where"] == ["Bangkok"]
            assert params["searchIntent"]["filter"]["salaryMin"] == "1000m"
            assert params["searchIntent"]["filter"]["listedAt"] == "7d"
            assert params["searchIntent"]["sort"] == "score"

    def test_search_raises_on_http_error(self):
        with JobsDBClient() as c:
            _patch_session(c, _fake_response(500, "boom"))
            c.retries = 0
            with pytest.raises(JobsDBError):
                c.search()

    def test_search_suggestions_id_kind(self):
        """H2 contract (live-verified): completions carry id+kind; label is
        withheld by the API unless an undocumented enum context is supplied."""
        body = _search_body(0, total=0, suggestions={
            "local": {"completions": [
                {"id": "1000008", "kind": "SEEK_AREA"},
                {"id": "47516", "kind": "REGION"},
            ]},
            "international": {"completions": []},
        })
        with JobsDBClient() as c:
            _patch_session(c, _fake_response(200, body))
            res = c.search(keywords="", where="bangkok",
                           include_suggestions=True, page_size=1)
            assert [(s.id, s.kind) for s in res.suggestions] == [
                ("1000008", "SEEK_AREA"), ("47516", "REGION")]
            assert all(s.label == "" for s in res.suggestions)
            # locations() routes the prefix through `where`
            sess = _patch_session(c, _fake_response(200, body))
            locs = c.locations("bangkok")
            payload = sess.post.call_args.kwargs["json"]
            assert payload["variables"]["params"]["searchIntent"]["where"] == ["bangkok"]
            assert locs[0].id == "1000008"

    def test_job_detail(self):
        with JobsDBClient() as c:
            body = {"data": {"jobDetails": {"job": {
                "id": "94301059", "title": "Software Engineer",
                "content": "<p>x</p>"}}}}
            _patch_session(c, _fake_response(200, body))
            jd = c.job("94301059")
            assert jd.id == "94301059"
            assert jd.content_html == "<p>x</p>"

    def test_job_detail_empty_raises(self):
        with JobsDBClient() as c:
            _patch_session(c, _fake_response(200, {"data": {"jobDetails": {}}}))
            with pytest.raises(JobsDBError, match="not found"):
                c.job("123")


# --------------------------------------------------------------- search params

class TestSearchParams:
    def test_page_bounds(self):
        p = build_search_params(country_code="TH", locale="en",
                                page=0, page_size=999)
        assert p["responseConfig"]["page"] == 1
        assert p["responseConfig"]["pageSize"] == 30

    def test_salary_period_invalid(self):
        with pytest.raises(JobsDBError):
            build_search_params(country_code="TH", locale="en",
                                salary_period="weekly")

    def test_sort_mode(self):
        p = build_search_params(country_code="TH", locale="en", sort="date")
        assert p["searchIntent"]["sort"] == "listedAt"

    def test_facets_enrichment(self):
        p = build_search_params(country_code="TH", locale="en",
                                include_facets=True)
        assert "facets" in p["responseConfig"]["enrichment"]


# --------------------------------------------------------------------- http

class TestHttp:
    def test_classify_blocked(self):
        assert isinstance(classify_response(403, ""), RequestError)
        assert isinstance(classify_response(429, ""), RequestError)
        assert isinstance(classify_response(200, "Just a moment..."),
                          RequestError)

    def test_classify_ok(self):
        assert classify_response(200, '{"data": 1}') == {"data": 1}

    def test_interpret_body_hard_error(self):
        with pytest.raises(JobsDBError, match="bad"):
            interpret_body({"errors": [{"message": "bad"}]}, "Op")

    def test_interpret_body_soft_runtime_error(self):
        with pytest.raises(RequestError) as ei:
            interpret_body(
                {"errors": [{"message": "An error occurred",
                             "extensions": {"code": "UNSTABLE_QUERY_ERROR"}}]},
                "Op")
        assert ei.value.kind == "runtime"

    def test_interpret_body_ok(self):
        body = {"data": {"Op": {"x": 1}}}
        assert interpret_body(body, "Op") is body

    def test_rate_limiter_never_negative(self):
        RateLimiter(60000).wait()  # must not raise


# ---------------------------------------------------------------------- CLI

class TestCli:
    def _args(self, **kw):
        return argparse.Namespace(**kw)

    def test_version_exposed(self):
        assert jobsdb_wrapper.__version__

    def test_doctor_healthy_check_dataclass(self):
        from jobsdb_wrapper.doctor import CheckResult, DoctorReport
        rep = DoctorReport()
        rep.results = [CheckResult("a", True, "ok"),
                       CheckResult("b", False, "bad")]
        assert not rep.healthy
        assert "DRIFT DETECTED" in rep.summary()
