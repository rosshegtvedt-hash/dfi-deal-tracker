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

## Currency conversion (`fx_rates.csv` + `fx.py` + `update_fx_rates.py`)

`fx_rates.csv` holds annual-average exchange rates to USD (currently EUR and
GBP), computed from the ECB's official daily reference rates via the free
frankfurter.app API. Regenerate with `python update_fx_rates.py` (run once a
year, or when adding a currency). Loaders convert via `fx.to_usd(amount,
currency, year)`; any fallback (pre-1999 years, missing years) is logged to
`quality_issues` as `fx_rate_approximated` — conversions are never silently
approximated.

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
