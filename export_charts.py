"""
export_charts.py — renders the tracker's exhibits in the RCFH Advisory
Bathymetric house style.

Run:
    python export_charts.py

Writes into charts/. The apparatus (header band, coverage strip, brass rules,
notes block, source block) comes from brand/rcfh_chart.py, vendored from the
rcfh-advisory-brand skill. Nothing here restyles matplotlib by hand.

THREE HOUSE RULES THIS FILE IS BUILT AROUND
  * Brass never fills. It marks the apparatus and, via emphasise_row, the one
    row an exhibit argues about.
  * Colour encodes an ordering, never nothing. Every chart below states which
    ordering its ramp carries: rank, chronology, or a technical ladder. Where
    the categories genuinely have no order (the thematic labels), the note
    says so, so nobody reads depth as magnitude.
  * Every exhibit carries a notes block. rcfh.save refuses a figure without
    one, and the coverage strip runs on every exhibit including those drawing
    on all ten institutions, because a strip that appears only when something
    is missing trains the reader to ignore it.

TYPE
Sitka ships on this machine only as a variable font (SitkaVF.ttf), which
matplotlib reads as a single family "Sitka"; it cannot address the Heading and
Text optical sizes the house style specifies. Rather than render headings at
the wrong weight, these exhibits use the declared fallback, Georgia, which
carries the correct weights and renders identically on any machine. Set
USE_SITKA_VF = True to prefer the variable font instead.

COMPARABILITY, unchanged from the previous build
Institution totals are not like-for-like. EIB Global counts loan tranches,
Proparco covers only disclosure-consented deals since 2014, and three
institutions publish no instrument at all. Every exhibit states its own cut.
FMO is filtered to its OWN ACCOUNT throughout: its disclosure covers both its
own book and the Dutch government funds it administers, and blending them
inflates its deal count with programme grants.

Counts and averages use OPERATIONS, not rows. EIB Global discloses loan
tranches and EBRD splits some facilities, so one deal can arrive as many rows.
Rows sharing an institution, a name and a date are summed back into one
operation first.
"""

import csv
import sqlite3
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.font_manager as fm  # noqa: E402

USE_SITKA_VF = False
_SITKA_VF = Path("C:/Windows/Fonts/SitkaVF.ttf")
if USE_SITKA_VF and _SITKA_VF.exists():
    fm.fontManager.addfont(str(_SITKA_VF))

sys.path.insert(0, str(Path(__file__).parent / "brand"))
sys.path.insert(0, str(Path(__file__).parent))
import rcfh_chart as rcfh  # noqa: E402
from database import DB_PATH  # noqa: E402

if USE_SITKA_VF and _SITKA_VF.exists():
    rcfh.HEADING = ["Sitka"] + rcfh.HEADING
    rcfh.BODY = ["Sitka"] + rcfh.BODY

OUT_DIR = Path(__file__).parent / "charts"
RECENT_FROM, RECENT_TO = 2015, 2024

ALL_TEN = ["IFC", "EBRD", "AfDB", "EIB Global", "IDB Invest",
           "FMO", "BII", "DFC", "Proparco", "ADB"]

# World Bank income-group names run long enough to collide in a single-row
# legend. The full names stay in the CSV and in the notes.
SHORT_GROUP = {"Low income": "Low   ", "Lower middle income": "Lower-middle   ",
               "Upper middle income": "Upper-middle   ", "High income": "High"}

YEAR = ("COALESCE(CAST(strftime('%Y', approval_date) AS INTEGER), fiscal_year)")
WINDOW = f"{YEAR} BETWEEN {RECENT_FROM} AND {RECENT_TO}"

# FMO publishes its own book alongside Dutch government funds it merely
# administers. Only own-account rows belong beside institutions that lend off
# their own balance sheet. The tag sits at the front of the description.
OWN_ACCOUNT = ("(institution <> 'FMO' OR description LIKE 'Fund: FMO%' "
               "OR description LIKE 'Funds: FMO%' "
               "OR description LIKE '%; FMO%' OR description LIKE '%Fund: FMO')")

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def long_date(iso):
    """2026-08-20 -> 20 August 2026. The house style never uses 8/20/26."""
    if not iso or len(iso) < 10:
        return iso or ""
    y, m, d = iso[:4], int(iso[5:7]), int(iso[8:10])
    return f"{d} {MONTHS[m - 1]} {y}"


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def as_of(conn):
    return long_date((conn.execute(
        "SELECT MAX(scraped_at) FROM projects").fetchone()[0] or "")[:10])


def money(v_bn):
    return f"USD {v_bn:,.1f}bn" if v_bn < 100 else f"USD {v_bn:,.0f}bn"


