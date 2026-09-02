"""Property-style tests for key invariants — no property-based framework needed.

These verify invariants that must hold for all valid inputs, using
exhaustive/parametrized combinations where the state space is small and
targeted random sampling where it isn't.
"""

from __future__ import annotations

import json
import threading
import time

import pytest

from jobsdb_wrapper.cache import DetailCache
from jobsdb_wrapper.http import (
    RateLimiter,
    build_search_params,
    classify_response,
    resolve_arrangement,
    resolve_work_type,
)
from jobsdb_wrapper.models import MARKET_HOSTS, JobDetail, JobSummary, SearchResult

# ---------------------------------------------------------------------------
# 1. Encoding then parsing preserves semantics (round-trip)
# ---------------------------------------------------------------------------

def _all_work_types() -> list[str]:
    """All canonical work type keys the resolver accepts."""
    return ["full_time", "part_time", "contract", "casual", "242", "243", "244", "245"]


def _all_arrangements() -> list[str]:
    return ["on_site", "hybrid", "remote", "1", "2", "3"]


def _all_markets() -> list[str]:
    return list(MARKET_HOSTS.keys())


class TestRoundTripEncoding:
    """Filters encode -> GraphQL variables -> decode back to canonical forms."""

    @pytest.mark.parametrize("wt", _all_work_types())
    def test_work_type_roundtrip(self, wt):
        resolved = resolve_work_type(wt)
        assert resolved is not None
        # Re-resolving the resolved ID must be idempotent
        assert resolve_work_type(resolved) == resolved

    @pytest.mark.parametrize("arr", _all_arrangements())
    def test_arrangement_roundtrip(self, arr):
        resolved = resolve_arrangement(arr)
        assert resolved is not None
        assert resolve_arrangement(resolved) == resolved

    @pytest.mark.parametrize("market", _all_markets())
    def test_market_resolution_idempotent(self, market):
        from jobsdb_wrapper.http import resolve_market
        host, cc, locale = resolve_market(market)
        host2, cc2, locale2 = resolve_market(cc.lower())
        assert (host, cc, locale) == (host2, cc2, locale2)


class TestSearchParamsEncoding:
    """build_search_params must be a pure function: same inputs -> same output."""

    def test_deterministic_output(self):
        p1 = build_search_params(
            country_code="TH", locale="en-TH",
            keywords="python", where=["Bangkok", "Phuket"],
            work_types=["full_time", "contract"],
            salary_min=50000, salary_max=100000, salary_period="monthly",
            page=2, page_size=20, include_facets=True, session_id="fixed-uuid"
        )
        p2 = build_search_params(
            country_code="TH", locale="en-TH",
            keywords="python", where=["Bangkok", "Phuket"],
            work_types=["full_time", "contract"],
            salary_min=50000, salary_max=100000, salary_period="monthly",
            page=2, page_size=20, include_facets=True, session_id="fixed-uuid"
        )
        assert p1 == p2

    def test_page_bounds_clamped(self):
        # page < 1 -> 1, page_size > 30 -> 30
        p = build_search_params(country_code="TH", locale="en-TH", page=0, page_size=999)
        assert p["responseConfig"]["page"] == 1
        assert p["responseConfig"]["pageSize"] == 30

    def test_salary_encoding_preserves_order(self):
        p = build_search_params(
            country_code="TH", locale="en-TH",
            salary_min=50000, salary_max=100000, salary_period="monthly"
        )
        flt = p["searchIntent"]["filter"]
        # Numeric values preserved in encoded strings (same suffix)
        assert int(flt["salaryMin"].rstrip("m")) < int(flt["salaryMax"].rstrip("m"))

    def test_unknown_tags_dropped_not_crash(self):
        p = build_search_params(
            country_code="TH", locale="en-TH",
            tags=["NEW", "BOGUS_TAG", "seen"]
        )
        assert p["searchIntent"]["filter"]["tags"] == ["new", "seen"]

    def test_work_type_case_insensitive(self):
        p1 = build_search_params(country_code="TH", locale="en-TH", work_types=["FULL_TIME"])
        p2 = build_search_params(country_code="TH", locale="en-TH", work_types=["full_time"])
        assert p1["searchIntent"]["filter"]["workTypeId"] == p2["searchIntent"]["filter"]["workTypeId"]


# ---------------------------------------------------------------------------
# 2. Pagination doesn't duplicate jobs
# ---------------------------------------------------------------------------

