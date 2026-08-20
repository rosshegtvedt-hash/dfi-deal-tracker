"""
export_charts.py — renders branded PNG charts from the tracker, sized for
LinkedIn (1200x1200).

Run:
    python export_charts.py

Writes into charts/. Every chart is drawn inside one shared frame
(`brand_frame`) that stamps the RCFH Advisory wordmark, the title/subtitle
and the **source attribution footer** — the footer is part of the frame
rather than each chart, so a published chart cannot accidentally lose it.

COLOUR — the categorical palette carries exactly six hues that clear the
CVD, normal-vision and lightness checks together (validated with the dataviz
validator at all-pairs). So the six largest institutions by committed USD get
a fixed hue each and everything else is a neutral "Other". Hues follow the
institution, never its rank in a given chart, so a chart that drops a series
never repaints the survivors.

COMPARABILITY — institution totals are not like-for-like (different coverage
windows; EIB Global counts loan tranches; Proparco covers only
disclosure-consented deals since 2014). Charts therefore default to a recent
window (RECENT_FROM onward) and every subtitle states the cut being shown.

FMO is filtered to its OWN ACCOUNT everywhere in these charts. FMO's
disclosure covers both its own book and the Dutch government funds it
administers (MASSIF, Building Prospects, Access to Energy Fund and others),
and the two have very different deal sizes — blending them put FMO's average
cheque at USD 12m against USD 15m for its own lending, and inflated its deal
count with programme grants. Every other institution here is its own account,
so filtering FMO makes the comparison honest. The interactive dashboards
still show all FMO rows, each tagged with its fund.
"""

import sqlite3
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.path import Path as MPath  # noqa: E402
from matplotlib.patches import Patch, PathPatch  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from database import DB_PATH  # noqa: E402

OUT_DIR = Path(__file__).parent / "charts"
RECENT_FROM = 2015
# Last year with usable coverage across the panel. 2025 is deliberately
# excluded: DFC and ADB contribute nothing to it (both load from dated
# snapshot files), FMO is down 97% and BII 75% on reporting lag, while EBRD,
# EIB Global, IDB Invest and Proparco all grew. Charting 2025 would show a
# ~25% "collapse" in development finance that is an artefact of when each
# source was published, not anything that happened in the market.
RECENT_TO = 2024

# ---------------------------------------------------------------- tokens --
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
SURFACE = "#fcfcfb"
ACCENT = "#2a78d6"          # single-series magnitude hue

# Six validated categorical hues, one per institution, plus a neutral bucket.
INSTITUTION_COLORS = {
    "IFC": "#2a78d6",         # blue
    "EBRD": "#1baf7a",        # aqua
    "DFC": "#eda100",         # yellow
    "IDB Invest": "#008300",  # green
    "EIB Global": "#4a3aa7",  # violet
    "AfDB": "#e34948",        # red
}
OTHER_SERIES = "Other DFIs"
OTHER_COLOR = MUTED
CHART_SERIES = ["IFC", "EBRD", "AfDB", "EIB Global", "IDB Invest", "DFC", OTHER_SERIES]

FOOTER = ("Source: public project disclosures of DFC, IFC, EBRD, IDB Invest, ADB, "
          "AfDB, BII, FMO, Proparco and EIB Global. FMO is its own account only.\n"
          "Compiled by RCFH Advisory · DFI Deal Flow Tracker · Data as of {as_of}")

# FMO publishes its own book alongside Dutch government funds it merely
# administers. Only the own-account rows belong in a comparison against
# institutions that lend off their own balance sheet.
OWN_ACCOUNT_ONLY = {"FMO"}
OWN_ACCOUNT_FUND = "FMO"

plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]


