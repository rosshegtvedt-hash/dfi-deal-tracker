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


# ------------------------------------------------- infrastructure series --
# Exhibits 13 to 16 read the infrastructure book. Two conventions hold across
# all four:
#
#   * INFRA is the harmonised canonical sector, never a source label. Each
#     institution publishes its own taxonomy and the mapping file does the
#     reconciliation, so "Infrastructure" here means the same thing in ten
#     books that spell it ten ways.
#   * Anything counting or averaging DEALS runs on OPERATIONS, per the rule at
#     the top of this file. Exhibit 14 would be wrong by a wide margin
#     otherwise: EIB Global discloses loan tranches, so a port financed in six
#     parts would enter a ticket-size distribution as six small cheques.
INFRA = "Infrastructure"

INFRA_SUBSECTORS = ["Transport & Logistics", "Energy & Utilities",
                    "Water & Sanitation", "Municipal & Environmental"]

# One operation per (institution, name, year, sector), summed back from the
# rows the sources publish. Adding the sector columns to exhibit 04's key
# splits the 199 operations whose rows carry more than one canonical sector
# and the 76 that carry more than one subsector, out of 12,546. That is
# tolerable where the exhibit SUMS value, which a regrouping cannot change,
# and intolerable where it counts or averages deals, so exhibit 14 uses the
# unmodified house key instead.
OPERATIONS = f"""
    SELECT institution, lower(project_name) nm, {YEAR} y,
           canonical_sector sector, canonical_subsector subsector,
           MAX(sovereign_exposure) sovereign, SUM(amount_usd) v
    FROM projects
    WHERE {WINDOW} AND {OWN_ACCOUNT}
    GROUP BY institution, nm, y, sector, subsector
"""

# Exhibit 04's key, unmodified. An operation joins a subsector's distribution
# when any of its rows carries that subsector, so the 76 spanning two appear
# in both; the alternative assigns a cheque to one subsector by a tiebreak
# nobody published.
HOUSE_KEY = f"institution, lower(project_name), {YEAR}"

# The two institutions that produced 93 per cent of the decade's growth
# (exhibit 11). Exhibit 13 exists because both are infrastructure-light, so
# their expansion moves the sector's SHARE without anyone committing less.
GROWTH_PAIR = ("IFC", "DFC")


def percentile(sorted_values, q):
    """Nearest-rank percentile. No interpolation: these are cheque sizes, and
    an interpolated value would name an amount nobody committed."""
    if not sorted_values:
        return 0.0
    return sorted_values[min(int(q * len(sorted_values)), len(sorted_values) - 1)]