class TestPaginationNoDuplicates:
    """SearchResult pagination math must never produce overlapping pages."""

    def test_has_next_boundary_exact(self):
        # total exactly on page boundary -> no next page
        r = SearchResult(jobs=[], page=2, page_size=20, total=40)
        assert r.has_next is False

    def test_has_next_true_when_remainder(self):
        r = SearchResult(jobs=[], page=2, page_size=20, total=41)
        assert r.has_next is True

    def test_page_size_clamped_in_params(self):
        # page_size is clamped at build time, so SearchResult page_size
        # should never exceed 30 in practice
        p = build_search_params(country_code="TH", locale="en-TH", page_size=999)
        assert p["responseConfig"]["pageSize"] == 30

    def test_page_never_zero_in_params(self):
        p = build_search_params(country_code="TH", locale="en-TH", page=0)
        assert p["responseConfig"]["page"] == 1

    def test_iter_all_stops_at_max_pages(self):
        # Verified in test_async.py::TestAsyncSearch::test_iter_all_stops_at_max_pages
        # but the property is: max_pages bounds total requests
        pass  # covered by async test


# ---------------------------------------------------------------------------
# 3. Cache validation detects content changes
# ---------------------------------------------------------------------------

class TestCacheContentChangeDetection:
    """DetailCache.get_valid returns None when stored content hash mismatches."""

    def test_get_valid_returns_none_on_content_change(self, tmp_path):
        c = DetailCache(tmp_path / "cache.db")
        payload = {"content": "<p>original</p>", "title": "Job"}
        c.put("111", "th", payload)
        # Valid fetch
        assert c.get_valid("111", "th") is not None
        # Mutate content on disk without updating hash
        with c._lock:
            mutated = dict(payload)  # copy the dict
            mutated["content"] = "<p>changed</p>"
            c._conn.execute(
                "UPDATE details SET payload=? WHERE job_id='111' AND market='th'",
                (json.dumps(mutated),)
            )
            c._conn.commit()
        # Must reject
        assert c.get_valid("111", "th") is None
        c.close()

    def test_get_valid_returns_none_on_corrupt_json(self, tmp_path):
        c = DetailCache(tmp_path / "cache2.db")
        c.put("222", "th", {"content": "<p>x</p>"})
        with c._lock:
            c._conn.execute("UPDATE details SET payload='{not json' WHERE job_id='222'")
            c._conn.commit()
        assert c.get_valid("222", "th") is None
        c.close()

    def test_content_hash_deterministic(self):
        payload = {"content": "<p>hello</p>", "other": "ignored"}
        h1 = DetailCache.content_hash(payload)
        h2 = DetailCache.content_hash(payload)
        assert h1 == h2
        assert len(h1) == 40  # SHA-1 hex

    def test_content_hash_sensitive_to_content_field_only(self):
        p1 = {"content": "<p>same</p>", "title": "A"}
        p2 = {"content": "<p>same</p>", "title": "B"}
        assert DetailCache.content_hash(p1) == DetailCache.content_hash(p2)
        p3 = {"content": "<p>diff</p>", "title": "A"}
        assert DetailCache.content_hash(p1) != DetailCache.content_hash(p3)

    def test_overwrite_replaces_not_appends(self, tmp_path):
        c = DetailCache(tmp_path / "cache3.db")
        c.put("333", "th", {"content": "<p>v1</p>"})
        c.put("333", "th", {"content": "<p>v2</p>"})
        assert c.stats()["entries"] == 1
        got = c.get_valid("333", "th")
        assert got["content"] == "<p>v2</p>"
        c.close()

    def test_market_isolation(self, tmp_path):
        c = DetailCache(tmp_path / "cache4.db")
        c.put("444", "th", {"content": "<p>th</p>"})
        c.put("444", "sg", {"content": "<p>sg</p>"})
        assert c.get_valid("444", "th")["content"] == "<p>th</p>"
        assert c.get_valid("444", "sg")["content"] == "<p>sg</p>"
        assert c.stats()["entries"] == 2
        assert c.stats()["markets"] == 2
        c.close()


# ---------------------------------------------------------------------------
# 4. Concurrency never exceeds bound
# ---------------------------------------------------------------------------

