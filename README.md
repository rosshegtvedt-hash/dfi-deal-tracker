# DFI Deal Flow Tracker

Pipeline that loads public project disclosures from development finance
institutions into a unified SQLite database (`data/dfi_tracker.db`).
Ten institutions: **DFC, IFC, EBRD, IDB Invest, ADB, AfDB, BII, FMO,
Proparco** and **EIB Global**. Field definitions:
[data_dictionary.md](data_dictionary.md).

## The routine

Open a terminal in this folder (in File Explorer: right-click an empty spot
→ "Open in Terminal"), then run, in this order:

```
python -m scrapers.dfc      # 1a. refresh DFC   (quarterly release — see note below)
python -m scrapers.ifc      # 1b. refresh IFC   (source updates daily)
python -m scrapers.ebrd     # 1c. refresh EBRD  (annual release — see note below)
python -m scrapers.idbinvest # 1d. refresh IDB Invest (feed always current)
python -m scrapers.adb      # 1e. refresh ADB (needs manual download — see below)
python -m scrapers.afdb     # 1f. refresh AfDB (needs manual download — see below)
python -m scrapers.bii      # 1g. refresh BII (IATI feed always current)
python -m scrapers.fmo      # 1h. refresh FMO (world map + detail pages, ~25 min)
python -m scrapers.proparco # 1i. refresh Proparco (AFD open data, ~monthly)
python -m scrapers.eib      # 1j. refresh EIB Global (live service)
python enrich_afdb_instruments.py  # 1k. recover AfDB's instrument from its own IATI feed
python derive_counterparties.py    # 1l. work out who each deal was WITH
python harmonize.py         # 2. apply the four mapping CSVs (sector, country, instrument, E&S) + per-deal instrument overrides
python dedupe.py            # 3. re-flag probable co-financed duplicates
python verify.py            # 4. sanity-check summary in the terminal
python export_review.py     # 5. (optional) full dump to data/review_export.xlsx
```

