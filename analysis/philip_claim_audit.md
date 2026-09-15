# Claim audit — DFI sector allocation and the storage/handling layer

**Prepared:** 2026-09-08
**Source:** `data/dfi_tracker.db`, read-only. No schema change, no mutation, no scraper run.
**Purpose:** test whether a specific public claim survives contact with the data before it is made to a practitioner who will check it against operating memory.

**Headline: the claim as written is NOT SUPPORTABLE.** Not because it is wrong — because the taxonomy cannot see the thing it is about. Detail in Phase 2. Phase 3 is therefore not run. Six alternative claims that do survive are in Phase 4.

---

## Phase 1 — Inventory (actual state, not intended state)

### Panel

| Institution | Rows | Year range | Rows w/ amount | w/ date | w/ country | w/ sector | Disclosed USD (bn) |
|---|---:|---|---:|---:|---:|---:|---:|
| EBRD | 9,415 | 1991–2025 | 9,415 | 9,414 | 9,415 | 9,415 | 261.63 |
| IFC | 7,035 | 1993–2026 | 6,685 | 6,777 | 7,035 | 7,035 | 339.69 |
| AfDB | 5,949 | 1967–2026 | 5,941 | 5,949 | 5,949 | 5,949 | 199.65 |
| EIB Global | 4,722 | 1965–2026 | 4,722 | 4,722 | 4,722 | 4,722 | 215.47 |
| IDB Invest | 2,087 | 1989–2026 | 1,569 | 1,964 | 2,087 | 2,086 | 38.83 |
| FMO | 1,511 | 2000–2026 | 1,464 | 1,511 | 1,511 | 1,511 | 19.90 |
| BII | 1,368 | 2003–2025 | 1,335 | 1,368 | 1,368 | 1,368 | 35.02 |
| DFC | 1,313 | 1960–2024 | 1,313 | 0 | 1,313 | 1,313 | 58.38 |
| Proparco | 899 | 2009–2026 | 875 | 895 | 899 | 899 | 17.54 |
| ADB | 342 | 2004–2024 | 342 | 342 | 342 | 342 | 21.10 |
| **Total** | **34,641** | 1960–2026 | 33,661 | — | — | — | **1,207.2** |

**Total disclosed commitments captured: $1,207.2bn.** This is a floor on disclosed public data, not a measure of DFI activity.

Field completeness across all 34,641 rows:

- usable amount (`amount_usd > 0`): 33,661 (97.2%)
- usable year: 34,255 (98.9%)
- usable country: 34,585 (99.8%)
- usable sector: 34,425 (99.4%)
- **all four simultaneously usable: 33,516 (96.8%)**

**Assumption flagged — the year field.** `fiscal_year` is null for nine of ten institutions. Every year figure in this memo is derived as `COALESCE(CAST(substr(approval_date,1,4) AS INTEGER), fiscal_year)`. DFC is the mirror image: it has zero `approval_date` values and populated `fiscal_year` only, so **DFC deals cannot be date-sequenced within a year** and DFC is excluded from any ordering test. DFC's 1960 floor is real — the portfolio inherits OPIC-era records.

**Assumption flagged — FX.** `amount_usd` is converted at the **annual-average rate of the commitment year** (`fx.py`, `fx_rates.csv`, ECB reference rates). Amounts are therefore nominal USD of the deal year. 41% of total value originates in EUR, 42% in USD, 17% in XDR (all AfDB). Within-year shares are unaffected. Cross-year *levels* carry an undeflated-nominal caveat.

**Discrepancy noted.** Project documentation records $1.263T. The database computes $1,207.2bn. The gap is ~4.4% and is not explained here. Do not cite the $1.263T figure without reconciling it.

### Raw sector values

335 distinct raw `sector` strings; 351 distinct `(institution, sector)` pairs. `subsector` is **null in every row** at source — the `canonical_subsector` column is entirely derived.

Distinct raw values per institution — and this asymmetry is the whole story:

| Institution | Distinct raw sector strings | Vocabulary type |
|---|---:|---|
| Proparco | 111 | free text, French, uncontrolled (`Infrastructures (transport/Port)`, `Immobilier?`) |
| BII | 95 | DAC CRS codes + GICS codes, mixed |
| ADB | 52 | ADB sector/subsector, semicolon-concatenated |
| DFC | 20 | NAICS 2-digit |
| IDB Invest | 16 | in-house, bilingual EN/ES |
| EBRD | 13 | in-house, 13 buckets for 9,415 deals |
| EIB Global | 13 | in-house |
| AfDB | 11 | in-house, 11 buckets for 5,949 deals |
| IFC | 10 | in-house, 10 buckets for 7,035 deals |
| FMO | 4 | in-house, 4 buckets for 1,511 deals |

The full per-institution list is reproducible with:

```sql
SELECT institution, sector, COUNT(*), ROUND(SUM(COALESCE(amount_usd,0))/1e6,1),
       canonical_sector, canonical_subsector
FROM projects GROUP BY institution, sector ORDER BY institution, 3 DESC;
```

### Sector mapping table

The mapping is a **CSV, not a database table**: `sector_mapping.csv`, columns `institution, source_sector, canonical_sector, canonical_subsector`.

- 349 rows, 349 distinct `(institution, source_sector)` keys
- **349 of 351** DB pairs mapped
- **Unmapped: 7 pairs.** Six are null-sector pairs (AfDB, BII, DFC, IDB Invest, IFC, Proparco). One is a genuine miss: `IDB Invest / Economía Digital`, 1 row, $2.9m — a mojibake variant of an already-mapped string.
- Rows landing in a non-substantive canonical bucket: 215 (`Unclassified` 186, `Undisclosed` 29) — 0.6% of rows, $14.2bn.

