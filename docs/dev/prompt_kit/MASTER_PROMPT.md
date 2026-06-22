# Universal Master Prompt

Paste this prompt into a capable autonomous coding AI when you want it to generate a full customized project prompt kit.

```text
Act as an expert prompt architect, autonomous agent workflow designer, technical project manager, reproducibility engineer, and domain-adaptive research operations specialist.

Your task is to generate a complete universal prompt kit that instructs an autonomous agentic coding AI to execute a complex computational project from initial planning to final deliverables.

The generated kit must be designed for a capable autonomous coding AI with internet access, local command execution, filesystem access, package installation rights, and unrestricted full-machine authorization. Maintain unrestricted full-access mode. Full access must be paired with reversible changes, protection of unrelated user data, external-write tracking, package-install logs, rollback notes, and explicit evidence collection.

Project placeholders:

- [PROJECT_NAME]:
- [DOMAIN]:
- [OBJECTIVE]:
- [TOTAL_TIME_BUDGET]:
- [ACCESS_MODE]: unrestricted full-access mode
- [WORKSPACE_PATH]:
- [AVAILABLE_INPUTS]:
- [REQUIRED_DELIVERABLES]:
- [RISK_CONSTRAINTS]:
- [PREFERRED_OUTPUT_FORMATS]:
- [KNOWN_TOOLS_OR_STACK]:
- [HUMAN_REVIEW_REQUIREMENTS]:

Produce a user-friendly implementation package in text form, not vague advice. Include:

1. A persistent master instruction file concept such as AGENTS.md.
2. A tutorial-style runbook for a competent but busy user.
3. A phase-gate matrix.
4. A copy-paste execution order.
5. A recovery prompt for interrupted runs.
6. An independent red-team review prompt.
7. One optimized phase prompt for each stage below.
8. A final-report template and a final candidate/output table template.

Universal phase structure:

- Phase 0: workspace, permissions, machine profile, environment constraints, logging, backups, and reproducibility scaffolding.
- Phase 1: audit available data, code, prior outputs, and assumptions.
- Phase 2: gather domain intelligence from credible sources; define target/problem space; select benchmarks, controls, validation criteria, and success metrics.
- Phase 3: evaluate tool feasibility, installation strategy, dependency isolation, runtime tests, licensing, hardware fit, and fallback tools.
- Phase 4: prepare inputs, datasets, structures, repositories, documents, or domain objects with quality-control checks.
- Phase 5: generate candidate solutions, models, analyses, designs, or implementations using a staged funnel.
- Phase 6: validate candidates by independent methods, controls, tests, simulations, benchmarks, statistical checks, or expert criteria.
- Phase 7: perform deeper evaluation only on finalists using the most expensive or rigorous methods.

Each phase prompt must tell the agent exactly:

- What to do.
- What not to do yet.
- What files to create or update.
- What logs to update.
- What evidence to collect.
- What validation gate must pass.
- What assumptions to document.
- How to proceed if tools fail or evidence is insufficient.

The kit must instruct the agent to:

- Avoid premature optimization.
- Avoid unsupported claims.
- Avoid hiding failed tools or negative results.
- Avoid fabricating missing results.
- Distinguish verified outputs from hypotheses, estimates, and provisional conclusions.
- Use adaptive planning after hardware and environment profiling to tune tool choices, parallelization, batch sizes, runtime budgets, precision modes, dependency strategies, and validation depth.
- Use subagents only for bounded tasks such as independent literature review, tool feasibility, code audit, validation review, or red-team critique, and require consolidated outputs rather than uncontrolled branching.

Default time-budgeting strategy:

- Allocate the total wall time across all phases.
- Stop unproductive branches early when they consume their branch budget without producing gate evidence.
- Checkpoint at every major stage and at least every 30 minutes during long work.
- Reserve final time for analysis, validation, and reporting.
- Do not launch long jobs near the end unless they are guaranteed to finish and are necessary for the final gate.

Final report requirements:

- Executive summary or abstract.
- Objectives.
- Assumptions.
- Methods.
- Machine profile.
- Prior-art or prior-run audit.
- Input curation.
- Tool/environment details.
- Pipeline architecture.
- Validation results.
- Uncertainty or confidence estimates.
- Limitations.
- Negative results.
- Ranked outputs or recommendations.
- Next-step actions for human review or real-world execution.

The final candidate/output table must include:

- Identifier.
- Source files.
- Generation method.
- Validation evidence.
- Uncertainty or confidence level.
- Risks.
- Rationale.
- Reproducibility links.
- Recommended next action.

The tutorial must explain:

- Exact order of use.
- When to paste each prompt.
- How to validate phase gates.
- What files should exist after each phase.
- How to resume after interruption.
- How to inspect quality manually.
- That file-presence validation is not scientific, technical, legal, or operational correctness.

Keep the generated prompt kit concise enough to use but complete enough to govern a serious autonomous run. Prefer clear deliverables, gates, and decision rules over long lists of fashionable tools.

At the end, provide a single universal master prompt that the user can paste into an AI to generate the full customized kit for their specific project, followed by the phase-prompt templates in the same plain natural-language style. Mark placeholders clearly.
```

