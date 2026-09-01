"""Async client — parallel detail fetching for bulk scrapes (guest mode)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

try:
    from curl_cffi import requests as curl_requests
except ImportError:  # pragma: no cover
    curl_requests = None

from .client import V6_FACET_QUERY, _AsyncContextMixin, _BaseClient
from .http import (
    RequestError,
    backoff_sleep,
    build_search_params,
    classify_response,
    interpret_body,
)
from .models import (
    CategoryFacet,
    JobDetail,
    JobsDBBlockedError,
    JobsDBError,
    JobSummary,
    LocationFacet,
    SearchResult,
    TitleFacet,
)
from .queries import JOB_DETAIL_QUERY, SEARCH_QUERY


class AsyncJobsDBClient(_AsyncContextMixin, _BaseClient):
    """Async mirror of JobsDBClient (same constructor args, guest mode).

    Extra:
        concurrency: max parallel detail fetches (fetch_details_many)
        Note: detail cache is sync-only; pass cache=False semantics here.
    """

    def __init__(self, *args, concurrency: int = 5, **kwargs):
        kwargs.pop("detail_cache", None)  # not supported on async path
        super().__init__(*args, **kwargs)
        self._semaphore = asyncio.Semaphore(concurrency)

    async def aclose(self) -> None:
        if self._session is not None:
            try:
                await self._session.close()
            except Exception:
                pass
            self._session = None

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    def close(self) -> None:
        # sync contexts must not touch AsyncSession (its close() is a coroutine);
        # only propagate close() for a plain sync Session. Use aclose() or
        # 'async with' for real cleanup of the async session.
        from curl_cffi.requests import Session

        if self._session is not None and isinstance(self._session, Session):
            super().close()

    async def _ensure_session(self):
        if self._session is None:
            self._session = curl_requests.AsyncSession()
        return self._session

    async def graphql(
        self, query: str, variables: dict[str, Any], operation: str, runtime_retry: bool = False
    ) -> dict[str, Any]:
        payload = {
            "query": query,
            "variables": variables,
            "operationName": operation,
            "extensions": {"clientLibrary": {"name": "@apollo/client", "version": "4.2.12"}},
        }
        last_err: Exception | None = None
        for attempt in range(self.retries + 1):
            await asyncio.to_thread(self.limiter.wait)
            try:
                session = await self._ensure_session()
                r = await session.post(
                    self.graphql_url,
                    json=payload,
                    headers=self._headers(),
                    impersonate="chrome131",
                    timeout=self.timeout,
                    proxies=self._proxy,
                )
            except Exception as e:
                last_err = RequestError("network", str(e))
                await asyncio.to_thread(backoff_sleep, attempt)
                continue
            self.limiter.adapt(dict(r.headers))
            outcome = classify_response(r.status_code, r.text)
            if isinstance(outcome, RequestError):
                last_err = outcome
                if outcome.kind == "blocked" and attempt >= 1:
                    raise JobsDBBlockedError(
                        "API route is being challenged. Rotate IP / slow down."
                    )
                await asyncio.to_thread(backoff_sleep, attempt)
                continue
            try:
                return interpret_body(outcome, operation.split("(")[0])
            except RequestError as e:
                last_err = e
                if e.kind == "runtime" and runtime_retry:
                    variables = dict(variables)
                    if "params" in variables:
                        variables["params"] = dict(variables["params"])
                        variables["params"]["sessionId"] = str(uuid.uuid4())
                    continue
                await asyncio.to_thread(backoff_sleep, attempt)
        kind = getattr(last_err, "kind", "network")
        if kind == "blocked":
            raise JobsDBBlockedError(str(last_err))
        raise JobsDBError(f"Request failed after {self.retries} retries: {last_err}")

    # ----------------------------------------------------------------- search

    async def search(self, keywords: str | None = None, **filters) -> SearchResult:
        filters.setdefault("keywords", keywords)
        params = build_search_params(country_code=self.country_code, locale=self.locale, **filters)
        body = await self.graphql(
            SEARCH_QUERY,
            {"params": params, "locale": self.locale},
            "JobSearchV7",
            runtime_retry=True,
        )
        resp = (body.get("data") or {}).get("jobSearchV7") or {}
        results = resp.get("results") or {}
        pagination = results.get("pagination") or {}
        facets: list[CategoryFacet] = []
        enr = ((resp.get("enrichment") or {}).get("facets") or {}).get("categoryV1") or []
        for f in enr:
            label = (f.get("label") or {}).get("text") or ""
            facets.append(
                CategoryFacet(id=str(f.get("id")), label=label, count=int(f.get("count") or 0))
            )
        return SearchResult(
            jobs=[
                JobSummary.from_graphql(j, market=self.country_key)
                for j in results.get("jobs") or []
            ],
            page=int(pagination.get("page") or params["responseConfig"]["page"]),
            page_size=int(pagination.get("pageSize") or params["responseConfig"]["pageSize"]),
            total=int(pagination.get("resultCount") or 0),
            facets=facets,
        )

    async def iter_all(
        self,
        keywords: str | None = None,
        max_pages: int | None = None,
        page_size: int = 30,
        **filters,
    ):
        page = 1
        while True:
            res = await self.search(keywords=keywords, page=page, page_size=page_size, **filters)
            for j in res.jobs:
                yield j
            if not res.has_next or not res.jobs:
                return
            if max_pages is not None and page >= max_pages:
                return
            page += 1

    # ------------------------------------------------------------------ detail

    async def job(self, job_id: str) -> JobDetail:
        async with self._semaphore:
            body = await self.graphql(JOB_DETAIL_QUERY, {"id": str(job_id)}, "JobDetail")
        jd = (body.get("data") or {}).get("jobDetails") or {}
        job = jd.get("job")
        if not job:
            raise JobsDBError(f"Job {job_id} not found or empty payload")
        return JobDetail.from_graphql(job, market=self.country_key)

    async def fetch_details_many(self, job_ids: list[str]) -> list[JobDetail]:
        """Fetch many postings concurrently (bounded by `concurrency`).
        Partial success tolerated; raises only if every fetch failed."""
        results = await asyncio.gather(*(self.job(i) for i in job_ids), return_exceptions=True)
        out: list[JobDetail] = []
        errors: list[tuple[str, BaseException]] = []
        for jid, r in zip(job_ids, results):
            if isinstance(r, BaseException):
                errors.append((jid, r))
            else:
                out.append(r)
        if errors and not out:
            raise errors[0][1]
        return out

    # --------------------------------------------------------------- discovery

    async def title_facets(self, keywords: str | None = None, **filters) -> list[TitleFacet]:
        p6 = self._v6_params(filters, ["distinctTitle"], keywords)
        body = await self.graphql(V6_FACET_QUERY, {"params": p6}, "JobSearchV6")
        d = (body.get("data") or {}).get("jobSearchV6") or {}
        return [
            TitleFacet(
                id=str(f.get("id")), label=f.get("label") or "", count=int(f.get("count") or 0)
            )
            for f in ((d.get("facets") or {}).get("distinctTitle")) or []
        ]

    async def location_facets(self, keywords: str | None = None, **filters) -> list[LocationFacet]:
        p6 = self._v6_params(filters, ["location"], keywords)
        body = await self.graphql(V6_FACET_QUERY, {"params": p6}, "JobSearchV6")
        d = (body.get("data") or {}).get("jobSearchV6") or {}
        return [
            LocationFacet(
                id=str(f.get("id")),
                label=((f.get("label") or {}).get("text")) or "",
                count=int(f.get("count") or 0),
            )
            for f in ((d.get("facets") or {}).get("location")) or []
        ]

    def _v6_params(self, filters: dict, facets: list[str], keywords: str | None) -> dict[str, Any]:
        from .client import _build_v6_base

        return _build_v6_base(self.country_code, self.locale, facets, keywords, filters)
