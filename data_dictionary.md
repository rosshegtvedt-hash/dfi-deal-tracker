# DFI Deal Flow Tracker — Data Dictionary

Database: `data/dfi_tracker.db` (SQLite). Created by `database.py`.

## Table: `projects`

One row per project/transaction disclosed by a development finance institution.

| Field | Type | Description |
|---|---|---|
| `id` | INTEGER | Auto-assigned row ID. Internal only — not stable across reloads. |
| `institution` | TEXT | Short code of the DFI: `DFC`, `IFC`, `EBRD`, `AfDB`, `BII`, `FMO`, `Proparco`. |
| `project_name` | TEXT | Project or client name as disclosed by the institution. |
| `country` | TEXT | Country of the project as reported by the source. Regional/multi-country deals keep the source's label (e.g. "Africa Regional"). Not yet normalized across institutions. |
| `region` | TEXT | Region as reported by the source. Each DFI uses its own region taxonomy — do not compare regions across institutions without mapping. |
| `sector` | TEXT | Broad sector as reported by the source (each DFI has its own taxonomy). |
| `subsector` | TEXT | Finer sector detail where the source provides it; otherwise NULL. |
| `instrument` | TEXT | Financial product: loan, equity, guarantee, insurance, investment fund, etc. Source's own terminology. **Means "what the source we loaded published"** — stays NULL where that source publishes none, even if the institution states it elsewhere. |
| `instrument_enriched` | TEXT | Instrument recovered from a *different publication by the same institution*, used only where the loaded source publishes none. Today AfDB only, from its IATI finance type (e.g. `421 Standard loan`), set by `enrich_afdb_instruments.py`. Never overwrites `instrument`. |
| `amount_original` | REAL | Committed amount in the source's reporting currency, in **plain units** (dollars, not millions). |
| `currency` | TEXT | ISO 4217 code of `amount_original` (e.g. `USD`, `EUR`). |
| `amount_usd` | REAL | Committed amount converted to **plain US dollars**. For USD sources this equals `amount_original`. |
| `approval_date` | TEXT | Date of board approval / commitment, ISO `YYYY-MM-DD`. NULL if the source only discloses a fiscal year or nothing — never guessed. |
| `fiscal_year` | INTEGER | The institution's fiscal year of commitment, for sources (like DFC) that disclose only a year and no exact date. Note fiscal years differ by institution (DFC: Oct 1–Sep 30). |
| `status` | TEXT | Project status as reported (e.g. Active). NULL if the source doesn't report one. |
| `es_category` | TEXT | Environmental & social risk category (e.g. A/B/C) where disclosed. |
| `sponsor` | TEXT | Project sponsor / borrower / investee where disclosed. Raw source value; only IFC, Proparco, ADB and IDB Invest publish one. |
| `counterparty` | TEXT | Who the deal was WITH. Either the disclosed sponsor verbatim, or a client name cleaned out of `project_name`. Set by `derive_counterparties.py`. NULL where no client could be identified without guessing. |
| `counterparty_key` | TEXT | `counterparty` uppercased, legal form removed, punctuation collapsed. The join key for "who appears in two institutions' books". An exact-match normalisation, NOT a fuzzy score. |
| `mobilised_original` | REAL | Third-party capital raised alongside this deal, in the deal's currency. **Never part of `amount_original`** — it is other people's money. Today IDB Invest only. A zero means "reported, none"; NULL means not reported. |
| `mobilised_usd` | REAL | The same in USD, converted at the **deal's own** rate rather than a separately looked-up one, so the pair can never sit on different years. NULL rather than unconverted when there is no rate to reuse. |
| `counterparty_provenance` | TEXT | `disclosed` (the source named the client) or `derived_from_project_name` (we cleaned it out of the project title). Always check this before quoting a client relationship. |
| `description` | TEXT | Free-text project description from the source. |
| `source_url` | TEXT | URL of the disclosure page or file this record was loaded from. |
| `scraped_at` | TEXT | UTC timestamp (ISO) of the load run that produced this row. |
| `canonical_sector` | TEXT | Harmonized sector from `sector_mapping.csv`, set by `harmonize.py`. `Unclassified` when the source reported no sector. |
| `canonical_subsector` | TEXT | Harmonized subsector where the source label is specific enough to support one; otherwise NULL. |
| `probable_duplicate_group` | TEXT | Group ID (`DUP-0001`, ...) linking records that are probably the same co-financed deal disclosed by multiple institutions. Set by `dedupe.py`. A flag for review — nothing is deleted or merged. |
| `canonical_country` | TEXT | Harmonized country name from `country_mapping.csv`, set by `harmonize.py` ('Turkiye'/'Türkiye'/'Turkey' → 'Türkiye'). Regional deals get 'Regional — ...' labels. Use this, not `country`, for any cross-institution analysis. |
| `canonical_region` | TEXT | World Bank-style region from `country_mapping.csv`: Sub-Saharan Africa, Middle East & North Africa, Europe & Central Asia, South Asia, East Asia & Pacific, Latin America & Caribbean, plus Western Europe, North America, Global / Multi-Region, Undisclosed. |

### Reload behavior

Each loader run **replaces** all rows for its institution (delete-then-insert),
so rerunning a loader never creates duplicates. Historical snapshots are the
date-stamped raw files kept in `data/raw/`.

## Table: `quality_issues`

One row per data problem found during a load. The affected project row is
still inserted into `projects` (with NULL in the problem field) — problems are
logged, never silently dropped or filled in.

| Field | Type | Description |
|---|---|---|
| `id` | INTEGER | Auto-assigned row ID. |
| `institution` | TEXT | Which DFI's load produced the issue. |
| `project_name` | TEXT | Project the issue relates to, if identifiable. |
| `issue_type` | TEXT | Machine-readable code: `missing_amount`, `unparseable_date`, `missing_project_name`, etc. |
| `detail` | TEXT | Human-readable explanation, including the raw value that failed. |
| `raw_row` | TEXT | JSON snapshot of the original source row, for audit. |
| `logged_at` | TEXT | UTC timestamp (ISO) when the issue was logged. |

## Source notes

### DFC (`scrapers/dfc.py`)