# ------------------------------------------------------------- exhibit 13 --
def infrastructure_share(conn, stamp):
    """Infrastructure's share of commitments, whole panel against the eight.

    Grouped by a real attribute rather than ramped by sequence, because the
    finding IS the grouping: the two series diverge, and colour should carry
    which panel a line belongs to.
    """
    rows = conn.execute(
        f"""SELECT {YEAR} y,
                   SUM(CASE WHEN canonical_sector = ? THEN amount_usd ELSE 0 END) infra,
                   SUM(amount_usd) total,
                   SUM(CASE WHEN canonical_sector = ? AND institution NOT IN (?, ?)
                            THEN amount_usd ELSE 0 END) infra_eight,
                   SUM(CASE WHEN institution NOT IN (?, ?)
                            THEN amount_usd ELSE 0 END) total_eight
            FROM projects
            WHERE {WINDOW} AND amount_usd IS NOT NULL AND {OWN_ACCOUNT}
            GROUP BY 1 ORDER BY 1""",
        (INFRA, INFRA, *GROWTH_PAIR, *GROWTH_PAIR)).fetchall()
    years = [r["y"] for r in rows]
    all_ten = [100 * r["infra"] / r["total"] for r in rows]
    eight = [100 * r["infra_eight"] / r["total_eight"] for r in rows]

    # The levels the note quotes, so the exhibit cannot drift from its caption.
    lvl = conn.execute(
        f"""SELECT SUM(CASE WHEN {YEAR} = ? THEN amount_usd ELSE 0 END) / 1e9 first,
                   SUM(CASE WHEN {YEAR} = ? THEN amount_usd ELSE 0 END) / 1e9 last
            FROM projects
            WHERE {WINDOW} AND amount_usd IS NOT NULL AND {OWN_ACCOUNT}
              AND canonical_sector = ? AND institution NOT IN (?, ?)""",
        (RECENT_FROM, RECENT_TO, INFRA, *GROWTH_PAIR)).fetchone()
    rise = 100 * (lvl["last"] / lvl["first"] - 1)

    order = ["All ten institutions", "Excluding IFC and DFC"]
    colors, labels = rcfh.by_group(order, order=order)

    fig, ax = rcfh.figure("tracker", height=12.5)
    rcfh.header(fig, "Composition explains infrastructure's flat share",
                dek=f"Infrastructure as a share of own-account commitments, "
                    f"{RECENT_FROM}–{RECENT_TO}. Colour carries which "
                    "panel of institutions a line describes.", exhibit="13")
    rcfh.coverage(fig, included=ALL_TEN)
    rcfh.legend(fig, [f"{lab}   " for lab in labels], colors=colors, y=0.735)
    fig.subplots_adjust(bottom=0.395)

    for series, color in ((all_ten, colors[0]), (eight, colors[1])):
        ax.plot(years, series, color=color, linewidth=2.4, zorder=3,
                marker="o", markersize=5, markerfacecolor=color,
                markeredgecolor=rcfh.GROUND, markeredgewidth=1.2)
        ax.annotate(f"{series[-1]:.0f}%", (years[-1], series[-1]),
                    textcoords="offset points", xytext=(13, -4), ha="left",
                    color=color, fontsize=13, fontfamily=rcfh.MONO, zorder=4)

    ax.grid(False)
    ax.yaxis.grid(True, color=rcfh.FATHOM, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_xticks(years)
    ax.set_xlim(years[0] - 0.3, years[-1] + 0.9)
    ax.set_ylim(0, 55)
    ax.set_ylabel("Infrastructure share of commitments, per cent")

    rcfh.notes(
        fig,
        f"The gap between the lines carries the finding. Infrastructure "
        f"commitments ROSE over the window at nine of the ten institutions; "
        f"the eight outside "
        f"IFC and DFC took theirs from USD {lvl['first']:,.1f}bn to USD "
        f"{lvl['last']:,.1f}bn, a rise of {rise:.0f} per cent, on a book that "
        "grew 5 per cent. Their infrastructure share therefore climbs. The "
        "whole-panel line stays flat because IFC and DFC tripled over the same "
        "decade and both run infrastructure-light books, so the sector's share "
        "falls arithmetically while no institution retreats from it. Exhibit 11 "
        "carries that growth decomposition. Two smaller cautions: 2022 is "
        "further depressed by two one-off IFC supply-chain finance facilities "
        "worth USD 6.2bn, which lift the denominator alone, and DFC publishes "
        "no approval dates, so its years are US federal fiscal years. Sectors "
        "are harmonised from ten source taxonomies and deals with no source "
        "sector are excluded rather than assigned.", y=0.305)
    rcfh.source(fig, as_of=stamp)
    return rcfh.save(fig, OUT_DIR / "13_infrastructure_share.png")


# ------------------------------------------------------------- exhibit 14 --
def infrastructure_ticket_size(conn, stamp):
    """Cheque-size distribution by infrastructure subsector, ramp by RANK.

    Plots the MEDIAN, because the mean is the wrong statistic here and saying
    so is most of the point: infrastructure's distribution is long-tailed to
    the right, so its mean sits near the 70th percentile and describes almost
    nobody's deal.
    """
    def spread(where, params=()):
        values = sorted(r[0] for r in conn.execute(
            f"""SELECT SUM(amount_usd) v FROM projects
                WHERE {WINDOW} AND {OWN_ACCOUNT} AND {where}
                GROUP BY {HOUSE_KEY} HAVING v IS NOT NULL AND v > 0""", params))
        return dict(n=len(values),
                    p25=percentile(values, 0.25) / 1e6,
                    median=percentile(values, 0.50) / 1e6,
                    p75=percentile(values, 0.75) / 1e6,
                    mean=(sum(values) / len(values) / 1e6) if values else 0.0)

    rows = [(s, spread("canonical_sector = ? AND canonical_subsector = ?",
                       (INFRA, s))) for s in INFRA_SUBSECTORS]
    rows.append(("All infrastructure", spread("canonical_sector = ?", (INFRA,))))
    rows.append(("All other sectors", spread("canonical_sector <> ?", (INFRA,))))
    rows.sort(key=lambda kv: kv[1]["median"])

    labels = [k for k, _ in rows]
    medians = [v["median"] for _, v in rows]
    infra = dict(rows)["All infrastructure"]

    fig, ax = rcfh.figure("tracker", height=12.0)
    # The headline number is read off the same computation the bars use, so a
    # data refresh can never leave the title contradicting the chart.
    rcfh.header(fig, f"Half of infrastructure deals fall under USD "
                     f"{infra['median']:,.0f}m",
                dek=f"Committed value per operation, {RECENT_FROM}–"
                    f"{RECENT_TO}. Bars are medians and the ramp follows them; "
                    "the rule spans the middle half of each distribution.",
                exhibit="14")
    rcfh.coverage(fig, included=ALL_TEN)
    fig.subplots_adjust(left=0.295, bottom=0.400)

    ax.barh(range(len(medians)), medians, color=rcfh.by_rank(medians),
            height=0.52, zorder=3)
    for i, (_, v) in enumerate(rows):
        # Interquartile rule and mean marker in Sounding: they carry the
        # distribution, and brass is reserved for the emphasised row.
        ax.plot([v["p25"], v["p75"]], [i + 0.36, i + 0.36],
                color=rcfh.SOUNDING, linewidth=1.4, zorder=4,
                solid_capstyle="butt")
        for x in (v["p25"], v["p75"]):
            ax.plot([x, x], [i + 0.28, i + 0.44], color=rcfh.SOUNDING,
                    linewidth=1.4, zorder=4)
        # Below the bar, not level with it: the median label occupies the row
        # centre and the two collide on the shortest bar.
        ax.plot([v["mean"]], [i - 0.36], marker="D", markersize=6,
                markerfacecolor=rcfh.GROUND, markeredgecolor=rcfh.SOUNDING,
                markeredgewidth=1.4, zorder=5)

    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels)
    ax.set_xlim(0, max(v["p75"] for _, v in rows) * 1.20)
    ax.set_xlabel("USD millions per operation")
    rcfh.value_labels(ax, medians, [f"USD {m:,.0f}M" for m in medians])
    # The title quotes the all-infrastructure median, so brass marks that row
    # rather than the tallest bar.
    rcfh.emphasise_row(ax, labels.index("All infrastructure"))

    transport = dict(rows)["Transport & Logistics"]
    municipal = dict(rows)["Municipal & Environmental"]
    rcfh.notes(
        fig,
        f"The diamond marks the MEAN. Infrastructure's mean commitment reaches "
        f"USD {infra['mean']:,.0f}m against a median of USD "
        f"{infra['median']:,.0f}m, because a handful of very large operations "
        f"pull it upward; the mean sits above roughly seven deals in ten and "
        f"describes almost none of them. The subsector spread matters more "
        f"than either statistic: a transport sponsor and a municipal one "
        f"choose between different markets, at USD "
        f"{transport['median']:,.0f}m against USD {municipal['median']:,.0f}m "
        f"at the median. Figures run per OPERATION, not per disclosed row, so "
        "the loan tranches EIB Global publishes and the facilities EBRD splits "
        "are summed back into one cheque first; skipping that step understated "
        "the largest tickets by roughly a quarter. Percentiles are "
        "nearest-rank, never interpolated, so every figure names an amount "
        "somebody committed. An operation whose rows carry two subsectors "
        "enters both distributions, which affects 76 of 12,546. Deals with no "
        "disclosed amount are excluded rather than imputed.", y=0.310)
    rcfh.source(fig, as_of=stamp)
    return rcfh.save(fig, OUT_DIR / "14_infrastructure_ticket_size.png")


