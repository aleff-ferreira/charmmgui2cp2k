# Phase 7 Prompt: Finalist Release Review

## Objective

Finish the implementation run with review-grade documentation, release decision, and exact user instructions.

## Do Now

1. Perform a red-team review using `prompt_kit_tui/RED_TEAM_REVIEW_PROMPT.md`.
2. Review all evidence:
   - code diff.
   - install log.
   - test matrix.
   - validation logs.
   - UX validation report.
   - design implementation notes.
   - fallback behavior.
   - CLI regression.
3. Write:
   - `FINAL_TUI_REPORT.md`
   - `TUI_USER_RUNBOOK.md`
   - `manifests/red_team_review.md`
   - `manifests/release_decision.md`
   - `logs/phase_07_finalist_release_review.md`
   - `phase_notes/phase_07_gate.md`
4. Include exact commands:
   - activate environment.
   - launch TUI.
   - run tests.
   - use CLI fallback.
   - rollback source.
5. State final status:
   - PASS.
   - PASS WITH RISKS.
   - FAIL/BLOCKED.

## Do Not Do

- Do not overstate the validation.
- Do not omit known limitations.
- Do not describe the UI as self-explanatory unless the evidence supports it.
- Do not remove logs or temporary evidence needed for reproducibility.

## Gate

PASS only if:

- Final docs exist and match actual evidence.
- User can reproduce launch and tests from the runbook.
- Rollback instructions are present.
- The final status is honest and bounded.
- Release decision explicitly states whether the primary workflow is usable without external documentation.