# ------------------------------------------------------------------ data --
def load():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT institution, project_name, canonical_country AS country,
                  canonical_sector AS sector, amount_usd, description,
                  COALESCE(CAST(strftime('%Y', approval_date) AS INTEGER),
                           fiscal_year) AS year,
                  probable_duplicate_group AS dup
           FROM projects"""
    ).fetchall()
    as_of = (conn.execute("SELECT MAX(scraped_at) FROM projects").fetchone()[0] or "")[:10]
    conn.close()
    return [own_account(dict(r)) for r in rows], as_of


def funds_of(row):
    """Fund names a row is tagged with, from 'Fund: X' / 'Funds: X; Y'."""
    text = row.get("description") or ""
    if not text.startswith(("Fund:", "Funds:")):
        return []
    return [f.strip() for f in text.split(":", 1)[1].split(";") if f.strip()]


def own_account(row):
    """Mark whether a row is the institution's own lending."""
    row["is_own_account"] = (
        row["institution"] not in OWN_ACCOUNT_ONLY
        or OWN_ACCOUNT_FUND in funds_of(row))
    return row


def recent(rows, lo=RECENT_FROM, hi=RECENT_TO):
    return [r for r in rows
            if r["is_own_account"]
            and r["year"] and lo <= r["year"] <= hi and r["amount_usd"] is not None]


def series_for(institution):
    return institution if institution in INSTITUTION_COLORS else OTHER_SERIES


def money(v):
    if abs(v) >= 1e12:
        return f"${v/1e12:,.2f}T"
    if abs(v) >= 1e9:
        return f"${v/1e9:,.1f}B"
    return f"${v/1e6:,.0f}M"


# ----------------------------------------------------------------- frame --
def brand_frame(title, subtitle, as_of, note=None, left=0.065):
    """Shared canvas: wordmark, title, subtitle, chart axes, source footer.

    `left` widens the plot's left margin so long category labels are never
    clipped — a clipped label is worse than no label.
    """
    fig = plt.figure(figsize=(12, 12), dpi=100, facecolor=SURFACE)

    fig.text(0.065, 0.955, "R C F H   A D V I S O R Y", fontsize=13,
             color=ACCENT, fontweight="bold")
    fig.text(0.065, 0.915, title, fontsize=31, color=INK, fontweight="semibold",
             va="top")
    fig.text(0.065, 0.868, subtitle, fontsize=15.5, color=INK_2, va="top",
             linespacing=1.5)

    # The note sits above the footer; the footer's top is derived from how many
    # lines the note actually has, so a longer caveat can never collide with
    # the source attribution.
    footer_y = 0.052
    if note:
        note_top = 0.100
        fig.text(0.065, note_top, note, fontsize=12.5, color=MUTED, va="top",
                 style="italic", linespacing=1.45)
        footer_y = note_top - note.count("\n") * 0.0175 - 0.028
    fig.text(0.065, footer_y, FOOTER.format(as_of=as_of), fontsize=12,
             color=MUTED, va="top", linespacing=1.55)

    ax = fig.add_axes([left, 0.15, 0.95 - left, 0.66])
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=13.5, length=0)
    return fig, ax


def px_to_xunits(ax, px):
    """Convert a pixel distance to x-data units — the rounding radius has to be
    a visual length, and x here is dollars, so it cannot be a data fraction."""
    inv = ax.transData.inverted()
    return abs(inv.transform((px, 0))[0] - inv.transform((0, 0))[0])


def bar_height_px(ax, height):
    """Rendered height, in pixels, of a bar `height` y-data units tall."""
    t = ax.transData
    return abs(t.transform((0, height))[1] - t.transform((0, 0))[1])


