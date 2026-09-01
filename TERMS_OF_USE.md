# Terms of Use

**TL;DR:** this is a read-oriented client for public job listings. Use it
lawfully, gently, and at your own risk. You are responsible for your traffic.

## 1. What this software is

`jobsdb-wrapper` is an unofficial, community-maintained client for the public
GraphQL endpoints of SEEK-operated job boards (th/hk.jobsdb.com,
my/sg/ph/id.jobstreet.com). It is **not affiliated with, endorsed by, or
connected to SEEK Ltd** or any of its subsidiaries.

## 2. Your responsibility

By using this package you agree that:

1. **You comply with the target site's Terms of Service.** Automated access
   may be restricted by those terms; whether and how you use this tool is your
   decision and your liability.
2. **You rate-limit yourself.** The default client ships at 60 requests/minute
   and backs off on 403/429/5xx. Do not disable this, do not run bulk crawls
   in parallel across many IPs, and do not hammer the endpoints. If you need
   data at scale, contact SEEK about their official APIs.
3. **You respect personal data law.** Job ads are public, but scraping for
   purposes like bulk profiling of individuals may trigger GDPR/PDPA
   obligations. The maintainers take no position on your use case.
4. **You use authenticated features only on your own account.** The
   `[session]` profile surface operates on cookies from *your own* logged-in
   browser. Using it against accounts you do not control is prohibited.

## 3. No warranty

The software is provided "as is", without warranty of any kind. SEEK may
change their platform at any time (the `jobsdb doctor` command exists
precisely because of this). The maintainers are not liable for blocked IPs,
lost sessions, stale data, or any damages arising from use of this package.

## 4. Acceptable-use summary

| Allowed | Not allowed |
|---|---|
| Personal job search & saved-search tooling | Reselling listing data as a commercial feed |
| Academic/research scraping at modest volume | Aggressive crawling / DoS-like load |
| Automating your **own** SEEK profile | Accessing accounts you don't own |
| Building a job aggregator with attribution | Stripping SEEK branding and republishing as your own board |

## 5. Changes

These terms may change between releases; the version in the latest published
package applies.
