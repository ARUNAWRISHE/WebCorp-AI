# Sources, access rights and data handling

Every published claim carries its source URL, retrieval time, content SHA-256, extractor version and a
claim span (text excerpt or JSON path). Raw response bytes are stored content-addressed under
`state/snapshots/` so evidence stays verifiable after a refresh.

| Source | Used for | Access | Licence / terms | Stored | Limits we respect |
|---|---|---|---|---|---|
| Brønnøysund Enhetsregisteret API (`data.brreg.no/enhetsregisteret`) | Identity, status, address, industry, registered activity, employees, capital, former names, roles, subunits, group structure | Official open API, no key | [NLOD 2.0](https://data.norge.no/nlod/en/2.0) | Raw JSON | ≤8 concurrent requests; birth dates in role records are **not** stored |
| Regnskapsregisteret API (`data.brreg.no/regnskapsregisteret`) | Normalised annual accounts (up to 3 years, company and group), filed-year list and official copy links | Official open API, no key | NLOD 2.0 | Raw JSON | Copy-year endpoint ≈30 req/min: single throttled lane (2.05 s spacing, honours `x-rate-limit-remaining`) |
| NAV Arbeidsplassen public job feed (`pam-stilling-feed.nav.no`) | Active job postings, exact via `employer.orgnr` | Official public API; the public token is fetched at run time from NAV's published `/api/publicToken` endpoint (not tied to any personal account) | [NAV API terms](https://arbeidsplassen.nav.no/vilkar-api): free, republishing allowed; inactive ads must be removed | Raw ad JSON (contact persons are **not** copied into claims) | Only `ACTIVE`, unexpired ads are published; a refresh reports `closed_job` when an ad disappears |
| Wikidata API (`www.wikidata.org/w/api.php`) | Knowledge-base entry, declared website and social handles, exact via property P2333 (Norwegian organisation number) | Public API, no key, descriptive User-Agent | CC0 | Raw JSON | ≤3 concurrent requests, batched (40 org numbers per search) |
| Company websites (registry-declared, Wikidata-declared, subunit-declared, registered email domain, or a domain derived from the legal name) | Official website, brand, description, company-linked social profiles, careers page, job postings (JobPosting JSON-LD / ATS links), dated news (JSON-LD, RSS/Atom, `<time>` cards), leadership corroboration | Plain HTTP GET, `robots.txt` enforced (RFC 9309: 4xx = allow, 5xx/blocked = disallow), ≤2 concurrent requests per host, ≤6 pages + 1 feed per site, 10 s timeout, 2 MB cap, public-IP guard on every redirect | Company-owned content; used as a company-reported claim layer only | Raw HTML | No search-engine result scraping, no login, no JavaScript rendering, no CAPTCHA handling |
| Local LLM (optional, Ollama `qwen2.5:7b`, Apache-2.0) | Rewording of already-verified, cited facts into a summary | Local process on the operator's GPU; disabled automatically when not present | Apache-2.0 model licence | Nothing | Every sentence must cite claim ids and every number must appear in the cited claims, otherwise the deterministic template is used |

## Not used

- No search engine API (no key available) and no scraping of search result pages.
- No LinkedIn, Meta, Instagram, X, Glassdoor or Indeed scraping. Social profile URLs are published only when
  they are linked from the verified company website or listed on the company's Wikidata item; the platforms
  themselves are not fetched.
- The starter kit's experimental scripts (`run_linkedin_guest_*`, `run_google_news_rss_connector.py`,
  `run_fagfolkguiden_reviews_connector.py`, `run_youtube_search_connector.py`) are **not** called by the agent.

## Secrets

The agent needs no secrets. Optional settings are environment variables only (`SIGNALPOST_TIME_BUDGET_SECONDS`,
`SIGNALPOST_WORKERS`, `SIGNALPOST_STATE_DIR`, `SIGNALPOST_LLM`, `SIGNALPOST_LLM_MODEL`, `SIGNALPOST_REGISTRY_SNAPSHOT`, `SIGNALPOST_RUN_ID`).

## Third-party cost

All sources are free. Declared third-party cost per official run: **USD 0**.
