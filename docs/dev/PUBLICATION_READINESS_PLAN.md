# charmmgui2cp2k — Publication-Readiness & Usability Master Plan

Prepared 2026-06-18. This plan turns the existing CHARMM-GUI/AMBER → CP2K QM/MM
input generator into (a) a tool whose scientific rigor survives peer review at a
high-impact venue, and (b) a wizard so self-explanatory that external
documentation becomes optional. It is grounded in two evidence-gathering passes:
an internal scientific-rigor audit of `charmmgui2cp2k.py` and an external survey
of the publication bar and competitive landscape.

---

## 0. Strategic framing (read first)

### 0.1 Venue reality check
The stated target, *Briefings in Bioinformatics*, is in practice a **review/survey
journal** and a poor fit for announcing an author-developed tool (confidence:
medium — its live software-article policy is ambiguous and should be confirmed by
email to the editor). The realistic high-impact homes for a CLI/TUI QM/MM
converter, in priority order:

| Venue | Type | Fit | Open-source required | Key hurdle |
|---|---|---|---|---|
| **Bioinformatics (OUP)** | Application Note (~2.6k words) | **Best high-impact** | Yes, stable URL + test data | "must not be a trivial utility" |
| **JCIM (ACS)** | Application Note (~5k words) | **Best thematic** (QM/MM is core) | No (reviewer access ok) | must state novelty |
| **JOSS** | Software paper | Software-credit + rigorous review | Yes, OSI license | **repo public ≥6 months** w/ active dev |
| **SoftwareX** | Original Software Pub. | Reliable fallback | Yes, metadata table | low novelty bar, lower IF |
| ~~JCTC~~ | — | needs new *methodology*, no software type | — | excluded unless method advance |
| ~~NAR Web Server~~ | — | needs free public **web** server | — | excluded unless we build a web UI |

**Recommended strategy:** primary submission to **Bioinformatics Application Note
or JCIM Application Note**, with a **parallel JOSS submission** for software credit
and review rigor. *Action with a deadline:* JOSS requires the public repo to exist
with active development for ≥6 months, so **initialize the public repository now**
to start that clock — it is the longest-lead-time item in this plan.

### 0.2 The novelty claim (defensible, currently unmet)
"**The first automated generator of CP2K QM/MM input from CHARMM-GUI/AMBER
biomolecular setups.**" No competitor closes this gap: CHARMM-GUI's QM/MM
Interfacer is web-based, semiempirical-only, and emits CHARMM/AMBER engine input
(no CP2K); CP2K ships no setup wizard; ASH is a scripting library not a wizard;
MiMiCPy targets CPMD+GROMACS. Differentiators to emphasize: AMBER ingestion,
terminal-native offline TUI, and automation of error-prone CP2K-specific authoring
(`QM_KIND`/`MM_INDEX` enumeration, `LINK` atoms, charge/LJ pre-edits).
**Watch item:** CHARMM-GUI Interfacer "Part 2" (ai-QM/DFT) is forthcoming — ship
before it adds CP2K, or the differentiation narrows.

### 0.3 What the audit established
The tool already has **above-average scientific design**: topology validation
(CHAMBER/SCEE/pointers), residual-charge redistribution with PRMTOP round-trip
verification, link-atom forbidden-bond classification, a 5-detector spin-risk
taxonomy, CP2K version-capability gating, and rich audit artifacts
(`RunProvenance`, `boundary_charges.json/.dat`, `electronic_state.dat`, compat
report). The blockers are **not design flaws** — they are missing **empirical
validation, external cross-checks, and automated tests**. That is good news: the
gap to publication is bounded and mostly additive.

---

## 1. Track A — Scientific rigor (reviewer-blocking)

Ordered by how hard a reviewer will push on each.

### A1. Automated test & reproducibility infrastructure  *(blocker)*
Current state: 5 integration tests, **zero unit tests for the scientific core, no
regression baselines** (`tests/`).