Mapping coverage is **not** the constraint. The taxonomy's resolution is.

### Co-financing deduplication

`dedupe.py` has run. State:

- 2,068 rows carry a `probable_duplicate_group`
- 736 distinct groups
- **all 736 are cross-institution by construction** — the matcher only compares records from different institutions
- Group sizes: 486 pairs, 133 triples, 58 quads, tail out to one 42-member group

**Critical caveat, and it disqualifies Phase 3's second pass.** The matcher blocks on same country and ±1 year, then fuzzy-matches *normalised project names* at ≥0.80 similarity (≥0.90 where a year is missing), and chains transitively. It is therefore a **repeat-borrower detector, not a co-financing detector.** Inspection of the head of the list:

- `DUP-0001` groups a DFC "Republic of Serbia" record with an EBRD "Republic of Serbia: Road Recovery Project" — different transactions, matched on sovereign name.
- `DUP-0003` groups DFC's Kenya Commercial Bank with **IFC's Kenya Commercial Bank II (2011) and III (2013)** — two distinct facilities to one borrower, chained into one "duplicate" group.

Groups are leads about *who banks the same client*, which is genuinely useful (see Claim 4). They are **not** a basis for collapsing rows to unique underlying projects.

---

## Phase 2 — Feasibility verdict

### The claim under test

> Capital concentrates in power generation and corridor transport, while the storage, warehousing, cold chain, and materials-handling layer that lets a country capture margin receives materially less.

### VERDICT: **NOT SUPPORTABLE**

The taxonomy cannot separate the storage and handling layer from corridor transport, and it cannot separate power generation from transmission either. Both halves of the comparison fail, for the same reason: the reporting institutions publish a single undifferentiated word.

### What it collapses into

**1. The storage layer has no home of its own.** Across all ten institutions and 335 raw sector strings, exactly **two** strings name storage:

| Raw string | Institution | Rows | USD |
|---|---|---:|---:|
| `21061 Storage` (DAC CRS) | BII | 1 | $19.9m |
| `Transportation and Warehousing` (NAICS 48-49) | DFC | 23 | $1,321.2m |

That is the entire universe. The BII code is a single deal. The DFC code is the US NAICS supersector that **merges transport and warehousing by design** — it cannot be split. Everything else disappears into `Transport & Logistics`, `Agribusiness & Food`, `Manufacturing`, or a financial-institution credit line.

**2. Corridor transport is equally invisible.** `canonical_subsector = 'Transport & Logistics'` holds 1,987 rows and $120.08bn. Of that value, **96.6% sits behind the bare one-word string `Transport`** — AfDB $40.0bn, EIB Global $44.7bn, EBRD $28.2bn, IDB Invest $3.2bn. Including DFC's `Transportation and Warehousing`, **97.7% of the transport bucket is behind a string that names no mode.** Only ADB (5 strings), BII (7), and Proparco (8) distinguish road from rail from port from air, and together they are 3.5% of the bucket's value. There is no road/rail/port series to compare a storage series against.

**3. Power generation is not separable from transmission.** `canonical_subsector = 'Energy & Utilities'` holds 3,073 rows and $141.4bn, mixing generation, T&D, efficiency, and utility services. Rows where the raw string identifies generation:

| Institution | Rows in E&U | USD (m) | Generation-identifiable |
|---|---:|---:|---:|
| ADB | 144 | 9,427 | 115 (80%) |
| BII | 220 | 5,479 | 201 (91%) |
| Proparco | 96 | 2,210 | 35 (36%) |
| EIB Global | 767 | 46,788 | **0** |
| EBRD | 620 | 30,754 | **0** |
| AfDB | 555 | 27,744 | **0** |
| DFC | 101 | 7,991 | **0** |
| FMO | 359 | 5,779 | **0** |
| IDB Invest | 211 | 5,249 | **0** |

**87% of energy value is behind a string that does not say whether it is a power plant or a wire.**

### The text workaround, and why it also fails

The obvious next move is to classify from `project_name` and `description`. It does not work, and the reason it does not work is instructive.

A best-effort classifier — 22 positive terms (`warehous`, `cold chain`, `cold stor`, `silo`, `logistics park`, `distribution cent`, `fulfilment cent`, `container terminal`, `dry port`, `inland container`, `bonded warehouse`, `freight terminal`, `intermodal`, `multimodal`, `materials handling`, `bulk terminal`, `stockpil`, …) minus 15 confounder terms (`batter`, `energy storage`, `bess`, `pumped`, `gas storage`, `regasif`, `storage dam`, `reservoir`, `carbon storage`, `data stor`, …) — returns **205 rows and $4.78bn**.

The confounder exclusion is not optional. A naive search on `storage` alone returns 172 rows and $6.89bn, of which **53 rows and $2.47bn are battery storage**, plus underground gas storage (Bulgartransgaz, MOL, Bozoi, Plinacro, Silivri), a water storage dam, and an LNG floating regasification unit. In a DFI portfolio, "storage" overwhelmingly means electrons or gas, not goods.

But the classifier's real problem is that **its yield tracks how verbose an institution's disclosure is, not how much it lends to storage:**

