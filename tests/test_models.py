import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jobsdb_wrapper import (  # noqa: E402
    SALARY_PERIODS,
    SORT_MODES,
    WORK_ARRANGEMENTS,
    WORK_TYPES,
    CategoryFacet,
    JobDetail,
    JobSummary,
    SearchResult,
)


def test_work_type_resolution():
    assert WORK_TYPES["full_time"] == "242"
    assert WORK_TYPES["FULL_TIME".lower()] == "242"
    assert WORK_TYPES["contract"] == "244"


def test_arrangement_resolution():
    assert WORK_ARRANGEMENTS["remote"] == "3"
    assert WORK_ARRANGEMENTS["on_site"] == "1"


def test_salary_period_suffixes():
    assert SALARY_PERIODS["monthly"] == "m"
    assert SALARY_PERIODS["annual"] == "y"
    assert SALARY_PERIODS["hourly"] == "h"


def test_sort_modes():
    assert SORT_MODES["relevance"] == "score"
    assert SORT_MODES["date"] == "listedAt"


def test_job_summary_from_graphql():
    raw = {
        "id": "94162495",
        "title": "Developer (Python)",
        "advertiser": {"id": "62536658", "name": "ACME"},
        "organisation": {"id": "322", "name": "ACME LTD"},
        "location": {"id": "1000047", "displayName": {"text": "Taling Chan, Bangkok"}},
        "salary": {"period": "monthly", "min": 25000, "max": 35000, "currency": "THB"},
        "categories": [{"id": "6287", "label": "Developers/Programmers"}],
        "workArrangements": [{"id": "1", "label": {"lang": "en", "text": "On-site"}}],
        "listedAt": {"dateTimeUtc": "2026-08-24T04:15:31.000Z"},
        "abstract": "short",
        "url": None,
    }
    s = JobSummary.from_graphql(raw)
    assert s.id == "94162495"
    assert s.company == "ACME LTD"
    assert s.location == "Taling Chan, Bangkok"
    assert s.salary_min == 25000
    assert s.salary_currency == "THB"
    assert s.categories == ["Developers/Programmers"]
    assert s.work_arrangements == ["On-site"]
    assert s.web_url == "https://th.jobsdb.com/th/job/94162495"


def test_job_detail_from_graphql():
    raw = {
        "id": "123",
        "title": "T",
        "content": "<p>body</p>",
        "isExpired": False,
        "salary": {"label": "THB 30k/mo"},
        "classifications": [{"label(languageCode)": None, "label": "ICT"}],
        "listedAt": {"dateTimeUtc": "2026-08-20T00:00:00Z"},
        "createdAt": {"dateTimeUtc": "2026-08-20T00:00:01Z"},
    }
    d = JobDetail.from_graphql(raw)
    assert d.content_html == "<p>body</p>"
    assert d.salary_label == "THB 30k/mo"
    assert d.is_expired is False
    assert isinstance(d, JobSummary)


def test_search_result_pagination():
    r = SearchResult(
        jobs=[], page=2, page_size=20, total=45, facets=[CategoryFacet("6287", "Dev", 12)]
    )
    assert r.has_next is True
    assert r.facets[0].count == 12
