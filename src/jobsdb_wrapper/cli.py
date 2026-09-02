#!/usr/bin/env python3
"""JobsDB CLI — search jobs and fetch full postings from SEEK markets (guest mode).

Usage:
  python -m jobsdb_wrapper.cli search "python developer" --where Bangkok \
      --work-type full_time --salary-min 50000 --salary-period monthly \
      --posted-within 14 --sort date --facets --json
  python -m jobsdb_wrapper.cli job 94162495 --markdown -o job.md
  python -m jobsdb_wrapper.cli locations "bangkok"
  python -m jobsdb_wrapper.cli facets-v6 "python" --kind titles
  python -m jobsdb_wrapper.cli doctor
"""

from __future__ import annotations

import argparse
import json
import sys


def _add_search_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("keywords", nargs="?", default=None, help="Search keywords")
    p.add_argument(
        "--country",
        default="th",
        choices=["th", "hk", "my", "sg", "ph", "id"],
        help="Market site (default th)",
    )
    p.add_argument("--locale", help="Locale override (e.g. th-TH)")
    p.add_argument("--where", help="Location text (e.g. Bangkok)")
    p.add_argument("--distance", type=int, help="Distance km around --where")
    p.add_argument(
        "--work-type",
        action="append",
        dest="work_types",
        choices=["full_time", "part_time", "contract", "casual"],
        help="Repeatable",
    )
    p.add_argument(
        "--arrangement",
        action="append",
        dest="arrangements",
        choices=["on_site", "hybrid", "remote"],
        help="Repeatable",
    )
    p.add_argument("--salary-min", type=int, help="Minimum salary")
    p.add_argument("--salary-max", type=int, help="Maximum salary")
    p.add_argument("--salary-period", default="monthly", choices=["hourly", "monthly", "annual"])
    p.add_argument("--posted-within", type=int, metavar="DAYS", help="Posted within N days (1-31)")
    p.add_argument(
        "--category", action="append", dest="categories", help="Category id from facets; repeatable"
    )
    p.add_argument("--company", help="Organisation name filter")
    p.add_argument(
        "--tag",
        action="append",
        dest="tags",
        choices=["new", "seen", "viewed", "applied"],
        help="Repeatable",
    )
    p.add_argument("--sort", default="relevance", choices=["relevance", "date"])
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--page-size", type=int, default=20)
    p.add_argument(
        "-l",
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Stop after N results total (paginates internally)",
    )
    p.add_argument("--facets", action="store_true", help="Include category facet counts")
    p.add_argument("--json", action="store_true", help="JSON output")
    p.add_argument("--proxy", help="Proxy URL (or env JOBSDB_PROXY)")