| Institution | Rows | Mean description length (chars) | Hits | Hits per 1,000 rows |
|---|---:|---:|---:|---:|
| IDB Invest | 2,087 | 661 | 85 | **40.7** |
| ADB | 342 | 574 | 4 | 11.7 |
| DFC | 1,313 | 94 | 15 | 11.4 |
| BII | 1,368 | 287 | 10 | 7.3 |
| EIB Global | 4,722 | 153 | 25 | 5.3 |
| EBRD | 9,415 | 47 | 37 | 3.9 |
| IFC | 7,035 | **0** | 18 | 2.6 |
| AfDB | 5,949 | 30 | 9 | 1.5 |
| Proparco | 899 | 255 | 1 | 1.1 |
| FMO | 1,511 | 13 | 1 | 0.7 |

**Spearman ρ = 0.72 between mean description length and hit rate, p = 0.019.**

**IFC has zero descriptions in all 7,035 rows.** It is the largest institution in the panel by value ($339.7bn) and it is structurally invisible to any text classifier — its 18 hits come from project names alone. AfDB's descriptions average 30 characters and FMO's average 13; both are boilerplate strings, not narrative. So a text-derived storage series would report that IDB Invest does 28% of the world's DFI storage finance on 6% of the rows. That is a statement about IDB Invest's disclosure policy.

And where the 205 candidates currently sit shows the ambiguity is structural, not fixable:

| Current canonical home | Rows | USD (m) |
|---|---:|---:|
| Infrastructure / Transport & Logistics | 54 | 1,893.0 |
| Agribusiness & Food | 37 | 716.6 |
| Manufacturing | 35 | 556.6 |
| Financial Institutions (incl. Banking) | 39 | 872.2 |
| Infrastructure / other | 12 | 374.8 |
| everything else | 28 | 364.9 |

A grain silo is agribusiness. A cold store attached to a processing plant is manufacturing. A logistics park is real estate. A warehouse financed through a bank credit line is a financial institution. **These are all defensible classifications, and no mapping choice makes them one category** — which is the definition of a category that does not resolve.

### The deeper problem: the on-lending veil

**$452.1bn — 37.4% of all disclosed value — sits in `Financial Institutions` and `Investment Funds`.** That is money on-lent to end borrowers the DFIs never name. Whatever the true storage-and-handling share is, more than a third of the denominator is a black box, and there is no reason to assume the black box has the same sector mix as the disclosed portion. Even a perfect taxonomy on the disclosed 63% would not settle the claim.

### What this means for the claim

The concentration half is directionally checkable and unsurprising: within Infrastructure 2015–2025, **Energy & Utilities is 38.4% of value and Transport & Logistics 31.3% — 69.7% together.** But that is `Energy` and `Transport`, not generation and corridor. The comparison half — "the storage layer receives materially less" — cannot be measured at all, and would in any case be near-tautological: any narrowly-defined layer receives less than a broadly-defined one, so the sentence has no falsifiable content without a denominator the data cannot supply.

**Phase 3 is not run.** Per instruction, and because computing sector shares with a storage line would produce an authoritative-looking number built on disclosure verbosity.

**If you want to keep something in this territory,** Claim 6 below is the survivable version: it makes a structural point about sovereign versus private financeability — and, underneath it, ticket size — that lands on the same commercial insight, the margin-capture layer being structurally hard to finance, without asserting a sector share the data cannot support. It is also the claim the reader is best placed to confirm from his own experience, which makes it a better opener than a number he would have to take on trust.

---

## Phase 4 — Alternative claims that survive

Ranked by how likely a practitioner with logistics-parks-and-warehousing-across-frontier-markets background is to find them non-obvious.

Panel-wide caveats that travel with **every** claim below:

- All totals are **floors on disclosed public data**. Undisclosed amounts (980 rows) and undisclosed sectors are excluded, not imputed.
- Amounts are **nominal USD at commitment-year annual-average FX**.
- **$452.1bn (37.4%) is on-lending through financial institutions and funds**, where end use is unobservable.
- The panel is ten DFIs. It is not "development finance" — no China policy banks, no World Bank IBRD/IDA sovereign lending, no bilateral ODA.

---

### Claim 1 — Guarantees proliferated while the average guarantee shrank by two-thirds

> **Publishable form:** Across the six DFIs that disclose instrument type consistently, the number of guarantee commitments tripled between 2010–2015 and 2021–2025, from 204 to 643 — while the median guarantee fell 68%, from $29.3m to $9.5m, and total guarantee value fell 32%. Over the same period the median direct loan grew. The mobilisation turn shows up as many small guarantees, not as more risk capital.

**Numbers**

| Period | Guarantees (n) | Median | Mean | p90 | Total ($m) |
|---|---:|---:|---:|---:|---:|
| 2010–2015 | 204 | $29.27m | $145.9m | $218.0m | 29,756 |
| 2016–2020 | 333 | $8.78m | $57.5m | $126.9m | 19,142 |
| 2021–2025 | 643 | $9.46m | $31.4m | $59.5m | 20,213 |

Debt over the same windows: mean $39.9m → $42.4m → **$52.1m** (n = 2,903 / 2,842 / 3,411). Political risk insurance is the one instrument that grew in size: mean $45.9m → $83.5m, n 29 → 70.

**SQL**

```sql
SELECT CASE WHEN yr<=2015 THEN '2010-2015' WHEN yr<=2020 THEN '2016-2020'
            ELSE '2021-2025' END AS period,
       pi.canonical_instrument, COUNT(*) n,
       ROUND(AVG(amount_usd)/1e6,1) mean_m, ROUND(SUM(amount_usd)/1e6,0) total_m
FROM (SELECT *, COALESCE(CAST(substr(approval_date,1,4) AS INTEGER), fiscal_year) yr
      FROM projects) p
JOIN project_instruments pi ON pi.project_id = p.id
WHERE p.institution IN ('ADB','DFC','EBRD','IDB Invest','IFC','Proparco')
  AND p.yr BETWEEN 2010 AND 2025 AND p.amount_usd > 0
GROUP BY 1,2 ORDER BY 2,1;
```

