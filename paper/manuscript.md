# charmmgui2cp2k: automated generation of CP2K QM/MM input from CHARMM-GUI/AMBER biomolecular setups

**Authors:** TODO (given-names / family-names / affiliations / ORCID)
**Corresponding author:** TODO

> Target venue: *Bioinformatics* (Application Note) or *JCIM* (Application Note),
> with a parallel *JOSS* submission. This is a working draft; placeholders are
> marked TODO and numeric results trace to `validation/`.

## Abstract

Setting up a biomolecular quantum-mechanics/molecular-mechanics (QM/MM)
simulation in CP2K from an existing AMBER / CHARMM-GUI system is a manual,
error-prone expert task: the QM region must be enumerated, every boundary link
atom defined, boundary charges redistributed, and the AMBER topology pre-edited.
We present **charmmgui2cp2k**, a terminal-native wizard (plain CLI and full-screen
Textual TUI sharing one validated core) that automates this end to end and emits
immediately runnable CP2K QM/MM input, embedding the scientific safeguards a
careful setup requires (topology validation, hydrogen link atoms with
forbidden-cut rejection, charge-conserving boundary schemes, spin-state risk
analysis, and CP2K version/data-file capability gating). To our knowledge it is
the first automated CHARMM-GUI/AMBER → CP2K QM/MM input generator. We validate
correctness by NVE energy conservation, real-CP2K parser acceptance, and an
independent ParmEd cross-check, and show the generated boundary is energy-
conserving. The tool is open source (MIT) at TODO_URL.

## 1 Statement of need

CP2K is a widely used engine for biomolecular QM/MM, able to read AMBER `prmtop`
and CHARMM PSF topologies directly, but it ships no setup GUI or wizard: users
hand-author the `&QMMM` region (`QM_KIND`/`MM_INDEX`), every `&LINK` atom, the
boundary charge handling, and Lennard-Jones/charge pre-edits of the topology.
Mistakes in any of these silently produce physically wrong simulations.

No existing tool closes this gap end to end (Table 1). CHARMM-GUI's QM/MM
Interfacer is web-based, semiempirical-only, and targets the CHARMM/AMBER
engines, not CP2K; ASH is a scripting library rather than a guided wizard;
MiMiCPy targets CPMD+GROMACS. `charmmgui2cp2k` fills this gap and is delivered as
an offline, terminal-native wizard aimed at enzyme active sites, metalloproteins,
and redox cofactors — the systems where boundary and charge correctness matter
most.

**Table 1. Landscape of QM/MM setup tools and the gap.**

| Tool | Form | Engine target | Closes CHARMM-GUI/AMBER→CP2K gap? |
|------|------|---------------|------------------------------------|
| CHARMM-GUI QM/MM Interfacer | web GUI | CHARMM/AMBER, semiempirical | No (no CP2K, no DFT) |
| CP2K (native) | input language | CP2K | No (no setup wizard) |
| ASH | Python library | many (CP2K as a backend) | No (library, not a wizard; no CHARMM-GUI ingest) |
| MiMiCPy | wizard | CPMD + GROMACS | No (different stack) |
| gmx2qmmm | script | GROMACS↔Gaussian/ORCA/… | No (no CP2K) |
| QwikMD | VMD GUI | NAMD | No (no CP2K) |
| **charmmgui2cp2k** | **CLI + TUI wizard** | **CP2K** | **Yes** |

## 2 Implementation

The pipeline is a single Python module exposing three frontends over one shared
scientific core (Figure 1): a plain CLI wizard, a Textual TUI workbench
(Figure 2; eight phases: System → QM region → Boundary → Method → Electronic →
Workflow → Preview → Generate), and a non-interactive batch mode. The core
performs:

- **Topology validation** — AMBER `POINTERS`/array cross-checks, CHAMBER
  rejection, mixed-SCEE detection.
