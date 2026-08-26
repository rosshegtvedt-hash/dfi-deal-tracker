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
    rcfh.header(fig, f"IDB Invest raises USD {ratio:,.2f} beside every dollar "
                     "of its own",
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


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    conn = connect()
    stamp = as_of(conn)
    n = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    print(f"Rendering Bathymetric exhibits from {n:,} records "
          f"(data as of {stamp})")
    for fn in (commitments_over_time, top_countries, sector_mix, ticket_size,
               cofinancing_pairs, thematic_debt, mobilisation, instrument_mix,
               repeat_clients):
        path = fn(conn, stamp)
        print(f"  wrote {Path(path).name if path else fn.__name__}")
    conn.close()
    print(f"Done \u2014 {OUT_DIR}")


if __name__ == "__main__":
    main()