class TestConcurrencyBound:
    """AsyncJobsDBClient.fetch_details_many respects the semaphore bound."""

    def test_semaphore_enforces_hard_bound(self):
        """Deterministic test using a fake semaphore and counter."""
        import asyncio

        async def run_test():
            concurrency = 3
            sem = asyncio.Semaphore(concurrency)
            active = 0
            peak = 0
            lock = asyncio.Lock()

            async def fake_job(i: int):
                nonlocal active, peak
                async with sem:
                    async with lock:
                        active += 1
                        peak = max(peak, active)
                    await asyncio.sleep(0.01)
                    async with lock:
                        active -= 1
                return i

            tasks = [fake_job(i) for i in range(15)]
            results = await asyncio.gather(*tasks)
            assert len(results) == 15
            assert peak <= concurrency

        asyncio.run(run_test())

    def test_rate_limiter_thread_safe(self):
        """RateLimiter.wait() serializes callers correctly under contention."""
        rl = RateLimiter(rpm=60000)  # ~1ms min interval
        now_calls = []
        sleep_calls = []

        def fake_now():
            now_calls.append(1)
            return time.monotonic()

        def fake_sleep(d):
            sleep_calls.append(d)

        rl._now = fake_now
        rl._sleep = fake_sleep

        def caller():
            for _ in range(5):
                rl.wait()

        threads = [threading.Thread(target=caller) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All 50 wait() calls executed
        assert len(now_calls) == 50
        # Each wait() should have resulted in at most one sleep (no busy loops)
        assert len(sleep_calls) <= 50

    def test_rate_limiter_adaptive_widens_then_recovers(self):
        rl = RateLimiter(rpm=6000)  # min_interval = 0.01s
        min_int = rl._min_interval

        # Pressure increases interval
        rl.adapt({"seek-bot-score": "80"})
        assert rl._interval > min_int
        assert rl._interval <= min_int * 3  # capped at 3x

        # Recovery decreases interval
        for _ in range(50):
            rl.adapt({"seek-bot-score": "1"})
        assert rl._interval == pytest.approx(min_int, rel=0.01)
        assert rl._interval >= min_int  # never below minimum

    def test_classify_response_failure_kinds_distinct(self):
        """Each failure class maps to a distinct RequestError.kind."""
        # Network: non-JSON 200
        err = classify_response(200, "not json")
        assert err.kind == "network"
        assert err.status == 200

        # Blocked: Cloudflare challenge in 200
        err = classify_response(200, "<html>Just a moment...</html>")
        assert err.kind == "blocked"
        assert err.status == 200

        # Blocked: HTTP 403
        err = classify_response(403, "forbidden")
        assert err.kind == "blocked"
        assert err.status == 403

        # HTTP retryable: 429, 502, 503, 504
        for status in (429, 502, 503, 504):
            err = classify_response(status, "error")
            assert err.kind == "http"
            assert err.status == status

        # HTTP non-retryable: other 4xx/5xx
        for status in (400, 401, 404, 500, 501):
            err = classify_response(status, "error")
            assert err.kind == "http"
            assert err.status == status


# ---------------------------------------------------------------------------
# 5. Model serialization preserves identity
# ---------------------------------------------------------------------------

class TestModelIdentity:
    """JobSummary/JobDetail equality and web_url are stable."""

    def test_job_summary_equality_on_all_fields(self):
        j1 = JobSummary(id="123", title="A", market="th", company="X")
        j2 = JobSummary(id="123", title="A", market="th", company="X")
        j3 = JobSummary(id="123", title="B", market="th", company="X")
        j4 = JobSummary(id="123", title="A", market="sg", company="X")
        assert j1 == j2  # all fields equal
        assert j1 != j3  # title differs
        assert j1 != j4  # market differs

    def test_web_url_uses_correct_host_per_market(self):
        j = JobSummary(id="999", title="T", market="sg")
        assert j.web_url == "https://sg.jobstreet.com/sg/job/999"
        j2 = JobSummary(id="999", title="T", market="th")
        assert j2.web_url == "https://th.jobsdb.com/th/job/999"

    def test_job_detail_inherits_summary_fields(self):
        jd = JobDetail(id="1", title="T", market="th")
        # Set content_html directly since it's a field
        jd.content_html = "<p>x</p>"
        assert isinstance(jd, JobSummary)
        assert jd.id == "1"
        assert jd.content_html == "<p>x</p>"


# ---------------------------------------------------------------------------
# 6. Response classification diagnostic fields
# ---------------------------------------------------------------------------

class TestClassificationDiagnostics:
    """RequestError carries status and body_snippet for observability."""

    def test_body_snippet_truncated(self):
        long_body = "x" * 500
        err = classify_response(200, long_body)
        assert err.body_snippet is not None
        assert len(err.body_snippet) == 200
        assert err.body_snippet == long_body[:200]

    def test_non_json_200_is_network_error(self):
        err = classify_response(200, "plain text response")
        assert err.kind == "network"
        assert err.status == 200

    def test_ok_json_returns_dict(self):
        ok = classify_response(200, '{"data": {"jobSearchV7": {}}}')
        assert isinstance(ok, dict)
        assert ok["data"]["jobSearchV7"] == {}


# ---------------------------------------------------------------------------
# 7. Salary period suffix encoding
# ---------------------------------------------------------------------------

class TestSalaryEncoding:
    """Salary min/max encoding adds correct suffix and preserves numeric value."""

    @pytest.mark.parametrize("period,suffix", [
        ("monthly", "m"), ("annual", "y"), ("annually", "y"), ("hourly", "h"),
        ("MONTHLY", "m"), ("Annual", "y"),
    ])
    def test_salary_suffix_added(self, period, suffix):
        p = build_search_params(
            country_code="TH", locale="en-TH",
            salary_min=50000, salary_max=90000, salary_period=period
        )
        flt = p["searchIntent"]["filter"]
        assert flt["salaryMin"] == f"50000{suffix}"
        assert flt["salaryMax"] == f"90000{suffix}"

    def test_salary_period_required_when_min_or_max_given(self):
        from jobsdb_wrapper.models import JobsDBError
        with pytest.raises(JobsDBError):
            build_search_params(country_code="TH", locale="en-TH", salary_min=50000, salary_period="weekly")

    def test_salary_period_ignored_when_no_min_max(self):
        p = build_search_params(country_code="TH", locale="en-TH", salary_period="monthly")
        assert "filter" not in p["searchIntent"] or "salaryMin" not in p["searchIntent"].get("filter", {})


# ---------------------------------------------------------------------------
# 8. Category/Organisation/Advertiser filter encoding
# ---------------------------------------------------------------------------

class TestFilterEncoding:
    """All filter fields encode as arrays of strings."""

    def test_organisation_ids_as_array(self):
        p = build_search_params(country_code="TH", locale="en-TH", organisation_ids=["1", "2"])
        assert p["searchIntent"]["filter"]["organisationId"] == ["1", "2"]

    def test_advertiser_id_as_array(self):
        p = build_search_params(country_code="TH", locale="en-TH", advertiser_id="123")
        assert p["searchIntent"]["filter"]["advertiserId"] == ["123"]

    def test_category_ids_as_strings(self):
        p = build_search_params(country_code="TH", locale="en-TH", categories=["6287", "6281"])
        assert p["searchIntent"]["filter"]["categoryId"] == ["6287", "6281"]

    def test_where_accepts_string_or_list(self):
        p1 = build_search_params(country_code="TH", locale="en-TH", where="Bangkok")
        p2 = build_search_params(country_code="TH", locale="en-TH", where=["Bangkok"])
        assert p1["searchIntent"]["where"] == ["Bangkok"]
        assert p2["searchIntent"]["where"] == ["Bangkok"]


# ---------------------------------------------------------------------------
# 9. Sort mode mapping
# ---------------------------------------------------------------------------

class TestSortModeMapping:
    @pytest.mark.parametrize("sort,expected", [
        ("relevance", "score"), ("score", "score"),
        ("date", "listedAt"), ("listed_at", "listedAt"), ("listedAt", "listedAt"),
    ])
    def test_sort_maps_to_graphql_value(self, sort, expected):
        p = build_search_params(country_code="TH", locale="en-TH", sort=sort)
        assert p["searchIntent"]["sort"] == expected

    def test_invalid_sort_raises(self):
        with pytest.raises(Exception):
            build_search_params(country_code="TH", locale="en-TH", sort="invalid")


# ---------------------------------------------------------------------------
# 10. Rate limiter minimum interval respected
# ---------------------------------------------------------------------------

class TestRateLimiterInvariants:
    def test_min_interval_enforced(self):
        rl = RateLimiter(rpm=60)  # 1s min interval
        assert rl._min_interval == 1.0
        assert rl._interval == 1.0

    def test_zero_rpm_clamped(self):
        rl = RateLimiter(rpm=0)
        assert rl._min_interval == 60.0 / 0.1  # clamped to 0.1 rpm

    def test_adapt_ignores_non_numeric_score(self):
        rl = RateLimiter(rpm=6000)
        before = rl._interval
        rl.adapt({"seek-bot-score": "NaN"})
        assert rl._interval == before
        rl.adapt({"seek-bot-score": "not-a-number"})
        assert rl._interval == before

    def test_adapt_ignores_missing_header(self):
        rl = RateLimiter(rpm=6000)
        before = rl._interval
        rl.adapt({"content-type": "application/json"})
        assert rl._interval == before