- Source: official downloadable Excel published on
  <https://www.dfc.gov/our-impact/transaction-data> ("Annual Project Data").
  Published deliberately for public use; updated after each fiscal year /
  quarter. The file URL is a constant at the top of `scrapers/dfc.py` —
  update it when DFC posts a new release.
- All DFC amounts are USD, so `currency = 'USD'` and
  `amount_original = amount_usd`.
- Column mapping from the source file to this schema is documented in
  `scrapers/dfc.py`.

### IFC (`scrapers/ifc.py`)

- Source: "IFC Investment Services Projects" dataset (DS00499) on the World
  Bank Group's Finances One open-data platform,
  <https://financesone.worldbank.org/ifc-investment-services-projects/DS00499>.
  Official machine-readable API, updated daily, CC-BY licensed — chosen over
  scraping IFC's JavaScript disclosure portal. Paginated at 1,000 records per
  request with a 1-second polite delay.
- All amounts are USD; the API reports them in **millions**, converted to
  plain dollars on load (× 1,000,000).
- `sponsor` = the API's `company_name`; `region` and `description` are not in
  this dataset (NULL). Exact `approval_date` is available, so `fiscal_year`
  stays NULL.
- A few projects appear twice (disclosed under both the 2006 and 2012
  disclosure policies); only the most recent disclosure is kept, each
  collapse logged as `duplicate_disclosure_collapsed`.
- **Umbrella program caveat:** GTFP/GTSF/GSCF partner-bank records carry the
  program-level envelope (e.g. $7,000M repeated on 55 records), not the
  bank's own facility size. Those amounts are set to NULL and logged as
  `program_envelope_amount` (original value preserved in the log); the
  program's own "World Region" record keeps the envelope.

### EBRD (`scrapers/ebrd.py`)

- Source: official "Projects overview" Excel (every signed operation since
  1991) published on
  <https://www.ebrd.com/work-with-us/project-finance/project-summary-documents.html>.
  The filename embeds the coverage period (e.g. `ebrd-investments-1991-2025.xlsx`),
  so update `DATA_URL` in `scrapers/ebrd.py` when a new edition is posted.
- Amounts are EUR ("at reported rates", EBRD's own restatement), stored in
  `amount_original` with `currency='EUR'`; `amount_usd` converted at the
  ECB annual-average rate for the signing year (see FX section below).
  Pre-1999 signings use the 1999 rate, each logged as `fx_rate_approximated`.
- `approval_date` holds the **original signing date** (EBRD doesn't publish
  board dates in this file) — a known ~1-quarter skew vs. other institutions'
  approval dates.
- `instrument` is derived from the file's Debt/Equity/Guarantee finance
  components (e.g. "Debt + Equity"). `status` is 'Signed' for all rows; the
  file doesn't distinguish active from repaid. The private/state and
  direct/regional flags are preserved in `description`.
- Not in this file (NULL): region, es_category, sponsor, per-project URLs.
  EBRD's per-project PSD pages could enrich these later.

### IDB Invest (`scrapers/idbinvest.py`)

- Source: official XML feed <https://idbinvest.org/en/projects.xml> — a
  complete dump of the project disclosure portal, IIC/IDB Invest operations
  back to 1989. Nothing to update between runs; the feed is always current.
- The feed is bilingual (each project once in English, once in Spanish,
  same project_number); the loader keeps the English record. A few projects
  exist only in Spanish — their Spanish sector/country labels are mapped in
  the CSVs.
- `amount_original` = `iic_financing_amount` (IDB Invest's own account,
  ~87% populated), falling back to `project_idb_fin_amount` (broader IDB
  Group financing) when absent. `sponsor` = the feed's `company`.
- Local-currency deals are real here (MXN, COP, BRL, PEN, ...). MXN and BRL
  convert via ECB annual averages; currencies the ECB doesn't publish
  (COP, PEN, PYG, TTD, DOP, CLP, UYU, ARS, GTQ, JMD) keep their
  amount_original but get `amount_usd = NULL` + a `fx_rate_missing` issue.
- Statuses are IDB Invest's own (Repaid, In implementation, Inactive,
  Proposed, Hold, Approved, Closed). E&S categories include FI-1/2/3 for
  financial intermediaries.

### ADB (`scrapers/adb.py`) — manual download

- Source: ADB's official "Nonsovereign Products" dataset,
  <https://data.adb.org/dataset/adb-nonsovereign-products>. ADB's sites sit
  behind bot protection, so the file must be downloaded **manually in a
  browser** into `data/raw/` with a name starting `adb-nonsov-products`
  (the loader reads the newest matching file). ADB's IATI publication was
  evaluated and rejected: it doesn't reliably distinguish sovereign from
  non-sovereign operations, and guessing fails our integrity rules.
- One row per product approval (a project can have several — logged as
  `duplicate_approval_number`, all rows kept). Covers 2004 onward; the
  loader asserts every row is flagged 'Nonsovereign'.
- Amounts are pre-converted to USD by ADB; for local-currency deals the
  original currency/amount are preserved in `amount_original`/`currency`.
- ADB discloses granular subsector labels (some multi-valued) rather than
  broad sectors; they're stored in `sector` and rolled up via
  sector_mapping.csv. Project names carry a country-code prefix
  ('IND: ...') which dedupe.py strips before matching.
- Not in this file (NULL): region, es_category. `source_url` is constructed
  as https://www.adb.org/projects/&lt;project number&gt;/main.

### AfDB (`scrapers/afdb.py`) — manual download

- Source: MapAfrica projects CSV export, <https://mapafrica.afdb.org/en>
  (bot-protected — download manually in a browser into `data/raw/` with a
  name starting `afdb_mapafrica`; the loader reads the newest match).
- Covers the **entire AfDB Group history (1967→)** and **both sovereign and
  non-sovereign** operations — same treatment as EBRD's state operations:
  the flag plus the funding window (ADF/ADB/Blend) are preserved in
  `description` (e.g. "Sovereign operation; window: ADF").