**Coverage caveat that must travel with it.** Instrument type is only usable for six of ten institutions. **BII, EIB Global and FMO have zero instrument coverage.** AfDB collapses from 87.4% coverage in 2015–2019 to 19.5% in 2020–2025 (its IATI enrichment does not extend to recent years) and is excluded for that reason — including it would manufacture a false trend. The six retained institutions run 75–100% coverage in both windows.

Second caveat: **use the median, not the mean.** The 2010–2015 mean is inflated by trade-finance programme envelopes — EBRD `Regional TFP: National Bank Of Egypt` at $4,538m, `Regional TFP: AikBank` at $2,542m, three IFC Global Trade Supplier Finance facilities at $1,000m each. These are revolving facility limits, not commitments, and they are not comparable to a project guarantee. The median falls 68% regardless, and p90 falls 73%, so the compression is real independent of the outliers.

Third caveat: a guarantee's `amount_usd` is the amount guaranteed, which is not economically the same quantity as a loan commitment. The count trend is more robust than the value trend.

**Obvious to a practitioner?** The direction is not — most people in the market have absorbed "DFIs are pivoting to guarantees and mobilisation" and would expect guarantee *weight* to be rising. It is not: guarantee value fell 32% while debt grew. The count-up/size-down split is the non-obvious part and it is the operationally relevant one, because it says the guarantee product has moved down-market into small credit enhancements rather than up-market into large risk transfer. **This is the strongest claim in the set.**

---

### Claim 2 — Sub-Saharan Africa's infrastructure weight is entirely one institution's sovereign book

> **Publishable form:** Sub-Saharan Africa looks more infrastructure-heavy than the rest of the world — 33.4% of disclosed value versus 28.1%. Remove AfDB, whose Sub-Saharan book is 92% sovereign, and the ranking inverts: the private-facing DFIs put **less** of their African money into infrastructure than they do elsewhere, 23.7% versus 27.9%.

**Numbers** (2015–2025, share of disclosed value)

| Sector | SSA, all institutions | RoW, all | SSA ex-AfDB | RoW ex-AfDB |
|---|---:|---:|---:|---:|
| Infrastructure | 33.4% | 28.1% | **23.7%** | **27.9%** |
| Financial Institutions | 24.5% | 41.2% | 35.3% | 42.3% |
| Investment Funds | 4.4% | 4.0% | 8.3% | 4.2% |
| Digital & Telecom | 3.1% | 2.1% | 5.2% | 2.2% |
| Extractives | 2.0% | 1.8% | 3.9% | 1.8% |

AfDB's Sub-Saharan portfolio: 4,878 sovereign rows, 433 non-sovereign.

**SQL**

```sql
SELECT canonical_sector,
  ROUND(100.0*SUM(CASE WHEN canonical_region='Sub-Saharan Africa' THEN COALESCE(amount_usd,0) END)
        / (SELECT SUM(COALESCE(amount_usd,0)) FROM projects
           WHERE canonical_region='Sub-Saharan Africa' AND institution<>'AfDB'
             AND COALESCE(CAST(substr(approval_date,1,4) AS INTEGER),fiscal_year) BETWEEN 2015 AND 2025),1) ssa_pct,
  ROUND(100.0*SUM(CASE WHEN canonical_region<>'Sub-Saharan Africa' THEN COALESCE(amount_usd,0) END)
        / (SELECT SUM(COALESCE(amount_usd,0)) FROM projects
           WHERE canonical_region<>'Sub-Saharan Africa' AND institution<>'AfDB'
             AND COALESCE(CAST(substr(approval_date,1,4) AS INTEGER),fiscal_year) BETWEEN 2015 AND 2025),1) row_pct
FROM projects
WHERE COALESCE(CAST(substr(approval_date,1,4) AS INTEGER),fiscal_year) BETWEEN 2015 AND 2025
  AND institution <> 'AfDB'
GROUP BY 1 ORDER BY 2 DESC;
```

**Coverage caveat.** `sovereign_exposure` is populated **for AfDB only** — all 5,949 AfDB rows, zero elsewhere. The sovereign/non-sovereign split cannot be run panel-wide; the AfDB figure is used here only to characterise AfDB, not to compare institutions. The regional comparison is also a composition artefact in the other direction: EBRD's 9,415 rows are almost entirely non-African and heavily financial, which inflates the rest-of-world financial share. The claim is safest stated as *"AfDB is doing something structurally different from the other nine"* rather than as a clean geographic contrast.

**Obvious to a practitioner?** Partly. Anyone who has raised in Africa knows AfDB and IFC behave differently. What is not obvious is the **magnitude and the sign flip** — that the entire "Africa gets more infrastructure" observation is one balance sheet, and that on private-facing capital Africa is actually *under*-weighted in infrastructure relative to the rest of the DFI world. That reframes a pitch.

---

### Claim 3 — A quarter of Sub-Saharan DFI money has no country

> **Publishable form:** $75.1bn of the $293.0bn disclosed for Sub-Saharan Africa — 25.6% — is booked to "Regional / Africa" rather than to any country. It is the single largest recipient line in the region, three times South Africa. Country-level league tables of DFI flows are missing a quarter of the money by construction.

**Numbers**

