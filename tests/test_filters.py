"""Filter-encoding unit tests (no network)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jobsdb_wrapper.client import (  # noqa: E402
    JobsDBClient,
    JobsDBError,
)
from jobsdb_wrapper.http import (  # noqa: E402
    resolve_arrangement as _resolve_arrangement,
)
from jobsdb_wrapper.http import (
    resolve_work_type as _resolve_work_type,
)
from jobsdb_wrapper.queries import JOB_DETAIL_QUERY, SEARCH_QUERY  # noqa: E402


def test_work_type_resolver():
    assert _resolve_work_type("full_time") == "242"
    assert _resolve_work_type("PART_TIME") == "243"
    assert _resolve_work_type("244") == "244"
    assert _resolve_work_type("bogus") is None
    assert _resolve_arrangement("remote") == "3"
    assert _resolve_arrangement("hybrid") == "2"


def test_query_documents_shape():
    assert "jobSearchV7(params: $params)" in SEARCH_QUERY
    assert "JobSearchV7QueryInput" in SEARCH_QUERY
    assert "jobDetails(id: $id)" in JOB_DETAIL_QUERY


class _CaptureClient(JobsDBClient):
    def __init__(self):
        # bypass parent init that requires curl_cffi session for capture-only use
        self.country_key = "th"
        from jobsdb_wrapper.http import MARKET_HOSTS

        self.host, self.country_code, default_locale = MARKET_HOSTS["th"]
        self.locale = default_locale
        self.graphql_url = f"https://{self.host}/graphql"
        self.timeout = 30
        self.retries = 3
        from jobsdb_wrapper.http import RateLimiter

        self.limiter = RateLimiter(60)
        self._proxy = None
        self._session = None
        self.captured = None

    def graphql(self, query, variables, operation, runtime_retry=False):
        self.captured = {"query": query, "variables": variables, "operation": operation}
        return {
            "data": {
                "jobSearchV7": {
                    "results": {
                        "jobs": [],
                        "pagination": {"page": 1, "pageSize": 20, "resultCount": 0},
                    }
                }
            }
        }


def test_search_params_encoding():
    c = _CaptureClient()
    c.search(
        keywords="python dev",
        where="Bangkok",
        distance_km=25,
        work_types=["full_time", "contract"],
        work_arrangements=["remote"],
        salary_min=50000,
        salary_max=90000,
        salary_period="monthly",
        posted_within_days=14,
        sort="date",
        page=2,
        page_size=10,
        include_facets=True,
    )
    params = c.captured["variables"]["params"]
    intent = params["searchIntent"]
    assert intent["text"] == "python dev"
    assert intent["where"] == ["Bangkok"]
    assert intent["distanceKms"] == 25
    assert intent["sort"] == "listedAt"
    flt = intent["filter"]
    assert flt["workTypeId"] == ["242", "244"]
    assert flt["workArrangementId"] == ["3"]
    assert flt["salaryMin"] == "50000m"
    assert flt["salaryMax"] == "90000m"
    assert flt["listedAt"] == "14d"
    rc = params["responseConfig"]
    assert rc["page"] == 2 and rc["pageSize"] == 10
    assert rc["enrichment"]["facets"] == ["categoryV1"]
    sc = params["searchContext"]
    assert sc["brand"] == "seek" and sc["channel"] == "web"


def test_search_rejects_bad_enum():
    c = _CaptureClient()
    try:
        c.search(work_types=["nonsense"], salary_period="weekly")
        raised = False
    except JobsDBError:
        raised = True
    assert raised


def test_country_support():
    import pytest

    with pytest.raises(JobsDBError):
        JobsDBClient(country="us")
