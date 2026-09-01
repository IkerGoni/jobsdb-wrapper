# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [4.0.0] - 2026-09-13

**Guest-only rewrite.** The entire authentication/profile surface was removed
so the package does one thing well: anonymous job search and posting
extraction.

### Removed (BREAKING)
- `jobsdb_wrapper.profile` and all root shims (`user.py`, `cookie_jar.py`,
  `safari_cookies.py`, `browser_auth.py`) — profile read/write, Chrome/Safari
  cookie decryption, browser login.
- `[session]` extra (pycryptodome, zendriver, binarycookie). Core dependency
  is `curl_cffi` only.
- Client methods: `load_browser_cookies`, `import_cookie_dict`, `verify`,
  `get_profile`, `get_score`, `get_suggestions`, `get_suggested_skills`,
  `update_personal_statement`, `add_skill`/`update_skills`,
  `add/update/delete_experience`, `get_roles`, `user_manager`.
- CLI commands: `login`, `profile`, `profile-edit`, `save`, `apply`,
  `experience`, `education`, `skill`, `auth`, `browser-login`,
  `extract-cookies`. Remaining: `search`, `job`, `locations`, `facets-v6`,
  `doctor`.
- `examples/demo_user_features.py`, `docs/captures/profile-ops.json`,
  `tests/test_user.py`.

### Why
SEEK sessions are server-side and revocable; exercising them from a
third-party client carries maintenance and safety burdens that outweigh the
value for a guest-scraping library. The v3 implementation is preserved in
git history (`v3.0.1`) if it is ever needed.

### Added
- `docs/FAILURE_MATRIX.md` — failure-mode matrix (network, Cloudflare
  challenge, GraphQL soft/hard errors, bot-score adaptation, drift).
- CI: `security` job (gitleaks secret scan + pip-audit dependency audit);
  build job now gates on it.

### Changed
- `RateLimiter.wait()` now reserves the slot before sleeping (concurrent
  callers serialize instead of thundering-herd).
- Docs (README, USER_GUIDE, MANIFEST) rewritten guest-only and truthful.

## [3.0.1] - 2026-08-31

Post-audit release (see `docs/audit-v3-report.md`): fixes H1–H4, hardening
H5–H10, packaging split, test coverage 50 → 79.

### Fixed
- **H1** — CLI `search -l` no longer aliases `--where`; it is a real
  `--limit/-l` output cap.
- **H2** — `locations()` / `include_suggestions` now actually return data.
  Live contract verified 2026-08-31: the server-side autocomplete trigger is
  the `where` search text (not keywords); completions expose `id` + `kind`
  (`SEEK_AREA`, `REGION`, …). The human-readable `label` field requires an
  undocumented `SeekLocationContext` enum value that is not present in any
  captured traffic — probing ~50 candidate values via the live API all failed
  schema validation, so completions are surfaced id+kind only, documented as
  such in `LocationSuggestion`.
- **H3** — CLI `profile --profile-path` is now passed as `profile_path=`
  (previously mis-routed into `profile_name`, always failing).
- **H4** — `AsyncJobsDBClient.close()` (sync path) no longer calls the async
  session's coroutine `close()`; guard by concrete `Session` type.
- **H5** — Chrome cookie v10 decrypt: `meta.version >= 24` framing
  (SHA256(host)[32] || value) asserted before slicing.
- **H7** — `RateLimiter` is thread-safe (lock around wait/adapt).
- **H9/H10** — exported session files get `chmod 0600`; cookie-name prefixes
  are never printed.

### Changed
- **Packaging split** — core install needs only `curl_cffi`; profile/session
  features are behind the `[session]` extra with lazy imports, so
  `import jobsdb_wrapper` never pulls pycryptodome/zendriver.
- `JobsDBUserManager` is lazily constructed inside both clients (importing
  it at module level would break core-only installs).
- Tests: +29 offline tests on core paths (client lifecycle, graphql retry,
  search param wiring, suggestions parsing, classify/interpret branches,
  doctor shape, CLI guard without the extra).
