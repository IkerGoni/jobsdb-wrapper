"""Async client tests: bounded concurrency, failure isolation, lifecycle.

All requests are faked by replacing `graphql` with a local coroutine, so
these run offline and deterministically (no real upstream timing).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from jobsdb_wrapper.async_client import AsyncJobsDBClient


def _search_body(page=1, ids=(1,), total=100):
    jobs = [
        {
            "id": str(i),
            "title": f"Job {i}",
            "advertiser": {"name": f"Company {i}"},
            "location": {"displayName": {"text": "Bangkok"}},
            "listedAt": {"dateTimeUtc": "2026-08-30T00:00:00Z"},
            "salary": {"min": 30000, "max": 50000, "currency": "THB", "period": "monthly"},
            "workArrangements": [],
            "categories": [],
        }
        for i in ids
    ]
    return {
        "data": {
            "jobSearchV7": {
                "results": {
                    "jobs": jobs,
                    "pagination": {"page": page, "pageSize": 20, "resultCount": total},
                }
            }
        }
    }


def _detail_body(job_id, title="T", content="<p>x</p>"):
    return {"data": {"jobDetails": {"job": {"id": str(job_id), "title": title, "content": content}}}}


class TestBoundedConcurrency:
    async def test_concurrency_never_exceeds_bound(self):
        client = AsyncJobsDBClient(concurrency=3)
        active = 0
        peak = 0

        async def fake_graphql(query, variables, operation, runtime_retry=False):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.005)
            active -= 1
            return _detail_body(variables["id"])

        client.graphql = fake_graphql
        results = await client.fetch_details_many([str(i) for i in range(15)])
        assert len(results) == 15
        assert peak <= 3  # hard concurrency bound respected


class TestFailureIsolation:
    async def test_partial_failure_keeps_successes(self):
        client = AsyncJobsDBClient(concurrency=4)

        async def fake_graphql(query, variables, operation, runtime_retry=False):
            if variables["id"] == "bad":
                raise RuntimeError("boom")
            return _detail_body(variables["id"])

        client.graphql = fake_graphql
        results = await client.fetch_details_many(["1", "bad", "3"])
        assert [r.id for r in results] == ["1", "3"]

    async def test_all_failures_raise(self):
        client = AsyncJobsDBClient(concurrency=4)

        async def fake_graphql(query, variables, operation, runtime_retry=False):
            raise RuntimeError("boom")

        client.graphql = fake_graphql
        with pytest.raises(RuntimeError):
            await client.fetch_details_many(["1", "2"])


class TestLifecycle:
    async def test_aclose_closes_async_session(self):
        client = AsyncJobsDBClient()
        sess = MagicMock()
        sess.close = AsyncMock()
        client._session = sess
        await client.aclose()
        sess.close.assert_awaited_once()

    async def test_async_context_manager_closes_session(self):
        client = AsyncJobsDBClient()
        sess = MagicMock()
        sess.close = AsyncMock()
        client._session = sess
        async with client as c:
            assert c is client
        sess.close.assert_awaited_once()


class TestAsyncSearch:
    async def test_search_parses_summaries(self):
        client = AsyncJobsDBClient()

        async def fake_graphql(query, variables, operation, runtime_retry=False):
            return _search_body(ids=(1,), total=7)

        client.graphql = fake_graphql
        res = await client.search(keywords="python")
        assert res.total == 7
        assert res.jobs[0].title == "Job 1"
        assert res.jobs[0].company == "Company 1"

    async def test_search_passes_filters(self):
        client = AsyncJobsDBClient()
        captured = {}

        async def fake_graphql(query, variables, operation, runtime_retry=False):
            captured["params"] = variables["params"]
            return _search_body(ids=(), total=0)

        client.graphql = fake_graphql
        await client.search(keywords="dev", salary_min=1000, posted_within_days=7)
        flt = captured["params"]["searchIntent"]["filter"]
        assert flt["salaryMin"] == "1000m"
        assert flt["listedAt"] == "7d"

    async def test_iter_all_stops_at_max_pages(self):
        client = AsyncJobsDBClient()
        pages = []

        async def fake_graphql(query, variables, operation, runtime_retry=False):
            page = variables["params"]["responseConfig"]["page"]
            pages.append(page)
            return _search_body(page=page, ids=(page,), total=100)

        client.graphql = fake_graphql
        seen = [j.id async for j in client.iter_all(keywords="x", max_pages=2)]
        assert seen == ["1", "2"]
        assert pages == [1, 2]
