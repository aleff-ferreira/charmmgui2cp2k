#!/usr/bin/env python3
"""Regenerate the data-driven validation figure from committed validation output.

    .conda-tui/bin/python figures/make_figures.py

Produces a single two-panel figure (vector PDF + SVG, plus PNG):
  fig3_validation.{pdf,svg,png}
    (a) NVE conserved-quantity trace (A4.1)
    (b) boundary-scheme over-polarization (A4.3)

Reads validation/results/ (committed). Requires matplotlib.
"""

import os
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

import _style  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "validation", "results")
HARTREE_TO_KCAL = 627.509474
P = _style.PALETTE


def _read_nve():
    times, conserved = [], []
    with open(os.path.join(RESULTS, "nve_ala_dipeptide-1.ener")) as fh:
        for line in fh:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            p = s.split()
            if len(p) < 6:
                continue
            times.append(float(p[1]))
            conserved.append(float(p[5]))
    e0 = conserved[0]
    return times, [(e - e0) * HARTREE_TO_KCAL for e in conserved]


def _read_boundary():
    energies = {}
    with open(os.path.join(RESULTS, "singlepoint_probes_report.txt")) as fh:
        for line in fh:
            m = re.match(r"E\[([A-Z0-9_]+)\s*\]\s*=\s*([-\d.]+)\s*Ha", line.strip())
            if m:
                energies[m.group(1)] = float(m.group(2))
    return energies


def panel_nve(ax):
    t, rel = _read_nve()
    ax.plot(t, rel, color=P["accent"], lw=1.6, solid_capstyle="round")
    ax.axhline(0.0, color=P["neutral"], lw=0.8, ls=(0, (4, 3)), zorder=0)
    ax.set_xlabel("time (fs)")
    ax.set_ylabel(r"$\Delta$ conserved quantity (kcal/mol)")
    ax.set_xlim(0, 50)
    ax.set_ylim(-0.012, 0.14)
    ax.set_yticks([0.00, 0.04, 0.08, 0.12])
    # Drift stat in a clean boxed annotation, placed in empty headroom.
    ax.text(0.97, 0.95,
            "drift  $-2.5{\\times}10^{-7}$ Ha/dof/ps\n"
            "($2.6{\\times}10^{-4}$ kT/dof/ps) — no trend",
            transform=ax.transAxes, ha="right", va="top", fontsize=7.8,
            color=P["muted"],
            bbox=dict(boxstyle="round,pad=0.4", fc="white",
                      ec=P["grid"], lw=0.8))


def panel_boundary(ax):
    e = _read_boundary()
    ref = e["CHARGE_SHIFT"]
    schemes = ["NONE", "Z1", "CHARGE_SHIFT"]
    vals = [(e[s] - ref) * HARTREE_TO_KCAL for s in schemes]
    colors = [P["problem"], P["neutral"], P["ref"]]
    x = range(len(schemes))
    bars = ax.bar(x, vals, width=0.62, color=colors, edgecolor="white", lw=0.6, zorder=3)
    # Zero line is the CHARGE_SHIFT reference.
    ax.axhline(0.0, color=P["ref"], lw=1.1, ls=(0, (5, 3)), zorder=1)
    ax.text(2.0, 0.10, "reference", color=P["ref"], fontsize=7.6,
            ha="center", va="bottom")
    ax.set_xticks(list(x))
    ax.set_xticklabels(["NONE", "Z1", "CHARGE_\nSHIFT"])
    ax.set_ylabel(r"$\Delta E$ vs CHARGE_SHIFT (kcal/mol)")
    ax.set_ylim(-1.1, 3.25)
    ax.set_yticks([0, 1, 2, 3])
    # Value labels clear of the bars/axis.
    for xi, v in zip(x, vals):
        if abs(v) < 1e-9:
            continue
        off = 0.10 if v > 0 else -0.10
        ax.annotate(f"{v:+.2f}", (xi, v), xytext=(0, 7 if v > 0 else -12),
                    textcoords="offset points", ha="center",
                    fontsize=8.2, fontweight="bold",
                    color=P["problem"] if v > 0 else P["muted"])


def main():
    _style.apply()
    fig, (axa, axb) = plt.subplots(1, 2, figsize=(7.2, 3.1))
    panel_nve(axa)
    panel_boundary(axb)
    _style.panel_label(axa, "a")
    _style.panel_label(axb, "b", x=-0.20)
    fig.subplots_adjust(left=0.10, right=0.985, bottom=0.20, top=0.92, wspace=0.42)
    paths = _style.save_all(fig, "fig3_validation")
    plt.close(fig)
    for p in paths:
        print("wrote", os.path.relpath(p, ROOT))


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