# ------------------------------------------------------------- exhibit 01 --
def commitments_over_time(conn, stamp):
    """Total committed value per year, ramp by CHRONOLOGY.

    A single series rather than the seven-institution stack this replaced.
    The palette carries five stops and the house rule is that beyond five
    series a chart is doing too much; the institutional split has its own
    exhibits. Colouring a year chart by value would scramble chronology, so
    the ramp runs earliest-shallow to latest-deep.
    """
    rows = conn.execute(
        f"""SELECT {YEAR} y, SUM(amount_usd) / 1e9 bn FROM projects
            WHERE {WINDOW} AND amount_usd IS NOT NULL AND {OWN_ACCOUNT}
            GROUP BY 1 ORDER BY 1""").fetchall()
    years = [r["y"] for r in rows]
    values = [r["bn"] for r in rows]

    fig, ax = rcfh.figure("tracker")
    rcfh.header(fig, "Development finance commitments have risen by half",
                dek=f"Disclosed commitments of ten institutions, {RECENT_FROM}"
                    f"\u2013{RECENT_TO}. The ramp runs in chronological order, "
                    "earliest shallowest.", exhibit="01")
    rcfh.coverage(fig, included=ALL_TEN)
    ax.bar(years, values, color=rcfh.by_sequence(len(years), reverse=True),
           width=0.68, zorder=3)
    ax.grid(False)
    ax.yaxis.grid(True, color=rcfh.FATHOM, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_xticks(years)
    ax.set_ylabel("USD billions committed")
    for x, v in zip(years, values):
        ax.text(x, v + max(values) * 0.02, f"{v:,.0f}", ha="center",
                va="bottom", color=rcfh.SOUNDING, fontsize=11,
                fontfamily=rcfh.MONO)
    rcfh.notes(fig,
               "Coverage differs by institution and totals are a FLOOR, not a "
               "market size. EIB Global counts loan tranches rather than whole "
               "projects; Proparco covers only deals signed since 2014 whose "
               "clients consented to disclosure; FMO is its own account only. "
               f"{RECENT_TO + 1} is omitted because several sources had not "
               "reported it in full, which would read as a fall that did not "
               "happen.")
    rcfh.source(fig, as_of=stamp)
    return rcfh.save(fig, OUT_DIR / "01_commitments_over_time.png")


# ------------------------------------------------------------- exhibit 02 --
def top_countries(conn, stamp):
    """Top 15 recipients, ramp by RANK."""
    rows = conn.execute(
        f"""SELECT canonical_country c, SUM(amount_usd) / 1e9 bn FROM projects
            WHERE {WINDOW} AND amount_usd IS NOT NULL AND {OWN_ACCOUNT}
              AND canonical_country IS NOT NULL
              AND canonical_country NOT LIKE 'Regional%'
              AND canonical_country NOT IN ('Undisclosed', 'Unclassified')
            GROUP BY 1 ORDER BY bn DESC LIMIT 15""").fetchall()
    labels = [r["c"] for r in rows][::-1]
    values = [r["bn"] for r in rows][::-1]

    fig, ax = rcfh.figure("tracker")
    rcfh.header(fig, "Where development finance went",
                dek=f"Top 15 country recipients by disclosed commitment, "
                    f"{RECENT_FROM}\u2013{RECENT_TO}. The ramp follows the "
                    "ranking, deepest on the largest.", exhibit="02")
    rcfh.coverage(fig, included=ALL_TEN)
    fig.subplots_adjust(left=0.24)
    ax.barh(range(len(values)), values, color=rcfh.by_rank(values),
            height=0.66, zorder=3)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels)
    ax.set_xlim(0, max(values) * 1.18)
    rcfh.value_labels(ax, values, [money(v) for v in values])
    rcfh.emphasise_row(ax, len(values) - 1)
    rcfh.notes(fig,
               "Country-specific deals only: regional and multi-country "
               "operations are excluded, so this understates every institution "
               "with a regional window. Countries are harmonised across the ten "
               "sources, since each publishes its own spellings. Totals are a "
               "floor for the coverage reasons in the source note.")
    rcfh.source(fig, as_of=stamp)
    return rcfh.save(fig, OUT_DIR / "02_top_countries.png")


# ------------------------------------------------------------- exhibit 03 --
def sector_mix(conn, stamp):
    """What development finance funds, ramp by RANK."""
    rows = conn.execute(
        f"""SELECT canonical_sector s, SUM(amount_usd) / 1e9 bn FROM projects
            WHERE {WINDOW} AND amount_usd IS NOT NULL AND {OWN_ACCOUNT}
              AND canonical_sector IS NOT NULL
              AND canonical_sector <> 'Unclassified'
            GROUP BY 1 ORDER BY bn DESC""").fetchall()
    labels = [r["s"] for r in rows][::-1]
    values = [r["bn"] for r in rows][::-1]

    fig, ax = rcfh.figure("tracker")
    rcfh.header(fig, "What development finance actually funds",
                dek=f"Disclosed commitments by harmonised sector, "
                    f"{RECENT_FROM}\u2013{RECENT_TO}. The ramp follows the "
                    "ranking.", exhibit="03")
    rcfh.coverage(fig, included=ALL_TEN)
    fig.subplots_adjust(left=0.30)
    ax.barh(range(len(values)), values, color=rcfh.by_rank(values),
            height=0.66, zorder=3)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels)
    ax.set_xlim(0, max(values) * 1.18)
    rcfh.value_labels(ax, values, [money(v) for v in values])
    rcfh.emphasise_row(ax, len(values) - 1)
    rcfh.notes(fig,
               "Each institution publishes its own sector taxonomy; these are "
               "harmonised into fourteen canonical sectors by a reviewed mapping "
               "file, and deals whose source sector is blank are excluded rather "
               "than assigned. A sector total mixes very different instruments, "
               "so read it as where money went, not as what it bought.")
    rcfh.source(fig, as_of=stamp)
    return rcfh.save(fig, OUT_DIR / "03_sector_mix.png")


# ------------------------------------------------------------- exhibit 04 --
def ticket_size(conn, stamp):
    """Average commitment per OPERATION, ramp by RANK."""
    rows = conn.execute(
        f"""SELECT institution i, AVG(v) avg_usd, COUNT(*) n FROM (
              SELECT institution, lower(project_name) nm, {YEAR} y,
                     SUM(amount_usd) v
              FROM projects
              WHERE {WINDOW} AND amount_usd IS NOT NULL AND {OWN_ACCOUNT}
              GROUP BY institution, nm, y)
            GROUP BY 1 HAVING n >= 20 ORDER BY avg_usd DESC""").fetchall()
    labels = [r["i"] for r in rows][::-1]
    values = [r["avg_usd"] / 1e6 for r in rows][::-1]
    shown = {r["i"] for r in rows}

    fig, ax = rcfh.figure("tracker")
    rcfh.header(fig, "Who writes what size cheque",
                dek=f"Average commitment per operation, {RECENT_FROM}\u2013"
                    f"{RECENT_TO}. The spread is what a sponsor chooses between "
                    "when picking a financier.", exhibit="04")
    rcfh.coverage(fig, included=[i for i in ALL_TEN if i in shown],
                  excluded=[i for i in ALL_TEN if i not in shown])
    fig.subplots_adjust(left=0.24)
    ax.barh(range(len(values)), values, color=rcfh.by_rank(values),
            height=0.66, zorder=3)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels)
    ax.set_xlim(0, max(values) * 1.18)
    rcfh.value_labels(ax, values, [f"USD {v:,.0f}M" for v in values])
    rcfh.emphasise_row(ax, len(values) - 1)
    rcfh.notes(fig,
               "Averages run per OPERATION, not per disclosed row. EIB Global "
               "publishes loan tranches and EBRD splits some facilities, so rows "
               "sharing an institution, a name and a year are summed back "
               "together first; averaging the slices understated EIB Global by "
               "27% and EBRD by 17%. Institutions with fewer than 20 operations "
               "in the window are excluded, and an average hides a wide "
               "distribution in both directions.")
    rcfh.source(fig, as_of=stamp)
    return rcfh.save(fig, OUT_DIR / "04_ticket_size.png")


