"""
DFI Deal Flow Tracker — Streamlit dashboard.

Run from the project root:
    python -m streamlit run dashboard/app.py

Reads data/dfi_tracker.db (read-only). All filtering happens in pandas on a
cached copy — the database is only touched once per hour per session.
Analysis columns are the harmonized ones (canonical_country/region/sector);
the deal table links every row back to its official disclosure page.
"""

from pathlib import Path
import sqlite3

import altair as alt
import pandas as pd
import streamlit as st

DB_PATH = Path(__file__).parent.parent / "data" / "dfi_tracker.db"

# Fixed color per institution (dataviz reference palette, validated order).
# Color follows the entity: filtering never repaints the survivors.
INSTITUTION_COLORS = {
    "IFC": "#2a78d6",         # blue
    "EBRD": "#1baf7a",        # aqua
    "DFC": "#eda100",         # yellow
    "IDB Invest": "#008300",  # green
    "EIB Global": "#4a3aa7",  # violet
    "AfDB": "#e34948",        # red
}
# Only SIX categorical hues clear the CVD, normal-vision and lightness checks
# together at all-pairs (verified with the dataviz validator; an 8-hue set
# fails — magenta/orange are indistinguishable even with full colour vision,
# and green/orange fail CVD). So the six largest institutions by committed USD
# get a fixed hue each and the rest share a neutral "Other". Membership is
# hardcoded rather than computed at runtime, so filtering never repaints a
# survivor. Every other part of the dashboard still shows all ten separately.
OTHER_SERIES = "Other DFIs"
FOLDED_INTO_OTHER = {"BII", "ADB", "Proparco", "FMO"}
INSTITUTION_COLORS[OTHER_SERIES] = "#898781"  # neutral, not a categorical hue
GRID = "#e1e0d9"
MUTED = "#898781"
BAR_BLUE = "#2a78d6"  # single-hue for magnitude-only charts

st.set_page_config(page_title="DFI Deal Flow Tracker", page_icon="🌍", layout="wide")


@st.cache_data(ttl=3600)
def load_data() -> tuple[pd.DataFrame, str]:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        """SELECT institution, project_name,
                  canonical_country AS country, canonical_region AS region,
                  canonical_sector AS sector, canonical_subsector AS subsector,
                  instrument, amount_usd, approval_date, fiscal_year, status,
                  es_category, sponsor, counterparty, counterparty_provenance,
                  source_url, probable_duplicate_group,
                  COALESCE(CAST(strftime('%Y', approval_date) AS INTEGER),
                           fiscal_year) AS year
           FROM projects""",
        conn,
    )
    data_as_of = conn.execute("SELECT MAX(scraped_at) FROM projects").fetchone()[0]
    conn.close()
    return df, (data_as_of or "")[:10]


def apply_dedupe(df: pd.DataFrame) -> pd.DataFrame:
    """Keep one record per probable co-financing group — the largest single
    commitment — so a deal financed by three institutions counts once."""
    dupes = df[df["probable_duplicate_group"].notna()]
    if dupes.empty:
        return df
    keep = (dupes.assign(_amt=dupes["amount_usd"].fillna(-1.0))
                 .groupby("probable_duplicate_group")["_amt"].idxmax())
    return pd.concat([df[df["probable_duplicate_group"].isna()], df.loc[keep]])


def money(value: float) -> str:
    if pd.isna(value):
        return "—"
    if abs(value) >= 1e12:
        return f"${value / 1e12:,.2f}T"
    if abs(value) >= 1e9:
        return f"${value / 1e9:,.1f}B"
    return f"${value / 1e6:,.1f}M"


df, data_as_of = load_data()

# ---------------------------------------------------------------- sidebar --
st.sidebar.title("Filters")

institutions = st.sidebar.multiselect(
    "Institution", sorted(df["institution"].unique()))
regions = st.sidebar.multiselect(
    "Region", sorted(df["region"].dropna().unique()))
countries = st.sidebar.multiselect(
    "Country", sorted(df["country"].dropna().unique()))
sectors = st.sidebar.multiselect(
    "Sector", sorted(df["sector"].dropna().unique()))
instruments = st.sidebar.multiselect(
    "Instrument", sorted(df["instrument"].dropna().unique()))

year_lo, year_hi = int(df["year"].min()), int(df["year"].max())
year_range = st.sidebar.slider("Year range", year_lo, year_hi, (year_lo, year_hi))
include_undated = st.sidebar.checkbox(
    "Include deals with no year", value=True,
    help="Some disclosures carry no approval date or fiscal year.")

