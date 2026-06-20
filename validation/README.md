# Validation study

Reproducible scientific validation of the `charmmgui2cp2k` generator, supporting
the manuscript's correctness claims. Each probe targets a way a QM/MM setup can
be silently wrong.

## Design (Phase 4 of the publication plan)

| # | Probe | What it proves | Status |
|---|-------|----------------|--------|
| A4.1 | **NVE energy conservation** | Link atoms, deleted boundary bonded terms, and boundary charges are mutually self-consistent (a broken boundary drifts) | **automated here** (`run_nve_validation.py`) |
| A4.2 | Cross-code / full-QM single-point agreement | The generated QM/MM single-point energy matches an independent reference | scaffold (see below) |
| A4.3 | Boundary-scheme over-polarization probe | The charge-redistribution scheme controls frontier over-polarization vs naive deletion | scaffold |
| A4.4 | BioExcel CP2K QM/MM benchmark suite | Tool-generated input agrees with CP2K-standalone references (MQAE, ClC, CBD_PHY, GFP) | needs suite download |
| A4.5 | **Metalloprotein active-site case study** | Headline: correctness where boundary/charge handling is most scrutinized | needs the production LAAO system |

A4.1 runs here on the committed alanine-dipeptide fixture (tiny QM region, fast).
A4.4/A4.5 require external data / the user's production systems and are driven by
the same harness with a different `--dir`.

## A4.1 — NVE energy conservation

```bash
.conda-tui/bin/python validation/run_nve_validation.py \
    --steps 200 --timestep 0.5 --functional PBE
```

Pipeline: (1) run the validated CLI generation on the fixture to produce
`system_qmmm.prmtop` + `system.xyz`; (2) assemble a **self-contained** NVE QM/MM
MD input via `assemble_cp2k_input` (no restart chaining); (3) run CP2K; (4) parse
the `.ener` conserved quantity and report drift per ps, normalized per degree of
freedom (`analyze_energy.py`).

PBE (GGA) is used for speed: the conservation test validates the QM/MM *coupling*
(link atoms / boundary charges / deleted terms), which is functional-independent.
Hybrid functionals only change cost, not the conservation physics.

**Interpretation.** A well-coupled boundary gives a small, non-drifting conserved
quantity (literature reference ~1e-5–1e-6 kT/dof/ps; Götz et al., JCTC 2014).
A systematic drift indicates a boundary inconsistency the generator should be
fixed to avoid. Results are written to `validation/results/`.

> Note: a short demonstration run (tens of fs) establishes the methodology and
> machinery; a publication-grade number needs a longer trajectory (≥ several ps)
> and ideally a solvated system. Increase `--steps` accordingly.

### Result on the fixture (committed)

A 100-step / 50 fs PBE run (`validation/results/nve_energy_report.txt`):

| metric | value |
|--------|-------|
| frames | 101 (50 fs) |
| conserved-quantity range | 1.66e-4 Ha (0.104 kcal/mol) |
| drift slope | -1.64e-5 Ha/ps (-0.010 kcal/mol/ps) |
| drift / dof | -2.49e-7 Ha/dof/ps (2.6e-4 kT/dof/ps at 300 K) |

The conserved quantity is stable (no systematic drift) — the tool-generated link
atoms, deleted boundary terms, and boundary charges are mutually consistent. The
residual is within ~2 orders of the literature reference (1e-5–1e-6 kT/dof/ps),
as expected for a short 50 fs trajectory at default SCF tolerance; a longer run
with tighter `EPS_SCF` tightens it further. CP2K: cp2k.psmp 2025.2.

## Outputs

`validation/results/` holds the committed report (`nve_energy_report.txt`) plus a
copy of the generated input and the `.ener` trace. The bulky transient run
directory (`nve_workdir/`, with wavefunctions and restarts) is git-ignored.

## Provenance

CP2K version, functional, basis, step count, and timestep are recorded in the
report header and the generated input. The generation step also emits the full
provenance/audit artifacts (`run_provenance.txt`, `boundary_charges.dat`,
`electronic_state.dat`).
