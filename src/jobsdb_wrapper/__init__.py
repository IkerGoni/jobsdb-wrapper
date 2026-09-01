"""JobsDB wrapper — free GraphQL client for JobsDB/JobStreet (SEEK unified platform).

Guest-only: search, job details, facets, Markdown extraction, caching, async
bulk — with just curl_cffi. No accounts, no cookies, no browser automation.
"""

__version__ = "4.0.0"
from .async_client import AsyncJobsDBClient
from .client import JobsDBClient
from .markdown import html_to_markdown, job_to_markdown
from .models import (
    SALARY_PERIODS,
    SORT_MODES,
    WORK_ARRANGEMENTS,
    WORK_TYPES,
    CategoryFacet,
    CompanyInfo,
    JobDetail,
    JobsDBBlockedError,
    JobsDBError,
    JobsDBHTTPError,
    JobSummary,
    LocationFacet,
    LocationSuggestion,
    SearchResult,
    TitleFacet,
)

__all__ = [
    "JobsDBClient",
    "AsyncJobsDBClient",
    "JobsDBError",
    "JobsDBBlockedError",
    "JobsDBHTTPError",
    "TitleFacet",
    "LocationFacet",
    "LocationSuggestion",
    "CompanyInfo",
    "JobDetail",
    "JobSummary",
    "SearchResult",
    "CategoryFacet",
    "WORK_TYPES",
    "WORK_ARRANGEMENTS",
    "SALARY_PERIODS",
    "SORT_MODES",
    "html_to_markdown",
    "job_to_markdown",
]