| Recipient | Rows | USD (bn) |
|---|---:|---:|
| **Regional — Africa** | **2,356** | **75.06** |
| South Africa | 410 | 27.21 |
| Nigeria | 501 | 24.70 |
| Kenya | 571 | 16.25 |
| Côte d'Ivoire | 322 | 10.43 |
| Tanzania | 297 | 10.06 |

Concentration including the regional bucket: top-5 = 52.4%, top-10 = 67.1%, top-20 = 84.7% of $293.0bn.
Excluding it, across 48 countries: top-5 = 40.7%, top-10 = 59.3%, top-20 = 81.0% of $217.9bn.

Composition of the regional bucket: AfDB $37.2bn, IFC $16.0bn, EIB Global $10.1bn, BII $5.7bn, DFC $2.9bn, FMO $1.9bn, Proparco $1.4bn. By sector: Infrastructure $21.8bn, Financial Institutions $20.1bn, Other/Multi-sector $10.8bn, Investment Funds $5.7bn.

**SQL**

```sql
SELECT canonical_country, COUNT(*) n, ROUND(SUM(COALESCE(amount_usd,0))/1e9,2) usd_bn
FROM projects WHERE canonical_region='Sub-Saharan Africa'
GROUP BY 1 ORDER BY 3 DESC LIMIT 20;
```

**Coverage caveat.** The regional bucket is heterogeneous — multi-country facilities, regional funds, pan-African financial institutions, and genuine regional infrastructure. It is not a data error; it is a real category that country-level analysis silently drops. Note also that these are **commitments, not disbursements or exposure**, and that the $75.1bn includes fund commitments that will be deployed across countries over a decade.

**Obvious to a practitioner?** The existence of regional facilities, yes. **The share, no.** Most people would guess 5–10%. That it is the largest single line in African DFI, larger than South Africa and Nigeria combined, is a genuinely useful fact for anyone building a country pipeline — it says a quarter of the addressable capital is not reachable through a country-level relationship.

---

### Claim 4 — The small bilateral DFIs are the ones that share borrowers; the big regionals go alone

> **Publishable form:** Normalised for portfolio size, FMO, DFC and BII are five to fifteen times more likely than EBRD or AfDB to appear alongside another DFI on the same borrower. In Sub-Saharan Africa the rate is 165, 163 and 151 clusters per 1,000 deals for FMO, DFC and BII, against 61 for IFC, 52 for EIB Global and 11 for AfDB. The unnormalised picture says the opposite, because IFC's sheer volume puts it in 52% of all clusters.

**Numbers**

Cluster participation, all geographies:

| Institution | Rows | Clusters | Per 1,000 rows |
|---|---:|---:|---:|
| FMO | 1,511 | 215 | **142.3** |
| BII | 1,368 | 192 | **140.4** |
| DFC | 1,313 | 142 | **108.1** |
| ADB | 342 | 21 | 61.4 |
| IFC | 7,035 | 386 | 54.9 |
| Proparco | 899 | 44 | 48.9 |
| EIB Global | 4,722 | 209 | 44.3 |
| IDB Invest | 2,087 | 75 | 35.9 |
| EBRD | 9,415 | 255 | 27.1 |
| AfDB | 5,949 | 68 | **11.4** |

Restricted to Sub-Saharan Africa, so geography is held roughly constant: FMO 164.7, DFC 163.4, BII 150.5, IFC 60.5, Proparco 58.0, EIB Global 51.5, AfDB 10.9.

AfDB's outlier status is structural, not behavioural: its Sub-Saharan book is 92% sovereign, and sovereign lending does not share a borrower name with private DFIs. **Restricted to AfDB's non-sovereign window, the rate jumps from 10.9 to 90.1 per 1,000 — an eight-fold increase** — putting it in line with IFC.

Most frequent pairings (raw cluster counts): EBRD+IFC 136, BII+IFC 79, BII+FMO 78, DFC+FMO 72, EBRD+EIB 67, FMO+IFC 65, EIB+IFC 63, IDB Invest+IFC 58.

**SQL**

```sql
WITH clusters AS (
  SELECT probable_duplicate_group g, institution
  FROM projects
  WHERE probable_duplicate_group IS NOT NULL AND probable_duplicate_group <> ''
    AND canonical_region = 'Sub-Saharan Africa'
  GROUP BY 1,2
)
SELECT c.institution, COUNT(*) clusters, s.n rows,
       ROUND(1000.0*COUNT(*)/s.n,1) per_1000
FROM clusters c
JOIN (SELECT institution, COUNT(*) n FROM projects
      WHERE canonical_region='Sub-Saharan Africa' GROUP BY 1) s
  ON s.institution = c.institution
GROUP BY 1 ORDER BY 4 DESC;
```

**Coverage caveat — the heaviest in this memo.** As established in Phase 1, `probable_duplicate_group` is a **fuzzy name-match on the same borrower in the same country within ±1 year**, not a verified co-financing. It will flag two separate facilities to one bank as a cluster, and it will miss any genuine co-financing where the institutions named the deal differently. **Do not state a co-financing volume or a syndication share from this field.** The claim is defensible as *"these institutions are repeatedly found on the same names"* and not as *"these institutions co-finance at these rates."* State that limitation in the post itself if you make this claim.

**Anchor-versus-follow cannot be tested.** Sequencing requires dates, and **DFC has zero `approval_date` values** across all 1,313 rows while sitting in 142 clusters. Any ordering test would systematically misplace one of the three institutions the claim is about. This is a real gap, not a judgement call — do not compute it.