- `pyproject.toml`: `[session]` extra, project urls, ruff.lint config.

## [3.0.0] - 2026-08-30

### Changed (BREAKING)
- **Two-group packaging**: `pip install jobsdb-wrapper` installs the search core
  (curl_cffi only). Profile/session features moved to `jobsdb_wrapper.profile`
  and are opt-in via `pip install jobsdb-wrapper[session]`
  (pycryptodome, zendriver, binarycookie). CLI profile/session subcommands
  print the install hint and exit non-zero when the extra is absent.
- **Real SEEK GraphQL contract**: replaced invented ops (`LoginUser`, `GetUserProfile`,
  `UpdateProfile`, `AddExperience`, `ApplyToJob` — none exist in SEEK's schema) with
  operations captured from the live th.jobsdb.com profile UI:
  `GetScore`, `GetSuggestions`, `GetSuggestedSkills`, `GetPersonalDetails`,
  `GetConfirmedRoles`, `GetSkills`, `GetCareerObjectives`, `GetResumes`,
  `UpdateCareerObjectives`, `UpdateRole`, `UpdateSkills`, `getRoleTitle`, `getSpecReqs`.
- **user_manager is always instantiated** on `JobsDBClient` / `AsyncJobsDBClient`
  (previously `None` without auth). Session-required methods raise `JobsDBError`
  until `load_browser_cookies()` or `import_cookie_dict()` is called.
- Removed invented public methods that silently did nothing; they now raise with a
  clear "not a real op / not captured" message pointing at the real alternative.
- `auth0` cookie is host-only for `login.seek.com` and never sent to the market
  domain; `appSession` + `JobseekerSessionId` are what matters for API calls.
- Client transport now sends full SEEK session headers:
  `seek-request-brand`, `seek-request-country`, `x-seek-site: Profile web UI`,
  `x-seek-ec-sessionid` / `x-seek-ec-visitorid` (UUID v4).

### Added
- `profile/` subpackage: `user`, `cookie_jar` (Chrome cookie decryption, Keychain
  "Chrome Safe Storage" → PBKDF2-SHA1 1003 iterations → AES-128-CBC, incl. Chrome
  151 meta-v24 plaintext = SHA256(host_key)[32B] || value), `safari_cookies`,
  `browser_auth`. Top-level `user`/`cookie_jar`/`safari_cookies`/`browser_auth`
  modules remain as deprecated shims re-exporting from the subpackage.
- `safari_cookies.py`: Safari cookie extraction.
- `SessionExpiredError`: raised when SEEK rejects a replayed session
  server-side (sessions are revocable regardless of JWE lifetime); probe with
  read-only `GetScore` via `user_manager.verify()`.
- `docs/captures/profile-ops.json`: 38 redacted GraphQL operations (query +
  variables) harvested from browser HARs — the persistent source of the real contract.
- `browser_auth.extract_chrome_cookies()` now decrypts via `cookie_jar`
  (profile-copy to temp dir handles SQLite lock).

### Fixed
- Duplicate `SessionInfo` dataclass definition shadowed itself.
- Docs no longer contain real session ids / JWE fragments.
- `client.add_skill(name, level=…, years_experience=…)` no longer leaks `level`
  into the `ontology_id` positional argument.
- `AsyncJobsDBClient` user ops were calling ten non-existent `user_manager.async_*`
  methods (AttributeError) and `async_get_profile()` returned an un-awaited
  coroutine; all user ops now delegate to the real sync profile contract via
  `asyncio.to_thread`.
- `async_client` respects the same `_require_user_context()` rule as sync.

### Removed (truth-correction; these never matched SEEK's schema)
- `JobsDBAuth.authenticate()` / `request_magic_link()` / `verify_magic_link()` /
  `authenticate_with_magic_link()` were built on invented `LoginUser` /
  `RequestMagicLink` / `VerifyMagicLink` mutations — no such operations exist on
  `th.jobsdb.com/graphql`. Sessions are browser-created and server-side.
- `client.request_magic_link` / `verify_magic_link` / `authenticate_with_magic_link`
  sync wrappers and their async equivalents.
- CLI `auth import --cookies-file/--cookies/--session-id/--user-id/--days`
  fabricated a file session the transport never used. `auth import` now explains
  the browser-first flow; `auth status` is labeled as bookkeeping-only.
- CLI `login` (email/password) now answers truthfully: SEEK has no such login.
- CLI `save` / `apply` now report that bookmarking/apply are not part of the
  captured contract instead of pretending a result existed.
- `cmd_extract_cookies` / `cmd_browser_login` no longer require the host-only
  `auth0` cookie (that cookie never travels to the market domain) and save a
  plain cookie dict for `import_cookie_dict()`.

### Added (client facade)
- Sync surface for the real profile contract: `verify()`, `get_score()`,
  `get_suggestions()`, `get_suggested_skills()`, `get_roles()`,
  `update_personal_statement()`, `update_skills()`.
- Async equivalents on `AsyncJobsDBClient`.
- CLI `profile` now decrypts the local Chrome SEEK session and prints
  seeker id / completeness / suggested skills / confirmed roles; honours
  `--profile-path`.

## [2.1.0] - 2026-08-25

### Added
- User authentication system with email/password and magic link (Gmail) support
- Cookie import for Google OAuth accounts (requires `appSession`, `JobseekerSessionId`, `auth0` cookies)
- Session persistence to `~/.jobsdb_session.json`
- User profile management (name, headline, summary, avatar, location)
- Work experience management (add, update, delete)
- Education management (add, update, delete)
- Skills management with proficiency levels
- User settings (notifications, job alerts, privacy, language)
- Job application with cover letter and custom fields
- Application status tracking (pending, reviewed, rejected, hired)
- Job saving/bookmarking
- Async support for all user management features
- Browser automation for Google OAuth login flow

### Changed
- Enhanced CLI with new commands: `login`, `profile`, `save`, `apply`, `auth`, `profile-edit`, `experience`, `education`, `skill`
- Updated README with comprehensive authentication and user management documentation
- Added detailed USER_GUIDE.md in src/jobsdb_wrapper/

### Fixed
- Clarified auth0 cookie domain requirement (must be from correct regional domain)
- Fixed cookie export instructions for all major browsers

## [2.0.0] - 2026-08-20

### Added
- Async client (`AsyncJobsDBClient`) with bounded concurrency
- SQLite detail cache with content-hash validation
- Lazy pagination iterator (`iter_all`)
- Discovery helpers: `title_facets`, `location_facets`, `company`
- Contract drift detection (`doctor` command)
- Adaptive rate limiting based on `seek-bot-score` header
- Multi-market support: th, hk, my, sg, ph, id
- Full filter surface: keywords, location+radius, work type, arrangement, salary, posting age, categories, advertiser/org filters, tags, sort

### Changed
- **Breaking**: Major refactor — sync/async clients share pure search-param builder
- **Breaking**: Response classification taxonomy: `ok | network | http | runtime | blocked`
- **Breaking**: CLI output format changes (JSON structure updated)

### Fixed
- Salary period encoding (hourly|monthly|annual)
- Page size clamped to upstream max of 30

## [1.0.0] - 2026-08-15

### Added
- Initial release: Free pure-HTTP GraphQL client for th.jobsdb.com
- Search with all website filters
- Full job detail fetch as structured data and Markdown
- CLI and Python API
- No browser, no CAPTCHA, no credentials required

---

## Upgrade Notes

### 1.x → 2.0
- `JobsDBClient` constructor signature changed
- `search()` parameters reorganized
- Response objects have new structure
- Run `jobsdb doctor` after upgrade to verify API compatibility

### 2.0 → 2.1
- Backward compatible — all existing code works unchanged
- New features require optional `JobsDBAuth` initialization
- New CLI commands available