def cmd_search(args: argparse.Namespace) -> int:
    from .client import JobsDBClient

    limit = getattr(args, "limit", None)
    with JobsDBClient(
        country=args.country,
        locale=getattr(args, "locale", None),
        proxy=getattr(args, "proxy", None),
    ) as client:
        res = client.search(
            keywords=args.keywords,
            where=args.where,
            distance_km=args.distance,
            work_types=args.work_types,
            work_arrangements=args.arrangements,
            salary_min=args.salary_min,
            salary_max=args.salary_max,
            salary_period=args.salary_period,
            posted_within_days=min(args.posted_within, 31) if args.posted_within else None,
            categories=args.categories,
            company=args.company,
            tags=args.tags,
            sort=args.sort,
            page=args.page,
            page_size=args.page_size,
            include_facets=args.facets,
        )
        if limit is not None and limit > 0 and len(res.jobs) > limit:
            res.jobs = res.jobs[:limit]
    if args.json:
        print(
            json.dumps(
                {
                    "total": res.total,
                    "page": res.page,
                    "page_size": res.page_size,
                    "has_next": res.has_next,
                    "facets": [
                        {"id": f.id, "label": f.label, "count": f.count} for f in res.facets
                    ],
                    "jobs": [
                        {
                            "id": j.id,
                            "title": j.title,
                            "company": j.company,
                            "location": j.location,
                            "listed_at": j.listed_at,
                            "url": j.web_url,
                            "salary": {
                                "min": j.salary_min,
                                "max": j.salary_max,
                                "currency": j.salary_currency,
                                "period": j.salary_period,
                            },
                            "categories": j.categories,
                            "work_arrangements": j.work_arrangements,
                            "abstract": j.abstract,
                        }
                        for j in res.jobs
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    print(f"Total: {res.total}  (page {res.page}, size {res.page_size})")
    if res.facets:
        tops = ", ".join(f"{f.label}({f.id}):{f.count}" for f in res.facets[:10])
        print(f"Facets: {tops}")
    for i, j in enumerate(res.jobs, 1):
        sal = ""
        if j.salary_min or j.salary_max:
            cur = j.salary_currency or ""
            sal = (
                f" | {cur} {j.salary_min:,}-{j.salary_max:,}/{j.salary_period}"
                if j.salary_min and j.salary_max
                else ""
            )
        print(
            f"{i:3d}. [{j.id}] {j.title} — {j.company} ({j.location}){sal} {j.listed_at[:10] if j.listed_at else ''}"
        )
        print(f"     {j.web_url}")
    return 0


def cmd_job(args: argparse.Namespace) -> int:
    from .client import JobsDBClient

    with JobsDBClient(
        country=args.country,
        proxy=getattr(args, "proxy", None),
        detail_cache=getattr(args, "cache", None),
    ) as client:
        jd = client.job(args.job_id, force_refresh=getattr(args, "refresh", False))
        if args.json:
            print(
                json.dumps(
                    {
                        "id": jd.id,
                        "title": jd.title,
                        "company": jd.company,
                        "location": jd.location,
                        "salary_label": jd.salary_label,
                        "is_expired": jd.is_expired,
                        "listed_at": jd.listed_at,
                        "created_at": jd.created_at,
                        "url": jd.web_url,
                        "categories": jd.categories,
                        "content_html": jd.content_html,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        md = client.job_markdown(args.job_id)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(md)
            print(f"saved -> {args.output}")
        else:
            print(md)
    return 0


def cmd_locations(args: argparse.Namespace) -> int:
    from .client import JobsDBClient

    with JobsDBClient(country=args.country) as client:
        for s in client.locations(args.prefix):
            kind = f" {s.kind}" if s.kind else ""
            print(f"{s.id:12s}{kind}  {s.label}".rstrip())
    return 0


def cmd_facets_v6(args: argparse.Namespace) -> int:
    from .client import JobsDBClient

    with JobsDBClient(country=args.country) as client:
        if args.kind == "titles":
            for f in client.title_facets(keywords=args.keywords):
                print(f"{f.count:>6}  {f.id}  {f.label}")
        else:
            for f in client.location_facets(keywords=args.keywords):
                print(f"{f.count:>6}  {f.id}  {f.label}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from .doctor import run_doctor

    report = run_doctor(country=args.country)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(report.summary())
    return 0 if report.healthy else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="jobsdb", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("search", help="Search jobs")
    _add_search_args(sp)
    sp.set_defaults(func=cmd_search)

    jp = sub.add_parser("job", help="Fetch full job posting (Markdown output)")
    jp.add_argument("job_id", help="Numeric job id, e.g. 94162495")
    jp.add_argument(
        "--country",
        default="th",
        choices=["th", "hk", "my", "sg", "ph", "id"],
        help="Market site (default th)",
    )
    jp.add_argument("--json", action="store_true", help="Raw JSON payload")
    jp.add_argument("-o", "--output", help="Write Markdown to file instead of stdout")
    jp.add_argument("--proxy", help="Proxy URL (or env JOBSDB_PROXY)")
    jp.add_argument(
        "--cache", metavar="PATH", help="SQLite cache file for detail dedupe between runs"
    )
    jp.add_argument("--refresh", action="store_true", help="Bypass cache and refetch")
    jp.set_defaults(func=cmd_job)

    lp = sub.add_parser("locations", help="Autocomplete location names")
    lp.add_argument("prefix", help="Location text, e.g. Bang")
    lp.add_argument("--country", default="th", choices=["th", "hk", "my", "sg", "ph", "id"])
    lp.set_defaults(func=cmd_locations)

    fp = sub.add_parser("facets-v6", help="Title/location facets with counts")
    fp.add_argument("keywords", nargs="?", default=None)
    fp.add_argument("--kind", default="titles", choices=["titles", "locations"])
    fp.add_argument("--country", default="th", choices=["th", "hk", "my", "sg", "ph", "id"])
    fp.set_defaults(func=cmd_facets_v6)

    dp = sub.add_parser("doctor", help="Contract drift check against live API")
    dp.add_argument("--country", default="th", choices=["th", "hk", "my", "sg", "ph", "id"])
    dp.add_argument("--json", action="store_true", help="Machine-readable JSON report")
    dp.set_defaults(func=cmd_doctor)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
