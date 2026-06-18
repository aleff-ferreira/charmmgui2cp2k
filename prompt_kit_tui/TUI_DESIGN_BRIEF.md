# TUI Design Brief

Goal: implement a state-of-the-art Textual TUI that feels modern, precise, and self-explanatory while remaining appropriate for a serious computational chemistry workflow.

## Product Standard

The TUI must feel like a polished scientific operations console, not a script with widgets attached.

It should be:

- Futuristic, but not decorative at the cost of clarity.
- Aesthetically refined, with a coherent visual system, strong hierarchy, and careful spacing.
- Self-explanatory for the primary workflow: a competent user should be able to complete setup, validation review, and generation without reading a manual.
- Keyboard-first and efficient, with mouse support where Textual provides it naturally.
- Calm under complexity: dense enough for expert work, but never visually chaotic.
- Honest about uncertainty, failed checks, and high-risk scientific choices.

## Visual Direction

Use a restrained high-contrast operator-console design:

- Dark neutral base, subtle panel separation, limited accent palette.
- One primary accent for active state, plus semantic colors for success, warning, error, and neutral pending.
- Stable layout with a persistent phase rail or breadcrumb, sticky system summary, validation tray, and main work area.
- No excessive gradients, ornament, novelty ASCII art, blinking effects, or purely decorative panels.
- Use compact status chips, progress bars, tables, and structured cards only when they clarify workflow state.
- Avoid nested cards and visual clutter.

## Interaction Direction

The UI should explain itself through structure and affordances rather than visible tutorial prose.

Required interaction qualities:

- The next safe action must be obvious from the current state.
- Disabled or blocked actions must expose a concise reason.
- Each phase should have one dominant task and a clear completion state.
- Validation messages must be local enough to identify the fix.
- Advanced settings must use progressive disclosure, not overwhelm the default path.
- The generation phase must show progress, current operation, warnings, and final artifacts.
- Error recovery must be clear: retry, go back, change input, or use CLI fallback.

## Self-Explanation Standard

"Documentation unnecessary" means the primary workflow does not require external instructions. It does not remove the need for audit docs, reproducibility notes, or final reports.

The TUI should not rely on long in-app explanations. Prefer:

- Clear labels.
- Defaults that visibly match source evidence.
- Phase state indicators.
- Inline validation near the failing control.
- Concise status and artifact summaries.
- Contextual advanced panels for expert controls.

## Accessibility And Usability

Validate:

- Keyboard-only navigation.
- TTY sizes at minimum, normal, and wide dimensions.
- Text does not overflow, overlap, or disappear.
- Warnings and errors are distinguishable without relying on color alone.
- The UI remains usable over SSH-like terminal conditions.
- The app does not freeze during heavy parsing or generation.

## Definition Of Design Done

The design is done only when:

- Headless Textual tests prove launch, navigation, validation, and resize behavior.
- A PTY/manual smoke test confirms the screen is usable in a real terminal, or a blocker is documented.
- A red-team reviewer can complete the primary workflow from the UI state alone.
- CLI behavior remains intact.
- The final runbook is for reproducibility and operations, not required to understand the basic UI flow.