exclude_dupes = st.sidebar.toggle(
    "Exclude probable duplicates", value=False,
    help="Co-financed deals appear once per institution. When on, each "
         "flagged group keeps only its largest single commitment, so the "
         "same deal isn't counted several times. Flags are fuzzy-matched "
         "leads, not confirmed matches.")

# --------------------------------------------------------------- filtering --
view = df
if exclude_dupes:
    view = apply_dedupe(view)
if institutions:
    view = view[view["institution"].isin(institutions)]
if regions:
    view = view[view["region"].isin(regions)]
if countries:
    view = view[view["country"].isin(countries)]
if sectors:
    view = view[view["sector"].isin(sectors)]
if instruments:
    view = view[view["instrument"].isin(instruments)]

year_mask = view["year"].between(*year_range)
view = view[year_mask | (view["year"].isna() if include_undated else False)]

# ----------------------------------------------------------------- header --
st.title("DFI Deal Flow Tracker")
st.caption(
    f"{view['institution'].nunique()} institutions · public disclosure data "
    f"as of {data_as_of} · cumulative disclosed operations (coverage periods "
    "differ by institution — see Data notes)")

with_amount = view[view["amount_usd"].notna()]
col1, col2, col3 = st.columns(3)
col1.metric("Total commitments", money(with_amount["amount_usd"].sum()))
col2.metric("Deals", f"{len(view):,}")
col3.metric("Average ticket", money(with_amount["amount_usd"].mean()))
if len(view) > len(with_amount):
    st.caption(f"{len(view) - len(with_amount):,} deals have no disclosed "
               "amount and are counted in deal totals but not in dollar figures.")

# ----------------------------------------------------------------- charts --
alt.themes.enable("none")


def style(chart: alt.Chart) -> alt.Chart:
    return (chart
            .configure_view(stroke=None)
            .configure_axis(gridColor=GRID, domainColor=GRID,
                            tickColor=GRID, labelColor=MUTED, titleColor=MUTED)
            .configure_legend(labelColor="#52514e", titleColor=MUTED))


inst_scale = alt.Scale(domain=list(INSTITUTION_COLORS),
                       range=list(INSTITUTION_COLORS.values()))

st.subheader("Commitments over time")
by_year = (view.dropna(subset=["year", "amount_usd"])
               .assign(institution=lambda d: d["institution"].where(
                   ~d["institution"].isin(FOLDED_INTO_OTHER), OTHER_SERIES))
               .groupby(["year", "institution"], as_index=False)["amount_usd"].sum())
by_year["amount_bn"] = by_year["amount_usd"] / 1e9
year_chart = (
    alt.Chart(by_year)
    .mark_bar(cornerRadiusTopLeft=2, cornerRadiusTopRight=2,
              stroke="#ffffff", strokeWidth=1)
    .encode(
        x=alt.X("year:O", title=None,
                axis=alt.Axis(labelAngle=0,
                              labelExpr="datum.value % 5 ? '' : datum.value")),
        y=alt.Y("amount_bn:Q", title="Commitments (US$ bn)"),
        color=alt.Color("institution:N", scale=inst_scale, title=None,
                        legend=alt.Legend(orient="top")),
        tooltip=[alt.Tooltip("year:O", title="Year"),
                 alt.Tooltip("institution:N", title="Institution"),
                 alt.Tooltip("amount_bn:Q", title="US$ bn", format=",.2f")],
    )
    .properties(height=280)
)
st.altair_chart(style(year_chart), width="stretch")

left, right = st.columns(2)

