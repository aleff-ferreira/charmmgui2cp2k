# Bundled demo system — alanine dipeptide QM/MM

These four files are the one-command `charmmgui2cp2k --demo` quickstart system:
an AMBER alanine-dipeptide topology/coordinates plus a QM/MM `mdin` marking the
methyl group as the QM region. Running `--demo` copies them into a work
directory and generates a complete, runnable CP2K QM/MM input set — no input
files of your own required.

Regenerate the topology with `tests/fixtures/make_ala_dipeptide.tleap`.
