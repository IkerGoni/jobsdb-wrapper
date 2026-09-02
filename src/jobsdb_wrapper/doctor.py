"""Contract doctor — detect upstream schema drift before it breaks workflows.

Each check runs one cheap live query and asserts the field contract the
wrapper depends on. Run via: python -m jobsdb_wrapper.cli doctor
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class DoctorReport:
    results: list[CheckResult] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return all(r.ok for r in self.results)

    def summary(self) -> str:
        failed = sum(1 for r in self.results if not r.ok)
        lines = ["JobsDB contract doctor", ""]
        lines.extend(f"[{'PASS' if r.ok else 'FAIL'}] {r.name}: {r.detail}" for r in self.results)
        status = "HEALTHY" if failed == 0 else f"DRIFT DETECTED ({failed} check(s) failed)"
        lines += ["", f"Contract status: {status}"]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Stable shape for `jobsdb doctor --json` automation."""
        return {
            "status": "healthy" if self.healthy else "unhealthy",
            "checks": [
                {"name": r.name, "status": "pass" if r.ok else "fail", "detail": r.detail}
                for r in self.results
            ],
        }


def run_doctor(country: str = "th") -> DoctorReport:
    from .client import JobsDBClient

    report = DoctorReport()

    def check(name):
        def deco(fn):
            try:
                ok, detail = fn()
            except Exception as e:
                ok, detail = False, f"{type(e).__name__}: {str(e)[:120]}"
            report.results.append(CheckResult(name, ok, detail))

        return deco

    with JobsDBClient(country=country) as c:

        @check("search.basic")
        def _():
            res = c.search(keywords="python", page_size=3)
            return (res.total > 0 and len(res.jobs) > 0, f"total={res.total}")

        @check("search.fields")
        def _():
            res = c.search(keywords="python", page_size=1)
            j = res.jobs[0]
            missing = [
                f for f in ("id", "title", "company", "location", "listed_at") if not getattr(j, f)
            ]
            return (
                not missing,
                "missing: " + ",".join(missing) if missing else "core fields present",
            )

        @check("search.facets")
        def _():
            res = c.search(keywords="python", include_facets=True, page_size=1)
            return (
                len(res.facets) > 0,
                f"{len(res.facets)} category facets" if res.facets else "no facets returned",
            )

        @check("search.salary_filter")
        def _():
            base = c.search(page_size=1)
            filtered = c.search(salary_min=1, salary_period="monthly", page_size=1)
            return (filtered.total <= base.total, f"base={base.total} filtered={filtered.total}")

        @check("detail.payload")
        def _():
            res = c.search(keywords="engineer", page_size=5)
            for j in res.jobs:
                jd = c.job(j.id)
                if jd.content_html:
                    return True, f"job {j.id}: {len(jd.content_html)}b content"
            return False, "no job with content among first 5"

        @check("facets.v6_titles")
        def _():
            t = c.title_facets(keywords="developer")
            return (len(t) > 0, f"{len(t)} title facets")

        @check("facets.v6_locations")
        def _():
            locs = c.location_facets()
            return (len(locs) > 0, f"{len(locs)} location facets")

    return report
