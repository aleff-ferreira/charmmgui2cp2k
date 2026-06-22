# Phase 4 Prompt: Input Preparation And QC

```text
Phase 4 objective: prepare inputs, datasets, structures, repositories, documents, or domain objects with quality-control checks.

Project placeholders:

- [PROJECT_NAME]:
- [DOMAIN]:
- [OBJECTIVE]:
- [WORKSPACE_PATH]:
- [RUN_DIRECTORY]:
- [AVAILABLE_INPUTS]:
- [REQUIRED_DELIVERABLES]:
- [RISK_CONSTRAINTS]:

What to do:

1. Read Phase 0-3 outputs.
2. Work only on derived copies unless a reversible in-place edit is explicitly necessary.
3. Create a curated input area under the run directory or a clearly named project output folder.
4. For every transformation, record source file, command/tool, parameters, version, output path, and reason.
5. Run QC checks appropriate to [DOMAIN] and Phase 2 validation criteria.
6. Mark inputs as accepted, rejected, corrected, or provisional.
7. Preserve rejected inputs and explain why they were rejected if storage permits.
8. Update provenance links so every prepared input can be traced to source files.
9. Update assumptions and risks discovered during QC.

What not to do yet:

- Do not generate final candidates.
- Do not run expensive finalist evaluation.
- Do not silently fix or normalize inputs.
- Do not discard negative QC results.

Files to create/update:

- `curated_inputs_manifest.*`
- `transformation_log.*`
- `qc_report.*`
- `rejection_log.*`
- `provenance_map.*`
- `assumption_register.*`
- `risk_register.*`
- Current phase log and command log.

Evidence to collect:

- Input hashes/metadata before and after transformation, QC command outputs, schema/format validation, sanity plots/tables if relevant, and rejection reasons.

Gate to pass:

Phase 4 passes only if prepared inputs are reproducible, QC status is explicit, source provenance is retained, and unresolved input risks are acceptable for candidate generation.

If tools fail or evidence is insufficient:

- Use fallback parsers or validators from Phase 3.
- Keep questionable inputs provisional.
- Stop if input defects invalidate the objective or validation criteria.

End with:

- Phase 4 gate decision.
- Prepared input summary.
- QC pass/fail/provisional table.
- Transformations performed.
- Input risks carried into Phase 5.
- Whether Phase 5 is authorized.
```