- Amounts are in **UA (Units of Account) = IMF SDR**, stored as
  `currency='XDR'`; `amount_usd` converts at IMF annual-average
  USD-per-SDR rates (see FX section). The IMF's online archive starts in
  2003, so 1967–2002 approvals use the 2003 rate — logged per record as
  `fx_rate_approximated`.
- `es_category` holds AfDB's categorization: `Category 1` (highest risk) to
  `Category 4`, or FI-A/B/C for financial intermediaries.
- Not in this export (NULL): sponsor, prose description, instrument.
  `source_url` is constructed as
  `https://mapafrica.afdb.org/en/projects/46002-<project id>` (MapAfrica
  shows a bot-check interstitial to automated fetchers; human clicks pass).

### BII (`scrapers/bii.py`)

- Source: BII's own IATI publication (reporting org `GB-COH-03877777`),
  served by the Code for IATI Datastore Classic. Fetching, the truncation
  guard, date/country fallbacks and the d-portal link are shared with the
  FMO loader in `scrapers/iati_common.py`. No API key, no bot
  protection, refreshed continuously — nothing to update by hand.
  The `stream=True` parameter is **required**: without it the API silently
  returns only the first 50 rows, so the loader refuses to load any export
  with implausibly few rows rather than overwriting good data.
- **One row is one commitment transaction**, read from the Datastore's
  `transaction` export: a single dated commitment by BII, valued in USD.
  `amount_original` is that transaction's own value — not a facility size,
  not a portfolio balance, not a lifetime total.
- **This replaced an earlier activity-level load that overstated BII by
  roughly 2x** (all-time USD 77.4bn against USD 35.0bn now; 2016 onward
  USD 57.3bn against USD 25.8bn). Two causes compounded. The activity
  export's `total-Commitment` sums every commitment an activity ever
  received, collapsing separate commitments made years apart into one row
  dated to the activity's start. And BII's published transactions are
  heavily duplicated: only ~1,368 of 2,926 are distinct once matched on the
  fields that identify a commitment. "Africa Gateway" carried **five
  identical USD 325m records**, which is exactly where its USD 1,625m
  figure came from.
- **De-duplication matches on identifying fields, not narrative text**
  (`DEDUP_KEY`: activity, date, value, currency, provider). Whole-row
  comparison is not enough — the two USD 400m "Standard Chartered Risk
  Sharing Facility" records differ only in the character encoding of an
  apostrophe. Each collapsed set is logged as
  `duplicate_transaction_collapsed` with the number of copies. Nothing is
  scaled or apportioned.
- 30 transactions are **negative** (about -USD 0.9bn in total): genuine
  reversals and cancellations, loaded as published so totals net correctly,
  and flagged `negative_amount`.
- `approval_date` is the **commitment's own transaction date**, so BII's
  commitments now fall in the years they were actually made.
- Not in IATI's activity CSV, left NULL rather than inferred: `es_category`,
  `instrument`, and `sponsor` — for sponsor, the Implementing-org field is
  empty on every row and the Funding org is BII/CDC itself, so filling it
  would stamp the funder's name on all 1,258 records. BII's `project_name`
  carries the investee company or fund name instead.
- **Countries:** 334 activities have no `recipient-country`. Where a
  `recipient-region` is disclosed (e.g. "Africa, regional") that label is
  used and `country_mapping.csv` resolves it to the same `Regional — ...`
  values used for other institutions' regional deals; rows with neither
  land on `Undisclosed`. Every such row is logged as `missing_country`
  naming the region that stood in.
- **Sectors — three vocabularies.** BII publishes under IATI sector
  vocabulary 1 (OECD DAC 5-digit, 364 rows), 2 (DAC 3-digit category, 43
  rows) and 99 (851 rows). Vocabulary 99 is BII's **own undocumented
  scheme**; its codes have GICS structure (2/4/6/8 digits) and GICS
  semantics, verified against investees (551050 on Globeleq/Gridworks,
  4010 on NMB Bank/Tyme, 302020 on Africa Improved Foods, 15101030 on
  Indorama Fertilizer). They are stored as `GICS <code> <name>` using the
  name table in `scrapers/bii.py`. **This identification is ours, not
  BII's** — the raw code is always kept in the stored value and every
  mapping is reviewable in `sector_mapping.csv`. Note BII tags fund
  commitments with a bare 2-digit GICS sector (~89% of those rows are
  fund vehicles), so 2-digit codes map to canonical **Investment Funds**
  with the GICS sector carried as the subsector; 4/6/8-digit codes map to
  their industry. Source code `0` is BII's unclassified placeholder and is
  loaded as NULL sector (→ `Unclassified`) with a logged issue.

### FMO (`scrapers/fmo.py`)

- Source: FMO's own project disclosure, the world map at
  <https://www.fmo.nl/world-map> — server-rendered, no API key, paginated
  20 per page. Fetched live each run; nothing to update by hand.
- **This replaced an earlier IATI load that had the wrong population.**
  FMO's IATI publication (`NL-KVK-27078545`) contains **none of FMO's
  own-account investments**: every activity belongs to a fund FMO manages
  for the Dutch state, reported at transaction grain down to
  technical-assistance line items of a few thousand dollars. Under that
  source "FMO" meant MASSIF, Building Prospects and AEF-I only, with a
  median deal of about USD 0.3m and USD 1.9bn over a decade — against a
  committed portfolio of roughly EUR 13bn.
- **Every row records its fund**, in `description`, as `Fund: FMO`,
  `Funds: FMO; MASSIF`, and so on — the same treatment `scrapers/afdb.py`
  gives AfDB's sovereign/window flags. **`Fund: FMO` is FMO's own account**
  (911 investments); the rest are Dutch government programme funds
  (MASSIF 263, Building Prospects 136, Access to Energy Fund 69, Ventures
  Program 29, DFCD 20, Mobilising Finance for Forests 12, Other funding 5).
  To compare FMO against IFC/EBRD/AfDB, filter to the FMO fund; the
  programme rows are kept because they are real disclosures, but they are
  money FMO administers rather than lends.
  **FMO own account, 2016 onward: USD 15.8bn across 825 investments,
  median USD 15.0m.**
- 68 investments appear in the full list under no fund filter; they load as
  `Fund: not stated` and are logged `fund_not_stated` rather than guessed
  into a fund.
