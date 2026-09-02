# JobsDB Wrapper — Guest Mode (v4)

> **Guest-only by design.** Since v4.0.0 this package ships **no authentication
> surface**: no login, no cookie handling, no profile access. SEEK sessions are
> server-side and cannot be created or exercised safely from a third-party
> client. The v3 profile/session modules (`jobsdb_wrapper.profile.*`,
> `extract-cookies`, `browser-login`, `auth`) were removed.

## What Works (guest / anonymous)

| Operation | CLI | Python API |
|-----------|-----|------------|
| Job search (full filter surface) | `jobsdb search` | `client.search()` |
| Paginate all results | `jobsdb search -l N` | `client.iter_all()` |
| Full posting (Markdown) | `jobsdb job <id>` | `client.job_markdown()` |
| Full posting (JSON) | `jobsdb job <id> --json` | `client.job()` |
| Location autocomplete | `jobsdb locations <prefix>` | `client.locations()` |
| Title/location facets | `jobsdb facets-v6` | `client.title_facets()` / `client.location_facets()` |
| Bulk parallel details | — | `AsyncJobsDBClient.fetch_details_many()` |
| SQLite detail cache | `jobsdb job --cache FILE` | `JobsDBClient(detail_cache=...)` |
| Live contract drift check | `jobsdb doctor` | — |

**Deliberately not implemented:**
- Login / account creation (SEEK has no email/password GraphQL login)
- Profile read/write, skills, experience, education (authenticated surface)
- Save/apply to jobs (not in the captured guest contract)
- Browser automation / cookie extraction (removed in 4.0.0)

---

## Quick Start

```bash
pip install jobsdb-wrapper
```

### Python API

```python
from jobsdb_wrapper import JobsDBClient

with JobsDBClient() as client:
    res = client.search("python developer", where="Bangkok",
                        salary_min=30000, posted_within_days=14)
    for job in res.jobs:
        print(job.id, job.title, job.company, job.salary_label)

    detail = client.job(res.jobs[0].id)
    print(detail.content_html)

    md = client.job_markdown(res.jobs[0].id)
```

### CLI

```bash
jobsdb search "python developer" --where Bangkok --salary-min 50000 --json
jobsdb job 94162495 -o job.md
jobsdb locations "bangkok"
jobsdb facets-v6 "python" --kind titles
jobsdb doctor
```

### Async bulk

```python
import asyncio
from jobsdb_wrapper import AsyncJobsDBClient

async def main():
    async with AsyncJobsDBClient(concurrency=5) as client:
        res = await client.search("data analyst", page_size=50)
        details = await client.fetch_details_many([j.id for j in res.jobs])
        print(len(details), "postings fetched")

asyncio.run(main())
```

### Filters

`search()` supports: `keywords`, `where`, `distance_km`, `work_types`
(`full_time|part_time|contract|casual`), `work_arrangements`
(`on_site|hybrid|remote`), `salary_min/max/period` (`hourly|monthly|annual`),
`posted_within_days`, `categories`, `advertiser_id`, `organisation_ids`,
`company`, `tags`, `sort` (`relevance|date`), `page`, `page_size`,
`include_facets`.

### Markets

`country` accepts `th`, `hk`, `my`, `sg`, `ph`, `id` (JobsDB/JobStreet unified
SEEK platform). Locale override via `locale="th-TH"`.

### Rate limits & blocking

Upstream allows roughly 60 requests/min per IP. On sustained use the /graphql
route may start challenging requests — the client raises `JobsDBBlockedError`
after one retry. Set `rate_limit_rpm`, a `proxy` (or `JOBSDB_PROXY` env), and
respect `robots.txt` / the site's terms of use.
