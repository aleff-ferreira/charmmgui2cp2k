#!/usr/bin/env python3
"""Parse a CP2K MD .ener file and quantify energy conservation (A4.1).

CP2K writes ``<project>-1.ener`` with columns:
    step  time[fs]  kinetic[a.u.]  temperature[K]  potential[a.u.]
    conserved_quantity[a.u.]  used_time[s]

For an NVE run the *conserved quantity* should be flat. We report its drift as a
least-squares slope, converted to per-picosecond and normalized per degree of
freedom (3*natom), the standard way QM/MM setup papers report energy
conservation (cf. Goetz et al. AMBER interface; OpenMM-MiMiC).
"""

HARTREE_TO_KCAL = 627.509474
KB_HARTREE = 3.166811563e-6  # Boltzmann constant in Hartree/K (for kT reference)


def _read_ener(path):
    rows = []
    with open(path) as fh:
        for line in fh:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            parts = s.split()
            if len(parts) < 6:
                continue
            try:
                rows.append([float(x) for x in parts[:6]])
            except ValueError:
                continue
    return rows


def _linfit(xs, ys):
    """Least-squares slope and intercept of ys vs xs."""
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx if sxx else 0.0
    return slope, my - slope * mx


def analyze_ener_file(path, natom, temperature=300.0):
    import os
    if not os.path.isfile(path):
        return f"ENERGY ANALYSIS: FAILED — .ener file not found: {path}\n"
    rows = _read_ener(path)
    if len(rows) < 3:
        return (f"ENERGY ANALYSIS: INSUFFICIENT DATA — only {len(rows)} MD frame(s) "
                f"in {path}; the run likely did not complete enough steps.\n")

    times_fs = [r[1] for r in rows]
    conserved = [r[5] for r in rows]
    temps = [r[3] for r in rows]
    times_ps = [t / 1000.0 for t in times_fs]

    slope_ha_per_ps, _ = _linfit(times_ps, conserved)
    dof = 3 * int(natom)
    drift_per_dof_ps = slope_ha_per_ps / dof
    span_ps = times_ps[-1] - times_ps[0]

    cons_min, cons_max = min(conserved), max(conserved)
    fluct_ha = cons_max - cons_min
    mean_temp = sum(temps) / len(temps)

    # kT/dof/ps reference (a standard normalization in the QM/MM literature).
    kt = KB_HARTREE * temperature
    drift_kt_per_dof_ps = drift_per_dof_ps / kt if kt else float("nan")

    lines = [
        "# NVE energy-conservation analysis (A4.1)",
        f"frames:                      {len(rows)}",
        f"trajectory_span:             {span_ps*1000:.2f} fs ({span_ps:.4f} ps)",
        f"degrees_of_freedom (3N):     {dof}",
        f"mean_temperature:            {mean_temp:.2f} K",
        "",
        f"conserved_quantity_range:    {fluct_ha:.3e} Ha "
        f"({fluct_ha*HARTREE_TO_KCAL:.4f} kcal/mol)",
        f"drift_slope:                 {slope_ha_per_ps:.3e} Ha/ps "
        f"({slope_ha_per_ps*HARTREE_TO_KCAL:.4f} kcal/mol/ps)",
        f"drift_per_dof:               {drift_per_dof_ps:.3e} Ha/dof/ps",
        f"drift_per_dof (|kT| units):  {abs(drift_kt_per_dof_ps):.3e} kT/dof/ps "
        f"(kT at {temperature:.0f} K)",
        "",
        "# Reference: a well-coupled QM/MM boundary typically gives "
        "|drift| ~ 1e-5..1e-6 kT/dof/ps",
        "# (cf. Goetz et al., JCTC 2014, AMBER QM/MM interface).",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    import sys
    natom = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    print(analyze_ener_file(sys.argv[1], natom))
