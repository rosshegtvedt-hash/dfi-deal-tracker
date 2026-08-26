"""RCFH Advisory - Bathymetric chart apparatus.

Draws the parts of an exhibit that sit outside the plot: header band, brass
rules, coverage strip, notes block and source block, sized per surface.

The notes block is not optional. ``save`` refuses to write a figure that has
none, because an exhibit from this tracker without its caveats misleads by
omission.

Usage
-----
    import sys; sys.path.insert(0, "<skill>/assets")
    import rcfh_chart as rcfh

    fig, ax = rcfh.figure("linkedin")
    rcfh.header(fig, "Who actually takes equity risk",
                dek="Share of committed value by instrument family, 2015-2024.",
                exhibit="06")
    ax.barh(names, values, color=rcfh.RAMP[0])
    rcfh.emphasise_row(ax, 3)
    rcfh.notes(fig, "Six institutions. EIB Global, FMO and BII publish none ...")
    rcfh.source(fig, rcfh.TRACKER_SOURCE, as_of="20 August 2026")
    rcfh.save(fig, "exhibit-06.png")
"""

from __future__ import annotations

import os
import textwrap

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

# ---------------------------------------------------------------- palette
INK = "#0B1016"
TRENCH = "#0E2A3F"
OPEN_WATER = "#2E6187"
SHOAL = "#7FA3BC"
SILVER = "#B7C8D3"
ICE = "#E2E9ED"
GROUND = "#FBFCFC"
SOUNDING = "#5D6C77"
BRASS = "#A8853F"
FATHOM = "#D6DEE3"

RAMP = [TRENCH, OPEN_WATER, SHOAL, SILVER, ICE]

HEADING = ["Sitka Heading", "Sitka Banner", "Georgia", "DejaVu Serif"]
BODY = ["Sitka Text", "Sitka Small", "Georgia", "DejaVu Serif"]
MONO = ["Consolas", "Courier New", "DejaVu Sans Mono"]

TRACKER_SOURCE = (
    "Source: public project disclosures of DFC, IFC, EBRD, IDB Invest, ADB, AfDB, "
    "BII, FMO, Proparco and EIB Global. FMO is its own account only."
)
DISCLAIMER = (
    "This piece reflects my own analysis. It does not constitute investment, "
    "legal, or tax advice."
)

# --------------------------------------------------------------- surfaces
SURFACES = {
    "linkedin": dict(figsize=(12.0, 12.0), dpi=100, title=30, dek=17, tick=15,
                     note=15, source=13, wrap=86, title_wrap=44, wordmark=True, band=False),
    "report": dict(figsize=(6.5, 4.2), dpi=200, title=13, dek=10, tick=9,
                   note=8.5, source=8, wrap=104, title_wrap=62, wordmark=False, band=False),
    "tracker": dict(figsize=(12.0, 10.0), dpi=100, title=26, dek=14, tick=13,
                    note=12, source=11, wrap=104, title_wrap=52, wordmark=True, band=True),
}


def _pts(fig, px_or_pt, surface):
    """Sizes in the tables are already in the unit matplotlib wants."""
    return px_or_pt


def figure(surface: str = "tracker", height: float | None = None):
    """Create a figure and axes with the apparatus margins reserved."""
    if surface not in SURFACES:
        raise ValueError(f"surface must be one of {sorted(SURFACES)}")
    cfg = SURFACES[surface]
    w, h = cfg["figsize"]
    if height is not None:
        h = height
    style = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "rcfh_bathymetric.mplstyle")
    if os.path.exists(style):
        plt.style.use(style)
    fig, ax = plt.subplots(figsize=(w, h), dpi=cfg["dpi"])
    fig._rcfh = dict(surface=surface, cfg=cfg, has_notes=False, note_y=None)
    top = 0.78 if cfg["band"] else 0.80
    fig.subplots_adjust(left=0.16, right=0.94, top=top, bottom=0.32)
    return fig, ax


