"""Data models for JobsDB wrapper."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

WORK_TYPES: dict[str, str] = {
    "full_time": "242",
    "part_time": "243",
    "contract": "244",
    "casual": "245",
    "242": "242",
    "243": "243",
    "244": "244",
    "245": "245",
}

WORK_ARRANGEMENTS: dict[str, str] = {
    "on_site": "1",
    "hybrid": "2",
    "remote": "3",
    "1": "1",
    "2": "2",
    "3": "3",
}

SALARY_PERIODS: dict[str, str] = {
    "hourly": "h",
    "monthly": "m",
    "annual": "y",
    "annually": "y",
}

SORT_MODES: dict[str, str] = {
    "relevance": "score",
    "score": "score",
    "date": "listedAt",
    "listed_at": "listedAt",
    "listedat": "listedAt",
}


class JobsDBError(Exception):
    """Base wrapper error."""


class JobsDBBlockedError(JobsDBError):
    """Cloudflare (or edge) started challenging the API route."""


class JobsDBHTTPError(JobsDBError):
    def __init__(self, status: int, body: str):
        self.status = status
        super().__init__(f"HTTP {status}: {body[:200]}")


MARKET_HOSTS: dict[str, str] = {
    "th": "th.jobsdb.com",
    "hk": "hk.jobsdb.com",
    "my": "my.jobstreet.com",
    "sg": "sg.jobstreet.com",
    "ph": "ph.jobstreet.com",
    "id": "id.jobstreet.com",
}


@dataclass
class JobSummary:
    id: str
    title: str
    market: str = "th"
    company: str | None = None
    advertiser_id: str | None = None
    location: str | None = None
    salary_label: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    categories: list[str] = field(default_factory=list)
    category_ids: list[str] = field(default_factory=list)
    work_arrangements: list[str] = field(default_factory=list)
    listed_at: str | None = None
    abstract: str | None = None
    url: str | None = None
    profile_url: str | None = None

    @property
    def web_url(self) -> str:
        host = MARKET_HOSTS.get(self.market, MARKET_HOSTS["th"])
        return f"https://{host}/{self.market}/job/{self.id}"

    @classmethod
    def from_graphql(cls, j: dict[str, Any], market: str = "th") -> JobSummary:
        adv = j.get("advertiser") or {}
        org = j.get("organisation") or {}
        profile_url = org.get("companyProfileUrl")
        loc = (j.get("location") or {}).get("displayName") or {}
        sal = j.get("salary") or {}
        raw_cats = j.get("categories")
        if isinstance(raw_cats, list):
            cats = [c for c in raw_cats if isinstance(c, dict)]
        else:
            cats = []
            if isinstance(raw_cats, dict) and raw_cats.get("label"):
                cats = [{"id": None, "label": raw_cats["label"]}]
        arrs = [((w.get("label") or {}).get("text")) for w in (j.get("workArrangements") or [])]
        listed = (j.get("listedAt") or {}).get("dateTimeUtc")
        return cls(
            id=str(j["id"]),
            title=j.get("title") or "",
            market=market,
            company=org.get("name") or adv.get("name"),
            advertiser_id=adv.get("id"),
            location=loc.get("text"),
            salary_min=sal.get("min"),
            salary_max=sal.get("max"),
            salary_currency=sal.get("currency"),
            salary_period=sal.get("period"),
            categories=[c["label"] for c in cats if c.get("label")],
            category_ids=[str(c.get("id")) for c in cats if c.get("id")],
            work_arrangements=[a for a in arrs if a],
            listed_at=listed,
            abstract=j.get("abstract"),
            url=j.get("url"),
            profile_url=profile_url,
        )


@dataclass
class JobDetail(JobSummary):
    content_html: str | None = None
    is_expired: bool = False
    salary_display: str | None = None
    created_at: str | None = None

    @classmethod
    def from_graphql(cls, j: dict[str, Any], market: str = "th") -> JobDetail:
        sal_label = (j.get("salary") or {}).get("label")
        loc_raw = j.get("location") or {}
        location = loc_raw.get("label") or ((loc_raw.get("displayName") or {}).get("text"))
        base = super().from_graphql(j, market=market)
        return cls(
            **{
                "id": base.id,
                "title": base.title,
                "market": market,
                "company": base.company,
                "advertiser_id": base.advertiser_id,
                "location": location or base.location,
                "salary_label": sal_label or base.salary_label,
                "salary_min": base.salary_min,
                "salary_max": base.salary_max,
                "salary_currency": base.salary_currency,
                "salary_period": base.salary_period,
                "categories": [
                    c.get("label") for c in (j.get("classifications") or []) if c.get("label")
                ]
                or base.categories,
                "category_ids": base.category_ids,
                "work_arrangements": base.work_arrangements,
                "listed_at": (j.get("listedAt") or {}).get("dateTimeUtc"),
                "abstract": base.abstract,
                "url": base.url,
                "content_html": j.get("content"),
                "is_expired": bool(j.get("isExpired")),
                "created_at": (j.get("createdAt") or {}).get("dateTimeUtc"),
            }
        )


@dataclass
class CategoryFacet:
    id: str
    label: str
    count: int


@dataclass
class LocationSuggestion:
    id: str
    label: str = ""
    kind: str = ""


@dataclass
class TitleFacet:
    id: str
    label: str
    count: int


@dataclass
class LocationFacet:
    id: str
    label: str
    count: int


@dataclass
class CompanyInfo:
    name: str
    organisation_id: str | None = None
    profile_url: str | None = None
    active_jobs: int = 0


@dataclass
class SearchResult:
    jobs: list[JobSummary]
    page: int
    page_size: int
    total: int
    facets: list[CategoryFacet] = field(default_factory=list)
    suggestions: list[LocationSuggestion] = field(default_factory=list)

    @property
    def has_next(self) -> bool:
        return self.page * self.page_size < self.total