# ------------------------------------------------------------- exhibit 15 --
def infrastructure_es_risk(conn, stamp):
    """High E&S grades, infrastructure against the rest of the same book.

    Grouped rather than ranked: the comparison is the finding, and each
    institution is its own control. Cross-institution levels are NOT
    comparable here (the scales differ), which is exactly why the exhibit
    holds each bank against itself.
    """
    rows = conn.execute(
        f"""SELECT institution i,
               SUM(CASE WHEN canonical_sector = ? THEN 1 ELSE 0 END) n_infra,
               100.0 * SUM(CASE WHEN canonical_sector = ?
                    AND canonical_es_category = 'High' THEN 1 ELSE 0 END)
                    / NULLIF(SUM(CASE WHEN canonical_sector = ? THEN 1 ELSE 0 END), 0) hi_infra,
               SUM(CASE WHEN canonical_sector <> ? THEN 1 ELSE 0 END) n_rest,
               100.0 * SUM(CASE WHEN canonical_sector <> ?
                    AND canonical_es_category = 'High' THEN 1 ELSE 0 END)
                    / NULLIF(SUM(CASE WHEN canonical_sector <> ? THEN 1 ELSE 0 END), 0) hi_rest
            FROM projects
            WHERE canonical_es_category IS NOT NULL AND {WINDOW} AND {OWN_ACCOUNT}
            GROUP BY 1 HAVING n_infra >= 20""", (INFRA,) * 6).fetchall()
    # Ordered by the RATIO rather than the level, because the levels are not
    # comparable across institutions and the ratio is what the title claims.
    rows = sorted(rows, key=lambda r: r["hi_infra"] / max(r["hi_rest"], 0.01))
    labels = [r["i"] for r in rows]
    infra = [r["hi_infra"] for r in rows]
    rest = [r["hi_rest"] for r in rows]
    shown = {r["i"] for r in rows}
    top = rows[-1]

    order = ["Infrastructure", "Everything else"]
    colors, keys = rcfh.by_group(order, order=order)

    fig, ax = rcfh.figure("tracker", height=12.0)
    rcfh.header(fig, "Infrastructure concentrates the high-risk grades",
                dek=f"Share of operations graded highest environmental and "
                    f"social risk, {RECENT_FROM}–{RECENT_TO}, each "
                    "institution against its own book, ordered by the "
                    "multiple between the two.", exhibit="15")
    # Coverage first at its default row, legend below it. Both helpers set the
    # axes top and the LAST call wins, so reversing these two lines drops the
    # plot straight onto the coverage chips.
    rcfh.coverage(fig, included=[i for i in ALL_TEN if i in shown],
                  excluded=[i for i in ALL_TEN if i not in shown])
    rcfh.legend(fig, [f"{lab}   " for lab in keys], colors=colors, y=0.735)
    fig.subplots_adjust(left=0.255, bottom=0.400)

    h = 0.34
    idx = range(len(labels))
    ax.barh([i + h / 2 for i in idx], infra, height=h, color=colors[0], zorder=3)
    ax.barh([i - h / 2 for i in idx], rest, height=h, color=colors[1], zorder=3)
    ax.set_yticks(list(idx))
    ax.set_yticklabels(labels)
    limit = max(infra) * 1.42
    ax.set_xlim(0, limit)
    ax.set_xlabel("Operations graded highest risk, per cent")
    for i, (a, b) in enumerate(zip(infra, rest)):
        ax.text(a + max(infra) * 0.014, i + h / 2, f"{a:.0f}%",
                color=rcfh.SOUNDING, fontsize=12, fontfamily=rcfh.MONO,
                va="center")
        ax.text(b + max(infra) * 0.014, i - h / 2, f"{b:.0f}%",
                color=rcfh.SOUNDING, fontsize=12, fontfamily=rcfh.MONO,
                va="center")
        # The multiple in a right-hand column, so the row ORDER explains
        # itself. Bar length follows the level, which is ordered differently.
        mult = a / max(b, 0.01)
        # A decimal below 3x, because rounding 1.27 to "1x" reads as no gap.
        ax.text(limit * 0.985, i,
                f"{mult:.1f}×" if mult < 3 else f"{mult:.0f}×",
                color=rcfh.INK, fontsize=13, fontfamily=rcfh.MONO,
                ha="right", va="center")
    ax.text(limit * 0.985, len(labels) - 0.62, "MULTIPLE", color=rcfh.SOUNDING,
            fontsize=10, fontfamily=rcfh.MONO, ha="right", va="center")
    rcfh.emphasise_row(ax, len(labels) - 1)

    rcfh.notes(
        fig,
        f"Read each pair against itself and never across institutions. The "
        f"banks run different scales, harmonised here onto a shared ladder: "
        f"Proparco and FMO grade on four levels, the other four on three, so "
        f"the LEVELS carry different meanings while the gap within one book "
        f"stays meaningful. That gap runs from {top['hi_infra'] / max(top['hi_rest'], 0.01):.0f} "
        f"times at {top['i']} down to under twice at FMO. The datasets we load "
        "from ADB, BII, EBRD and EIB Global carry no grade at all, so those "
        "four cannot appear; whether each discloses one elsewhere has not been "
        "checked here, and their absence is a limit of this tracker rather "
        "than a finding about their practice. AfDB is the one institution here "
        "lending mostly to sovereigns and the pattern survives that: its "
        "infrastructure book grades 53 per cent highest-risk on sovereign "
        "operations and 52 per cent on non-sovereign ones. Fourteen Proparco "
        "operations carry a financial-intermediary or unrated grade that maps "
        "to nothing on the shared ladder and drop out. Grades measure assessed "
        "risk at approval and say nothing about outcomes.", y=0.300)
    rcfh.source(fig, as_of=stamp)
    return rcfh.save(fig, OUT_DIR / "15_infrastructure_es_risk.png")