def header(fig, title, dek="", exhibit=None, wordmark="RCFH ADVISORY",
           series="DFI DEAL FLOW TRACKER"):
    """Wordmark, exhibit number, brass rule, finding-title and dek."""
    st = fig._rcfh
    cfg = st["cfg"]
    if cfg["band"]:
        fig.patches.append(Rectangle((0, 0.955), 1, 0.045, transform=fig.transFigure,
                                     facecolor=TRENCH, zorder=5, clip_on=False))
        fig.text(0.055, 0.9695, wordmark, color=GROUND, fontsize=cfg["dek"] * 0.8,
                 fontfamily=BODY, fontweight="bold", va="center", zorder=6)
        right = series if exhibit is None else f"{series} / {exhibit}"
        fig.text(0.945, 0.9695, right, color="#8FB3BA", fontsize=cfg["dek"] * 0.72,
                 fontfamily=MONO, ha="right", va="center", zorder=6)
        y = 0.915
    else:
        if cfg["wordmark"]:
            fig.text(0.055, 0.955, wordmark, color=INK, fontsize=cfg["dek"] * 0.78,
                     fontfamily=HEADING, fontweight="bold", va="center")
        if exhibit is not None:
            fig.text(0.945, 0.955, f"EXHIBIT {exhibit}", color=BRASS,
                     fontsize=cfg["dek"] * 0.72, fontfamily=MONO, ha="right",
                     va="center")
        fig.add_artist(plt.Line2D([0.055, 0.945], [0.937, 0.937], color=BRASS,
                                  linewidth=1.0, transform=fig.transFigure))
        y = 0.905

    title_lines = textwrap.wrap(title, cfg["title_wrap"]) or [title]
    fig.text(0.055, y, "\n".join(title_lines), color=INK, fontsize=cfg["title"],
             fontfamily=HEADING, fontweight="semibold", va="top", linespacing=1.2)
    if dek:
        dek_y = y - 0.042 * len(title_lines) - 0.004
        fig.text(0.055, dek_y, textwrap.fill(dek, cfg["wrap"]), color=SOUNDING,
                 fontsize=cfg["dek"], fontfamily=BODY, va="top", linespacing=1.45)
    return fig


def coverage(fig, included, excluded=(), y=None, label="COVERAGE"):
    """Chips showing which institutions the exhibit draws on."""
    cfg = fig._rcfh["cfg"]
    y = 0.795 if y is None else y
    fig.subplots_adjust(top=y - 0.065)
    fig.text(0.055, y, label, color=SOUNDING, fontsize=cfg["source"] * 0.8,
             fontfamily=MONO, va="center")
    x = 0.16
    for name, inc in [(n, True) for n in included] + [(n, False) for n in excluded]:
        w = 0.012 + len(name) * 0.0072 * (cfg["dek"] / 14)
        fig.patches.append(Rectangle((x, y - 0.011), w, 0.022,
                                     transform=fig.transFigure,
                                     facecolor=TRENCH if inc else GROUND,
                                     edgecolor="none" if inc else FATHOM,
                                     linewidth=0.9, zorder=4, clip_on=False))
        fig.text(x + w / 2, y, name, color=GROUND if inc else SOUNDING,
                 fontsize=cfg["source"] * 0.78, fontfamily=BODY, ha="center",
                 va="center", zorder=5)
        x += w + 0.006
    fig.text(0.16, y - 0.028,
             "Filled = data published. Outlined = excluded, see notes.",
             color=SOUNDING, fontsize=cfg["source"] * 0.78, fontfamily=BODY,
             va="center")
    return fig


def ramp(n, full=False, reverse=False):
    """An n-step ramp interpolated from the five palette stops.

    Charts with more rows than the palette has stops (top-15 country tables,
    twelve co-financing pairs) need a continuous scale rather than a repeat.
    By default the ramp stops at Silver rather than running to Ice, because
    Ice on Chart white is nearly invisible as a fill. Pass ``full=True`` for
    stacked segments, where neighbouring fills supply the contrast.
    """
    from matplotlib.colors import LinearSegmentedColormap
    stops = RAMP if full else RAMP[:4]
    cmap = LinearSegmentedColormap.from_list("bathymetric", stops, N=256)
    if n == 1:
        cols = [stops[0]]
    else:
        cols = [cmap(i / (n - 1)) for i in range(n)]
    return list(reversed(cols)) if reverse else cols


def by_rank(values, ascending=None):
    """Fills for a single-series chart, deepest on the largest value.

    ``values`` in the order you passed them to the plot. For a horizontal bar
    chart matplotlib draws index 0 at the bottom, so pass the data as-is and
    this returns fills in the same order.
    """
    n = len(values)
    order = sorted(range(n), key=lambda i: values[i], reverse=True)
    cols = ramp(n)
    out = [None] * n
    for depth, idx in enumerate(order):
        out[idx] = cols[depth]
    return out


def by_sequence(n, reverse=False):
    """Fills for a chart ordered by something other than size.

    Years, stages, tranches, risk ladders. The ramp follows the sequence, so
    depth encodes position rather than magnitude. Use this for time series;
    colouring a year chart by value scrambles chronology and misleads.
    """
    return ramp(n, reverse=reverse)


