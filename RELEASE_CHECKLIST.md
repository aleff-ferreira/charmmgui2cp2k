# Release checklist (Phase 6 — FAIR public release)

Steps to take the local repository to a citeable public release, in dependency
order. Items marked **[user]** require decisions/credentials only the maintainer
has; the rest are mechanical.

## 1. Identity & metadata **[user]**
- [ ] Fill author identity: `LICENSE` (copyright holder), `CITATION.cff`
      (given-names/family-names/affiliation/ORCID), `paper/manuscript.md` authors.
- [ ] Replace `REPLACE_ME` / `TODO_URL` repository URLs in `README.md` and
      `CITATION.cff` with the real GitHub URL.

## 2. Internal scaffolding — DONE (moved to docs/dev/)
The autonomous-agent working material has been moved out of the public top level
into `docs/dev/` (reversible; `git rm -r docs/dev/` for total removal):
- [x] `AGENTS.md` → `docs/dev/AGENTS.md`
- [x] `prompt_kit/`, `prompt_kit_tui/` → `docs/dev/`
- [x] `PUBLICATION_READINESS_PLAN.md` → `docs/dev/`
- [ ] **[user]** decide whether to delete `docs/dev/` entirely before release.
- [x] `.gitignore` excludes `.claude/`, envs, generated outputs.

## 3. Make the repository public **[user]**
- [ ] Create the public GitHub repo and push `main`
      (`gh repo create … --public --source=. --push`).
- [ ] **This starts the JOSS 6-month public-development clock** — do it early.
- [ ] Verify CI (`.github/workflows/ci.yml`) is green on GitHub.

## 4. Versioned archive (FAIR F1.2 / R1.1)
- [ ] Tag a release (`v0.1.0`; matches `__version__` and `CITATION.cff`).
- [ ] Enable the Zenodo–GitHub integration; cut the release to mint a DOI.
- [ ] Record the DOI in `README.md`, `CITATION.cff`, and the manuscript.

## 5. Reproducibility capsule
- [ ] Pin a dependency manifest beyond `environment-tui.yml` (CP2K version used
      for validation: 2025.2; AmberTools 24 for fixtures/ParmEd).
- [ ] Document exact commands to regenerate every validation figure/number
      (`validation/README.md` already lists them).
- [ ] Optional: Code Ocean / container image reproducing the validation results.

## 6. Manuscript
- [ ] Complete `paper/manuscript.md`: insert citations, the LAAO flavoenzyme
      case study (§3.4) and BioExcel benchmark results (§3.5), and figures
      (architecture diagram, TUI screenshot, NVE plot, boundary-scheme probe,
      cross-code table).
- [ ] Confirm venue (email the *Briefings in Bioinformatics* editor if still
      considered; otherwise submit to *Bioinformatics*/*JCIM* Application Note).
- [ ] Prepare the parallel JOSS submission (statement of need, state of the
      field, automated tests + CI — all already in place).

## Status of the publication-readiness plan
- Phases 1–3: complete (repo+CI, scientific test net, runtime/geometry/strict
  hardening, real-CP2K parse).
- Phase 4: A4.1 (NVE conservation) + A4.2/A4.3 (single-point reproducibility &
  boundary over-polarization) done on the demo system; A4.4 (BioExcel) and A4.5
  (LAAO headline) await external/production data — harness ready.
- Phase 5: B4/B5/B6/B8 done (embedded provenance, --demo, machine-readable
  provenance, resize tests + Ctrl-P fix).
- Phase 6: manuscript draft + this checklist; remaining items above are
  user-gated.