- **QM/MM boundary** — automatic detection of bonds crossing the boundary,
  hydrogen link-atom capping (IMOMM), classification and rejection of chemically
  impossible cuts, M1/M2 neighbour enrichment, GEEP embedding radii, and
  generation-time link-geometry sanity checks.
- **Charge conservation** — residual-charge redistribution across split-residue
  MM atoms with PRMTOP round-trip verification, plus a combined cross-channel
  audit (FIST residual + ADD_MM_CHARGE embedding).
- **Electronic structure** — GTH-valence electron counting, multiplicity-parity
  enforcement, and a multi-detector spin-risk taxonomy (transition metals, redox
  cofactors, π-stacking geometry, unresolved elements) that refuses to
  auto-assign spin when the choice is unreliable.
- **CP2K capability gating** — keyword/basis/dispersion emission gated against
  the detected CP2K version *and* against the presence of the corresponding data
  files (GTH potentials, ADMM basis, dftd3.dat) in the install.
- **Provenance** — every generated input embeds a deterministic parameter header;
  a full decision log, boundary-charge audit, and electronic-state report are
  written alongside.

A `--strict` mode turns unresolved scientific concerns into a non-zero exit for
reproducible pipelines.

## 3 Validation

All validation is reproducible from `validation/` on a committed alanine-dipeptide
demo system (build script included); production-scale agreement is the
metalloprotein case study (§3.4).

### 3.1 Real-CP2K acceptance
Every generated staged input passes a real CP2K binary's parser-only
`--input-check` (CP2K 2025.2); see `tests/regression/test_cp2k_input_check.py`.

### 3.2 NVE energy conservation
A self-contained NVE QM/MM trajectory of the generated setup (PBE, 50 fs) gives a
conserved-quantity range of 0.104 kcal/mol and a drift of **2.6×10⁻⁴ kT/dof/ps**
with no systematic trend (Figure 3; `validation/results/nve_energy_report.txt`),
demonstrating the link atoms, deleted boundary terms, and boundary charges are
mutually consistent. A longer trajectory with tighter SCF tolerance reduces this
toward the literature reference (1e-5–1e-6 kT/dof/ps; Götz et al., JCTC 2014).

### 3.3 Boundary handling and reproducibility
Single-point energies under the NONE / Z1 / CHARGE_SHIFT boundary schemes differ
measurably: NONE (the full M1 frontier charge retained in the embedding) lies
2.61 kcal/mol from CHARGE_SHIFT, while Z1 and CHARGE_SHIFT (both remove M1 from
the embedding) agree to 0.26 kcal/mol
(Figure 4; `validation/results/singlepoint_probes_report.txt`). This confirms the boundary
charge treatment is physically active and that the redistribution schemes control
the frontier over-polarization NONE exhibits. Repeated runs are bitwise
reproducible (|ΔE| = 5×10⁻¹⁵ Ha). Element identities and charges agree with an
independent ParmEd parse (`tests/unit/test_parmed_crosscheck.py`).

### 3.4 Metalloprotein case study — TODO
Headline validation on a metal-containing active site (L-amino-acid oxidase,
LAAO), where boundary/charge correctness is most scrutinized: single-point and
short-MD agreement against a reference, plus a boundary over-polarization probe.
*(Awaiting the production system; the harness runs unchanged via `--dir`.)*

### 3.5 Benchmark suite — TODO
Agreement with the BioExcel GROMACS+CP2K QM/MM benchmark systems (MQAE, ClC,
CBD_PHY, GFP) to show tool-generated CP2K input matches standalone references.

## 4 Usability and reproducibility (FAIR)

The primary workflow is designed to need no external manual: defaults trace to
source evidence, expert controls use progressive disclosure, validation failures
state the corrective action, and the generation phase shows progress and final
artifacts. Each generated input embeds its full parameter set as a comment header
(FAIR R1.2); a one-command `--demo` reproduces a complete run from bundled data.
The software ships an OSI license, `CITATION.cff`, and continuous-integration
tests; releases will be archived on Zenodo for a versioned DOI.