- **Pagination is not stable.** One pass over the unfiltered list returns
  1,308 cards but only ~1,288 distinct projects — some appear on two pages,
  others are missed. The loader therefore crawls every fund view *and* the
  unfiltered list and unions them on FMO's project id, recovering ~1,510
  distinct investments.
- Amounts are **FMO's own financing per project** ("Total FMO financing" on
  the card) in the deal's currency — mostly USD and EUR, but also INR, ZAR,
  KES, GEL and others. Currencies `fx_rates.csv` covers are converted;
  the rest keep `amount_original` with `amount_usd = NULL` and a logged
  `fx_rate_missing`.
- `approval_date` is the **disclosure date** shown on the card, i.e. FMO's
  publication date for the investment rather than a board-approval date.
- Not published on the card, left NULL: `instrument`, `sponsor`,
  `es_category`.

### Proparco (`scrapers/proparco.py`)

- Source: "Données de l'aide au développement de Proparco" on AFD's
  open-data portal (opendata.afd.fr), via the Opendatasoft export API as
  semicolon-delimited UTF-8-with-BOM. No API key; refreshes roughly monthly
  and is fetched live each run. Proparco does **not** publish to IATI, so
  this loader does not share `scrapers/iati_common.py`.
- **⚠ COVERAGE IS SYSTEMATICALLY INCOMPLETE — the most important caveat in
  this database.** The dataset contains only projects signed **since
  1 January 2014**, and only those for which **the client granted disclosure
  authorisation**. Deals whose clients declined are absent at any size.
  Proparco totals are therefore a **FLOOR, never a complete picture**, and
  must never be compared like-for-like with IFC / EBRD / AfDB totals without
  stating this. (One 2009 signature appears despite the stated cut-off; it
  is loaded as disclosed and logged as `outside_stated_coverage`.)
- **One row is not in euros.** Activity CUG110502 (Centenary Bank EURIZ
  guarantee, Uganda) carries 20,040,609,850 in the euro column — alone 56%
  of Proparco's total and far beyond the institution's annual commitments.
  The source's own `description_du_projet` says "une garantie EURIZ de 5
  millions d'UGX (20 millions d'euros)", i.e. a EUR 20 **million** guarantee
  recorded as EUR 20 **billion**, evidently left in Ugandan shillings.
  Because the source text is self-contradictory about the true figure, the
  loader does **not** correct it: the amount is stored NULL and logged as
  `implausible_amount` with the original value preserved. The rule is a
  magnitude threshold (`IMPLAUSIBLE_AMOUNT_EUR`, EUR 500m) rather than a
  hardcoded row id — Proparco's largest genuine financing here is EUR 156m.
- `es_category` comes from the `ces` column, confirmed to be Proparco's
  environmental & social categorisation (its values read "IF-B : projet à
  risque E&S modéré" etc.). Only the code is kept: A, B+, B, C, IF-A, IF-B,
  IF-C, Z, or "Pas de classement". Two rows hold free-text commentary
  instead of a category and are stored NULL and logged.
- `status` (`etat_en_cours_ou_cloture`) is present on only 186 of 899 rows
  and is free text ("En cours", "Clôturé", and longer notes); the remainder
  stay NULL. `instrument` keeps the source's French terms (Prêt, Prise de
  participation, Garantie, Subvention, …).
- **French labels.** This is the only source in French. Every distinct
  country spelling (122, including case, accent and multi-country variants
  such as `Pérou`, `TURQUIE`, `Ghana, Sénégal`, `Multi-Pays AFO`) and every
  sector spelling (111, including typos like `Mutli-Secteurs` and mixed
  French/English) has an **explicit** row in `country_mapping.csv` /
  `sector_mapping.csv`. Nothing is fuzzy-matched or case-folded in code.
  AFD's internal multi-country desk codes (AFR/AFS/AFO/AFA/AFN) all resolve
  to `Regional — Africa`; the finer geography behind them is not published.
  Where a sector string combines a cross-cutting theme with a real sector
  ("Climat, Energie"; "Microfinance, genre"), the theme is dropped and the
  sector used.
- Rows funded by FISEA (the Africa fund Proparco manages, 8 rows) are loaded
  under `Proparco`.

### EIB Global (`scrapers/eib.py`)