# ------------------------------------------------------------- exhibit 05 --
def cofinancing_pairs(conn, stamp):
    """Institution pairs sharing a flagged deal, ramp by RANK."""
    import collections
    import itertools
    groups = collections.defaultdict(set)
    for r in conn.execute(
            "SELECT probable_duplicate_group g, institution i FROM projects "
            "WHERE probable_duplicate_group IS NOT NULL"):
        groups[r["g"]].add(r["i"])
    pairs = collections.Counter()
    for insts in groups.values():
        for a, b in itertools.combinations(sorted(insts), 2):
            pairs[(a, b)] += 1
    top = pairs.most_common(12)[::-1]
    labels = [f"{a}  +  {b}" for (a, b), _ in top]
    values = [n for _, n in top]

    fig, ax = rcfh.figure("tracker")
    rcfh.header(fig, "Who co-finances with whom",
                dek="Deals appearing in more than one institution's "
                    "disclosures, matched on project name, country and year "
                    "across the full history. The ramp follows the ranking.",
                exhibit="05")
    rcfh.coverage(fig, included=ALL_TEN)
    fig.subplots_adjust(left=0.30)
    ax.barh(range(len(values)), values, color=rcfh.by_rank(values),
            height=0.66, zorder=3)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels)
    ax.set_xlim(0, max(values) * 1.18)
    rcfh.value_labels(ax, values, [f"{v} deals" for v in values])
    rcfh.emphasise_row(ax, len(values) - 1)
    rcfh.notes(fig,
               "These are FUZZY-MATCHED LEADS, not confirmed syndications. "
               "Name matching misses deals the two institutions disclosed under "
               "different names, and can over-group similar names in the same "
               "country and year. Nothing is merged or deleted in the database; "
               "the groups are flags for review. Treat the counts as a floor on "
               "co-financing and never as a count of syndications.")
    rcfh.source(fig, as_of=stamp)
    return rcfh.save(fig, OUT_DIR / "05_cofinancing_pairs.png")


# ------------------------------------------------------------- exhibit 06 --
def thematic_debt(conn, stamp):
    """Labelled debt by institution. The ramp here carries NO ordering."""
    operations = """
        SELECT DISTINCT p.institution inst, lower(p.project_name) nm,
               COALESCE(p.approval_date, '') dt, t.theme, t.labelled_instrument li
        FROM projects p JOIN project_themes t ON t.project_id = p.id
    """
    rows = conn.execute(
        f"SELECT inst, theme, COUNT(*) n FROM ({operations}) GROUP BY 1, 2").fetchall()
    order = [r[0] for r in conn.execute(
        f"SELECT inst FROM ({operations}) GROUP BY inst ORDER BY COUNT(*) DESC")]
    ops, labels_n, bonds, loans = conn.execute(f"""
        SELECT COUNT(DISTINCT inst || '|' || nm || '|' || dt), COUNT(*),
               SUM(CASE WHEN li = 'bond' THEN 1 ELSE 0 END),
               SUM(CASE WHEN li = 'loan' THEN 1 ELSE 0 END)
        FROM ({operations})""").fetchone()

    themes = ["Green", "Sustainability", "Social", "Sustainability-linked",
              "Blue", "Gender"]
    counts = {(r["inst"], r["theme"]): r["n"] for r in rows}
    order = order[::-1]
    cols = rcfh.ramp(len(themes), full=True)

    fig, ax = rcfh.figure("tracker")
    rcfh.header(fig, "Who issues labelled debt",
                dek=f"{labels_n} labels across {ops} operations, by the label "
                    "the issuer itself gave each one.", exhibit="06")
    rcfh.legend(fig, themes, cols)
    rcfh.coverage(fig, included=[i for i in ALL_TEN if i in order],
                  excluded=[i for i in ALL_TEN if i not in order], y=0.735)
    fig.subplots_adjust(left=0.24)
    left = {i: 0 for i in order}
    for ti, theme in enumerate(themes):
        for y, inst in enumerate(order):
            v = counts.get((inst, theme), 0)
            if v:
                ax.barh(y, v, left=left[inst], height=0.66, color=cols[ti],
                        edgecolor=rcfh.GROUND, linewidth=0.8, zorder=3)
                left[inst] += v
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels(order)
    ax.set_xlim(0, max(left.values()) * 1.16)
    rcfh.value_labels(ax, [left[i] for i in order],
                      [f"{left[i]} labels" for i in order])
    rcfh.notes(fig,
               "THE RAMP CARRIES NO ORDERING HERE. Green, social, "
               "sustainability, sustainability-linked, blue and gender have no "
               "natural sequence, so the colour assignment is arbitrary and "
               "depth must not be read as magnitude. Bars count LABELS: one bond "
               f"can be both social and gender. Bonds and loans both count "
               f"({bonds} and {loans}); repeated tranches of one operation are "
               "counted once, which is why EIB Global shows three and not "
               "twenty-nine. Counts are a floor, since they depend on the issuer "
               "using a recognised phrase.")
    rcfh.source(fig, as_of=stamp)
    return rcfh.save(fig, OUT_DIR / "06_thematic_debt.png")