def rounded_bar(ax, x0, y, width, height, color, radius=None, horizontal=True):
    """Bar with a rounded data-end and a square baseline end."""
    if horizontal:
        r = min(radius if radius is not None else 0, abs(width))
        if r <= 0 or width <= 0:
            return
        v = [(x0, y - height / 2), (x0 + width - r, y - height / 2),
             (x0 + width, y - height / 2), (x0 + width, y),
             (x0 + width, y + height / 2), (x0 + width - r, y + height / 2),
             (x0, y + height / 2), (x0, y - height / 2)]
        c = [MPath.MOVETO, MPath.LINETO, MPath.CURVE3, MPath.CURVE3,
             MPath.CURVE3, MPath.CURVE3, MPath.LINETO, MPath.CLOSEPOLY]
    else:
        r = min(radius if radius is not None else 0, abs(height))
        if r <= 0 or height <= 0:
            return
        v = [(x0 - width / 2, y), (x0 - width / 2, y + height - r),
             (x0 - width / 2, y + height), (x0, y + height),
             (x0 + width / 2, y + height), (x0 + width / 2, y + height - r),
             (x0 + width / 2, y), (x0 - width / 2, y)]
        c = [MPath.MOVETO, MPath.LINETO, MPath.CURVE3, MPath.CURVE3,
             MPath.CURVE3, MPath.CURVE3, MPath.LINETO, MPath.CLOSEPOLY]
    ax.add_patch(PathPatch(MPath(v, c), facecolor=color, edgecolor="none",
                           clip_on=False))


def save(fig, name):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
    print(f"  wrote {path.name}")
    return path


LABEL_FONT = 14


def hbar_chart(labels, values, title, subtitle, as_of, name, note=None,
               value_fmt=money, xlabel=None):
    """Single-series horizontal bars — the magnitude form, one hue."""
    # Reserve enough left margin for the longest label. Estimated from the
    # font size (Segoe UI averages ~0.52em per character) and then confirmed
    # against the rendered text below, so nothing is ever clipped.
    longest = max((len(str(l)) for l in labels), default=10)
    left = min(0.42, max(0.09, (longest * LABEL_FONT * 0.52 + 26) / 1200))

    fig, ax = brand_frame(title, subtitle, as_of, note, left=left)
    y = list(range(len(labels)))
    span = max(values) if values else 1

    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=LABEL_FONT, color=INK_2)
    ax.set_xlim(0, span * 1.16)
    ax.set_ylim(len(labels) - 0.45, -0.55)
    ax.xaxis.grid(True, color=GRID, linewidth=1, zorder=0)
    ax.set_axisbelow(True)
    ax.set_xticklabels([])
    ax.tick_params(axis="x", length=0)
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=13, color=MUTED, labelpad=12)

    # Limits are set, so pixel<->data conversion is now meaningful.
    height = 0.55
    radius = px_to_xunits(ax, min(7.0, bar_height_px(ax, height) * 0.3))
    for i, v in zip(y, values):
        rounded_bar(ax, 0, i, v, height, ACCENT, radius=radius)
        ax.text(v + span * 0.015, i, value_fmt(v), va="center", ha="left",
                fontsize=13, color=INK_2)

    # Confirm no y-label overflows the canvas; widen once if one does.
    fig.canvas.draw()
    overflow = min((t.get_window_extent().x0 for t in ax.get_yticklabels()),
                   default=1)
    if overflow < 4:
        for a in fig.axes:
            box = a.get_position()
            shift = (6 - overflow) / 1200
            a.set_position([box.x0 + shift, box.y0, box.width - shift, box.height])
    return save(fig, name)


