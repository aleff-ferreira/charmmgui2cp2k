# Phase 6 Prompt: Independent Validation

```text
Phase 6 objective: validate candidates by independent methods, controls, tests, simulations, benchmarks, statistical checks, or expert criteria.

Project placeholders:

- [PROJECT_NAME]:
- [DOMAIN]:
- [OBJECTIVE]:
- [WORKSPACE_PATH]:
- [RUN_DIRECTORY]:
- [REQUIRED_DELIVERABLES]:
- [TOTAL_TIME_BUDGET_REMAINING]:
- [RISK_CONSTRAINTS]:

What to do:

1. Read Phase 0-5 outputs.
2. Validate candidates using methods independent from the generation method wherever possible.
3. Run benchmarks, controls, tests, simulations, statistical checks, parser checks, expert criteria, or cross-tool comparisons defined in Phase 2.
4. Record validation commands, parameters, versions, runtime, hardware use, and outputs.
5. Estimate uncertainty or confidence for each candidate.
6. Compare against controls and acceptance thresholds.
7. Investigate failures enough to classify them as candidate defects, tool defects, input defects, or inconclusive results.
8. Rank candidates for Phase 7 finalist evaluation.
9. Update limitations, negative results, and risks.

What not to do yet:

- Do not run the most expensive finalist-only methods until finalists are selected.
- Do not validate only with the same method used to generate candidates unless no independent method exists and that limitation is explicit.
- Do not overclaim inconclusive validation.

Files to create/update:

- `validation_report.*`
- `control_results.*`
- `benchmark_results.*`
- `uncertainty_estimates.*`
- `candidate_scores.*`
- `negative_results.*`
- Current phase log and command log.

Evidence to collect:

- Validation outputs, logs, control outcomes, benchmark scores, statistical summaries, plots/tables if useful, and failure classifications.

Gate to pass:

Phase 6 passes only if candidates have independent validation evidence, controls are interpreted, uncertainty/confidence is assigned, and finalists are selected by predeclared criteria.

If tools fail or evidence is insufficient:

- Apply fallback validation from Phase 3.
- Lower confidence instead of inventing certainty.
- Stop if no candidate can be validated enough for finalist evaluation.

End with:

- Phase 6 gate decision.
- Validation summary.
- Candidate ranking.
- Finalists selected for Phase 7.
- Uncertainty/confidence and key risks.
- Whether Phase 7 is authorized.
```