# ------------------------------------------------------------- exhibit 07 --
def mobilisation(conn, stamp):
    """IDB Invest's own capital against what it mobilises."""
    rows = conn.execute(
        """SELECT CAST(substr(approval_date, 1, 4) AS INTEGER) y,
                  SUM(amount_usd) / 1e9 own, SUM(mobilised_usd) / 1e9 mob
           FROM projects WHERE mobilised_usd > 0
             AND approval_date >= '2016-01-01' AND approval_date < '2026-01-01'
           GROUP BY 1 ORDER BY 1""").fetchall()
    own_all, mob_all = conn.execute(
        "SELECT SUM(amount_usd), SUM(mobilised_usd) FROM projects "
        "WHERE mobilised_usd > 0").fetchone()
    years = [r["y"] for r in rows]
    ratio = mob_all / own_all if own_all else 0

    fig, ax = rcfh.figure("tracker")
    # The tracker surface wraps titles at 52 characters. A two-line title
    # pushes the dek down into the legend, so this one stays short.
    rcfh.header(fig, f"Every IDB Invest dollar brings USD {ratio:,.2f} more",
                dek="Own-account commitment and third-party capital mobilised "
                    "alongside it, USD billions per year.", exhibit="07")
    rcfh.legend(fig, ["Own account", "Third-party capital mobilised"],
                [rcfh.TRENCH, rcfh.SHOAL])
    rcfh.coverage(fig, included=["IDB Invest"],
                  excluded=[i for i in ALL_TEN if i != "IDB Invest"], y=0.735)
    w = 0.38
    ax.bar([y - w / 2 for y in years], [r["own"] for r in rows], width=w,
           color=rcfh.TRENCH, zorder=3)
    ax.bar([y + w / 2 for y in years], [r["mob"] for r in rows], width=w,
           color=rcfh.SHOAL, zorder=3)
    ax.grid(False)
    ax.yaxis.grid(True, color=rcfh.FATHOM, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_xticks(years)
    ax.set_ylabel("USD billions")
    rcfh.notes(fig,
               "IDB Invest ONLY. It is the one institution of the ten that "
               "publishes mobilisation per project; IFC reports a cumulative "
               "programme total and EBRD an annual aggregate, and neither can be "
               "mixed with deal-level data. Mobilised capital is never counted as "
               "an institution's own commitment anywhere in this tracker. The "
               "headline ratio is the all-time aggregate; single years run higher, "
               "because 2020 carried an unusually large own-account book.")
    rcfh.source(fig, as_of=stamp)
    return rcfh.save(fig, OUT_DIR / "07_mobilisation.png")


# ------------------------------------------------------------- exhibit 08 --
def instrument_mix(conn, stamp):
    """Instrument family share. The ramp follows the RISK LADDER."""
    excluded = ("EIB Global", "FMO", "BII", "AfDB")
    ph = ",".join("?" * len(excluded))
    rows = conn.execute(f"""
        SELECT p.institution inst, pi.canonical_instrument fam,
               SUM(p.amount_usd) v
        FROM projects p JOIN project_instruments pi ON pi.project_id = p.id
        WHERE {WINDOW} AND p.amount_usd IS NOT NULL
          AND p.institution NOT IN ({ph})
        GROUP BY 1, 2""", excluded).fetchall()

    # The ladder: debt deepest, then guarantee, equity, political risk
    # insurance, technical assistance. Depth carries risk borne, which is why
    # the dek states the ladder rather than leaving the reader to guess.
    ladder = ["Debt", "Guarantee", "Equity", "Political risk insurance",
              "Technical assistance / grant"]
    value = {(r["inst"], r["fam"]): (r["v"] or 0) for r in rows}
    totals = {i: sum(value.get((i, f), 0) for f in ladder)
              for i in {r["inst"] for r in rows}}
    order = sorted(totals, key=lambda i: value.get((i, "Equity"), 0) / totals[i])
    cols = rcfh.ramp(len(ladder), full=True)

    fig, ax = rcfh.figure("tracker")
    rcfh.header(fig, "Who actually takes equity risk",
                dek=f"Share of committed value by instrument family, "
                    f"{RECENT_FROM}\u2013{RECENT_TO}. The ramp follows the risk "
                    "ladder: debt deepest, technical assistance shallowest.",
                exhibit="08")
    rcfh.legend(fig, ["Debt", "Guarantee", "Equity", "Pol. risk ins.", "TA / grant"],
                cols)
    rcfh.coverage(fig, included=order, excluded=list(excluded), y=0.735)
    fig.subplots_adjust(left=0.24)
    for y, inst in enumerate(order):
        left = 0.0
        for fi, fam in enumerate(ladder):
            share = value.get((inst, fam), 0) / totals[inst] * 100
            if share <= 0:
                continue
            ax.barh(y, share, left=left, height=0.66, color=cols[fi],
                    edgecolor=rcfh.GROUND, linewidth=0.8, zorder=3)
            if share >= 7:
                ax.text(left + share / 2, y, f"{share:.0f}%", ha="center",
                        va="center", fontsize=12, fontfamily=rcfh.MONO,
                        color=rcfh.GROUND if fi < 2 else rcfh.INK, zorder=4)
            left += share
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels(order)
    ax.set_xlim(0, 118)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xticklabels(["0", "25%", "50%", "75%", "100%"])
    rcfh.value_labels(ax, [101] * len(order),
                      [money(totals[i] / 1e9) for i in order], pad=0.0)
    rcfh.emphasise_row(ax, len(order) - 1)
    rcfh.notes(fig,
               "Six institutions. EIB Global, FMO and BII publish no instrument "
               "at all. AfDB is excluded for a subtler reason: its only "
               "instrument source is its own IATI feed, which carries three "
               "finance-type codes and no equity code, so charting it would show "
               "0% equity, a blind spot presented as a finding. SENIORITY IS NOT "
               "SHOWN: sources state it on about 2% of debt rows and this tracker "
               "no longer infers it. IDB Invest publishes no instrument on 23% of "
               "its deals, which are excluded from its bar.")
    rcfh.source(fig, as_of=stamp)
    return rcfh.save(fig, OUT_DIR / "08_instrument_mix.png")


# ------------------------------------------------------------- exhibit 09 --
def repeat_clients(conn, stamp):
    """Clients banked by four or more institutions, ramp by RANK."""
    rows = conn.execute("""
        SELECT MIN(counterparty) client, COUNT(DISTINCT institution) dfis,
               COUNT(*) deals, SUM(COALESCE(amount_usd, 0)) v
        FROM projects
        WHERE counterparty_key IS NOT NULL AND counterparty_key <> ''
        GROUP BY counterparty_key HAVING dfis >= 4
        ORDER BY v DESC LIMIT 12""").fetchall()
    shared = conn.execute("""
        SELECT COUNT(*) FROM (SELECT counterparty_key FROM projects
          WHERE counterparty_key IS NOT NULL AND counterparty_key <> ''
          GROUP BY 1 HAVING COUNT(DISTINCT institution) >= 2)""").fetchone()[0]
    rows = rows[::-1]
    labels = [(r["client"][:26] + "\u2026") if len(r["client"]) > 27
              else r["client"] for r in rows]
    values = [r["v"] / 1e6 for r in rows]

    fig, ax = rcfh.figure("tracker")
    rcfh.header(fig, "The clients everybody banks",
                dek=f"{shared} companies have raised from two or more of these "
                    "ten institutions. These twelve are the largest that raised "
                    "from four or more. The ramp follows the ranking.",
                exhibit="09")
    rcfh.coverage(fig, included=[i for i in ALL_TEN
                                 if i not in ("AfDB", "EIB Global")],
                  excluded=["AfDB", "EIB Global"])
    fig.subplots_adjust(left=0.30)
    ax.barh(range(len(values)), values, color=rcfh.by_rank(values),
            height=0.66, zorder=3)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels)
    ax.set_xlim(0, max(values) * 1.28)
    rcfh.value_labels(ax, values,
                      [f"USD {v:,.0f}M \u00b7 {r['dfis']} DFIs"
                       for v, r in zip(values, rows)])
    rcfh.emphasise_row(ax, len(values) - 1)
    rcfh.notes(fig,
               "Names appear exactly as disclosed. Client names are DERIVED "
               "where an institution publishes no client field, by cleaning the "
               "project name; AfDB and EIB Global are excluded by design, because "
               "their name fields hold project and asset names rather than "
               "clients. Matching is exact on a normalised name and never fuzzy, "
               "since a missed link is safer than an invented one, so every count "
               "here is a FLOOR.")
    rcfh.source(fig, as_of=stamp)
    return rcfh.save(fig, OUT_DIR / "09_repeat_clients.png")