# ---------------------------------------------------------------- charts --
def chart_over_time(rows, as_of):
    data = recent(rows)
    years = list(range(RECENT_FROM, RECENT_TO + 1))
    totals = {s: {y: 0.0 for y in years} for s in CHART_SERIES}
    for r in data:
        totals[series_for(r["institution"])][r["year"]] += r["amount_usd"] / 1e9

    fig, ax = brand_frame(
        "Development finance commitments, 2015–2024",
        "Ten institutions' disclosed commitments, in US$ billions per year.",
        as_of,
        note=("Coverage differs by institution — EIB Global counts loan tranches and "
              "Proparco only disclosure-consented deals. Totals are a floor.\n"
              "2025 is omitted: several sources had not reported it in full, which "
              "would read as a fall that did not happen."))
    bottom = {y: 0.0 for y in years}
    gap = 0.06  # surface gap between stacked segments, in data units
    for s in CHART_SERIES:
        color = INSTITUTION_COLORS.get(s, OTHER_COLOR)
        for y in years:
            v = totals[s][y]
            if v <= 0:
                continue
            ax.bar(y, v - gap, bottom=bottom[y] + gap / 2, width=0.62,
                   color=color, edgecolor="none", zorder=3)
            bottom[y] += v

    ax.set_xticks(years)
    ax.set_xticklabels(years, fontsize=13, color=MUTED)
    ax.yaxis.grid(True, color=GRID, linewidth=1)
    ax.set_axisbelow(True)
    ax.set_ylabel("US$ billions committed", fontsize=13.5, color=MUTED, labelpad=14)
    peak = max(bottom.values())
    ax.set_ylim(0, peak * 1.08)
    # Explicit proxy handles — an empty ax.bar() carries no colour into the
    # legend, which silently renders every swatch in the default hue.
    handles = [Patch(facecolor=INSTITUTION_COLORS.get(s, OTHER_COLOR), label=s)
               for s in CHART_SERIES]
    ax.legend(handles=handles, loc="upper left", frameon=False, ncol=4,
              fontsize=13.5, labelcolor=INK_2, handlelength=1.1,
              handleheight=1.1, columnspacing=1.6, borderpad=0.2)
    return save(fig, "01_commitments_over_time.png")


def chart_top_countries(rows, as_of):
    data = recent(rows)
    agg = {}
    for r in data:
        c = r["country"]
        if not c or c.startswith(("Regional", "Undisclosed", "Unclassified")):
            continue
        agg[c] = agg.get(c, 0) + r["amount_usd"]
    top = sorted(agg.items(), key=lambda kv: -kv[1])[:15]
    return hbar_chart(
        [k for k, _ in top], [v for _, v in top],
        "Where development finance went, 2015–2024",
        "Top 15 countries by disclosed commitments from ten development finance\n"
        "institutions. Regional and multi-country operations excluded.",
        as_of, "02_top_countries.png",
        note="Country-specific deals only. Institution coverage differs — see the tracker's data notes.")


def chart_sectors(rows, as_of):
    data = recent(rows)
    agg = {}
    for r in data:
        s = r["sector"]
        if not s or s in ("Unclassified", "Undisclosed"):
            continue
        agg[s] = agg.get(s, 0) + r["amount_usd"]
    ranked = sorted(agg.items(), key=lambda kv: -kv[1])
    total = sum(v for _, v in ranked)
    share = ranked[0][1] / total * 100
    return hbar_chart(
        [k for k, _ in ranked], [v for _, v in ranked],
        "What development finance actually funds",
        f"Disclosed commitments by sector, 2015–2024. {ranked[0][0]} alone take "
        f"{share:.0f} cents\nof every disclosed development finance dollar.",
        as_of, "03_sector_mix.png")


def chart_ticket_size(rows, as_of):
    data = recent(rows)
    per = {}
    for r in data:
        per.setdefault(r["institution"], []).append(r["amount_usd"])
    stats = sorted(((k, sum(v) / len(v)) for k, v in per.items() if len(v) >= 20),
                   key=lambda kv: -kv[1])
    return hbar_chart(
        [k for k, _ in stats], [v for _, v in stats],
        "Who writes what size cheque",
        "Average disclosed commitment per deal, 2015–2024. The spread is what a\n"
        "sponsor is really choosing between when picking a financier.",
        as_of, "04_ticket_size.png",
        note=("EIB Global publishes loan tranches rather than whole projects, so its "
              "average is per tranche.\nInstitutions with fewer than 20 deals in the "
              "window are omitted."))