## 5 Availability

Source code, tests, and the validation harness: TODO_URL (MIT license). Tested on
Linux with Python 3.10–3.12 and CP2K ≥ 7.1.

## Figures

- **Figure 1.** Architecture and data flow (`figures/fig1_architecture.mmd`).
- **Figure 2.** TUI workbench, rendered live (`figures/fig2_tui_workbench.svg`).
- **Figure 3.** NVE energy conservation of the generated QM/MM setup
  (`figures/fig3_nve_conservation.png`).
- **Figure 4.** Boundary-scheme over-polarization, single-point energies
  (`figures/fig4_boundary_scheme.png`).

Figures 3–4 regenerate from committed validation output via
`figures/make_figures.py`; Figure 2 via `figures/make_tui_screenshot.py`.

## References

> Verify exact volumes/pages/DOIs against the publishers before submission.

1. Senn HM, Thiel W. QM/MM methods for biomolecular systems. *Angew Chem Int Ed.*
   2009;48(7):1198–1229.
2. Lin H, Truhlar DG. QM/MM: what have we learned, where are we, and where do we
   go from here? *Theor Chem Acc.* 2007;117:185–199.
3. Laino T, Mohamed F, Curioni A, VandeVondele J. An efficient real space
   multigrid QM/MM electrostatic coupling. *J Chem Theory Comput.*
   2005;1(6):1176–1184.
4. Laino T, Mohamed F, Curioni A, VandeVondele J. An efficient linear-scaling
   electrostatic coupling for treating periodic boundary conditions in QM/MM
   simulations. *J Chem Theory Comput.* 2006;2(5):1370–1378.
5. Kühne TD, Iannuzzi M, Del Ben M, et al. CP2K: An electronic structure and
   molecular dynamics software package — Quickstep. *J Chem Phys.*
   2020;152:194103.
6. Götz AW, Clark MA, Walker RC. An extensible interface for QM/MM molecular
   dynamics simulations with AMBER. *J Comput Chem.* 2014;35(2):95–108.
7. Maier JA, Martinez C, Kasavajhala K, Wickstrom L, Hauser KE, Simmerling C.
   ff14SB: improving the accuracy of protein side chain and backbone parameters.
   *J Chem Theory Comput.* 2015;11(8):3696–3713.
8. Grimme S, Ehrlich S, Goerigk L. Effect of the damping function in dispersion
   corrected density functional theory. *J Comput Chem.* 2011;32(7):1456–1465.
9. Guidon M, Hutter J, VandeVondele J. Auxiliary density matrix methods for
   Hartree–Fock exchange calculations. *J Chem Theory Comput.*
   2010;6(8):2348–2364.
10. VandeVondele J, Hutter J. Gaussian basis sets for accurate calculations on
    molecular systems in gas and condensed phases. *J Chem Phys.*
    2007;127:114105.
11. Cordero B, Gómez V, Platero-Prats AE, et al. Covalent radii revisited.
    *Dalton Trans.* 2008;(21):2832–2838.
12. Jo S, Kim T, Iyer VG, Im W. CHARMM-GUI: a web-based graphical user interface
    for CHARMM. *J Comput Chem.* 2008;29(11):1859–1865.
13. Lee J, Cheng X, Swails JM, et al. CHARMM-GUI Input Generator for NAMD,
    GROMACS, AMBER, OpenMM, and CHARMM/OpenMM simulations. *J Chem Theory
    Comput.* 2016;12(1):405–413.
14. List M, Ebert P, Albrecht F. Ten Simple Rules for Developing Usable Software
    in Computational Biology. *PLoS Comput Biol.* 2017;13(1):e1005265.
15. Barker M, Chue Hong NP, Katz DS, et al. Introducing the FAIR Principles for
    research software. *Sci Data.* 2022;9:622.