# ---------------------------------------------------------- macro series --
MACRO_PATH = Path(__file__).parent / "macro_series.csv"


def macro():
    """macro_series.csv as {(iso3, indicator): {year: value}}, plus lookups.

    Read from the CSV, never from the API, so a render stays reproducible and
    works offline. Regenerate with update_macro_series.py.
    """
    series, groups, names = {}, {}, {}
    if not MACRO_PATH.exists():
        raise FileNotFoundError(
            f"{MACRO_PATH.name} missing. Run: python update_macro_series.py")
    with MACRO_PATH.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            key = (row["iso3"], row["indicator"])
            series.setdefault(key, {})[int(row["year"])] = float(row["value"])
            if row["income_group"]:
                groups[row["iso3"]] = row["income_group"]
            names[row["iso3"]] = row["name"]
    return series, groups, names


def commitments_by_year(conn):
    """Own-account committed value per year, USD. The numerator both new
    exhibits divide."""
    return dict(conn.execute(
        f"""SELECT {YEAR}, SUM(amount_usd) FROM projects
            WHERE {WINDOW} AND amount_usd IS NOT NULL AND {OWN_ACCOUNT}
            GROUP BY 1""").fetchall())


def dodge_labels(fig, texts, markers=(), pad=2.5, radius=9.0, rounds=120,
                 leader=30.0):
    """Nudge annotation labels apart until their boxes stop overlapping.

    Scatter labels collide wherever the data clusters, and a hand-tuned offset
    table rots the moment the underlying figures change. This resolves them
    from the rendered text extents instead, so the exhibit stays correct after
    a refresh. Labels carry offsets in points, which is what set_position moves
    for an annotation built with textcoords="offset points".

    ``markers`` are the plotted points in data coordinates. A text-against-text
    pass alone will happily park one country's label on another country's dot,
    so each label also clears every marker except its own. Lift is capped at
    one marker height per round, because an uncapped push compounds across
    rounds and walks the labels off the canvas.

    A label pushed more than ``leader`` pixels clear of its own point gets a
    hairline back to it. Without one, a dense cluster reads as a set of labels
    floating above an unrelated set of dots.
    """
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    to_points = 72.0 / fig.dpi
    if len(markers):
        markers = texts[0].axes.transData.transform(markers)
    for _ in range(rounds):
        boxes = [t.get_window_extent(renderer) for t in texts]
        moved = False
        for i, box in enumerate(boxes):
            for j, (mx, my) in enumerate(markers):
                if i == j:
                    continue
                if not (box.x0 - radius < mx < box.x1 + radius
                        and box.y0 - radius < my < box.y1 + radius):
                    continue
                moved = True
                lift = min(my + radius - box.y0 + pad, 2 * radius) * to_points
                x, y = texts[i].get_position()
                texts[i].set_position((x, y + lift))
                boxes[i] = box = texts[i].get_window_extent(renderer)
        for i in range(len(texts)):
            for j in range(i + 1, len(texts)):
                a, b = boxes[i], boxes[j]
                if not a.overlaps(b):
                    continue
                moved = True
                shift = ((min(a.y1, b.y1) - max(a.y0, b.y0)) / 2 + pad) * to_points
                lo, hi = (i, j) if a.y0 <= b.y0 else (j, i)
                for idx, step in ((lo, -shift), (hi, shift)):
                    x, y = texts[idx].get_position()
                    texts[idx].set_position((x, y + step))
                boxes[lo] = texts[lo].get_window_extent(renderer)
                boxes[hi] = texts[hi].get_window_extent(renderer)
        if not moved:
            break
        fig.canvas.draw()

    if not len(markers):
        return
    axes = texts[0].axes
    inverse = axes.transData.inverted()
    for text, (mx, my) in zip(texts, markers):
        box = text.get_window_extent(renderer)
        anchor = ((box.x0 + box.x1) / 2, box.y0 - 1.5)
        if abs(anchor[1] - my) <= leader:
            continue
        (x0, y0), (x1, y1) = inverse.transform([(mx, my), anchor])
        axes.plot([x0, x1], [y0, y1], color=rcfh.FATHOM, linewidth=0.8,
                  zorder=2, solid_capstyle="butt")