- Source: the JSON service behind EIB's financed-projects list
  (<https://www.eib.org/en/projects/loans/>), keyless and paginated.
  Refreshed continuously by EIB and fetched live each run.
- **Scope is a deliberate subset, hence the name.** EIB's full book is
  29,696 loan parts, of which **22,863 are inside the EU** — ordinary
  European infrastructure lending, not development finance. The loader
  requests only the eight non-EU regions EIB Global operates in
  (enlargement, Western Balkans, Eastern and Southern Neighbourhood,
  Sub-Saharan Africa, Latin America & Caribbean, Asia-Pacific, OCT),
  excluding EFTA as high-income. Stored as `EIB Global`, not `EIB`, because
  labelling it `EIB` would misrepresent an overwhelmingly European lender.
- **Grain: one row is a LOAN PART (tranche), not a project.** 4,722 loan
  parts span 3,346 project numbers; the Global Green Bond Initiative alone
  has 24 tranches across Africa, Asia, Central Asia and Latin America with
  different amounts. **Summing rows is correct** — they are separate
  signatures — but EIB Global's *deal count* counts tranches and is not
  comparable with other institutions' project counts. Verified that the
  multi-region query does not duplicate rows and that identical tranches
  recur within single-region queries too, so the repetition is EIB's own
  data. Where a project has two or more tranches identical in amount, date
  and country, they cannot be distinguished from a repeated record; those
  are loaded as disclosed and flagged `identical_loan_parts`.
- Amounts are published as formatted euro strings ("€44,000,000") and are
  EUR on every row; converted via `fx.py` on the signature year.
- `approval_date` is the **signature date** (EIB publishes no board-approval
  date here). Dates run from 1969; pre-1970 values arrive as negative epoch
  milliseconds, which `datetime.fromtimestamp` cannot represent on Windows,
  so the loader converts with a timedelta from the epoch instead.
- `region` holds EIB's own mandate region ("Africa, Caribbean, Pacific
  countries + OCT", "Mediterranean countries", …) — the only source in the
  database that populates the raw `region` column meaningfully.
- Not published in this service, left NULL: `sponsor`, `instrument`,
  `status`, `es_category`. 706 rows have no description (logged).

## Currency conversion (`fx_rates.csv` + `fx.py` + `update_fx_rates.py`)

`fx_rates.csv` holds annual-average exchange rates to USD: EUR, GBP, MXN
and BRL from the ECB's official daily reference rates (via the free
frankfurter.app API, from 1999), and **XDR** (IMF Special Drawing Rights =
AfDB's UA) from the IMF's official "Currency units per SDR" monthly archive
(from 2003; annual figure = average of daily rates in Mar/Jun/Sep/Dec;
already-fetched years are cached in the CSV and never re-fetched).
Regenerate with `python update_fx_rates.py` (run once a year, or when
adding a currency). Loaders convert via `fx.to_usd(amount, currency,
year)`; any fallback (years before a currency's rate history, missing
years) is logged to `quality_issues` as `fx_rate_approximated` —
conversions are never silently approximated.

## Sector harmonization (`sector_mapping.csv` + `harmonize.py`)

`sector_mapping.csv` is the editable source of truth translating each
institution's own sector labels into the canonical taxonomy below. Edit the
CSV (Excel is fine), then rerun `python harmonize.py` — no code changes
needed. Labels found in the data but missing from the CSV are reported and
logged as `unmapped_sector`.

Canonical sectors: **Financial Institutions**, **Investment Funds**,
**Infrastructure** (subsectors: Energy & Utilities, Transport & Logistics,
Construction), **Agribusiness & Food**, **Manufacturing**,
**Digital & Telecom**, **Health & Education**, **Extractives**,
**Tourism, Retail & Property**, **Services**, **Public Sector**,
**Other / Multi-sector**, **Undisclosed** (redacted by source),
**Unclassified** (source reported no sector).

## Country harmonization (`country_mapping.csv` + `harmonize.py`)

`country_mapping.csv` translates every institution's country spelling into
one canonical name plus a region (columns: `source_country`,
`canonical_country`, `canonical_region`). Unlike the sector mapping it is
institution-agnostic — the same label always maps the same way. Regional and
multi-country operations map to `Regional — <region>` labels so they stay
visible without polluting country rankings; redacted/unknown labels map to
`Undisclosed`. Same workflow as sectors: edit the CSV, rerun
`python harmonize.py`, and unmapped labels are reported and logged as
`unmapped_country`.

## Table: `project_instruments`

Harmonized instruments, rebuilt by `harmonize.py` from
`instrument_mapping.csv`. A **child table**, not a column on `projects`,
because the mapping is one-to-many: EBRD's "Debt + Equity" is evidence for
senior debt *and* equity, and a single column would silently drop half of
every combined instrument.

| Field | Type | Description |
|---|---|---|
| `project_id` | INTEGER | FK to `projects.id`, `ON DELETE CASCADE`, so a loader wiping its institution's rows clears these too. |
| `canonical_instrument` | TEXT | One of the five canonical values below. |
| `provenance` | TEXT | Where this value came from: `source_label` (the institution's own instrument field), `iati_enrichment` (recovered from another of its publications), or `override` (a hand-reviewed per-deal decision). Filter on it when a chart needs only what institutions published directly. |

Unique on (`project_id`, `canonical_instrument`). To count deals by
instrument, join — do not assume one row per project:

```sql
SELECT pi.canonical_instrument, COUNT(*)
FROM project_instruments pi JOIN projects p ON p.id = pi.project_id
GROUP BY 1;
```

**`projects.instrument` keeps the raw source value and is never modified.**

## Instrument harmonization (`instrument_mapping.csv` + `harmonize.py`)

Seeded from the sibling DFI Mandate Match project's mapping and extended to
cover IDB Invest's 13 and ADB's 6 raw labels. Columns: `institution`,
`raw_instrument`, `canonical_instrument`, `notes` — the notes column records
the judgment behind each row, which matters because several are genuinely
arguable.

Canonical vocabulary (five values, deliberately small):
**Senior debt · Equity · Guarantee · Political risk insurance ·
Technical assistance / grant**

Two rules make this work:

- **One-to-many.** Several CSV rows may share an (institution, raw) key.
  That is how "Debt + Equity", "Debt + Guarantee", "Debt + Equity +
  Guarantee", "Loan & Equity" and "Loan & Guarantee" each produce two or
  three canonical rows.
- **Blank is not the same as absent.** A row present with an **empty**
  `canonical_instrument` means "reviewed, deliberately not mapped" and is
  *not* reported. A raw label with **no row at all** means "never seen" and
  *is* logged as `unmapped_instrument` — one issue per distinct label, not
  per project. Collapsing the two would hide new source labels behind old
  decisions. Seven labels are deliberately blank, including IFC's "Risk
  Management" (hedging products, no equivalent here), IDB Invest's "Not
  Specified", and its "Debt Fund Participation" and "Fund" (LP commitments
  to third-party funds: equity-like in form, debt in underlying exposure,
  and the source does not say which it records — if capturing these matters,
  a `Fund participation` canonical value would be the change to make).

Several mappings are defensible rather than certain, and say so in `notes`:
"Loan"/"Debt"/"Prêt" carry no seniority at source and are read as senior
debt; subscribed bonds and one asset-backed security are read as debt
without a stated rank.

The five canonical values are declared once, as `CANONICAL_INSTRUMENTS` in
`harmonize.py`, and **both** instrument CSVs are checked against it. A value
outside the list stops the run rather than being written, because a typo
would otherwise mint a sixth instrument and split every instrument chart in
two. Capitalisation is forgiven ("Senior Debt" becomes "Senior debt") since
these files are edited by hand in Excel and case drift is not a decision.
Adding a value there is a **two-project decision** — the same vocabulary
drives `../DFI Mandate Match/mandate_rules.csv`.

## Instrument enrichment (`enrich_afdb_instruments.py`)

AfDB's MapAfrica export publishes no instrument, so all 5,949 AfDB rows had
none. AfDB *does* state a finance type in its own IATI publication
(`XM-DAC-46002`) for the same projects. This step recovers it, taking AfDB
from **0% to 78%** instrument coverage — 2,883 standard loans and 1,791
standard grants.

**The join is on an identifier, never a title.** AfDB's project code appears
on both sides:

```
ours    https://mapafrica.afdb.org/en/projects/46002-P-MG-FA0-023
theirs  46002-P-MG-FA0-023        (the iati-identifier)
```

5,502 of our projects match exactly. Title matching was used only as a
feasibility diagnostic and plays no part in the load — this project has
already been bitten by name-similarity bugs.

Three rules keep the distinction honest:

- The value lands in `projects.instrument_enriched`. **`projects.instrument`
  keeps its meaning** — what the source we loaded published — and stays NULL.
- **Enrichment fills silence, it never argues with a disclosure.**
  `harmonize.py` reads `instrument_enriched` only for projects whose loaded
  source published no instrument. A test asserts this directly.
- Canonical values carry `provenance='iati_enrichment'`, so any analysis can
  exclude them.

A project with no matching IATI activity, or whose activity states no finance
type, keeps a NULL instrument and is logged as `afdb_no_iati_match` (1,256
projects). Nothing is inferred from similar projects. Codes are mapped through
`instrument_mapping.csv` like any other label, so IATI code **912 "Purchase of
securities from issuing agencies"** is deliberately blank — "securities" does
not say debt or equity, the same reading as Proparco's "Autres titres".

### The two institutions this was tried on and rejected

Both checked 2026-08-19, both recorded in `harmonize.py` so the question is
not reopened from scratch:

| | Why not |
|---|---|
| **ADB** | Its feed is current and *does* contain our 342 nonsovereign projects — but nothing in it reliably separates them from ADB's sovereign lending. Flow-type 21 covers 95% of our rows and also 45% of the rest; finance-type 421 covers 96% and also 70%. A filter would sweep in ~1,400 activities to catch ~325 real ones. |
| **EIB Global** | States a finance type on all 1,395 activities, but only ~21% of our 3,241 loan-part names appear (different grain — activities, not loan parts), and the feed stops in 2025 while our existing source runs to 2026. |

Separately and importantly: **ADB has not republished its Nonsovereign
Products dataset since the January 2025 edition.** Its latest deal is dated
2024-12-03 and it contributes nothing to 2025 or 2026. That is a gap at the
source, not a stale download.

## Per-deal instrument overrides (`instrument_overrides.csv`)

Some sources publish an instrument field that says nothing while the project
description names the instrument plainly. IDB Invest's 41 "Not Specified"
deals are the case this was built for: the field declines to answer, but the
descriptions are explicit about bond subscriptions, fund investments and
guarantees. The override file records a hand-reviewed decision for **one
named deal**, applied after the label mapping.

Columns: `institution`, `source_url`, `canonical_instrument`, `notes`.

- **Keyed on `source_url`, never on `projects.id`.** Ids are handed out
  afresh every time a loader replaces its institution's rows, so an id-keyed
  override would silently attach to a different deal after the next refresh.
- **One-to-many and blank-vs-absent work exactly as in the label mapping.**
  Several rows may share a URL; a blank canonical means "this deal was
  reviewed and deliberately left unmapped" and stays silent.
- **A blank override clears a value the label mapping produced.** That is the
  point — it is how a deal whose label is wrong for it gets removed.
- **Overriding is never quiet.** If an override contradicts a value the label
  mapping already produced, the run prints it and logs
  `instrument_overridden` with both the old and new values. A hand-written
  file overruling the systematic one should always leave a trace.
- **Overrides that match nothing are reported**, as
  `stale_instrument_override` — the deal was probably renamed or withdrawn at
  source, and a line doing nothing is worth knowing about.

Current contents: all 41 IDB Invest "Not Specified" deals, reviewed by hand
against their published descriptions — 22 senior debt, 3 equity, 3 guarantee,
13 deliberately unmapped. The 13 break down as four bonds the source itself
calls **subordinated** (mapping those to senior debt would record the
opposite of the disclosure, and this vocabulary has no non-senior value),
five LP interests in **private credit funds** (equity-like in form, debt in
exposure — the same reading as "Debt Fund Participation"), three
**receivables and payment facilities** (funded exposure, but nobody borrows
and nothing ranks), and one deal whose page never names the financing.

Two rows rest on the source's own **project title** rather than a
description, and say so in `notes`: Rutas 2/7 and Cardal-Punta del Tigre,
neither of which publishes a usable description. For Cardal the "B" denotes
the syndicated tranche of an A/B structure — which ranks *pari passu*, not
junior — so senior remains the default reading. **Open question recorded
there:** whether B-tranche amounts are IDB Invest's own money or mobilised
third-party capital. That is an amounts question, not an instrument one, and
it would touch EBRD's B-loans too.

### Institutions with no instrument data

Four institutions have none, and `harmonize.py` logs one
`instrument_absent_from_source` issue for each explaining **where we looked**,
so "the source does not publish it" is never confused with "our loader does
not collect it". The issues re-log on every run but only while the
institution still has zero coverage, so they clear themselves if a loader is
later taught to capture the field.

| Institution | Finding (checked 2026-08-17) |
|---|---|
| AfDB | The MapAfrica bulk export has no instrument-like column at all. Absent from the source we read. |
| BII | IATI carries instrument in the finance-type fields; BII leaves `default-finance-type-code` and `transaction_finance-type_code` empty on all 2,926 transactions while populating flow-type and aid-type. bii.co.uk could not be checked (HTTP 403 to automated requests). |
| EIB Global | Neither the loans/list service (country, region and sector tags only) nor the public project page names a finance type. |
| FMO | Checked directly: neither the world-map card nor the project-detail page names an instrument. **Not** a loader gap. Separately, the detail page *does* publish an E&S category that our loader does not capture — that one is a genuine loader gap. |

## E&S category harmonization (`es_category_mapping.csv` + `harmonize.py`)

`projects.es_category` holds each institution's own risk grade, in its own
dialect — IFC's `B - Limited`, DFC's `FI A/Fund A`, AfDB's `Category 1`,
IDB Invest's `FI-2`, Proparco's `B+`, FMO's `B+`. `canonical_es_category`
holds the harmonized level. **`es_category` is never modified.**

Unlike instruments, E&S is **one-to-one** — one grade means exactly one risk
level — so it is a column on `projects`, not a child table. Columns:
`institution`, `raw_es_category`, `canonical_es_category`, `source_url`,
`notes`; the `source_url` cites the policy defining the grade.

Canonical vocabulary (seven values, from the sibling project):
**High · Substantial · Moderate · Low · FI high · FI moderate · FI low**

`Substantial` exists because AFD/Proparco and FMO use a four-level
A/B+/B/C scale; folding `B+` into High or Moderate would misstate ~250 deals.

Blank-vs-absent works exactly as it does for instruments: a **blank**
canonical means "reviewed, deliberately unmapped" and is silent; a grade
with **no row at all** is logged as `unmapped_es_category`, once per
distinct label. **13 labels are deliberately blank**, including AfDB's
`Category 4` and `FI-A/B/C` (a later AfDB scheme the readable 2015 ESAP does
not define), Proparco's `IF-A/B/C` (almost certainly FI levels, but AFD's
framework documents only A/B+/B/C), DFC's `D` (no Category D exists in the
current ESPP; these are OPIC-era records), IFC's bare `FI`, and explicit
non-classifications like `Redacted` and `Pas de classement`.

