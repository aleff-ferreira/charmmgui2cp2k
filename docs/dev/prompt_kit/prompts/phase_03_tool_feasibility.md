# Phase 3 Prompt: Tool Feasibility

```text
Phase 3 objective: evaluate tool feasibility, installation strategy, dependency isolation, runtime tests, licensing, hardware fit, and fallback tools.

Project placeholders:

- [PROJECT_NAME]:
- [DOMAIN]:
- [OBJECTIVE]:
- [WORKSPACE_PATH]:
- [RUN_DIRECTORY]:
- [KNOWN_TOOLS_OR_STACK]:
- [TOTAL_TIME_BUDGET_REMAINING]:
- [RISK_CONSTRAINTS]:

What to do:

1. Read Phase 0-2 outputs.
2. List candidate tools and why each is relevant to the defined metrics and validation criteria.
3. Prefer tools already present and compatible with the workspace.
4. For missing dependencies, choose an isolated install strategy when practical: virtual environment, conda/mamba environment, container, local binary, or project-local cache.
5. Record all installations, versions, channels, URLs, licenses, and environment variables.
6. Run small smoke tests or parser checks before any large jobs.
7. Evaluate hardware fit: CPU/GPU/RAM/disk, parallelism, expected runtime, precision modes, batch sizes, checkpointing.
8. Define fallback tools and graceful degradation paths.
9. Decide which tools are authorized for Phase 4 and later.

What not to do yet:

- Do not process full datasets or run production simulations.
- Do not tune deeply before basic feasibility is proven.
- Do not hide failed installs or failed smoke tests.
- Do not make global environment changes without logging them.

Files to create/update:

- `tool_feasibility_matrix.*`
- `install_log.*`
- `smoke_tests.*`
- `license_notes.*`
- `hardware_fit_plan.*`
- `fallback_plan.*`
- Current phase log and command log.

Evidence to collect:

- Tool versions, command outputs, import checks, parser checks, license references, installation commands, hardware-fit rationale, and fallback decisions.

Gate to pass:

Phase 3 passes only if required tools either work or have credible fallbacks, installation state is reproducible, licenses are acceptable for the intended use, and runtime strategy fits the actual machine and time budget.

If tools fail or evidence is insufficient:

- Try the defined fallback.
- Reduce scope or validation depth if justified.
- Stop if no feasible toolchain can meet the required deliverables.

End with:

- Phase 3 gate decision.
- Selected toolchain.
- Failed tools and fallbacks.
- Installation/environment summary.
- Runtime and resource plan.
- Whether Phase 4 is authorized.
```

