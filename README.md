# DFI Deal Flow Tracker

Pipeline that loads public project disclosures from development finance
institutions into a unified SQLite database (`data/dfi_tracker.db`).
Sources so far: **DFC** (official Excel release) and **IFC** (WBG Finances
One API). Field definitions: [data_dictionary.md](data_dictionary.md).

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
python harmonize.py         # 2. apply sector_mapping.csv -> canonical sectors
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

## Reviewing the data

- **Excel:** `python export_review.py` writes `data/review_export.xlsx`
  with sheets: `all_projects`, `duplicates` (grouped for side-by-side
  comparison), `quality_issues`, `sector_rollup`.
- **Browsing the database directly:** install the free
  [DB Browser for SQLite](https://sqlitebrowser.org/) and open
  `data/dfi_tracker.db` (read-only recommended: File → Open Database Read Only).
- **Terminal:** `python verify.py` for the quick counts.

## Editing the sector or country taxonomies

Open `sector_mapping.csv` or `country_mapping.csv` (Excel is fine — keep
them saved as CSV), change any canonical values, save, then run
`python harmonize.py`. It reports any labels in the data that the CSVs
don't cover. Always analyze by `canonical_country` / `canonical_region` /
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
  `python -m scrapers.afdb` (it picks the newest matching file).
- **FX rates:** run `python update_fx_rates.py` once a year so the current
  year's annual-average rates stay fresh (ECB currencies + IMF SDR).
- Raw downloads are archived date-stamped in `data/raw/` — never delete
  these; they're the audit trail.
- Quality rules: bad rows are loaded with NULLs and logged to the
  `quality_issues` table, never dropped or guessed. See data_dictionary.md
  for what each `issue_type` means.