Two mappings are **read-across, not quotation**, and say so in `notes`:
IDB Invest's A/B/C and FI-1/2/3 use labels identical to IFC's and are read
from IFC's published definitions because idbinvest.org returns HTTP 403 to
automated access; FMO's A/B+/B/C is read from the AFD four-level scale its
own page label mirrors.

### Institutions with no E&S grade

`harmonize.py` logs one `es_category_absent_from_source` issue per
institution, and each says where we looked. Two of the four are **our gap**,
not the institution withholding it:

| Institution | Finding (checked 2026-08-18) |
|---|---|
| EBRD | The investments-overview spreadsheet has no E&S column. EBRD publishes per-project Project Summary Documents this loader does not fetch — **very likely our gap**; the PSD format could not be confirmed here (the URL tried returned 404). |
| ADB | The Nonsovereign Products spreadsheet has no safeguard column. ADB publishes safeguard categories on per-project pages this loader does not fetch and which could not be checked (adb.org returns HTTP 403). **Treat as our gap, unconfirmed.** |
| BII | Loaded from IATI, and the IATI activity standard has no E&S category element at all — there is no field to populate. Absent from the source we read. |
| EIB Global | Neither the loans/list service nor the project page states a category; the page carries an Environmental and Social Data Sheet document and prose instead. Verified directly. |

