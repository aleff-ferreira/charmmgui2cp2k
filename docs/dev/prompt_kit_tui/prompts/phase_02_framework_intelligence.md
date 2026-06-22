# Phase 2 Prompt: Framework Intelligence And Acceptance Criteria

## Objective

Use current primary sources to define how the TUI should be implemented and tested.

## Do Now

1. Review current official Textual documentation for:
   - app basics and `App.run()`.
   - widgets and composition.
   - CSS/layout.
   - testing with `App.run_test()` and Pilot.
   - snapshot testing if feasible.
   - workers if blocking tasks are present.
2. Record source links and retrieval dates.
3. Define acceptance criteria:
   - launch.
   - navigation.
   - validation tray/messages.
   - dry-run or mocked generation flow.
   - CLI non-regression.
   - Textual-absent fallback.
   - resize behavior.
   - no event-loop blocking for heavy operations.
   - keyboard-only operation.
   - visual hierarchy and readability at multiple terminal sizes.
   - primary workflow can be completed without external documentation.
   - advanced controls are progressively disclosed.
   - futuristic/polished style remains restrained and domain-appropriate.
4. Define the test strategy:
   - unit tests.
   - headless Textual tests.
   - PTY/manual smoke.
   - optional snapshots.
   - red-team self-explanation review.
5. Create/update:
   - `manifests/textual_sources.md`
   - `manifests/tui_acceptance_criteria.md`
   - `manifests/tui_design_spec.md`
   - `manifests/tui_test_strategy.md`
   - `logs/phase_02_framework_intelligence.md`
   - `phase_notes/phase_02_gate.md`

## Do Not Do Yet

- Do not implement UI changes yet.
- Do not add dependencies before Phase 3.
- Do not cite outdated or non-primary docs for framework behavior if primary docs are available.

## Gate

PASS only if:

- Official Textual sources are recorded.
- Acceptance criteria are concrete and testable.
- Design criteria are concrete and testable, not subjective slogans.
- Test strategy includes `run_test()` and fallback behavior.