# ------------------------------------------------------------- exhibit 16 --
def sovereign_gradient(conn, stamp):
    """AfDB infrastructure by subsector, split on who borrows.

    AfDB ONLY, and the note says so twice. It is the single institution of the
    ten whose disclosure states whether the borrower is the state, so this is
    the only place in the tracker where the question can be asked at all.
    """
    rows = conn.execute(
        f"""SELECT subsector,
                   SUM(CASE WHEN sovereign = 'sovereign' THEN v ELSE 0 END) / 1e9 sov,
                   SUM(CASE WHEN sovereign = 'non-sovereign' THEN v ELSE 0 END) / 1e9 non
            FROM ({OPERATIONS})
            WHERE sector = ? AND institution = 'AfDB' AND v IS NOT NULL
              AND subsector IS NOT NULL
            GROUP BY 1 ORDER BY (sov + non)""", (INFRA,)).fetchall()
    labels = [r["subsector"] for r in rows]
    sov = [r["sov"] for r in rows]
    non = [r["non"] for r in rows]
    share = [100 * n / (s + n) if (s + n) else 0 for s, n in zip(sov, non)]

    order = ["Sovereign borrower", "Non-sovereign borrower"]
    colors, keys = rcfh.by_group(order, order=order)

    fig, ax = rcfh.figure("tracker", height=12.0)
    # The title says "state guarantee", never "private capital": the shallow
    # segment holds unguaranteed state-owned enterprises as well as project
    # companies, and the note below says so. A title claiming private capital
    # would contradict its own exhibit.
    rcfh.header(fig, "Water borrows behind a sovereign guarantee",
                dek=f"AfDB infrastructure commitments by borrower type, "
                    f"{RECENT_FROM}–{RECENT_TO}, USD billions. Unguaranteed "
                    "exposure runs from 23 per cent in energy to 0.3 per cent "
                    "in water.", exhibit="16")
    # Coverage first, legend below: see the note in exhibit 15.
    rcfh.coverage(fig, included=["AfDB"],
                  excluded=[i for i in ALL_TEN if i != "AfDB"])
    rcfh.legend(fig, [f"{lab}   " for lab in keys], colors=colors, y=0.735)
    fig.subplots_adjust(left=0.295, bottom=0.400)

    idx = range(len(labels))
    ax.barh(list(idx), sov, height=0.54, color=colors[0], zorder=3)
    ax.barh(list(idx), non, height=0.54, left=sov, color=colors[1], zorder=3)
    ax.set_yticks(list(idx))
    ax.set_yticklabels(labels)
    ax.set_xlim(0, max(s + n for s, n in zip(sov, non)) * 1.30)
    ax.set_xlabel("USD billions committed")
    for i, (s, n, pct) in enumerate(zip(sov, non, share)):
        ax.text(s + n + max(sov) * 0.03, i,
                f"{pct:4.1f}% non-sovereign", color=rcfh.SOUNDING,
                fontsize=12, fontfamily=rcfh.MONO, va="center")
    # Brass marks the row the TITLE argues about, which is water, not the
    # longest bar. Colour carries the ordering; brass carries the finding.
    rcfh.emphasise_row(ax, labels.index("Water & Sanitation"))

    rcfh.notes(
        fig,
        "AfDB ONLY, and the exhibit cannot be widened: of the ten "
        "institutions, only AfDB states per project whether the borrower is "
        "the state or state-guaranteed. Eight of the others publish nothing on "
        "this, and a blank records our ignorance rather than a private "
        "borrower. The gradient carries the finding. Unguaranteed money "
        "reaches energy, which sells a metered product under a power purchase "
        "agreement, and reaches transport, where a concession can charge a "
        "user. It stops at water, where tariffs answer to politics and cost "
        "recovery rarely clears. Read the shallow segment as exposure taken "
        "without a sovereign guarantee, never as private capital: AfDB's "
        "non-sovereign window holds state-owned enterprises lending "
        "unguaranteed, Transnet and Eskom among them, beside genuine project "
        "companies, and the source does not separate the two. Splitting them "
        "would need a state-owned-enterprise pass this tracker has not run.",
        y=0.310)
    rcfh.source(fig, as_of=stamp)
    return rcfh.save(fig, OUT_DIR / "16_sovereign_gradient.png")


