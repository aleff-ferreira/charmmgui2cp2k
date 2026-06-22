# TUI Test Matrix

| Test ID | Area | Command or method | Expected result | Evidence path | Status |
|---|---|---|---|---|---|
| TUI-001 | Compile | `python -m py_compile charmmgui2cp2k.py` | Exit 0 | | |
| TUI-002 | Textual import | `python -c "import charmmgui2cp2k as c; ..."` in TUI env | `HAS_TEXTUAL=True`, app class exists | | |
| TUI-003 | Fallback import | Clean/no-Textual env or simulated import block | `HAS_TEXTUAL=False`, CLI still imports | | |
| TUI-004 | Help regression | `python charmmgui2cp2k.py --help` | Exit 0, CLI options shown | | |
| TUI-005 | CLI dry-run regression | `python charmmgui2cp2k.py --non-interactive --dry-run --dir .` | Exit 0 | | |
| TUI-006 | No-TUI regression | `python charmmgui2cp2k.py --no-tui --non-interactive --dry-run --dir .` | Exit 0 | | |
| TUI-007 | Headless launch | Textual `app.run_test()` | App mounts without crash | | |
| TUI-008 | Navigation | Pilot key/click tests | Phases advance/back correctly | | |
| TUI-009 | Validation messaging | Pilot interaction or direct phase tests | Invalid/missing fields show warnings without crash | | |
| TUI-010 | Resize | Pilot terminal resize tests | No blank or overlapping critical UI | | |
| TUI-011 | Generate dry path | Mocked or safe dry-run generation via TUI | Outputs/log progress as expected | | |
| TUI-012 | PTY smoke | `script`/real terminal launch | TUI screen opens or blocker documented | | |
| TUI-013 | Keyboard-only UX | Pilot keys only, no mouse | Primary path can be navigated and completed | | |
| TUI-014 | Self-explanation | Red-team/user review against design brief | Next safe action is obvious without manual | | |
| TUI-015 | Visual hierarchy | Snapshot/manual review at 100x30, 120x40, 160x50 | No overlap; phase/status/warnings are readable | | |
| TUI-016 | Advanced disclosure | Pilot/review of expert controls | Advanced settings are discoverable but not noisy | | |
