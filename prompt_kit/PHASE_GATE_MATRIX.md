# Phase Gate Matrix

Use this matrix as the acceptance standard for the autonomous run.

| Phase | Purpose | Required Files | Gate Evidence | Do Not Proceed If |
|---|---|---|---|---|
| 0 Workspace bootstrap | Establish unrestricted full-access execution, reproducibility scaffolding, machine profile, logs, backups, and constraints | `run_manifest.*`, `machine_profile.*`, `environment_report.*`, `command_log.*`, `backup_manifest.*`, `external_writes.*` | Workspace root, access mode, hardware, OS, interpreter/tool versions, storage, backup plan, and time budget are documented | Critical files cannot be protected; available permissions are unclear; no log path exists |
| 1 Inventory audit | Audit available files, prior outputs, code, assumptions, and missing inputs | `inventory_manifest.*`, `file_hashes.*`, `prior_run_audit.*`, `assumption_register.*`, `risk_register.*` | Inputs and prior outputs are identified with hashes/sizes; assumptions and gaps are explicit | Required inputs are missing or ambiguous; prior outputs are accepted without provenance |
| 2 Domain intelligence | Gather credible sources, define problem/target space, benchmarks, controls, validation criteria, and success metrics | `domain_brief.*`, `sources.*`, `benchmark_control_plan.*`, `success_metrics.*` | Sources are credible and cited; success metrics are measurable; controls and validation criteria are defined | Claims rely on memory only; benchmarks are not relevant; metrics are vague |
| 3 Tool feasibility | Evaluate tools, installation strategy, dependency isolation, runtime tests, licensing, hardware fit, and fallbacks | `tool_feasibility_matrix.*`, `install_log.*`, `smoke_tests.*`, `license_notes.*`, `fallback_plan.*` | Chosen tools run or have documented fallbacks; licenses and hardware fit are reviewed | Core tools cannot run and no fallback exists; installs are unlogged; license terms conflict |
| 4 Input preparation | Prepare inputs, datasets, structures, repositories, documents, or domain objects with QC checks | `curated_inputs_manifest.*`, `qc_report.*`, `transformation_log.*`, `rejection_log.*` | Every prepared input has provenance, transformation notes, QC status, and known limitations | Inputs are silently changed; QC fails without resolution; derived files cannot be traced |
| 5 Candidate generation | Generate candidate solutions, models, analyses, designs, or implementations through a staged funnel | `candidate_manifest.*`, `generation_log.*`, `ranking_funnel.*`, `discard_log.*` | Candidate IDs, source files, methods, parameters, and preliminary ranking rationale are recorded | Candidates are generated without reproducible methods; negative results are hidden |
| 6 Validation | Validate candidates by independent methods, controls, tests, simulations, benchmarks, statistics, or expert criteria | `validation_report.*`, `control_results.*`, `uncertainty_estimates.*`, `candidate_scores.*` | Independent checks agree enough to rank or reject candidates; uncertainty and failures are explicit | Validation only repeats generation method; controls fail; results are overclaimed |
| 7 Finalist deep evaluation | Apply the most rigorous or expensive methods only to finalists and produce final deliverables | `finalist_deep_eval.*`, `final_report.*`, `final_candidate_table.*`, `handoff_notes.*` | Finalists are ranked with evidence, risks, reproducibility links, and recommended next action | Finalists were chosen without Phase 6 evidence; expensive jobs cannot finish; final report lacks limitations |

## Universal Gate Rules

- A phase passes only when required files exist and their contents support the decision.
- Failed tools and negative results must be logged.
- Unsupported claims must be labeled as hypotheses, estimates, or provisional conclusions.
- The agent must not fabricate missing results.
- If evidence is insufficient, either gather more evidence within budget or stop with a clear handoff note.