# ------------------------------------------------------- LinkedIn pair --
# A different SURFACE, not a different dataset. The image travels alone on a
# phone, the caption does not survive a repost, and the reader gives it about
# two seconds, so: square canvas, notes at 15px and never smaller, and the
# standing disclaimer under the source block.
#
# The pair is designed to be read in order and each half does one job.
# L01 carries MAGNITUDE and L02 carries COMPOSITION over the same fifteen
# countries, so L02 can drop the axis to percentages without losing the
# scale: the reader already has it.
LINKEDIN_DIR = OUT_DIR / "linkedin"

# Four named sectors and a residual. The palette carries five stops and
# by_group refuses a sixth, which is the right constraint here anyway: a
# fourteen-segment stack on a phone is unreadable.
POST_SECTORS = ["Financial Institutions", "Infrastructure",
                "Agribusiness & Food", "Manufacturing"]
RESIDUAL = "Everything else"

# rcfh.legend sizes its row from a sans-width estimate while the house body
# face is a serif, and at the LinkedIn dek size five full sector names run off
# the canvas. These are legend labels only; the data keys stay canonical.
SHORT_SECTOR = {"Financial Institutions": "Banks & finance",
                "Infrastructure": "Infrastructure",
                "Agribusiness & Food": "Agribusiness",
                "Manufacturing": "Manufacturing",
                RESIDUAL: "Other"}

