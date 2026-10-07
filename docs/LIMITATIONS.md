# Known limitations

- **Website coverage is bounded.** Only about 11% of the 411,160 companies declare a website in the registry.
  The agent adds registered email domains, Wikidata and name-derived domains, but publishes a discovered site
  only with organisation-number proof or the current legal name plus a registry contact match. Many small
  holding and property companies have no public site at all; these are reported as `not_available`, and
  unproven candidates as `ambiguous`.
- **No search engine.** No search API key is available. Sites that use a brand name unrelated to the legal name,
  and have no registry or email link, are not found.
- **Jobs.** NAV Arbeidsplassen ads are matched by employer name and then verified by organisation number. Ads whose
  employer name differs from both the legal name and the registered subunit names are missed. Ads on the company's
  own careers page are found only when they are machine-readable (JobPosting JSON-LD) or link to a known ATS.
- **Activity.** Dated activity comes from the verified company site (JSON-LD, RSS/Atom, dated cards) and official
  registry events (registration, articles, capital and role-group update dates). Independent news and sentiment
  are not collected, because no licensed news source is available.
- **JavaScript-only sites** are not rendered (no browser). Their homepage may lack identity text, so they end as
  `ambiguous` or `not_available` rather than risk a wrong match.
- **Accounts endpoint gaps.** Some banks and insurers return HTTP 500 from Regnskapsregisteret. This is reported as
  `failed` with the error, never as zero.
- **Filing-year history** comes from a rate-limited endpoint (about 30 requests per minute). In a 1,000-company run with a
  short budget, companies not reached are reported as `blocked` (rate limit) for that one field. The 3-year
  normalised accounts are still present.
- **Local LLM summaries** run only where Ollama and the model are installed. Elsewhere, or when it fails validation,
  the cited deterministic template is used.
- **Social profiles** are URLs declared by the company (site or Wikidata). The platforms are not fetched, so follower
  counts and engagement are not reported.