def by_group(keys, order=None):
    """Fills and a legend label list for a chart grouped by a real attribute.

    ``keys`` is one group name per row. Returns ``(colors, labels)``; pass the
    labels straight to ``legend()``. Groups take ramp stops in the order given,
    or in first-appearance order.
    """
    labels = list(order) if order else list(dict.fromkeys(keys))
    if len(labels) > len(RAMP):
        raise ValueError("More groups than ramp stops. Collapse the grouping "
                         "or split the exhibit.")
    step = max(1, len(RAMP) // max(len(labels), 1))
    lookup = {lab: RAMP[min(i * step, len(RAMP) - 1)] for i, lab in enumerate(labels)}
    return [lookup[k] for k in keys], labels


def legend(fig, labels, colors=None, y=0.795, swatch=0.014):
    """Single-row key above the plot, left aligned to the plot edge.

    Legends never float inside the plot area. This also pushes the axes down
    so the key cannot collide with the top row.
    """
    cfg = fig._rcfh["cfg"]
    colors = colors or RAMP
    fig.subplots_adjust(top=y - 0.055)
    x = 0.16
    for i, name in enumerate(labels):
        fig.patches.append(Rectangle((x, y), swatch, swatch,
                                     transform=fig.transFigure,
                                     facecolor=colors[i],
                                     edgecolor=FATHOM if colors[i] == ICE else "none",
                                     linewidth=0.8, zorder=5, clip_on=False))
        fig.text(x + swatch + 0.006, y + swatch / 2, name, color=INK,
                 fontsize=cfg["dek"] * 0.86, fontfamily=BODY, va="center")
        x += swatch + 0.018 + len(name) * 0.0062 * (cfg["dek"] / 14)
    return fig


def emphasise_row(ax, index, color=BRASS, linewidth=2.0):
    """Brass rule under the row carrying the finding. Never fill it.

    ``index`` counts rows as matplotlib plots them: 0 is the bottom row of a
    horizontal bar chart, so it matches the order of the data you passed in.
    """
    ax.axhline(index - 0.5, color=color, linewidth=linewidth, zorder=6)
    return ax


def value_labels(ax, values, labels=None, pad=0.01, fontsize=None):
    """Consolas values to the right of horizontal bars."""
    cfg = ax.figure._rcfh["cfg"]
    fontsize = fontsize or cfg["tick"] * 0.92
    span = max(values) if values else 1
    for i, v in enumerate(values):
        text = labels[i] if labels else f"USD {v}bn"
        ax.text(v + span * pad, i, text, color=SOUNDING, fontsize=fontsize,
                fontfamily=MONO, va="center")
    return ax


def notes(fig, text, y=0.235):
    """The mandatory method block, over a brass hairline."""
    cfg = fig._rcfh["cfg"]
    fig.add_artist(plt.Line2D([0.055, 0.945], [y + 0.045, y + 0.045],
                              color=BRASS, linewidth=0.9,
                              transform=fig.transFigure))
    fig.text(0.055, y + 0.022, "NOTES", color=BRASS, fontsize=cfg["source"] * 0.8,
             fontfamily=MONO, va="center")
    wrapped = textwrap.fill(text, cfg["wrap"])
    fig.text(0.055, y, wrapped, color=INK, fontsize=cfg["note"],
             fontfamily=BODY, va="top", linespacing=1.5)
    line_frac = cfg["note"] * 1.5 / (fig.get_size_inches()[1] * 72)
    fig._rcfh["has_notes"] = True
    fig._rcfh["note_bottom"] = y - line_frac * (wrapped.count("\n") + 1)
    return fig


def source(fig, text=TRACKER_SOURCE, as_of=None, compiled=True,
           disclaimer=False, y=None):
    """Source attribution, long-form as-of date, optional disclaimer."""
    cfg = fig._rcfh["cfg"]
    if y is None:
        y = fig._rcfh.get("note_bottom", 0.13) - 0.035
    lines = [textwrap.fill(text, int(cfg["wrap"] * 1.12))]
    if compiled:
        tail = "Compiled by RCFH Advisory \u00b7 DFI Deal Flow Tracker"
        if as_of:
            tail += f" \u00b7 Data as of {as_of}"
        lines.append(tail)
    if disclaimer:
        lines.append(DISCLAIMER)
    fig.text(0.055, y, "\n".join(lines), color=SOUNDING, fontsize=cfg["source"],
             fontfamily=BODY, va="top", linespacing=1.45)
    return fig


def save(fig, path, allow_missing_notes=False):
    """Write the figure. Refuses an exhibit with no notes block."""
    if not fig._rcfh["has_notes"] and not allow_missing_notes:
        raise ValueError(
            "This exhibit has no notes block. Every RCFH exhibit states its "
            "coverage, even when the data looks clean. Call notes() first, or "
            "pass allow_missing_notes=True and explain the exception."
        )
    fig.savefig(path, facecolor=GROUND)
    return path
