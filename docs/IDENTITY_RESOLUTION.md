# Identity resolution and publication gates

The organisation number is the only identity anchor. Names, domains and handles are candidates until they
are tied back to it. When the match is uncertain the agent returns `ambiguous` (with the candidate in the
note) and publishes nothing from that source.

## Exact by construction

| Source | Why it is exact |
|---|---|
| Brønnøysund APIs | Queried by organisation number |
| NAV job ads | Published only when the ad's `employer.orgnr` equals the company or one of its registered subunits; ads are found by employer name, then verified on the detail record |
| Wikidata | Used only when the item's P2333 statement equals the organisation number |

## Website gate (`src/norway_company_agent/verify.py`)

Candidates are tried in order: registry-declared → Wikidata-declared → subunit-declared → registered email
domain (generic mail providers excluded) → domains derived from the current legal name. Up to 4 sites are
crawled per company (homepage + up to 5 identity/careers/news/team pages + 1 feed).

| Evidence on the site | Registry/Wikidata/subunit-declared | Email domain / derived domain |
|---|---|---|
| Parked, for-sale or placeholder page | rejected | rejected |
| This organisation number appears (any format: `916 617 445`, `916.617.445`, `NO916617445MVA`) | **exact (1.0)** unless ≥3 other org numbers are listed (directory/group page → ambiguous) | **exact (1.0)**, same exception |
| A *different* organisation number is stated, and the legal name is not in the site identity | rejected | rejected |
| Full legal name in homepage identity (title, og:site_name, JSON-LD name, footer, host) | exact (0.95) | ambiguous, unless a contact corroborator also matches |
| Current legal name in identity **and** registered phone, email or street address on the site | exact | **exact (0.93)** |
| Partial name + any registry corroborator | exact (0.92) | ambiguous |
| Two registry corroborators | exact (0.90) | ambiguous |
| Otherwise | ambiguous | rejected |

Former names and role-holder names never suffice for a discovered domain: they often point to a successor
or sister company run by the same person (regression test `test_former_name_plus_role_holder_is_not_exact_for_discovered_domain`).

## Facts that depend on the website

Only after the site passes the gate:

- social profile links on the site or in its JSON-LD `sameAs`, kept only when the handle matches the legal
  name, the site brand or the domain label (filters agency credits and platform widgets);
- careers page, JobPosting JSON-LD and job links to known applicant-tracking systems;
- dated news (JSON-LD articles, RSS/Atom items, `<time>`-dated cards, `article:published_time`);
- role holders named on the site are added as corroborating evidence to the official role claim.

## Measured behaviour (development runs)

See `reports/` for the latest smoke-test report. In development batches, plausible-but-unproven candidates
such as `nordlys.no` (a newspaper) for *NORDLYS. AS* and `peta.com` for *PETA AS* were held back as `ambiguous`.