# ------------------------------------------------------------- exhibit 10 --
def commitments_against_gdp(conn, stamp):
    """Commitments as basis points of GDP, two panels, ramp by GROUP.

    Two stacked panels rather than two lines on one axis. The denominators
    differ in size, so a shared scale would invite a comparison of heights
    that means nothing: low- and middle-income GDP runs to roughly half
    high-income GNI, which lifts the recipient line mechanically. Separate
    panels keep both levels readable and compare only the shapes, which is
    the question the exhibit asks.

    No deflator anywhere. Commitments and both denominators arrive as current
    USD, so the ratio needs no price index. Deflating commitments by US CPI
    and setting them against a global output series reverses the finding,
    which is the trap this exhibit exists to avoid.
    """
    series, _, _ = macro()
    dfi = commitments_by_year(conn)
    years = sorted(dfi)

    lmic_gdp = series[("LMY", "NY.GDP.MKTP.CD")]
    hic_gni = series[("HIC", "NY.GNP.MKTP.CD")]
    recipient = [1e4 * dfi[y] / lmic_gdp[y] for y in years]
    funder = [1e4 * dfi[y] / hic_gni[y] for y in years]

    lmic_real = series[("LMY", "NY.GDP.MKTP.KD")]
    hic_real = series[("HIC", "NY.GDP.MKTP.KD")]
    lmic_growth = 100 * (lmic_real[years[-1]] / lmic_real[years[0]] - 1)
    hic_growth = 100 * (hic_real[years[-1]] / hic_real[years[0]] - 1)
    nominal = 100 * (dfi[years[-1]] / dfi[years[0]] - 1)

    fig, ax = rcfh.figure("tracker", height=13.5)
    rcfh.header(fig, "Development finance has not kept pace with the "
                     "economies it serves",
                dek=f"Commitments of ten institutions as basis points of GDP, "
                    f"{RECENT_FROM}\u2013{RECENT_TO}. Both panels divide current "
                    "USD by current USD, so neither side is deflated.",
                exhibit="10")
    rcfh.coverage(fig, included=ALL_TEN, y=0.760)

    colors, _ = rcfh.by_group(["recipient", "funder"])
    fig.subplots_adjust(bottom=0.410)
    box = ax.get_position()
    ax.remove()
    gap = 0.075
    h = (box.height - gap) / 2
    upper = fig.add_axes([box.x0, box.y0 + h + gap, box.width, h])
    lower = fig.add_axes([box.x0, box.y0, box.width, h])

    panels = [
        (upper, recipient, colors[0],
         "Per unit of RECIPIENT output \u2014 basis points of low- and "
         "middle-income GDP"),
        (lower, funder, colors[1],
         "Per unit of FUNDER income \u2014 basis points of high-income GNI"),
    ]
    for axis, values, color, label in panels:
        axis.plot(years, values, color=color, linewidth=2.4, zorder=3,
                  marker="o", markersize=5, markerfacecolor=color,
                  markeredgecolor=rcfh.GROUND, markeredgewidth=1.2)
        axis.grid(False)
        axis.yaxis.grid(True, color=rcfh.FATHOM, linewidth=0.8)
        axis.set_axisbelow(True)
        axis.set_xticks(years)
        axis.set_xlim(years[0] - 0.4, years[-1] + 0.4)
        lo, hi = min(values), max(values)
        axis.set_ylim(lo - (hi - lo) * 0.55, hi + (hi - lo) * 0.45)
        axis.set_ylabel("basis points")
        axis.text(0.0, 1.07, label, transform=axis.transAxes,
                  color=rcfh.SOUNDING, fontsize=11, fontfamily=rcfh.BODY,
                  va="bottom")
        for x, v in ((years[0], values[0]), (years[-1], values[-1])):
            axis.annotate(f"{v:.1f}", (x, v), textcoords="offset points",
                          xytext=(0, 12), ha="center", color=rcfh.SOUNDING,
                          fontsize=12, fontfamily=rcfh.MONO)
        trough = min(range(len(values)), key=lambda i: values[i])
        axis.annotate(f"{values[trough]:.1f}", (years[trough], values[trough]),
                      textcoords="offset points", xytext=(0, -20),
                      ha="center", color=rcfh.BRASS, fontsize=12,
                      fontfamily=rcfh.MONO)
    upper.set_xticklabels([])

    rcfh.notes(fig,
               "Ratios divide disclosed commitments by World Bank national "
               "accounts, both in current USD, so no price index enters and the "
               "finding does not turn on a choice of deflator. Commitments are a "
               "FLOOR: coverage differs by institution, EIB Global counts loan "
               "tranches rather than whole projects, Proparco covers only "
               "disclosure-consented deals signed since 2014, and FMO is its own "
               "account only. The weakest year on each panel is marked in brass. "
               f"Over the same window low- and middle-income real GDP grew "
               f"{lmic_growth:.0f} per cent and high-income real GDP "
               f"{hic_growth:.0f} per cent, against nominal commitments up "
               f"{nominal:.0f} per cent. The funder panel measures balance-sheet "
               "deployment rather than aid: these institutions lend on "
               "non-concessional terms off leveraged capital, so it is not a read "
               "on generosity, and not a read on ODA, which is a separate series "
               "moving separately. The panels carry separate scales, because "
               "low- and middle-income GDP runs to roughly half high-income GNI "
               "and a shared axis would lift the upper line mechanically; "
               "compare the shapes, not the heights.", y=0.330)
    rcfh.source(fig, text=rcfh.TRACKER_SOURCE + " Denominators: World Bank World "
                          "Development Indicators, series NY.GDP.MKTP.CD, "
                          "NY.GNP.MKTP.CD and NY.GDP.MKTP.KD.",
                as_of=stamp)
    return rcfh.save(fig, OUT_DIR / "10_commitments_against_gdp.png")