def chart_cofinancing(rows, as_of):
    """Institution pairs that show up in the same probable co-financing group."""
    groups = {}
    for r in rows:
        if r["dup"] and r["is_own_account"]:
            groups.setdefault(r["dup"], set()).add(r["institution"])
    pairs = {}
    for members in groups.values():
        ms = sorted(members)
        for i in range(len(ms)):
            for j in range(i + 1, len(ms)):
                pairs[(ms[i], ms[j])] = pairs.get((ms[i], ms[j]), 0) + 1
    top = sorted(pairs.items(), key=lambda kv: -kv[1])[:12]
    return hbar_chart(
        [f"{a}  +  {b}" for (a, b), _ in top], [float(n) for _, n in top],
        "Who co-finances with whom",
        "Deals appearing in more than one institution's disclosures, matched on\n"
        "project name, country and year across the full history.",
        as_of, "05_cofinancing_pairs.png",
        value_fmt=lambda v: f"{int(v)}",
        note=("Fuzzy-matched leads, not confirmed syndications — name matching misses "
              "deals disclosed\nunder different names and can over-group similar ones."))


# Themes are their own categorical dimension, so they reuse the same six
# validated hues. No chart shows themes and institutions in colour on the same
# canvas, so a hue never means two things at once, and each legend says which
# dimension it is naming.
THEME_ORDER = ["Green", "Sustainability", "Social", "Sustainability-linked",
               "Blue", "Gender"]
THEME_COLORS = {
    "Green": "#008300",
    "Sustainability": "#1baf7a",
    "Social": "#2a78d6",
    "Sustainability-linked": "#4a3aa7",
    "Blue": "#eda100",
    "Gender": "#e34948",
}


def chart_thematic(as_of):
    """Who issues labelled debt, and in which flavour.

    A COMPOSITION chart rather than a time series, and that is the point.
    The year-by-year count swings hard — 27, 12, 33 across 2022–2024 — but the
    swing is almost entirely one institution: EBRD booked ten green bonds in
    2021, seven in 2022, NONE in 2023 and four in 2024. Take EBRD out and the
    rest is flat noise between two and eight a year. At this sample size a
    trend line would dress one lender's programme decisions up as a market
    signal, so the chart shows composition, which is stable, instead.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT p.institution, t.theme, COUNT(DISTINCT p.id) n
           FROM projects p JOIN project_themes t ON t.project_id = p.id
           GROUP BY 1, 2""").fetchall()
    # Order by LABELS, the same quantity the bar length shows. Ordering by
    # deals instead put IDB Invest's 77 labels below EBRD's 74, because a deal
    # carrying two labels is one deal and two segments.
    order = [r[0] for r in conn.execute(
        """SELECT p.institution FROM projects p
           JOIN project_themes t ON t.project_id = p.id
           GROUP BY p.institution ORDER BY COUNT(*) DESC""")]
    deals, labels, bonds, loans = conn.execute(
        """SELECT COUNT(DISTINCT project_id), COUNT(*),
                  COUNT(DISTINCT CASE WHEN labelled_instrument = 'bond'
                                      THEN project_id END),
                  COUNT(DISTINCT CASE WHEN labelled_instrument = 'loan'
                                      THEN project_id END)
           FROM project_themes""").fetchone()
    conn.close()

    counts = {(r["institution"], r["theme"]): r["n"] for r in rows}
    order = order[::-1]                       # barh draws bottom-up

    fig, ax = brand_frame(
        "Who issues labelled debt",
        f"{labels} labels across {deals} deals and ten institutions, by the\n"
        "label the issuer itself gave each one.",
        as_of,
        note=(f"Bars count LABELS, not deals: {labels} labels sit on {deals} deals - a bond can be both social and gender.\n"
              f"Bonds and loans both count ({bonds} bonds, {loans} loans): a green loan is labelled under the Loan Market\n"
              "Association's principles exactly as a green bond is under ICMA's. Counts are a floor."),
        left=0.135)

    left = {i: 0 for i in order}
    for theme in THEME_ORDER:
        for i in order:
            v = counts.get((i, theme), 0)
            if v:
                ax.barh(i, v, left=left[i], height=0.62,
                        color=THEME_COLORS[theme], edgecolor="none", zorder=3)
                left[i] += v
    for i in order:
        if left[i]:
            ax.text(left[i] + 0.9, i, str(left[i]), va="center", ha="left",
                    fontsize=13, color=INK_2, zorder=4)

    ax.xaxis.grid(True, color=GRID, linewidth=1)
    ax.set_axisbelow(True)
    ax.set_xlabel("labels applied", fontsize=13.5, color=MUTED, labelpad=14)
    ax.set_xlim(0, max(left.values()) * 1.12)
    ax.tick_params(axis="y", labelsize=14)
    handles = [Patch(facecolor=THEME_COLORS[t], label=t) for t in THEME_ORDER]
    ax.legend(handles=handles, loc="lower right", frameon=False, ncol=2,
              fontsize=13, labelcolor=INK_2, handlelength=1.1, handleheight=1.1,
              columnspacing=1.6, borderpad=0.2)
    return save(fig, "06_thematic_debt.png")