**Obvious to a practitioner?** The pairings, largely yes — anyone who has run a process knows FMO and BII travel together. The **inversion under normalisation** is not obvious and is the publishable part: the institution most present in co-lending clusters (IFC, 52% of them) is the one *least* inclined to it per deal among the private-facing DFIs. That is a useful correction to the reflex of anchoring a process on IFC.

---

### Claim 5 — BII runs a platform book; nobody else does

> **Publishable form:** 78.9% of BII's deals and 74.0% of its committed value go to borrowers it has backed before — roughly double the next institution and six times DFC. These are not tranches: Globeleq appears twelve times across 2017–2023, Gridworks twelve times across 2019–2025, Miro Forestry thirteen times across 2015–2025. BII builds platforms and refinances them; the rest of the panel largely transacts.

**Numbers**

| Institution | Distinct counterparties | Deals | Deals per counterparty | % deals to repeat | % value to repeat |
|---|---:|---:|---:|---:|---:|
| **BII** | 661 | 1,368 | **2.07** | **78.9%** | **74.0%** |
| IFC | 5,255 | 6,989 | 1.33 | 38.2% | 46.3% |
| ADB | 265 | 340 | 1.28 | 38.8% | 35.4% |
| Proparco | 745 | 893 | 1.20 | 28.1% | 27.0% |
| EBRD | 7,670 | 9,409 | 1.23 | 26.1% | 19.0% |
| FMO | 1,299 | 1,511 | 1.16 | 26.1% | 13.8% |
| IDB Invest | 1,219 | 1,408 | 1.16 | 23.4% | 20.6% |
| DFC | 1,038 | 1,133 | 1.09 | 13.2% | 12.6% |

BII's top repeat names: Standard Chartered (20 deals, 2013–2025), ABSA (16, 2019–2024), Miro Forestry (13, 2015–2025), Gridworks (12, 2019–2025), Globeleq (12, 2017–2023), Feronia (11, 2013–2020), Indorama Eleme Fertilizer (8, 2013–2025).

**SQL**

```sql
WITH x AS (
  SELECT institution, counterparty_key, COUNT(*) n, SUM(COALESCE(amount_usd,0)) v
  FROM projects
  WHERE counterparty_key IS NOT NULL AND TRIM(counterparty_key) <> ''
  GROUP BY 1,2)
SELECT institution, COUNT(*) distinct_cp, SUM(n) deals,
       ROUND(1.0*SUM(n)/COUNT(*),2) deals_per_cp,
       ROUND(100.0*SUM(CASE WHEN n>=2 THEN n END)/SUM(n),1) pct_deals_repeat,
       ROUND(100.0*SUM(CASE WHEN n>=2 THEN v END)/SUM(v),1) pct_value_repeat
FROM x GROUP BY 1 ORDER BY 6 DESC;
```

**Coverage caveat.** `counterparty` is **null for AfDB (5,949 rows) and EIB Global (4,722 rows)** — 31% of the database is out of scope for this claim, and those two must not appear in the table. Of the counterparties that exist, 9,630 are **disclosed** and 13,421 are **derived from project name** by rule (`derive_counterparties.py`, `counterparty_rules.csv`); the derived ones can over-merge similar names. IDB Invest is only 67.5% covered and DFC 86.3%, so their repeat rates are likely **understated**. Finally, BII's number is partly a disclosure convention — it publishes at a finer transaction grain than peers — but the named examples above are separate financings years apart, not capital calls, so the pattern is not purely artefactual.

**Obvious to a practitioner?** The Globeleq and Gridworks relationships, yes, to anyone in African power. **The systematic gap is not.** A 79%-versus-13% spread between BII and DFC on repeat business is a concrete statement about which DFI is worth building a decade-long platform relationship with, and it is exactly the kind of thing that is felt anecdotally but rarely quantified.

---

### Claim 6 — Transport is a sovereign product; energy is a private one

> **Publishable form:** Between 2015 and 2025 the median disclosed transport commitment was $43.4m against $19.2m for energy — 29.3% of transport deals exceeded $100m against 11.7% of energy deals. Energy is a high-count, low-ticket business for DFIs; transport is the opposite. The reason is not sector preference but which balance sheet the asset sits on: among the four institutions that can lend to a government, transport out-raises energy, $56.2bn against $53.0bn. Among the six that can only lend privately, energy beats transport more than five to one. Energy unbundled into privately-financeable assets a generation ago. Transport did not.

**Do not frame the aggregate gap as a puzzle.** Energy's $73.7bn against transport's $60.0bn — a $13.7bn gap — sits alongside a transport cheque twice the size, which simply means far fewer transport deals (714 against 1,726). That is arithmetic, not a finding, and presenting it as a tension invites the reply that it is definitional. The finding is the *route*: two sectors reaching comparable totals through opposite mechanics, for a structural reason.

**Numbers** (disclosed amounts > 0, 2015–2025)

Infrastructure subsectors:

| Subsector | n | p25 | Median | p75 | p90 | Total (bn) | <$10m | <$25m | ≥$100m |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Transport & Logistics | 714 | $11.8m | **$43.4m** | $116.9m | $223.0m | 60.0 | 22.3% | 38.2% | **29.3%** |
| Water & Sanitation | 381 | $3.2m | $19.7m | $72.8m | $121.1m | 17.7 | 38.3% | 55.4% | 16.3% |
| Energy & Utilities | 1,726 | $7.0m | **$19.2m** | $49.0m | $104.0m | 73.7 | 31.4% | 56.5% | **11.7%** |
| Municipal & Environmental | 507 | $4.2m | $11.5m | $31.6m | $70.5m | 13.9 | 44.0% | 69.8% | 5.7% |