# ------------------------------------------------------------- exhibit 11 --
def growth_decomposition(conn, stamp):
    """IFC, DFC and the other eight, ramp by CONTRIBUTION to the decade.

    Exhibit 10 shows the aggregate going nowhere against its denominators.
    This one says who moved and who did not, which is the question exhibit 10
    provokes and cannot answer.

    Three series rather than ten. The palette carries five stops and ten lines
    on one axis is a spaghetti chart; the split that matters is two risers
    against a flat remainder, so the remainder travels as one line and the
    institutional detail lives in exhibits 02 and 09.

    ON THE BRASS RULES
    They mark authorising events, not a demonstrated cause. Both institutions
    ramp after their own authority expanded, and IFC's trajectory tracks a
    published target rather than merely coinciding with a date. That is timing
    consistency and a stated intention, which is as far as this data reaches,
    and the note says so rather than letting two vertical lines imply a
    regression nobody ran.
    """
    rows = conn.execute(
        f"""SELECT {YEAR} y, institution i, SUM(amount_usd) / 1e9 bn
            FROM projects
            WHERE {WINDOW} AND amount_usd IS NOT NULL AND {OWN_ACCOUNT}
            GROUP BY 1, 2""").fetchall()
    years = sorted({r["y"] for r in rows})
    OTHER = "The other eight"
    totals = {(y, k): 0.0 for y in years for k in ("IFC", "DFC", OTHER)}
    for r in rows:
        totals[(r["y"], r["i"] if r["i"] in ("IFC", "DFC") else OTHER)] += r["bn"]

    order = ["IFC", "DFC", OTHER]
    colors, labels = rcfh.by_group(order, order=order)
    lift = {k: 100 * (totals[(years[-1], k)] / totals[(years[0], k)] - 1)
            for k in order}

    fig, ax = rcfh.figure("tracker", height=13.5)
    rcfh.header(fig, "Strip out IFC and DFC and the decade is flat",
                dek=f"Own-account commitments, {RECENT_FROM}\u2013{RECENT_TO}, "
                    f"USD billions. The ramp runs by contribution to the "
                    f"decade's growth, deepest on the largest riser.",
                exhibit="11")
    rcfh.coverage(fig, included=ALL_TEN)
    # Trailing pad for the same reason SHORT_GROUP carries it: the legend row
    # is sized from a sans-width estimate and the house body face is a serif.
    rcfh.legend(fig, [f"{lab}   " for lab in labels], colors=colors, y=0.735)
    fig.subplots_adjust(bottom=0.420)

    for key, color in zip(order, colors):
        values = [totals[(y, key)] for y in years]
        ax.plot(years, values, color=color, linewidth=2.4, zorder=3,
                marker="o", markersize=5, markerfacecolor=color,
                markeredgecolor=rcfh.GROUND, markeredgewidth=1.2)
        ax.annotate(f"{values[-1]:,.0f}", (years[-1], values[-1]),
                    textcoords="offset points", xytext=(13, -4), ha="left",
                    color=color, fontsize=13, fontfamily=rcfh.MONO, zorder=4)

    ax.grid(False)
    ax.yaxis.grid(True, color=rcfh.FATHOM, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_xticks(years)
    ax.set_xlim(years[0] - 0.3, years[-1] + 0.9)
    ax.set_ylim(0, 46)
    ax.set_ylabel("USD billions committed")

    # Fractional years, because both events land mid-year and snapping them to
    # a gridline would put the BUILD Act in the wrong DFC reporting year.
    for x, text in ((2018.79, "BUILD Act, October 2018"),
                    (2020.29, "IFC capital increase, April 2020")):
        ax.axvline(x, color=rcfh.BRASS, linewidth=1.1, zorder=2)
        ax.text(x + 0.10, 45.2, text, color=rcfh.BRASS, fontsize=10,
                fontfamily=rcfh.MONO, rotation=90, ha="left", va="top",
                zorder=4)

    rcfh.notes(fig,
               f"IFC rose {lift['IFC']:.0f} per cent over the window and DFC "
               f"{lift['DFC']:.0f} per cent, against {lift[OTHER]:.0f} per cent "
               "for the remaining eight combined, which US consumer prices alone "
               "turn into a real-terms decline. Together IFC and DFC account for "
               "93 per cent of the net rise; AfDB and ADB fell in nominal terms. "
               "The brass rules mark authorising events, NOT a demonstrated "
               "cause: the BUILD Act raised DFC's exposure cap from USD 29bn to "
               "USD 60bn and the corporation stood up in December 2019, while "
               "IFC's USD 5.5bn paid-in capital increase, endorsed in 2018, "
               "became effective in April 2020 carrying a published target to "
               "double annual investment to USD 48bn by 2030. DFC publishes no "
               "approval dates, so its years are US federal fiscal years running "
               "October to September, which places the BUILD Act at the opening "
               "of its 2019. IFC's 2022 step carries two one-off global "
               "supply-chain finance facilities worth USD 6.2bn between them; "
               "excluding every trade-finance facility, IFC still grows 2.5 "
               "times over the window, so the trend survives but that single "
               "year is inflated. Commitments are a FLOOR on the coverage terms "
               "stated across this series, and FMO is its own account only.",
               y=0.330)
    rcfh.source(fig, as_of=stamp)
    return rcfh.save(fig, OUT_DIR / "11_growth_decomposition.png")


# ------------------------------------------------------------- exhibit 12 --
def allocation_against_intensity(conn, stamp):
    """Dollars received against share of national investment, ramp by INCOME.

    The ramp runs down the income ladder, deepest on low income, so depth
    carries development need rather than restating either axis. Gross fixed
    capital formation is the denominator rather than GDP because these
    commitments are investment, and the comparison a reader wants is against
    the capital a country already forms.

    Deliberately NOT a growth chart. Commitments run to a fraction of one per
    cent of investment in the largest recipients, which forecloses any causal
    read on national growth; across this set the correlation between intensity
    and real growth is -0.06.

    Nor does it argue that volume and intensity trade off against each other.
    That correlation is -0.17 across nineteen recipients, too weak to carry a
    title, and Egypt and Morocco sit high on both axes. What the exhibit shows
    is the spread: dollars vary sixfold, weight in the national investment
    base varies by nearly three orders of magnitude, so a league table ranked
    on dollars says almost nothing about where the money lands hardest.
    """
    series, groups, names = macro()
    rows = conn.execute(
        f"""SELECT canonical_country cc, SUM(amount_usd) usd FROM projects
            WHERE {WINDOW} AND amount_usd IS NOT NULL AND {OWN_ACCOUNT}
              AND canonical_country IS NOT NULL
            GROUP BY 1""").fetchall()
    by_name = {r["cc"]: r["usd"] for r in rows}
    iso_of = {v: k for k, v in names.items() if v != k}

    pts, dropped = [], []
    for name, iso in iso_of.items():
        usd = by_name.get(name)
        if usd is None:
            continue
        gfcf = series.get((iso, "NE.GDI.FTOT.CD"), {})
        cum = sum(gfcf.get(y, 0) for y in range(RECENT_FROM, RECENT_TO + 1))
        if not cum:
            dropped.append(name)
            continue
        pts.append((name, usd / 1e9, 100 * usd / cum, groups.get(iso, "")))

    order = ["Low income", "Lower middle income", "Upper middle income",
             "High income"]
    order = [g for g in order if any(p[3] == g for p in pts)]
    pts.sort(key=lambda p: order.index(p[3]))
    colors, labels = rcfh.by_group([p[3] for p in pts], order=order)
    key = {}
    for point, color in zip(pts, colors):
        key.setdefault(point[3], color)

    vol_spread = max(p[1] for p in pts) / min(p[1] for p in pts)
    int_spread = max(p[2] for p in pts) / min(p[2] for p in pts)

    fig, ax = rcfh.figure("tracker", height=13.5)
    rcfh.header(fig, "A recipient league table hides how much the money matters",
                dek=f"Single-country recipients above USD 6bn, {RECENT_FROM}"
                    f"\u2013{RECENT_TO}. Commitments vary {vol_spread:.0f}-fold "
                    f"across them; their weight in the national investment base "
                    f"varies {int_spread:.0f}-fold.",
                exhibit="12")
    rcfh.coverage(fig, included=ALL_TEN, y=0.760)
    rcfh.legend(fig, [SHORT_GROUP[g] for g in labels],
                colors=[key[g] for g in labels], y=0.694)
    fig.subplots_adjust(bottom=0.420)

    tags = []
    for (name, bn, share, _), color in zip(pts, colors):
        ax.scatter(share, bn, s=190, color=color, zorder=3,
                   edgecolor=rcfh.GROUND, linewidth=1.3)
        tags.append(ax.annotate(
            name, (share, bn), textcoords="offset points", xytext=(0, 13),
            ha="center", color=rcfh.INK, fontsize=11, fontfamily=rcfh.BODY,
            zorder=4))
    ax.set_xscale("log")
    ax.grid(False)
    ax.yaxis.grid(True, color=rcfh.FATHOM, linewidth=0.8)
    ax.xaxis.grid(True, color=rcfh.FATHOM, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_xlim(0.013, 40)
    ax.set_ylim(-2.5, max(p[1] for p in pts) * 1.30)
    ax.set_xticks([0.02, 0.1, 0.5, 2, 10])
    ax.set_xticklabels(["0.02%", "0.1%", "0.5%", "2%", "10%"])
    ax.set_xlabel("Commitments as a share of the country's gross fixed capital "
                  "formation (log scale)")
    ax.set_ylabel("USD billions committed")
    dodge_labels(fig, tags, markers=[(p[2], p[1]) for p in pts])

    missing = (f"{', '.join(dropped)} clears the threshold but the World Bank "
               "publishes no capital formation series for it over this window, "
               "so it does not appear. ") if dropped else ""
    rcfh.notes(fig,
               "Commitments are cumulative over the window and the denominator "
               "is cumulative gross fixed capital formation over the same years, "
               "World Bank series NE.GDI.FTOT.CD in current USD. Regional and "
               "multi-country rows carry no national denominator and are excluded "
               "by construction, so this exhibit covers single-country flows "
               "only. " + missing +
               "Read this as an allocation chart, not a growth chart: at these "
               "shares commitments cannot move a national growth rate, and across "
               "this set the correlation between intensity and real GDP growth is "
               "-0.06. Income groups follow the World Bank classification and the "
               "legend abbreviates them: low, lower middle, upper middle and "
               "high income. "
               "Commitments are a FLOOR on the coverage terms stated across this "
               "series. Volume and intensity do not trade off cleanly against "
               "each other either: that correlation is -0.17, and Egypt and "
               "Morocco rank high on both. The claim here is about the spread, "
               "not about a slope.", y=0.330)
    rcfh.source(fig, text=rcfh.TRACKER_SOURCE + " Denominators and income "
                          "classification: World Bank World Development "
                          "Indicators.",
                as_of=stamp)
    return rcfh.save(fig, OUT_DIR / "12_allocation_against_intensity.png")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    conn = connect()
    stamp = as_of(conn)
    n = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    print(f"Rendering Bathymetric exhibits from {n:,} records "
          f"(data as of {stamp})")
    for fn in (commitments_over_time, top_countries, sector_mix, ticket_size,
               cofinancing_pairs, thematic_debt, mobilisation, instrument_mix,
               repeat_clients, commitments_against_gdp,
               growth_decomposition, allocation_against_intensity):
        path = fn(conn, stamp)
        print(f"  wrote {Path(path).name if path else fn.__name__}")
    conn.close()
    print(f"Done \u2014 {OUT_DIR}")


if __name__ == "__main__":
    main()