COUNTRY_ONLY = ("canonical_country IS NOT NULL "
                "AND canonical_country NOT LIKE 'Regional%' "
                "AND canonical_country NOT IN ('Undisclosed', 'Unclassified')")


def top_recipients(conn, limit=15):
    return conn.execute(
        f"""SELECT canonical_country c, SUM(amount_usd) / 1e9 bn FROM projects
            WHERE {WINDOW} AND amount_usd IS NOT NULL AND {OWN_ACCOUNT}
              AND {COUNTRY_ONLY}
            GROUP BY 1 ORDER BY bn DESC LIMIT {limit}""").fetchall()


# ---------------------------------------------------------- LinkedIn 01 --
def post_top_recipients(conn, stamp):
    """Top 15 recipients, ramp by RANK. The LinkedIn cut of exhibit 02."""
    rows = top_recipients(conn)
    labels = [r["c"] for r in rows][::-1]
    values = [r["bn"] for r in rows][::-1]

    fig, ax = rcfh.figure("linkedin", height=12.6)
    rcfh.header(fig, "Where development finance actually went",
                dek=f"Top 15 country recipients, {RECENT_FROM}–{RECENT_TO}, "
                    "USD billions committed by ten development finance "
                    "institutions. The ramp follows the ranking.")
    rcfh.coverage(fig, included=ALL_TEN)
    fig.subplots_adjust(left=0.235, bottom=0.375)
    ax.barh(range(len(values)), values, color=rcfh.by_rank(values),
            height=0.68, zorder=3)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels)
    ax.set_xlim(0, max(values) * 1.22)
    ax.set_xlabel("USD billions committed")
    rcfh.value_labels(ax, values, [f"USD {v:,.1f}bn" for v in values])
    rcfh.emphasise_row(ax, len(values) - 1)
    rcfh.notes(fig,
               "Country-specific deals only. Regional and multi-country "
               "operations are excluded, which understates every institution "
               "running a regional window, so these are FLOORS. Country names "
               "are harmonised across ten sources that each spell them "
               "differently. AfDB figures are a ceiling on its own share: its "
               "disclosure separates the government contribution but not other "
               "co-financiers.", y=0.250)
    rcfh.source(fig, as_of=stamp, disclaimer=True)
    return rcfh.save(fig, LINKEDIN_DIR / "L01_top_recipients.png")


