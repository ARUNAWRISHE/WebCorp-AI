# Sources, access rights and data handling (rights matrix)

Every published claim carries its source URL, retrieval time, content SHA-256, extractor version and a claim
span (text excerpt, JSON path or CSV row key). Raw response bytes are stored content-addressed under
`state/snapshots/`, except where a source asks us not to store them (DiBK).

## Access policy

- **Company websites (crawling):** `robots.txt` is enforced (RFC 9309: a 4xx robots file means allow; 5xx or an
  unreachable host means do not crawl). Limits: at most 2 concurrent requests per host, about 6 pages plus 1
  feed per site, 8–10 s timeouts, a 2 MB cap, and a public-IP guard on every redirect. No logins, no
  JavaScript rendering, no CAPTCHA handling, no search-result scraping.
- **Documented public APIs and open-data files:** used as their publishers document them, with a descriptive
  User-Agent and modest concurrency. Several of these hosts publish a generic `robots.txt` that disallows
  their API or data paths for *web crawlers* (Wikidata `/w/`, DiBK `/api/`, Mattilsynet `/`), while their API
  or data documentation invites programmatic use. We follow the documented terms for these endpoints and
  list them below. **Decision (2026-10-08): these documented APIs and open-data files are used**, because each
  publisher explicitly offers them for programmatic use: Wikimedia's API etiquette for bots, DiBK's API documentation
  ("free for all systems, no registration"), and Mattilsynet's CC BY 4.0 distribution in the national data catalogue.
  Their robots rules target web crawlers indexing pages. We respect each publisher's terms: a descriptive User-Agent,
  low concurrency, CC BY attribution for Mattilsynet, and no permanent storage of DiBK responses. Each connector
  can be turned off with `--no-wikidata` or `--no-registers`.

## Matrix

| Source | Facts | Exact identity | Access / terms | Licence | Stored | Robots on host |
|---|---|---|---|---|---|---|
| Brønnøysund Enhetsregisteret API | Identity, status, addresses, NACE, registered activity, employees, capital, former names, roles, subunits, group structure, role-change history | Queried by org number | Open API, no key | [NLOD 2.0](https://data.norge.no/nlod/en/2.0) | Raw JSON | No robots file served |
| Regnskapsregisteret API | 3 years of normalised accounts (company and group), filed years and official copy links | Queried by org number | Open API, no key; copy-year endpoint about 30 requests/min (throttled lane, honours `x-rate-limit-remaining`) | NLOD 2.0 | Raw JSON | No robots file served |
| NAV Arbeidsplassen public job feed | Active job postings | `employer.orgnr` equals the company or a registered subunit | Public feed; NAV publishes the public token at `/api/publicToken` (not tied to any account). [Terms](https://arbeidsplassen.nav.no/vilkar-api): free, republishing allowed, inactive ads must be removed | NAV API terms | Ad metadata only (employer org number, title, dates, location, occupation). **No contact persons or descriptions** | 404 (allow) |
| NAV ad metadata cache `data/nav-ad-cache.jsonl.gz` (declared cache) | Same as above, pre-fetched | Re-validated each run: an ad is published only if it is `ACTIVE` in *today's* feed with an unchanged `sistEndret` and not expired | Built with `scripts/build_nav_seed_cache.py` | NAV API terms | Metadata only | — |
| Wikidata API | Knowledge-base entry, declared website, social handles | Item's P2333 equals the org number | Public API, Wikimedia User-Agent policy, at most 3 concurrent requests, batched | CC0 | Raw JSON | Disallows `/w/` for crawlers; API use for bots is sanctioned by Wikimedia |
| Mattilsynet smilefjes inspections (`data.mattilsynet.no/smilefjes-tilsyn.csv`) | Food-safety inspection grade and history per establishment | Row `orgnummer` equals the company or a subunit | Open-data distribution listed in the national data catalogue; one download per run, cached for 20 h | CC BY 4.0 (attribution: "Contains data from Mattilsynet") | Raw CSV | Disallows `/` for crawlers |
| Arbeidstilsynet cleaning-company register (`registerdata.arbeidstilsynet.no/renhold_register.xml`) | Approval status | `Organisasjonsnummer` equals the company | Daily open data | NLOD | Raw XML | 403 (allow) |
| DiBK central approval register API (`sgregister.dibk.no/api/enterprises/{org}`) | Approval status, validity, approval areas and classes | Queried by org number (construction and engineering NACE codes only) | DiBK documents the API as free for systems, no registration, and asks users **not to store** register data permanently | Open public register | **Not stored**: URL, time, hash and span only | Disallows `/api/` for crawlers |
| Company websites | Verified official website, brand, description, company-linked social profiles, careers page, job postings, dated news, leadership corroboration | Identity gate (`docs/IDENTITY_RESOLUTION.md`) | Crawling policy above | Company-owned content, used as a company-reported layer | Raw HTML | Enforced |
| Local LLM (optional, Ollama `qwen3:8b`, Apache-2.0) | Plain-English paraphrase of cited registered purpose, change list and unknowns | Uses only verified claims; validated per part | Local process on the operator's GPU; absent elsewhere | Apache-2.0 | Nothing | — |

## Not used

- No search-engine API (no key available) and no scraping of search result pages.
- No LinkedIn, Meta, Instagram, X, Glassdoor, Indeed, Trustpilot or Google Maps scraping. Social profile URLs are
  published only when linked from the verified company website or listed on the company's Wikidata item.
- **Reviews:** no permitted, free source of customer or employee reviews exists for Norwegian companies, as far
  as I know. Google Places and Trustpilot require paid or approved API keys, and the platforms' terms forbid
  scraping. The agent instead reports official ratings where they exist (Mattilsynet food-safety grades) and
  official approvals (DiBK, Arbeidstilsynet).
- Brreg announcements (`w2.brreg.no/kunngjoring/`) are disallowed by robots.txt and are not used. Dated registry
  changes come from the official update API instead.
- The starter kit's experimental platform scripts (LinkedIn guest pages, Google News RSS, Fagfolkguiden, YouTube
  search, Google Maps normalisation) have been **removed** from this repository.

## Secrets

None required. Optional settings are environment variables only: `SIGNALPOST_TIME_BUDGET_SECONDS`,
`SIGNALPOST_WORKERS`, `SIGNALPOST_STATE_DIR`, `SIGNALPOST_LLM`, `SIGNALPOST_LLM_MODEL`,
`SIGNALPOST_REGISTRY_SNAPSHOT`, `SIGNALPOST_RUN_ID`.

## Third-party cost

All sources are free and the optional model runs locally. **Declared third-party cost per official run: USD 0.**