with left:
    st.subheader("Top countries")
    country_data = view[~view["country"].fillna("").str.startswith(("Regional", "Undisclosed", "Unclassified"))]
    top_countries = (country_data.dropna(subset=["amount_usd"])
                     .groupby("country", as_index=False)["amount_usd"].sum()
                     .nlargest(15, "amount_usd"))
    top_countries["amount_bn"] = top_countries["amount_usd"] / 1e9
    country_chart = (
        alt.Chart(top_countries)
        .mark_bar(color=BAR_BLUE, cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
        .encode(
            x=alt.X("amount_bn:Q", title="US$ bn"),
            y=alt.Y("country:N", sort="-x", title=None,
                    axis=alt.Axis(labelLimit=200)),
            tooltip=[alt.Tooltip("country:N", title="Country"),
                     alt.Tooltip("amount_bn:Q", title="US$ bn", format=",.2f")],
        )
        .properties(height=400)
    )
    st.altair_chart(style(country_chart), width="stretch")
    st.caption("Country-specific deals only; regional/multi-country "
               "operations are excluded from this ranking.")

with right:
    st.subheader("Sector breakdown")
    by_sector = (view.dropna(subset=["amount_usd", "sector"])
                 .groupby("sector", as_index=False)["amount_usd"].sum()
                 .sort_values("amount_usd", ascending=False))
    by_sector["amount_bn"] = by_sector["amount_usd"] / 1e9
    sector_chart = (
        alt.Chart(by_sector)
        .mark_bar(color=BAR_BLUE, cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
        .encode(
            x=alt.X("amount_bn:Q", title="US$ bn"),
            y=alt.Y("sector:N", sort="-x", title=None,
                    axis=alt.Axis(labelLimit=200)),
            tooltip=[alt.Tooltip("sector:N", title="Sector"),
                     alt.Tooltip("amount_bn:Q", title="US$ bn", format=",.2f")],
        )
        .properties(height=400)
    )
    st.altair_chart(style(sector_chart), width="stretch")

# ------------------------------------------------------------- deal table --
st.subheader("Deals")
search = st.text_input(
    "Search deals", placeholder="Project name or client…", label_visibility="collapsed")
table = view
if search:
    needle = search.strip().lower()
    table = table[
        table["project_name"].fillna("").str.lower().str.contains(needle, regex=False)
        | table["counterparty"].fillna("").str.lower().str.contains(needle, regex=False)]

table = (table.sort_values("approval_date", ascending=False, na_position="last")
              .assign(amount_musd=lambda d: d["amount_usd"] / 1e6))
st.dataframe(
    table[["institution", "project_name", "country", "sector", "instrument",
           "amount_musd", "year", "status", "counterparty", "source_url"]],
    width="stretch", height=420, hide_index=True,
    column_config={
        "institution": st.column_config.TextColumn("Institution", width="small"),
        "project_name": st.column_config.TextColumn("Project"),
        "country": st.column_config.TextColumn("Country"),
        "sector": st.column_config.TextColumn("Sector"),
        "instrument": st.column_config.TextColumn("Instrument", width="small"),
        "amount_musd": st.column_config.NumberColumn("US$ m", format="%,.1f"),
        "year": st.column_config.NumberColumn("Year", format="%d"),
        "status": st.column_config.TextColumn("Status", width="small"),
        "counterparty": st.column_config.TextColumn(
            "Client",
            help="Who the deal was with. Where an institution publishes no "
                 "client field this is derived from the project name; AfDB "
                 "and EIB Global name projects, not clients, so theirs are blank."),
        "source_url": st.column_config.LinkColumn("Disclosure", display_text="View"),
    },
)
st.caption(f"{len(table):,} deals shown.")

# ------------------------------------------------------------- data notes --
with st.expander("Data notes"):
    st.markdown(
        """
- **Coverage periods differ by institution.** IFC (from ~1994), EBRD (1991),
  IDB Invest (1989), AfDB (1967) and BII (2003) disclose cumulative history
  including completed deals; DFC's file covers currently-active projects
  only; ADB non-sovereign covers 2004 onward. EBRD and AfDB include
  state/sovereign operations (flagged in each record's description); the
  others are private-sector only. Cross-institution comparisons are most
  meaningful within a recent year range.
- **BII amounts are lifetime commitment totals** per activity (the sum of
  all commitment transactions ever reported for it), not single approval
  amounts like the other institutions'.
- **EIB Global is a deliberate subset of EIB.** Only EIB's operations
  outside the EU are loaded (8 non-EU regions, ~4,700 loan parts); the
  22,863 EU loan parts are excluded as ordinary European lending rather
  than development finance. Rows are **loan parts (tranches)**, not
  projects — 4,722 tranches span 3,346 project numbers — so EIB Global's
  deal count is not comparable with the others' project counts.
- **Proparco coverage is systematically incomplete.** AFD's open data covers
  only projects signed since 1 January 2014 *and* only those whose clients
  authorised disclosure. Proparco totals here are a floor, never a complete
  picture, and must not be compared like-for-like with IFC/EBRD/AfDB totals
  without saying so.
- **FMO rows carry their fund.** `Fund: FMO` is FMO's own account;
  the rest (MASSIF, Building Prospects, Access to Energy Fund and
  other Dutch government funds) are money FMO administers rather than
  lends. Filter on the fund before comparing FMO with the others.
""")

st.caption(
    "Source: public project disclosures of DFC, IFC (via WBG Finances One), "
    "EBRD, IDB Invest, ADB, AfDB (MapAfrica), BII and FMO (IATI), Proparco "
    "(AFD open data) and EIB Global · compiled by RCFH Advisory · DFI Deal "
    "Flow Tracker")