- **A1.1 Unit tests for the scientific core.** Target the functions the audit
  flagged as untested and high-impact:
  - `infer_element` / `build_element_map` (ambiguous prefixes CA/CO/NA, missing
    ATOMIC_NUMBER fallback) — `charmmgui2cp2k.py:2605,2660`.
  - `build_residual_charge_plan` + `evaluate_residual_charge_plan_severity`
    (uniform vs distance-weighted, degenerate weights, conservation) — `:1155,1338`.
  - `_find_small_rings` / `_ring_is_aromatic_like` / `detect_pi_stacking_risk`
    (needs benzene-pair and FAD-like fixtures) — `:4503,4550,4616`.
  - `parse_cp2k_version_string` / `cp2k_version_at_least` (semantic 8.1 vs
    year-based 2023.1, malformed strings) — `:5830,5868`.
  - `estimate_qm_electrons_for_spin` / `validate_multiplicity_parity` — `:4176,4904`.
  - `detect_link_bonds` / `enrich_link_with_m2` / `classify_forbidden_link_bond` — `:3115,3178,385`.
  - Target ≥85% line coverage on the scientific core (measure with `coverage.py`).
- **A1.2 Golden-output regression suite.** Freeze checksummed reference outputs
  for 3–5 small systems (start with a trimmed subset of the bundled 143k-atom
  system + 2–3 public small QM/MM systems). Any code change that perturbs an
  emitted CP2K input must diff against the baseline. Store baselines under
  `tests/regression/` with a documented regeneration command.
- **A1.3 Continuous integration.** GitHub Actions matrix (Python 3.10–3.12,
  Textual present/absent) running `py_compile`, unit + regression + existing TUI
  tests, and `coverage`. CI green is the merge gate. This directly satisfies the
  Bioinformatics "runs on a wide range of machines" and JOSS "automated tests +
  CI" criteria.
- **A1.4 Deterministic-output guarantee.** Audit for any nondeterminism (dict
  ordering in emitted sections, timestamps in artifacts). Make emitted scientific
  content byte-identical for identical inputs; isolate timestamps to clearly
  marked header lines so regression diffs stay clean.

### A2. External cross-validation  *(blocker)*
The tool currently validates itself against itself. Reviewers will want agreement
with an independent implementation.

- **A2.1 ParmEd / MDAnalysis cross-check.** For each test system, compare
  `infer_element` output and per-atom charges against ParmEd's `Topology.elements`
  and charge arrays; fail the test on any element mismatch. This closes the
  HIGH-severity "element misidentification → wrong electron count → wrong
  multiplicity" gap from the audit.
- **A2.2 Real CP2K single-point agreement.** Add an opt-in test (skipped if no
  CP2K binary) that runs `cp2k --check` on every generated input (the hook already
  exists: `run_cp2k_input_check`, `:5994`) and, for at least one small system,
  runs an actual single-point and compares the SCF energy to a hand-written
  reference input. Document agreement (target: sub-mHa).
