# Phase 1 Prompt: Inventory Audit

```text
Phase 1 objective: audit available data, code, prior outputs, and assumptions before any project-specific interpretation.

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

1. Read Phase 0 outputs and follow the logging/backup rules.
2. Inventory workspace files, directories, sizes, modification times, and relevant hashes.
3. Classify files as source input, derived input, code, config, prior output, log, cache, or unknown.
4. Inspect small text/config files directly. For large files, sample headers/metadata and avoid expensive full reads unless necessary.
5. Audit code entry points, CLI options, dependencies, tests, and generated-output behavior.
6. Audit prior outputs and determine whether their provenance is sufficient to trust them.
7. Extract domain-neutral facts from inputs without overinterpreting them.
8. Build an assumption register: verified facts, provisional assumptions, missing inputs, and user decisions needed.
9. Build a risk register: reproducibility risks, data integrity risks, scientific/technical risks, runtime risks, and safety/permission risks.

What not to do yet:

- Do not install major tools.
- Do not transform original inputs.
- Do not claim scientific correctness.
- Do not select final methods or benchmarks before Phase 2.

Files to create/update:

- `inventory_manifest.*`
- `file_hashes.*` or `file_metadata.*`
- `prior_run_audit.*`
- `code_audit_notes.*`
- `assumption_register.*`
- `risk_register.*`
- Current phase log and command log.

Evidence to collect:

- File listings, hashes/metadata, sampled headers, parsed config values, code entry points, dependency hints, and prior-output provenance.

Gate to pass:

Phase 1 passes only if available inputs and prior outputs are identified, source/derived boundaries are clear, key assumptions are explicit, and missing information is listed.

If tools fail or evidence is insufficient:

- Use simple shell inspection fallbacks.
- Label unparseable files as unknown, not verified.
- Stop if required inputs are missing or ambiguous enough to invalidate the objective.

End with:

- Phase 1 gate decision.
- Inventory summary.
- Verified facts versus assumptions.
- Prior outputs that are trusted, partially trusted, or untrusted.
- Risks that must shape Phase 2.
```

