"""JobsDB GraphQL client — sync + async, cache, bulk iterators.

Free pure-HTTP access to th.jobsdb.com and sibling SEEK markets (guest mode).
Cloudflare guards HTML routes; /graphql is open with proper headers.

Guest-only by design: no login, no cookie handling, no profile access. SEEK
sessions are server-side and cannot be created or exercised safely from a
third-party client; authenticated tooling lives outside this package.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Iterator
from typing import Any

try:
    from curl_cffi import requests as curl_requests
except ImportError:  # pragma: no cover
    curl_requests = None

from .http import (
    RateLimiter,
    RequestError,
    backoff_sleep,
    build_headers,
    build_search_params,
    classify_response,
    interpret_body,
    resolve_market,
)
from .models import (
    CategoryFacet,
    CompanyInfo,
    JobDetail,
    JobsDBBlockedError,
    JobsDBError,
    JobSummary,
    LocationFacet,
    LocationSuggestion,
    SearchResult,
    TitleFacet,
)
from .queries import JOB_DETAIL_QUERY, SEARCH_QUERY


class _BaseClient:
    """Shared config + search param logic for sync/async clients."""

    def __init__(
        self,
        country: str = "th",
        locale: str | None = None,
        rate_limit_rpm: float = 60,
        timeout: float = 30,
        proxy: str | None = None,
        retries: int = 3,
    ):
        if curl_requests is None:
            raise JobsDBError("curl_cffi is required: pip install curl_cffi>=0.13")
        self.country_key = country.lower()
        self.host, self.country_code, self.locale = resolve_market(country, locale)
        self.graphql_url = f"https://{self.host}/graphql"
        self.timeout = timeout
        self.retries = retries
        self.limiter = RateLimiter(rate_limit_rpm)
        proxy = proxy or os.environ.get("JOBSDB_PROXY")
        self._proxy = {"https": proxy} if proxy else None
        self._session = None

    def _origin(self) -> str:
        return f"https://{self.host}"

    def _headers(self) -> dict[str, str]:
        path = f"/{self.country_key}/jobs" if self.country_key in ("th", "hk") else "/"
        return build_headers(self._origin(), self._origin() + path, self.locale)

    def close(self) -> None:
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------ search

    def _search_call(self, execute) -> SearchResult:
        params = build_search_params(country_code=self.country_code, locale=self.locale)
        return self._search_with_params(execute, params)

    def _search_with_params(self, execute, params: dict[str, Any]) -> SearchResult:
        body = execute(
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
        sugg = ((resp.get("enrichment") or {}).get("suggestions") or {}).get("locationV1") or {}
        suggestions = [
            LocationSuggestion(
                id=str(c.get("id")),
                label=(c.get("label") or "").strip(),
                kind=(c.get("kind") or "").strip(),
            )
            for block in [sugg.get("local"), sugg.get("international")]
            for c in ((block or {}).get("completions") or [])
            if c.get("id")
        ]
        return SearchResult(
            jobs=[JobSummary.from_graphql(j, market=self.country_key) for j in results.get("jobs") or []],
            page=int(pagination.get("page") or params["responseConfig"]["page"]),
            page_size=int(pagination.get("pageSize") or params["responseConfig"]["pageSize"]),
            total=int(pagination.get("resultCount") or 0),
            facets=facets,
            suggestions=suggestions,
        )


class _AsyncContextMixin:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        await asyncio.to_thread(self.close)


class JobsDBClient(_BaseClient):
    """Sync client (guest mode).

    Args:
        country: th | hk | my | sg | ph | id
        locale: override (e.g. 'th-TH')
        rate_limit_rpm: upstream ~60 rpm per IP
        proxy: optional 'http://user:pass@host:port' (or env JOBSDB_PROXY)
        detail_cache: path to sqlite file enabling detail caching
    """

    def __init__(self, *args, detail_cache: str | os.PathLike | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        from .cache import DetailCache

        self.cache = DetailCache(detail_cache) if detail_cache else None

    # ------------------------------------------------------------- transport

    def _ensure_session(self):
        if self._session is None:
            self._session = curl_requests.Session()
        return self._session

    def graphql(
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
            self.limiter.wait()
            try:
                session = self._ensure_session()
                r = session.post(
                    self.graphql_url,
                    json=payload,
                    headers=self._headers(),
                    impersonate="chrome131",
                    timeout=self.timeout,
                    proxies=self._proxy,
                )
            except Exception as e:
                last_err = RequestError("network", str(e))
                backoff_sleep(attempt)
                continue
            self.limiter.adapt(dict(r.headers))
            outcome = classify_response(r.status_code, r.text)
            if isinstance(outcome, RequestError):
                last_err = outcome
                if outcome.kind == "blocked" and attempt >= 1:
                    raise JobsDBBlockedError(
                        "API route is being challenged. Options: rotate IP "
                        "(JOBSDB_PROXY env), slow down, or retry later."
                    )
                backoff_sleep(attempt)
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
                backoff_sleep(attempt)
            except JobsDBError:
                raise
        kind = getattr(last_err, "kind", "network")
        if kind == "blocked":
            raise JobsDBBlockedError(str(last_err))
        raise JobsDBError(f"Request failed after {self.retries} retries: {last_err}")

    # ----------------------------------------------------------------- search

    def search(self, keywords: str | None = None, **filters) -> SearchResult:
        """Search jobs. See build_search_params for the full filter surface."""
        filters.setdefault("keywords", keywords)
        params = build_search_params(country_code=self.country_code, locale=self.locale, **filters)
        return self._search_with_params(self.graphql, params)

    def iter_all(
        self,
        keywords: str | None = None,
        max_pages: int | None = None,
        page_size: int = 30,
        **filters,
    ) -> Iterator[JobSummary]:
        """Lazily paginate through every result for a query."""
        page = 1
        while True:
            res = self.search(keywords=keywords, page=page, page_size=page_size, **filters)
            yield from res.jobs
            if not res.has_next or not res.jobs:
                return
            if max_pages is not None and page >= max_pages:
                return
            page += 1

    # ------------------------------------------------------------------ detail

    def job(self, job_id: str, force_refresh: bool = False) -> JobDetail:
        if self.cache and not force_refresh:
            cached = self.cache.get_valid(job_id, self.country_key)
            if cached:
                return JobDetail.from_graphql(cached, market=self.country_key)
        body = self.graphql(JOB_DETAIL_QUERY, {"id": str(job_id)}, "JobDetail")
        jd = (body.get("data") or {}).get("jobDetails") or {}
        job = jd.get("job")
        if not job:
            raise JobsDBError(f"Job {job_id} not found or empty payload")
        if self.cache:
            self.cache.put(job_id, self.country_key, job)
        return JobDetail.from_graphql(job, market=self.country_key)

    def fetch_details(self, job_ids: list[str], force_refresh: bool = False) -> list[JobDetail]:
        """Sequential convenience over job(). For parallel use AsyncJobsDBClient."""
        return [self.job(i, force_refresh=force_refresh) for i in job_ids]

    def job_markdown(self, job_id: str, force_refresh: bool = False) -> str:
        from .markdown import job_to_markdown

        return job_to_markdown(self.job(job_id, force_refresh=force_refresh))

    # --------------------------------------------------------------- discovery

    def locations(self, prefix: str) -> list[LocationSuggestion]:
        """Location autocomplete -> canonical ids usable as whereId hints.

        Server-side trigger is the `where` search text: the API returns
        completions matching that prefix. The schema's human-readable
        `label` field requires an undocumented SeekLocationContext enum
        value, so completions expose `id` + `kind` only (verified live
        2026-08-31).
        """
        res = self.search(keywords="", where=prefix, include_suggestions=True, page_size=1)
        return res.suggestions

    def title_facets(self, keywords: str | None = None, **filters) -> list[TitleFacet]:
        p6 = _build_v6_base(
            self.country_code, self.locale, ["distinctTitle"], keywords, filters
        )
        body = self.graphql(V6_FACET_QUERY, {"params": p6}, "JobSearchV6")
        d = (body.get("data") or {}).get("jobSearchV6") or {}
        return [
            TitleFacet(
                id=str(f.get("id")), label=f.get("label") or "", count=int(f.get("count") or 0)
            )
            for f in ((d.get("facets") or {}).get("distinctTitle")) or []
        ]

    def location_facets(self, keywords: str | None = None, **filters) -> list[LocationFacet]:
        p6 = _build_v6_base(self.country_code, self.locale, ["location"], keywords, filters)
        body = self.graphql(V6_FACET_QUERY, {"params": p6}, "JobSearchV6")
        d = (body.get("data") or {}).get("jobSearchV6") or {}
        return [
            LocationFacet(
                id=str(f.get("id")),
                label=((f.get("label") or {}).get("text")) or "",
                count=int(f.get("count") or 0),
            )
            for f in ((d.get("facets") or {}).get("location")) or []
        ]

    def company(self, name: str, page_size: int = 20) -> CompanyInfo:
        res = self.search(keywords=name, page_size=1)
        # SEARCH_QUERY requests `organisation { id name companyProfileId
        # companyProfileUrl }` at the job root; the advertiser node only carries
        # id + name. Read the organisation from the job root.
        org: dict[str, Any] = next(
            (
                (j.raw or {}).get("organisation", {})
                for j in res.jobs
                if (j.raw or {}).get("organisation")
            ),
            {},
        )
        org_id = str(org.get("id") or "")
        if not org_id:
            raise JobsDBError(f"No organisation found for {name!r}")
        detail = self.search(organisation_ids=[org_id], page_size=page_size)
        url = next((j.profile_url for j in detail.jobs if j.profile_url), None)
        return CompanyInfo(
            name=name, organisation_id=org_id, profile_url=url, active_jobs=detail.total
        )


def _build_v6_base(
    country_code: str, locale: str, facets: list[str], keywords: str | None, filters: dict
) -> dict[str, Any]:
    p6: dict[str, Any] = {
        "siteKey": country_code,
        "locale": locale,
        "pageSize": 1,
        "page": 1,
        "channel": "web",
        "facets": facets,
    }
    if keywords:
        p6["keywords"] = keywords
    if filters.get("work_types"):
        from .http import resolve_work_type

        wts = [resolve_work_type(v) for v in filters["work_types"]]
        wts = [w for w in wts if w]
        if wts:
            p6["workType"] = wts
    if filters.get("posted_within_days"):
        p6["dateRange"] = int(filters["posted_within_days"])
    where = filters.get("where")
    if where:
        p6["where"] = where if isinstance(where, str) else ", ".join(where)
    return p6


V6_FACET_QUERY = """
query JobSearchV6($params: JobSearchV6QueryInput!) {
  jobSearchV6(params: $params) {
    totalCount
    facets {
      distinctTitle { id count label }
      location { id count label { lang text } }
    }
  }
}
"""
