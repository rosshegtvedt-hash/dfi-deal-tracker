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
| `instrument` | TEXT | Financial product: loan, equity, guarantee, insurance, investment fund, etc. Source's own terminology. |
| `amount_original` | REAL | Committed amount in the source's reporting currency, in **plain units** (dollars, not millions). |
| `currency` | TEXT | ISO 4217 code of `amount_original` (e.g. `USD`, `EUR`). |
| `amount_usd` | REAL | Committed amount converted to **plain US dollars**. For USD sources this equals `amount_original`. |
| `approval_date` | TEXT | Date of board approval / commitment, ISO `YYYY-MM-DD`. NULL if the source only discloses a fiscal year or nothing — never guessed. |
| `fiscal_year` | INTEGER | The institution's fiscal year of commitment, for sources (like DFC) that disclose only a year and no exact date. Note fiscal years differ by institution (DFC: Oct 1–Sep 30). |
| `status` | TEXT | Project status as reported (e.g. Active). NULL if the source doesn't report one. |
| `es_category` | TEXT | Environmental & social risk category (e.g. A/B/C) where disclosed. |
| `sponsor` | TEXT | Project sponsor / borrower / investee where disclosed. |
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
- **Amounts are lifetime commitment totals** (`total-Commitment` — the sum
  of every commitment transaction ever reported for an activity), not
  single approval amounts. BII figures are therefore not exactly comparable
  like-for-like with the other institutions' per-approval amounts.
  All rows are USD (currency read from `default-currency`, not assumed).
- `approval_date` holds the activity's **start date** (`start-actual`,
  falling back to `start-planned`) — IATI publishes no board-approval date.
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

- Source: FMO's IATI publication (reporting org `NL-KVK-27078545`) via the
  Code for IATI Datastore Classic — same mechanism, guard and shared
  plumbing as BII (`scrapers/iati_common.py`). Nothing to update by hand.
- **⚠ This is not FMO's own investment portfolio.** Every activity names
  the *Ministry of Foreign Affairs of the Netherlands* as funder, and the
  titles group into the Dutch government funds FMO manages: MASSIF (826),
  Building Prospects (295), AEF-I (139), Mobilizing Finance for Forests
  (20), LUF (13), DFCD (1). FMO's own ~EUR 12bn balance-sheet book is
  published separately on fmo.nl and is **not** in this feed. Many rows are
  technical-assistance/consultancy contracts (implementing orgs include
  Accion, MicroFinanza Rating, Value for Women, Niras, Frankfurt School),
  and the leading recipient countries are fund domiciles — United States
  (142), Netherlands (141), Mauritius (85), UK (55), Luxembourg (38).
  Read this institution as "Dutch government funds managed by FMO"; its
  deal counts and geography are not like-for-like with the others.
- **Currency — `default-currency` is wrong here and is deliberately not
  used.** It reads EUR on all 1,294 rows, but the per-transaction
  `currency` column reports 39 different currencies (EUR 653, USD 507, then
  INR, KES, XOF, BDT, VND, KHR, UZS, TZS, UGX, …). Taking the EUR label at
  face value would read 38.2bn Vietnamese dong as EUR 38.2bn: the raw
  amount column sums to EUR 155.94bn against an actual programme size of
  about USD 3.9bn. The loader reads the per-transaction `currency` and
  converts with `fx.py`. The Datastore's `total-Commitment-USD` column is
  not a usable alternative — it is a pass-through equal to the raw amount
  for USD rows and 0 for every non-USD row.
  129 rows are in currencies `fx_rates.csv` has no rate for; they keep
  `amount_original` and get `amount_usd = NULL` plus `fx_rate_missing`.
- **Titles:** 1,290 of 1,294 are internal fund identifiers
  ("MASSIF-P00015696-001") rather than project names. Loaded verbatim and
  flagged `title_is_internal_identifier`; nothing is prettified. The only
  four real names are the fund-level parent activities.
- **Descriptions:** the export's `description` column is the literal string
  `"1"` on every row (a broken field) and is ignored. Text comes from
  `description_general`; its 438 "Description not provided" placeholders are
  stored as NULL and logged rather than saved as content.
- `sponsor` = `participating-org (Implementing)`, populated on all rows —
  for TA contracts this is the adviser, for investments the counterparty.
- Not published, left NULL: `es_category`, `instrument`.

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

## Duplicate flagging (`dedupe.py`)

Fuzzy-matches project name + country + year (±1, since institutions'
fiscal years differ) across institutions and writes a shared group ID to
`probable_duplicate_group`. Flags are leads for review, not verdicts:
generic deal names can false-positive, and co-financings disclosed under
entirely different names will be missed.
