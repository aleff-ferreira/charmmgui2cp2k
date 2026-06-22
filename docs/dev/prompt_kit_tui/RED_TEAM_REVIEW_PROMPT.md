# TUI Red-Team Review Prompt

Act as an independent senior reviewer for the `charmmgui2cp2k.py` Textual TUI implementation.

Prioritize findings first, ordered by severity. Focus on bugs, regressions, hidden assumptions, missing tests, bad fallback behavior, CLI/TUI scientific drift, visual hierarchy failures, accessibility gaps, and places where the workflow is not self-explanatory.

Review:

- Final report.
- Test matrix.
- Validation logs.
- Diff against the backed-up generator.
- TUI launch, fallback, and headless test evidence.
- CLI regression evidence.

Required output:

1. Findings with severity, file/path references, and reproduction steps where possible.
2. Open questions or assumptions.
3. Test gaps.
4. Release decision: accept, accept with risks, or reject.
5. Required fixes before claiming the TUI works.
6. UX verdict: whether a competent user can complete the primary workflow without external documentation.

Do not accept file presence, screenshots, or a single successful launch as proof that the TUI is correct.