Each loader **replaces** its institution's rows, so rerunning is always safe
— no duplicates. Steps 2 and 3 must rerun after any load (loads reset their
institution's canonical sectors and the duplicate groups).

## Dashboards

There are two; they read the same database and show the same numbers.

**Public dashboard (Next.js, in `/web`)** — the one to deploy on Vercel:

```
python export_web_data.py        # refresh web/public/data.json from the DB
cd web
npm run dev                      # local preview at http://localhost:3000
```

It is a static site: the pipeline exports `web/public/data.json` and the
page filters it in the browser — no server or database hosting needed.
**Refreshing the live site** after a data update: run the pipeline, run
`python export_web_data.py`, then commit and push — Vercel redeploys
automatically.

**Local dashboard (Streamlit, in `/dashboard`)** — for private desk use:

```
python -m streamlit run dashboard/app.py
```

(Use `python -m streamlit`, not plain `streamlit` — the short command isn't
on this machine's PATH.) Opens at <http://localhost:8501>. Keep the terminal
window open while using it; stop with Ctrl+C. Sidebar filters cover
institution, region, country, sector, instrument, and year range — all on
the harmonized (canonical) fields. The "Exclude probable duplicates" toggle
keeps one record per flagged co-financing group (the largest single
commitment) so a deal financed by three institutions counts once. The deal
table is searchable and links every row to its official disclosure page.
The dashboard reads the database directly, so it always shows whatever the
last pipeline run loaded.

## Branded chart exports

```
python export_charts.py
```

Writes five LinkedIn-sized (1200x1200) PNGs into `charts/`: commitments over
time, top countries, sector mix, average ticket size, and co-financing pairs.
Every chart is drawn inside one shared frame that stamps the RCFH Advisory
wordmark and the **source attribution footer** — the footer belongs to the
frame, not to each chart, so a published chart cannot lose it.

Two things baked in deliberately:

- Charts cover **2015–2024**. 2025 is excluded because DFC and ADB load from
  dated snapshot files and contribute nothing to it, and FMO and BII lag —
  including it would show a ~25% "collapse" in development finance that is an
  artefact of publication timing, not the market.
- The palette carries **six** categorical hues (the most that pass the
  colour-vision and normal-vision separation checks together). The six
  largest institutions get a fixed hue; the rest share a neutral "Other".
  The dashboards use the same assignment, so exports and site agree.

## Who each deal was with (counterparties)

```
python derive_counterparties.py     # fill in the client on every deal it can
python report_counterparties.py     # who shares clients with whom
```

"Which DFIs are active in Kenya" was always answerable. "Who have they backed,
which of them keep going back to the same client, and who has raised money
from several" was not — only IFC, Proparco, ADB and IDB Invest publish a
client field, leaving ~70% of the database with no named counterparty.

Every other source was checked for a client field first, and **none has one**
— unlike AfDB's instrument, which really was published elsewhere. So this is
**derived**, and every row says so in `counterparty_provenance`:

- `disclosed` — the source published a sponsor; used verbatim.
- `derived_from_project_name` — cleaned from the project name, using the rules
  in `counterparty_rules.csv`.

Coverage went from **30% to 66%** (23,085 of 34,637 deals).

Two things this deliberately will not do:

- **AfDB and EIB Global get no counterparty at all.** Their name fields hold
  project and asset names — "Ethiopia - Agri-MSMES Development for Jobs
  Project", "ISTANBUL-ANKARA RAILWAY" — so deriving clients from them would
  invent about 10,000 companies that don't exist.
- **No fuzzy matching.** `counterparty_key` is a normalisation, not a
  similarity score. Two spellings that still differ after normalising stay
  apart, so a real relationship is missed rather than a false one invented.
  Every count in the report is therefore a floor.

`counterparty_rules.csv` is the editable part. `prefix` rows strip programme
codes ("AASF - NOA Agribusiness Credit Line" is NOA Agribusiness, banking with
the Albania Agribusiness Support Facility), `suffix` rows strip product words,
`legal_suffix` rows are removed from the matching key but kept in the name,
and `exclude` rows are labels that identify nobody.

There is also a `not_a_prefix` section, which the code reads and ignores on
purpose. It records leading acronyms that **look** like programme codes but are
real clients — OTP Bank, TBC Bank, NLB, Development Bank of Ghana. An
automatic "strip any leading acronym" rule would have deleted them, so the
list exists to stop anyone re-deriving that rule from the data.

What it finds today: **824 clients banked by two or more DFIs**, 183 by three
or more, and 955 clients with three or more deals from a single institution.
Vietnam Prosperity Bank has raised from six.

## Reviewing the data

- **Excel:** `python export_review.py` writes `data/review_export.xlsx`
  with sheets: `all_projects`, `duplicates` (grouped for side-by-side
  comparison), `quality_issues`, `sector_rollup`.
- **Browsing the database directly:** install the free
  [DB Browser for SQLite](https://sqlitebrowser.org/) and open
  `data/dfi_tracker.db` (read-only recommended: File → Open Database Read Only).
- **Terminal:** `python verify.py` for the quick counts.

## Editing the sector, country, instrument or E&S taxonomies

Open `sector_mapping.csv`, `country_mapping.csv`,
`instrument_mapping.csv` or `es_category_mapping.csv` (Excel is fine — keep them saved as CSV), change
any canonical values, save, then run `python harmonize.py`. It reports any
labels in the data that the CSVs don't cover.

`instrument_mapping.csv` works slightly differently from the other two, in
two ways worth knowing:

- **One raw label can map to several canonical instruments.** EBRD's
  "Debt + Equity" has two rows in the CSV, and produces two rows in the
  `project_instruments` table. Add or remove a row to change that.
- **Leaving `canonical_instrument` blank is a decision, not an omission.**
  A blank means "I looked at this and chose not to map it", and is silent.
  Deleting the row entirely means "never seen", and gets reported. Use blank
  when a label genuinely doesn't fit the five canonical values rather than
  forcing a bad fit.

Instruments live in their own table because of the one-to-many mapping;
`projects.instrument` still holds each source's raw wording, untouched.
Three institutions (BII, EIB Global, FMO) publish no instrument at all —
`harmonize.py` records why for each. See data_dictionary.md.

## Recovering an instrument from a second publication

```
python enrich_afdb_instruments.py
```

AfDB's MapAfrica export has no instrument column, but AfDB publishes the same
projects to IATI, where the finance type **is** stated. This step joins the
two on AfDB's own project code — which appears in our `source_url` and in
their `iati-identifier`, so it is an exact identifier match, never a title
match — and fills `projects.instrument_enriched`. That took AfDB from **0% to
78%** instrument coverage, about 4,700 deals.

Three rules keep this honest:

- It writes only `instrument_enriched`. **`projects.instrument` still means
  "what the source we loaded published"**, and for AfDB that is still nothing.
- **Enrichment fills silence and never argues with a disclosure.**
  `harmonize.py` reads it only for projects whose loaded source published no
  instrument.
- Every canonical value records where it came from, in
  `project_instruments.provenance`: `source_label`, `iati_enrichment`, or
  `override`. So any chart can separate an institution's own instrument field
  from one recovered elsewhere.

The same check was run on ADB and EIB Global and **both were rejected** — ADB
because nothing in its feed reliably separates its nonsovereign book from its
sovereign lending, EIB because only ~21% of our loan parts appear in it and
its feed stops in 2025. Both findings are recorded in `harmonize.py` so the
question doesn't get reopened from scratch.

The five canonical instrument values are declared once in `harmonize.py`
(`CANONICAL_INSTRUMENTS`), and both instrument CSVs are checked against it —
a misspelled value stops the run instead of quietly becoming a sixth
instrument. Capitalisation is forgiven; unknown values are not.

## Overriding the instrument on a single deal

Some sources publish an instrument field that says nothing while the project
description says plenty. IDB Invest has 41 deals labelled "Not Specified"
whose descriptions plainly describe bond subscriptions, fund investments and
guarantees. `instrument_overrides.csv` records a hand-reviewed decision for
one named deal, applied on top of the label mapping:

```
institution,source_url,canonical_instrument,notes
```

It is keyed on `source_url`, **not** on the project's row id — ids are
reassigned every time a loader reloads its institution, so an id would drift
onto the wrong deal. Blank means the same thing here as everywhere else:
reviewed, deliberately unmapped. Two things are deliberately noisy — an
override that contradicts what the label mapping concluded is printed and
logged as `instrument_overridden`, and an override whose URL matches no
project is reported as `stale_instrument_override` rather than sitting in the
file doing nothing.

## Tests

```
python test_instruments.py
python test_es_categories.py
python test_instrument_overrides.py
python test_instrument_enrichment.py
python test_counterparties.py
```

Five suites, one per mechanism — instruments are one-to-many into a
child table, E&S is one-to-one into a column, overrides are keyed per deal and
replace rather than add, and enrichment may only fill silence — so a failure
names the right thing. They prove: combined instruments produce a row each,
deliberately-blank mappings stay silent, an unseen label is reported exactly
once however many projects carry it, an override survives ids being
reassigned, **enrichment never overwrites what a source published**, a
"publishes no instrument" finding clears once the gap closes, a value outside
the vocabulary stops the run, a rerun changes nothing, and editing a CSV
actually takes effect. Each exits non-zero on failure, so they can gate a
commit, and each builds a throwaway database in memory and never touches the
real one.

Always analyze by `canonical_country` / `canonical_region` /
`canonical_sector` — the raw `country` and `region` columns keep each
institution's own spelling and are not comparable across institutions.

## Maintenance notes

- **DFC:** new data file each fiscal year/quarter, ~45 days after period
  end. When posted on
  <https://www.dfc.gov/our-impact/transaction-data>, update `DATA_URL` at
  the top of `scrapers/dfc.py` and rerun the routine.
- **IFC:** nothing to update — the API always serves current data.
- **EBRD:** new "Projects overview" Excel posted annually; the filename
  embeds the coverage years, so update `DATA_URL` at the top of
  `scrapers/ebrd.py` and rerun the routine.
- **ADB:** bot protection blocks automated download. In your browser, open
  <https://data.adb.org/dataset/adb-nonsovereign-products>, download the
  XLSX into `data\raw\` keeping a filename that starts with
  `adb-nonsov-products`, then run `python -m scrapers.adb` (it picks the
  newest matching file). ADB refreshes this dataset roughly annually.
- **AfDB:** bot protection blocks automated download. In your browser, open
  <https://mapafrica.afdb.org/en>, export the projects CSV, save it into
  `data\raw\` with a filename starting `afdb_mapafrica`, then run
  `python -m scrapers.afdb` (it picks the newest matching file). Follow it
  with `python enrich_afdb_instruments.py`, which needs no download — it
  fetches AfDB's IATI feed live.
- **ADB caveat (important):** ADB has **not republished** this dataset since
  the January 2025 edition, so its latest deal is dated 2024-12-03 and it
  contributes nothing to 2025 or 2026. That is a gap at the source, not a
  stale download — checked 2026-08-19. ADB's IATI feed *is* current, but it
  does not distinguish its nonsovereign book from its sovereign lending, so it
  cannot be used to fill the gap without guessing. Say so before comparing ADB
  with the others on recent years.
- **BII:** nothing to update — its IATI publication is refreshed
  continuously and the loader fetches it live each run.
- **FMO:** nothing to update — crawled live from FMO's own world map. Note
  the crawl makes ~150 page requests with a polite delay, so it takes a
  couple of minutes.
- **FMO caveat:** the loader records the **fund** on every row.
  `Fund: FMO` is FMO's own account; the rest (MASSIF, Building Prospects,
  Access to Energy Fund, …) are Dutch government funds FMO merely
  administers. Filter to the FMO fund before comparing FMO with
  IFC/EBRD/AfDB. See data_dictionary.md.
- **BII caveat:** BII is loaded from IATI's **transaction** export (one row
  per dated commitment), not the activity export. The activity export's
  lifetime `total-Commitment` overstated BII by roughly 2x, partly because
  BII republishes many transactions verbatim — "Africa Gateway" appeared
  five times at USD 325m, producing a USD 1,625m phantom. Repeats are
  collapsed on identifying fields and logged. See data_dictionary.md.
- **Proparco:** nothing to update — AFD's open-data portal refreshes roughly
  monthly and the loader fetches it live each run.
- **EIB Global:** nothing to update — fetched live from EIB's own service.
  Note it loads only EIB's **non-EU** operations (its EU lending is 5x
  larger and is deliberately excluded), and its rows are **loan tranches**
  rather than projects. See data_dictionary.md.
- **Proparco caveat (important):** the source covers only projects signed
  since 1 January 2014 **and** only those whose clients authorised
  disclosure. Proparco totals are a **floor, never a complete picture**, and
  must not be compared like-for-like with IFC/EBRD/AfDB totals without
  saying so. See data_dictionary.md.
- **FX rates:** run `python update_fx_rates.py` once a year so the current
  year's annual-average rates stay fresh (ECB currencies + IMF SDR).
- Raw downloads are archived date-stamped in `data/raw/` — never delete
  these; they're the audit trail.
- Quality rules: bad rows are loaded with NULLs and logged to the
  `quality_issues` table, never dropped or guessed. See data_dictionary.md
  for what each `issue_type` means.