All sectors, by median cheque: Extractives $40.0m, **Infrastructure $20.0m**, Digital & Telecom $17.4m, Financial Institutions $16.3m, Tourism/Retail/Property $15.8m, Investment Funds $14.2m, Health & Education $11.6m, Manufacturing $11.2m, **Agribusiness & Food $10.8m**, Services $8.6m.

Within Infrastructure 2015–2025: Energy & Utilities 38.4% of value, Transport & Logistics 31.3% — 69.7% together.

**The driver: sovereign capacity, not sector preference.** Split the panel by whether an institution can lend to a government at all:

| Group | Energy deals | Energy $bn | Transport deals | Transport $bn | Energy mean | Transport mean |
|---|---:|---:|---:|---:|---:|---:|
| **Sovereign-capable** (AfDB, EIB Global, EBRD, ADB) | 975 | 53.0 | 624 | **56.2** | $54.4m | $90.0m |
| **Private-only** (IFC, FMO, BII, DFC, IDB Invest, Proparco) | 751 | 20.7 | 90 | **3.9** | $27.6m | $43.1m |

**Among institutions that can lend to sovereigns, transport out-raises energy.** The aggregate "transport gets less" observation exists only because the two groups are pooled. Among private-only DFIs, energy outruns transport 5.3 to 1.

AfDB carries the mechanism directly, because it is the one institution in the panel with a populated sovereign flag: its 2015–2025 transport book is **200 sovereign deals against 18 non-sovereign, 92% sovereign by value** ($19.0bn of $21.4bn). Its energy book is 77% sovereign ($9.4bn of $12.2bn). Transport sits on government balance sheets; energy has substantially moved off them.

Institution-level detail (2015–2025, disclosed amounts, $bn):

| Institution | Energy n | Energy $bn | Transport n | Transport $bn |
|---|---:|---:|---:|---:|
| AfDB | 246 | 12.19 | 218 | 21.42 |
| EIB Global | 251 | 16.21 | 203 | 21.07 |
| EBRD | 383 | 19.12 | 189 | 12.33 |
| ADB | 95 | 5.48 | 14 | 1.33 |
| IDB Invest | 82 | 3.47 | 36 | 1.93 |
| DFC | 83 | 5.67 | 20 | 1.00 |
| BII | 202 | 5.23 | 22 | 0.59 |
| Proparco | 91 | 2.08 | 12 | 0.36 |
| FMO | 293 | 4.25 | 0 | — |
| IFC | — | — | — | — |

**SQL**

```sql
-- the ticket-size distribution
SELECT canonical_subsector, COUNT(*) n,
       ROUND(100.0*SUM(amount_usd<10000000)/COUNT(*),1)  pct_under_10m,
       ROUND(100.0*SUM(amount_usd<25000000)/COUNT(*),1)  pct_under_25m,
       ROUND(100.0*SUM(amount_usd>=100000000)/COUNT(*),1) pct_over_100m,
       ROUND(SUM(amount_usd)/1e9,1) total_bn
FROM projects
WHERE amount_usd > 0 AND canonical_sector='Infrastructure'
  AND COALESCE(CAST(substr(approval_date,1,4) AS INTEGER),fiscal_year) BETWEEN 2015 AND 2025
GROUP BY 1 ORDER BY 6 DESC;
```
(Percentiles computed in Python from the same filtered set; SQLite has no native percentile function.)

```sql
-- the sovereign/private split
SELECT CASE WHEN institution IN ('AfDB','EIB Global','EBRD','ADB')
            THEN 'sovereign-capable' ELSE 'private-only' END AS grp,
       canonical_subsector, COUNT(*) n,
       ROUND(SUM(amount_usd)/1e9,2) bn, ROUND(AVG(amount_usd)/1e6,1) mean_m
FROM (SELECT *, COALESCE(CAST(substr(approval_date,1,4) AS INTEGER), fiscal_year) yr
      FROM projects) p
WHERE amount_usd > 0 AND yr BETWEEN 2015 AND 2025
  AND canonical_subsector IN ('Energy & Utilities','Transport & Logistics')
GROUP BY 1,2 ORDER BY 1,2;
```

**Coverage caveat — the ticket-size half.** Cheque size is the **institution's own commitment**, not project cost — a $43m median transport commitment often sits inside a project several times that. 980 rows have no disclosed amount and are excluded, which biases the distribution upward if undisclosed deals are systematically smaller. And per Phase 2, `Transport & Logistics` is 96.6% one undifferentiated word: this compares *the transport bucket* to *the energy bucket*, not roads to power plants.

**Coverage caveat — the sovereign/private half. The two legs are not equally sound, and the difference must be stated.**

The **sovereign-capable leg is clean**: only $0.38bn of its infrastructure (0.3%, 7 rows) lacks a subsector. The finding *"among institutions that can lend to sovereigns, transport out-raises energy, $56.2bn to $53.0bn"* is safe to publish as stated.

The **private-only leg is not**. Of that group's $51.8bn of 2015–2025 infrastructure, **$24.2bn — 47% — has no subsector at all**, because IFC and FMO publish "Infrastructure" as a single undifferentiated word. Composition of the blind pool: IFC $21.2bn (290 rows), FMO $2.9bn (293 rows), everyone else $0.5bn. **IFC therefore appears nowhere in the tables above**, despite being the largest institution in the panel. FMO's zero in the transport column is a taxonomy artefact, not a business fact — FMO's four sector buckets contain no transport category, so any transport it does is inside its $2.9bn "Infrastructure, Manufacturing and Services" line.

