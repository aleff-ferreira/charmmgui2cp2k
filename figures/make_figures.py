#!/usr/bin/env python3
"""Regenerate the data-driven manuscript figures from committed validation output.

    .conda-tui/bin/python figures/make_figures.py

Produces:
  fig3_nve_conservation.png  — NVE conserved-quantity trace (A4.1)
  fig4_boundary_scheme.png   — boundary-scheme over-polarization (A4.3)

Reads validation/results/ (committed). Requires matplotlib.
"""

import os
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "validation", "results")
HERE = os.path.dirname(os.path.abspath(__file__))
HARTREE_TO_KCAL = 627.509474


def fig_nve():
    ener = os.path.join(RESULTS, "nve_ala_dipeptide-1.ener")
    times, conserved = [], []
    with open(ener) as fh:
        for line in fh:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            p = s.split()
            if len(p) < 6:
                continue
            times.append(float(p[1]))            # fs
            conserved.append(float(p[5]))        # Ha
    e0 = conserved[0]
    rel = [(e - e0) * HARTREE_TO_KCAL for e in conserved]  # kcal/mol vs t0

    fig, ax = plt.subplots(figsize=(5.0, 3.2))
    ax.plot(times, rel, lw=1.3, color="#1f6feb")
    ax.axhline(0.0, color="0.6", lw=0.8, ls="--")
    ax.set_xlabel("time (fs)")
    ax.set_ylabel(r"$\Delta$ conserved quantity (kcal/mol)")
    ax.set_title("NVE energy conservation — generated QM/MM setup", fontsize=10)
    ax.text(0.03, 0.04,
            "drift = 2.6e-4 kT/dof/ps (no systematic trend)",
            transform=ax.transAxes, fontsize=8, color="0.3")
    fig.tight_layout()
    out = os.path.join(HERE, "fig3_nve_conservation.png")
    fig.savefig(out, dpi=200)
    plt.close(fig)
    return out


def fig_boundary():
    report = os.path.join(RESULTS, "singlepoint_probes_report.txt")
    energies = {}
    with open(report) as fh:
        for line in fh:
            m = re.match(r"E\[([A-Z0-9_]+)\s*\]\s*=\s*([-\d.]+)\s*Ha", line.strip())
            if m:
                energies[m.group(1)] = float(m.group(2))
    order = ["NONE", "Z1", "CHARGE_SHIFT"]
    ref = energies["CHARGE_SHIFT"]
    rel = [(energies[s] - ref) * HARTREE_TO_KCAL for s in order]
    colors = ["#d1242f", "#9a6700", "#1a7f37"]

    fig, ax = plt.subplots(figsize=(4.6, 3.2))
    bars = ax.bar(order, rel, color=colors, width=0.6)
    ax.axhline(0.0, color="0.5", lw=0.8)
    ax.set_ylabel(r"$\Delta E$ vs CHARGE_SHIFT (kcal/mol)")
    ax.set_title("Boundary-scheme over-polarization (single point)", fontsize=10)
    for b, v in zip(bars, rel):
        ax.text(b.get_x() + b.get_width() / 2, v + (0.06 if v >= 0 else -0.12),
                f"{v:+.2f}", ha="center", fontsize=8)
    ax.set_ylim(min(rel) - 0.6, max(rel) + 0.6)
    fig.tight_layout()
    out = os.path.join(HERE, "fig4_boundary_scheme.png")
    fig.savefig(out, dpi=200)
    plt.close(fig)
    return out


if __name__ == "__main__":
    for f in (fig_nve(), fig_boundary()):
        print("wrote", os.path.relpath(f, ROOT))