def chart_mobilisation(as_of):
    """Third-party capital raised alongside IDB Invest's own money."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        """SELECT CAST(substr(approval_date, 1, 4) AS INTEGER) y,
                  SUM(amount_usd) / 1e9     own,
                  SUM(mobilised_usd) / 1e9  mob
           FROM projects WHERE mobilised_usd > 0
             AND approval_date >= '2016-01-01' AND approval_date < '2026-01-01'
           GROUP BY 1 ORDER BY 1""").fetchall()
    own_all, mob_all = conn.execute(
        "SELECT SUM(amount_usd), SUM(mobilised_usd) FROM projects "
        "WHERE mobilised_usd > 0").fetchone()
    conn.close()

    years = [r[0] for r in rows]
    fig, ax = brand_frame(
        "The money that comes with the money",
        "Third-party capital raised alongside IDB Invest's own commitments,\n"
        "US$ billions per year.",
        as_of,
        note=("IDB Invest only. It is the one institution of the ten that publishes "
              "mobilisation per project; IFC and\n"
              "EBRD report it as programme or annual aggregates, which cannot be "
              "mixed with deal-level data.\n"
              "Mobilised capital is never counted as an institution's own "
              "commitment anywhere in this tracker."))

    width = 0.38
    for r in rows:
        ax.bar(r[0] - width / 2, r[1], width=width, color=ACCENT,
               edgecolor="none", zorder=3)
        ax.bar(r[0] + width / 2, r[2], width=width, color="#1baf7a",
               edgecolor="none", zorder=3)

    ax.set_xticks(years)
    ax.set_xticklabels(years, fontsize=13, color=MUTED)
    ax.yaxis.grid(True, color=GRID, linewidth=1)
    ax.set_axisbelow(True)
    ax.set_ylabel("US$ billions", fontsize=13.5, color=MUTED, labelpad=14)
    ax.set_ylim(0, max(max(r[1], r[2]) for r in rows) * 1.20)
    ratio = mob_all / own_all if own_all else 0
    # Both dollar signs are escaped: a matched PAIR of unescaped "$" in a
    # matplotlib string is parsed as mathtext, which rendered this headline
    # as italic run-together maths.
    ax.text(0.5, 0.98, rf"\${ratio:,.2f} mobilised for every \$1 of its own",
            transform=ax.transAxes, ha="center", va="top", fontsize=18,
            color=INK, fontweight="semibold")
    handles = [Patch(facecolor=ACCENT, label="IDB Invest's own account"),
               Patch(facecolor="#1baf7a", label="Third-party capital mobilised")]
    ax.legend(handles=handles, loc="upper left", frameon=False, fontsize=13.5,
              labelcolor=INK_2, handlelength=1.1, handleheight=1.1, borderpad=0.2)
    return save(fig, "07_mobilisation.png")


def main():
    rows, as_of = load()
    print(f"Rendering charts from {len(rows):,} records (data as of {as_of})")
    chart_over_time(rows, as_of)
    chart_top_countries(rows, as_of)
    chart_sectors(rows, as_of)
    chart_ticket_size(rows, as_of)
    chart_cofinancing(rows, as_of)
    chart_thematic(as_of)
    chart_mobilisation(as_of)
    print(f"Done — {OUT_DIR}")


if __name__ == "__main__":
    main()
