# TUI Phase Gate Matrix

| Phase | Goal | Required evidence | Gate decision |
|---|---|---|---|
| 0 | Workspace and reproducibility scaffold | Timestamped run dir, backup of `charmmgui2cp2k.py`, command log, environment profile, install log, external writes log | PASS only if rollback path exists |
| 1 | Current code audit | TUI code map, CLI parity map, dispatch map, risk register, baseline CLI commands | PASS only if implementation surface is understood |
| 2 | Framework and UX intelligence | Official Textual docs reviewed, design brief refined, acceptance criteria, test strategy, accessibility/keyboard requirements | PASS only if claims cite current primary sources and UX criteria are testable |
| 3 | Tool feasibility | Isolated env plan, Textual import smoke, pytest/headless feasibility, PTY feasibility, license notes | PASS only if dependency route is reproducible |
| 4 | Architecture/test harness | Test files or planned fixtures, mock/dry-run strategy, baseline non-regression tests, TUI architecture and design-system plan | PASS only if implementation and UX quality can be tested incrementally |
| 5 | TUI implementation | Small commits/patches, run logs, implementation notes, partial tests after each increment, design-system evidence | PASS only if app launches in headless mode, core navigation works, and the UI has coherent state/visual hierarchy |
| 6 | Validation and regression | Full test matrix, CLI regression, Textual `run_test()`, fallback tests, resize/usability checks, PTY smoke or documented blocker | PASS only if tests prove behavior and design-readiness claims |
| 7 | Release review | Final report, runbook, red-team review, known limitations, rollback, exact user commands | PASS only if remaining risks are explicit |

## Stop Rules

Stop and request human review if:

- A source edit cannot be rolled back.
- CLI regression fails and cannot be fixed quickly.
- Dependency installation would require unsafe global changes.
- The TUI requires a scientific default change to work.
- Textual APIs differ from assumptions and no primary-source documentation resolves the issue.
- Headless or PTY tests cannot be run and the user expects a verified TUI.
- The UI needs a manual to complete the primary path because the on-screen flow is unclear.
