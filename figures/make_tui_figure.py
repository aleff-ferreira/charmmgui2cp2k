#!/usr/bin/env python3
"""Build the annotated TUI workbench figure (Figure 2).

    .conda-tui/bin/python figures/make_tui_figure.py

Overlays numbered callout badges on a screenshot of the Textual TUI and a legend
strip, then saves vector (PDF/SVG, with the screenshot embedded) and PNG.

Input: figures/fig2_tui_raw.png — a render of the live TUI. Regenerate it with:
    python figures/make_tui_screenshot.py          # -> figures/fig2_tui_workbench.svg
    google-chrome --headless --screenshot=fig2_tui_raw.png ... fig2_tui_workbench.svg
(see figures/README.md).
"""

import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Circle  # noqa: E402
import matplotlib.image as mpimg  # noqa: E402

import _style  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
P = _style.PALETTE

# Callout regions, as fractions of the screenshot (x, y from top-left), so they
# track the image regardless of its pixel size.
CALLOUTS = [
    (0.66, 0.030, "1", "Phase rail — current and remaining steps"),
    (0.065, 0.70, "2", "Sticky system summary (atoms, residues, QM region)"),
    (0.30, 0.205, "3", "Auto-detected inputs, each with its provenance"),
    (0.225, 0.62, "4", "Progressive disclosure — expert detail on demand"),
]


def main():
    _style.apply()
    img = mpimg.imread(os.path.join(HERE, "fig2_tui_raw.png"))
    h, w = img.shape[0], img.shape[1]
    asp = h / w
    fig_w = 7.0
    fig = plt.figure(figsize=(fig_w, fig_w * asp + 0.95))
    # screenshot axes (top) + legend axes (bottom)
    ax = fig.add_axes([0.012, 0.20, 0.976, 0.79])
    ax.imshow(img)
    ax.set_xlim(0, w); ax.set_ylim(h, 0)
    ax.axis("off")
    # thin frame around the screenshot
    for s in ("top", "bottom", "left", "right"):
        ax.spines[s].set_visible(True)
        ax.spines[s].set_color(P["grid"]); ax.spines[s].set_linewidth(1.0)

    r = 0.018 * w
    for fx, fy, num, _label in CALLOUTS:
        cx, cy = fx * w, fy * h
        ax.add_patch(Circle((cx, cy), r * 1.5, fc="white", ec=P["accent"],
                            lw=1.4, alpha=0.92, zorder=5))
        ax.add_patch(Circle((cx, cy), r, fc=P["accent"], ec="white", lw=1.2, zorder=6))
        ax.text(cx, cy, num, color="white", fontsize=10, fontweight="bold",
                ha="center", va="center", zorder=7)

    # legend strip
    lax = fig.add_axes([0.012, 0.0, 0.976, 0.18]); lax.axis("off")
    lax.set_xlim(0, 1); lax.set_ylim(0, 1)
    ys = [0.78, 0.54, 0.30, 0.06]
    for (_, _, num, label), yy in zip(CALLOUTS, ys):
        lax.add_patch(Circle((0.022, yy + 0.03), 0.013, transform=lax.transAxes,
                             fc=P["accent"], ec="none"))
        lax.text(0.022, yy + 0.03, num, color="white", fontsize=8, fontweight="bold",
                 ha="center", va="center", transform=lax.transAxes)
        lax.text(0.05, yy + 0.03, label, color=P["ink"], fontsize=9,
                 ha="left", va="center", transform=lax.transAxes)

    paths = _style.save_all(fig, "fig2_tui")
    plt.close(fig)
    for p in paths:
        print("wrote", os.path.relpath(p, ROOT))


if __name__ == "__main__":
    import sys
    sys.path.insert(0, HERE)
    main()