## Duplicate flagging (`dedupe.py`)

Fuzzy-matches project name + country + year (±1, since institutions'
fiscal years differ) across institutions and writes a shared group ID to
`probable_duplicate_group`. Flags are leads for review, not verdicts:
generic deal names can false-positive, and co-financings disclosed under
entirely different names will be missed.

## Counterparties (`derive_counterparties.py` + `counterparty_rules.csv`)

The database could always answer "which DFIs are active in Kenya". It could
not answer "who have they backed, and who keeps going back to the same
client" — the business-development question — because only IFC, Proparco, ADB
and IDB Invest publish a client field. About 70% of rows had no named
counterparty.

**Every other source was checked for a client field before this was built,
and none has one.** That matters, because the AfDB instrument gap turned out
to be recoverable from a second publication and this one is not:

| Source | What it publishes |
|---|---|
| EBRD | ten columns; the only name is "Operation Name" |
| BII | IATI names a participating org, but it is *CDC Group Plc* — BII itself, as funder. No implementing or extending org. |
| FMO | world-map records carry `title`, nothing client-like |
| DFC | "Project Name", no borrower column |

So counterparties are **derived**, and every row records which kind it is in
`counterparty_provenance`. Coverage: **30% → 66%** (23,085 of 34,637).

### Whose project name is a client name

Decided by reading samples from each source directly (2026-08-19), recorded in
`NAME_IS_COUNTERPARTY`:

| Yes | No |
|---|---|
| FMO — "Banco Macro Sociedad Anonima" | AfDB — "Ethiopia - Agri-MSMES Development for Jobs (AMD4J) Project" |
| BII — "Aavas Financiers Limited" | EIB Global — "ISTANBUL-ANKARA RAILWAY" |
| DFC — "AgDevCo Limited" | |
| EBRD — "Operation Name", usually behind a programme code | |

AfDB and EIB Global therefore get **no counterparty at all**. Deriving one
from those name fields would manufacture roughly 10,000 companies that do not
exist. Logged as `counterparty_name_not_a_client`.

### The rules file

`counterparty_rules.csv` holds four active rule types and one inert one:

- `prefix` — programme codes stripped from the start. "AASF - NOA Agribusiness
  Credit Line" is NOA Agribusiness banking with the Albania Agribusiness
  Support Facility. Matched whether separated by a dash or a space.
- `suffix` — trailing product words ("Credit Line", "Risk Sharing Facility",
  "MRPA"). 4,050 EBRD names are cleaned by these.
- `legal_suffix` — corporate forms. Removed from `counterparty_key` only, and
  kept in the displayed `counterparty`.
- `exclude` — labels that identify nobody.
- **`not_a_prefix`** — read and ignored on purpose. These are leading acronyms
  that look like programme codes but are real clients: **OTP Bank, TBC Bank,
  NLB, Development Bank of Ghana**. An automatic "strip any leading acronym"
  rule would delete them, so the list exists to stop anyone re-deriving that
  rule from the data. This is the single most important safeguard in the file.

Two further guards: a name that is only a country is not a company (checked
against `country_mapping.csv` rather than a second list), and an institution
naming *itself* is not a client relationship — IFC's sponsor field says
"INTERNATIONAL FINANCE CORPORATION" on 20 of its own rows. One DFI naming
*another* is kept, because that is a real disclosure about a co-investor.

### Matching, and why it is a floor

