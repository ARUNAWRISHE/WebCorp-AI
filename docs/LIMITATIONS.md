# Known limitations

- **Website coverage is bounded without a search engine.** About 11% of the 411,160 companies declare a website in
  the registry. The agent adds Wikidata, subunit, registered-email and name-derived domains, and probes
  contact/about/privacy pages. A discovered site is published only with organisation-number proof, the unique
  registered legal name *with its legal form* on the site, or the current legal name plus a registry contact
  match. In a 1,000-company test this verified about 11–12% of companies. Most of the rest have no
  public site, or use a brand unrelated to the legal name. Finding those needs a search API, which we do not have.
- **Jobs.** NAV registers ads against the *establishment* (subunit) number, so matching uses each company's registered
  subunits plus a full employer map of all active ads (seed cache plus run-time sync). About 0.7% of the universe has
  active NAV ads, so a random batch of 1,000 typically has fewer than 10 hiring companies on NAV. Company careers
  pages add machine-readable postings (JobPosting JSON-LD or ATS links) where they exist.
- **Reviews.** No permitted free review source exists. Official ratings are reported where they exist (Mattilsynet
  food-safety grades for restaurants, cafés and hotels), and official approvals for construction (DiBK) and cleaning
  (Arbeidstilsynet).
- **News.** Dated activity comes from the verified company website (JSON-LD articles, RSS/Atom, dated news cards,
  probed `/nyheter`, `/aktuelt`, `/feed/`) and official registry events (registration, articles, capital, role
  changes). Independent news media are not collected: no licensed news source is available, and name-based news
  matching has a high wrong-company risk.
- **JavaScript-only sites** are not rendered (no browser). Their identity text may be missing, so they end as
  `ambiguous` or `not_available` rather than risk a wrong match.
- **Accounts endpoint gaps.** Some banks and insurers return HTTP 500 from Regnskapsregisteret. This is reported as
  `failed`, never as zero.
- **Filing-year history** comes from an endpoint limited to about 30 requests per minute. In large batches, companies
  not reached inside the lane's time window are reported as `blocked` (rate limit) for that one field. Three years
  of normalised accounts are always present.
- **LLM synthesis** runs only where Ollama and `qwen3:8b` are installed. On Builderr's evaluator the cited
  deterministic template is used. The LLM paraphrase is validated (citations, verbatim source quotes, no new
  numbers, English only) but can still choose imprecise words; it is labelled as a machine paraphrase next to its
  sources. When enabled, it uses any time left in the budget, so local runs take the full budget.
- **Social profiles** are URLs declared by the company (site or Wikidata). The platforms are not fetched, so follower
  counts and engagement are not reported.
- **Robots policy for public APIs.** Some official API and open-data hosts disallow those paths for generic crawlers
  while documenting them for programmatic use. See the policy note in `docs/SOURCES.md`; the connectors can be
  turned off.
