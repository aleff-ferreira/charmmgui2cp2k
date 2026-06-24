"""Shared figure style for the charmmgui2cp2k manuscript.

A single source of truth so every panel uses the same fonts, sizes, palette, and
spine/tick conventions — the consistency expected of a publication figure set.
Colours are from the Okabe–Ito colourblind-safe palette, mapped to semantics.
"""

import matplotlib as mpl

# ── Semantic, colourblind-safe palette (Okabe–Ito) ──────────────────────────
PALETTE = {
    "accent":  "#1f6feb",   # reference / primary
    "blue":    "#0072B2",
    "ref":     "#0072B2",   # the chosen/reference scheme
    "problem": "#D55E00",   # vermilion — outlier / uncontrolled case
    "caution": "#E69F00",   # amber
    "neutral": "#9AA6B2",   # grey — secondary
    "ok":      "#009E73",   # green
    "ink":     "#1b2733",
    "muted":   "#5b6b7d",
    "grid":    "#e6eaf0",
}

RC = {
    "figure.dpi": 150,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.04,
    "savefig.facecolor": "white",
    "pdf.fonttype": 42,           # embed TrueType (editable, portable)
    "ps.fonttype": 42,
    "svg.fonttype": "none",       # keep text as text in SVG
    "font.family": "sans-serif",
    "font.sans-serif": ["DejaVu Sans", "Arial", "Helvetica", "Liberation Sans"],
    "font.size": 9.0,
    "axes.titlesize": 9.5,
    "axes.titleweight": "bold",
    "axes.labelsize": 9.5,
    "axes.labelcolor": PALETTE["ink"],
    "axes.edgecolor": "#3a4654",
    "axes.linewidth": 0.9,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": False,
    "xtick.labelsize": 8.5,
    "ytick.labelsize": 8.5,
    "xtick.color": "#3a4654",
    "ytick.color": "#3a4654",
    "xtick.direction": "out",
    "ytick.direction": "out",
    "xtick.major.size": 3.5,
    "ytick.major.size": 3.5,
    "xtick.major.width": 0.9,
    "ytick.major.width": 0.9,
    "legend.fontsize": 8.3,
    "legend.frameon": False,
    "lines.linewidth": 1.6,
    "text.color": PALETTE["ink"],
}


def apply():
    mpl.rcParams.update(RC)


def panel_label(ax, letter, x=-0.16, y=1.04):
    """Bold panel letter (a, b, …) in the top-left corner, journal style."""
    ax.text(x, y, letter, transform=ax.transAxes, fontsize=12, fontweight="bold",
            va="bottom", ha="left", color=PALETTE["ink"])


def save_all(fig, stem):
    """Save a figure as PDF (vector), SVG (vector), and PNG (raster) under figures/."""
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    paths = []
    for ext in ("pdf", "svg", "png"):
        p = os.path.join(here, f"{stem}.{ext}")
        fig.savefig(p)
        paths.append(p)
    return paths