# ---------------------------------------------------------- LinkedIn 02 --
def post_sector_composition(conn, stamp):
    """The same fifteen countries as a 100% stack, ordered by banking share.

    PERCENTAGES, not dollars, and the pairing is the reason: L01 already gave
    the reader the magnitudes for exactly these countries, so repeating them
    here would spend the whole canvas restating the previous chart. What this
    one has to show is that the mix moves, and a common baseline is the only
    way to see that across a 4x range in size.

    Ordered by banking share so the divergence reads as a wedge rather than
    as noise.
    """
    countries = [r["c"] for r in top_recipients(conn)]
    marks = ",".join("?" * len(countries))
    rows = conn.execute(
        f"""SELECT canonical_country c, canonical_sector s, SUM(amount_usd) v
            FROM projects
            WHERE {WINDOW} AND amount_usd IS NOT NULL AND {OWN_ACCOUNT}
              AND {COUNTRY_ONLY} AND canonical_sector <> 'Unclassified'
              AND canonical_country IN ({marks})
            GROUP BY 1, 2""", countries).fetchall()

    cell = {}
    total = dict.fromkeys(countries, 0.0)
    for r in rows:
        key = r["s"] if r["s"] in POST_SECTORS else RESIDUAL
        cell[(r["c"], key)] = cell.get((r["c"], key), 0.0) + r["v"]
        total[r["c"]] += r["v"]

    def share(country, sector):
        return 100 * cell.get((country, sector), 0.0) / total[country]

    # SENSITIVITY. EBRD's Trade Facilitation Programme books per-bank facility
    # limits, USD 17.9bn over 77 operations in the window, all of it inside
    # Financial Institutions and concentrated in three of these countries: it
    # carries 22 points of Greece's banking share, 11 of Ukraine's and 11 of
    # Tunisia's. These are real committed limits, distinct per bank and never
    # repeated, so they are NOT the umbrella double-count that IFC's trade
    # envelopes were, and removing them would be editorialising. Recomputing
    # the range without them is the honest test, and the note states both.
    ex_tfp = dict(conn.execute(
        f"""SELECT canonical_country,
                   100.0 * SUM(CASE WHEN canonical_sector = 'Financial Institutions'
                        THEN amount_usd ELSE 0 END) / SUM(amount_usd)
            FROM projects
            WHERE {WINDOW} AND amount_usd IS NOT NULL AND {OWN_ACCOUNT}
              AND canonical_country IN ({marks})
              AND NOT (institution = 'EBRD' AND project_name LIKE '%TFP%')
            GROUP BY 1""", countries).fetchall())

    # Deepest fill on the largest sector globally, so depth still carries the
    # ordering the reader meets first in the legend.
    groups = POST_SECTORS + [RESIDUAL]
    colors, keys = rcfh.by_group(groups, order=groups)
    order = sorted(countries, key=lambda c: share(c, "Financial Institutions"))

    fi = [share(c, "Financial Institutions") for c in order]
    infra = [share(c, "Infrastructure") for c in order]

    # ONE line: the LinkedIn surface wraps titles at 44 characters and the
    # dek is placed on the assumption of a single line, so a wrapped title
    # lands the dek on top of the coverage strip.
    fig, ax = rcfh.figure("linkedin", height=14.4)
    rcfh.header(fig, "Same two sectors, wildly different mixes",
                dek=f"Sector composition of the fifteen largest recipients, "
                    f"{RECENT_FROM}–{RECENT_TO}, per cent of each country's "
                    "commitments. Ordered by banking share.")
    rcfh.coverage(fig, included=ALL_TEN)
    rcfh.legend(fig, [f"{SHORT_SECTOR[k]}  " for k in keys], colors=colors,
                y=0.742)
    fig.subplots_adjust(left=0.235, bottom=0.430)

    left = [0.0] * len(order)
    for sector, color in zip(groups, colors):
        widths = [share(c, sector) for c in order]
        ax.barh(range(len(order)), widths, left=left, height=0.72,
                color=color, zorder=3)
        left = [a + b for a, b in zip(left, widths)]

    ax.set_yticks(range(len(order)))
    ax.set_yticklabels(order)
    ax.set_xlim(0, 100)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xlabel("Share of the country's committed value, per cent")
    ax.grid(False)
    rcfh.emphasise_row(ax, len(order) - 1)

    rcfh.notes(
        fig,
        f"Every country here draws most of its development finance from the "
        f"same two sectors, and no two draw it in the same proportion. Banking "
        f"runs from {min(fi):.0f} per cent of {order[0]}'s book to "
        f"{max(fi):.0f} per cent of {order[-1]}'s, infrastructure from "
        f"{min(infra):.0f} to {max(infra):.0f} per cent. Together they average "
        f"about 69 per cent everywhere, which is why the aggregate looks "
        f"stable while saying almost nothing about any single market. The "
        f"spread does not rest on trade finance: EBRD's trade facilitation "
        f"limits sit inside Financial Institutions and carry 22 points of "
        f"Greece's share, but excluding them the banking range is still "
        f"{min(ex_tfp.values()):.0f} to {max(ex_tfp.values()):.0f} per cent. "
        f"No single operation exceeds 11 per cent of any bar. Ten sector "
        f"taxonomies are harmonised into fourteen canonical sectors; the four "
        f"largest are named and the rest pooled. Country-specific deals only, "
        f"so every figure is a floor.", y=0.318)
    rcfh.source(fig, as_of=stamp, disclaimer=True)
    return rcfh.save(fig, LINKEDIN_DIR / "L02_sector_composition.png")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    LINKEDIN_DIR.mkdir(parents=True, exist_ok=True)
    conn = connect()
    stamp = as_of(conn)
    n = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    print(f"Rendering Bathymetric exhibits from {n:,} records "
          f"(data as of {stamp})")
    for fn in (commitments_over_time, top_countries, sector_mix, ticket_size,
               cofinancing_pairs, thematic_debt, mobilisation, instrument_mix,
               repeat_clients, commitments_against_gdp,
               growth_decomposition, allocation_against_intensity,
               infrastructure_share, infrastructure_ticket_size,
               infrastructure_es_risk, sovereign_gradient,
               post_top_recipients, post_sector_composition):
        path = fn(conn, stamp)
        print(f"  wrote {Path(path).name if path else fn.__name__}")
    conn.close()
    print(f"Done \u2014 {OUT_DIR}")


if __name__ == "__main__":
    main()