A name-only probe of IFC's 290 unclassified infrastructure rows (no descriptions exist) resolves 79 rows / $4.4bn as energy and 18 rows / $1.6bn as transport, leaving **193 rows and $15.2bn — 72% of the pool by value — ambiguous even by name.** The direction survives the probe (roughly 2.7:1 energy on the resolvable part, against 5.3:1 on the classified data), but the gap cannot be closed.

**Therefore:** publish the sovereign-capable comparison as a number. Treat the private-only ratio as **directional only**, and say so. Do not state a private-DFI transport total.

**Obvious to a practitioner?** The ticket-size direction is intuitive once stated — ports and rail are lumpier than solar. **The magnitude is not**: 56.5% of energy deals are under $25m versus 38.2% of transport deals, so the DFI energy desk routinely writes cheques the transport desk does not. **The sovereign/private split is the genuinely non-obvious part**, and it is the half worth leading with. Almost everyone reads the aggregate as a statement about DFI sector appetite. It is not — it is a statement about which asset classes became privately financeable. Anyone who has raised for both a power project and a port has felt this, but rarely seen it separated.

**This is the honest survivor of the original claim.** It reaches the same commercial insight — the margin-capture layer is structurally hard to finance — without asserting a sector share the taxonomy cannot produce. It also locates the reason more precisely than ticket size alone did.

**The question it sets up, which the data raises and cannot settle:** energy unbundled into privately-financed IPPs a generation ago — a project company, an offtake, a bankable asset. Transport largely did not. *What did solar clear that ports and warehousing did not?* That is answerable only from operating experience, which makes it a conversation rather than an assertion to be checked.

**A hypothesis, explicitly labelled as one.** If the storage and handling layer is invisible in DFI data, one candidate reason is that it is a private, small-ticket, commercially-financed asset class fitting neither the sovereign transport window nor the private energy playbook. **The data cannot test this.** It is a better thing to put to a practitioner than a sector share, but it must be offered as a question, not a finding.

---

## Two things the data cannot answer

Stated plainly rather than computed.

**Data centres.** A keyword sweep on `data cent`, `datacent` and `hyperscal` across all 34,641 rows returns **16 deals**: 3 in 2010, 1 in 2012, 1 in 2018, 1 in 2020, 1 in 2021, 3 in 2022, 1 in 2023, 3 in 2024, 1 in 2026. That is not a series. It is also subject to the same disclosure artefact as Phase 2 — IFC has no descriptions, so IFC data centre deals are invisible unless the facility is named in the project title, and no institution has a data centre sector code. **Do not make a data centre claim from this database.** Given that this is the reader's own vertical, being straight about the gap is worth more than a number.

**Digital more broadly** *is* measurable, because it is mapping-based rather than text-based, and the result is worth knowing even though it does not make the ranked list. `Digital & Telecom` was **2.73% of disclosed value in 2010–2015 and 2.67% in 2020–2025** — flat across fifteen years, and never above 3.6% in any single year globally. In Sub-Saharan Africa the value share roughly doubled, 2.16% → 4.00%, but on 5 to 24 deals a year, swinging between 0.46% (2017) and 6.43% (2024). The defensible version is negative and narrow: **the African digital infrastructure boom is not visible as a share of DFI commitments; digital has never exceeded 6.4% of Sub-Saharan DFI value in any year and averages about 3%.** It is a real finding, but it is a claim about what *didn't* happen, and the underlying counts are thin enough that a well-briefed sceptic could push back on the SSA trend specifically. Use the global flatness, not the African doubling.

---

## Assumption register

| # | Assumption | Where it bites |
|---|---|---|
| 1 | Year = `substr(approval_date,1,4)`, falling back to `fiscal_year` | Every time series. Institutions' fiscal years differ; ±1 year noise across the panel. |
| 2 | `amount_usd` = commitment-year annual-average FX, nominal | Cross-year level comparisons. Within-year shares unaffected. |
| 3 | Guarantee `amount_usd` = amount guaranteed | Claim 1. Not economically comparable to a loan commitment. |
| 4 | `probable_duplicate_group` = same-borrower fuzzy match, **not** verified co-financing | Claim 4. Do not state co-financing volumes. |
| 5 | `counterparty` 66% coverage, 58% of that derived by rule not disclosed | Claim 5. Derived keys can over-merge. |
| 6 | `sovereign_exposure` populated for AfDB only | Claim 2. No panel-wide sovereign split exists. |
| 7 | Instrument coverage 71% overall, zero for BII/EIB/FMO, collapsing for AfDB | Claim 1. Six-institution panel only. |
| 8 | 37.4% of value is on-lending with unobservable end use | Every sector share, including the ones in Phase 2. |
| 9 | Description length varies 0–661 chars by institution | Any text-derived classification. This is what kills the storage claim. |
| 10 | Database total is $1,207.2bn; project docs record $1.263T | Unreconciled ~4.4% gap. Cite the computed figure. |
| 11 | Infrastructure subsector coverage is 99.7% for AfDB/EIB/EBRD/ADB but only 53% for the private-only DFIs — IFC and FMO publish "Infrastructure" as one word | Claim 6's private-only leg, and any energy-vs-transport comparison. IFC ($21.2bn) is absent from both subsector buckets entirely; FMO's transport zero is an artefact. |
| 12 | "Sovereign-capable" is defined by institutional mandate (AfDB, EIB Global, EBRD, ADB), not by a per-deal flag | Claim 6. Only AfDB has a row-level `sovereign_exposure`; the grouping is a reasonable proxy that will misclassify each institution's private-window deals. |