- **A2.3 Runtime availability checks** (closes audit gaps A4/A5 — "version-gated
  but never file-existence-checked"). Before emitting `GTH-*`, `BASIS_ADMM_MOLOPT`,
  or `DFTD3` references, verify the corresponding data files exist in the detected
  CP2K `data/` directory; downgrade-with-provenance or hard-warn if absent. Extend
  `validate_functional_pp_match`/`resolve_admm_aux_basis` (`:4060,10689`).

### A3. Close the residual scientific gaps  *(strengthens, some blocking)*
- **A3.1 Cross-channel charge-balance verification** *(blocker-ish).* Add a single
  check that the FIST residual redistribution **plus** the per-link
  `ADD_MM_CHARGE` embedding contributions jointly conserve the excised QM charge
  (today each channel is verified in isolation — `:1287`, `:1523`). Emit the
  combined balance into `boundary_charges.dat` and fail loudly on imbalance.
- **A3.2 Link-bond geometry sanity checks** *(strengthens).* Validate QM–MM cut
  distances (covalent-radius window) and QM–MM–H placement angle at generation
  time; emit a link-geometry table into the boundary audit. Catches nonsensical
  cuts before they fail in SCF. Extend `detect_link_bonds` consumers (`:3115`).
- **A3.3 Hard-stop policy in non-interactive mode** *(strengthens).* Forbidden
  link bonds currently only WARN in batch mode (`:1949`); add a
  `--strict`/`--fail-on-warn` mode that converts scientific WARNs into non-zero
  exit. Reviewers and reproducible pipelines expect fail-fast.
- **A3.4 Self-documenting decision trail** *(strengthens).* Record redistribution
  *strategy* (uniform vs distance-weighted) and PP/ADMM fallback rationale into
  `electronic_state.dat`, not only the JSON provenance.

### A4. The validation/benchmarking study  *(the make-or-break manuscript section)*
This is what separates a "format converter" from a credible scientific tool. Build
a `validation/` directory and a reproducible study:

- **A4.1 NVE energy conservation.** Generate a QM/MM-MD setup with the tool, run
  it in CP2K, report **energy drift per ps normalized per degree of freedom**.
  Template target from the AMBER QM/MM interface: ~1.7×10⁻⁶ kT/dof/ps.
- **A4.2 Cross-code / full-QM agreement.** For one small system, compare the
  tool-generated CP2K QM/MM single-point energy against (i) a hand-written CP2K
  reference and (ii) where feasible a full-QM or independent-code reference.
- **A4.3 Boundary-scheme correctness probe.** Demonstrate the implemented
  charge-redistribution scheme controls over-polarization using a hard probe
  (e.g. proton affinity / deprotonation energy near the QM/MM boundary), showing
  improvement over naive charge deletion.
- **A4.4 Standard benchmark suite.** Run the BioExcel GROMACS+CP2K QM/MM benchmark
  systems (MQAE, ClC, CBD_PHY, GFP) and/or validate against CP2K's GEEP embedding
  (Laino 2005) to show tool-generated input agrees with CP2K-standalone references.
- **A4.5 Metalloprotein/active-site case study.** Because the tool targets
  metalloproteins and redox cofactors — exactly where boundary/charge correctness
  is most scrutinized — include at least one metal-containing active-site case as
  the headline validation. (The bundled LAAO system is a candidate.)

> Note: exact literature drift/agreement figures cited here are from
> abstracts/secondary sources; re-confirm against the primary DOIs before quoting
> them in the manuscript.

---

## 2. Track B — Usability ("documentation unnecessary")

Reframe the goal precisely: *the primary workflow requires no external manual.*
This is publishable substance — it maps onto peer-reviewed best-practice rules
(Ten Simple Rules for Usable Software; FAIR4RS) that the paper will cite. The TUI
design brief in `prompt_kit_tui/` already targets this; the work below closes the
remaining gap and makes the claim defensible.

- **B1. Defaults match visible source evidence.** Every defaulted value (QM region
  from `mdin`, charge, multiplicity, functional) must show *where it came from*
  in-line, so the user trusts the default without reading docs. (Ten Simple Rules:
  conservative defaults; expose only mandatory parameters.)
- **B2. Progressive disclosure of expert controls.** Audit each phase
  (`SystemPhase`…`GeneratePhase`) so the default path shows only the dominant task;
  advanced controls (cutoffs, ADMM, dispersion, SCF profile) live behind
  Collapsibles. The `_didactic` collapsible mechanism already exists — apply it
  consistently.
- **B3. Errors as teaching tools.** Every validation failure must state the
  *corrective action* in local language next to the failing control, not a generic
  message (clig.dev principle; current `validate()` issues should be audited for
  actionability). The π-stacking flag, e.g., should suggest UKS / QM-region edit,
  not just describe the risk.
- **B4. Embedded provenance in every output.** Emit the full parameter set + tool
  version + dependency versions (Python, Textual, CP2K, ParmEd) **as comment
  headers inside every generated CP2K input**. One move satisfying Ten Simple Rules
  (configuration log), FAIR4RS R1.2 (provenance), and reproducibility reviewers.
- **B5. Ship demo data + one-command quickstart.** A trimmed bundled system and a
  `charmmgui2cp2k --demo` path so a new user reaches a generated input in one
  command (Bioinformatics "test data" requirement; Ten Simple Rules rule 8).
- **B6. Self-documenting machine-readable output.** Ensure JSON artifacts carry
  schema versions and field descriptions (`boundary_charges.json` already has
  `schema_version`; extend the pattern).
- **B7. Generation-phase transparency.** The Generate phase must show progress,
  current operation, warnings, and final artifact paths (largely present in
  `GeneratePhase._run_generation`); verify resize-safety and worker
  responsiveness on the 143k-atom system.
- **B8. Accessibility & resize validation.** Headless `run_test()` coverage at
  min/normal/wide TTY sizes; warnings distinguishable without color alone.

---

## 3. Track C — Publication packaging & FAIR release

- **C1. Open-source release.** Public Git repo (start the JOSS clock **now**),
  OSI-approved `LICENSE` (MIT or Apache-2.0 recommended), `README.md` with
  *statement of need* + *state of the field* (the competitor table from §0.2),
  `CONTRIBUTING.md`.
- **C2. Citeability & archival.** `CITATION.cff`; archive tagged releases on
  **Zenodo** for a versioned DOI; record the DOI in the README and in embedded
  output provenance (FAIR F1.2/R1.1).
- **C3. Software metadata.** A metadata table (version, OS, language, license,
  permanent code URL) for SoftwareX-style requirements; `environment-tui.yml`
  already pins the env — extend to a documented dependency manifest.
- **C4. Manuscript skeleton** (Application Note shape): Abstract → Statement of
  need / gap → Architecture (single-script pipeline, three frontends, validated
  core) → Scientific safeguards (charge conservation, link atoms, spin risk,
  version gating) → Validation results (Track A4) → Usability/FAIR → Availability.
  Reuse the `prompt_kit_tui` design brief language for the usability section.
- **C5. Figures.** (1) workflow/architecture diagram; (2) TUI screenshot walking a
  metalloprotein setup; (3) NVE energy-conservation plot; (4) boundary-scheme
  over-polarization probe; (5) cross-code agreement table.
- **C6. Reproducibility capsule.** Code Ocean / container image reproducing the
  validation figures end-to-end (Bioinformatics encourages; reviewers test it).

---

## 4. Phased execution roadmap (phase-gated, per AGENTS.md)

Each phase has an explicit **gate**: do not advance without the listed evidence.

| Phase | Goal | Gate evidence |
|---|---|---|
| **P1 — Repo + CI foundation** | Public repo, license, CI skeleton, coverage tooling | Repo live (JOSS clock started); CI green on existing tests; coverage report produced |
| **P2 — Scientific test net** (A1, A2.1, A3.1) | Unit tests for core, ParmEd cross-check, golden regression baselines, cross-channel charge balance | ≥85% core coverage; ParmEd element/charge parity on all fixtures; regression suite locks outputs |
| **P3 — Runtime + geometry hardening** (A2.3, A3.2–A3.4) | Data-file existence checks, link geometry checks, strict mode, decision trail | New checks unit-tested; `--strict` fails on scientific WARN; CP2K `--check` passes on all fixtures |
| **P4 — Validation study** (A4) | NVE drift, cross-code agreement, boundary probe, benchmark suite, flavoenzyme (LAAO) case | `validation/` reproduces all figures; numbers meet targets and are DOI-confirmed |
| **P5 — Usability pass** (Track B) | Defaults-with-evidence, progressive disclosure, actionable errors, embedded provenance, demo data, resize tests | Red-team user completes full workflow from UI alone, no manual; headless UX tests pass at 3 TTY sizes |
| **P6 — FAIR release + manuscript** (Track C) | Zenodo DOI, CITATION.cff, reproducibility capsule, manuscript draft | DOI minted; capsule reproduces figures; draft + cover letter ready |
| **P7 — Submission** | Venue confirmed, submit | Editor confirmation (esp. if BiB); JOSS submission opened in parallel |

**Critical path / longest lead time:** P1 (repo public) gates the 6-month JOSS
clock, and P4 (validation study) gates the manuscript. Start both as early as
possible; P2/P3/P5 can proceed in parallel once P1 lands.

### Risks
- **BiB scope** unconfirmed → confirm by email before investing; default to
  Bioinformatics/JCIM.
- **CHARMM-GUI Interfacer Part 2** may add CP2K → ship first; lean on AMBER + TUI
  + offline differentiation.
- **CP2K runtime access** needed for A2.2/A4 → secure a working CP2K build (the
  tool already detects installs) or document as a constrained-environment blocker.
- **"Trivial utility" objection** (Bioinformatics) → the validation study + safety
  machinery is the rebuttal; foreground it.

---

## 5. Immediate next actions (first sprint)
1. Decide the primary venue (recommend Bioinformatics Application Note + parallel
   JOSS) and email the BiB editor to settle the scope question.
2. Initialize the public repository with license + README skeleton (**starts the
   JOSS clock**).
3. Stand up CI + coverage and pin a `pytest` layout that separates unit /
   regression / TUI tests.
4. Write the first unit tests + ParmEd cross-check for `infer_element` and
   `build_residual_charge_plan`, and freeze the first golden-output baseline.
