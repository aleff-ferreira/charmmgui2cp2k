
# Scientific-Rigor Audit — `charmmgui2cp2k`
**Target:** `/home/nexus/aleff/fcup/laao_codex/charmmgui2cp2k.py` (21,246 lines) + TUI + test suite
**Scope:** Automated generation of CP2K QM/MM input from AMBER / CHARMM-GUI biomolecular setups
**Method:** 12 subsystem auditors → 3-vote perspective-diverse adversarial panel (guarded-elsewhere / chemistry-correctness / reproduce-it). A finding is CONFIRMED unless ≥2 of 3 verifiers refuted it.
**Tally (verified machine totals):** 43 findings raised, 6 refuted, **37 confirmed** — 5 Critical (C1–C5), 13 High (H1–H13), 16 Medium (M1–M16), 3 Low (L1–L3). *(An earlier draft header said "40/46"; the enumerated findings below total 37, matching the run's machine totals.)*

> **Maintainer verification (2026-06-29):** C1, C2, C4, C5, and H1 were independently spot-checked against the source and all hold (e.g. `LINK_GEOMETRY_TOLERANCE_FRAC = 0.40` at line 3314; `BoundaryPhase.validate` returns `True, []` with no forbidden-link check; the bond loop strides `range(0, len-2, 3)` and never reads the `[k+2]` bond-type index). Line numbers are approximate and may drift; confirm before editing.
>
> **P0 remediation status (2026-06-30, branch `fix/p0-scientific-rigor`):** all P0 items are **FIXED & test-backed** (176 tests pass, +60 new):
> - **C1, H8** — DFTD4 version-gated on every selection path (`validate_dispersion_scheme_version`). _commit 8d1b2d8_
> - **C5, H9, M1** — out-of-range QM indices and sub-physical RCUT now hard-fail. _commit 547c18d_
> - **C2, C3, H12** — TUI now enforces forbidden-link, ADMM-coverage and MD-range gates via shared helpers. _commit 0e4d365_
> - **C4, H1, L2** — bond order inferred from `BOND_EQUIL_VALUE`; non-single cuts warned; geometry tolerance 0.40→0.15. _commit a3cb557_
>
> **P1 remediation status (2026-07-01, branch `fix/scientific-rigor`):** all P1 items **FIXED & test-backed** (207 tests pass, +90 new since the audit):
> - **H6, H7, M9, M10** — spin ambiguity/risk, parity inconsistency, duplicate-M1, unresolved elements now `--strict` gate concerns (also wired C2 forbidden-link + C4 non-single cuts into the gate). _commit 44db65f_
> - **M7, M8, M11** — parity `None` (unverifiable) no longer silently accepted; parity-violation exits with `STRICT_GATE_EXIT_CODE` (3). _commit 3fc45fb_
> - **H2, M2** — TUI blocks unresolved GTH (matching the CLI, now exit 3); PDB elements resolved via topology `ATOMIC_NUMBER` (Cα≠Ca). _commit 000738b_
> - **H10, H13, M15, M13** — relaxed RCUT, unsafe timestep (>0.5 fs), under-converged MGRID cutoff now `--strict` gate concerns. _commit 9975691_
>
> P2/P3 remain open: peptide/aromatic IMOMM α (H3, H4), remove forbidden metals from `COVALENT_RADII_ANG` (M5), charge-conservation totals (H5, M6), basis-name validation (H11, M14), misc (M3, M4, M16, L1, L3, M12), CP2K `--check` golden test, metal-at-boundary fixture (P3).

---

## 1. Executive summary

**Verdict: Conditionally trustworthy — not yet publication-grade. Do not treat generated QM/MM input as scientifically correct-by-construction until the Critical and boundary-chemistry High findings are fixed.**

The pipeline is well-engineered on the *housekeeping* axes that the adversarial panel could most easily falsify: per-atom charge bookkeeping, torsion/1-4 preservation, NONBONDED_PARM_INDEX arithmetic, and E16.8 quantization were all probed and **dismissed as false alarms** (topology: 0/3 confirmed). That is a genuinely good signal — the obvious failure modes are guarded.

The confirmed failures cluster in three places where a wrong answer is **silent** (input generates cleanly, then either fails cryptically at CP2K parse time or, worse, runs and produces physically wrong chemistry):

1. **Boundary / link-atom chemistry is the worst subsystem (6/6 confirmed, incl. 1 Critical).** The code cuts QM/MM bonds using single-bond geometry assumptions with a ±40% tolerance, so it will silently sever double, triple, aromatic, and peptide bonds and cap them with a single-bond IMOMM hydrogen. For a flavoenzyme / aromatic-rich active site this is a direct route to wrong electronic structure. This is the headline scientific risk.

2. **Validation is computed but not *gated*.** Repeatedly, the code knows something is wrong — out-of-range QM indices, unresolved elements, parity-inconsistent multiplicity, sub-physical RCUT, forbidden metal link bonds — and only `warn()`s, or writes the violation to an audit file that the strict gate never reads (`provenance_gate`: 5/6 confirmed). In batch/non-interactive runs these warnings are effectively silent.

3. **The TUI is a second, weaker code path.** Three Critical/High gates that the CLI enforces (ADMM aux-basis coverage, forbidden link bonds, MD parameter ranges) are simply **absent** from the corresponding TUI phases (`tui_dataflow`: 3/3 confirmed). A user driving the tool through the TUI can produce input the CLI would have rejected.

Headline risks, in order: **(a) silent π-bond / peptide-bond cuts**, **(b) DFTD4 emitted for CP2K < 8.1 via CLI override → guaranteed runtime failure**, **(c) TUI bypasses ADMM-coverage and forbidden-link gates**, **(d) warn-don't-block culture defeats the project's own `feedback_no_silent_modifications` policy.**

---

## 2. Confirmed findings by severity

Severities below are **re-ranked using the verifiers' corrected votes** where the panel disagreed with the original auditor (the `corrected` array). Notable demotions/promotions are flagged inline.

### CRITICAL

**C1 — DFTD4 emission not gated by CP2K version when passed via `--dispersion-scheme` CLI override**
`charmmgui2cp2k.py` (CLI override path ~20465-20474; emission 13553-13558; `CP2K_DFTD4_MIN_VERSION=(8,1)` at 4121 defined but never wired into `CP2K_KEYWORD_MIN_VERSION` at 6483-6510)
*Consequence:* DFTD4 requires CP2K ≥ 8.1. A user on CP2K 7.5 who passes `--dispersion-scheme DFTD4` clears the wrapper's hard-floor check (7.1) and the override path skips `recommend_dftd4_upgrade`. CP2K then fails at parse time with "DFTD4 not available" — after queue wait and wasted allocation. Silently non-runnable input.
*Fix:* Add `'&FORCE_EVAL/&DFT/&XC/&VDW_POTENTIAL/&PAIR_POTENTIAL/TYPE (DFTD4)': (8,1)` to `CP2K_KEYWORD_MIN_VERSION`; validate it in the `dispersion_scheme_override` branch (~20466), raising `ValueError` if the detected version is below 8.1. (Panel: 3/3 confirmed, conf 0.96.)

**C2 — `BoundaryPhase.validate()` does not check for forbidden QM/MM link bonds (TUI)**
`charmmgui2cp2k.py:15277-15280` (returns `(True, [])` unconditionally); CLI equivalent at 17566-17632; `classify_forbidden_link_bond()` defined at 387 but never called from the TUI.
*Consequence:* Forbidden cuts (e.g. transition-metal–Kr-pseudopotential frontier pairs) give an ill-defined QM/MM Hamiltonian → wrong forces and wrong QM/MM MD. The TUI shows the link in a table with no warning; the user cannot know it is forbidden.
*Fix:* Call `classify_forbidden_link_bond()` per link in `BoundaryPhase.validate()`; on any forbidden pair append a `correction`-severity record and return `(False, [remedy message: widen QM region / supply bonded FF])`. (Panel 0.96.)

**C3 — `MethodPhase` missing ADMM auxiliary-basis coverage gate (TUI)**
`charmmgui2cp2k.py:15284-15396` (no `validate()` at all); CLI gate at 19398-19421 via `missing_admm_aux_basis_elements()`.
*Consequence:* ADMM requires an aux basis covering *every* QM element (Guidon et al., JCTC 6, 2348, 2010). A missing AUX_FIT Kind is the documented silent failure: input looks valid, passes downstream checks, then CP2K cannot execute. Especially likely with metals (FE/ZN/MO absent from `FIT3_AUX_ELEMENTS`).
*Fix:* Add `MethodPhase.validate()` mirroring CLI lines 19398-19421; block advancement (or record a blocking `correction`) when uncovered elements exist and no CP2K data dir is available. (Panel 3/3, 0.95.)

**C4 — Permissive ±40% geometry tolerance allows silent cuts through π-bonds**
`charmmgui2cp2k.py:3314` (`LINK_GEOMETRY_TOLERANCE_FRAC = 0.40`); bounds at 3363-3368.
*Consequence:* For a C–C single bond (expected 1.54 Å) the accepted window is [0.924, 2.156] Å. C=C (1.34), aromatic C–C (1.40), and C≡C (1.20) all fall inside and are flagged `ok`. The QM region gets an H-cap where the force field still expects the π system → QM/MM Hamiltonian mismatch, H-cap with no restoring force, geometry drift, and SCF converging to the wrong electronic state. *(Verifier corrected critical→high on one vote, but two upheld; net Critical.)*
*Fix:* Tighten to ±15% (window [1.31, 1.77] for C–C single) **and** implement bond-order detection (see H2). At minimum, warn loudly when |d − expected| < 5% (a higher-order-bond signature). (Panel 0.96.)

**C5 — `extract_qm_from_pdb` does not validate atom indices against topology NATOM**
`charmmgui2cp2k.py:3004-3051`; called at 17431, consumed at 17540 with no NATOM check. Contrast `extract_qm_from_indices` (3073-3076) which validates.
*Consequence:* Out-of-bounds QM indices propagate three ways: phantom QM/MM links in `detect_link_bonds`, invalid `MM_INDEX` written to `&QM_KIND` (13718-13723) → CP2K runtime failure, and `'X'` element fallback (2998, 3085) that corrupts electron counting and the spin decision. *(Verifiers split — corrected to [low, high]; the reproduce-it verifier upheld high. Retained Critical given the three independent downstream corruption channels; a reviewer may reasonably read this as High.)*
*Fix:* Pass `topo`/`natom` into `extract_qm_from_pdb`; filter to `[1, natom]` and warn+drop out-of-range indices (pattern of 2985-2988), or validate at the 17431 call site before building `qm_set`. (Panel 0.93.)

### HIGH

**H1 — Bond-type information is never extracted or validated**
`charmmgui2cp2k.py:3209-3235` — loop reads `bond_arr[k]`, `bond_arr[k+1]` but never `bond_arr[k+2]` (the type index); alpha selected from elements only (3224-3226).
*Consequence:* IMOMM was designed for single-bond cuts. Without bond order, the wrong α is *always* used for non-single bonds, and intrinsically uncuttable bonds (e.g. carbonyl C=O) cannot be forbidden. Root cause enabling C4, H3, H4.
*Fix:* Read `bond_arr[k+2]`, map to multiplicity via AMBER encoding, forbid non-single cuts (or route to an explicit `pi_bond_cuts` confirmation list). (Panel 0.92.)

**H2 — Unresolved elements in QM region produce invalid CP2K input but only warn**
`charmmgui2cp2k.py:5756-5795` (warn at 5788-5793, no `error()`/`sys.exit`).
*Consequence:* Unresolved element → `qX` POTENTIAL keyword → CP2K "No matching GTH potential found" at parse time. In verbose/batch output the warning is easily missed; user assumes setup succeeded. Sources of unresolved elements: name-inferred pseudo-elements (3045-3046), `element_map` defaulting to `'X'` (2996, 3083), malformed `AMBER_ATOM_TYPE`.
*Fix:* In `generate_qm_kinds`, `error()` + `sys.exit(1)` when `unresolved` is non-empty; or promote to a fatal spin-gate flag. (Panel 0.92.)

**H3 — Peptide C–N amide bonds treated as single bonds (≈10% α error)**
`charmmgui2cp2k.py:252` (`('C','N'): 1.35  # 1.47/1.09`).
*Consequence:* Peptide C–N is ~1.33 Å (π-character); using 1.47 Å places the H-cap at ~1.472 Å instead of ~1.330 Å, mis-coupling QM/MM electrostatics and distorting effective backbone stiffness in protein-dynamics studies. Error ≈10.7%. *(Verifiers corrected to [high, high] — confirmed High.)*
*Fix:* Detect backbone peptide bonds (C(=O)–N) and use α_peptide ≈ 1.22; document that backbone cuts should be avoided. (Panel 0.92.)

**H4 — Aromatic C–C link bonds use single-bond IMOMM α (≈7–8% error)**
`charmmgui2cp2k.py:249-286` (entry `('C','C'): 1.38`; no aromatic entry).
*Consequence:* For conjugated/aromatic systems the H-cap is misplaced by ~7.8% (correct α_aromatic ≈ 1.28), perturbing the embedding field, dipoles, and electronic-state ordering — directly relevant to aromatic active sites. *(Verifier corrected medium→high on the reproduce-it vote; net High.)*
*Fix:* Add aromatic C–C α ≈ 1.28 with ring/aromaticity detection, or document that rings should be fully enclosed in QM. (Panel 0.86.)

**H5 — Missing global system charge-conservation validation**
`charmmgui2cp2k.py:1525-1633` — `verify_prmtop_charges_match_manifest` checks per-atom drift only; no `sum(emitted) == sum(expected)` check anywhere (grep-confirmed).
*Consequence:* Per-atom-bounded drift can accumulate to ~1e-5 e/200 atoms of net charge gain/loss, biasing QM/MM electrostatics, barriers, and pKa-type quantities. The design *asserts* total charge is conserved (1120, 1448) but never proves it.
*Fix:* Add a total-charge balance check; WARN below ~1e-6 e, `RuntimeError` above ~1e-5 e. (Panel 0.81.)

**H6 — Spin-state risk flags NOT collected in the strict gate**
`charmmgui2cp2k.py:1647-1665` (`collect_generation_scientific_concerns` takes only 3 args); spin path `sys.exit(1)` at 19666-19674 fires *before* the gate; `recommend_qm_spin_state` (5249) returns `risk_flags`/`decision_class` the gate never sees.
*Consequence:* Transition-metal QM regions (AMBIGUOUS_REQUIRES_USER) and parity-violating user multiplicities never reach the formal `STRICT_GATE_EXIT_CODE=3` path; CI/batch sees inconsistent exit codes and the formal concerns ledger is blind to a real rigor failure. *(1 verifier refuted; 2 upheld.)*
*Fix:* Pass the `spin_decision` dict into `collect_generation_scientific_concerns`; add a concern when `risk_flags` non-empty or `parity_consistent` is False. (Panel 0.92.)

**H7 — Parity-consistency violation written to file but NOT gated**
`charmmgui2cp2k.py:5620-5641` (writes `PARITY_CONSISTENT: NO`), `20340-20344` (warn only).
*Consequence:* M = 2S+1 parity is a hard physics constraint (Szabo & Ostlund §2.2). A parity-violating multiplicity cannot be a spin eigenstate; CP2K SCF may converge to garbage or crash. Non-interactive mode hard-errors (19691-19699), but `--strict` cannot gate on it because the parity result reaches only the audit file.
*Fix:* Pass `parity_consistent` to the gate; append `('spin_parity', ...)` concern when False. (Panel 0.92.)

**H8 — No test coverage for DFTD4 version compatibility**
`tests/unit/` (grep for `dftd4` → 0 hits; only DFTD3 tested at `test_runtime_data_availability.py:67,79`).
*Consequence:* The C1 gap could regress unnoticed; no guard against analogous version-gating holes.
*Fix:* Add `test_dftd4_requires_cp2k_8_1_in_gating_dict`, `test_dftd4_cli_override_validates_version`, and a version-gate coherence test. (Panel 0.96.)

**H9 — Silent skipping of invalid QM atom indices in `compute_qm_cell`**
`charmmgui2cp2k.py:6075-6077`.
*Consequence:* `qm_indices=[1,2,100,200]` with only 2 atoms present silently yields a 2-atom QM cell — physically wrong QM sizing and electrostatic coupling, no error.
*Fix:* Raise `ValueError` listing out-of-range indices `[1..ncoord]`. (Panel 0.85.)

**H10 — Non-blocking RCUT reduction when MM box limits QM cell**
`charmmgui2cp2k.py:6125-6137`.
*Consequence:* A too-small MM box silently relaxes RCUT (e.g. 8.0→6.5 Å, −19%), changing the multipole cutoff that controls QM–MM coupling accuracy (Laino et al., JCTC 2, 1370, 2006). Warning only; input still generated and easily missed in batch.
*Fix:* Raise an error when `rcut_relaxed` (or require an explicit `--force-reduced-rcut` override). (Panel 0.90.)

**H11 — Basis-set names not validated against known CP2K BASIS_MOLOPT entries**
`charmmgui2cp2k.py:10981-10986` (only non-empty check); substring `MOLOPT`/`DZVP` matching at 10991-10992, 11056, 18749.
*Consequence:* An invalid `BASIS_SET` label sails through generation and fails at CP2K runtime ("No basis set found for element X"); substring heuristics misclassify bogus "MOLOPT-like" names, mis-setting NGRIDS/advisories.
*Fix:* Validate against `QM_BASIS_SET_PRESETS` (9547-9554) or a GTH naming pattern; WARN for custom names so the user knows a `BASIS_SET_FILE_NAME` is required. (Panel 0.95.)

**H12 — `WorkflowPhase` has no `validate()`; MD parameters never range-checked (TUI)**
`charmmgui2cp2k.py:15557-15665`; CLI validates at 17137-17148.
*Consequence:* TUI accepts `mm_nvt_steps -1`, `md_timestep 0.0`, etc., producing invalid CP2K MD settings the CLI would have rejected before generation.
*Fix:* Add `WorkflowPhase.validate()` enforcing `em_max_iter≥1`, `mm_nvt_steps≥1`, `mm_npt_steps≥1`, `md_timestep>0`, `md_temperature>0`, valid ensemble. (Panel 0.86.)

**H13 — Missing validation for unsafe QM/MM production timesteps**
`charmmgui2cp2k.py:9530-9533` (SHAKE-on-QM-H limitation noted), `18094` (`ask_float` with no max), custom preset 1.0 fs at 12571.
*Consequence:* Unconstrained QM H atoms need Δt ≤ 0.5 fs; a 1.0 fs QM/MM run silently drifts in energy and risks SCF failure — wrong results that look valid.
*Fix:* Warn/confirm when `md_timestep > 0.5` under QM/MM. (Panel 0.95.)

### MEDIUM

**M1 — No hard floor blocking physically nonsensical RCUT–cell combinations**
`charmmgui2cp2k.py:10519` — a 0.5 Å cell drives `effective_rcut` to 0.15 Å. *(Verifiers corrected upward — [high, critical, high]; this is arguably the most under-rated finding in the set: an RCUT of 0.15 Å effectively deletes all MM electrostatics, catastrophically wrong energetics/forces. Treat as High-leaning.)*
*Fix:* `if effective_rcut < 1.0: raise ValueError(...)`. (Panel 0.95.)

**M2 — `extract_qm_from_pdb` element extraction may produce invalid element symbols**
`charmmgui2cp2k.py:3042-3047` — regex yields e.g. `'CA'` (Cα → calcium), `'HB'` (non-element). *(Corrected medium→high on chemistry vote.)*
*Consequence:* Silent mis-element → wrong GTH pseudopotential (Ca q2 vs C q4), wrong core configuration.
*Fix:* Validate against `SYMBOL_TO_ATOMIC_NUM`; fall back to topology atomic numbers or require the PDB element column (76-78). (Panel 0.94.)

**M3 — No validation that mdin QM indices fall within [1, NATOM] beyond a one-shot warning**
`charmmgui2cp2k.py:2983-2989`.
*Consequence:* Out-of-range `iqmatoms` silently truncated; user-intended QM atoms dropped, no pause in non-interactive mode.
*Fix:* Error+exit in non-interactive mode; prompt to confirm in interactive. (Panel 0.82.)

**M4 — No validation against partial-residue QM selection**
`charmmgui2cp2k.py:17485-17530` (split-residue detected at 1204-1209 but chemical closedness never checked; residual plan at 1213-1220).
*Consequence:* A QM boundary not at a clean single bond (e.g. backbone-only, side chain dropped) yields broken-bond caps and incorrect frontier MM-charge redistribution.
*Fix:* Topology connectivity check that QM atoms form connected components respecting bonds; warn/confirm/error per mode. (Panel 0.87.)

**M5 — Inconsistent covalent radii for forbidden transition metals**
`charmmgui2cp2k.py:3305-3310` (radii for MN/FE/CO/NI/CU/ZN) vs `325-342` (same elements forbidden). *(Corrected [high,high,high] — strongly upheld.)*
*Consequence:* A forbidden metal bind that slips past confirmation can pass the geometry check because a radius exists — silent fallback violating "no silent modifications."
*Fix:* Remove forbidden metals from `COVALENT_RADII_ANG`, or guard `expected_covalent_bond_length()` to return `None` for forbidden elements. (Panel 0.88.)

**M6 — `verify_qmmm_charge_conservation` missing cross-channel total check**
`charmmgui2cp2k.py:3750-3832` (per-residue and per-link consistency only; returns `ok` at 3817).
*Consequence:* A bug deleting some QM atoms from both the FIST-redistribution and ADD_MM_CHARGE channels would still report "ok"; net charge silently vanishes. Worse with multiple QM residues.
*Fix:* Add cross-channel identity `|Σ residual.removed + Σ link.M1_CHARGE_E − Σ qm_atom.original_charge| ≤ tol`; pass `qm_indices`/`topo` in. (Panel 0.82.)

**M7 — Parity check fails to warn when electron count unknown (interactive mode)**
`charmmgui2cp2k.py:19613-19626`; `validate_multiplicity_parity` returns `(None, msg)` at 5231. *(Corrected [medium,high,high].)*
*Consequence:* When elements are unresolved, electron count is `None`; `if parity_ok is False:` misses the `None` branch, so an absurd multiplicity is accepted with no warning that parity is unverifiable.
*Fix:* Change to `if parity_ok is not True:` and message that count is unknown. (Panel 0.97.)

**M8 — Identical parity-check logic bug in non-interactive mode**
`charmmgui2cp2k.py:19691-19699`. *(Corrected [medium,high,high].)*
*Consequence:* Defensive gap — `if parity_ok is False` again misses `None`; safe only because of the upstream exit at 19674, fragile under refactor.
*Fix:* `if parity_ok is not True:`; distinguish "parity-inconsistent" from "parity-unverifiable" in the message. (Panel 0.94.)

**M9 — Duplicate M1 frontier atoms not gated as a concern**
`charmmgui2cp2k.py:3398-3424` (detector), `17744-17773` (warn only). *(1 verifier refuted; 2 upheld; corrected toward high on reproduce-it vote.)*
*Consequence:* One MM atom serving as frontier for two cuts gives a doubly-perturbed, non-physical embedding (Laino 2006; Senn & Thiel 2009 §3.1; Lin & Truhlar 2007 §2.2 each assume one M1 per cut).
*Fix:* Collect duplicate-M1 as a gate concern. (Panel 0.90.)

**M10 — Unresolved elements in electron count not gated as a concern**
`charmmgui2cp2k.py:4492-4650`, `5110-5128` (added to `risk_flags`, never to the gate). *(1 refuted; 2 upheld.)*
*Consequence:* Z-fallback valence vs GTH q-tag mismatch can flip parity, yielding a converged wavefunction for the wrong spin manifold — silent.
*Fix:* Pass `qm_e_meta` to the gate; concern when `unresolved_elements` non-empty. (Panel 0.79.)

**M11 — Inconsistent exit-code convention across rigor checks**
`charmmgui2cp2k.py:19666-19674` & `19699` (`sys.exit(1)`) vs `21070-21077` (`STRICT_GATE_EXIT_CODE=3`). *(1 refuted; 2 upheld; corrected [high,high].)*
*Consequence:* CI/batch cannot distinguish a rigor-gate failure from a transient/input error; some failures may be wrongly retried.
*Fix:* Route all rigor failures through the formal gate; standardize on exit 3 under `--strict`. (Panel 0.91.)

**M12 — Hardcoded `EWALD_PRECISION` independent of QM cell and RCUT**
`charmmgui2cp2k.py:13714`. *(1 verifier marked "not_a_bug"; 1 refuted; net just-confirmed — lowest-confidence Medium.)*
*Consequence:* Fixed 1E-6 may be unachievable/slow at tight RCUT and over-conservative at large RCUT; not user-tunable. Marginal.
*Fix:* Scale precision with effective RCUT or expose as a policy parameter. (Panel 0.87; weakest survivor.)

**M13 — Warnings not blocking generation, easily overlooked**
`charmmgui2cp2k.py:20997, 21004` (~15-20 non-blocking `warnings.append`). *(1 refuted; 2 upheld.)*
*Consequence:* RCUT/box-limited reductions surface only in an end-of-run "Warnings requiring review" block; batch users miss them. The umbrella symptom behind H10/M1 — "warn-don't-block" defeats `feedback_no_silent_modifications`.
*Fix:* Promote RCUT/box-limited warnings to errors, or require an explicit `--accept-reduced-rcut` flag. (Panel 0.87.)

**M14 — ADMM aux-basis selection does not check element coverage before recommending**
`charmmgui2cp2k.py:11037-11061` (recommends cFIT3 at 11061 without checking `FIT3_AUX_ELEMENTS`).
*Consequence:* User with {FE,C,H} is told to use cFIT3, then rejected post-hoc because FE is uncovered → forced to disable ADMM or pass `--admm-allow-unverified`. Friction + risk, not a wrong number.
*Fix:* Check candidate coverage during recommendation; recommend the broadest-coverage basis or disabling ADMM. (Panel 0.94.)

**M15 — MGRID CUTOFF/REL_CUTOFF advisory-only, no hard floor**
`charmmgui2cp2k.py:11755-11827` (WARN at 11779-11788, never aborts); defaults safe (500/60 at 12924). *(Corrected medium→high on reproduce-it vote.)*
*Consequence:* A user overriding CUTOFF below ~280 Ry for DZVP/TZVP MOLOPT gets Gaussian-projection artifacts → spurious force oscillations → silently wrong MD trajectories (VandeVondele–Hutter regime, cited at 11748).
*Fix:* Optional `--strict-convergence` hard error below the recommended floors, or a CRITICAL warning requiring `--accept-under-converged-mgrid`. (Panel 0.93.)

**M16 — Timestep mismatch between MM stages and QM/MM warmup not validated**
`charmmgui2cp2k.py:18261-18301`. *(1 refuted; 2 upheld.)*
*Consequence:* `mm_timestep` larger than both warmup and production breaks conservative staging; not catastrophic but unconventional.
*Fix:* Warn (non-blocking) when `mm_timestep > warmup_timestep`. (Panel 0.93.)

### LOW

**L1 — Default 100 Å MM box may mask genuine system-size problems**
`charmmgui2cp2k.py:12178, 17344` (also second warning at 20994). *(Corrected toward medium on reproduce-it vote.)*
*Consequence:* A box-less RST7 silently gets a 100 Å cube that may not match the real system; warning missable in batch.
*Fix:* Smaller/safer default with a stronger warning, or require `--box-override` / treat as error in strict mode. (Panel 0.76.)

**L2 — Tolerance comment is factually incorrect**
`charmmgui2cp2k.py:3311-3313` — claims the ±40% band "catches clashes and non-bonds," but π-bonds at 1.34/1.40/1.20 Å sit inside the accepted window.
*Consequence:* Documentation hazard — masks C4 from future maintainers.
*Fix:* Rewrite the comment to state explicitly that double/aromatic/triple bonds pass silently. (Panel 0.89.)

**L3 — EXT_RESTART velocity restoration for stage 40 is implicit, not explicit**
`charmmgui2cp2k.py:14073-14080, 14092-14099` (`prod_restart_vel=True` outside `md_state_flags`). *(1 refuted; 2 upheld.)*
*Consequence:* Maintainability — a refactor assuming `md_state_flags` controls all restart flags could silently break velocity continuity in stage 40.
*Fix:* Fold `restart_vel` into `md_state_flags`. (Panel 0.86.)

---

## 3. Considered but dismissed (adversarial panel killed these)

- **Residual charge not applied to PRMTOP / missing AMBER_CHARGE_SCALE (18.2223)** — refuted: `system_qmmm.prmtop` artifacts already carry post-redistribution charges within float tolerance.
- **Torsion/1-4 preservation calls `_find_flag_sections` redundantly in loop** — false alarm: it is called every iteration *by design* (2268-2269) so indices recompute after each slice mutation; downstream guard `_verify_preserve_torsion_14_flags()` (2290-2331) re-parses the output.
- **Zero-LJ hydrogen detection uses wrong NONBONDED_PARM_INDEX formula** — verified correct: `ntypes*(type_idx-1)+type_idx` (1961) reproduces the diagonal `[1,3,6,10,15,21,28]` for ntypes=7.
- **Residual charge plan computed without E16.8 rounding** — conceptually valid but empirically guarded: `verify_prmtop_charges_match_manifest` (1525) models E16.8 quantization in its tolerance.
- **`estimate_qm_electrons_for_spin` crashes on iterator input** — technically true (`len(iterator)`), but every caller passes a list; not a rigor risk.
- **"Mission says five concerns, code has three"** — false premise: no mission doc specifies five categories.

---

## 4. Coverage & blind spots

This was a **static / structural** audit. The following were **NOT** exercisable and remain open risk:

- **No live CP2K run.** Every "CP2K will fail at parse/SCF time" consequence (C1, H2, H11, M15) is inferred from CP2K's documented behavior, not observed. The actual error messages, and whether a given CP2K build silently degrades vs. hard-fails, were not confirmed end-to-end.
- **No transition-metal / metalloenzyme system was run.** The forbidden-link logic (C2, M5), ADMM metal coverage (C3, M14), and metal spin-ambiguity gating (H6, M10) were validated by code path and synthetic inputs (e.g. `{'FE': [0]}`), **not** on a real metal-containing topology with a coordination sphere at the QM/MM boundary. *(Note: the project's flagship case, LAAO, is a flavoenzyme, not a metalloprotein per the latest dev-plan correction — so the most safety-critical metal path may be under-exercised in practice precisely because the headline use case does not hit it.)*
- **No production AMBER/CHARMM-GUI dataset beyond demo artifacts.** Charge-conservation findings (H5, M6) were reasoned from code + small demo prmtops; accumulation behavior on a 10⁴–10⁵-atom solvated system is unmeasured.
- **TUI gates assessed by reading phase classes, not by driving the TUI.** C2, C3, H12 are confirmed as *absent code*, which is unambiguous, but the resulting end-to-end TUI failure was not reproduced interactively.
- **Bond-order / π-bond cuts (C4, H1-H4) never tested against a real bonded prmtop** with double/aromatic/peptide bonds at the chosen boundary; α-error magnitudes are from literature reference lengths, not from generated `&LINK` blocks on a real cut.
- **`generated_output` dimension reported 0 findings** — this likely reflects *no auditor coverage* of the final emitted `.inp` as an integrated whole, not a clean bill of health. A golden-file / CP2K-`--check`-parse test of a full generated input is a genuine gap.
- **Numerical accuracy of IMOMM α placement** was checked as ratios, not by computing actual cap coordinates in 3D and comparing to a reference QM/MM engine.

---

## 5. Prioritized remediation plan

**P0 — Block silently-wrong or non-runnable output (do before any production use):**
1. **C4 + H1:** Read `bond_arr[k+2]`, detect bond order, **forbid non-single cuts** (or explicit-confirm list); tighten `LINK_GEOMETRY_TOLERANCE_FRAC` to ≤0.15. Then fix the comment (L2). *(charmmgui2cp2k.py:3209-3235, 3314, 3311-3313)*
2. **C1 + H8:** Wire `(8,1)` DFTD4 into `CP2K_KEYWORD_MIN_VERSION`, validate in the `--dispersion-scheme` override path, add the three DFTD4 version-gating tests. *(6483-6510, ~20466, 13553-13558; tests/unit/)*
3. **C2 + C3 + H12:** Give the TUI the gates the CLI already has — `BoundaryPhase.validate()` forbidden-link check, `MethodPhase.validate()` ADMM coverage, `WorkflowPhase.validate()` MD ranges. *(15277-15280, 15284-15396, 15557-15665)*
4. **C5 + H9 + M1:** NATOM-validate QM indices in `extract_qm_from_pdb` and `compute_qm_cell`; add a hard RCUT floor (`effective_rcut ≥ 1.0`). *(3004-3051, 6075-6077, 10519)*

**P1 — Convert "knows-but-only-warns" into gated failures:**
5. **H6 + H7 + M9 + M10 + M11:** Extend `collect_generation_scientific_concerns` to accept `spin_decision` + `qm_e_meta`; gate on risk_flags, parity inconsistency, duplicate-M1, unresolved elements; route all rigor exits through `STRICT_GATE_EXIT_CODE`. *(1647-1665, 19666-19699, 21070-21077)*
6. **H2 + M2 + M7 + M8:** Abort on unresolved QM elements; validate inferred element symbols against `SYMBOL_TO_ATOMIC_NUM`; fix both `is not True` parity branches. *(5756-5795, 3042-3047, 19613-19626, 19691-19699)*
7. **H10 + H13 + M13 + M15:** Make RCUT-reduction, unsafe-timestep, and under-converged-MGRID blocking (or behind explicit `--force-*` flags). *(6125-6137, 18094, 20997, 11755-11827)*

**P2 — Correctness hardening & UX:**
8. **H3 + H4 + M5:** Add peptide and aromatic IMOMM α entries with detection; remove forbidden metals from `COVALENT_RADII_ANG` (or guard the length function). *(252, 249-286, 3305-3310)*
9. **H5 + M6:** Add global and cross-channel charge-conservation checks. *(1525-1633, 3750-3832)*
10. **H11 + M14:** Validate basis-set names; move ADMM element-coverage into the recommendation phase. *(10981-10986, 11037-11061)*
11. **M3 + M4 + M16 + L1 + L3 + M12:** mdin out-of-range handling, partial-residue connectivity check, MM/warmup timestep consistency warning, safer default box, explicit `restart_vel` flag, adaptive `EWALD_PRECISION`.

**P3 — Close the audit's own blind spots:**
12. Add a **golden-file integration test** that generates a full `.inp` and runs `cp2k --check` (parse-only) in CI — this directly addresses the empty `generated_output` coverage.
13. Add a **transition-metal-at-boundary regression fixture** (real prmtop with a metal coordination sphere crossing the QM/MM cut) to exercise C2/C3/M5/H6 end-to-end.
14. Run a **large solvated production prmtop** through charge verification to bound real-world charge drift (H5/M6).

**Bottom line:** the arithmetic-level rigor is sound, but the tool currently *detects* most of its serious problems and then *proceeds anyway*. Closing the P0/P1 items — chiefly bond-order-aware link chemistry, DFTD4 version gating, TUI gate parity, and converting warnings into gated failures — would move `charmmgui2cp2k` from "conditionally trustworthy with expert oversight" to publication-grade.