`counterparty_key` is a normalisation, not a similarity score. **There is no
fuzzy matching here on purpose**: an invented relationship is far more
damaging than a missed one, and the value of a cross-institution match is that
two independent sources agreed. Where spellings still differ after
normalisation the link is simply missed. Fund vintages stay separate — "Growth
Fund II" and "Growth Fund III" are different funds and must not merge.

Every count in `report_counterparties.py` is therefore a **floor**: 824
clients banked by two or more DFIs, 183 by three or more, 955 clients with
three or more deals from one institution.

## Mobilisation, and the B-tranche question

### The question

In an A/B structure a DFI is lender of record while institutional investors
fund the B tranche. If a source reports the whole facility and we book it as
the institution's own commitment, every total is inflated by mobilised
third-party capital — the same class of error as the BII overstatement.

### The answer: no institution's amount field includes it

Checked 2026-08-20 against each source directly:

| | Evidence |
|---|---|
| **IDB Invest** | The feed separates them. Cardal-Punta del Tigre B Bond: `iic_financing_amount` USD 14,000,000, `mobilization` USD 55,539,300. We store 14,000,000. |
| **EBRD** | "EBRD Finance" equals Debt + Equity + Guarantee on **100%** of 9,415 rows, so it is an own-account instrument breakdown, not a syndicated total. Its 128 A/B-loan operations total 0.46% of its book. |
| **IFC** | Every amount field is named `ifc_investment_for_*`. Syndications are a separate dataset this pipeline does not read. |

`test_mobilisation.py` keeps a known-value regression on the Cardal deal, so
if a future change ever folds the two together the row becomes 69,539,300 and
the suite fails.

### What the investigation did find

IDB Invest publishes **two** amounts. `iic_financing_amount` is its own
account; `project_idb_fin_amount` is IDB **Group** financing, a broader
concept running **1.8x to 5.3x** the own-account figure where both appear
(Nuevo Cauca Toll Road: own $16m, group $84m; Porto de Sergipe: $38m vs
$200m).

The loader used to fall back to the group figure when the own-account one was
absent, which put **$10.08bn of group-level money into IDB Invest's totals —
20% of its book**. Those 248 records now load with `amount` NULL and a
`group_level_amount` issue preserving the group figure, the same treatment
IFC's umbrella-programme envelopes get. IDB Invest fell from $48.91bn to
$38.83bn as a result.

### The mobilisation dimension

`mobilised_original` / `mobilised_usd` carry third-party capital raised
alongside a deal. **510 IDB Invest projects report $28.37bn of mobilisation
against $14.91bn of its own money on those same deals — $1.90 mobilised per
$1 committed.**

Availability is the limit, and it is worth stating plainly:

- **IDB Invest** publishes mobilisation per project. Loaded.
- **IFC** publishes mobilisation only as programme aggregates (MCPP, a
  cumulative platform total), not per project in any machine-readable
  dataset found.
- **EBRD** publishes Annual Mobilised Investment as an annual aggregate
  (EUR 5.7bn in 2025), not per project.

So a cross-DFI *per-project* mobilisation series is not currently possible.
Adding IFC and EBRD would mean hand-entering annual aggregates from their
reports, on a different grain from the per-project data, and that has not
been done rather than quietly mixing the two.

## Table: `project_themes` — thematic bond labels

One row per (project, theme). Set by `derive_thematic_bonds.py` from
`thematic_bond_rules.csv`.

| Field | Type | Description |
|---|---|---|
| `project_id` | INTEGER | FK to `projects.id`, `ON DELETE CASCADE`. |
| `theme` | TEXT | One of: Green bond, Social bond, Sustainability bond, Sustainability-linked bond, Blue bond, Gender bond. |
| `provenance` | TEXT | `project_name` (the issuer's own label) or `description` (prose that mentions it). The name is stronger evidence; filter to it for a stricter view. |

### Why this is not an instrument

A green bond is a **senior bond that happens to be green**. The theme is a
use-of-proceeds label sitting on top of an instrument. Putting these in the
instrument vocabulary would make one deal both `Senior debt` and `Green bond`
in the same one-to-many table, and break every "what share is equity"
denominator. Hence a separate child table.

It is a child table rather than a column because one bond is routinely two
things: "Banistmo Social Bond with a Gender Focus" is genuinely both, and
6 deals carry more than one label.

### Why deriving this is safe, when deriving an instrument was not

This project refuses to infer an instrument from a description, because
structure has to be disclosed to be known. A theme is different in kind: the
issuer **names** the bond. "Banco Pichincha - Green Bond" is not our reading
of a green bond, it is what the thing is called. We record a label; we do not
deduce a structure.

Three guards keep that honest, and each was added because it caught something:

1. **Only literal phrases match** — no stemming, no similarity scoring.
2. **A phrase only counts on a row that is already a bond**: the text must
   also say bond, note, sukuk or debenture. Without this, "gender focus"
   tags equity deals as gender bonds.
3. **Framework names are stripped before matching** (`exclude_phrase` rows).
   "Climate Bonds Initiative" is a certifier and "Social Bond Principles" is
   an ICMA standard — neither says what *this* deal is. The first of these
   tagged an explicit green **loan** as a green bond. Note that `climate
   bond` was removed as a theme phrase entirely: it had exactly one match in
   the whole database, and it was that false positive.

### What is there

217 deals across all ten institutions, ~$10.9bn:

| Theme | From name | From description | Total |
|---|---|---|---|
| Green bond | 109 | 10 | 119 |
| Sustainability bond | 24 | 11 | 35 |
| Social bond | 19 | 13 | 32 |
| Sustainability-linked bond | 13 | 5 | 18 |
| Blue bond | 11 | 1 | 12 |
| Gender bond | 8 | 0 | 8 |

**A sustainability bond and a sustainability-LINKED bond are different
things** and never collapse: the first is use-of-proceeds, the second is a
performance structure whose coupon steps if KPIs are missed.

Counts are a **floor** — they depend on the issuer using a recognised phrase.

### Deliberately out of scope

Thematic **loans**. The data holds 28 "green loan" and 6
"sustainability-linked loan" mentions. They are a real and fast-growing
market, but they are a different instrument, and whether they belong in this
table is a decision nobody has made yet.
