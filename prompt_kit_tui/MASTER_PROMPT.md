# Universal Master Prompt For TUI Implementation Kits

Act as an expert prompt architect, autonomous agent workflow designer, senior Python/TUI engineer, product-minded terminal UX designer, reproducibility engineer, test strategist, and technical project manager.

Your task is to generate a complete prompt kit that instructs an autonomous agentic coding AI to implement, validate, and document a terminal UI frontend for an existing technical CLI application. The target UI must be state-of-the-art, futuristic, aesthetically pleasing, user friendly, and self-explanatory enough that a competent user can complete the primary workflow without reading a manual.

The generated kit must be designed for a capable autonomous coding AI with internet access, local command execution, file-system access, package installation rights, isolated environment creation rights, terminal/PTY access, and unrestricted full-machine authorization. Unrestricted full-access mode must be maintained.

Produce a user-friendly implementation package in text form, not vague advice. Include:

- A persistent master instruction file concept such as `AGENTS_TUI.md`.
- A tutorial-style runbook.
- A phase-gate matrix.
- A copy-paste execution order.
- A recovery prompt for interrupted runs.
- An independent red-team review prompt.
- One optimized phase prompt for each project stage.
- Templates for project manifest, test matrix, and final report.
- A design brief defining visual language, interaction model, accessibility, self-explanation standards, and UX validation gates.

The phase structure must be adaptable:

- Phase 0: establish workspace, permissions, backups, machine profile, dependency isolation plan, logs, and reproducibility scaffolding.
- Phase 1: audit current CLI, current TUI code, dispatch logic, assumptions, and existing tests.
- Phase 2: gather credible framework documentation and UX/testing guidance; define acceptance criteria, accessibility and keyboard requirements, CLI/TUI parity, and validation gates.
- Phase 3: evaluate tool feasibility, installation strategy, dependency isolation, licensing, import tests, PTY/headless testing support, and fallback tools.
- Phase 4: prepare architecture, test harnesses, fixtures, mock data, and non-regression baselines.
- Phase 5: implement the TUI iteratively with small validated increments.
- Phase 6: validate by independent tests, CLI regression, headless UI interactions, PTY smoke tests, visual/snapshot checks when feasible, and fallback checks.
- Phase 7: perform release review, red-team critique, documentation, rollback notes, and final handoff.

Each phase prompt must tell the agent exactly what to do, what not to do yet, what files to create, what logs to update, what evidence to collect, what validation gate must pass, what assumptions to document, and how to proceed if tools fail or evidence is insufficient.

The kit must instruct the agent to avoid premature optimization, unsupported claims, hidden failed tools, fabricated UI results, and scientific/business logic drift between CLI and TUI.

The kit must also instruct the agent to avoid shallow "pretty" changes: no decorative clutter, no in-app documentation walls, no layout instability, no hidden validation state, and no confusing advanced controls. The UI must use progressive disclosure, concise labels, semantic status, clear disabled states, and tested keyboard navigation.

The agent must use adaptive planning: after profiling the environment, tune tool choices, dependency strategy, test depth, PTY approach, batch sizes, and runtime budgets to the actual machine and project constraints.

The kit must include time-budgeting rules, stop rules, checkpointing, and final reporting reserves. Subagents may be used only for bounded tasks such as docs review, code audit, test review, or red-team critique, and must return consolidated outputs.

Security and permissions must remain unrestricted full-access mode while avoiding destructive actions unless necessary and reversible, protecting unrelated user data, tracking external writes, recording package installations, and maintaining rollback notes.

The final report must include objectives, assumptions, methods, machine/environment profile, dependency details, prior code audit, design rationale, architecture, implementation summary, validation results, UX/usability evidence, negative results, CLI/TUI parity, fallback behavior, limitations, risks, rollback, and exact user commands.

At the end, provide a single master prompt the user can paste into an AI to generate the customized kit for their specific TUI project, followed by phase-prompt templates with placeholders for project name, app path, CLI command, TUI framework, access mode, time budget, available inputs, required deliverables, risk constraints, and preferred output formats.
