# Phase 5 Prompt: Candidate Generation

```text
Phase 5 objective: generate candidate solutions, models, analyses, designs, or implementations using a staged funnel.

Project placeholders:

- [PROJECT_NAME]:
- [DOMAIN]:
- [OBJECTIVE]:
- [WORKSPACE_PATH]:
- [RUN_DIRECTORY]:
- [REQUIRED_DELIVERABLES]:
- [TOTAL_TIME_BUDGET_REMAINING]:
- [RISK_CONSTRAINTS]:
- [PREFERRED_OUTPUT_FORMATS]:

What to do:

1. Read Phase 0-4 outputs.
2. Define a staged funnel before generation:
   - Fast broad generation.
   - Cheap sanity screening.
   - Medium-cost refinement.
   - Finalist selection for Phase 6.
3. Generate candidates using reproducible methods and recorded parameters.
4. Assign stable identifiers to every candidate.
5. Keep source files, generation commands, tool versions, random seeds, and parameter settings.
6. Rank candidates using Phase 2 metrics and Phase 4 QC constraints.
7. Record rejected candidates and rejection reasons.
8. Avoid premature optimization; first establish viable candidates and evidence.
9. Stop branches that consume their branch budget without producing useful evidence.

What not to do yet:

- Do not claim final validity.
- Do not run the most expensive validation.
- Do not hide failed generations.
- Do not change success metrics to favor a candidate.

Files to create/update:

- `candidate_manifest.*`
- `generation_log.*`
- `ranking_funnel.*`
- `discard_log.*`
- Candidate output files in a stable directory.
- Current phase log and command log.

Evidence to collect:

- Commands, parameters, seeds, source input links, generated files, preliminary scores, failure logs, and resource usage.

Gate to pass:

Phase 5 passes only if candidates are reproducible, ranked by predeclared criteria, and enough evidence exists to choose candidates for independent validation.

If tools fail or evidence is insufficient:

- Use Phase 3 fallbacks.
- Reduce candidate breadth before sacrificing logging.
- Stop if candidate generation cannot produce reproducible outputs.

End with:

- Phase 5 gate decision.
- Candidate count and identifiers.
- Top candidates and rationale.
- Rejected candidates and reasons.
- Validation priorities for Phase 6.
- Whether Phase 6 is authorized.
```

