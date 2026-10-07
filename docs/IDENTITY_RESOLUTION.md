# Identity resolution and publication gates

The organisation number is the only identity anchor. Names, domains and handles are candidates until they
are tied back to it. When the match is uncertain the agent returns `ambiguous` (with the candidate in the
note) and publishes nothing from that source.

## Exact by construction

| Source | Why it is exact |
|---|---|
| Brønnøysund APIs | Queried by organisation number |
| NAV job ads | Published only when the ad's `employer.orgnr` equals the company or one of its **registered establishments** (NAV registers every ad against the establishment number) |
| Wikidata | Used only when the item's P2333 statement equals the organisation number |
| Mattilsynet, Arbeidstilsynet, DiBK | Row or API record keyed by the organisation number (Mattilsynet: owner or establishment) |

## Website candidates

Tried in order, up to 4 crawls per company: registry-declared → Wikidata-declared → subunit-declared →
registered email domain (generic providers excluded) → domains derived from the current legal name (`.no`
first, ø→o and ø→oe spellings) → domains derived from distinct establishment trading names. Each crawl covers
the homepage and up to 5 linked identity, careers, news or team pages. If the candidate is still uncertain,
it also probes `/kontakt`, `/om-oss`, `/personvern` and similar paths (JavaScript menus often hide these).

## Website gate (`src/norway_company_agent/verify.py`)

| Evidence on the site | Declared candidate (registry, Wikidata, subunit) | Discovered candidate (email domain, derived domain) |
|---|---|---|
| Parked, for-sale or placeholder page (incl. a title that is just the domain) | rejected | rejected |
| **This organisation number**, or a registered establishment's number, in any format | exact (1.0 / 0.97); with ≥3 other org numbers listed, exact only if the legal name is the site's title or brand, otherwise ambiguous (directory or group page) | same |
| A *different* organisation number stated and the legal name not in the site identity | rejected | rejected |
| **The unique registered legal name with its legal form** ("Flislegger Simonsen AS") as title, brand, structured legal name or footer | exact | exact (0.92) for multi-word names; one-word names ("Nordlys AS") also need a registry corroborator; blocked if another org number is stated |
| Current legal name in site identity + registered phone, email or street address (or postcode + city) | exact | exact (0.93) |
| Current legal name as title or brand + a registered role holder named on the site | exact | exact (0.90) |
| Full legal name in identity, no corroboration | exact (0.95) | ambiguous |
| Otherwise | ambiguous | rejected |

Rules that prevent known wrong-company traps (each has a regression test):
- **Hostname is not name evidence.** For a domain derived from the name it would be circular. Foreign namesakes
  such as `bemaco.com` (a Spanish florist) are rejected.
- **Former names and role-holder names alone never qualify** a discovered domain. They often point to a successor
  or sister company run by the same person.
- **Group, brand and franchise sites:** a declared site that does not present this entity as its own title or brand
  (e.g. `7-eleven.no` for a franchisee) is reported as `registry_website` (what the registry says) with
  `official_website: ambiguous`. Its social profiles, news and jobs are not attributed.
- Placeholder org numbers (`123456789` etc.) are ignored.

## Facts that depend on the website

Only after the site passes the gate *and* is entity-specific:
- social profile links on the site or in its JSON-LD `sameAs`, kept only when the handle matches the legal name,
  brand or domain label (this filters out agency credits and platform widgets);
- careers page, JobPosting JSON-LD and job links to known applicant-tracking systems;
- dated news: JSON-LD articles, RSS/Atom, `<time>`-dated cards, `article:published_time`, and probed
  `/nyheter`, `/aktuelt` and `/feed/`;
- role holders named on the site are added as corroborating evidence to the official role claim.
