#!/usr/bin/env python3
"""
charmmgui2cp2k.py — CHARMM-GUI QM/MM Interfacer → CP2K Input Generator
========================================================================
Production-grade, interactive CLI wizard that converts CHARMM-GUI QM/MM
Interfacer AMBER-style outputs into immediately runnable CP2K QM/MM inputs.

Consolidates all fixes discovered during extensive debugging:
  - %COMMENT stripping from PRMTOP
  - Zero-LJ hydrogen patching
  - Element inference with conformer expansion
  - QM/MM &KIND ordering (QM first)
  - ADMM auxiliary basis handling for BASIS_ADMM / BASIS_ADMM_MOLOPT
  - Deterministic CP2K alias mapping for AMBER atom types
  - XYZ export for large systems
  - Zero-LJ hydrogen patching via ParmEd changeLJSingleType using
    physically meaningful (Rmin/2, epsilon) parameters

Usage:
    python3 charmmgui2cp2k.py [--dir DIR] [--dry-run] [--non-interactive]
                               [--hardware-aware|--no-hardware-aware]
"""

import os
import sys
import re
import json
import hashlib
import math
import glob
import shutil
import subprocess
import argparse
import tempfile
from datetime import datetime, timezone
from collections import OrderedDict, defaultdict
from typing import NamedTuple

try:
    import yaml
except Exception:  # pragma: no cover - optional dependency in some environments
    yaml = None

# ─── Textual TUI Import Guard ────────────────────────────────────────────────
# Textual (https://textual.textualize.io/) requires Python >= 3.9.  When
# available, the script offers a full-screen Terminal User Interface instead
# of the plain ask_*/print CLI wizard.  When Textual is absent (e.g. on
# Python 3.6, on a headless CI runner, or simply not installed), the flag
# HAS_TEXTUAL stays False and the existing CLI wizard is used unchanged.
# The guard is deliberately broad (ImportError covers missing package;
# SyntaxError covers Python-version incompatibility with Textual's own
# type annotations).

HAS_TEXTUAL = False
_textual_import_error = None
try:
    from textual.app import App, ComposeResult
    from textual.screen import Screen
    from textual.widgets import (
        Header, Footer, Static, Button, Input, Select,
        Switch, DataTable, ProgressBar, RichLog, Label, Rule,
        RadioSet, RadioButton, Collapsible, TabbedContent,
        TabPane, LoadingIndicator, Markdown, ContentSwitcher,
        OptionList, Tree, Pretty,
    )
    from textual.widgets.option_list import Option
    from textual.containers import (
        Vertical, Horizontal, Center, ScrollableContainer,
        VerticalScroll,
    )
    from textual.reactive import reactive, var
    from textual.worker import Worker, get_current_worker
    from textual import work, on
    from textual.binding import Binding
    from textual.message import Message
    from textual.css.query import NoMatches
    HAS_TEXTUAL = True
except (ImportError, SyntaxError) as _te:
    _textual_import_error = _te

# ─── Terminal Styling ─────────────────────────────────────────────────────────

class C:
    """ANSI color codes for terminal output."""
    BOLD = '\033[1m'
    DIM = '\033[2m'
    R = '\033[0m'  # Reset
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'

def info(msg):    print(f"  {C.GREEN}{C.BOLD}✓{C.R} {msg}")
def warn(msg):    print(f"  {C.YELLOW}{C.BOLD}⚠{C.R} {C.YELLOW}{msg}{C.R}")
def error(msg):   print(f"  {C.RED}{C.BOLD}✗{C.R} {C.RED}{msg}{C.R}")
def step(n, total, msg): print(f"\n{C.BLUE}{C.BOLD}[{n}/{total}]{C.R} {C.BOLD}{msg}{C.R}")
def detail(msg):  print(f"    {C.DIM}{msg}{C.R}")

def ask(prompt, default=None):
    """Interactive prompt with optional default."""
    if default is not None:
        raw = input(f"  {C.CYAN}?{C.R} {prompt} [{C.BOLD}{default}{C.R}]: ").strip()
        return raw if raw else str(default)
    return input(f"  {C.CYAN}?{C.R} {prompt}: ").strip()

def ask_yes(prompt, default=True):
    """Yes/no prompt."""
    hint = "Y/n" if default else "y/N"
    raw = input(f"  {C.CYAN}?{C.R} {prompt} [{hint}]: ").strip().lower()
    if not raw:
        return default
    return raw in ('y', 'yes')

def ask_choice(prompt, choices, default=None):
    """Choose one option from a list (case-insensitive)."""
    allowed = {str(c).upper(): str(c) for c in choices}
    while True:
        raw = ask(prompt, default).strip()
        key = raw.upper()
        if key in allowed:
            return allowed[key]
        warn(f"Invalid choice '{raw}'. Allowed: {', '.join(str(c) for c in choices)}")

def ask_int(prompt, default, minimum=None):
    """Prompt for integer value."""
    while True:
        raw = ask(prompt, str(default))
        try:
            val = int(raw)
        except ValueError:
            warn(f"'{raw}' is not an integer")
            continue
        if minimum is not None and val < minimum:
            warn(f"Value must be >= {minimum}")
            continue
        return val

def ask_float(prompt, default, minimum=None):
    """Prompt for float value."""
    while True:
        raw = ask(prompt, str(default))
        try:
            val = float(raw)
        except ValueError:
            warn(f"'{raw}' is not a number")
            continue
        if minimum is not None and val < minimum:
            warn(f"Value must be >= {minimum}")
            continue
        return val

def banner():
    # Fixed-width box: 58 visible columns between the vertical bars.
    # The arrow (U+2192) is a narrow Unicode character; alignment is
    # verified at the source level, not dependent on terminal metrics.
    print(f"""{C.BLUE}{C.BOLD}
  ╔════════════════════════════════════════════════════════════╗
  ║       CHARMM-GUI → CP2K QM/MM Input Generator            ║
  ║           charmmgui2cp2k.py — Production Build            ║
  ╚════════════════════════════════════════════════════════════╝{C.R}
""")

# ─── Periodic Table ──────────────────────────────────────────────────────────

ELEMENTS = [
    "H","HE","LI","BE","B","C","N","O","F","NE","NA","MG","AL","SI","P","S",
    "CL","AR","K","CA","SC","TI","V","CR","MN","FE","CO","NI","CU","ZN","GA",
    "GE","AS","SE","BR","KR","RB","SR","Y","ZR","NB","MO","TC","RU","RH","PD",
    "AG","CD","IN","SN","SB","TE","I","XE","CS","BA","LA","CE","PR","ND","PM",
    "SM","EU","GD","TB","DY","HO","ER","TM","YB","LU","HF","TA","W","RE","OS",
    "IR","PT","AU","HG","TL","PB","BI","PO","AT","RN","FR","RA"
]
ATOMIC_NUM_TO_SYMBOL = {i+1: e for i, e in enumerate(ELEMENTS)}
SYMBOL_TO_ATOMIC_NUM = {e.upper(): i+1 for i, e in enumerate(ELEMENTS)}

# GTH pseudopotential valence-electron mapping for QM &KIND POTENTIAL lines.
# Each tag 'qN' means CP2K treats the atom as having N valence electrons;
# the GTH pseudopotential replaces the core electrons.
# Source: CP2K GTH_POTENTIALS library file shipped with CP2K ≥9.1.
# Reference: Goedecker, Teter, Hutter, Phys. Rev. B 54, 1703 (1996);
#            Hartwigsen, Goedecker, Hutter, Phys. Rev. B 58, 3641 (1998);
#            Krack, Theor. Chem. Acc. 114, 145 (2005).
GTH_CHARGE_MAP = {
    # ── Main-group biologically relevant elements ────────────────────────
    'H': 'q1', 'C': 'q4', 'N': 'q5', 'O': 'q6', 'F': 'q7',
    'P': 'q5', 'S': 'q6', 'CL': 'q7', 'BR': 'q7', 'I': 'q7',
    'SE': 'q6',     # Selenocysteine, cofactors; GTH-PBE-q6
    # ── Alkali / alkaline-earth ───────────────────────────────────────────
    # Large-core pseudopotentials, compatible with the default MOLOPT
    # (non-SR) basis sets shipped with CP2K (BASIS_MOLOPT file):
    #   Na (Z=11): [Ne]-core → q1  (1 valence: 3s¹)
    #   K  (Z=19): [Ar]-core → q1  (1 valence: 4s¹)
    #   Mg (Z=12): [Ne]-core → q2  (2 valence: 3s²)
    #   Ca (Z=20): [Ar]-core → q2  (2 valence: 4s²)
    # For improved metal-ligand accuracy (metalloenzymes, ion channels),
    # switch to semicore PPs (Na/K → q9, Mg/Ca → q10) AND the matching
    # semicore basis set (e.g. DZVP-MOLOPT-SR-GTH).
    # Ref: Krack, Theor. Chem. Acc. 114, 145 (2005), Tables 1–2;
    #      VandeVondele & Hutter, J. Chem. Phys. 127, 114105 (2007).
    'NA': 'q1', 'K': 'q1', 'MG': 'q2', 'CA': 'q2',
    # ── First-row transition metals (3d block) ───────────────────────────
    # The standard CP2K GTH library uses TWO core conventions within the
    # 3d row, both from the Krack 2005 parameterisation:
    #
    #   Sc–Ni: [Ne]-core (small-core) pseudopotentials — 10 e⁻ frozen,
    #          qN = Z − 10.  The 3s3p semi-core shell is treated as
    #          valence, giving better accuracy for d-block chemistry.
    #   Cu–Zn: [Ar]-core pseudopotentials — 18 e⁻ frozen, qN = Z − 18.
    #          The filled 3d sub-shell allows a larger core.
    #
    # Ref: Krack, Theor. Chem. Acc. 114, 145 (2005), Tables 1–2;
    #      Goedecker, Teter, Hutter, Phys. Rev. B 54, 1703 (1996).
    'SC': 'q11', 'TI': 'q12', 'V':  'q13', 'CR': 'q14',
    'MN': 'q15', 'FE': 'q16', 'CO': 'q17', 'NI': 'q18',
    'CU': 'q11', 'ZN': 'q12',
    # ── Second-row transition metals (4d block) ──────────────────────────
    # The CP2K GTH library uses THREE core conventions within the 4d row:
    #
    #   Y, Zr:    [Kr]-core — 36 e⁻ frozen, qN = Z − 36.
    #   Nb–Pd:    [Ar+3d¹⁰]-core (small-core) — 28 e⁻ frozen,
    #             qN = Z − 28.  The 4s4p semi-core shell is valence.
    #   Ag, Cd:   [Kr]-core — 36 e⁻ frozen, qN = Z − 36.
    #
    # Ref: Krack, Theor. Chem. Acc. 114, 145 (2005), Tables 3–4.
    'Y':  'q3',  'ZR': 'q4',  'NB': 'q13', 'MO': 'q14',
    'TC': 'q15', 'RU': 'q16', 'RH': 'q17', 'PD': 'q18',
    'AG': 'q11', 'CD': 'q12',
    # ── Third-row transition metals (5d block) ───────────────────────────
    # Hf–Hg: [Xe+4f¹⁴] core (68 e⁻ frozen), so qN = Z − 68.
    # These use the large-core convention from the CP2K GTH library.
    # Ref: Krack, Theor. Chem. Acc. 114, 145 (2005), Table 3.
    'HF': 'q4',  'TA': 'q5',  'W':  'q6',  'RE': 'q7',
    'OS': 'q8',  'IR': 'q9',  'PT': 'q10', 'AU': 'q11',
    'HG': 'q12',
}

# IMOMM link-atom scaling: ALPHA = r(QM–MM bond) / r(QM–H_link).
# Keyed as (QM_element, MM_element) — asymmetric because the denominator
# r(QM–H) depends on which side of the cut is the QM atom.
# ALPHA is needed by CP2K's &LINK section for the IMOMM capping-atom scheme
# (Maseras & Morokuma, J. Comput. Chem. 16, 1170, 1995).
# r(X–H) references: C–H 1.09, N–H 1.01, O–H 0.96, S–H 1.34,
#                     P–H 1.44, Se–H 1.47 Å.
# Bond lengths from CRC Handbook of Chemistry & Physics, 97th ed., sec. 9.
DEFAULT_ALPHA_IMOMM = 1.38
LINK_ALPHA_IMOMM_BY_PAIR = {
    # QM=C  (denominator r(C–H)=1.09)
    ('C', 'C'): 1.38,   # 1.54/1.09 = 1.41 ≈ 1.38 (conventional)
    ('C', 'N'): 1.35,   # 1.47/1.09
    ('C', 'O'): 1.31,   # 1.43/1.09
    ('C', 'S'): 1.67,   # 1.82/1.09
    ('C', 'P'): 1.72,   # 1.87/1.09 (C-P single bond)
    ('C', 'SE'): 1.79,  # 1.95/1.09 (C-Se single bond)
    # QM=N  (denominator r(N–H)=1.01)
    ('N', 'C'): 1.46,   # 1.47/1.01
    ('N', 'N'): 1.44,   # 1.45/1.01
    ('N', 'O'): 1.39,   # 1.40/1.01
    ('N', 'S'): 1.72,   # 1.74/1.01
    ('N', 'P'): 1.66,   # 1.68/1.01 (N-P single bond)
    # QM=O  (denominator r(O–H)=0.96)
    ('O', 'C'): 1.49,   # 1.43/0.96
    ('O', 'N'): 1.46,   # 1.40/0.96
    ('O', 'O'): 1.50,   # 1.44/0.96 (O-O peroxide bond)
    ('O', 'S'): 1.77,   # 1.70/0.96
    ('O', 'P'): 1.69,   # 1.62/0.96 (O-P in phosphate)
    ('O', 'SE'): 1.80,  # 1.73/0.96
    # QM=S  (denominator r(S–H)=1.34)
    ('S', 'C'): 1.36,   # 1.82/1.34
    ('S', 'N'): 1.30,   # 1.74/1.34
    ('S', 'O'): 1.27,   # 1.70/1.34
    ('S', 'S'): 1.53,   # 2.05/1.34
    ('S', 'P'): 1.42,   # 1.90/1.34 (S-P thiol-phosphorus)
    ('S', 'SE'): 1.63,  # 2.19/1.34
    # QM=P  (denominator r(P–H)=1.44)
    ('P', 'C'): 1.30,   # 1.87/1.44
    ('P', 'N'): 1.17,   # 1.68/1.44
    ('P', 'O'): 1.13,   # 1.62/1.44
    ('P', 'S'): 1.32,   # 1.90/1.44
    # QM=Se (denominator r(Se–H)=1.47)
    ('SE', 'C'): 1.33,  # 1.95/1.47
    ('SE', 'N'): 1.19,  # 1.75/1.47
    ('SE', 'S'): 1.49,  # 2.19/1.47
}

# ── C.1.a: Forbidden-bond classifier via the AMBER "Kr proxy" ───────────
#
# Background.  AMBER force fields ship covalent bond, angle, and dihedral
# parameters only for a restricted subset of main-group elements (H, B,
# C, N, O, F, P, S, Cl, Br and Se through GAFF/ff14SB).  Atoms outside
# that subset — transition metals, heavy main-group metals, halogens
# beyond Br, noble gases, and the entire f-block — are routinely carried
# in AMBER systems as *non-bonded* point charges with a mass-only /
# dummy parameterisation.  In the AMBER QM/MM literature this convention
# is colloquially called the "Kr proxy": the MM atom is treated as an
# inert site with well-defined Lennard-Jones & charge terms but no
# covalent bonded parameters — exactly the role that a krypton dummy
# would play.  See AmberTools Manual (Case et al., "Amber 2023 Reference
# Manual", ch. "QM/MM"), §"link atoms", which explicitly warns that a
# QM/MM cut through a bond to a Kr-proxied atom is undefined because
# both (i) the MM-side r(QM–MM) equilibrium distance and (ii) the
# H-replacement direction used by IMOMM have no force-field analogue.
#
# When this pipeline encounters a boundary bond of that kind, the
# IMOMM capping-atom construction (Maseras & Morokuma, JCC 16, 1170
# (1995)) would silently substitute a hydrogen along a direction the
# MM force field does not parameterise — producing a QM fragment whose
# geometry drifts with every MD step because no restoring force acts
# on the H_link from the MM side.  The classifier below flags those
# cases *loudly* and — per the no-silent-modifications policy — halts
# a non-interactive run unless the user has explicitly confirmed that
# the coordination sphere has been expanded into the QM region or that
# a curated bonded parameter set has been supplied out-of-band.
#
# Citations:
#   - Maseras & Morokuma, J. Comput. Chem. 16, 1170 (1995) — IMOMM.
#   - Case et al., AmberTools Reference Manual (current edition),
#     QM/MM chapter, discussion of link-atom vs. bonded-metal models.
#   - Lin & Truhlar, Theor. Chem. Acc. 117, 185 (2007) — review of
#     link-atom caveats for non-main-group elements.
#   - Peters et al., JCTC 6, 2935 (2010) — pitfalls of H-capping
#     across dative / metal–ligand bonds.
FORBIDDEN_LINK_BOND_KR_PROXY_ELEMENTS = frozenset({
    # Noble gases: no covalent bonds defined in any AMBER force field.
    'HE', 'NE', 'AR', 'KR', 'XE', 'RN',
    # 3d transition metals (AMBER typically uses non-bonded / cationic
    # dummy models; CHARMM-GUI Metal Protein builder provides bonded
    # parameters — but the user must opt in by expanding QM region).
    'SC', 'TI', 'V', 'CR', 'MN', 'FE', 'CO', 'NI', 'CU', 'ZN',
    # 4d / 5d transition metals.
    'Y',  'ZR', 'NB', 'MO', 'TC', 'RU', 'RH', 'PD', 'AG', 'CD',
    'HF', 'TA', 'W',  'RE', 'OS', 'IR', 'PT', 'AU', 'HG',
    # Heavy main-group metals / metalloids.
    'AL', 'GA', 'IN', 'TL', 'SN', 'PB', 'BI', 'PO',
    # Heaviest halogen (no AMBER parameters).
    'AT',
    # f-block entirely — lanthanides and actinides.
    'LA','CE','PR','ND','PM','SM','EU','GD','TB','DY','HO','ER','TM','YB','LU',
    'AC','TH','PA','U','NP','PU','AM','CM','BK','CF','ES','FM','MD','NO','LR',
})

FORBIDDEN_LINK_BOND_REASONS = {
    'noble_gas': (
        "noble-gas element has no covalent bond parameters in any AMBER "
        "force field; IMOMM H-capping is geometrically undefined"
    ),
    'transition_metal': (
        "transition-metal–ligand bond: AMBER typically uses a non-bonded "
        "cationic dummy model, so the IMOMM cut has no MM-side restoring "
        "force — expand the QM region to include the full coordination "
        "sphere or supply curated bonded parameters"
    ),
    'heavy_main_group': (
        "heavy main-group element beyond the AMBER/GAFF covalent subset; "
        "r(QM–MM) is not parameterised and IMOMM α would be arbitrary"
    ),
    'f_block': (
        "f-block element: AMBER has no standard covalent parameters; "
        "the QM region must subsume the entire coordination polyhedron"
    ),
}


def _classify_forbidden_element(elem):
    """Return an FORBIDDEN_LINK_BOND_REASONS key for a Kr-proxy element, or None."""
    e = str(elem or '').strip().upper()
    if e not in FORBIDDEN_LINK_BOND_KR_PROXY_ELEMENTS:
        return None
    if e in {'HE', 'NE', 'AR', 'KR', 'XE', 'RN'}:
        return 'noble_gas'
    if e in {
        'SC','TI','V','CR','MN','FE','CO','NI','CU','ZN',
        'Y','ZR','NB','MO','TC','RU','RH','PD','AG','CD',
        'HF','TA','W','RE','OS','IR','PT','AU','HG',
    }:
        return 'transition_metal'
    if e in {
        'LA','CE','PR','ND','PM','SM','EU','GD','TB','DY','HO','ER','TM','YB','LU',
        'AC','TH','PA','U','NP','PU','AM','CM','BK','CF','ES','FM','MD','NO','LR',
    }:
        return 'f_block'
    return 'heavy_main_group'


def classify_forbidden_link_bond(qm_elem, mm_elem):
    """
    Classify a QM/MM link-bond element pair against the AMBER Kr-proxy table.

    Returns a dict::

        {
          'forbidden': bool,
          'side': 'QM' | 'MM' | 'both' | None,
          'reason_key': <key into FORBIDDEN_LINK_BOND_REASONS> | None,
          'reason': <long-form human-readable reason> | None,
        }

    A bond is ``forbidden=True`` when *either* element is Kr-proxied in
    AMBER; the caller is responsible for consent (interactive prompt) or
    surfacing a non-interactive WARN plus run-provenance record.
    """
    qm_reason = _classify_forbidden_element(qm_elem)
    mm_reason = _classify_forbidden_element(mm_elem)
    if not qm_reason and not mm_reason:
        return {'forbidden': False, 'side': None, 'reason_key': None, 'reason': None}
    if qm_reason and mm_reason:
        side, key = 'both', qm_reason  # pick QM-side reason as primary
    elif qm_reason:
        side, key = 'QM', qm_reason
    else:
        side, key = 'MM', mm_reason
    return {
        'forbidden': True,
        'side': side,
        'reason_key': key,
        'reason': FORBIDDEN_LINK_BOND_REASONS[key],
    }


BOUNDARY_CHARGE_SCHEMES = OrderedDict((
    (
        'CHARGE_SHIFT',
        'Recommended: embedding-only charge shift '
        '(QMMM_SCALE_FACTOR 0.0, FIST_SCALE_FACTOR 1.0, valid ADD_MM_CHARGE redistribution to M2)',
    ),
    (
        'CHARGE_SHIFT_FIST',
        'Aggressive override: also rescale the classical FIST M1 charge '
        '(QMMM_SCALE_FACTOR 0.0, FIST_SCALE_FACTOR 0.0, ADD_MM_CHARGE redistribution to M2)',
    ),
    (
        'Z1',
        'Fallback: zero M1 only in the QM/MM embedding and do not redistribute '
        '(use when no M2 atoms are available)',
    ),
    (
        'NONE',
        'Legacy/debug: keep the full M1 charge in both QM/MM embedding and FIST '
        '(not recommended for production)',
    ),
))
DEFAULT_BOUNDARY_CHARGE_SCHEME = 'CHARGE_SHIFT'
BOUNDARY_CHARGE_REDISTRIBUTION_SCHEMES = {'CHARGE_SHIFT', 'CHARGE_SHIFT_FIST'}

# ── Gaussian-embedding radii for &QMMM/&MM_KIND blocks ────────────────────────
# CP2K's Gaussian Expansion of the Electrostatic Potential (GEEP) replaces each
# MM point charge with a spherical Gaussian whose width is read per-element from
# &MM_KIND/RADIUS.  Absent an explicit &MM_KIND, CP2K silently uses a default
# radius that is the same for every element, which over-smooths near-field
# embedding for heavy ions and under-smooths for hydrogen.  The defaults below
# are taken from Laino, Mohamed, Curioni & VandeVondele, JCTC 2, 1370 (2006),
# Table I ("standard" GEEP radii), plus extensions for ions of biological
# relevance derived from the analogous Shannon crystal ionic radii scaled to
# the GEEP convention.  Unlisted elements fall back to MM_KIND_RADIUS_FALLBACK.
#
# References:
#   - Laino, Mohamed, Curioni, VandeVondele, JCTC 1, 1176 (2005) §2.1   [GEEP].
#   - Laino, Mohamed, Curioni, VandeVondele, JCTC 2, 1370 (2006) §2–3  [periodic].
#   - CP2K manual §FORCE_EVAL/QMMM/MM_KIND.
MM_KIND_RADIUS_FALLBACK = 0.80    # [Å]  CP2K internal default; used for rare ions.
MM_KIND_GEEP_RADII = {
    # Core biomolecular elements (Laino 2006, Table I).
    'H':  0.44,
    'C':  0.78,
    'N':  0.78,
    'O':  0.78,
    'S':  0.87,
    'P':  0.87,
    # Halogens (same Table; extended for Br/I by interpolation of Shannon radii).
    'F':  0.78,
    'CL': 0.97,
    'BR': 1.10,
    'I':  1.30,
    # Alkali / alkaline-earth physiological ions (Shannon crystal radii
    # scaled to GEEP convention; large Gaussians avoid divergent near-field
    # embedding with the soft ionic core of CHARMM/AMBER FFs).
    'LI': 0.80,
    'NA': 1.10,
    'K':  1.52,
    'MG': 0.90,
    'CA': 1.20,
    # Redox / cofactor transition-metal ions (standard large-core conventions).
    'MN': 0.95,
    'FE': 0.90,
    'CO': 0.90,
    'NI': 0.88,
    'CU': 0.90,
    'ZN': 0.95,
    # Noble gases are practically inert in biomolecular MM but listed for
    # completeness of any ion-channel / cryo-equilibration setups.
    'HE': 0.50,
    'NE': 0.62,
    'AR': 0.82,
}

# Ambiguous two-letter tokens that commonly appear as AMBER atom-type labels
# and should generally default to first-letter element inference in fallback.
# Example: CA/CO are usually aromatic/carbonyl carbon types, not Ca/Co ions.
AMBIGUOUS_PREFIXES = {
    'C': {"CL","CA","CU","CO","CD","CR","CS","CE"},
    'H': {"HE","HF","HG","HO","HS"},
    'N': {"NE","NA","NI","NB","ND","NP"},
    'O': {"OS"},
    'P': {"PD","PT","PB","PR","PO","PA","PM","PU"},
    'S': {"SI","SC","SE","SR","SN","SB","SM"},
}


def _normalize_box_dims(raw_vals):
    """
    Normalize raw box values to [a, b, c, alpha, beta, gamma].

    Supported inputs:
      - 6 values: [a, b, c, alpha, beta, gamma]
      - 4 values (AMBER BOX_DIMENSIONS): [beta, a, b, c]
      - 3 values: [a, b, c] (orthorhombic default angles)
    """
    vals = [float(v) for v in (raw_vals or [])]
    if len(vals) >= 6:
        a, b, c, alpha, beta, gamma = vals[:6]
        return [a, b, c, alpha, beta, gamma]
    if len(vals) >= 4:
        beta, a, b, c = vals[:4]
        return [a, b, c, 90.0, beta, 90.0]
    if len(vals) >= 3:
        a, b, c = vals[:3]
        return [a, b, c, 90.0, 90.0, 90.0]
    return None

# ─── AMBER Topology Parser ───────────────────────────────────────────────────

class AmberTopology:
    """Pure-Python AMBER PRMTOP parser. Strips %COMMENT lines automatically."""

    def __init__(self, path):
        self.path = path
        self.raw_lines = []
        self.flags = OrderedDict()
        self._parse(path)

    def _parse(self, path):
        with open(path, 'r') as f:
            self.raw_lines = f.readlines()

        # Strip %COMMENT lines and parse flag blocks
        clean = []
        for line in self.raw_lines:
            if line.startswith('%COMMENT'):
                continue
            clean.append(line)

        current_flag = None
        current_fmt = None
        current_data_lines = []

        for line in clean:
            if line.startswith('%VERSION'):
                continue
            if line.startswith('%FLAG'):
                if current_flag is not None:
                    self.flags[current_flag] = (current_fmt, current_data_lines)
                current_flag = line.split()[1] if len(line.split()) > 1 else line[6:].strip()
                current_fmt = None
                current_data_lines = []
            elif line.startswith('%FORMAT'):
                current_fmt = line.strip()
            elif current_flag is not None:
                current_data_lines.append(line)

        if current_flag is not None:
            self.flags[current_flag] = (current_fmt, current_data_lines)

    def _parse_format(self, fmt_str):
        """Parse %FORMAT(NaW) or %FORMAT(NEN.D) into (count, type, width)."""
        m = re.search(r'\((\d+)[aA](\d+)\)', fmt_str)
        if m:
            return int(m.group(1)), 'a', int(m.group(2))
        m = re.search(r'\((\d+)[iI](\d+)\)', fmt_str)
        if m:
            return int(m.group(1)), 'i', int(m.group(2))
        m = re.search(r'\((\d+)[eE](\d+)\.(\d+)\)', fmt_str)
        if m:
            return int(m.group(1)), 'e', int(m.group(2))
        # Fallback for odd formats
        return None, None, None

    def get_string_array(self, flag_name):
        if flag_name not in self.flags:
            return []
        fmt_str, data_lines = self.flags[flag_name]
        _, _, width = self._parse_format(fmt_str)
        if width is None:
            width = 4
        values = []
        for line in data_lines:
            raw = line.rstrip('\n')
            for j in range(0, len(raw), width):
                val = raw[j:j+width].strip()
                if val:
                    values.append(val)
        return values

    def get_int_array(self, flag_name):
        if flag_name not in self.flags:
            return []
        fmt_str, data_lines = self.flags[flag_name]
        _, _, width = self._parse_format(fmt_str)
        if width is None:
            width = 8
        values = []
        for line in data_lines:
            raw = line.rstrip('\n')
            for j in range(0, len(raw), width):
                val = raw[j:j+width].strip()
                if val:
                    try:
                        values.append(int(val))
                    except ValueError:
                        pass
        return values

    def get_float_array(self, flag_name):
        if flag_name not in self.flags:
            return []
        fmt_str, data_lines = self.flags[flag_name]
        _, _, width = self._parse_format(fmt_str)
        if width is None:
            width = 16
        values = []
        for line in data_lines:
            raw = line.rstrip('\n')
            for j in range(0, len(raw), width):
                val = raw[j:j+width].strip()
                if val:
                    try:
                        values.append(float(val))
                    except ValueError:
                        pass
        return values

    @property
    def natom(self):
        p = self.get_int_array('POINTERS')
        return p[0] if p else 0

    @property
    def ntypes(self):
        p = self.get_int_array('POINTERS')
        return p[1] if len(p) > 1 else 0

    @property
    def box(self):
        """Return [A, B, C, alpha, beta, gamma] or None."""
        if 'BOX_DIMENSIONS' in self.flags:
            vals = self.get_float_array('BOX_DIMENSIONS')
            box = _normalize_box_dims(vals)
            if box:
                return box
        return None

    @property
    def is_chamber(self):
        """Detect CHARMM/CHAMBER topology format.

        CHAMBER topologies are generated by ParmEd's chamber tool when
        converting CHARMM PSF+RTF into AMBER parm7 format.  They retain
        CHARMM-specific FLAG sections (FORCE_FIELD_TYPE, CTITLE,
        CHARMM_UREY_BRADLEY, LENNARD_JONES_14_ACOEF, etc.) that are
        absent in native AMBER topologies.
        Ref: ParmEd docs — https://parmed.github.io/ParmEd/
        """
        chamber_flags = {
            'FORCE_FIELD_TYPE', 'CTITLE',
            'CHARMM_UREY_BRADLEY', 'CHARMM_UREY_BRADLEY_COUNT',
            'CHARMM_NUM_IMPROPERS', 'CHARMM_IMPROPERS',
            'CHARMM_CMAP_COUNT', 'LENNARD_JONES_14_ACOEF',
        }
        return bool(set(self.flags.keys()) & chamber_flags)

    @property
    def has_mixed_scee(self):
        """Detect mixed per-dihedral SCEE values indicating CHARMM-origin.

        Pure AMBER topologies have uniform SCEE (typically 1.2).  CHARMM
        force fields use per-dihedral 1-4 scaling, so chamber-converted
        topologies often contain mixed {1.0, 1.2} SCEE values.
        A global EI_SCALE14 is incorrect when SCEE varies per dihedral.
        Ref: AMBER 2024 Manual, §15.1 (force field file formats).
        """
        scee = self.get_float_array('SCEE_SCALE_FACTOR')
        if not scee:
            return False
        unique = set(round(v, 6) for v in scee)
        return len(unique) > 1


# ── PRMTOP POINTERS → array-length cross-check ───────────────────────────────
# AMBER parm7 declares all per-entity counts in a single POINTERS block and
# then ships the actual topology data as 1-D arrays whose lengths must match
# those counts under the fixed stride per entity:
#
#   POINTERS[0]=NATOM       ATOM_NAME/CHARGE/MASS/ATOMIC_NUMBER: length NATOM
#   POINTERS[2]=NBONH       BONDS_INC_HYDROGEN:      length 3·NBONH
#   POINTERS[3]=MBONA       BONDS_WITHOUT_HYDROGEN:  length 3·MBONA
#   POINTERS[4]=NTHETH      ANGLES_INC_HYDROGEN:     length 4·NTHETH
#   POINTERS[5]=MTHETA      ANGLES_WITHOUT_HYDROGEN: length 4·MTHETA
#   POINTERS[6]=NPHIH       DIHEDRALS_INC_HYDROGEN:  length 5·NPHIH
#   POINTERS[7]=MPHIA       DIHEDRALS_WITHOUT_HYDROGEN: length 5·MPHIA
#
# A mismatch means the PRMTOP was truncated (incomplete CHARMM-GUI export) or
# damaged in transit.  detect_link_bonds() walks BONDS_* with stride 3 under
# the assumption that len/3 == NBONH; a shorter array silently under-counts
# link bonds without raising.  Catching the mismatch here lets us surface a
# user-actionable error ("rerun the CHARMM-GUI AMBER tab") instead of a
# cryptic MissingLinkAtomError downstream.
# Reference: AmberTools Reference Manual §2.2 "The Topology File Format".
_PRMTOP_POINTER_STRIDES = (
    # (pointers_index, flag_name, stride_per_entity, human-readable label)
    (2, 'BONDS_INC_HYDROGEN',      3, 'bonds-with-H'),
    (3, 'BONDS_WITHOUT_HYDROGEN',  3, 'bonds-without-H'),
    (4, 'ANGLES_INC_HYDROGEN',     4, 'angles-with-H'),
    (5, 'ANGLES_WITHOUT_HYDROGEN', 4, 'angles-without-H'),
    (6, 'DIHEDRALS_INC_HYDROGEN',  5, 'dihedrals-with-H'),
    (7, 'DIHEDRALS_WITHOUT_HYDROGEN', 5, 'dihedrals-without-H'),
)


def _validate_prmtop_pointers(topo):
    """Cross-check POINTERS counts against array lengths; return a list of
    human-readable mismatch messages (empty if consistent)."""
    pointers = topo.get_int_array('POINTERS') or []
    if len(pointers) < 8:
        return [
            f"POINTERS block has {len(pointers)} entries; "
            "AMBER parm7 requires at least 8."
        ]
    messages = []
    # Per-atom arrays (fixed length NATOM).
    natom = int(pointers[0])
    for flag in ('ATOM_NAME', 'CHARGE', 'MASS', 'ATOMIC_NUMBER', 'ATOM_TYPE_INDEX'):
        if flag in topo.flags:
            arr = (topo.get_int_array(flag) if flag in ('ATOMIC_NUMBER', 'ATOM_TYPE_INDEX')
                   else topo.get_float_array(flag) if flag in ('CHARGE', 'MASS')
                   else topo.get_string_array(flag))
            if arr is None:
                continue
            if len(arr) != natom:
                messages.append(
                    f"{flag} length {len(arr)} does not match POINTERS[NATOM]={natom}."
                )
    # Strided bond/angle/dihedral arrays.
    for idx, flag, stride, label in _PRMTOP_POINTER_STRIDES:
        if flag not in topo.flags:
            continue
        expected_count = int(pointers[idx])
        arr = topo.get_int_array(flag) or []
        actual_entries, rem = divmod(len(arr), stride)
        if rem != 0:
            messages.append(
                f"{flag} length {len(arr)} is not divisible by stride {stride} "
                f"({label})."
            )
        if actual_entries != expected_count:
            messages.append(
                f"{flag} carries {actual_entries} {label} but POINTERS[{idx}]={expected_count}."
            )
    return messages


def validate_topology_format(topo, interactive=True):
    """Reject CHAMBER topologies and warn on CHARMM-origin mixed SCEE.

    CP2K's AMBER connectivity reader expects standard AMBER parm7 with
    uniform per-dihedral SCEE/SCNB scaling.  CHARMM force fields use
    per-dihedral 1-4 exceptions that cannot be represented by a single
    global EI_SCALE14/VDW_SCALE14 value.
    Ref: CP2K Manual §FORCE_EVAL/MM/FORCEFIELD (EI_SCALE14, VDW_SCALE14).
    """
    # ── POINTERS sanity — first, because malformed counts break everything else ──
    # Catching a truncated CHARMM-GUI export here gives the user a precise
    # diagnosis ("rerun AMBER tab") instead of an opaque downstream failure.
    pointer_issues = _validate_prmtop_pointers(topo)
    if pointer_issues:
        error(
            "AMBER PRMTOP is structurally inconsistent: POINTERS counts do not match "
            "array lengths.  This usually means the CHARMM-GUI export was truncated "
            "or the file was damaged in transit."
        )
        for msg in pointer_issues:
            error(f"  - {msg}")
        error(
            "Re-run the CHARMM-GUI 'AMBER' tab and download a fresh PRMTOP. "
            "See AmberTools Reference Manual §2.2 for the topology-file format."
        )
        sys.exit(1)
    if topo.is_chamber:
        error(
            "CHAMBER (CHARMM-converted) topology detected. "
            "This pipeline requires native AMBER parm7 format. "
            "CHARMM-specific FLAG sections (FORCE_FIELD_TYPE, CTITLE, "
            "CHARMM_UREY_BRADLEY, etc.) are not supported by CP2K's "
            "AMBER connectivity reader."
        )
        sys.exit(1)
    if topo.has_mixed_scee:
        scee = topo.get_float_array('SCEE_SCALE_FACTOR')
        unique = sorted(set(round(v, 6) for v in scee))
        msg = (
            f"Mixed SCEE_SCALE_FACTOR values detected: {unique}. "
            "This indicates a CHARMM-origin topology converted via chamber. "
            "A global EI_SCALE14 is physically incorrect when per-dihedral "
            "SCEE varies — some 1-4 electrostatic interactions will be "
            "over- or under-scaled."
        )
        if interactive:
            warn(msg)
            if not ask_yes("Continue despite mixed SCEE? (Not recommended for production)", default=False):
                error("Aborting due to mixed SCEE in topology.")
                sys.exit(1)
        else:
            warn(msg)
            warn(
                "Non-interactive mode: proceeding with AMBER_RECOMMENDED "
                "global 1-4 scaling. Verify 1-4 treatment manually."
            )


# ─── Atom-Type Alias Planning ─────────────────────────────────────────────────

ATOM_TYPE_ALIAS_PREFIX = 'T'
ATOM_TYPE_ALIAS_WIDTH = 4
ATOM_TYPE_ALIAS_COUNTER_WIDTH = ATOM_TYPE_ALIAS_WIDTH - len(ATOM_TYPE_ALIAS_PREFIX)
ATOM_TYPE_ALIAS_ALPHABET = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
ATOM_TYPE_ALIAS_MANIFEST_BASENAME = 'atom_type_alias_manifest.json'
# Pre-compiled pattern for recognising synthetic atom-type aliases produced by
# this pipeline (e.g. "T000", "T00A").  Uses re.escape() so that the prefix
# constant is safe even if it were ever changed to contain regex metacharacters.
_ATOM_TYPE_ALIAS_RE = re.compile(
    r'^' + re.escape(ATOM_TYPE_ALIAS_PREFIX)
    + r'[0-9A-Z]{' + str(ATOM_TYPE_ALIAS_COUNTER_WIDTH) + r'}$'
)


class AtomTypeIdentity(NamedTuple):
    raw_label: str
    atom_type_index: int


class AtomTypeAliasPlan(NamedTuple):
    atom_identities: tuple
    atom_aliases: tuple
    identity_to_alias: OrderedDict
    alias_to_identity: OrderedDict
    alias_to_element: OrderedDict
    alias_counts: OrderedDict
    unresolved_aliases: tuple


def _sha256_file(path):
    """Return the SHA-256 digest for *path*."""
    digest = hashlib.sha256()
    with open(path, 'rb') as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _encode_alias_counter(value, width=ATOM_TYPE_ALIAS_COUNTER_WIDTH):
    """Encode a non-negative integer in fixed-width base36."""
    if value < 0:
        raise ValueError("Alias counter must be non-negative.")
    base = len(ATOM_TYPE_ALIAS_ALPHABET)
    chars = []
    current = int(value)
    while current:
        current, rem = divmod(current, base)
        chars.append(ATOM_TYPE_ALIAS_ALPHABET[rem])
    token = ''.join(reversed(chars or ['0']))
    if len(token) > width:
        raise ValueError(
            f"Need more than {width} base36 digits to encode atom-type alias index {value}."
        )
    return token.rjust(width, '0')


def _resolved_alias_element_map(alias_plan):
    """Return alias->element for identities that resolved cleanly."""
    return OrderedDict(
        (alias, elem)
        for alias, elem in alias_plan.alias_to_element.items()
        if elem
    )


def _apply_alias_element_overrides(alias_plan, overrides):
    """Return a copy of *alias_plan* with alias->element overrides applied."""
    alias_to_element = OrderedDict(alias_plan.alias_to_element)
    for alias, element in (overrides or {}).items():
        elem = str(element).strip().upper()
        if not elem:
            continue
        if alias not in alias_to_element:
            raise KeyError(f"Unknown atom-type alias '{alias}' in override map.")
        alias_to_element[alias] = elem
    unresolved = tuple(alias for alias, elem in alias_to_element.items() if not elem)
    return AtomTypeAliasPlan(
        atom_identities=alias_plan.atom_identities,
        atom_aliases=alias_plan.atom_aliases,
        identity_to_alias=alias_plan.identity_to_alias,
        alias_to_identity=alias_plan.alias_to_identity,
        alias_to_element=alias_to_element,
        alias_counts=alias_plan.alias_counts,
        unresolved_aliases=unresolved,
    )


def build_atom_type_alias_plan(topo):
    """
    Build a deterministic CP2K alias plan from the source topology.

    The authoritative source identity is (raw AMBER_ATOM_TYPE, ATOM_TYPE_INDEX),
    not the transformed string written for CP2K consumption.
    """
    if topo is None:
        raise ValueError("Topology object is required to build an atom-type alias plan.")

    raw_atom_types = [str(v).strip() for v in topo.get_string_array('AMBER_ATOM_TYPE')]
    atom_type_indices = topo.get_int_array('ATOM_TYPE_INDEX')
    atomic_numbers = topo.get_int_array('ATOMIC_NUMBER')
    natom = int(topo.natom or 0)
    if natom <= 0:
        natom = len(raw_atom_types)
    if len(raw_atom_types) < natom:
        raise ValueError(
            f"AMBER_ATOM_TYPE count mismatch: expected {natom}, found {len(raw_atom_types)}."
        )
    if len(atom_type_indices) < natom:
        raise ValueError(
            f"ATOM_TYPE_INDEX count mismatch: expected {natom}, found {len(atom_type_indices)}."
        )

    # AMBER File Formats: ATOM_TYPE_INDEX and NONBONDED_PARM_INDEX carry the LJ-type
    # identity, so we key aliases on (raw label, type index) instead of a renamed string.
    atom_identities = tuple(
        AtomTypeIdentity(raw_atom_types[i], int(atom_type_indices[i]))
        for i in range(natom)
    )
    unique_identities = sorted(
        set(atom_identities),
        key=lambda ident: (ident.atom_type_index, ident.raw_label),
    )
    capacity = len(ATOM_TYPE_ALIAS_ALPHABET) ** ATOM_TYPE_ALIAS_COUNTER_WIDTH
    if len(unique_identities) > capacity:
        raise ValueError(
            f"Atom-type alias space exhausted: {len(unique_identities)} identities exceed "
            f"{capacity} available {ATOM_TYPE_ALIAS_WIDTH}-character aliases."
        )

    identity_to_alias = OrderedDict()
    alias_to_identity = OrderedDict()
    alias_counts = OrderedDict()
    alias_to_element = OrderedDict()
    identity_elements = defaultdict(set)
    unresolved_identities = set()

    for idx, ident in enumerate(unique_identities):
        # AMBER and ParmEd both treat atom types as 4-character labels, so 4-character
        # aliases preserve source-scale semantics even though the derived CP2K PRMTOP is padded later.
        alias = ATOM_TYPE_ALIAS_PREFIX + _encode_alias_counter(idx)
        identity_to_alias[ident] = alias
        alias_to_identity[alias] = ident
        alias_counts[alias] = 0
        alias_to_element[alias] = None

    for atom_idx, ident in enumerate(atom_identities):
        alias = identity_to_alias[ident]
        alias_counts[alias] += 1
        elem = infer_element(
            ident.raw_label,
            atomic_numbers=atomic_numbers,
            atom_idx=atom_idx,
        )
        if elem:
            identity_elements[ident].add(elem.upper())

    for ident in unique_identities:
        alias = identity_to_alias[ident]
        elems = identity_elements.get(ident, set())
        if len(elems) > 1:
            raise ValueError(
                f"Ambiguous element assignment for atom type {ident.raw_label!r} "
                f"(ATOM_TYPE_INDEX={ident.atom_type_index}): {sorted(elems)}"
            )
        if elems:
            # CP2K KIND docs make ELEMENT explicit, so the alias plan stores element
            # assignment separately instead of encoding chemistry into the alias name.
            alias_to_element[alias] = next(iter(elems))
        else:
            unresolved_identities.add(ident)

    atom_aliases = tuple(identity_to_alias[ident] for ident in atom_identities)
    if len(set(identity_to_alias.values())) != len(unique_identities):
        raise ValueError("Atom-type alias plan is not bijective.")

    unresolved_aliases = tuple(identity_to_alias[ident] for ident in unique_identities if ident in unresolved_identities)
    return AtomTypeAliasPlan(
        atom_identities=atom_identities,
        atom_aliases=atom_aliases,
        identity_to_alias=identity_to_alias,
        alias_to_identity=alias_to_identity,
        alias_to_element=alias_to_element,
        alias_counts=alias_counts,
        unresolved_aliases=unresolved_aliases,
    )


# ─── RST7 Coordinate Reader ──────────────────────────────────────────────────

def read_rst7(path):
    """
    Read AMBER restart/inpcrd file.
    Returns:
      - xyz: list of (x, y, z) tuples
      - box: [a, b, c, alpha, beta, gamma] or None
    """
    with open(path, 'r') as f:
        lines = f.readlines()

    # Line 0: title, Line 1: NATOM [time]
    parts = lines[1].split()
    natom = int(parts[0])
    values = []

    for line in lines[2:]:
        raw = line.rstrip('\n')
        if not raw:
            continue
        # Standard format: 6F12.7
        for j in range(0, len(raw), 12):
            chunk = raw[j:j+12].strip()
            if chunk:
                try:
                    values.append(float(chunk))
                except ValueError:
                    break

    need = natom * 3
    if len(values) < need:
        raise ValueError(
            f"RST7 coordinate parse failed: expected {need} floats for {natom} atoms, "
            f"found {len(values)} in {path}"
        )

    coords = values[:need]
    # AMBER RST7 layout: [coordinates (natom*3)] [velocities (natom*3)?] [box (3-6)?]
    # When velocities are present (equilibrated restarts from sander/pmemd),
    # the total float count exceeds natom*3 + 6 (the maximum box size).
    # In that case, skip the velocity block to reach the trailing box values.
    # Heuristic matches cpptraj (Roe & Cheatham, JCTC 2013), MDAnalysis,
    # and ParmEd's own RST7 reader.  Unambiguous for natom > 2.
    has_velocities = len(values) > need + 6
    if has_velocities:
        tail = values[need * 2:]
    else:
        tail = values[need:]
    box = None
    if len(tail) >= 6:
        box = _normalize_box_dims(tail[:6])
    elif len(tail) >= 3:
        box = _normalize_box_dims(tail[:3])

    xyz = []
    for i in range(0, min(len(coords), natom * 3), 3):
        xyz.append((coords[i], coords[i+1], coords[i+2]))
    return xyz, box


# ─── LJ Parameter Patcher ────────────────────────────────────────────────────

#
# Zero-LJ hydrogen patch references:
# - BioExcel AmberTools↔CP2K tutorial (ParmEd workflow):
#   https://docs.bioexcel.eu/2020_06_09_online_ambertools4cp2k/08-parmed/
# - CP2K QM/MM and MM force-field documentation (integration context):
#   https://manual.cp2k.org/trunk/CP2K_INPUT/FORCE_EVAL/QMMM.html
#   https://manual.cp2k.org/trunk/CP2K_INPUT/FORCE_EVAL/MM/FORCEFIELD.html
#

REFERENCE_LJ_PARAMS = {
    # GAFF hydroxyl hydrogen (HO), used as a conservative small-H LJ proxy.
    'default': {'rmin_half': 0.3019, 'epsilon': 0.047, 'source': 'GAFF HO (BioExcel tutorial)'},
}

ZERO_LJ_HYDROGEN_TYPES = {
    'HW': {'rmin_half': 0.3019, 'epsilon': 0.047, 'source': 'GAFF HO (BioExcel tutorial)'},
    'HO': {'rmin_half': 0.3019, 'epsilon': 0.047, 'source': 'GAFF HO (BioExcel tutorial)'},
    'HG': {'rmin_half': 0.3019, 'epsilon': 0.047, 'source': 'GAFF HO (BioExcel tutorial)'},
}

AMBER_CHARGE_SCALE = 18.2223

# ── B.3.a: residual-charge redistribution strategy enum ─────────────────
#
# When QM atoms are excised from an MM residue, their net fixed-point
# charge is placed back onto the surviving MM atoms so that the residue's
# integrated charge (and therefore the total system charge) remains
# unchanged.  The *how* is a modelling choice with two defensible options:
#
#   'uniform'           — equal Δq on every non-frontier MM atom of the
#                         host residue (the original CP2K-tutorial choice;
#                         simplest and reproducible).  Preserves the
#                         integrated residue charge exactly but does not
#                         localize the correction to where the "scar" is.
#
#   'distance_weighted' — Δq proportional to 1/(d² + r0²), where d is the
#                         distance from each target MM atom to the nearest
#                         excised QM atom in the *same residue*, and
#                         r0 ≈ 1.0 Å is a regularizer that prevents a
#                         single near-frontier atom from collecting
#                         essentially all of the correction.  This
#                         concentrates the charge edit near the
#                         QM-boundary, which matches the physical
#                         intuition that the missing electrostatic
#                         environment of the excised atoms is "felt" more
#                         strongly by their nearest MM neighbours.
#                         Integrated residue charge is still preserved
#                         exactly (weights are normalised to sum to 1).
#
# Citation: Lin & Truhlar, Theor. Chem. Acc. 117, 185 (2007) review the
# charge-redistribution schemes used at QM/MM boundaries and discuss the
# trade-off between integrated neutrality (automatic under any weight
# choice whose weights sum to 1) and spatial localisation (favoured by
# distance-weighted schemes).  Also Senn & Thiel, Angew. Chem. Int. Ed.
# 48, 1198 (2009) for the broader QM/MM embedding literature.
RESIDUAL_CHARGE_REDISTRIBUTE_STRATEGIES = ('uniform', 'distance_weighted')
RESIDUAL_CHARGE_DISTANCE_WEIGHT_R0_ANG = 1.0  # regularizer, in Ångströms


def _validate_redistribute_strategy(value):
    """Return a normalized redistribute-strategy token or raise ValueError."""
    if value is None:
        return 'uniform'
    token = str(value).strip().lower()
    if token in RESIDUAL_CHARGE_REDISTRIBUTE_STRATEGIES:
        return token
    raise ValueError(
        f"Invalid redistribute_strategy {value!r}. "
        f"Allowed: {', '.join(RESIDUAL_CHARGE_REDISTRIBUTE_STRATEGIES)}."
    )


def build_residual_charge_plan(qm_indices, topo, m1_set=None,
                                redistribute_strategy='uniform', coords=None):
    """
    Build a split-residue MM-charge redistribution plan.

    For each residue containing both QM and MM atoms, compute the net MM charge
    removed with the QM atoms and redistribute it across remaining non-frontier
    MM atoms in that residue.

    Parameters
    ----------
    redistribute_strategy : {'uniform', 'distance_weighted'}
        See :data:`RESIDUAL_CHARGE_REDISTRIBUTE_STRATEGIES` for the
        physical rationale.  ``'distance_weighted'`` requires ``coords``;
        if coordinates are unavailable the routine falls back to
        ``'uniform'`` (which is always safe) and records the degradation
        in the returned per-residue plan entry under ``strategy``.
    coords : sequence of (x, y, z) or None
        Cartesian coordinates in Ångströms, indexed 0-based by AMBER atom
        index minus 1.  Only consulted for ``distance_weighted``.
    """
    redistribute_strategy = _validate_redistribute_strategy(redistribute_strategy)
    natom = int(topo.natom or 0)
    charges_raw = topo.get_float_array('CHARGE')
    residue_pointers = topo.get_int_array('RESIDUE_POINTER')
    residue_labels = topo.get_string_array('RESIDUE_LABEL')

    if natom <= 0 or len(charges_raw) < natom or not residue_pointers:
        return []

    charges_e = [float(c) / AMBER_CHARGE_SCALE for c in charges_raw[:natom]]
    qm_set = {int(i) for i in (qm_indices or []) if 1 <= int(i) <= natom}
    m1_set = {int(i) for i in (m1_set or set()) if 1 <= int(i) <= natom}

    plan = []
    nres = len(residue_pointers)
    for r in range(nres):
        start = int(residue_pointers[r])
        end = int(residue_pointers[r + 1]) - 1 if (r + 1) < nres else natom
        if start < 1:
            start = 1
        if end > natom:
            end = natom
        if end < start:
            continue

        res_atoms = list(range(start, end + 1))
        qm_atoms = [a for a in res_atoms if a in qm_set]
        if not qm_atoms:
            continue
        mm_atoms = [a for a in res_atoms if a not in qm_set]
        if not mm_atoms:
            continue
        # Exclude frontier MM atoms (M1) from redistribution targets.
        # They are handled per-link via QMMM_SCALE_FACTOR / FIST_SCALE_FACTOR /
        # ADD_MM_CHARGE in the CP2K LINK blocks.
        mm_atoms_non_frontier = [a for a in mm_atoms if a not in m1_set]

        removed_charge_e = sum(charges_e[a - 1] for a in qm_atoms)
        if abs(removed_charge_e) < 1.0e-10:
            continue

        res_label = residue_labels[r].strip().upper() if r < len(residue_labels) else f"RES{r+1}"
        target_atoms = mm_atoms_non_frontier
        strategy = 'all_mm'

        if not target_atoms:
            continue

        # ── B.3.a: per-target weights ───────────────────────────────────
        # 'uniform' gives every target the same Δq (classic CP2K tutorial
        # choice).  'distance_weighted' concentrates Δq on the targets
        # physically closest to any excised QM atom in the *same residue*,
        # using weights ∝ 1/(d² + r0²); r0 regularises the 1/d² pole so a
        # single near-frontier atom cannot collect essentially the entire
        # correction. In both cases Σ w_a = 1, so the integrated residue
        # charge is preserved exactly.
        applied_strategy = redistribute_strategy
        can_distance_weight = (
            redistribute_strategy == 'distance_weighted'
            and coords is not None
            and len(coords) >= natom
        )
        if can_distance_weight:
            r0_sq = float(RESIDUAL_CHARGE_DISTANCE_WEIGHT_R0_ANG) ** 2
            qm_xyz = [coords[a - 1] for a in qm_atoms]
            weights = []
            for a in target_atoms:
                ax, ay, az = coords[a - 1]
                d2_min = None
                for (qx, qy, qz) in qm_xyz:
                    dx = ax - qx
                    dy = ay - qy
                    dz = az - qz
                    d2 = dx * dx + dy * dy + dz * dz
                    if d2_min is None or d2 < d2_min:
                        d2_min = d2
                weights.append(1.0 / (d2_min + r0_sq))
            w_sum = sum(weights)
            if w_sum <= 0.0:
                # Defensive: degenerate weights — fall back to uniform.
                weights = [1.0 / len(target_atoms)] * len(target_atoms)
                applied_strategy = 'uniform (fallback: degenerate weights)'
            else:
                weights = [w / w_sum for w in weights]
        elif redistribute_strategy == 'distance_weighted':
            # Requested but coords unavailable — fall back and record so
            # the operator sees the degradation in the run provenance.
            weights = [1.0 / len(target_atoms)] * len(target_atoms)
            applied_strategy = 'uniform (fallback: coords unavailable)'
        else:
            weights = [1.0 / len(target_atoms)] * len(target_atoms)

        mm_charge_before_e = sum(charges_e[a - 1] for a in mm_atoms)
        updates = []
        for a, w in zip(target_atoms, weights):
            old_q = charges_e[a - 1]
            delta_a = removed_charge_e * w
            updates.append({
                'atom_index': int(a),
                'old_charge_e': float(old_q),
                'new_charge_e': float(old_q + delta_a),
                'weight': float(w),
            })
        # Retain backward-compatible 'delta_per_atom_e' as the *mean*.
        delta_per_atom_e = removed_charge_e / float(len(target_atoms))

        mm_charge_after_e = mm_charge_before_e + removed_charge_e
        # ── Defensive charge-neutrality check ─────────────────────────
        # The redistribution is exact by construction (uniform split),
        # but verify the invariant to guard against future regressions.
        actual_redistributed = sum(u['new_charge_e'] - u['old_charge_e'] for u in updates)
        if abs(actual_redistributed - removed_charge_e) > 1.0e-8:
            warn(
                f"Charge redistribution drift in {res_label}: "
                f"expected {removed_charge_e:.10f} e, got {actual_redistributed:.10f} e"
            )
        plan.append({
            'residue_index': int(r + 1),
            'residue_label': res_label,
            'strategy': strategy,
            'redistribute_strategy': applied_strategy,
            'qm_atoms': [int(a) for a in qm_atoms],
            'mm_atoms': [int(a) for a in mm_atoms],
            'target_atoms': [int(a) for a in target_atoms],
            'removed_charge_e': float(removed_charge_e),
            'mm_charge_before_e': float(mm_charge_before_e),
            'mm_charge_after_e': float(mm_charge_after_e),
            'delta_per_atom_e': float(delta_per_atom_e),
            'updates': updates,
        })

    return plan


# ── B.3.b: severity escalation thresholds for residual-charge plan ──────
#
# Uniform redistribution of an excised QM-region net charge across all
# remaining MM atoms in the host residue is exact in the integrated sense
# but not in the spatial-detail sense: large per-atom shifts dilute the
# original AMBER fixed-point charge model, and large per-residue shifts
# (full ionic units) move the residue's electrostatic identity in the MM
# Hamiltonian seen by the QM region.  Both regimes deserve more than the
# single warn-line we previously emitted.
#
# Thresholds selected from biomolecular FF practice:
#   * per-atom |Δq| ≥ 0.10 e  → noticeable (typical AMBER atomic charges
#     are 0.0–0.5 e; a 0.1 e shift is comparable to a polarising term).
#   * per-atom |Δq| ≥ 0.25 e  → severe (rivals the charge of a polar
#     hydrogen on a peptide backbone).
#   * per-residue |Σremoved| ≥ 0.5 e → noticeable (≥ ½ ionic unit).
#   * per-residue |Σremoved| ≥ 1.0 e → severe (≥ full ionic unit; the
#     residue's net charge identity is being moved).
# Refs: AMBER ff14SB charge derivation conventions (Maier et al., JCTC
# 11, 3696 (2015)); RESP charge fitting (Bayly et al., JPC 97, 10269
# (1993)) — both establish ~0.1 e as the noise scale of standard MM
# electrostatics for biomolecular systems.
RESIDUAL_CHARGE_PER_ATOM_NOTICEABLE_E = 0.10
RESIDUAL_CHARGE_PER_ATOM_SEVERE_E = 0.25
RESIDUAL_CHARGE_PER_RESIDUE_NOTICEABLE_E = 0.50
RESIDUAL_CHARGE_PER_RESIDUE_SEVERE_E = 1.00


def evaluate_residual_charge_plan_severity(plan):
    """Return per-residue and overall severity diagnostics for the plan.

    Returns a dict::
        {
          'overall_severity': 'ok' | 'noticeable' | 'severe',
          'noticeable_residues': [ {residue_index, residue_label, ... }, ... ],
          'severe_residues': [ ... ],
          'max_abs_per_atom_e': float,
          'max_abs_per_residue_e': float,
        }
    """
    noticeable = []
    severe = []
    max_per_atom = 0.0
    max_per_res = 0.0
    for entry in (plan or ()):
        per_res_abs = abs(float(entry.get('removed_charge_e', 0.0)))
        per_atom_abs = abs(float(entry.get('delta_per_atom_e', 0.0)))
        max_per_atom = max(max_per_atom, per_atom_abs)
        max_per_res = max(max_per_res, per_res_abs)
        bucket = None
        if (per_atom_abs >= RESIDUAL_CHARGE_PER_ATOM_SEVERE_E
                or per_res_abs >= RESIDUAL_CHARGE_PER_RESIDUE_SEVERE_E):
            bucket = severe
        elif (per_atom_abs >= RESIDUAL_CHARGE_PER_ATOM_NOTICEABLE_E
                or per_res_abs >= RESIDUAL_CHARGE_PER_RESIDUE_NOTICEABLE_E):
            bucket = noticeable
        if bucket is not None:
            bucket.append({
                'residue_index': entry.get('residue_index'),
                'residue_label': entry.get('residue_label'),
                'removed_charge_e': float(entry.get('removed_charge_e', 0.0)),
                'delta_per_atom_e': float(entry.get('delta_per_atom_e', 0.0)),
                'n_targets': len(entry.get('target_atoms') or []),
            })
    if severe:
        overall = 'severe'
    elif noticeable:
        overall = 'noticeable'
    else:
        overall = 'ok'
    return {
        'overall_severity': overall,
        'noticeable_residues': noticeable,
        'severe_residues': severe,
        'max_abs_per_atom_e': float(max_per_atom),
        'max_abs_per_residue_e': float(max_per_res),
    }


def warn_residual_charges(qm_indices, topo, m1_set=None,
                           redistribute_strategy='uniform', coords=None):
    """
    Emit warnings/details for split-residue residual MM charges.
    Returns a redistribution plan to be applied with ParmEd change CHARGE.

    ``redistribute_strategy`` selects between ``'uniform'`` and
    ``'distance_weighted'`` per :data:`RESIDUAL_CHARGE_REDISTRIBUTE_STRATEGIES`.
    ``coords`` (0-indexed Å tuples) is only required for the distance-
    weighted variant; without it the builder falls back to uniform.
    """
    plan = build_residual_charge_plan(
        qm_indices, topo, m1_set=m1_set,
        redistribute_strategy=redistribute_strategy,
        coords=coords,
    )
    if not plan:
        info("No split-residue MM charge redistribution needed.")
        return []

    total_removed = sum(entry['removed_charge_e'] for entry in plan)
    total_targets = sum(len(entry['target_atoms']) for entry in plan)
    warn("QM atoms removed from MM electrostatics leave residual charges on split residues.")
    warn("Applying automated charge redistribution to MM atoms using ParmEd change CHARGE.")
    info(
        f"Prepared MM charge redistribution for {len(plan)} residue(s), "
        f"{total_targets} target atoms; total redistributed charge {total_removed:+.6f} e"
    )
    preview = plan[:8]
    for entry in preview:
        detail(
            f"  Residue {entry['residue_index']} ({entry['residue_label']}): "
            f"removed {entry['removed_charge_e']:+.6f} e, "
            f"targets={len(entry['target_atoms'])}, strategy={entry['strategy']}, "
            f"delta/atom={entry['delta_per_atom_e']:+.6f} e"
        )
    if len(plan) > len(preview):
        detail(f"  ... {len(plan) - len(preview)} additional residue(s) omitted from preview")

    # ── B.3.b: severity escalation for large per-residue shifts ─────────
    # A uniform redistribution is exact in the *integrated* sense (charge
    # neutrality is preserved exactly), but it can dilute the original
    # AMBER fixed-point charge identity — both per-atom (each MM atom's
    # local field changes) and per-residue (the residue's electrostatic
    # identity in the MM Hamiltonian shifts).  Escalate the warning when
    # either threshold is exceeded; the exact split (preview lines above)
    # already showed the per-residue numbers, so we only summarise here.
    severity = evaluate_residual_charge_plan_severity(plan)
    if severity['overall_severity'] == 'severe':
        warn(
            f"Residual-charge redistribution is SEVERE: "
            f"{len(severity['severe_residues'])} residue(s) exceed the "
            f"per-atom |Δq|≥{RESIDUAL_CHARGE_PER_ATOM_SEVERE_E:.2f} e or "
            f"per-residue |Σ|≥{RESIDUAL_CHARGE_PER_RESIDUE_SEVERE_E:.1f} e "
            "threshold (peak per-atom shift "
            f"{severity['max_abs_per_atom_e']:.3f} e / per-residue "
            f"{severity['max_abs_per_residue_e']:.3f} e). The redistribution "
            "remains exact in total but the MM Hamiltonian seen by the "
            "QM region is being noticeably reshaped. Consider revisiting "
            "the QM region cuts to avoid splitting an ionic moiety. "
            "Refs: AMBER ff14SB (Maier et al., JCTC 11, 3696 (2015)); "
            "RESP fitting (Bayly et al., JPC 97, 10269 (1993))."
        )
        for sr in severity['severe_residues'][:6]:
            detail(
                f"    [SEVERE] Residue {sr['residue_index']} ({sr['residue_label']}): "
                f"removed {sr['removed_charge_e']:+.4f} e, "
                f"Δq/atom {sr['delta_per_atom_e']:+.4f} e across "
                f"{sr['n_targets']} target(s)"
            )
        if len(severity['severe_residues']) > 6:
            detail(
                f"    ... {len(severity['severe_residues']) - 6} more severe residue(s)"
            )
    elif severity['overall_severity'] == 'noticeable':
        warn(
            f"Residual-charge redistribution is NOTICEABLE: "
            f"{len(severity['noticeable_residues'])} residue(s) exceed the "
            f"per-atom |Δq|≥{RESIDUAL_CHARGE_PER_ATOM_NOTICEABLE_E:.2f} e or "
            f"per-residue |Σ|≥{RESIDUAL_CHARGE_PER_RESIDUE_NOTICEABLE_E:.1f} e "
            "threshold (peak per-atom shift "
            f"{severity['max_abs_per_atom_e']:.3f} e / per-residue "
            f"{severity['max_abs_per_residue_e']:.3f} e). The split is "
            "exact in total; this is a quality-of-embedding caution rather "
            "than a hard error."
        )
    # Severity is recomputed by callers that want to record it in
    # run_provenance.txt — keeping the return type a plain list of plan
    # entries preserves backwards compatibility with every consumer of
    # build_residual_charge_plan / warn_residual_charges.
    return plan


def _apply_residual_charge_plan_to_raw_charges(charges_raw, residual_charge_plan):
    """Return a copy of AMBER raw charges with a residual-charge plan applied."""
    patched = list(charges_raw or [])
    for entry in residual_charge_plan or []:
        for upd in entry.get('updates', []):
            idx = int(upd.get('atom_index', 0)) - 1
            if 0 <= idx < len(patched):
                patched[idx] = float(upd['new_charge_e']) * AMBER_CHARGE_SCALE
    return patched


# ── PRMTOP-vs-manifest charge verification (S11) ─────────────────────────────
# Tolerance model for the emitted CHARGE array versus the residual-plan-
# adjusted manifest.  Both expressed in *AMBER internal charge units*
# (electron charges multiplied by 18.2223 — the hard-coded Coulomb
# prefactor √(k_e / 4πε₀) absorbed into the FIST LJ framework).
#
# PRMTOP CHARGE is written with ``%FORMAT(5E16.8)`` — 8 significant
# digits per number.  For a |q×18.2223| of magnitude up to ~30 (covers
# every chemically reasonable per-atom charge), the on-disk absolute
# precision is therefore ~3e-7 AMBER-units (~1.6e-8 e).  A pure absolute
# tolerance must accommodate this round-trip noise floor or the check
# will spuriously fail on values that differ only in the 9th digit.
#
# We use a hybrid (absolute + relative) bound:
#
#     |Δq| ≤ TOL_ABS + |q_expected| * TOL_REL
#
# with TOL_ABS = 1.0e-6 AMBER-units (~5.5e-8 e) covering the smallest
# round-off, and TOL_REL = 1.0e-7 covering the proportional 8-digit
# truncation for larger charges.  Together this still flags any
# systematic dropped update or silent renormalisation (chemically
# meaningful drift starts at ~1e-4 e ≈ 1.8e-3 AMBER-units, three orders
# of magnitude above this bound) while accepting bit-exact format
# noise.  Ref: AmberTools Reference Manual §2.2 ("CHARGE" flag) and
# IEEE-754 single-/double-conversion behaviour of the Fortran ``E16.8``
# formatter (8 sig figs ⇒ ~10⁻⁸ relative).
PRMTOP_CHARGE_VERIFICATION_TOLERANCE = 1.0e-6
PRMTOP_CHARGE_VERIFICATION_RELATIVE = 1.0e-7


def verify_prmtop_charges_match_manifest(
    emitted_prmtop_path,
    source_charges_amber_units,
    residual_charge_plan,
    tolerance=PRMTOP_CHARGE_VERIFICATION_TOLERANCE,
    relative_tolerance=PRMTOP_CHARGE_VERIFICATION_RELATIVE,
    label=None,
):
    """Re-parse an emitted PRMTOP and cross-check its CHARGE array.

    Guards against the subtle class of bugs where ParmEd (or any
    downstream editor) silently re-normalises, re-orders, or drops a
    residual-charge update between the in-memory plan and the on-disk
    topology.  Such drift cannot be caught by examining the plan or the
    original PRMTOP alone — only by re-reading the *final* file CP2K
    will actually consume during the MD stages.

    Parameters
    ----------
    emitted_prmtop_path : str
        Path to the PRMTOP written by :func:`patch_lj_and_write` /
        :func:`_convert_with_parmed`.
    source_charges_amber_units : sequence of float
        Original AMBER ``CHARGE`` array (already in internal AMBER units,
        i.e. electron charges scaled by ``AMBER_CHARGE_SCALE`` ≈ 18.2223).
    residual_charge_plan : list[dict] or None
        Plan produced by :func:`build_residual_charge_plan`.  When None
        or empty, the expected array reduces to the source charges.
    tolerance : float
        Per-atom *absolute* tolerance in AMBER internal units.  Default
        ``PRMTOP_CHARGE_VERIFICATION_TOLERANCE`` (1.0e-6 ≈ 5.5e-8 e).
    relative_tolerance : float
        Per-atom *relative* tolerance applied to ``|q_expected|``.
        Default ``PRMTOP_CHARGE_VERIFICATION_RELATIVE`` (1.0e-7).
        Together with ``tolerance`` this defines the hybrid bound
        ``|Δq| ≤ tolerance + |q_expected|·relative_tolerance``, which
        accommodates the E16.8 format quantization while still flagging
        chemically meaningful drift.
    label : str, optional
        Human-readable tag (e.g. "QM/MM stage topology") used in error
        messages so the operator can identify which PRMTOP diverged.

    Raises
    ------
    RuntimeError
        If NATOM mismatches between source and emitted PRMTOP, or if any
        per-atom charge differs by more than ``tolerance``.  The raised
        message lists the worst offender and a short summary so the
        operator can decide whether to investigate or re-run.
    """
    tag = f" ({label})" if label else ""
    expected = _apply_residual_charge_plan_to_raw_charges(
        source_charges_amber_units, residual_charge_plan
    )
    emitted_topo = AmberTopology(emitted_prmtop_path)
    emitted_charges = emitted_topo.get_float_array('CHARGE') or []

    if len(emitted_charges) != len(expected):
        raise RuntimeError(
            "PRMTOP charge-verification NATOM mismatch"
            f"{tag}: emitted file carries {len(emitted_charges)} CHARGE "
            f"entries but the manifest-derived reference has {len(expected)}. "
            "This indicates the topology writer dropped or duplicated "
            "atoms during conversion — refuse to proceed."
        )

    # Scan all atoms.  Keep the worst per-atom deviation so the operator
    # can judge severity (a single isolated hit versus a systemic drift).
    # The per-atom bound is ``tolerance + |q_expected|·relative_tolerance``
    # — see the module-level docstring for the format-precision rationale.
    worst_idx = -1
    worst_diff = 0.0
    worst_bound = 0.0
    violations = 0
    for i, (q_emitted, q_expected) in enumerate(zip(emitted_charges, expected)):
        q_exp_f = float(q_expected)
        diff = abs(float(q_emitted) - q_exp_f)
        atom_bound = float(tolerance) + abs(q_exp_f) * float(relative_tolerance)
        if diff > atom_bound:
            violations += 1
            if diff > worst_diff:
                worst_diff = diff
                worst_idx = i
                worst_bound = atom_bound

    if violations:
        # Convert the worst offender back to electron charges so the
        # error message is easier to read (the in-memory manifest is
        # authored in e, not internal AMBER units).
        worst_diff_e = worst_diff / AMBER_CHARGE_SCALE
        q_emit_e = float(emitted_charges[worst_idx]) / AMBER_CHARGE_SCALE
        q_expect_e = float(expected[worst_idx]) / AMBER_CHARGE_SCALE
        worst_bound_e = worst_bound / AMBER_CHARGE_SCALE
        raise RuntimeError(
            "PRMTOP charge-verification failed"
            f"{tag}: {violations} of {len(expected)} atoms differ from "
            f"the residual-plan-adjusted manifest beyond the hybrid bound "
            f"|Δq| ≤ {tolerance:.1e} + |q|·{relative_tolerance:.1e} "
            f"AMBER-units (E16.8 format precision).\n"
            f"  Worst: atom index {worst_idx + 1} (1-based) — "
            f"emitted q = {q_emit_e:+.8f} e, expected q = {q_expect_e:+.8f} e, "
            f"|Δq| = {worst_diff_e:.2e} e (bound at this atom: "
            f"{worst_bound_e:.2e} e).\n"
            "  This indicates drift between the in-memory residual-charge "
            "plan and the on-disk topology CP2K will consume.  The likely "
            "cause is a ParmEd format round-trip that re-normalised the "
            "charges or a silent conversion-path fallback.  Refusing to "
            "proceed so the divergence is investigated before launching MD."
        )


def write_boundary_charges_audit(out_dir, link_bonds, residual_charge_plan,
                                 boundary_charge_scheme, topo):
    """
    Emit a structured audit artifact documenting *both* channels that modify
    charge near the QM/MM boundary.  This makes the two-channel composition
    auditable post-hoc without re-parsing the generated CP2K input.

    Channels reported:
      (1) Residual MM-charge redistribution: modifies the *MM FIST* CHARGE
          array so that the excised QM charge is redistributed across the
          residue's remaining non-frontier MM atoms.  Affects MM-MM and
          MM-QM electrostatics computed by the FIST back-end.
      (2) QM/MM link-boundary scheme: adds Gaussian-screened partial
          charges (ADD_MM_CHARGE) or zeroes M1 (Z1) via &QMMM/&LINK.
          Affects only the QM-MM *embedding* seen by the QM subsystem.

    The two channels operate on disjoint Hamiltonian representations
    (FIST vs. QM embedding) and therefore do not literally double-count;
    this audit artifact exposes the per-atom composition so that a third
    party can verify the superposition.

    Writes both `boundary_charges.json` (machine-readable) and
    `boundary_charges.dat` (plain-text human-readable).

    References:
      - Senn & Thiel, Angew. Chem. Int. Ed. 48, 1198 (2009) — QM/MM review.
      - Laino, Mohamed, Curioni, VandeVondele, JCTC 2, 1370 (2006) §3.
      - Maseras & Morokuma, J. Comput. Chem. 16, 1170 (1995) — IMOMM.
    """
    import json as _json
    natom = int(topo.natom or 0)
    charges_raw = topo.get_float_array('CHARGE') or []
    charges_e = [float(c) / AMBER_CHARGE_SCALE for c in charges_raw[:natom]]
    residue_labels = topo.get_string_array('RESIDUE_LABEL') or []

    # ── Per-link payload ────────────────────────────────────────────────
    link_entries = []
    for link in (link_bonds or ()):
        qm_index = int(link.get('QM_INDEX', 0))
        mm_index = int(link.get('MM_INDEX', 0))
        m2_indices = [int(i) for i in link.get('M2_INDICES', [])]
        link_entries.append({
            'qm_index': qm_index,
            'qm_element': str(link.get('QM_ELEM', '')),
            'mm_index': mm_index,
            'mm_element': str(link.get('MM_ELEM', '')),
            'alpha_imomm': float(link.get('ALPHA_IMOMM', DEFAULT_ALPHA_IMOMM)),
            'r_qm_mm_A': float(link.get('R_QM_MM', 0.0)),
            'r_qm_h_A': float(link.get('R_QM_H', 0.0)),
            'm1_charge_e': float(link.get('M1_CHARGE_E', 0.0)),
            'm2_indices': m2_indices,
            'm2_charge_per_neighbor_e': (
                float(link.get('M1_CHARGE_E', 0.0)) / len(m2_indices)
                if m2_indices else 0.0
            ),
            'boundary_scheme': boundary_charge_scheme,
        })

    # ── Per-residue payload ─────────────────────────────────────────────
    residual_entries = []
    for entry in (residual_charge_plan or ()):
        residual_entries.append({
            'residue_index': int(entry.get('residue_index', 0)),
            'residue_label': str(entry.get('residue_label', '')),
            'strategy': str(entry.get('strategy', '')),
            'qm_atoms': list(entry.get('qm_atoms', [])),
            'mm_atoms': list(entry.get('mm_atoms', [])),
            'target_atoms': list(entry.get('target_atoms', [])),
            'removed_charge_e': float(entry.get('removed_charge_e', 0.0)),
            'mm_charge_before_e': float(entry.get('mm_charge_before_e', 0.0)),
            'mm_charge_after_e': float(entry.get('mm_charge_after_e', 0.0)),
            'delta_per_atom_e': float(entry.get('delta_per_atom_e', 0.0)),
            'n_target_atoms': len(entry.get('target_atoms', [])),
        })

    # ── Per-atom boundary-charge composition ────────────────────────────
    # For every atom touched by *any* channel we report:
    #   q_original (from PRMTOP before any redistribution)
    #   q_after_residual  — post-FIST modification
    #   delta_addmm_charge_e — supplemental Gaussian on embedding side
    # The FIST-visible charge is always `q_after_residual`; the embedding
    # seen by the QM region additionally includes `delta_addmm_charge_e`
    # when the boundary scheme is CHARGE_SHIFT or CHARGE_SHIFT_FIST.
    touched = {}
    for entry in (residual_charge_plan or ()):
        for upd in entry.get('updates', []):
            idx = int(upd.get('atom_index', 0))
            touched[idx] = {
                'atom_index': idx,
                'residue_index': int(entry.get('residue_index', 0)),
                'residue_label': str(entry.get('residue_label', '')),
                'q_original_e': float(upd.get('old_charge_e', 0.0)),
                'q_after_residual_e': float(upd.get('new_charge_e', 0.0)),
                'delta_residual_e': float(upd.get('new_charge_e', 0.0)) - float(upd.get('old_charge_e', 0.0)),
                'delta_addmm_charge_e': 0.0,
                'on_channel': ['residual'],
            }
    for link in (link_bonds or ()):
        q_m1 = float(link.get('M1_CHARGE_E', 0.0))
        m2_list = [int(i) for i in link.get('M2_INDICES', [])]
        if not m2_list or boundary_charge_scheme not in BOUNDARY_CHARGE_REDISTRIBUTION_SCHEMES:
            continue
        per_neighbor = q_m1 / len(m2_list)
        for m2_idx in m2_list:
            if m2_idx not in touched:
                # Atom was not part of residual-redistribution; seed a row.
                q_orig = charges_e[m2_idx - 1] if 1 <= m2_idx <= natom else 0.0
                touched[m2_idx] = {
                    'atom_index': m2_idx,
                    'residue_index': 0,
                    'residue_label': '',
                    'q_original_e': float(q_orig),
                    'q_after_residual_e': float(q_orig),
                    'delta_residual_e': 0.0,
                    'delta_addmm_charge_e': 0.0,
                    'on_channel': [],
                }
            touched[m2_idx]['delta_addmm_charge_e'] += float(per_neighbor)
            if 'addmm' not in touched[m2_idx]['on_channel']:
                touched[m2_idx]['on_channel'].append('addmm')
    per_atom = sorted(touched.values(), key=lambda r: r['atom_index'])

    payload = {
        'schema_version': 1,
        'boundary_charge_scheme': boundary_charge_scheme,
        'n_links': len(link_entries),
        'n_residues_redistributed': len(residual_entries),
        'total_residual_charge_e': float(sum(e['removed_charge_e'] for e in residual_entries)),
        'total_addmm_charge_e': float(
            sum(e['m1_charge_e'] for e in link_entries if boundary_charge_scheme in BOUNDARY_CHARGE_REDISTRIBUTION_SCHEMES)
        ),
        'links': link_entries,
        'residual_redistribution': residual_entries,
        'per_atom_boundary_composition': per_atom,
    }

    # Emit both representations.  JSON is machine-consumable; .dat is a
    # human-readable summary that mirrors the `electronic_state.dat` style.
    json_path = os.path.join(out_dir, 'boundary_charges.json')
    dat_path = os.path.join(out_dir, 'boundary_charges.dat')

    with open(json_path, 'w') as fh:
        _json.dump(payload, fh, indent=2, sort_keys=True)

    with open(dat_path, 'w') as fh:
        fh.write("# QM/MM boundary-charge audit\n")
        fh.write(f"# Scheme: {boundary_charge_scheme}\n")
        fh.write(f"# Links: {len(link_entries)}    Redistributed residues: {len(residual_entries)}\n")
        fh.write("#\n")
        fh.write("# Channels:\n")
        fh.write("#   (1) residual redistribution — modifies MM FIST CHARGE array.\n")
        fh.write("#   (2) ADD_MM_CHARGE (CHARGE_SHIFT) — adds Gaussians in &QMMM/&LINK embedding only.\n")
        fh.write("# The two channels operate on disjoint Hamiltonians (FIST vs. QM embedding).\n")
        fh.write("# Refs: Senn & Thiel ACIE 48, 1198 (2009); Laino et al. JCTC 2, 1370 (2006).\n")
        fh.write("\n")

        fh.write("[LINKS]\n")
        fh.write("# qm_index  qm_elem  mm_index  mm_elem  alpha_IMOMM  q(M1)[e]  n_M2\n")
        for le in link_entries:
            fh.write(
                f"{le['qm_index']:<9d} {le['qm_element']:<7s} {le['mm_index']:<9d} "
                f"{le['mm_element']:<7s} {le['alpha_imomm']:<11.3f} "
                f"{le['m1_charge_e']:+.6f}    {len(le['m2_indices'])}\n"
            )

        fh.write("\n[RESIDUAL_REDISTRIBUTION]\n")
        fh.write("# res_index  residue  n_targets  removed[e]   delta/atom[e]   strategy\n")
        for e in residual_entries:
            fh.write(
                f"{e['residue_index']:<11d} {e['residue_label']:<8s} "
                f"{e['n_target_atoms']:<10d} {e['removed_charge_e']:+.6e}  "
                f"{e['delta_per_atom_e']:+.6e}  {e['strategy']}\n"
            )

        fh.write("\n[PER_ATOM_COMPOSITION]\n")
        fh.write("# atom_index  residue  q_original[e]  +delta_residual[e]  +delta_addmm[e]  channels\n")
        for r in per_atom:
            channels = '+'.join(r['on_channel']) or 'none'
            fh.write(
                f"{r['atom_index']:<12d} {r['residue_label']:<8s} "
                f"{r['q_original_e']:+.6e}  {r['delta_residual_e']:+.6e}  "
                f"{r['delta_addmm_charge_e']:+.6e}  {channels}\n"
            )

    return {
        'json_path': json_path,
        'dat_path': dat_path,
        'n_links': len(link_entries),
        'n_redistributed_residues': len(residual_entries),
        'n_atoms_touched': len(per_atom),
    }


def compute_amber_self_acoef_bcoef(rmin_half, epsilon):
    """Convert (Rmin/2, epsilon) to AMBER self ACOEF/BCOEF."""
    rmin = 2.0 * float(rmin_half)
    eps = float(epsilon)
    rmin6 = rmin ** 6
    rmin12 = rmin6 ** 2
    acoef = eps * rmin12
    bcoef = 2.0 * eps * rmin6
    return acoef, bcoef


def _lookup_zero_lj_h_type_params(atom_type):
    """Get type-specific patch parameters for a zero-LJ hydrogen atom type."""
    t = str(atom_type).strip().upper()
    if t in ZERO_LJ_HYDROGEN_TYPES:
        return dict(ZERO_LJ_HYDROGEN_TYPES[t]), True
    for k, v in ZERO_LJ_HYDROGEN_TYPES.items():
        if t.startswith(k):
            return dict(v), True
    return dict(REFERENCE_LJ_PARAMS['default']), False


def patch_lj_and_write(topo, out_path, prmtop_path, residual_charge_plan=None, alias_plan=None):
    """
    Patch zero-LJ hydrogen interactions and write a CP2K-prepared derived PRMTOP.

    Requires ParmEd conversion from *prmtop_path* to ensure all LJ pair entries
    are updated consistently via combining rules (changeLJSingleType).
    No manual fallback is allowed.
    """
    if not prmtop_path:
        raise ValueError(
            "prmtop_path is required. Manual LJ fallback was removed because "
            "diagonal-only ACOEF/BCOEF patching leaves cross-type interactions incorrect. "
            "Use ParmEd conversion."
        )

    an = topo.get_int_array('ATOMIC_NUMBER')
    ati = topo.get_int_array('ATOM_TYPE_INDEX')
    npt = topo.get_int_array('NONBONDED_PARM_INDEX')
    acoef = topo.get_float_array('LENNARD_JONES_ACOEF')
    bcoef = topo.get_float_array('LENNARD_JONES_BCOEF')
    atom_types = topo.get_string_array('AMBER_ATOM_TYPE')
    ntypes = topo.ntypes

    patch_plan = {}
    patched_count = 0
    fallback_types = set()

    for atom_idx in range(len(an)):
        if an[atom_idx] == 1:  # Hydrogen
            if atom_idx < len(ati) and atom_idx < len(atom_types):
                type_idx = ati[atom_idx]
                nb_idx = ntypes * (type_idx - 1) + type_idx
                if nb_idx - 1 < len(npt):
                    param_idx = npt[nb_idx - 1]
                    if 0 < param_idx <= len(acoef):
                        if acoef[param_idx - 1] == 0.0 and bcoef[param_idx - 1] == 0.0:
                            atype = str(atom_types[atom_idx]).strip().upper()
                            if atype not in patch_plan:
                                params, known = _lookup_zero_lj_h_type_params(atype)
                                params['atom_type'] = atype
                                params['count'] = 0
                                params['known_type'] = known
                                patch_plan[atype] = params
                                if not known:
                                    fallback_types.add(atype)
                            patch_plan[atype]['count'] += 1
                            patched_count += 1

    if patch_plan:
        info(
            f"Patching {patched_count} zero-LJ hydrogen atoms "
            f"across {len(patch_plan)} atom types using (Rmin/2, epsilon) references"
        )
        detail("Reference: BioExcel AmberTools↔CP2K ParmEd tutorial (GAFF HO)")
        detail("Context: CP2K FORCE_EVAL/QMMM and FORCE_EVAL/MM/FORCEFIELD documentation")
        for atype in sorted(patch_plan):
            params = patch_plan[atype]
            acoef_i, bcoef_i = compute_amber_self_acoef_bcoef(params['rmin_half'], params['epsilon'])
            detail(
                f"  {atype}: count={params['count']}, Rmin/2={params['rmin_half']:.4f}, "
                f"epsilon={params['epsilon']:.4f} -> A={acoef_i:.6g}, B={bcoef_i:.6g} "
                f"[{params['source']}]"
            )
        if fallback_types:
            warn(
                "Zero-LJ hydrogen atom types not in explicit patch map "
                f"(HW/HO/HG) were patched with default reference values: {', '.join(sorted(fallback_types))}"
            )
    else:
        info("No zero-LJ hydrogen atom types detected; no LJ patch needed")

    if alias_plan is None:
        alias_plan = build_atom_type_alias_plan(topo)

    if _convert_with_parmed(prmtop_path, out_path, patch_plan, residual_charge_plan=residual_charge_plan):
        # ParmEd docs warn that raw-data and topology-object edits can drift out of sync,
        # so the alias layer is applied post-write by rewriting the PRMTOP section directly.
        _rewrite_cp2k_string_sections(out_path, atom_type_values=alias_plan.atom_aliases)
        _validate_atom_type_alias_plan(topo, alias_plan)
        _validate_prepared_prmtop(prmtop_path, out_path, alias_plan)
        return out_path
    raise RuntimeError(
        "ParmEd conversion failed. Cannot proceed without ParmEd because "
        "manual diagonal-only LJ patching would leave cross-type interactions incorrect."
    )


def _strip_comments(prmtop_path):
    """Remove %COMMENT lines from a PRMTOP file in-place."""
    with open(prmtop_path, 'r') as f:
        lines = f.readlines()
    has_comments = any(l.startswith('%COMMENT') for l in lines)
    if has_comments:
        with open(prmtop_path, 'w') as f:
            for line in lines:
                if not line.startswith('%COMMENT'):
                    f.write(line)
        detail(f"Stripped %COMMENT lines from {os.path.basename(prmtop_path)}")


def _find_flag_sections(lines):
    """Return ordered section metadata: flag -> (flag_idx, fmt_idx, data_start, data_end)."""
    sections = OrderedDict()
    i = 0
    while i < len(lines):
        if lines[i].startswith('%FLAG'):
            parts = lines[i].split()
            flag = parts[1] if len(parts) > 1 else ''
            flag_idx = i
            j = i + 1
            fmt_idx = None
            while j < len(lines):
                if lines[j].startswith('%COMMENT'):
                    j += 1
                    continue
                if lines[j].startswith('%FORMAT'):
                    fmt_idx = j
                    j += 1
                    break
                j += 1
            data_start = j
            while j < len(lines) and not lines[j].startswith('%FLAG'):
                j += 1
            data_end = j
            sections[flag] = (flag_idx, fmt_idx, data_start, data_end)
            i = j
        else:
            i += 1
    return sections


def _tokenize_prmtop_string_section(lines, start, end):
    """Tokenize a PRMTOP string section the way CP2K's parser does: by whitespace."""
    tokens = []
    for idx in range(start, end):
        raw = lines[idx].rstrip('\n')
        if not raw or raw.startswith('%COMMENT'):
            continue
        tokens.extend(raw.split())
    return tokens


def _rewrite_cp2k_string_sections(prmtop_path, atom_type_values=None):
    """Rewrite PRMTOP string sections with whitespace-delimited fields for CP2K."""
    with open(prmtop_path, 'r') as f:
        lines = f.readlines()

    sections = _find_flag_sections(lines)
    if 'POINTERS' not in sections:
        raise ValueError(f"PRMTOP {prmtop_path} is missing POINTERS.")

    topo = AmberTopology(prmtop_path)
    pointers = topo.get_int_array('POINTERS')
    natom = pointers[0] if len(pointers) > 0 else None
    nres = pointers[11] if len(pointers) > 11 else None
    if natom is None or natom <= 0:
        raise ValueError(f"Could not determine NATOM from {prmtop_path}.")
    replacements = []

    if atom_type_values is not None:
        if len(atom_type_values) != natom:
            raise ValueError(
                f"Atom-type value count mismatch for {prmtop_path}: expected {natom}, found {len(atom_type_values)}."
            )
        if any((len(str(alias)) > 8) or (not str(alias).isalnum()) for alias in atom_type_values):
            raise ValueError("CP2K atom-type values must be <=8-character alphanumeric tokens.")
        if 'AMBER_ATOM_TYPE' not in sections:
            raise ValueError(f"PRMTOP {prmtop_path} is missing AMBER_ATOM_TYPE.")
        _, fmt_idx, _, data_end = sections['AMBER_ATOM_TYPE']
        if fmt_idx is None:
            raise ValueError(f"PRMTOP {prmtop_path} has AMBER_ATOM_TYPE without %FORMAT.")
        # CP2K topology_amber.F reads string sections with parser_get_object()
        # instead of fixed-width A-format parsing, so the derived CP2K topology
        # must pad each token with whitespace even though this deviates from canonical AMBER 20A4.
        fmt_line = '%FORMAT(10a8)\n'
        data_lines = []
        for i in range(0, len(atom_type_values), 10):
            chunk = atom_type_values[i:i + 10]
            data_lines.append(''.join(f"{str(alias):<8s}" for alias in chunk) + '\n')
        replacements.append((fmt_idx, data_end, [fmt_line] + data_lines))

    if 'RESIDUE_LABEL' in sections and nres:
        values = topo.get_string_array('RESIDUE_LABEL')
        if len(values) != nres:
            raise ValueError(
                f"RESIDUE_LABEL count mismatch for {prmtop_path}: expected {nres}, found {len(values)}."
            )
        _, fmt_idx, _, data_end = sections['RESIDUE_LABEL']
        if fmt_idx is None:
            raise ValueError(f"PRMTOP {prmtop_path} has RESIDUE_LABEL without %FORMAT.")
        # CP2K uses the same whitespace-token parser for residue labels; width 5
        # preserves 4-char AMBER residue names while guaranteeing one delimiter blank.
        fmt_line = '%FORMAT(16a5)\n'
        data_lines = []
        for i in range(0, len(values), 16):
            chunk = values[i:i + 16]
            data_lines.append(''.join(f"{str(value)[:4]:<5s}" for value in chunk) + '\n')
        replacements.append((fmt_idx, data_end, [fmt_line] + data_lines))

    replacements.sort(reverse=True, key=lambda item: item[0])
    for start, end, block in replacements:
        lines[start:end] = block
    with open(prmtop_path, 'w') as f:
        f.writelines(lines)

    detail(f"Rewrote CP2K string sections with whitespace-safe fields: {os.path.basename(prmtop_path)}")


def _validate_atom_type_alias_plan(topo, alias_plan):
    """Validate that the alias plan is bijective over source atom-type identities."""
    source_identities = tuple(
        AtomTypeIdentity(str(v).strip(), int(i))
        for v, i in zip(
            topo.get_string_array('AMBER_ATOM_TYPE'),
            topo.get_int_array('ATOM_TYPE_INDEX'),
        )
    )
    unique_source_identities = set(source_identities)
    if len(alias_plan.identity_to_alias) != len(unique_source_identities):
        raise RuntimeError(
            "Atom-type alias count does not match the number of unique source identities."
        )
    if len(alias_plan.alias_to_identity) != len(unique_source_identities):
        raise RuntimeError("Atom-type alias reverse map is not bijective.")
    if len(set(alias_plan.identity_to_alias.values())) != len(unique_source_identities):
        raise RuntimeError("Duplicate CP2K atom-type aliases were generated.")


def _validate_prepared_prmtop(src_prmtop, dst_prmtop, alias_plan):
    """Validate invariants that must survive preparation of a CP2K-specific topology."""
    src = AmberTopology(src_prmtop)
    dst = AmberTopology(dst_prmtop)

    for flag in ('ATOM_TYPE_INDEX', 'NONBONDED_PARM_INDEX'):
        if src.get_int_array(flag) != dst.get_int_array(flag):
            raise RuntimeError(f"Prepared PRMTOP changed {flag}, which must remain invariant.")

    with open(dst_prmtop, 'r') as f:
        lines = f.readlines()
    sections = _find_flag_sections(lines)
    fmt_idx = sections.get('AMBER_ATOM_TYPE', (None, None, None, None))[1]
    fmt_line = lines[fmt_idx].strip().lower() if fmt_idx is not None and fmt_idx < len(lines) else ''
    if fmt_line != '%format(10a8)':
        raise RuntimeError(
            f"Prepared PRMTOP must expose CP2K-safe AMBER_ATOM_TYPE strings in 10A8 format; found {fmt_line!r}."
        )
    res_fmt_idx = sections.get('RESIDUE_LABEL', (None, None, None, None))[1]
    res_fmt_line = lines[res_fmt_idx].strip().lower() if res_fmt_idx is not None and res_fmt_idx < len(lines) else ''
    if res_fmt_line != '%format(16a5)':
        raise RuntimeError(
            f"Prepared PRMTOP must expose CP2K-safe RESIDUE_LABEL strings in 16A5 format; found {res_fmt_line!r}."
        )

    written_aliases = dst.get_string_array('AMBER_ATOM_TYPE')
    if written_aliases != list(alias_plan.atom_aliases):
        raise RuntimeError("Prepared PRMTOP atom-type aliases do not match the canonical alias plan.")
    atom_section = sections['AMBER_ATOM_TYPE']
    residue_section = sections['RESIDUE_LABEL']
    if _tokenize_prmtop_string_section(lines, atom_section[2], atom_section[3]) != list(alias_plan.atom_aliases):
        raise RuntimeError("Prepared PRMTOP AMBER_ATOM_TYPE section is not tokenized safely for CP2K.")
    if _tokenize_prmtop_string_section(lines, residue_section[2], residue_section[3]) != src.get_string_array('RESIDUE_LABEL'):
        raise RuntimeError("Prepared PRMTOP RESIDUE_LABEL section is not tokenized safely for CP2K.")


def build_atom_type_alias_manifest(source_prmtop_path, derived_prmtops, alias_plan):
    """Return a JSON-serializable provenance manifest for the alias plan."""
    script_hash = _sha256_file(__file__)
    entries = []
    for alias, ident in alias_plan.alias_to_identity.items():
        entries.append(OrderedDict([
            ('raw_label', ident.raw_label),
            ('atom_type_index', int(ident.atom_type_index)),
            ('alias', alias),
            ('element', alias_plan.alias_to_element.get(alias)),
            ('atom_count', int(alias_plan.alias_counts.get(alias, 0))),
        ]))

    derived = []
    for label, path in derived_prmtops:
        derived.append(OrderedDict([
            ('label', str(label)),
            ('path', os.path.basename(path)),
            ('sha256', _sha256_file(path)),
        ]))

    # Sandve et al. 2013 Rule 1 and Wilson et al. 2017 both emphasize provenance;
    # a JSON sidecar keeps the source->alias mapping machine-readable and reproducible.
    return OrderedDict([
        ('schema', 'cp2k_atom_type_alias_manifest.v1'),
        ('generated_at_utc', datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')),
        ('tool', OrderedDict([
            ('script_name', os.path.basename(__file__)),
            ('tool_version', f"sha256:{script_hash[:12]}"),
            ('script_sha256', script_hash),
        ])),
        ('source_prmtop', OrderedDict([
            ('path', os.path.abspath(source_prmtop_path)),
            ('sha256', _sha256_file(source_prmtop_path)),
        ])),
        ('derived_prmtops', derived),
        ('atom_type_aliases', entries),
    ])


def write_atom_type_alias_manifest(out_path, source_prmtop_path, derived_prmtops, alias_plan):
    """Write the atom-type alias provenance manifest to JSON."""
    manifest = build_atom_type_alias_manifest(source_prmtop_path, derived_prmtops, alias_plan)
    with open(out_path, 'w') as fh:
        json.dump(manifest, fh, indent=2, sort_keys=False)
        fh.write('\n')


PRMTOP_TORSION_14_FLAGS = (
    'DIHEDRALS_INC_HYDROGEN',
    'DIHEDRALS_WITHOUT_HYDROGEN',
    'DIHEDRAL_FORCE_CONSTANT',
    'DIHEDRAL_PERIODICITY',
    'DIHEDRAL_PHASE',
    'SCEE_SCALE_FACTOR',
    'SCNB_SCALE_FACTOR',
)


def _enforce_preserve_torsion_14_flags(src_prmtop, dst_prmtop):
    """
    Copy torsion and 1-4 scaling FLAG blocks verbatim from source topology.

    This guarantees preservation of DIHEDRAL_* and SCEE/SCNB sections regardless
    of writer behavior in intermediate conversion libraries.
    """
    with open(src_prmtop, 'r') as f:
        src_lines = f.readlines()
    with open(dst_prmtop, 'r') as f:
        dst_lines = f.readlines()

    changed = 0
    for flag in PRMTOP_TORSION_14_FLAGS:
        src_sections = _find_flag_sections(src_lines)
        dst_sections = _find_flag_sections(dst_lines)
        if flag not in src_sections or flag not in dst_sections:
            continue
        src_start, src_end = src_sections[flag][0], src_sections[flag][3]
        dst_start, dst_end = dst_sections[flag][0], dst_sections[flag][3]
        # Filter %COMMENT lines from source to avoid reintroducing them into
        # the already-cleaned destination (CP2K's AMBER parser may choke).
        cleaned_src = [l for l in src_lines[src_start:src_end]
                       if not l.startswith('%COMMENT')]
        dst_lines[dst_start:dst_end] = cleaned_src
        changed += 1

    if changed:
        with open(dst_prmtop, 'w') as f:
            f.writelines(dst_lines)
        detail(
            f"Enforced exact preservation of torsion/1-4 FLAG blocks ({changed} sections) "
            f"in {os.path.basename(dst_prmtop)}"
        )


def _verify_preserve_torsion_14_flags(src_prmtop, dst_prmtop):
    """
    Validate torsion and 1-4 scaling arrays are unchanged after conversion.
    Raises RuntimeError on any mismatch.
    """
    src = AmberTopology(src_prmtop)
    dst = AmberTopology(dst_prmtop)

    float_flags = {
        'DIHEDRAL_FORCE_CONSTANT',
        'DIHEDRAL_PERIODICITY',
        'DIHEDRAL_PHASE',
        'SCEE_SCALE_FACTOR',
        'SCNB_SCALE_FACTOR',
    }

    for flag in PRMTOP_TORSION_14_FLAGS:
        if flag in float_flags:
            a = src.get_float_array(flag)
            b = dst.get_float_array(flag)
        else:
            a = src.get_int_array(flag)
            b = dst.get_int_array(flag)

        if len(a) != len(b):
            raise RuntimeError(
                f"Torsion/1-4 preservation failed for {flag}: length changed "
                f"{len(a)} -> {len(b)}"
            )
        if a != b:
            first_diff = None
            for i, (x, y) in enumerate(zip(a, b)):
                if x != y:
                    first_diff = (i, x, y)
                    break
            if first_diff is None:
                first_diff = (-1, None, None)
            idx, vx, vy = first_diff
            raise RuntimeError(
                f"Torsion/1-4 preservation failed for {flag}: first mismatch at index {idx} "
                f"({vx} != {vy})"
            )


def _discover_amber_homes():
    """Yield unique AMBERHOME candidates to look for a compatible ParmEd install.

    Discovery order:
      1. $AMBERHOME environment variable (authoritative if set).
      2. Common installation prefixes (/opt/amber*, /usr/local/amber*).
    Ref: AMBER 2024 Manual §1.2 — AMBERHOME must point to the top-level
         directory of an AMBER/AmberTools installation.
    """
    candidates = [os.environ.get('AMBERHOME')]
    # Probe standard system-wide installation locations.
    # These paths are non-intrusive: os.path.isdir() returns False
    # if they do not exist, so no performance or correctness penalty.
    for prefix_pattern in ('/opt/amber*', '/usr/local/amber*'):
        candidates.extend(sorted(glob.glob(prefix_pattern), reverse=True))
    seen = set()
    for home in candidates:
        if not home:
            continue
        home = os.path.abspath(home)
        if home in seen or not os.path.isdir(home):
            continue
        seen.add(home)
        yield home


class ParmEdBackend(NamedTuple):
    """Resolved ParmEd backend, ordered by preference."""
    kind: str
    label: str
    python_exe: str = None
    amber_home: str = None
    parmed_exe: str = None


_PARMED_BACKENDS_CACHE = None


def _find_amber_parmed(amber_home):
    """Return a ParmEd executable inside AMBERHOME, if present."""
    candidates = [
        os.path.join(amber_home, 'bin', 'parmed'),
        os.path.join(amber_home, 'miniconda', 'bin', 'parmed'),
    ]
    for exe in candidates:
        if os.path.isfile(exe) and os.access(exe, os.X_OK):
            return exe
    return None


def _find_amber_python(amber_home):
    """Return an executable Python path inside AMBERHOME, if present."""
    candidates = [
        os.path.join(amber_home, 'miniconda', 'bin', 'python'),
        os.path.join(amber_home, 'bin', 'python3'),
        os.path.join(amber_home, 'bin', 'python'),
    ]
    for pyexe in candidates:
        if os.path.isfile(pyexe) and os.access(pyexe, os.X_OK):
            return pyexe
    return None


def _amber_python_env(amber_home):
    """Build subprocess environment so AmberTools ParmEd can be imported reliably."""
    env = os.environ.copy()
    env['AMBERHOME'] = amber_home
    sp_candidates = sorted(glob.glob(os.path.join(amber_home, 'lib', 'python*', 'site-packages')))
    if sp_candidates:
        amber_sp = sp_candidates[-1]
        existing = env.get('PYTHONPATH', '')
        env['PYTHONPATH'] = amber_sp if not existing else amber_sp + os.pathsep + existing
    return env


def _probe_external_parmed(pyexe, env):
    """Return ParmEd module location if the external interpreter can import it."""
    try:
        run = subprocess.run(
            [pyexe, '-c', 'import parmed as pmd; print(getattr(pmd, "__file__", "UNKNOWN"))'],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=20,
        )
    except Exception:
        return None
    if run.returncode != 0:
        return None
    location = run.stdout.strip().splitlines()
    return location[-1] if location else 'UNKNOWN'


def _discover_parmed_backends(force_refresh=False):
    """Return available ParmEd backends, preferring AmberTools over current Python."""
    global _PARMED_BACKENDS_CACHE
    if _PARMED_BACKENDS_CACHE is not None and not force_refresh:
        return _PARMED_BACKENDS_CACHE

    backends = []
    seen = set()

    for amber_home in _discover_amber_homes():
        pyexe = _find_amber_python(amber_home)
        parmed_exe = _find_amber_parmed(amber_home)
        if not pyexe:
            continue
        env = _amber_python_env(amber_home)
        parmed_location = _probe_external_parmed(pyexe, env)
        if not parmed_location:
            continue
        key = ('amber', os.path.realpath(pyexe))
        if key in seen:
            continue
        seen.add(key)
        tool_hint = parmed_exe or pyexe
        backends.append(
            ParmEdBackend(
                kind='amber',
                label=f"AmberTools ParmEd ({tool_hint})",
                python_exe=pyexe,
                amber_home=amber_home,
                parmed_exe=parmed_exe,
            )
        )

    try:
        import parmed as _pmd_probe  # noqa: F401
    except Exception:
        _pmd_probe = None
    if _pmd_probe is not None:
        current_location = getattr(_pmd_probe, '__file__', sys.executable)
        key = ('current', os.path.realpath(current_location))
        if key not in seen:
            backends.append(
                ParmEdBackend(
                    kind='current',
                    label=f"current Python ParmEd ({current_location})",
                )
            )
        del _pmd_probe

    _PARMED_BACKENDS_CACHE = tuple(backends)
    return _PARMED_BACKENDS_CACHE


def _get_preferred_parmed_backend():
    """Return the highest-priority ParmEd backend, or None if unavailable."""
    backends = _discover_parmed_backends()
    return backends[0] if backends else None


def _format_parmed_search_locations():
    """Return a concise description of the ParmEd locations searched."""
    searched = [f"current Python ({sys.executable})"]
    for amber_home in _discover_amber_homes():
        parmed_exe = _find_amber_parmed(amber_home)
        pyexe = _find_amber_python(amber_home)
        if parmed_exe:
            searched.append(parmed_exe)
        elif pyexe:
            searched.append(pyexe)
        else:
            searched.append(amber_home)
    deduped = []
    seen = set()
    for item in searched:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return ', '.join(deduped)


def _apply_lj_patch_parmed(top, zero_lj_type_map):
    """Apply LJ patches using ParmEd changeLJSingleType (proper combining-rule update)."""
    import parmed as pmd

    patched_types = []
    for atom_type, params in sorted((zero_lj_type_map or {}).items()):
        mask = f"@%{atom_type}"
        try:
            action = pmd.tools.changeLJSingleType(
                top,
                mask,
                float(params['rmin_half']),
                float(params['epsilon']),
            )
            action.execute()
            patched_types.append(atom_type)
        except Exception as e:
            warn(f"ParmEd LJ patch skipped for atom type {atom_type} ({mask}): {e}")

    if patched_types:
        info(f"ParmEd LJ patch applied to atom types: {', '.join(sorted(patched_types))}")
    else:
        detail("No ParmEd LJ type patches were applied")


def _apply_residual_charge_plan_parmed(top, residual_charge_plan):
    """Apply split-residue MM charge redistribution with ParmEd change CHARGE."""
    import parmed as pmd

    plan = residual_charge_plan or []
    if not plan:
        detail("No split-residue MM charge redistribution to apply")
        return

    applied_atoms = 0
    applied_residues = 0
    for entry in plan:
        residue_ok = True
        for upd in entry.get('updates', []):
            atom_index = int(upd['atom_index'])
            new_charge = float(upd['new_charge_e'])
            try:
                action = pmd.tools.change(
                    top,
                    None,
                    f"@{atom_index}",
                    "CHARGE",
                    f"{new_charge:.10f}",
                    "quiet",
                )
                action.execute()
                applied_atoms += 1
            except Exception as e:
                residue_ok = False
                warn(
                    f"ParmEd charge redistribution failed for residue "
                    f"{entry.get('residue_index', '?')} atom @{atom_index}: {e}"
                )
        if residue_ok:
            applied_residues += 1

    if applied_atoms:
        info(
            f"ParmEd charge redistribution applied for {applied_residues} residue(s) "
            f"across {applied_atoms} MM atoms"
        )
    else:
        warn("Split-residue MM charge redistribution plan existed but no updates were applied")


def _convert_with_parmed(prmtop_path, out_path, zero_lj_type_map, residual_charge_plan=None):
    """
    Convert topology to a derived AMBER-format PRMTOP with ParmEd.
    Prefers AmberTools-bundled ParmEd over the current interpreter.
    """
    payload = json.dumps({
        'in_path': os.path.abspath(prmtop_path),
        'out_path': os.path.abspath(out_path),
        'zero_lj_type_map': zero_lj_type_map or {},
        'residual_charge_plan': residual_charge_plan or [],
    })

    # ── External ParmEd helper script ───────────────────────────────
    # When ParmEd is only available via an external AmberTools Python
    # interpreter, we build a self-contained helper that applies two
    # topology transformations:
    #
    #   1. Zero-LJ hydrogen patch — AMBER assigns LJ parameters to
    #      polar hydrogens for numerical convenience, but CP2K's FIST
    #      engine expects true zero-LJ for merged-vdW hydrogen types.
    #      Ref: Cornell et al., JACS 117, 5179 (1995).
    #
    #   2. Split-residue charge redistribution — QM atoms removed from
    #      the MM subsystem leave residual charge on their parent
    #      residue; the excess is redistributed to remaining MM atoms
    #      to preserve charge neutrality.
    #      Ref: Senn & Thiel, Angew. Chem. Int. Ed. 48, 1198 (2009), §3.3.
    #
    # Both operations must succeed for a valid topology.  If either
    # fails, the helper exits non-zero so the parent process detects
    # the incomplete topology and tries the next ParmEd backend.
    helper_code = (
        "import json, sys\n"
        "cfg = json.loads(sys.argv[1])\n"
        "import parmed as pmd\n"
        "top = pmd.load_file(cfg['in_path'])\n"
        "for atype, prm in cfg.get('zero_lj_type_map', {}).items():\n"
        "    try:\n"
        "        act = pmd.tools.changeLJSingleType(top, '@%'+str(atype), float(prm['rmin_half']), float(prm['epsilon']))\n"
        "        act.execute()\n"
        "    except Exception as e:\n"
        "        print(f'ERROR: LJ patch failed for type {atype}: {e}', file=sys.stderr)\n"
        "        sys.exit(1)\n"
        "for entry in cfg.get('residual_charge_plan', []):\n"
        "    for upd in entry.get('updates', []):\n"
        "        try:\n"
        "            act = pmd.tools.change(top, None, '@'+str(int(upd['atom_index'])), 'CHARGE', float(upd['new_charge_e']), 'quiet')\n"
        "            act.execute()\n"
        "        except Exception as e:\n"
        "            idx = upd.get('atom_index', '?')\n"
        "            print(f'ERROR: Charge patch failed for atom @{idx}: {e}', file=sys.stderr)\n"
        "            sys.exit(1)\n"
        "top.save(cfg['out_path'], overwrite=True)\n"
    )

    for backend in _discover_parmed_backends():
        if backend.kind == 'current':
            try:
                import parmed as pmd
                detail(f"Using ParmEd backend: {backend.label}")
                top = pmd.load_file(prmtop_path)
                _apply_lj_patch_parmed(top, zero_lj_type_map)
                _apply_residual_charge_plan_parmed(top, residual_charge_plan)
                top.save(out_path, overwrite=True)
            except Exception as e:
                detail(f"ParmEd backend failed ({backend.label}): {e}")
                continue
        elif backend.kind == 'amber':
            detail(f"Using ParmEd backend: {backend.label}")
            env = _amber_python_env(backend.amber_home)
            try:
                run = subprocess.run(
                    [backend.python_exe, '-c', helper_code, payload],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=True,
                    timeout=300,
                )
            except Exception as e:
                warn(f"AmberTools ParmEd invocation failed ({backend.amber_home}): {e}")
                continue

            if run.returncode != 0:
                stderr = run.stderr.strip().splitlines()
                msg = stderr[-1] if stderr else f"exit code {run.returncode}"
                warn(f"AmberTools ParmEd conversion failed ({backend.amber_home}): {msg}")
                continue
        else:
            continue

        _strip_comments(out_path)
        _enforce_preserve_torsion_14_flags(prmtop_path, out_path)
        _verify_preserve_torsion_14_flags(prmtop_path, out_path)
        if residual_charge_plan:
            total_targets = sum(len(e.get('updates', [])) for e in residual_charge_plan)
            info(
                f"Applied split-residue MM charge redistribution: "
                f"{len(residual_charge_plan)} residue(s), {total_targets} atom updates"
            )
        info(f"Wrote derived AMBER topology via ParmEd: {os.path.basename(out_path)}")
        return True

    return False


# ─── Element Inference Engine ─────────────────────────────────────────────────

def infer_element(atom_type, atomic_numbers=None, atom_idx=None):
    """
    Infer chemical element from an AMBER atom type label.
    Priority: ATOMIC_NUMBER array > prefix heuristic > periodic table fallback.
    """
    # Strategy 1: Direct lookup from ATOMIC_NUMBER
    if atomic_numbers and atom_idx is not None and atom_idx < len(atomic_numbers):
        anum = atomic_numbers[atom_idx]
        if anum in ATOMIC_NUM_TO_SYMBOL:
            return ATOMIC_NUM_TO_SYMBOL[anum]

    # Strategy 2: Heuristic from atom type name
    raw = str(atom_type).strip().upper()
    has_explicit_charge = ('+' in raw) or ('-' in raw)
    t = raw.replace('+', '').replace('-', '').replace('*', '')
    clean = re.sub(r'\d+', '', t)  # Strip digits
    # Strip a trailing 'X' (e.g. from alias suffixes) so that two-letter
    # halogens (CL→CLX, BR→BRX) are not misidentified as C / B.
    if len(clean) >= 3 and clean.endswith('X'):
        stem = clean[:-1]
        if stem in {'CL', 'BR', 'FE', 'ZN', 'CU', 'MG', 'MN', 'CO', 'NI'}:
            clean = stem

    # Explicit ion-like tokens with charge markers should be interpreted as elements.
    if has_explicit_charge:
        if len(clean) >= 2 and clean[:2] in ELEMENTS:
            return clean[:2]
        if len(clean) >= 1 and clean[:1] in ELEMENTS:
            return clean[:1]

    for letter, exclusions in AMBIGUOUS_PREFIXES.items():
        if clean.startswith(letter):
            # For common AMBER/GAFF force-field atom-type codes (CA, CO, NA, OS, ...),
            # prefer first-letter element inference over two-letter periodic symbols.
            # Halogens and selenium: these two-letter tokens are more commonly
            # actual elements than force-field type prefixes.
            # CL = chlorine, BR = bromine, SE = selenium (selenocysteine).
            # Ref: IUPAC periodic table; selenocysteine is the 21st
            #      proteinogenic amino acid (Böck et al., Mol. Microbiol.
            #      5, 515, 1991).
            if clean in exclusions:
                if clean in {'CL', 'BR', 'SE'}:
                    return clean
                return letter
            return letter

    # Strategy 3: Two-letter then one-letter periodic table lookup
    if len(clean) >= 2 and clean[:2] in ELEMENTS:
        return clean[:2]
    if len(clean) >= 1 and clean[:1] in ELEMENTS:
        return clean[:1]

    return None


def build_element_map(topo):
    """
    Build a complete mapping: AMBER_ATOM_TYPE → element symbol.
    Uses ATOMIC_NUMBER array when available, falls back to heuristic.
    """
    atom_types = topo.get_string_array('AMBER_ATOM_TYPE')
    atomic_numbers = topo.get_int_array('ATOMIC_NUMBER')

    type_to_element = {}
    unresolved = []

    unique_types = sorted(set(atom_types))
    for t in unique_types:
        # Find first atom with this type for ATOMIC_NUMBER lookup
        idx = None
        for i, at in enumerate(atom_types):
            if at == t:
                idx = i
                break
        elem = infer_element(t, atomic_numbers, idx)
        if elem:
            type_to_element[t] = elem
        else:
            unresolved.append(t)

    return type_to_element, unresolved, atom_types


def derive_cp2k_conformed_kinds(atom_types, charges):
    """
    Emulate CP2K's AMBER atom-type conformation (charge-splitting suffixes).

    Returns:
      - conformed_names: per-atom final kind names
      - kind_to_base: final kind name -> normalized base atom type
    """
    natom = min(len(atom_types), len(charges))
    atom_types = atom_types[:natom]
    charges = charges[:natom]
    if natom == 0:
        return [], {}

    # CP2K sorts atom types and then splits equal-type blocks by exact charge value.
    sorted_idx = sorted(range(natom), key=lambda i: atom_types[i])
    sorted_types = [atom_types[i] for i in sorted_idx]
    sorted_names = list(sorted_types)

    i = 0
    while i < natom:
        j = i + 1
        while j < natom and sorted_types[j] == sorted_types[i]:
            j += 1

        # Block [i, j): same base atom type
        block_len = j - i
        if block_len > 1:
            block_charges = [charges[sorted_idx[k]] for k in range(i, j)]
            order = sorted(range(block_len), key=lambda t: block_charges[t])

            # Count unique values (exact comparison to mirror CP2K behavior)
            unique_count = 1
            prev = block_charges[order[0]]
            for pos in range(1, block_len):
                val = block_charges[order[pos]]
                if val != prev:
                    unique_count += 1
                    prev = val

            if unique_count != 1:
                counter = 1
                kstart = 0
                current = block_charges[order[0]]
                for pos in range(1, block_len):
                    val = block_charges[order[pos]]
                    if val != current:
                        kend = pos - 1
                        for u in range(kstart, kend + 1):
                            gind = i + order[u]
                            sorted_names[gind] = f"{sorted_names[gind]}{counter}"
                        counter += 1
                        current = val
                        kstart = pos

                kend = block_len - 1
                for u in range(kstart, kend + 1):
                    gind = i + order[u]
                    sorted_names[gind] = f"{sorted_names[gind]}{counter}"

        i = j

    conformed_names = [None] * natom
    kind_to_base = {}
    for pos, orig_idx in enumerate(sorted_idx):
        final_name = sorted_names[pos]
        base_name = sorted_types[pos]
        conformed_names[orig_idx] = final_name
        if final_name not in kind_to_base:
            kind_to_base[final_name] = base_name

    return conformed_names, kind_to_base


# ─── QM Region Extraction ────────────────────────────────────────────────────

def _strip_amber_namelist_comment(line):
    """Remove AMBER/Fortran '!' comments while preserving quoted strings."""
    out = []
    in_single = False
    in_double = False
    for ch in str(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == '!' and not in_single and not in_double:
            break
        out.append(ch)
    return ''.join(out).rstrip()


def _split_amber_namelist_terminator(line):
    """Split a namelist line at a trailing '/' terminator outside of quotes."""
    text = str(line or "")
    in_single = False
    in_double = False
    for i, ch in enumerate(text):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == '/' and not in_single and not in_double and not text[i + 1:].strip():
            return text[:i].rstrip(), True
    return text.rstrip(), False


def _extract_amber_namelist_block(content, name):
    """Return a comment-stripped AMBER namelist body without its closing '/'."""
    start_re = re.compile(rf'^\s*&{re.escape(name)}\b', re.IGNORECASE)
    end_re = re.compile(r'^\s*&end\b\s*$', re.IGNORECASE)

    in_block = False
    block_lines = []
    for raw_line in str(content or "").splitlines():
        if not in_block:
            if not start_re.search(raw_line):
                continue
            in_block = True
            clean = _strip_amber_namelist_comment(start_re.sub('', raw_line, count=1))
        else:
            clean = _strip_amber_namelist_comment(raw_line)

        clean, ended = _split_amber_namelist_terminator(clean)
        if end_re.match(clean.strip()):
            break
        if clean.strip():
            block_lines.append(clean)
        if ended:
            break

    if not in_block:
        return None
    return '\n'.join(block_lines).strip()


def _extract_amber_namelist_value(block, key):
    """Extract a single AMBER namelist value, preserving multiline continuations."""
    if not block:
        return None
    match = re.search(
        rf'\b{re.escape(key)}\s*=\s*(.+?)(?=,\s*[A-Za-z_][A-Za-z0-9_]*\s*=|\Z)',
        block,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    return match.group(1).strip().rstrip(',')


def extract_qm_from_mdin(
    mdin_path,
    topo,
    element_map,
    atom_types,
    prmtop_path=None,
    crd_path=None,
    mask_resolver=None,
):
    """
    Extract QM atom indices from an AMBER .mdin file.
    Parses the &qmmm namelist for iqmatoms/qmmask, qmcharge, and qm_theory.
    Returns (qm_elements_dict, qm_indices_list, metadata_dict) or (None, None, None).
    """
    with open(mdin_path, 'r') as f:
        content = f.read()

    block = _extract_amber_namelist_block(content, 'qmmm')
    if not block:
        return None, None, None

    indices = []
    iq_raw = _extract_amber_namelist_value(block, 'iqmatoms')
    if iq_raw:
        indices = [int(token) for token in re.findall(r'\d+', iq_raw)]
        indices = list(dict.fromkeys(indices))

    # Extract metadata
    metadata = {}
    qc_raw = _extract_amber_namelist_value(block, 'qmcharge')
    if qc_raw:
        qc_match = re.search(r'-?\d+', qc_raw)
        if qc_match:
            metadata['qmcharge'] = int(qc_match.group(0))
    qt_raw = _extract_amber_namelist_value(block, 'qm_theory')
    if qt_raw:
        metadata['qm_theory'] = qt_raw.strip().strip("'\"")
    qmmask_raw = _extract_amber_namelist_value(block, 'qmmask')
    if qmmask_raw:
        metadata['qmmask'] = qmmask_raw.strip().strip("'\"")
    # AMBER's SQM interface uses 'spin' for multiplicity (2S+1) in &qmmm.
    # Ref: AMBER 2024 Manual, §11.3 (QM/MM &qmmm namelist variables).
    spin_raw = _extract_amber_namelist_value(block, 'spin')
    if spin_raw:
        spin_match = re.search(r'(\d+)', spin_raw)
        if spin_match:
            metadata['spin'] = int(spin_match.group(1))

    if indices:
        metadata['selection_source'] = 'iqmatoms'

    if not indices and metadata.get('qmmask'):
        if prmtop_path and crd_path:
            resolver = mask_resolver or extract_qm_from_mask
            mask_elements, mask_indices = resolver(metadata['qmmask'], prmtop_path, crd_path)
            if mask_indices:
                metadata['selection_source'] = 'qmmask'
                return mask_elements, mask_indices, metadata
        return None, None, None

    if not indices:
        return None, None, None

    # Validate indices against topology
    natom = topo.natom
    invalid = [i for i in indices if i < 1 or i > natom]
    if invalid:
        warn(f"MDIN contains {len(invalid)} QM indices out of range (NATOM={natom}), skipping them.")
        indices = [i for i in indices if 1 <= i <= natom]

    # Group by element
    elements = {}
    for idx in indices:
        atom_idx_0 = idx - 1
        if atom_idx_0 < len(atom_types):
            atype = atom_types[atom_idx_0]
            elem = element_map.get(atype, 'X')
        else:
            elem = 'X'
        elements.setdefault(elem, []).append(str(idx))

    return elements, indices, metadata


def extract_qm_from_pdb(pdb_path):
    """
    Extract QM atom indices from PDB file.
    CHARMM-GUI marks QM atoms with specific residue names or segment IDs.
    Returns 1-based indices grouped by element.
    """
    qm_indices = []
    qm_elements = {}

    with open(pdb_path, 'r') as f:
        for line in f:
            if not (line.startswith('ATOM') or line.startswith('HETATM')):
                continue
            # Check occupancy column (55-60) or B-factor (61-66) for QM markers
            # CHARMM-GUI uses segment ID or specific residue names
            resname = line[17:20].strip()
            segid = line[72:76].strip() if len(line) > 75 else ''

            # Common CHARMM-GUI QM markers
            is_qm = False
            if segid in ('HETB', 'HETD', 'QM', 'QMMM'):
                is_qm = True
            elif resname in ('HETB', 'HETD'):
                is_qm = True

            if is_qm:
                serial = int(line[6:11].strip())
                # ── Element symbol extraction ────────────────────
                # PDB columns 77-78: right-justified element symbol
                # (PDB v3.3 specification, §8.3).  If absent, infer
                # from the atom name (columns 13-16) by extracting
                # the leading alphabetic prefix.  A single-character
                # fallback avoids misidentifying two-letter elements
                # (e.g. "CA" atom name in a protein is carbon-alpha,
                # not calcium; "CL", "FE", "BR" are genuine 2-char
                # elements).  The element column is authoritative
                # when present.
                # Ref: wwPDB Format v3.3, Table 4 — ATOM/HETATM.
                elem = line[76:78].strip() if len(line) > 77 else ''
                if not elem:
                    raw_name = line[12:16].strip()
                    alpha_match = re.match(r'[A-Za-z]{1,2}', raw_name)
                    elem = alpha_match.group(0) if alpha_match else raw_name[:1]
                elem = elem.upper()
                qm_indices.append(serial)
                qm_elements.setdefault(elem, []).append(str(serial))

    return qm_elements, qm_indices


def extract_qm_from_indices(index_str, topo, element_map, atom_types):
    """
    Extract QM region from comma-separated 1-based atom indices.
    Groups by element using the element_map.
    """
    indices = []
    for part in index_str.replace(' ', ',').split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            # Range: e.g., "100-200"
            a, b = part.split('-', 1)
            indices.extend(range(int(a), int(b) + 1))
        else:
            indices.append(int(part))

    # Validate
    natom = topo.natom
    invalid = [i for i in indices if i < 1 or i > natom]
    if invalid:
        error(f"QM indices out of range (NATOM={natom}): {invalid[:5]}...")
        sys.exit(1)

    elements = {}
    for idx in indices:
        atom_idx_0 = idx - 1
        if atom_idx_0 < len(atom_types):
            atype = atom_types[atom_idx_0]
            elem = element_map.get(atype, 'X')
        else:
            elem = 'X'
        elements.setdefault(elem, []).append(str(idx))

    return elements, indices


def extract_qm_from_mask(mask_str, prmtop_path, crd_path):
    """
    Use ParmEd to resolve an AMBER mask to QM atom indices.
    Returns elements dict and index list, or None if ParmEd unavailable.
    """
    mask = mask_str.strip("'\"[]")
    helper_payload = json.dumps({
        'prmtop_path': os.path.abspath(prmtop_path),
        'crd_path': os.path.abspath(crd_path),
        'mask': mask,
    })
    helper_code = (
        "import json, sys\n"
        "cfg = json.loads(sys.argv[1])\n"
        "import parmed as pmd\n"
        "top = pmd.load_file(cfg['prmtop_path'], xyz=cfg['crd_path'])\n"
        "qm_atoms = top.view[cfg['mask']]\n"
        "elements = {}\n"
        "indices = []\n"
        "for atom in qm_atoms.atoms:\n"
        "    elem = atom.element_name.upper()\n"
        "    idx = atom.idx + 1\n"
        "    elements.setdefault(elem, []).append(str(idx))\n"
        "    indices.append(idx)\n"
        "print(json.dumps({'elements': elements, 'indices': indices}))\n"
    )

    for backend in _discover_parmed_backends():
        if backend.kind == 'current':
            try:
                import parmed as pmd
                top = pmd.load_file(prmtop_path, xyz=crd_path)
                qm_atoms = top.view[mask]
                elements = {}
                indices = []
                for atom in qm_atoms.atoms:
                    elem = atom.element_name.upper()
                    idx = atom.idx + 1
                    elements.setdefault(elem, []).append(str(idx))
                    indices.append(idx)
                return elements, indices
            except Exception as e:
                error(f"ParmEd mask resolution failed ({backend.label}): {e}")
                return None, None

        if backend.kind != 'amber':
            continue

        try:
            run = subprocess.run(
                [backend.python_exe, '-c', helper_code, helper_payload],
                env=_amber_python_env(backend.amber_home),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=120,
            )
        except Exception as e:
            warn(f"AmberTools ParmEd mask resolution invocation failed ({backend.amber_home}): {e}")
            continue

        if run.returncode != 0:
            stderr = run.stderr.strip().splitlines()
            msg = stderr[-1] if stderr else f"exit code {run.returncode}"
            warn(f"AmberTools ParmEd mask resolution failed ({backend.amber_home}): {msg}")
            continue

        try:
            payload = json.loads(run.stdout.strip().splitlines()[-1])
            return payload.get('elements') or {}, payload.get('indices') or []
        except Exception as e:
            warn(f"AmberTools ParmEd mask resolution returned unreadable output ({backend.label}): {e}")

    return None, None


# ─── Link Atom Detection ─────────────────────────────────────────────────────

def _element_for_atom(atom_idx_1b, atom_types, element_map, atomic_numbers):
    """Resolve element symbol for a 1-based atom index."""
    i = atom_idx_1b - 1
    if atomic_numbers and 0 <= i < len(atomic_numbers):
        anum = atomic_numbers[i]
        if anum in ATOMIC_NUM_TO_SYMBOL:
            return ATOMIC_NUM_TO_SYMBOL[anum]
    if atom_types and 0 <= i < len(atom_types):
        atype = atom_types[i]
        elem = element_map.get(atype) if element_map else None
        if elem:
            return elem.upper()
        guess = infer_element(atype, atomic_numbers, i)
        if guess:
            return guess.upper()
    return 'X'


def _alpha_imomm_for_pair(qm_elem, mm_elem):
    """Select ALPHA_IMOMM for a QM/MM boundary bond based on element pair."""
    q = str(qm_elem).upper()
    m = str(mm_elem).upper()
    # Key is (QM_element, MM_element); no symmetric fallback — values are direction-dependent.
    if (q, m) in LINK_ALPHA_IMOMM_BY_PAIR:
        return LINK_ALPHA_IMOMM_BY_PAIR[(q, m)]
    return DEFAULT_ALPHA_IMOMM


def detect_link_bonds(topo, qm_indices_set, atom_types=None, element_map=None, atomic_numbers=None):
    """
    Detect bonds crossing the QM/MM boundary from AMBER bond arrays.
    Returns list of dicts with QM/MM atom indices, elements, and ALPHA_IMOMM.
    """
    bonds_h = topo.get_int_array('BONDS_INC_HYDROGEN')
    bonds_a = topo.get_int_array('BONDS_WITHOUT_HYDROGEN')

    links = []
    seen = set()
    unknown_alpha_pairs = set()

    for bond_arr in [bonds_h, bonds_a]:
        # AMBER bonds: (i/3, j/3, type) triplets with coordinate indices
        for k in range(0, len(bond_arr) - 2, 3):
            a1 = bond_arr[k] // 3 + 1     # 1-based
            a2 = bond_arr[k+1] // 3 + 1   # 1-based

            in_qm_1 = a1 in qm_indices_set
            in_qm_2 = a2 in qm_indices_set

            if in_qm_1 ^ in_qm_2:  # XOR: exactly one in QM
                qm_atom = a1 if in_qm_1 else a2
                mm_atom = a2 if in_qm_1 else a1
                bond_key = (min(qm_atom, mm_atom), max(qm_atom, mm_atom))
                if bond_key not in seen:
                    seen.add(bond_key)
                    qm_elem = _element_for_atom(qm_atom, atom_types, element_map, atomic_numbers)
                    mm_elem = _element_for_atom(mm_atom, atom_types, element_map, atomic_numbers)
                    alpha = _alpha_imomm_for_pair(qm_elem, mm_elem)
                    if alpha == DEFAULT_ALPHA_IMOMM and (qm_elem, mm_elem) not in LINK_ALPHA_IMOMM_BY_PAIR and (mm_elem, qm_elem) not in LINK_ALPHA_IMOMM_BY_PAIR:
                        unknown_alpha_pairs.add((qm_elem, mm_elem))
                    links.append({
                        'QM_INDEX': qm_atom,
                        'MM_INDEX': mm_atom,
                        'QM_ELEM': qm_elem,
                        'MM_ELEM': mm_elem,
                        'ALPHA_IMOMM': alpha,
                    })

    if unknown_alpha_pairs:
        pairs = ", ".join(f"{a}-{b}" for a, b in sorted(unknown_alpha_pairs))
        warn(
            f"Using default ALPHA_IMOMM={DEFAULT_ALPHA_IMOMM:.2f} for unsupported boundary pairs: {pairs}"
        )

    return links


def build_mm_adjacency(topo):
    """
    Build a full 1-based bonded adjacency map from AMBER bond arrays.
    """
    adjacency = defaultdict(set)
    for bond_arr in (topo.get_int_array('BONDS_INC_HYDROGEN'), topo.get_int_array('BONDS_WITHOUT_HYDROGEN')):
        for k in range(0, len(bond_arr) - 2, 3):
            a1 = bond_arr[k] // 3 + 1
            a2 = bond_arr[k + 1] // 3 + 1
            adjacency[a1].add(a2)
            adjacency[a2].add(a1)
    return dict(adjacency)


def enrich_link_with_m2(links, adjacency, qm_indices_set, charges_e,
                         atom_types=None, element_map=None, atomic_numbers=None):
    """
    Enrich link-bond metadata with M1 charge, M2 MM-neighbor indices, and
    (when resolvable) the element symbol of each M2 atom.

    The per-M2 element list (``M2_ELEMENTS``) lets the LINK-block emitter
    key the GEEP Gaussian radius (``RADIUS`` / ``CORR_RADIUS``) on the
    actual MM neighbour element rather than a uniform 0.80 Å default —
    see :data:`MM_KIND_GEEP_RADII` and Laino, Mohamed, Curioni,
    VandeVondele, JCTC 2, 1370 (2006), Table I.  ``M2_ELEMENTS`` is
    parallel to ``M2_INDICES``; entries default to ``'X'`` for any atom
    whose element we cannot resolve so the caller can fall back to
    ``MM_KIND_RADIUS_FALLBACK``.
    """
    qm_set = {int(i) for i in (qm_indices_set or set())}
    for link in links:
        m1 = int(link['MM_INDEX'])
        m2_set = set(adjacency.get(m1, set())) - qm_set - {int(link['QM_INDEX'])}
        link['M1_INDEX'] = m1
        m2_sorted = sorted(int(i) for i in m2_set)
        link['M2_INDICES'] = m2_sorted
        if atom_types is not None or element_map is not None or atomic_numbers is not None:
            link['M2_ELEMENTS'] = [
                (_element_for_atom(a, atom_types, element_map, atomic_numbers) or 'X')
                for a in m2_sorted
            ]
        else:
            link['M2_ELEMENTS'] = ['X'] * len(m2_sorted)
        if 1 <= m1 <= len(charges_e):
            link['M1_CHARGE_E'] = float(charges_e[m1 - 1])
        else:
            link['M1_CHARGE_E'] = 0.0


def detect_duplicate_m1_frontier_atoms(links):
    """Detect MM atoms (M1) that serve as the frontier for >1 link bond (C.1.b).

    A single M1 atom hosting multiple links means the same MM atom appears
    in two different &LINK blocks.  CP2K accepts this — but the resulting
    QM/MM embedding doubly-perturbs the M1 environment (each &LINK block
    independently rescales QMMM_SCALE_FACTOR/FIST_SCALE_FACTOR for its
    cut), and the per-link ADD_MM_CHARGE redistributions to disjoint M2
    sets compose in a way that is hard to audit post-hoc.

    Returns a dict ``{m1_index: [link_dict, ...]}`` containing only those
    M1 atoms that appear more than once.  Empty dict means no duplication.
    The detector is read-only: the caller decides whether to WARN, prompt
    the user to re-include M1 in the QM region, or accept the doubly-
    truncated embedding.

    Refs: Senn & Thiel, Angew. Chem. Int. Ed. 48, 1198 (2009), §3.1 —
          link-atom hygiene in QM/MM; Lin & Truhlar, Theor. Chem. Acc.
          117, 185 (2007), §2.2 — M1 as a single frontier per cut.
    """
    by_m1 = defaultdict(list)
    for link in (links or ()):
        m1 = link.get('M1_INDEX', link.get('MM_INDEX'))
        if m1 is None:
            continue
        by_m1[int(m1)].append(link)
    return {m1: lst for m1, lst in by_m1.items() if len(lst) > 1}


def normalize_boundary_charge_scheme(scheme):
    """Normalize boundary-charge scheme names to documented supported values."""
    resolved = str(scheme or DEFAULT_BOUNDARY_CHARGE_SCHEME).strip().upper()
    if resolved not in BOUNDARY_CHARGE_SCHEMES:
        return DEFAULT_BOUNDARY_CHARGE_SCHEME
    return resolved


def verify_per_link_boundary_charge_overrides(links, global_scheme,
                                                interactive=False,
                                                run_provenance=None):
    """
    Validate any per-link ``BOUNDARY_CHARGE_SCHEME`` overrides carried on
    link dicts (C.2.a).

    Link dicts may carry an optional ``BOUNDARY_CHARGE_SCHEME`` key that
    overrides the global scheme for that one &LINK block.  Common use
    cases:

      * Mixed boundaries where a single link hits a metal–ligand
        coordination site and must fall back to ``Z1`` while the bulk
        covalent cuts use ``CHARGE_SHIFT``.
      * Debug/benchmark workflows that A/B one link against another
        (Brunk & Rothlisberger, Chem. Rev. 115, 6217 (2015)).

    Verification rules:
      1. Token must be a documented :data:`BOUNDARY_CHARGE_SCHEMES` key.
      2. Redistribution schemes (``CHARGE_SHIFT``, ``CHARGE_SHIFT_FIST``)
         require a non-empty ``M2_INDICES``; otherwise ``Z1`` is the
         only physically meaningful fallback and we demote with WARN.
      3. Unknown / malformed overrides are stripped; the emitter will
         then use the global scheme.

    Returns a list of dicts summarising the verdict per affected link::

        [{'link_index': <int>, 'qm': <int>, 'mm': <int>,
          'requested': <str>, 'applied': <str>, 'verdict': 'accepted'
          | 'demoted' | 'rejected', 'reason': <str>}, ...]

    Side-effect: mutates ``link['BOUNDARY_CHARGE_SCHEME']`` in place to
    either the validated token, the demoted fallback, or pops the key
    entirely on rejection.  Every affected link is also recorded in
    ``run_provenance`` (when supplied) so the audit trail matches the
    CP2K input.
    """
    report = []
    global_norm = normalize_boundary_charge_scheme(global_scheme)
    for i, link in enumerate(links or []):
        if not isinstance(link, dict):
            continue
        raw = link.get('BOUNDARY_CHARGE_SCHEME')
        if raw is None:
            continue
        requested = str(raw).strip().upper()
        qm_idx = int(link.get('QM_INDEX') or -1)
        mm_idx = int(link.get('MM_INDEX') or -1)
        if requested not in BOUNDARY_CHARGE_SCHEMES:
            link.pop('BOUNDARY_CHARGE_SCHEME', None)
            verdict = {
                'link_index': i, 'qm': qm_idx, 'mm': mm_idx,
                'requested': requested, 'applied': global_norm,
                'verdict': 'rejected',
                'reason': (
                    f"Unknown boundary-charge scheme {requested!r}; "
                    f"allowed tokens are {list(BOUNDARY_CHARGE_SCHEMES)}."
                ),
            }
            report.append(verdict)
            warn(
                f"Per-link boundary-charge override rejected "
                f"(QM={qm_idx}, MM={mm_idx}): unknown token {requested!r}."
            )
            if run_provenance is not None:
                run_provenance.record(
                    kind='per_link_boundary_charge_override',
                    severity='correction',
                    source=('user' if interactive else 'auto'),
                    from_value=requested, to_value=global_norm,
                    accepted=False, reason=verdict['reason'],
                    citation='CP2K manual §FORCE_EVAL/QMMM/LINK',
                    context={'qm': qm_idx, 'mm': mm_idx},
                )
            continue
        m2_indices = link.get('M2_INDICES') or []
        needs_m2 = requested in BOUNDARY_CHARGE_REDISTRIBUTION_SCHEMES
        if needs_m2 and not m2_indices:
            link['BOUNDARY_CHARGE_SCHEME'] = 'Z1'
            verdict = {
                'link_index': i, 'qm': qm_idx, 'mm': mm_idx,
                'requested': requested, 'applied': 'Z1',
                'verdict': 'demoted',
                'reason': (
                    f"Override {requested!r} requires M2 atoms for charge "
                    "redistribution, but this link has none; demoted to Z1 "
                    "(zero M1 in the QM/MM embedding only)."
                ),
            }
            report.append(verdict)
            warn(
                f"Per-link boundary-charge override demoted "
                f"(QM={qm_idx}, MM={mm_idx}): {requested} → Z1 (no M2)."
            )
            if run_provenance is not None:
                run_provenance.record(
                    kind='per_link_boundary_charge_override',
                    severity='recommendation',
                    source=('user' if interactive else 'auto'),
                    from_value=requested, to_value='Z1',
                    accepted=True, reason=verdict['reason'],
                    citation=(
                        "Brunk & Rothlisberger, Chem. Rev. 115, 6217 (2015); "
                        "Laino et al., JCTC 2, 1370 (2006)"
                    ),
                    context={'qm': qm_idx, 'mm': mm_idx},
                )
            continue
        # Valid + redistribution-ready (or non-redistribution scheme).
        link['BOUNDARY_CHARGE_SCHEME'] = requested
        verdict = {
            'link_index': i, 'qm': qm_idx, 'mm': mm_idx,
            'requested': requested, 'applied': requested,
            'verdict': 'accepted',
            'reason': (
                f"Per-link override {requested!r} accepted "
                f"(global scheme is {global_norm!r})."
            ),
        }
        report.append(verdict)
        info(
            f"Per-link boundary-charge override accepted "
            f"(QM={qm_idx}, MM={mm_idx}): {requested} "
            f"(global is {global_norm})."
        )
        if run_provenance is not None:
            run_provenance.record(
                kind='per_link_boundary_charge_override',
                severity='info',
                source=('user' if interactive else 'auto'),
                from_value=global_norm, to_value=requested,
                accepted=True, reason=verdict['reason'],
                citation=(
                    "Laino et al., JCTC 2, 1370 (2006); "
                    "Senn & Thiel, Angew. Chem. Int. Ed. 48, 1198 (2009)"
                ),
                context={'qm': qm_idx, 'mm': mm_idx},
            )
    return report


def generate_link_charge_directives(link, scheme):
    """
    Build CP2K LINK-block charge directives for the selected boundary scheme.

    A per-link override may be present on ``link['BOUNDARY_CHARGE_SCHEME']``;
    when set to a valid BOUNDARY_CHARGE_SCHEMES key it takes precedence
    over the global ``scheme`` argument.  The override must have already
    been validated by :func:`verify_per_link_boundary_charge_overrides`
    (C.2.a); unvalidated or unknown override values silently fall back
    to the global scheme so an invalid override never reaches CP2K.
    Refs: Senn & Thiel, Angew. Chem. Int. Ed. 48, 1198 (2009);
    Laino et al., JCTC 2, 1370 (2006).
    """
    per_link = link.get('BOUNDARY_CHARGE_SCHEME') if isinstance(link, dict) else None
    if per_link:
        per_link_token = str(per_link).strip().upper()
        if per_link_token in BOUNDARY_CHARGE_SCHEMES:
            scheme = per_link_token
    resolved = normalize_boundary_charge_scheme(scheme)

    m1_index = int(link.get('M1_INDEX') or link.get('MM_INDEX'))
    m1_charge = float(link.get('M1_CHARGE_E', 0.0) or 0.0)
    m2_indices = [int(i) for i in (link.get('M2_INDICES') or [])]
    classical_scale = 1.0
    embedding_scale = 1.0

    if resolved == 'NONE':
        return [
            "! Legacy mode: keep the full M1 charge in both QM/MM embedding and classical FIST electrostatics.\n",
            "QMMM_SCALE_FACTOR 1.0\n",
            "FIST_SCALE_FACTOR 1.0\n",
        ]

    if resolved in BOUNDARY_CHARGE_REDISTRIBUTION_SCHEMES and (
        'M1_CHARGE_E' not in link or 'M2_INDICES' not in link
    ):
        if not link.get('_boundary_charge_enrichment_warned'):
            warn(
                f"Missing M1/M2 enrichment for link QM={link.get('QM_INDEX')} MM={link.get('MM_INDEX')}; "
                "falling back to Z1."
            )
            link['_boundary_charge_enrichment_warned'] = True
        resolved = 'Z1'

    if resolved in BOUNDARY_CHARGE_REDISTRIBUTION_SCHEMES and not m2_indices:
        if not link.get('_boundary_charge_empty_m2_warned'):
            warn(
                f"Link QM={link.get('QM_INDEX')} MM(M1)={link.get('MM_INDEX')} has no MM-side M2 neighbors; "
                "falling back to Z1."
            )
            link['_boundary_charge_empty_m2_warned'] = True
        resolved = 'Z1'

    if resolved == 'Z1':
        return [
            "! Z1 fallback: remove the M1 charge only from the QM/MM embedding; keep the classical FIST charge unchanged.\n",
            "QMMM_SCALE_FACTOR 0.0\n",
            "FIST_SCALE_FACTOR 1.0\n",
        ]

    # CP2K documents QMMM_SCALE_FACTOR as the embedding-side scaler and
    # FIST_SCALE_FACTOR as the classical MM scaler for the frontier atom.
    # The pipeline default keeps FIST_SCALE_FACTOR 1.0 so the MM force field
    # remains unchanged while the QM/MM embedding gets the frontier correction.
    embedding_scale = 0.0
    if resolved == 'CHARGE_SHIFT_FIST':
        classical_scale = 0.0

    if resolved == 'CHARGE_SHIFT_FIST':
        # ── CHARGE_SHIFT_FIST advisory (C.2.b) ────────────────────────────
        # Setting both QMMM and FIST scale factors to zero removes the M1
        # frontier charge from BOTH the QM/MM embedding seen by the QM
        # region AND the classical force-field electrostatics felt by the
        # MM subsystem.  This is occasionally needed when the M1 atom
        # carries a large MM charge that the FIST point-charge model
        # cannot represent without distorting nearby MM electrostatics —
        # but it perturbs the classical force field away from its
        # parameterised form, so the deviation should be tracked.
        # Refs: Brunk & Rothlisberger, Chem. Rev. 115, 6217 (2015) —
        #       review of QM/MM electrostatic embedding strategies;
        #       Sherwood et al., J. Mol. Struct. THEOCHEM 632, 1 (2003) —
        #       per-link FIST charge handling in production QM/MM stacks;
        #       Lin & Truhlar, Theor. Chem. Acc. 117, 185 (2007) §2.3 —
        #       caveats of full M1 charge removal from the classical model.
        lines = [
            "! Aggressive override (CHARGE_SHIFT_FIST): remove M1 from BOTH the QM/MM embedding AND the\n",
            "! classical FIST charge model.  This perturbs the parameterised force field on the residue\n",
            "! containing M1; only use when the FIST point-charge model is itself a known limitation\n",
            "! (e.g. M1 carries an unusually large MM charge that distorts nearby MM electrostatics).\n",
            "! Refs: Brunk & Rothlisberger, Chem. Rev. 115, 6217 (2015); Sherwood et al., JMS-Theochem\n",
            "!       632, 1 (2003); Lin & Truhlar, Theor. Chem. Acc. 117, 185 (2007).\n",
            "! ADD_MM_CHARGE redistributes the removed embedding charge to M2 atoms.\n",
            "! CP2K adds one source per block; documented M1->M2 with ALPHA 0.0 places it exactly on M2.\n",
            f"QMMM_SCALE_FACTOR {embedding_scale:.1f}\n",
            f"FIST_SCALE_FACTOR {classical_scale:.1f}\n",
        ]
    else:
        lines = [
            "! Recommended biomolecular default: remove M1 only from the QM/MM embedding seen by the QM region.\n",
            "! FIST_SCALE_FACTOR 1.0 preserves the original classical FIST charge while the embedding is corrected.\n",
            "! ADD_MM_CHARGE redistributes the removed embedding charge to M2 atoms.\n",
            "! CP2K adds one source per block; documented M1->M2 with ALPHA 0.0 places it exactly on M2.\n",
            f"QMMM_SCALE_FACTOR {embedding_scale:.1f}\n",
            f"FIST_SCALE_FACTOR {classical_scale:.1f}\n",
        ]
    if abs(m1_charge) <= 1.0e-8:
        return lines

    charge_per_m2 = m1_charge / float(len(m2_indices))
    # ── C.1.c: element-keyed ADD_MM_CHARGE GEEP radius ───────────────────
    # CP2K's GEEP electrostatic embedding replaces each point charge
    # with a spherical Gaussian whose width (RADIUS / CORR_RADIUS) must
    # match the MM atom's effective size.  The previous uniform 0.80 Å
    # default is correct for light-element M2 atoms (C/N/O/S) but is
    # noticeably too narrow for alkali ions (1.1–1.5 Å) and too wide
    # for hydrogen (0.44 Å).  We now read the per-M2 element from
    # link['M2_ELEMENTS'] (populated by enrich_link_with_m2) and key
    # the Gaussian width into MM_KIND_GEEP_RADII — the same table
    # already used by the &QMMM/&MM_KIND block generator — so the
    # embedding stays self-consistent across &MM_KIND and &ADD_MM_CHARGE.
    # Refs: Laino, Mohamed, Curioni, VandeVondele, JCTC 2, 1370 (2006),
    #       Table I — GEEP Gaussian radii for periodic QM/MM.
    m2_elements = link.get('M2_ELEMENTS') or []
    # CP2K stores one added charge per ADD_MM_CHARGE block and places it at
    # alpha*r(Index1) + (1-alpha)*r(Index2). Using the documented M1->M2
    # direction with ALPHA 0.0 therefore places one source exactly on M2.
    for idx_in_list, m2_index in enumerate(m2_indices):
        m2_elem = (
            str(m2_elements[idx_in_list]).upper()
            if idx_in_list < len(m2_elements) else 'X'
        )
        radius_ang = MM_KIND_GEEP_RADII.get(m2_elem, MM_KIND_RADIUS_FALLBACK)
        lines.append("&ADD_MM_CHARGE\n")
        lines.append(f"  ATOM_INDEX_1 {m1_index}\n")
        lines.append(f"  ATOM_INDEX_2 {m2_index}\n")
        lines.append("  ALPHA  0.0\n")
        lines.append(f"  CHARGE {charge_per_m2: .10f}\n")
        lines.append(f"  RADIUS {radius_ang:.3f}     ! element={m2_elem} (Laino 2006, Tbl I; fallback={MM_KIND_RADIUS_FALLBACK})\n")
        lines.append(f"  CORR_RADIUS {radius_ang:.3f}\n")
        lines.append("&END ADD_MM_CHARGE\n")
    # ── Defensive: verify total redistributed charge matches M1 ───────
    total_redistributed = charge_per_m2 * len(m2_indices)
    if abs(total_redistributed - m1_charge) > 1.0e-10:
        warn(
            f"LINK ADD_MM_CHARGE charge drift: M1={m1_charge:.10f}, "
            f"redistributed={total_redistributed:.10f}"
        )
    return lines


# ─── KIND Block Generation ────────────────────────────────────────────────────

def extract_mm_element_symbols(mm_kinds_lines):
    """
    Scan &KIND blocks emitted by generate_mm_kinds and return the set of
    element symbols that appear in `ELEMENT <sym>` lines.

    The QM/MM assembler uses this set to emit &QMMM/&MM_KIND blocks that
    pin explicit Gaussian embedding radii per element (Laino, Mohamed,
    Curioni, VandeVondele, JCTC 2, 1370 (2006)).  Without these radii
    CP2K falls back to a single default radius applied to every MM atom,
    which over-smooths near-field embedding for heavy ions and
    under-smooths for hydrogen.
    """
    elements = set()
    for raw in (mm_kinds_lines or ()):
        line = raw.strip()
        if line.upper().startswith('ELEMENT'):
            parts = line.split()
            if len(parts) >= 2:
                sym = parts[1].strip().upper()
                # Synthetic alias placeholder; carries no chemistry.
                if sym and sym != 'X':
                    elements.add(sym)
    return elements


def generate_mm_kinds(atom_types, charges, element_map, qm_element_symbols):
    """
    Generate MM &KIND blocks with ELEMENT mapping for exactly the CP2K-required
    conformed kind names (no generic C1..C400 expansion).
    """
    lines = []
    qm_syms = {s.upper() for s in qm_element_symbols}
    _, kind_to_base = derive_cp2k_conformed_kinds(atom_types, charges)

    for kname in sorted(kind_to_base.keys()):
        # Bare element kinds are defined in QM KIND blocks with basis/potential.
        if kname.upper() in qm_syms:
            continue

        base = kind_to_base[kname]
        elem = element_map.get(base)
        if not elem:
            # CP2K KIND keeps ELEMENT explicit, so synthetic aliases never carry chemistry.
            elem = 'X' if _ATOM_TYPE_ALIAS_RE.match(str(base)) else (infer_element(base) or 'X')

        lines.append(f"  &KIND {kname}\n")
        lines.append(f"    ELEMENT {elem}\n")
        lines.append(f"  &END KIND\n")

    return lines


def collect_topology_variant_data(topo, qm_element_symbols, charge_array_override=None, alias_plan=None):
    """
    Collect MM-kind generation data from one topology view.

    The topology object may be the original in-memory AmberTopology or a
    re-parsed prepared PRMTOP.  An optional charge override lets dry-run mode
    preview a redistributed QM/MM topology without writing files.
    """
    if alias_plan is not None:
        # Reusing one canonical alias plan for dry-run and real execution follows
        # Sandve et al. 2013 Rule 1: the same result should come from the same inputs.
        element_map_for_kinds = _resolved_alias_element_map(alias_plan)
        unresolved = list(alias_plan.unresolved_aliases)
        atom_types_for_kinds = list(alias_plan.atom_aliases)
    else:
        element_map_for_kinds, unresolved, atom_types_for_kinds = build_element_map(topo)
    if charge_array_override is None:
        atom_charges_for_kinds = topo.get_float_array('CHARGE')
    else:
        atom_charges_for_kinds = list(charge_array_override)
    # ── Round charges to Fortran E16.8 precision ────────────────────────
    # AMBER PRMTOP stores charges in %FORMAT(5E16.8), giving 8 decimal
    # digits in scientific notation.  derive_cp2k_conformed_kinds() uses
    # exact float equality to assign charge-splitting suffixes.  If we
    # compare Python double-precision charges against the E16.8-rounded
    # values that CP2K reads from the written PRMTOP, the suffix mapping
    # can diverge, producing KIND blocks that don't match the topology.
    # Rounding here ensures the pipeline's KIND assignment matches CP2K's.
    # Ref: AMBER File Specification §CHARGE — %FORMAT(5E16.8);
    #      CP2K topology_amber.F parse_amber_section() reads the same format.
    atom_charges_for_kinds = [float(f"{c:16.8E}") for c in atom_charges_for_kinds]
    if len(atom_types_for_kinds) != len(atom_charges_for_kinds):
        warn(
            "AMBER_ATOM_TYPE/CHARGE length mismatch in topology view "
            f"({len(atom_types_for_kinds)} vs {len(atom_charges_for_kinds)}). "
            "Using the shared prefix length."
        )
    mm_kinds = generate_mm_kinds(
        atom_types_for_kinds,
        atom_charges_for_kinds,
        element_map_for_kinds,
        qm_element_symbols,
    )
    return {
        'element_map': element_map_for_kinds,
        'unresolved': unresolved,
        'atom_types': atom_types_for_kinds,
        'atom_charges': atom_charges_for_kinds,
        'mm_kinds': mm_kinds,
    }


# ── B.1.c: Functional → GTH pseudopotential prefix table ─────────────
# GTH (Goedecker-Teter-Hutter) pseudopotentials are *functional-specific*:
# the PP is generated by solving the reference atom Kohn–Sham problem in
# the same functional that will later drive the solid-state / molecular
# calculation, so energy differentials are self-consistent.  Using a
# GTH-PBE pseudopotential with a non-PBE functional is *not* strictly
# forbidden — CP2K will integrate the inputs — but the all-electron
# reference the PP reproduces no longer matches the valence functional,
# which shifts core–valence partitioning and can bias relative energies
# of several tenths of mHa per atom.  We therefore:
#   * prefer a functional-matched PP when CP2K ships one (exact=True);
#   * accept a proxy PP with an explicit advisory when the functional
#     has no shipped self-consistent PP (exact=False);
#   * refuse silent fallback for functionals we have no evidence for —
#     the operator must confirm via ``validate_functional_pp_match``.
#
# Primary references:
#   * Goedecker, Teter, Hutter, *Phys. Rev. B* **54**, 1703 (1996) — GTH
#     pseudopotential formulation.
#   * Hartwigsen, Goedecker, Hutter, *Phys. Rev. B* **58**, 3641 (1998)
#     — GTH-LDA parametrisation (PADE).
#   * Krack, *Theor. Chem. Acc.* **114**, 145 (2005) — GTH-PBE, GTH-BLYP,
#     GTH-BP and other GGA parametrisations shipped with CP2K.
#   * CP2K Manual §4.3 (POTENTIAL keyword) — file layout and matching
#     rules in POTENTIAL / POTENTIAL_UZH / GTH_POTENTIALS.
#
# Values are (prefix, exact, note).  ``exact`` is True only when the GTH
# PP is generated at the listed functional; proxies carry a short note
# explaining which self-consistent functional was used and why the
# proxy is the least-worst choice.  Hybrid functionals (B3LYP, PBE0,
# HSE06, BHandHLYP) never have a self-consistent GTH parametrisation
# — the exchange-correlation kernel contains non-local Hartree–Fock
# which GTH construction does not accommodate — and by community
# convention the underlying GGA component's GTH PP is used (Guidon,
# Hutter & VandeVondele, *JCTC* **5**, 3010 (2009), §2.2).
_FUNCTIONAL_TO_PP = {
    # GGAs — self-consistent GTH parametrisations shipped with CP2K.
    'PBE':       ('GTH-PBE',   True,  'GGA; Krack 2005'),
    'BLYP':      ('GTH-BLYP',  True,  'GGA; Krack 2005'),
    'BP86':      ('GTH-BP',    True,  'GGA; Krack 2005'),
    'OLYP':      ('GTH-OLYP',  True,  'GGA; Krack 2005'),
    'HCTH120':   ('GTH-HCTH120', True, 'GGA; Krack 2005'),
    'HCTH407':   ('GTH-HCTH407', True, 'GGA; Krack 2005'),
    # Meta-GGAs — no shipped self-consistent GTH; best proxy is GTH-PBE.
    'PBESOL':    ('GTH-PBE',   False,
                  "PBEsol shares PBE's xc kernel structure; no shipped "
                  "GTH-PBESol, proxy is GTH-PBE"),
    'SCAN':      ('GTH-PBE',   False,
                  "meta-GGA; no shipped GTH-SCAN; proxy is GTH-PBE"),
    'R2SCAN':    ('GTH-PBE',   False,
                  "meta-GGA; no shipped GTH-r2SCAN; proxy is GTH-PBE"),
    'TPSS':      ('GTH-PBE',   False,
                  "meta-GGA; no shipped GTH-TPSS; proxy is GTH-PBE"),
    # Hybrids — by convention reuse the parent-GGA PP (Guidon 2009).
    'PBE0':      ('GTH-PBE',   False,
                  "hybrid with 25% HF exchange on PBE; reuse GTH-PBE "
                  "per Guidon, Hutter & VandeVondele JCTC 5, 3010 (2009)"),
    'B3LYP':     ('GTH-BLYP',  False,
                  "hybrid with 20% HF exchange on BLYP; reuse GTH-BLYP "
                  "per Krack 2005 + Guidon 2009"),
    'BHANDHLYP': ('GTH-BLYP',  False,
                  "hybrid with 50% HF exchange on BLYP; reuse GTH-BLYP"),
    'HSE06':     ('GTH-PBE',   False,
                  "range-separated hybrid on PBE; reuse GTH-PBE"),
    # Common long-range-corrected families — same GGA-proxy convention.
    'CAM-B3LYP': ('GTH-BLYP',  False, "LC-hybrid on BLYP; reuse GTH-BLYP"),
    'LC-OMEGAPBE': ('GTH-PBE', False, "LC-hybrid on PBE; reuse GTH-PBE"),
    # LDA / PADE — the historical default, parametrised by Hartwigsen 1998.
    'LDA':       ('GTH-PADE',  True,  'LDA; Hartwigsen, Goedecker, Hutter 1998'),
    'PADE':      ('GTH-PADE',  True,  'LDA; Hartwigsen, Goedecker, Hutter 1998'),
}

# Fallback prefix used only when the operator has confirmed, after a
# WARN-then-ask prompt, that they intend to proceed with an unmatched
# functional.  This is ``GTH-PBE`` rather than ``GTH-PADE`` because
# modern biomolecular QM/MM defaults (PBE/PBE0/BLYP/B3LYP) all reduce
# to a PBE-generation GTH PP, so PBE-family atoms remain consistent
# even when the functional label is unrecognised (e.g. a typo or a
# novel composite functional not yet in the table above).
_FUNCTIONAL_TO_PP_DEFAULT_FALLBACK = 'GTH-PBE'


# ── D.1.a: DFTD3(BJ) parameter availability gate ──────────────────────────────
# CP2K writes &VDW_POTENTIAL/&PAIR_POTENTIAL with TYPE DFTD3(BJ) and a
# REFERENCE_FUNCTIONAL.  At runtime CP2K looks up that functional in the
# Grimme parameter file (dftd3.dat) and fails with a hard stop if the
# functional has no entry.  The table below records which functionals have
# published Becke–Johnson damping parameters in Grimme's official set so the
# pipeline can gate the VDW block before emission rather than after CP2K
# parses it.
#
# Sources:
#   * Grimme, Antony, Ehrlich, Krieg, J. Chem. Phys. 132, 154104 (2010)
#     — original DFT-D3 with zero damping.
#   * Grimme, Ehrlich, Goerigk, J. Comput. Chem. 32, 1456 (2011) — the
#     Becke–Johnson (rational) damping variant used here.  §3 lists the
#     functionals with published BJ-damping parameters.
#   * Goerigk et al., Phys. Chem. Chem. Phys. 19, 32184 (2017) — GMTKN55
#     benchmark summary: an authoritative consolidated table of DFTD3(BJ)-
#     parameterised functionals.
#   * dftd3.dat shipped with CP2K (data/dftd3.dat); the set actually
#     consulted by CP2K at runtime.
#
# Values: True  → functional has published BJ parameters in dftd3.dat
#         False → no BJ parameters published; CP2K will fail at runtime
#                 unless the operator provides a patched dftd3.dat
# A functional missing from the table is treated as "unknown" — same
# no-silent-modifications handling as unknown GTH PP prefixes.
_FUNCTIONAL_DFTD3_PARAMETER_AVAILABLE = {
    # GGAs covered by Grimme 2011
    'PBE':         True,
    'BLYP':        True,
    'BP86':        True,
    'B97-D':       True,
    'PW91':        True,
    'REVPBE':      True,
    'RPBE':        True,
    'OLYP':        True,
    'PBESOL':      True,
    # Meta-GGAs
    'TPSS':        True,
    'M06L':        True,
    'SCAN':        True,
    'R2SCAN':      True,
    # Common hybrids
    'PBE0':        True,
    'B3LYP':       True,
    'BHANDHLYP':   True,
    'TPSSH':       True,
    'HSE06':       True,
    'B3PW91':      True,
    'B97':         True,
    # Range-separated hybrids
    'CAM-B3LYP':   True,
    'LC-WPBE':     True,
    'WB97X':       True,
    # LDA has no DFTD3 parameters: dispersion on LDA is a scientifically
    # dubious combination and Grimme explicitly did not parametrise it.
    'LDA':         False,
    'PADE':        False,
}


# ── D.1.b: DFTD4 availability table and minimum CP2K version ─────────────────
# DFTD4 (Caldeweyher et al., J. Chem. Phys. 150, 154122 (2019)) is the
# charge- and geometry-dependent successor to DFTD3.  For charged QM/MM
# systems (enzyme active sites, metal cofactors, charged substrates) DFTD4
# dispersion coefficients respond to local polarisation, yielding more
# accurate non-covalent interactions than DFTD3(BJ) — especially in
# biomolecular contexts where the QM region carries net charge.  However
# DFTD4 is only available in CP2K ≥ 8.1 (the release introducing the
# s-dftd4 library linkage — see CP2K release notes "CP2K 8.1").  Earlier
# builds simply lack the keyword.
#
# The table mirrors the DFTD3 table: True if the functional has published
# DFTD4 damping parameters (Caldeweyher 2019 §III and the upstream
# s-dftd4 param file).  None = unknown functional, treated as "offer
# DFTD3 instead" to stay safe.
CP2K_DFTD4_MIN_VERSION = (8, 1)

_FUNCTIONAL_DFTD4_PARAMETER_AVAILABLE = {
    # Common GGAs
    'PBE':        True,
    'BLYP':       True,
    'BP86':       True,
    'REVPBE':     True,
    'RPBE':       True,
    'PBESOL':     True,
    # Meta-GGAs
    'TPSS':       True,
    'SCAN':       True,
    'R2SCAN':     True,
    # Hybrids
    'PBE0':       True,
    'B3LYP':      True,
    'BHANDHLYP':  True,
    'TPSSH':      True,
    'HSE06':      True,
    # Range-separated hybrids
    'CAM-B3LYP':  True,
    'WB97X':      True,
    # LDA: intentionally unparameterised in DFTD4 (same rationale as DFTD3).
    'LDA':        False,
    'PADE':       False,
}


def recommend_dftd4_upgrade(functional, cp2k_version_tuple,
                            interactive=False, run_provenance=None):
    """Interactive advisory to upgrade DFTD3(BJ) → DFTD4 when available.

    Returns ``True`` when the caller should switch to DFTD4, ``False``
    otherwise.  Non-interactive callers get ``False`` (unchanged DFTD3
    path) with an informational WARN when the upgrade would have been
    offered — per feedback_no_silent_modifications the pipeline never
    promotes dispersion schemes silently.

    The helper guards against:
      * CP2K too old (< 8.1) → never offer
      * Functional has no DFTD4 parameters → never offer
      * Non-interactive mode → never promote; emit an info-level WARN
        so the operator notices the available upgrade in the log
    """
    fkey = str(functional or '').strip().upper()
    if not cp2k_version_tuple:
        return False
    if not cp2k_version_at_least(cp2k_version_tuple, CP2K_DFTD4_MIN_VERSION):
        return False
    if not _FUNCTIONAL_DFTD4_PARAMETER_AVAILABLE.get(fkey):
        return False
    rationale = (
        f"DFTD4 is available in your CP2K build "
        f"(version {format_cp2k_version(cp2k_version_tuple)} ≥ "
        f"{format_cp2k_version(CP2K_DFTD4_MIN_VERSION)}) and has "
        f"published parameters for functional {fkey}.  For charged "
        "biomolecular QM regions DFTD4's charge-dependent coefficients "
        "typically give more physically consistent dispersion than "
        "DFTD3(BJ) (Caldeweyher et al., J. Chem. Phys. 150, 154122 "
        "(2019))."
    )
    accepted = False
    source = 'non_interactive_warn'
    if interactive:
        source = 'interactive_prompt'
        detail(rationale)
        accepted = ask_yes(
            "Upgrade VDW_POTENTIAL from DFTD3(BJ) to DFTD4?",
            default=False,
        )
    else:
        warn(
            rationale
            + "  Non-interactive mode will keep DFTD3(BJ); rerun "
            "interactively or pass --dispersion-scheme DFTD4 to promote."
        )
    if run_provenance is not None:
        run_provenance.record(
            kind='dftd4_upgrade_offer',
            severity='recommendation',
            source=source,
            from_value='DFTD3(BJ)',
            to_value=('DFTD4' if accepted else 'DFTD3(BJ)'),
            accepted=accepted,
            reason=rationale,
            citation=(
                "Caldeweyher, Ehlert, Hansen, Neugebauer, Spicher, Bannwarth, "
                "Grimme, J. Chem. Phys. 150, 154122 (2019); "
                "CP2K 8.1 release notes (DFTD4 library linkage)"
            ),
        )
    return accepted


# ── D.2.a: ADMM purification method choice (ADVANCED only) ────────────────
# CP2K's &AUXILIARY_DENSITY_MATRIX_METHOD supports several purification
# schemes that project the auxiliary density onto an idempotent density
# matrix before HFX evaluation.  The pipeline currently picks automatically:
#
#   * SCF engine = OT  → MO_DIAG  (diagonalise in Cauchy representation,
#                         Guidon et al., JCTC 6, 2348 (2010); recommended
#                         for BOMD closed-shell hybrid DFT).
#   * SCF engine = DIAG → NONE    (MO_DIAG requires OT per cp_control_utils;
#                         see CP2K-user list discussion, Watkins 2015).
#
# ADVANCED operators occasionally need a third option:
#
#   * NON_PURIFICATION — skip the purification step entirely and use the
#     projected auxiliary density as-is.  Useful for benchmarking the
#     HFX error introduced by purification (Merlot et al., J. Chem. Phys.
#     141, 094104 (2014), §III) or for systems where MO_DIAG is numerically
#     unstable (near-degenerate auxiliary MOs).  Produces larger HFX errors
#     than MO_DIAG but is stable and still OT-compatible.
#
# The override is exposed only through the ADVANCED SCF wizard so non-expert
# users remain on the engine-matched default.  Per
# feedback_no_silent_modifications the pipeline still emits the engine-
# matched method unless the operator explicitly picks an override.
ADMM_PURIFICATION_METHODS = ('NONE', 'NON_PURIFICATION', 'MO_DIAG')


def validate_admm_purification_override(value):
    """Normalize an ADMM purification override value.

    Returns one of ``ADMM_PURIFICATION_METHODS`` or ``None`` for
    "use pipeline default".  Raises ValueError on unknown tokens.
    """
    if value is None:
        return None
    token = str(value).strip().upper()
    if not token or token in {'DEFAULT', 'AUTO'}:
        return None
    if token not in ADMM_PURIFICATION_METHODS:
        allowed = ', '.join(ADMM_PURIFICATION_METHODS)
        raise ValueError(
            f"Invalid ADMM_PURIFICATION_METHOD '{value}'. Allowed: {allowed}"
        )
    return token


DISPERSION_SCHEMES = ('DFTD3_BJ', 'DFTD4', 'NONE')


def _validate_dispersion_scheme(scheme):
    """Normalize dispersion-scheme to one of ``DISPERSION_SCHEMES``."""
    if scheme is None:
        return 'DFTD3_BJ'
    value = str(scheme).strip().upper().replace('-', '_').replace('(', '_').replace(')', '')
    aliases = {
        'DFTD3': 'DFTD3_BJ', 'DFTD3_BJ': 'DFTD3_BJ',
        'D3': 'DFTD3_BJ', 'D3BJ': 'DFTD3_BJ',
        'DFTD4': 'DFTD4', 'D4': 'DFTD4',
        'NONE': 'NONE', 'OFF': 'NONE', '': 'DFTD3_BJ',
    }
    key = aliases.get(value)
    if key is None:
        raise ValueError(
            f"Invalid dispersion scheme '{scheme}'. "
            f"Allowed: {', '.join(DISPERSION_SCHEMES)}"
        )
    return key


def validate_functional_dftd3_availability(functional, interactive=False,
                                           run_provenance=None):
    """Gate DFTD3(BJ) emission against Grimme's dftd3.dat parameter set.

    Returns True when the functional is known to have DFTD3(BJ) parameters,
    False when it is known NOT to have them (e.g. LDA/PADE), and None when
    the functional is not in the table — the operator is asked or warned.

    Non-availability handling follows feedback_no_silent_modifications:
      * explicit False (known-unparameterised) → WARN + optional abort;
      * None (unknown) → WARN + prompt in interactive mode, WARN only
        in non-interactive mode; run_provenance records the advisory.

    Callers decide what to do with the return value — typically by
    skipping VDW_POTENTIAL emission when the functional is unparameterised
    and the operator does not supply an override.
    """
    fkey = str(functional or '').strip().upper()
    status = _FUNCTIONAL_DFTD3_PARAMETER_AVAILABLE.get(fkey)
    if status is True:
        return True
    message_known_false = (
        f"Functional '{fkey}' has no published DFTD3(BJ) parameters "
        "(Grimme dftd3.dat); emitting &VDW_POTENTIAL TYPE DFTD3(BJ) will fail "
        "at CP2K runtime with 'reference functional not found'.  Dispersion "
        f"correction on '{fkey}' is also scientifically discouraged."
    )
    message_unknown = (
        f"Functional '{fkey}' is not in the pipeline's DFTD3(BJ) "
        "parameter-availability table.  CP2K may or may not have a "
        "dftd3.dat entry for it.  Omitting DFTD3 is the safer default."
    )
    if status is False:
        warn(message_known_false)
        if run_provenance is not None:
            run_provenance.record(
                kind='dftd3_functional_unparameterised',
                severity='hard_stop_candidate',
                source='auto',
                from_value=fkey,
                to_value='DFTD3 omitted',
                accepted=False,
                reason=message_known_false,
                citation=(
                    "Grimme, Ehrlich, Goerigk, J. Comput. Chem. 32, 1456 (2011); "
                    "Goerigk et al., PCCP 19, 32184 (2017)"
                ),
            )
        return False
    # status is None → unknown functional.
    warn(message_unknown)
    accepted = False
    if interactive:
        accepted = ask_yes(
            f"Proceed with DFTD3(BJ) REFERENCE_FUNCTIONAL={fkey} anyway? "
            "(pick 'no' to skip VDW_POTENTIAL and avoid a possible CP2K runtime error)",
            default=False,
        )
    if run_provenance is not None:
        run_provenance.record(
            kind='dftd3_functional_unknown_parameters',
            severity='recommendation',
            source='interactive_prompt' if interactive else 'non_interactive_warn',
            from_value=fkey,
            to_value=('DFTD3 emitted (operator consent)' if accepted else 'DFTD3 omitted'),
            accepted=accepted,
            reason=message_unknown,
            citation=(
                "Grimme, Ehrlich, Goerigk, J. Comput. Chem. 32, 1456 (2011); "
                "CP2K data/dftd3.dat"
            ),
        )
    return accepted or None


def pp_prefix_for_functional(functional):
    """Return the GTH pseudopotential prefix matched to *functional*.

    Pure lookup with a silent fallback on unknown functionals — the
    advisory / confirmation path lives in
    :func:`validate_functional_pp_match`, which callers invoke once
    before emitting the KIND blocks.  Keeping this function pure makes
    it safe to use in tight inner loops (e.g. for KIND emission) while
    still surfacing the advisory at the correct one-shot point.
    """
    entry = _FUNCTIONAL_TO_PP.get(str(functional).upper())
    if entry is None:
        return _FUNCTIONAL_TO_PP_DEFAULT_FALLBACK
    return entry[0]


def validate_functional_pp_match(functional, interactive=False,
                                 run_provenance=None):
    """WARN-then-ask advisory for GTH-PP ↔ functional self-consistency.

    Returns the resolved prefix (possibly identical to the pure
    :func:`pp_prefix_for_functional` return value) and never raises.
    When the functional is in the table:
      * exact  → silent, log a detail() only.
      * proxy  → WARN both interactively and non-interactively; in
                 interactive mode offer to abort (``keep / abort``).
    When the functional is not in the table:
      * non-interactive → WARN and return the safe fallback prefix.
      * interactive     → ask the operator whether to proceed with
                          ``GTH-PBE`` as a fallback or abort.
    Provenance is recorded when a non-default decision is taken.
    """
    fkey = str(functional or '').strip().upper()
    entry = _FUNCTIONAL_TO_PP.get(fkey)
    if entry is not None:
        prefix, exact, note = entry
        if exact:
            detail(
                f"GTH-PP match: {fkey} → {prefix} (self-consistent; {note})."
            )
            return prefix
        # Proxy — self-consistency is approximate; always announce.
        warn(
            f"GTH-PP for '{fkey}' uses proxy prefix {prefix}: {note}. "
            "Core-valence partitioning is no longer self-consistent with "
            "the functional; relative energies carry a sub-mHa/atom "
            "systematic bias.  Ref: Krack, Theor. Chem. Acc. 114, 145 "
            "(2005); Guidon, Hutter & VandeVondele, JCTC 5, 3010 (2009)."
        )
        if interactive and not ask_yes(
            f"Proceed with proxy GTH pseudopotential '{prefix}' for {fkey}?",
            default=True,
        ):
            error(
                f"User aborted: no self-consistent GTH pseudopotential is "
                f"shipped for '{fkey}' and the proxy was declined. "
                "Either choose a functional with a shipped GTH PP "
                "(PBE/BLYP/BP86/OLYP/HCTH/LDA), or supply a custom "
                "POTENTIAL file with matching Kinds."
            )
            import sys
            sys.exit(1)
        if run_provenance is not None:
            run_provenance.record(
                kind='gth_pp_proxy_used',
                severity='recommendation',
                source='auto',
                from_value=fkey,
                to_value=prefix,
                accepted=True,
                reason=note,
                citation=(
                    'Krack, Theor. Chem. Acc. 114, 145 (2005); '
                    'Guidon, Hutter & VandeVondele, JCTC 5, 3010 (2009)'
                ),
            )
        return prefix
    # Unknown functional — no entry in the curated table at all.
    fallback = _FUNCTIONAL_TO_PP_DEFAULT_FALLBACK
    warn(
        f"No GTH pseudopotential mapping for functional '{fkey}'. "
        f"Safe fallback is {fallback}, but self-consistency is not "
        "guaranteed; sub-mHa/atom systematic bias is expected. "
        "Ref: CP2K Manual §4.3 (POTENTIAL keyword); Krack 2005."
    )
    if interactive:
        if not ask_yes(
            f"Proceed with fallback GTH prefix '{fallback}' for unknown "
            f"functional '{fkey}'?",
            default=False,
        ):
            error(
                f"User aborted: no GTH pseudopotential is mapped for "
                f"'{fkey}' and the fallback was declined. "
                "Either add '{fkey}' to _FUNCTIONAL_TO_PP with a cited "
                "justification, switch to a supported functional, or "
                "supply a custom POTENTIAL file with matching Kinds."
            )
            import sys
            sys.exit(1)
    if run_provenance is not None:
        run_provenance.record(
            kind='gth_pp_unknown_functional_fallback',
            severity='recommendation',
            source='auto',
            from_value=fkey,
            to_value=fallback,
            accepted=True,
            reason=(
                f"No entry in _FUNCTIONAL_TO_PP for '{fkey}'; "
                f"fallback to '{fallback}'."
            ),
            citation='CP2K Manual §4.3 (POTENTIAL keyword)',
        )
    return fallback

def _gth_valence_electrons(elem):
    """
    Return valence-electron count used by GTH potential conventions.
    Falls back to atomic number when no explicit GTH q-value mapping exists.
    """
    e = str(elem).strip().upper()
    qtag = GTH_CHARGE_MAP.get(e)
    if qtag:
        m = re.match(r'^[qQ](\d+)$', str(qtag).strip())
        if m:
            return int(m.group(1)), 'gth'
    z = SYMBOL_TO_ATOMIC_NUM.get(e)
    if z is not None:
        return int(z), 'z-fallback'
    return None, 'unknown'

def estimate_qm_electrons_for_spin(qm_elements, qm_charge, link_bonds=None):
    """
    Estimate CP2K QM electron count for multiplicity parity guidance.
    Uses per-element GTH valence electrons and includes QM/MM link-H caps.
    Returns (electron_count_or_None, metadata_dict).
    """
    qm_valence_electrons = 0
    unresolved = []
    source_counts = {'gth': 0, 'z-fallback': 0}

    for elem, indices in (qm_elements or {}).items():
        count = len(indices)
        if count <= 0:
            continue
        ve, source = _gth_valence_electrons(elem)
        if ve is None:
            unresolved.append(str(elem))
            continue
        qm_valence_electrons += int(ve) * int(count)
        source_counts[source] = source_counts.get(source, 0) + int(count)

    link_count = len(link_bonds or [])
    link_h_ve, _ = _gth_valence_electrons('H')
    if link_h_ve is None:
        link_h_ve = 1
    link_electrons_added = int(link_count) * int(link_h_ve)
    total_valence = int(qm_valence_electrons) + int(link_electrons_added)
    charge_subtracted = int(qm_charge)
    final_electron_count = int(total_valence - charge_subtracted)
    final_parity = 'even' if (final_electron_count % 2) == 0 else 'odd'

    meta = {
        'qm_valence_electrons': int(qm_valence_electrons),
        'link_electrons_added': int(link_electrons_added),
        'total_valence': int(total_valence),
        'charge_subtracted': int(charge_subtracted),
        'final_electron_count': int(final_electron_count),
        'final_electron_parity': final_parity,
        'qm_charge': int(qm_charge),
        'link_count': int(link_count),
        'link_h_valence': int(link_h_ve),
        'unresolved_elements': unresolved,
        'source_counts': source_counts,
    }
    if unresolved:
        meta['final_electron_count'] = None
        meta['final_electron_parity'] = 'unknown'
        return None, meta

    return int(final_electron_count), meta


# ─── Spin-State Decision Engine ──────────────────────────────────────────────
#
# Electron-count parity is a *necessary constraint* (an even electron count
# requires odd multiplicity and vice versa) but is *never sufficient* to
# determine the correct spin state.  Oxidation state, ligand field, spin–
# orbit coupling, and near-degenerate electronic configurations all matter
# for the true ground-state multiplicity.  No amount of topology inspection
# can substitute for explicit electronic-structure knowledge.
#
# The helpers below classify every decision as one of:
#   AUTHORITATIVE           — explicit user or parsed metadata; no guessing.
#   LOW_RISK_INFERRED       — parity-safe default for fully resolved
#                             main-group closed-shell biomolecular QM regions.
#   AMBIGUOUS_REQUIRES_USER — risk flags present; the pipeline must not
#                             silently assign a spin state.

# Cofactor / motif patterns that signal redox ambiguity when detected among
# the QM-region elements.  These never *assign* a spin state; they only
# raise risk flags that force explicit handling.
_REDOX_COFACTOR_ELEMENT_HINTS = {
    'FE', 'CU', 'MN', 'CO', 'MO', 'NI', 'V', 'CR', 'W', 'RU',
}
_OXYGEN_ACTIVATION_ELEMENTS = {'FE', 'CU', 'MN'}


# ── B.1.a: Known redox-active cofactor residue table ──────────────────
# The element-only hint set above catches metal-containing cofactors
# (heme, [Fe-S], copper sites) but misses the *organic* radicals that
# dominate flavoenzyme and quinone chemistry: FAD / FMN semiquinone,
# ubiquinone ↔ semiquinone ↔ ubiquinol, plastoquinone Q_A/Q_B.  Those
# cofactors contain only C / H / N / O / P and are therefore
# indistinguishable from an average peptide under element-only
# screening — yet they are the chemically dispositive species in the
# enzyme that houses them.  Silently picking a default singlet/doublet
# multiplicity for a QM region containing a flavin isoalloxazine is
# scientifically indefensible, so this table raises a *risk flag* and
# forces explicit multiplicity handling.  Membership never assigns a
# spin state.
#
# Keys are 3-letter PDB Chemical Component Dictionary IDs (RCSB-curated;
# https://www.wwpdb.org/data/ccd) as they appear in ``RESIDUE_LABEL`` of
# the prmtop after CHARMM-GUI preparation.  Values are a 3-tuple
# ``(name, class, radical_note)``.  Classes are used in the detector
# explanation shown to the operator.
#
# Class-level authoritative references (cited inline in warnings):
#   * flavin        — Massey, *FASEB J.* **9**, 473 (1995); Ghisla &
#                     Massey, *Eur. J. Biochem.* **181**, 1 (1989) —
#                     FAD/FMN quinone / semiquinone / hydroquinone
#                     one-electron redox cycle.
#   * heme          — Ortiz de Montellano (ed.), *Cytochrome P450*,
#                     3rd ed., Kluwer (2005) — Fe(II)/Fe(III)/Fe(IV)=O
#                     cycle, Compound-I π-cation radical.
#   * fe-s          — Beinert, Holm & Münck, *Science* **277**, 653
#                     (1997) — [2Fe-2S], [3Fe-4S], [4Fe-4S]
#                     electron-transfer centres with mixed-valence
#                     ground states.
#   * chlorophyll   — Deisenhofer et al., *J. Mol. Biol.* **180**, 385
#                     (1984) — photo-generated radical pair in the
#                     bacterial photosynthetic reaction centre.
#   * quinone       — Trumpower, *J. Biol. Chem.* **265**, 11409 (1990)
#                     — Q-cycle semiquinone in respiratory complex III.
#   * radical-sam   — Sofia et al., *Nucleic Acids Res.* **29**, 1097
#                     (2001) — 5′-deoxyadenosyl radical generation by
#                     SAM + [4Fe-4S]^{1+}.
KNOWN_REDOX_COFACTOR_RESIDUES = {
    # Flavins — C/H/N/O/P only; element-only detector would miss these.
    'FAD': ('Flavin adenine dinucleotide', 'flavin',
            'isoalloxazine quinone/semiquinone/hydroquinone cycle'),
    'FMN': ('Flavin mononucleotide', 'flavin',
            'isoalloxazine quinone/semiquinone/hydroquinone cycle'),
    'FDA': ('Dihydroflavin adenine dinucleotide', 'flavin',
            'FADH2 form; radical-prone on reoxidation'),
    'FMA': ('Reduced flavin mononucleotide', 'flavin',
            'FMNH2 form; radical-prone on reoxidation'),
    # Hemes — Fe-containing; element detector also fires, but named
    # entries are kept for didactic manifest output and to distinguish
    # heme class from [Fe-S] in the warning text.
    'HEM': ('Heme B (protoporphyrin IX Fe)', 'heme',
            'Fe(II)/Fe(III)/Fe(IV)=O cycle; Compound-I π-cation radical'),
    'HEB': ('Heme B (alias of HEM)', 'heme',
            'Fe(II)/Fe(III)/Fe(IV)=O cycle; Compound-I π-cation radical'),
    'HEA': ('Heme A', 'heme',
            'terminal electron acceptor in cytochrome c oxidase'),
    'HEC': ('Heme C (covalent thioether)', 'heme',
            'c-type heme; covalently bound through Cys side chains'),
    'HDM': ('Demethyl-heme intermediate', 'heme',
            'heme demethylation pathway intermediate'),
    'HAS': ('Heme A variant (siroheme context)', 'heme',
            'biosynthesis intermediate; keep until explicitly resolved'),
    # Iron-sulfur clusters — element detector also fires.
    'SF4': ('[4Fe-4S] iron-sulfur cluster', 'fe-s',
            'electron-transfer; mixed-valence ground states'),
    'F3S': ('[3Fe-4S] cluster', 'fe-s',
            'one-electron oxidised [4Fe-4S]; common under O₂ damage'),
    'FES': ('[2Fe-2S] ferredoxin / Rieske cluster', 'fe-s',
            'one-electron centre; antiferromagnetic in oxidised form'),
    'FS3': ('[3Fe-4S] alternate code', 'fe-s',
            'alias of F3S in some CHARMM-GUI outputs'),
    # Chlorophylls / pheophytins — photo-generated radicals.
    'CLA': ('Chlorophyll a', 'chlorophyll',
            'photo-induced cation radical in photosystem reaction centres'),
    'CHL': ('Chlorophyll a (alias)', 'chlorophyll',
            'same chemistry as CLA; alias in some force fields'),
    'BCL': ('Bacteriochlorophyll a', 'chlorophyll',
            'BRC special pair; cation radical on photo-excitation'),
    'BCB': ('Bacteriochlorophyll b', 'chlorophyll',
            'BRC variant of BCL'),
    'PHO': ('Pheophytin a', 'chlorophyll',
            'PSII acceptor A₀; transient anion radical'),
    'BPH': ('Bacteriopheophytin', 'chlorophyll',
            'BRC analogue of PHO'),
    # Quinones — organic; semiquinone intermediates.
    'UQ1': ('Ubiquinone-1', 'quinone', 'respiratory Q-cycle semiquinone'),
    'UQ2': ('Ubiquinone-2', 'quinone', 'respiratory Q-cycle semiquinone'),
    'UQ9': ('Ubiquinone-9', 'quinone', 'respiratory Q-cycle semiquinone'),
    'PQN': ('Plastoquinone', 'quinone',
            'PSII Q_A / Q_B semiquinone in photosynthesis'),
    'MQ7': ('Menaquinone-7', 'quinone',
            'menaquinol / menaquinone redox couple'),
    'MQ8': ('Menaquinone-8', 'quinone',
            'menaquinol / menaquinone redox couple'),
    # Radical-SAM cofactor — only radical-prone under catalysis; always
    # flag so the operator confirms the intended oxidation state.
    'SAM': ('S-adenosyl-L-methionine', 'radical-sam',
            "5′-deoxyadenosyl radical on C–S homolysis coupled to "
            "[4Fe-4S]^{1+}"),
}


def detect_known_redox_cofactor_residues(qm_residue_labels):
    """Return the subset of QM residues that are known redox cofactors.

    Arguments:
        qm_residue_labels: an iterable of residue 3-letter codes (as
        stored in prmtop ``RESIDUE_LABEL``) belonging to QM atoms.

    Returns a list of ``(code, (name, class, note))`` tuples, sorted by
    residue code for deterministic output.  Empty list means no known
    redox cofactor residue is present in the QM region (either truly
    absent, or absent from the curated table — callers must not
    confuse the two interpretations and should rely on the element
    detector and the geometric probe as complementary lines of
    evidence).
    """
    if not qm_residue_labels:
        return []
    seen = set()
    hits = []
    for raw in qm_residue_labels:
        key = str(raw or '').strip().upper()
        if not key or key in seen:
            continue
        seen.add(key)
        entry = KNOWN_REDOX_COFACTOR_RESIDUES.get(key)
        if entry is not None:
            hits.append((key, entry))
    hits.sort(key=lambda h: h[0])
    return hits


def parse_mdin_spin_metadata(mdin_meta):
    """Extract spin-relevant metadata from an AMBER .mdin parse result.

    Returns a dict with 'mdin_multiplicity' (int or None) and
    'mdin_qm_theory' (str or None).  AMBER's &qmmm namelist does not
    carry an explicit multiplicity field, but qm_theory may imply a
    method that the user intended to be open-shell.
    """
    meta = dict(mdin_meta or {})
    result = {
        'mdin_multiplicity': None,
        'mdin_qm_theory': None,
    }
    # AMBER &qmmm has 'spin' in some versions (SQM interface).
    for key in ('spin', 'multiplicity', 'qmmm_int_spin'):
        raw = meta.get(key)
        if raw is not None:
            try:
                val = int(raw)
                if val >= 1:
                    result['mdin_multiplicity'] = val
                    break
            except (ValueError, TypeError):
                pass
    qt = meta.get('qm_theory')
    if qt:
        result['mdin_qm_theory'] = str(qt).strip()
    return result


# ── π-stacking geometric risk detector (Tier B) ─────────────────────────────
#
# Purpose: raise a *risk flag* (never an automatic decision) when the QM
# region contains two or more aromatic rings in a face-to-face stacking
# geometry.  Such geometries host low-energy charge-transfer states that
# can manifest as a two-cycle SCF oscillation between π/π* configurations
# — the pathology observed in flavoenzyme QM/MM warmup when an aromatic
# substrate π-stacks against the flavin isoalloxazine.
#
# Scope and limitations (stated honestly, not apologetically):
#   • This is a *structural* probe on the prep-time geometry.  It cannot
#     predict orbital-energy alignment, polarisation, or dynamical CT.
#   • Ring aromaticity is approximated by an sp²-heuristic (all ring atoms
#     are C/N, each with degree 2 or 3 in the QM graph, and the ring is
#     planar within a tolerance).  This will misclassify dearomatised or
#     strongly puckered systems in either direction.  Consequence: the
#     output is a *warning*, not a routing input.
#   • Only 5- and 6-membered rings are searched (monocyclic aromatics
#     common in biomolecular cofactors: imidazole, phenyl, pyrrole,
#     pyridine, pyrimidine, and the three fused rings of FAD/FMN/NADH
#     isoalloxazine discovered independently).  Larger/smaller rings
#     are outside scope.
#   • Face-to-face criterion follows the π-π literature consensus:
#     centroid–centroid distance ≈ 3.3–4.5 Å and inter-plane angle
#     within ±30°.  Refs: Hunter & Sanders, J. Am. Chem. Soc. 112, 5525
#     (1990) — classical π-stacking geometry model;
#     Janiak, J. Chem. Soc. Dalton Trans. 2000, 3885 — survey of
#     stacking distances and angles in crystal structures.
#
# Output: zero or more risk-flag strings appended by detect_spin_risk_flags.
# Never promotes the decision class on its own; the user remains in
# control of the SCF profile choice.

# Elements that can plausibly participate in biomolecular aromatic rings.
# (Oxygen in furan/oxazole-like rings is rare in proteins but allowed.)
_AROMATIC_CAPABLE_ELEMENTS = {'C', 'N', 'O'}
# Planarity tolerance: maximum allowed RMS out-of-plane deviation of
# ring atoms from the least-squares ring plane, in Å.  Empirical: benzene
# in MD snapshots stays well under 0.05 Å; puckered systems (cyclohexane
# chair) easily exceed 0.4 Å.  0.15 Å is a conservative boundary.
_RING_PLANARITY_TOL_A = 0.15
# Centroid–centroid window for face-to-face stacking (Å).
_PI_STACK_DIST_MIN_A = 3.2
_PI_STACK_DIST_MAX_A = 4.5
# Inter-plane angle window (degrees).  ≤30° captures face-to-face; a
# dedicated branch near 90° would capture T-shaped edge-to-face, but T
# stacking is far less CT-prone and is intentionally omitted to keep
# false-positive rate low.
_PI_STACK_ANGLE_MAX_DEG = 30.0
# Face-to-face criterion: the projection of the centroid–centroid
# displacement onto the ring plane normal must be at least this value,
# in Å, so that two aromatic rings lying edge-to-edge in the same plane
# (parallel normals but zero vertical separation) are NOT reported as
# stacked.  2.5 Å is safely below typical stacking distances (~3.3–3.8 Å)
# yet above the in-plane slip of parallel-displaced stacks.
# Ref: Janiak (2000) survey — the "ideal" face-to-face offset along the
# normal is ≈ 3.3–3.5 Å; parallel-displaced stacks retain ≥ 3 Å along
# the normal axis even when in-plane slip approaches the ring radius.
_PI_STACK_MIN_NORMAL_OFFSET_A = 2.5
# Safety cap on graph search to keep the helper O(N) in practice even on
# pathological inputs (highly cross-linked organic cofactors).
_PI_STACK_MAX_RINGS_CONSIDERED = 64


def _vec_sub(a, b):
    """Return a - b for 3-vectors."""
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _vec_cross(a, b):
    """Return a × b for 3-vectors."""
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _vec_norm(v):
    """Euclidean length of a 3-vector."""
    import math as _m
    return _m.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _find_small_rings(adjacency, max_ring_size=6):
    """Find all simple rings of size ≤ max_ring_size in an undirected graph.

    adjacency: dict[int → set[int]] — 0-based node adjacency.
    Returns: list of tuples (node_0, node_1, …, node_k) sorted canonically
    so each ring appears exactly once.

    Algorithm: bounded DFS from each node, only accepting paths that
    return to the starting node with length in [3, max_ring_size].  Each
    ring is canonicalised (rotated to start at its minimum-index node,
    oriented so its second node is the smaller of its two neighbours)
    before deduplication, so a ring cycle found from any of its vertices
    maps to a single key.  This is O(N · d^max_size); for biomolecular
    QM regions (N ≲ 200, d ≲ 4, max_size = 6) the constant is tiny.
    """
    rings = set()
    nodes = sorted(adjacency.keys())
    for start in nodes:
        # Stack entries: (current_node, path_tuple).
        stack = [(start, (start,))]
        while stack:
            cur, path = stack.pop()
            if len(path) > max_ring_size:
                continue
            for nb in adjacency.get(cur, ()):
                if nb == start and len(path) >= 3:
                    # Closed ring of length len(path).
                    ring = tuple(path)
                    # Canonicalise: rotate to smallest, orient forward.
                    k = ring.index(min(ring))
                    rot = ring[k:] + ring[:k]
                    # Two orientations; pick lexicographically smaller.
                    rev = (rot[0],) + tuple(reversed(rot[1:]))
                    canon = rot if rot <= rev else rev
                    rings.add(canon)
                    continue
                # Only extend through higher-indexed nodes to keep the
                # canonical form discoverable without exploding the
                # search tree — start is always min(ring) after canon.
                if nb <= start:
                    continue
                if nb in path:
                    continue
                stack.append((nb, path + (nb,)))
    return [list(r) for r in sorted(rings)]


def _ring_is_aromatic_like(ring_indices, atoms, adjacency):
    """Heuristic aromaticity test for one ring.

    ring_indices: sequence of 0-based atom indices forming the ring.
    atoms: list of (element_symbol, (x, y, z)) in the same indexing.
    adjacency: dict[int → set[int]] giving each atom's QM-graph degree.

    Returns True when every ring atom is an sp²-capable element (C/N/O)
    and has graph degree 2 or 3 (consistent with three-connected planar
    sp² centres, or two-connected bridgehead-adjacent centres).  This
    does NOT test Hückel's 4n+2 rule — we cannot infer π-electron count
    without bond-order information — so the test is deliberately
    permissive and the output is only used to raise a warning.
    """
    for i in ring_indices:
        if i >= len(atoms):
            return False
        elem = str(atoms[i][0]).upper()
        if elem not in _AROMATIC_CAPABLE_ELEMENTS:
            return False
        deg = len(adjacency.get(i, ()))
        if deg < 2 or deg > 3:
            return False
    return True


def _ring_centroid_and_normal(ring_indices, atoms):
    """Return (centroid, plane_normal, planarity_rms) for a ring.

    The plane normal is computed from the first three-atom triangle of the
    ring (sufficient for 5- and 6-membered rings assumed approximately
    planar); the planarity RMS is the root-mean-square signed distance of
    all ring atoms from the plane.  A large RMS means the ring is puckered
    and should be disqualified by the caller.
    """
    coords = [atoms[i][1] for i in ring_indices]
    n = len(coords)
    cx = sum(c[0] for c in coords) / n
    cy = sum(c[1] for c in coords) / n
    cz = sum(c[2] for c in coords) / n
    centroid = (cx, cy, cz)

    v01 = _vec_sub(coords[1], coords[0])
    v02 = _vec_sub(coords[2], coords[0])
    normal = _vec_cross(v01, v02)
    mag = _vec_norm(normal)
    if mag == 0.0:
        # Degenerate (colinear first three atoms); reject upstream.
        return centroid, (0.0, 0.0, 0.0), float('inf')
    normal = (normal[0] / mag, normal[1] / mag, normal[2] / mag)

    # Signed distance of each atom to the plane through coords[0] with
    # this normal.  RMS of those distances quantifies planarity.
    sq = 0.0
    for c in coords:
        d = (
            normal[0] * (c[0] - coords[0][0])
            + normal[1] * (c[1] - coords[0][1])
            + normal[2] * (c[2] - coords[0][2])
        )
        sq += d * d
    import math as _m
    rms = _m.sqrt(sq / n)
    return centroid, normal, rms


def detect_pi_stacking_risk(qm_geometry):
    """Geometric probe for face-to-face π-stacking in the QM region.

    qm_geometry is a dict with:
      'atoms': list of (element_symbol_str, (x, y, z)) — 0-based, parallel.
      'bonds': iterable of frozenset({i, j}) with 0-based indices into 'atoms'.

    Returns a list of zero or more risk-flag strings.  An empty list
    means no stacked aromatic pair was identified; it does NOT prove
    absence of charge-transfer risk (a later conformation under MD may
    adopt a stacking geometry not present in the prep-time snapshot).

    This function is deliberately isolated: it never mutates its inputs,
    never calls SCF-routing logic, and degrades to an empty list if the
    input is malformed.  Failures here must never kill a pipeline run —
    the upstream router still produces a defensible default.

    Refs:
      Hunter & Sanders, J. Am. Chem. Soc. 112, 5525 (1990) — π-stacking
        geometrical criteria (centroid distance and inter-plane angle).
      Janiak, J. Chem. Soc. Dalton Trans. 2000, 3885 — survey of aromatic
        stacking geometries in the Cambridge Structural Database.
    """
    flags = []
    if not isinstance(qm_geometry, dict):
        return flags
    atoms = list(qm_geometry.get('atoms') or [])
    bonds_iter = qm_geometry.get('bonds') or ()
    if not atoms:
        return flags

    # Build a 0-based adjacency map restricted to QM atoms.  Guard
    # against malformed bond records (wrong types, out-of-range indices).
    adjacency = {i: set() for i in range(len(atoms))}
    for bond in bonds_iter:
        try:
            pair = tuple(bond)
        except TypeError:
            continue
        if len(pair) != 2:
            continue
        a, b = int(pair[0]), int(pair[1])
        if a == b:
            continue
        if 0 <= a < len(atoms) and 0 <= b < len(atoms):
            adjacency[a].add(b)
            adjacency[b].add(a)

    # Enumerate and filter rings.
    try:
        rings = _find_small_rings(adjacency, max_ring_size=6)
    except Exception:
        # Pathological input; abandon detection rather than crash.
        return flags
    if len(rings) > _PI_STACK_MAX_RINGS_CONSIDERED:
        # If the search explodes, the QM region is not a typical
        # biomolecular active site; skip the probe quietly.
        return flags

    # Compute centroid/normal/planarity once per aromatic-like ring.
    aromatic_rings = []
    for ring in rings:
        if len(ring) not in (5, 6):
            continue
        if not _ring_is_aromatic_like(ring, atoms, adjacency):
            continue
        centroid, normal, rms = _ring_centroid_and_normal(ring, atoms)
        if rms > _RING_PLANARITY_TOL_A:
            continue
        aromatic_rings.append({
            'indices': tuple(ring),
            'centroid': centroid,
            'normal': normal,
        })

    if len(aromatic_rings) < 2:
        return flags

    # Pairwise geometric test.  Symmetric O(M²) on M aromatic rings —
    # negligible for biomolecular QM regions (M ≲ 10).
    import math as _m
    stacked_pairs = []
    for i in range(len(aromatic_rings)):
        for j in range(i + 1, len(aromatic_rings)):
            ra, rb = aromatic_rings[i], aromatic_rings[j]
            d_vec = _vec_sub(rb['centroid'], ra['centroid'])
            d_mag = _vec_norm(d_vec)
            if d_mag < _PI_STACK_DIST_MIN_A or d_mag > _PI_STACK_DIST_MAX_A:
                continue
            # Inter-plane angle via |n_a · n_b|.  The absolute value
            # folds the two equivalent orientations of a plane normal.
            dot = (
                ra['normal'][0] * rb['normal'][0]
                + ra['normal'][1] * rb['normal'][1]
                + ra['normal'][2] * rb['normal'][2]
            )
            dot = max(-1.0, min(1.0, abs(dot)))
            angle_deg = _m.degrees(_m.acos(dot))
            # Face-to-face: both normals nearly parallel (angle ≤ tol)
            # OR nearly antiparallel (angle ≥ 180 - tol).  After |·|
            # folding, only the small-angle branch remains.
            if angle_deg > _PI_STACK_ANGLE_MAX_DEG:
                continue
            # Require genuine face-to-face offset: project the centroid
            # displacement onto each ring's normal and demand that the
            # (absolute) projection is above a threshold.  Two coplanar
            # aromatics in the same plane fail this test despite having
            # parallel normals, eliminating the in-plane false positive.
            proj_a = abs(
                d_vec[0] * ra['normal'][0]
                + d_vec[1] * ra['normal'][1]
                + d_vec[2] * ra['normal'][2]
            )
            proj_b = abs(
                d_vec[0] * rb['normal'][0]
                + d_vec[1] * rb['normal'][1]
                + d_vec[2] * rb['normal'][2]
            )
            normal_offset = 0.5 * (proj_a + proj_b)
            if normal_offset < _PI_STACK_MIN_NORMAL_OFFSET_A:
                continue
            stacked_pairs.append((ra, rb, d_mag, angle_deg))

    if not stacked_pairs:
        return flags

    # Report at most a handful of pairs to keep the audit line readable.
    # The flag text deliberately says "possible" and "near-degenerate":
    # this is a structural warning, not a diagnosis.
    summary_bits = []
    for ra, rb, dist_a, ang in stacked_pairs[:3]:
        summary_bits.append(
            f"{len(ra['indices'])}-ring ↔ {len(rb['indices'])}-ring "
            f"d={dist_a:.2f} Å, θ={ang:.1f}°"
        )
    flags.append(
        "possible π-π stacking between aromatic rings in QM region — "
        "near-degenerate charge-transfer states can drive SCF oscillation "
        "(" + "; ".join(summary_bits)
        + (f"; +{len(stacked_pairs) - 3} more" if len(stacked_pairs) > 3 else "")
        + ")"
    )
    return flags


def detect_spin_risk_flags(qm_elements, electron_count, unresolved_elements,
                           qm_geometry=None, qm_residue_labels=None):
    """Detect conditions that make automated spin-state assignment unreliable.

    Returns a list of short human-readable risk-flag strings.  Any non-empty
    list means the decision class must be AMBIGUOUS_REQUIRES_USER unless the
    user supplies an explicit multiplicity.  These heuristics may only
    *increase* risk; they never silently resolve it.

    The optional *qm_geometry* enables the π-stacking geometric probe
    (Tier B).  The optional *qm_residue_labels* enables the residue-name
    redox-cofactor lookup (B.1.a) — critical for flavin/quinone
    cofactors whose elements (C/H/N/O/P) are invisible to the
    element-only hint set.  When either is None, the corresponding
    probe is skipped and prior callers see unchanged behaviour.
    """
    flags = []
    elems = {str(e).strip().upper() for e in (qm_elements or {}) if str(e).strip()}

    if elems & TRANSITION_METALS:
        flags.append(
            f"transition metal(s) in QM region: "
            f"{', '.join(sorted(elems & TRANSITION_METALS))}"
        )
    if elems & _REDOX_COFACTOR_ELEMENT_HINTS:
        flags.append(
            f"redox-active cofactor element(s): "
            f"{', '.join(sorted(elems & _REDOX_COFACTOR_ELEMENT_HINTS))}"
        )
    if elems & _OXYGEN_ACTIVATION_ELEMENTS and 'O' in elems:
        flags.append("possible O₂ / oxygen-activation motif (metal + O in QM)")
    # Residue-name redox-cofactor lookup (B.1.a).  The element set can
    # miss organic radicals (flavin semiquinone, ubiquinone/semiquinone
    # couple, etc.), so we also consult the curated residue table.
    if qm_residue_labels:
        cofactor_hits = detect_known_redox_cofactor_residues(qm_residue_labels)
        if cofactor_hits:
            flags.append(
                "known redox-active cofactor residue(s) in QM: "
                + ", ".join(
                    f"{code} [{cls}: {note}]"
                    for code, (_name, cls, note) in cofactor_hits
                )
            )
    if unresolved_elements:
        flags.append(
            f"unresolved element(s) — electron count incomplete: "
            f"{', '.join(sorted(str(e) for e in unresolved_elements))}"
        )
    if electron_count is None:
        flags.append("electron count unknown — parity constraint unavailable")

    # Tier-B geometric probe.  Never raises: a failure inside the probe
    # is swallowed (returns an empty list) so the main routing decision
    # never depends on the probe succeeding.
    if qm_geometry is not None:
        try:
            flags.extend(detect_pi_stacking_risk(qm_geometry))
        except Exception:
            pass
    return flags


# ── B.1.b: Spin-risk detector taxonomy ────────────────────────────────────
#
# detect_spin_risk_flags returns free-form human strings; the AMBIGUOUS
# prompt previously echoed each verbatim with a generic "Spin risk:" prefix
# but never named the *detector category* that fired.  Knowing the
# taxonomy helps the user reason about which physics assumption is at risk
# (TM presence vs redox cofactor vs O₂-activation motif vs incomplete
# electron count vs π-stacking geometry) and decide whether to override
# the multiplicity, recover the missing element data, or rerun with
# explicit --multiplicity.  This classifier is purely informational; the
# detect_spin_risk_flags contract (returns a list of strings) is kept
# unchanged so existing callers (audit writer, CLI summariser) are
# unaffected.
SPIN_RISK_DETECTOR_LABELS = {
    'transition_metal_presence': (
        'Transition-metal element present in QM region '
        '(d-manifold near-degeneracy → SCF can converge to wrong state).'
    ),
    'redox_cofactor_element': (
        'Redox-active cofactor element hint detected '
        '(e.g. Fe/Cu/Mn/Mo — biological redox sites).'
    ),
    'known_redox_cofactor_residue': (
        'Known redox-active cofactor residue detected by name '
        '(FAD/FMN, heme, [Fe-S], quinone, chlorophyll, radical-SAM). '
        'The element-only detector would miss purely organic radicals '
        'such as flavin semiquinone.'
    ),
    'oxygen_activation_motif': (
        'Metal+O motif suggesting O₂ activation chemistry '
        '(Fenton/Compound-I/peroxo intermediates have non-trivial spin).'
    ),
    'unresolved_elements': (
        'Element identity could not be resolved for some QM atoms — '
        'electron count is incomplete and parity check unreliable.'
    ),
    'unknown_electron_count': (
        'Electron count could not be derived — parity constraint '
        'unavailable, multiplicity check disabled.'
    ),
    'pi_stacking_geometry': (
        'Aromatic π-stacking geometry detected '
        '(potential charge-transfer / inter-ring SOMO mixing — '
        'Hunter & Sanders, JACS 112, 5525 (1990)).'
    ),
}


def classify_spin_risk_detectors(qm_elements, electron_count, unresolved_elements,
                                 qm_geometry=None, qm_residue_labels=None):
    """Return the sorted list of detector keys that would fire.

    Mirrors the conditions inside ``detect_spin_risk_flags`` so the
    AMBIGUOUS prompt can enumerate detector *categories* (taxonomy)
    independently of the per-instance flag messages.  Returning a list
    rather than a set keeps the order deterministic for display.
    """
    elems = {str(e).strip().upper() for e in (qm_elements or {}) if str(e).strip()}
    fired = []
    if elems & TRANSITION_METALS:
        fired.append('transition_metal_presence')
    if elems & _REDOX_COFACTOR_ELEMENT_HINTS:
        fired.append('redox_cofactor_element')
    if qm_residue_labels and detect_known_redox_cofactor_residues(qm_residue_labels):
        fired.append('known_redox_cofactor_residue')
    if elems & _OXYGEN_ACTIVATION_ELEMENTS and 'O' in elems:
        fired.append('oxygen_activation_motif')
    if unresolved_elements:
        fired.append('unresolved_elements')
    if electron_count is None:
        fired.append('unknown_electron_count')
    if qm_geometry is not None:
        try:
            if detect_pi_stacking_risk(qm_geometry):
                fired.append('pi_stacking_geometry')
        except Exception:
            pass
    return fired


def validate_multiplicity_parity(multiplicity, electron_count):
    """Check whether multiplicity is parity-consistent with electron count.

    Returns (is_consistent: bool | None, explanation: str).
    None means the check could not be performed (unknown electron count).

    The parity rule: an even electron count requires odd multiplicity
    (1, 3, 5, …) and an odd electron count requires even multiplicity
    (2, 4, 6, …).  This is necessary physics, not a heuristic.
    """
    if electron_count is None:
        return None, "electron count unknown; parity check not possible"
    mult = int(multiplicity)
    n_unpaired = mult - 1
    # n_unpaired must have the same parity as electron_count.
    consistent = (electron_count % 2) == (n_unpaired % 2)
    if consistent:
        return True, (
            f"multiplicity {mult} is parity-consistent with "
            f"{electron_count} electrons"
        )
    return False, (
        f"multiplicity {mult} is parity-INCONSISTENT with "
        f"{electron_count} electrons "
        f"({'even' if electron_count % 2 == 0 else 'odd'} e⁻ → "
        f"{'odd' if electron_count % 2 == 0 else 'even'} multiplicity required)"
    )


def recommend_qm_spin_state(
    qm_elements,
    qm_charge,
    link_bonds=None,
    user_multiplicity=None,
    mdin_meta=None,
    qm_geometry=None,
    qm_residue_labels=None,
):
    """Conservative spin-state recommender for biomolecular QM/MM.

    Returns a structured decision dict.  Source precedence (strict):
      1. Explicit user multiplicity (--multiplicity) — authoritative.
      2. Parsed AMBER .mdin spin metadata — authoritative.
      3. Parity-based inference — low-risk fallback for main-group only.

    The optional *qm_geometry* unlocks the Tier-B π-stacking geometric
    probe inside detect_spin_risk_flags.  The optional
    *qm_residue_labels* unlocks the B.1.a residue-name redox-cofactor
    lookup.  Both are strictly additive: when omitted, the recommender
    preserves prior behaviour.  Neither probe alters the multiplicity
    decision path; they only populate the risk-flag list.

    The recommender never auto-guesses multiplicity above 2 from topology
    alone, never infers oxidation state from element identity, and never
    silently assigns a spin state when risk flags are present.
    """
    electron_count, e_meta = estimate_qm_electrons_for_spin(
        qm_elements, qm_charge, link_bonds,
    )
    unresolved = list(e_meta.get('unresolved_elements') or [])
    risk_flags = detect_spin_risk_flags(
        qm_elements, electron_count, unresolved,
        qm_geometry=qm_geometry,
        qm_residue_labels=qm_residue_labels,
    )
    mdin_spin = parse_mdin_spin_metadata(mdin_meta)
    has_risk = len(risk_flags) > 0

    # Electron parity, if known.
    if electron_count is not None:
        e_parity = 'even' if (electron_count % 2) == 0 else 'odd'
    else:
        e_parity = 'unknown'

    # ── Source 1: explicit user multiplicity (authoritative) ──────────
    if user_multiplicity is not None:
        mult = int(user_multiplicity)
        parity_ok, parity_msg = validate_multiplicity_parity(mult, electron_count)
        return _spin_decision(
            multiplicity=mult,
            electron_count=electron_count,
            electron_parity=e_parity,
            parity_consistent=parity_ok,
            risk_flags=risk_flags,
            decision_class='AUTHORITATIVE',
            decision_source='user_explicit',
            confidence='high',
            reason_lines=[
                f"User-supplied multiplicity {mult} is authoritative.",
                parity_msg,
            ] + ([f"Risk flag: {f}" for f in risk_flags] if risk_flags else []),
        )

    # ── Source 2: parsed AMBER .mdin metadata (authoritative) ─────────
    mdin_mult = mdin_spin.get('mdin_multiplicity')
    if mdin_mult is not None:
        parity_ok, parity_msg = validate_multiplicity_parity(mdin_mult, electron_count)
        return _spin_decision(
            multiplicity=mdin_mult,
            electron_count=electron_count,
            electron_parity=e_parity,
            parity_consistent=parity_ok,
            risk_flags=risk_flags,
            decision_class='AUTHORITATIVE',
            decision_source='mdin_metadata',
            confidence='high',
            reason_lines=[
                f"AMBER .mdin spin metadata specifies multiplicity {mdin_mult}.",
                parity_msg,
            ] + ([f"Risk flag: {f}" for f in risk_flags] if risk_flags else []),
        )

    # ── Source 3: parity-based inference (only when low-risk) ─────────
    if has_risk:
        # Cannot safely infer — force explicit handling.
        tentative = None
        if electron_count is not None:
            # Offer a parity-compatible starting point, but do NOT auto-accept.
            tentative = 2 if (electron_count % 2) != 0 else 1
        return _spin_decision(
            multiplicity=tentative,
            electron_count=electron_count,
            electron_parity=e_parity,
            parity_consistent=None if tentative is None else True,
            risk_flags=risk_flags,
            decision_class='AMBIGUOUS_REQUIRES_USER',
            decision_source='none_risk_flags_present',
            confidence='low',
            reason_lines=[
                "Spin state cannot be inferred automatically due to risk flags:",
            ] + [f"  • {f}" for f in risk_flags] + [
                "Provide --multiplicity explicitly.",
            ] + ([
                f"Tentative parity-safe starting point: multiplicity {tentative} "
                "(NOT auto-accepted)."
            ] if tentative is not None else []),
        )

    # Low-risk main-group path: all elements resolved, no metals / radicals.
    if electron_count is None:
        return _spin_decision(
            multiplicity=None,
            electron_count=None,
            electron_parity='unknown',
            parity_consistent=None,
            risk_flags=risk_flags,
            decision_class='AMBIGUOUS_REQUIRES_USER',
            decision_source='electron_count_unknown',
            confidence='low',
            reason_lines=[
                "Electron count is unknown; cannot infer multiplicity.",
                "Provide --multiplicity explicitly.",
            ],
        )

    # Even electrons → singlet (mult 1, no UKS).
    # Odd electrons  → doublet (mult 2, UKS).
    # Never auto-guess above 2; higher multiplicities require explicit intent.
    if (electron_count % 2) == 0:
        mult = 1
        reason = "Even electron count → singlet default for main-group biomolecular QM region."
    else:
        mult = 2
        reason = "Odd electron count → doublet default (lowest parity-allowed multiplicity)."

    return _spin_decision(
        multiplicity=mult,
        electron_count=electron_count,
        electron_parity=e_parity,
        parity_consistent=True,
        risk_flags=[],
        decision_class='LOW_RISK_INFERRED',
        decision_source='parity_main_group',
        confidence='medium',
        reason_lines=[
            reason,
            f"Electron count {electron_count} ({e_parity}) fully resolved, "
            "no transition metals or redox cofactors in QM region.",
            "Electron parity is a necessary constraint, not proof of the "
            "chemically correct spin state.",
        ],
    )


def _spin_decision(
    multiplicity, electron_count, electron_parity, parity_consistent,
    risk_flags, decision_class, decision_source, confidence, reason_lines,
):
    """Construct the structured spin-state decision object."""
    open_shell = (multiplicity is not None and int(multiplicity) != 1)
    emit_uks = open_shell
    return {
        'multiplicity': multiplicity,
        'open_shell': open_shell,
        'emit_uks': emit_uks,
        'confidence': confidence,
        'decision_class': decision_class,
        'electron_count': electron_count,
        'electron_parity': electron_parity,
        'parity_consistent': parity_consistent,
        'risk_flags': list(risk_flags or []),
        'decision_source': decision_source,
        'reason_lines': list(reason_lines or []),
    }


# ─── Unified Run Provenance Manifest (F.1.a) ─────────────────────────────────
#
# Every non-default decision the pipeline makes — auto-recommendation,
# version-driven substitution, accepted/declined SCF promotion, defaulted
# boundary policy, validator outcome, etc. — is recorded as one entry in a
# single ``RunProvenance`` accumulator that is created in main() and
# persisted to ``run_provenance.txt`` alongside the emitted CP2K input.
#
# The shape is the existing ``substitutions_log`` schema generalised:
#   { 'kind':       short topical key (e.g. 'admm_aux_basis', 'scf_promotion')
#     'severity':   'info' | 'recommendation' | 'correction' | 'substitution'
#     'source':     'auto' | 'recommendation' | 'cli' | 'wizard' | 'audit'
#     'from':       prior value (str/None)
#     'to':         resulting value (str/None)
#     'accepted':   True/False/None  (None when the entry is informational)
#     'reason':     short scientific rationale
#     'citation':   doc/paper reference
#     'context':    optional dict of extra facts
#   }
#
# Why a single accumulator: reproducing a previous run currently requires
# re-walking the wizard interactively because each subsystem owns its own
# audit fragment (admm_substitutions_log, scf_routing_audit, boundary_
# charges audit).  The unified manifest gives the user one artifact whose
# presence/absence answers "what got auto-decided here, and why?".  No
# new file format, no JSON/YAML — flat text, human-readable, single file.

class RunProvenance:
    """In-memory accumulator for non-default decisions made during a run.

    The class is intentionally minimal: a list of dicts plus convenience
    helpers for appending and rendering.  Keeping the API small avoids
    accidentally turning the manifest into a parallel configuration store
    that drifts from the actual emitted input.
    """

    __slots__ = ('_entries',)

    def __init__(self):
        self._entries = []

    def record(self, kind, severity='info', source='auto',
               from_value=None, to_value=None, accepted=None,
               reason='', citation='', context=None):
        """Append one structured provenance entry."""
        self._entries.append({
            'kind': str(kind),
            'severity': str(severity),
            'source': str(source),
            'from': None if from_value is None else str(from_value),
            'to': None if to_value is None else str(to_value),
            'accepted': accepted,
            'reason': str(reason or ''),
            'citation': str(citation or ''),
            'context': dict(context or {}),
        })

    def extend_from_substitutions(self, substitutions_log):
        """Mirror existing substitutions_log entries into the manifest."""
        for sub in (substitutions_log or ()):
            self._entries.append({
                'kind': sub.get('kind', 'substitution'),
                'severity': 'substitution',
                'source': 'auto',
                'from': sub.get('from') or sub.get('requested'),
                'to': sub.get('to') or sub.get('substituted'),
                'accepted': True,
                'reason': sub.get('reason', ''),
                'citation': sub.get('citation', ''),
                'context': {k: v for k, v in sub.items()
                            if k not in {'kind', 'from', 'to', 'requested',
                                         'substituted', 'reason', 'citation'}},
            })

    def __len__(self):
        return len(self._entries)

    def entries(self):
        """Return a shallow copy of the recorded entries."""
        return list(self._entries)

    def format_block(self, prefix=''):
        """Render the manifest as a human-readable text block.

        ``prefix`` lets the caller turn each line into a CP2K comment by
        passing ``'! '`` (CP2K's comment marker per the input reference).
        """
        if not self._entries:
            return f"{prefix}(no non-default decisions recorded)\n"
        lines = []
        for i, e in enumerate(self._entries, start=1):
            head = (
                f"#{i:03d} [{e['severity']}/{e['source']}] {e['kind']}"
            )
            if e.get('from') is not None or e.get('to') is not None:
                head += f": {e.get('from')} -> {e.get('to')}"
            if e.get('accepted') is True:
                head += "  (accepted)"
            elif e.get('accepted') is False:
                head += "  (declined)"
            lines.append(prefix + head)
            if e.get('reason'):
                lines.append(prefix + f"    reason: {e['reason']}")
            if e.get('citation'):
                lines.append(prefix + f"    ref:    {e['citation']}")
            ctx = e.get('context') or {}
            for k, v in ctx.items():
                lines.append(prefix + f"    {k}: {v}")
        return "\n".join(lines) + "\n"

    def write_file(self, out_path, header_lines=()):
        """Persist the manifest to a sibling text file alongside the input."""
        with open(out_path, 'w', encoding='utf-8') as fh:
            fh.write(
                "# run_provenance.txt — unified manifest of non-default decisions\n"
                "# generated by charmmgui2cp2k.py (RunProvenance).  Each entry\n"
                "# records one auto-recommendation, version substitution, SCF\n"
                "# promotion, validator outcome, or interactive override that\n"
                "# shaped this run.  See the per-subsystem audit files\n"
                "# (electronic_state.dat, boundary_charges.json,\n"
                "# cp2k_compat_report.txt) for the full per-domain detail.\n\n"
            )
            for hl in (header_lines or ()):
                fh.write(f"# {hl}\n")
            if header_lines:
                fh.write("\n")
            fh.write(self.format_block(prefix=''))


def write_electronic_state_dat(out_path, qm_meta, qm_charge, multiplicity,
                               spin_decision=None, scf_routing=None):
    """
    Write a transparent electron-accounting report for CP2K CHARGE/MULTIPLICITY checks.

    The optional *scf_routing* dict records the resolved SCF-profile
    routing rationale so the audit file tells the full story of how the
    calculation was parameterised.  Expected keys (all optional):
      'profile'            — final SCF_PROFILES key name (str).
      'engine'             — 'OT' or 'DIAG' as declared by the profile.
      'has_tm'             — bool; transition metal present in QM region.
      'expects_smearing'   — bool; Fermi-Dirac smearing will be emitted.
      'level_shift'        — float in Hartree or None; LEVEL_SHIFT value.
      'reason'             — short string explaining routing choice.
    Missing keys are simply omitted from the audit file.
    """
    meta = dict(qm_meta or {})
    qm_valence = int(meta.get('qm_valence_electrons', 0))
    link_added = int(meta.get('link_electrons_added', 0))
    charge_sub = int(qm_charge)
    final_count = meta.get('final_electron_count')
    unresolved = sorted(str(x) for x in (meta.get('unresolved_elements') or []))

    if final_count is None:
        final_parity = "unknown"
        required_mult_parity = "unknown"
        parity_consistent = None
    else:
        final_count = int(final_count)
        final_parity = "even" if (final_count % 2) == 0 else "odd"
        required_mult_parity = "odd" if final_parity == "even" else "even"
        parity_consistent = ((final_count % 2) == ((int(multiplicity) - 1) % 2))

    provided_mult_parity = "odd" if (int(multiplicity) % 2) == 1 else "even"
    consistency_str = "UNKNOWN" if parity_consistent is None else ("YES" if parity_consistent else "NO")

    lines = [
        "# electronic_state.dat",
        "# Transparent QM electron accounting for CP2K &DFT CHARGE/MULTIPLICITY",
        f"SUM_QM_GTH_VALENCE_ELECTRONS: {qm_valence}",
        f"LINK_H_ELECTRONS_ADDED: {link_added}",
        f"NET_CHARGE_SUBTRACTED: {charge_sub}",
        f"FINAL_ELECTRON_COUNT: {final_count if final_count is not None else 'UNKNOWN'}",
        f"FINAL_ELECTRON_PARITY: {final_parity.upper()}",
        f"CP2K_DFT_CHARGE: {int(qm_charge)}",
        f"CP2K_DFT_MULTIPLICITY: {int(multiplicity)}",
        f"REQUIRED_MULTIPLICITY_PARITY: {required_mult_parity.upper()}",
        f"PROVIDED_MULTIPLICITY_PARITY: {provided_mult_parity.upper()}",
        f"PARITY_CONSISTENT: {consistency_str}",
        f"LINK_H_COUNT: {int(meta.get('link_count', 0))}",
        f"LINK_H_VALENCE_ELECTRONS: {int(meta.get('link_h_valence', 1))}",
    ]
    if unresolved:
        lines.append(f"UNRESOLVED_QM_ELEMENTS: {', '.join(unresolved)}")
    if meta.get('source_counts'):
        lines.append(
            "VALENCE_SOURCE_COUNTS: "
            f"GTH={int(meta['source_counts'].get('gth', 0))}, "
            f"Z_FALLBACK={int(meta['source_counts'].get('z-fallback', 0))}"
        )

    # Spin-decision report section.
    sd = dict(spin_decision or {})
    if sd:
        lines.append("")
        lines.append("# ── Spin-State Decision Report ──")
        lines.append(f"DECISION_CLASS: {sd.get('decision_class', 'UNKNOWN')}")
        lines.append(f"DECISION_SOURCE: {sd.get('decision_source', 'UNKNOWN')}")
        lines.append(f"CONFIDENCE: {sd.get('confidence', 'UNKNOWN')}")
        lines.append(f"EMIT_UKS: {'YES' if sd.get('emit_uks') else 'NO'}")
        risk = sd.get('risk_flags') or []
        lines.append(f"RISK_FLAG_COUNT: {len(risk)}")
        for i, rf in enumerate(risk):
            lines.append(f"RISK_FLAG_{i+1}: {rf}")
        for i, rl in enumerate(sd.get('reason_lines') or []):
            lines.append(f"REASON_{i+1}: {rl}")

    # SCF-routing report section.  Documents the final profile chosen
    # after any post-hoc promotion (e.g. OT→ORGANIC_RADICAL_DIAG), plus
    # the declarative metadata that determines whether Fermi smearing
    # and/or LEVEL_SHIFT will appear in the emitted CP2K input.  This
    # makes the audit file self-sufficient for reproducing the choice.
    sr = dict(scf_routing or {})
    if sr:
        lines.append("")
        lines.append("# ── SCF Routing Report ──")
        if 'profile' in sr:
            lines.append(f"SCF_PROFILE: {sr.get('profile')}")
        if 'engine' in sr:
            lines.append(f"SCF_ENGINE: {sr.get('engine')}")
        if 'has_tm' in sr:
            lines.append(
                f"QM_HAS_TRANSITION_METAL: {'YES' if sr.get('has_tm') else 'NO'}"
            )
        if 'expects_smearing' in sr:
            lines.append(
                "SCF_EXPECTS_FERMI_SMEAR: "
                f"{'YES' if sr.get('expects_smearing') else 'NO'}"
            )
        ls = sr.get('level_shift')
        if ls is not None:
            # Hartree units; CP2K native.
            lines.append(f"SCF_LEVEL_SHIFT_HARTREE: {float(ls):.3f}")
        else:
            lines.append("SCF_LEVEL_SHIFT_HARTREE: NONE")
        if sr.get('reason'):
            lines.append(f"SCF_PROFILE_REASON: {sr.get('reason')}")

    lines.append("")

    with open(out_path, 'w') as f:
        f.write("\n".join(lines))

    return {
        'final_electron_count': final_count,
        'final_electron_parity': final_parity,
        'parity_consistent': parity_consistent,
    }


def ensure_link_cap_kind(qm_elements, link_bonds, cap_element='H'):
    """
    Ensure the QM kind dictionary contains the link-cap element kind.
    Returns True when a new kind entry was added.
    """
    if not link_bonds:
        return False
    cap = str(cap_element).strip().upper()
    if any(str(k).strip().upper() == cap for k in (qm_elements or {}).keys()):
        return False
    qm_elements[cap] = []
    return True

def _infer_admm_aux_basis_from_qm_kinds(qm_kinds_lines):
    """Infer AUX_FIT basis label from generated QM KIND lines when present."""
    for line in qm_kinds_lines or []:
        match = re.match(r'^\s*BASIS_SET\s+AUX_FIT\s+(\S+)\s*$', str(line))
        if match:
            return normalize_admm_aux_basis(match.group(1))
    return None


def generate_qm_kinds(qm_elements, basis_set="DZVP-MOLOPT-GTH", aux_basis=None,
                      potential_prefix="GTH-PBE", use_admm=True):
    """
    Generate QM &KIND blocks with BASIS_SET, POTENTIAL, and ELEMENT.
    These MUST appear before MM kinds in the CP2K input.
    """
    resolved_aux_basis = resolve_admm_aux_basis(qm_elements, aux_basis, use_admm=use_admm, basis_set=basis_set)
    lines = []
    unresolved = []
    for elem in sorted(qm_elements.keys()):
        q_val = GTH_CHARGE_MAP.get(elem.upper(), 'qX')
        if q_val == 'qX':
            unresolved.append(elem)

        lines.append(f"  &KIND {elem}\n")
        lines.append(f"    ELEMENT {elem}\n")
        lines.append(f"    BASIS_SET {basis_set}\n")
        if use_admm and resolved_aux_basis:
            lines.append(f"    BASIS_SET AUX_FIT {resolved_aux_basis}\n")
        lines.append(f"    POTENTIAL {potential_prefix}-{q_val}\n")
        lines.append(f"  &END KIND\n")

    # ── Unresolved GTH pseudopotential guard ─────────────────────────
    # Each QM element requires a Goedecker–Teter–Hutter pseudopotential
    # with an explicit core-electron configuration (e.g. GTH-PBE-q6 for
    # oxygen).  The mapping is defined in GTH_CHARGE_MAP and derives from
    # the GTH construction:
    #   Goedecker, Teter & Hutter, Phys. Rev. B 54, 1703 (1996);
    #   Hartwigsen, Goedecker & Hutter, Phys. Rev. B 58, 3641 (1998).
    # An unresolved element produces a 'qX' placeholder that has no
    # matching entry in any CP2K pseudopotential library file — the run
    # will crash at POTENTIAL parsing with a non-diagnostic error.
    if unresolved:
        warn(
            f"No GTH pseudopotential charge mapping for: "
            f"{', '.join(sorted(unresolved))}. "
            f"KIND blocks contain invalid 'POTENTIAL …-qX' placeholders."
        )

    return lines, unresolved


# ─── XYZ Exporter ────────────────────────────────────────────────────────────

def write_xyz(coords, elements_per_atom, out_path):
    """Write standard XYZ file from coordinates and element list."""
    natom = len(coords)
    with open(out_path, 'w') as f:
        f.write(f"{natom}\n")
        f.write("Generated by charmmgui2cp2k.py from AMBER RST7\n")
        for i, (x, y, z) in enumerate(coords):
            elem = elements_per_atom[i] if i < len(elements_per_atom) else 'X'
            f.write(f"{elem:<3s} {x:14.8f} {y:14.8f} {z:14.8f}\n")
    return natom


PDB_CHAIN_IDS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"


def _canonical_element_symbol(elem):
    """Return PDB-style element symbol (1-2 chars) or 'X' fallback."""
    raw = str(elem or "").strip()
    if not raw:
        return "X"
    up = raw.upper()
    if up in SYMBOL_TO_ATOMIC_NUM:
        if len(up) == 1:
            return up
        return up[0] + up[1:].lower()
    if len(up) == 1:
        return up
    return up[:2].title()


def _format_pdb_atom_name(atom_name, elem):
    """Format atom name in strict PDB columns 13-16."""
    name = re.sub(r"\s+", "", str(atom_name or ""))
    if not name:
        name = str(elem or "X").strip()[:2] or "X"
    name = name[:4]
    if len(name) >= 4:
        return name
    elem_clean = str(elem or "").strip()
    # One-letter elements are conventionally right-shifted in the atom-name field.
    if len(elem_clean) == 1 and name and name[0].isalpha():
        return name.rjust(4)
    return name.ljust(4)


def _atom_residue_index_map(natom, residue_pointers):
    """Build 1-based residue index for each atom from RESIDUE_POINTER."""
    n = int(natom or 0)
    mapping = [1] * max(n, 0)
    ptr = [int(v) for v in (residue_pointers or []) if int(v) >= 1]
    if not ptr or n <= 0:
        return mapping
    nres = len(ptr)
    for r in range(nres):
        start = max(ptr[r], 1)
        end = (ptr[r + 1] - 1) if (r + 1) < nres else n
        end = min(end, n)
        if end < start:
            continue
        for a in range(start, end + 1):
            mapping[a - 1] = r + 1
    return mapping


def _pdb_chain_and_resseq(res_idx_1b):
    """
    Map absolute residue index to PDB chain ID + 4-digit resSeq.
    Rolls to next chain every 9999 residues.
    """
    idx0 = max(int(res_idx_1b) - 1, 0)
    block = idx0 // 9999
    chain = PDB_CHAIN_IDS[block % len(PDB_CHAIN_IDS)]
    resseq = idx0 % 9999 + 1
    return chain, resseq


# ── Hybrid-36 PDB serial encoding (PDB v3.3 Appendix) ─────────────────
# The legacy PDB ATOM record reserves 5 columns (7–11) for the atom
# serial, so plain decimal saturates at 99 999.  For systems exceeding
# that count (LAAO: 143 099 atoms), the wwPDB v3.3 format defines an
# extension called *hybrid-36*: serials 1–99 999 are written in plain
# decimal, and serials 100 000…43 770 015 are written as five base-36
# digits with the first character restricted to [A–Z], i.e. the
# encoding space [A0000 … ZZZZZ].  The switch is lossless and parsed
# by the standard toolchain (PyMOL, VMD, OpenBabel, MDAnalysis, RDKit,
# CCTBX/iotbx.pdb.hybrid_36).
#
# Reference: Headd, Immormino, Keedy, Afonine, Richardson &
# Richardson, *J. Appl. Cryst.* **42**, 755 (2009); RCSB PDB File
# Format v3.3, Appendix on "hybrid-36 encoding of large residue and
# atom serial numbers".
_HYBRID36_DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _encode_hybrid36_serial(num):
    """Encode a positive PDB serial into its 5-char right-aligned field.

    * 1 ≤ *num* ≤ 99 999 → decimal, right-aligned in 5 columns.
    * 100 000 ≤ *num* ≤ 43 770 015 → five upper-case base-36 digits
      with the first digit in [A–Z] ("A0000" to "ZZZZZ").
    Raises ``ValueError`` outside that union — the caller should then
    fall back to mmCIF emission rather than truncate or wrap.
    """
    width = 5
    n = int(num)
    if n < 1:
        raise ValueError(f"PDB serial must be ≥ 1, got {n}")
    if n < 10 ** width:  # 1..99 999 → decimal
        return f"{n:>{width}d}"
    # Shift so that n=100_000 → 0, then offset by 10·36^(width-1) so
    # the first base-36 digit starts at 'A' (index 10) rather than '0'.
    shifted = n - 10 ** width
    max_hy36 = 26 * 36 ** (width - 1)  # 43 670 016 for width=5
    if shifted >= max_hy36:
        raise ValueError(
            f"PDB serial {n} exceeds hybrid-36 capacity "
            f"{10 ** width + max_hy36 - 1:,}; emit mmCIF instead."
        )
    shifted += 10 * 36 ** (width - 1)  # land at 'A0000'
    out = []
    for _ in range(width):
        shifted, r = divmod(shifted, 36)
        out.append(_HYBRID36_DIGITS[r])
    return "".join(reversed(out))


def _format_pdb_atom_record(
    serial, atom_name, res_name, chain_id, res_seq, x, y, z, occupancy, temp_factor, element,
    record_name="ATOM"
):
    """Format a single strict-width PDB ATOM/HETATM record.

    ``serial`` may be an ``int`` (decimal, 1–99 999) or a pre-encoded
    5-character hybrid-36 ``str`` for large systems; see
    :func:`_encode_hybrid36_serial` and Headd et al., *J. Appl. Cryst.*
    **42**, 755 (2009).
    """
    if isinstance(serial, str):
        serial_field = f"{serial:>5s}"
    else:
        serial_field = f"{int(serial):>5d}"
    line = (
        f"{record_name:<6s}"
        f"{serial_field} "
        f"{atom_name:4s}"
        f"{' ':1s}"
        f"{res_name:>3s} "
        f"{chain_id:1s}"
        f"{int(res_seq):>4d}"
        f"{' ':1s}   "
        f"{float(x):>8.3f}"
        f"{float(y):>8.3f}"
        f"{float(z):>8.3f}"
        f"{float(occupancy):>6.2f}"
        f"{float(temp_factor):>6.2f}"
        f"{'':10s}"
        f"{element:>2s}"
        f"{'':>2s}"
    )
    return line[:80] + "\n"


def write_qmmm_boundary_pdbs(
    coords,
    qm_indices,
    full_pdb_out_path,
    qm_only_pdb_out_path,
    elements_per_atom=None,
    atom_names=None,
    residue_labels=None,
    residue_pointers=None,
):
    """
    Write two strict-format PDB files for QM/MM boundary validation.

    1) Full system with B-factor QM/MM flag:
       - tempFactor=1.00 for QM atoms, 0.00 for MM atoms.
    2) Isolated QM subsystem containing only QM atoms.
    """
    coords = list(coords or [])
    natom = len(coords)
    qm_set = {int(i) for i in (qm_indices or []) if 1 <= int(i) <= natom}
    elements = list(elements_per_atom or [])
    names = list(atom_names or [])
    res_labels = [str(r).strip().upper() for r in (residue_labels or [])]
    atom_to_res = _atom_residue_index_map(natom, residue_pointers or [])

    # Systems with > 99 999 atoms overflow the legacy 5-column PDB
    # serial field.  We emit hybrid-36 (PDB v3.3 Appendix; Headd et
    # al., J. Appl. Cryst. 42, 755, 2009) so that every atom keeps a
    # unique, lossless serial — required by downstream tools that
    # index atoms by serial (PyMOL ``index``, VMD ``serial``, CP2K
    # ``&COLVAR ATOMS``).  mmCIF remains the more future-proof
    # long-term container for very large systems, so we still point
    # the user to it as an optional upgrade rather than a requirement.
    if natom > 99999:
        info(
            f"Atom count ({natom:,}) exceeds 99,999 — serial field 7–11 "
            "uses hybrid-36 encoding (PDB v3.3 Appendix; Headd et al., "
            "J. Appl. Cryst. 42, 755, 2009). For very large systems "
            "mmCIF is the more future-proof container."
        )

    def _line_for_atom(atom_index_1b, serial_out, temp_factor):
        i = atom_index_1b - 1
        x, y, z = coords[i]
        raw_elem = elements[i] if i < len(elements) else "X"
        elem = _canonical_element_symbol(raw_elem)
        raw_name = names[i] if i < len(names) else elem
        atom_name = _format_pdb_atom_name(raw_name, elem)
        res_idx = atom_to_res[i] if i < len(atom_to_res) else 1
        raw_res = res_labels[res_idx - 1] if (res_idx - 1) < len(res_labels) else "MOL"
        res_name = (raw_res[:3] or "MOL").upper()
        chain_id, res_seq = _pdb_chain_and_resseq(res_idx)
        # Hybrid-36 encoder returns a 5-char string; the record
        # formatter accepts str or int transparently.
        serial_pdb = _encode_hybrid36_serial(int(serial_out))
        return _format_pdb_atom_record(
            serial=serial_pdb,
            atom_name=atom_name,
            res_name=res_name,
            chain_id=chain_id,
            res_seq=res_seq,
            x=x,
            y=y,
            z=z,
            occupancy=1.00,
            temp_factor=temp_factor,
            element=elem,
            record_name="ATOM",
        )

    # Full-system PDB with QM/MM flag in B-factor.
    with open(full_pdb_out_path, "w") as f:
        f.write("REMARK   1 Full system QM/MM boundary validation export\n")
        f.write("REMARK   2 B-factor flag: 1.00 = QM atom, 0.00 = MM atom\n")
        for a in range(1, natom + 1):
            bfac = 1.00 if a in qm_set else 0.00
            f.write(_line_for_atom(a, a, bfac))
        f.write("END\n")

    # QM-only PDB export.
    qm_sorted = sorted(qm_set)
    with open(qm_only_pdb_out_path, "w") as f:
        f.write("REMARK   1 Isolated QM subsystem export\n")
        for serial_out, atom_idx in enumerate(qm_sorted, start=1):
            f.write(_line_for_atom(atom_idx, serial_out, 1.00))
        f.write("END\n")

    return {"full_atoms": natom, "qm_atoms": len(qm_sorted)}


def compute_qm_cell(qm_indices, coords, padding=6.0, box_dims=None, qmmm_periodic_policy=None):
    """
    Compute QM cell ABC (Angstrom) from QM-atom bounding box + isotropic padding.
    Returns (qm_cell_abc_string, metadata_dict).

    If *box_dims* are supplied, the span is checked against the simulation box
    to detect QM atoms that may be split across periodic boundaries (a sign that
    the coordinates need imaging/recentering before QM-cell sizing).

    If *qmmm_periodic_policy* is supplied, the QM cell is also enlarged when
    needed to support the target MULTIPOLE/RCUT from that policy, subject to
    the physical MM box limits.
    """
    policy = qmmm_periodic_policy
    if policy is not None and not isinstance(policy, QMMMPeriodicPolicy):
        raise TypeError("qmmm_periodic_policy must be a QMMMPeriodicPolicy instance or None.")
    requested_padding = float(policy.qm_cell_padding if policy is not None else padding)
    target_rcut = None if policy is None else float(policy.target_multipole_rcut)
    minimum_image_buffer = (
        None if policy is None else float(policy.minimum_image_buffer)
    )
    qm_coords = []
    ncoord = len(coords or [])
    for idx in (qm_indices or []):
        if 0 < int(idx) <= ncoord:
            qm_coords.append(coords[int(idx) - 1])

    if not qm_coords:
        return "25.0 25.0 25.0", {
            'fallback': True,
            'span': (0.0, 0.0, 0.0),
            'padding': float(requested_padding),
            'used_qm_atoms': 0,
            'imaging_suspect': False,
            'target_multipole_rcut': target_rcut,
            'minimum_image_buffer': minimum_image_buffer,
        }

    xs = [float(c[0]) for c in qm_coords]
    ys = [float(c[1]) for c in qm_coords]
    zs = [float(c[2]) for c in qm_coords]
    span_x = max(xs) - min(xs)
    span_y = max(ys) - min(ys)
    span_z = max(zs) - min(zs)

    # Detect possible PBC imaging artefact: if any QM span exceeds half the
    # simulation box, the QM atoms are likely split across a periodic boundary.
    imaging_suspect = False
    if box_dims is not None:
        try:
            norm = _normalize_box_dims(box_dims)
            if norm:
                ba, bb, bc = norm[0], norm[1], norm[2]
                if (span_x > 0.5 * ba) or (span_y > 0.5 * bb) or (span_z > 0.5 * bc):
                    imaging_suspect = True
        except Exception:
            pass

    span_lengths = (span_x, span_y, span_z)
    natural_lengths = tuple(span + 2.0 * float(requested_padding) for span in span_lengths)
    target_cell_edge = None
    desired_lengths = natural_lengths
    expanded_for_target_rcut = False
    if policy is not None:
        target_cell_edge = 2.0 * (float(policy.target_multipole_rcut) + float(policy.minimum_image_buffer))
        desired_lengths = tuple(max(length, target_cell_edge) for length in natural_lengths)
        expanded_for_target_rcut = any(
            desired > natural + 1.0e-8
            for natural, desired in zip(natural_lengths, desired_lengths)
        )

    effective_lengths = desired_lengths
    box_limited_axes = []
    if box_dims is not None:
        try:
            norm = _normalize_box_dims(box_dims)
            if norm:
                effective_lengths = []
                for axis, desired, mm_len in zip(('A', 'B', 'C'), desired_lengths, norm[:3]):
                    clipped = min(float(desired), float(mm_len))
                    if clipped + 1.0e-8 < float(desired):
                        box_limited_axes.append(axis)
                    effective_lengths.append(clipped)
                effective_lengths = tuple(effective_lengths)
        except Exception:
            effective_lengths = desired_lengths

    effective_padding = tuple(
        max(0.0, 0.5 * (float(length) - float(span)))
        for length, span in zip(effective_lengths, span_lengths)
    )

    return f"{effective_lengths[0]:.1f} {effective_lengths[1]:.1f} {effective_lengths[2]:.1f}", {
        'fallback': False,
        'span': span_lengths,
        'padding': float(requested_padding),
        'used_qm_atoms': len(qm_coords),
        'imaging_suspect': imaging_suspect,
        'natural_lengths': tuple(float(x) for x in natural_lengths),
        'desired_lengths': tuple(float(x) for x in desired_lengths),
        'effective_lengths': tuple(float(x) for x in effective_lengths),
        'effective_padding': tuple(float(x) for x in effective_padding),
        'expanded_for_target_rcut': bool(expanded_for_target_rcut),
        'box_limited_axes': tuple(box_limited_axes),
        'target_multipole_rcut': target_rcut,
        'minimum_image_buffer': minimum_image_buffer,
        'target_cell_edge': (None if target_cell_edge is None else float(target_cell_edge)),
    }


# ─── Execution Wrapper / Runtime Tuning ──────────────────────────────────────

CP2K_BINARY_CANDIDATES = ('cp2k.psmp', 'cp2k.popt', 'cp2k.ssmp', 'cp2k.sopt', 'cp2k')
MPI_LAUNCHER_CANDIDATES = ('mpirun', 'mpiexec', 'srun')


# ── CP2K version detection and capability model (V1, V3, V11) ────────────────
#
# CP2K ships two naming schemes side-by-side on ``--version``:
#   1) Semantic:  "CP2K 7.7.0 (Development Version)", "CP2K version 8.1"
#   2) Year-based: "CP2K 2022.2", "CP2K 2023.1"
# The year-based releases are formally ordered *after* the last semantic
# release (8.2, April 2021) and implicitly carry "major ≥ 2022" so any
# lexicographic compare works as long as we parse both forms into a
# 3-tuple ``(major, minor, patch)``.  Ref: CP2K release notes
# https://www.cp2k.org/version_history.
#
# ``CP2K_VERSION_RE`` captures either form from a single line of
# ``cp2k --version`` output.  Historical builds print, in order:
#     "CP2K version 6.1 (Development Version)"          (6.1)
#     "CP2K version 7.1 (Development Version)"          (7.1)
#     "CP2K 7.7.0 (Development Version)"                (7.7.0)
#     "CP2K 8.1 (Development Version)"                  (8.1)
#     "CP2K 8.2"                                        (8.2)
#     "CP2K 9.1"                                        (9.1)
#     "CP2K 2022.2 (Development Version)"               (2022.2)
#     "CP2K 2023.1"                                     (2023.1)
# The regex tolerates an optional "version" token and an optional third
# ``.patch`` group; missing patch is reported as 0.
CP2K_VERSION_RE = re.compile(
    r"""
    CP2K                # literal banner prefix
    \s+                 # separator
    (?:version\s+)?     # optional "version" token (older builds)
    (?P<major>\d+)      # major integer (6, 7, 8, 9, 2022, 2023, ...)
    \.
    (?P<minor>\d+)      # minor integer (1, 2, 7, ...)
    (?:\.(?P<patch>\d+))?   # optional patch integer (0, 1, ...)
    """,
    re.VERBOSE | re.IGNORECASE,
)


def parse_cp2k_version_string(text):
    """Parse a ``cp2k --version`` output string into a ``(major, minor, patch)`` tuple.

    Returns ``None`` if the text cannot be parsed — callers should treat
    this as "version unknown" rather than "old".

    Examples
    --------
    >>> parse_cp2k_version_string("CP2K version 8.1 (Development Version)")
    (8, 1, 0)
    >>> parse_cp2k_version_string("CP2K 7.7.0 (Development Version)")
    (7, 7, 0)
    >>> parse_cp2k_version_string("CP2K 2023.1")
    (2023, 1, 0)
    """
    if not text:
        return None
    for line in str(text).splitlines():
        m = CP2K_VERSION_RE.search(line)
        if m:
            patch = m.group('patch')
            return (
                int(m.group('major')),
                int(m.group('minor')),
                int(patch) if patch is not None else 0,
            )
    return None


def format_cp2k_version(version_tuple):
    """Format a ``(major, minor, patch)`` tuple as ``"major.minor"`` or ``"major.minor.patch"``."""
    if not version_tuple:
        return "unknown"
    if len(version_tuple) >= 3 and version_tuple[2]:
        return f"{version_tuple[0]}.{version_tuple[1]}.{version_tuple[2]}"
    return f"{version_tuple[0]}.{version_tuple[1]}"


def cp2k_version_at_least(version_tuple, required):
    """Return True iff ``version_tuple`` is lexicographically ≥ ``required``.

    ``version_tuple`` may be None (meaning unknown) — in that case we
    return False so the caller treats unknown-version as not-supported
    by default.  ``required`` is a ``(major, minor)`` or ``(major, minor, patch)``.
    """
    if not version_tuple:
        return False
    v = tuple(int(x) for x in version_tuple[:3]) + (0,) * (3 - len(version_tuple[:3]))
    r = tuple(int(x) for x in required[:3]) + (0,) * (3 - len(required[:3]))
    return v >= r


def query_cp2k_version(binary_path, timeout_s=6):
    """Invoke ``<binary_path> --version`` and return the parsed version tuple.

    Returns ``(version_tuple, raw_line)`` where ``version_tuple`` is None
    on failure and ``raw_line`` is the first stdout line (or error
    context) suitable for logging.  Short timeout defends against
    binaries that hang under CUDA initialization.
    """
    if not binary_path:
        return (None, "no binary path provided")
    try:
        proc = subprocess.run(
            [str(binary_path), '--version'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_s,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return (None, f"{type(exc).__name__}: {exc}")
    raw = (proc.stdout or b'') + (proc.stderr or b'')
    try:
        decoded = raw.decode('utf-8', errors='replace')
    except Exception:
        decoded = ''
    first_line = decoded.splitlines()[0] if decoded.strip() else ''
    return (parse_cp2k_version_string(decoded), first_line)


# ── Parser-only input validation via ``cp2k --check`` (V7) ───────────────────
#
# CP2K executables expose parser-only validation through ``--check`` / ``-c``
# in current releases.  Some older/local builds have historically used
# ``--input-check`` in wrappers and documentation, so the implementation below
# tries ``--check`` first and falls back to ``--input-check`` only when the
# first invocation clearly reports an unsupported option.  The check runs
# the parser over an input file and exits with a nonzero status on any
# structural or keyword error *without* performing any SCF/MD computation.
# This is ideal for generator-time smoke testing: we can confirm that the
# emitted stage files parse against the actual resident CP2K build before
# the user queues a long run.
#
# Reference: CP2K command-line help (``cp2k.psmp --help``) and CP2K manual
# §1.2 ("Command-line options").  The option has been stable across the 6.x,
# 7.x, 8.x, and 9.x series.
#
# This probe is opt-in (--cp2k-input-check) because:
#   * It requires a working CP2K binary on $PATH at generation time (which
#     is often, but not always, the same machine that will run the job).
#   * Basis/potential files referenced by ``@INCLUDE`` or ``BASIS_SET_FILE_NAME``
#     must be resolvable relative to the working directory; the generator
#     therefore invokes the check in the emitted-inputs directory so the
#     environment matches the real run.
#   * On large inputs the parser still needs to read ABC/CELL/coordinates,
#     which is fast but not free.
def _cp2k_check_output(proc):
    """Decode combined CP2K stdout/stderr from a parser-check subprocess."""
    try:
        return (
            ((proc.stdout or b'') + b'\n' + (proc.stderr or b''))
            .decode('utf-8', errors='replace')
        )
    except Exception:
        return ''


def _tail_nonempty_lines(text, max_lines=30):
    """Return the last non-empty lines from a diagnostic text block."""
    tail_lines = [ln for ln in str(text or '').splitlines() if ln.strip()]
    return "\n".join(tail_lines[-int(max_lines):])


def _strip_runtime_restart_dependencies_for_check(input_text):
    """Create a syntax-check copy that does not require runtime restart files.

    CP2K's `--check` validates `OLD` restart paths immediately.  For staged
    workflows, later inputs are deployable only after earlier stages create
    those restart artifacts.  This sanitizer is used only for parser checking:
    it removes top-level &EXT_RESTART, removes wavefunction restart filenames,
    and changes SCF_GUESS RESTART to ATOMIC so grammar validation can continue.
    """
    cleaned = []
    in_ext_restart = False
    for line in str(input_text or '').splitlines(True):
        stripped = line.strip()
        upper = stripped.upper()
        if not in_ext_restart and re.match(r'^&EXT_RESTART(?:\s|$)', upper):
            in_ext_restart = True
            continue
        if in_ext_restart:
            if re.match(r'^&END\s+EXT_RESTART(?:\s|$)', upper):
                in_ext_restart = False
            continue
        if re.match(r'^WFN_RESTART_FILE_NAME(?:\s|$)', upper):
            continue
        if re.match(r'^SCF_GUESS\s+RESTART(?:\s|$)', upper):
            cleaned.append(re.sub(r'(?i)(SCF_GUESS\s+)RESTART\b', r'\1ATOMIC', line, count=1))
            continue
        cleaned.append(line)
    return ''.join(cleaned)


def _cp2k_failure_is_missing_restart_dependency(output_text):
    """Return True when CP2K --check failed only because a restart file is absent."""
    text = str(output_text or '')
    return bool(
        re.search(r'The specified OLD file <[^>]+> cannot be opened', text, re.I)
        or re.search(r'WFN_RESTART_FILE_NAME.*(cannot be opened|does not exist)', text, re.I)
        or re.search(r'(restart|wfn).*file.*(cannot be opened|does not exist)', text, re.I)
    )


def run_cp2k_input_check(binary_path, input_path, working_dir=None, timeout_s=60):
    """Run CP2K parser-only input validation and report.

    Returns a dict with keys:
        ok : bool              — True iff exit code == 0
        returncode : int|None  — raw exit code (None on timeout/OS error)
        stderr_tail : str      — last few lines of stderr for diagnostics
        error : str|None       — OSError/TimeoutExpired summary if any

    We run the check in ``working_dir`` so relative ``@INCLUDE`` paths,
    ``BASIS_SET_FILE_NAME``, and ``POTENTIAL_FILE_NAME`` resolve exactly
    as they would at runtime.
    """
    result = {
        'ok': False,
        'returncode': None,
        'stderr_tail': '',
        'error': None,
        'mode': 'direct',
        'restart_dependency_missing': False,
        'direct_returncode': None,
        'direct_tail': '',
    }
    if not binary_path:
        result['error'] = 'no CP2K binary configured for --input-check'
        return result
    if not os.path.isfile(str(input_path)):
        result['error'] = f'input file does not exist: {input_path}'
        return result

    cwd = (str(working_dir) if working_dir else os.path.dirname(str(input_path)))
    input_name = str(os.path.basename(input_path))

    def _run_check(option, check_input_name=input_name):
        return subprocess.run(
            [str(binary_path), option, check_input_name],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_s,
            check=False,
        )

    try:
        proc = _run_check('--check')
        decoded = _cp2k_check_output(proc)
        option_unknown = (
            proc.returncode != 0
            and re.search(r'(unknown|invalid|unrecognized).*(--check|option)', decoded, re.I)
        )
        if option_unknown:
            proc = _run_check('--input-check')
    except (OSError, subprocess.TimeoutExpired) as exc:
        result['error'] = f"{type(exc).__name__}: {exc}"
        return result

    decoded = _cp2k_check_output(proc)
    result['direct_returncode'] = int(proc.returncode or 0)
    result['direct_tail'] = _tail_nonempty_lines(decoded, max_lines=30)

    if proc.returncode != 0 and _cp2k_failure_is_missing_restart_dependency(decoded):
        temp_name = None
        try:
            with open(input_path, 'r') as f:
                original_text = f.read()
            sanitized_text = _strip_runtime_restart_dependencies_for_check(original_text)
            with tempfile.NamedTemporaryFile(
                mode='w',
                dir=cwd,
                prefix='.cp2k_syntax_check_',
                suffix='.inp',
                delete=False,
            ) as tf:
                tf.write(sanitized_text)
                temp_name = os.path.basename(tf.name)
            proc = _run_check('--check', check_input_name=temp_name)
            decoded = _cp2k_check_output(proc)
            option_unknown = (
                proc.returncode != 0
                and re.search(r'(unknown|invalid|unrecognized).*(--check|option)', decoded, re.I)
            )
            if option_unknown:
                proc = _run_check('--input-check', check_input_name=temp_name)
                decoded = _cp2k_check_output(proc)
            result['mode'] = 'syntax_only_without_restart_dependencies'
            result['restart_dependency_missing'] = True
        except (OSError, subprocess.TimeoutExpired) as exc:
            result['error'] = f"{type(exc).__name__}: {exc}"
            return result
        finally:
            if temp_name:
                try:
                    os.unlink(os.path.join(cwd, temp_name))
                except OSError:
                    pass

    result['returncode'] = int(proc.returncode or 0)
    result['ok'] = (result['returncode'] == 0)
    result['stderr_tail'] = _tail_nonempty_lines(_cp2k_check_output(proc), max_lines=30)
    return result


# ── CP2K keyword → minimum stable version (V1) ───────────────────────────────
#
# Authoritative table mapping each CP2K input keyword or BASIS_ADMM_MOLOPT
# entry that the emitter can produce to the earliest CP2K release at which
# the keyword is documented stable.  Used by the V2 two-tier gate to
# decide whether emission of a given keyword is safe on the detected
# CP2K version, and by the V4 graceful-substitution path to decide
# whether a requested feature must be replaced by an older equivalent.
#
# Each entry carries a citation so the provenance is defensible on first
# read.  When adding a keyword, cite the primary paper *and* the CP2K
# release notes line that first documents it.
CP2K_KEYWORD_MIN_VERSION = {
    # ADMM: projects |Ψ⟩ onto a smaller auxiliary basis for HFX, then
    # computes the exchange correction on the difference density.  The
    # full ``&AUXILIARY_DENSITY_MATRIX_METHOD`` subsection has been
    # stable since CP2K 5.1.  Ref: Guidon, Hutter, VandeVondele,
    # JCTC 6, 2348 (2010).
    '&FORCE_EVAL/&DFT/&AUXILIARY_DENSITY_MATRIX_METHOD': (5, 1),
    # Truncated HFX interaction potential (real-space cutoff inside the
    # HFX integral); CUTOFF_RADIUS subkey has been stable since CP2K 4.1.
    # Ref: Guidon, Hutter, VandeVondele, JCTC 5, 3010 (2009).
    '&FORCE_EVAL/&DFT/&XC/&HF/&INTERACTION_POTENTIAL/CUTOFF_RADIUS': (4, 1),
    # GEEP-periodic QM/MM long-range multipole expansion.  The
    # ``&MULTIPOLE/RCUT`` subkey inside ``&QMMM/&PERIODIC`` has been
    # documented stable since CP2K 6.1.  Ref: Laino, Mohamed, Curioni,
    # VandeVondele, JCTC 2, 1370 (2006); CP2K 6.1 release notes.
    '&FORCE_EVAL/&QMMM/&PERIODIC/&MULTIPOLE/RCUT': (6, 1),
    # GEEP Gaussian embedding grid depth, stable since CP2K 4.1.
    # Ref: Laino et al., JCTC 1, 1176 (2005).
    '&FORCE_EVAL/&QMMM/USE_GEEP_LIB': (4, 1),
    # Historical curated ADMM auxiliary basis — cFIT3 / cpFIT3.  Shipped
    # in BASIS_ADMM_MOLOPT since CP2K 5.1.  Ref: Merlot, Iannuzzi et al.
    # contributions, BASIS_ADMM_MOLOPT file header.
    'BASIS_ADMM_MOLOPT/cFIT3': (5, 1),
    'BASIS_ADMM_MOLOPT/cpFIT3': (5, 1),
    # admm-dzp — newer curated auxiliary basis added in CP2K 8.1.
    # Ref: CP2K 8.1 release notes; BASIS_ADMM_MOLOPT header for 8.1+.
    'BASIS_ADMM_MOLOPT/admm-dzp': (8, 1),
}


# ── ResolvedCP2KCapability (V3) ──────────────────────────────────────────────
#
# Immutable snapshot of the capability view for a detected CP2K version.
# Built once at main() and threaded through the emitters so every
# version-gated decision reads from the same authoritative object.
class ResolvedCP2KCapability(NamedTuple):
    """Per-keyword availability for a resolved CP2K version.

    Attributes
    ----------
    version : tuple or None
        ``(major, minor, patch)`` tuple or None when detection failed.
    raw_version_line : str
        First line of ``cp2k --version`` output, kept for error
        messages and the compat report.
    keywords : dict
        Map from each entry in ``CP2K_KEYWORD_MIN_VERSION`` to a bool
        indicating whether the detected version is ≥ the required one.
    floor_hard : tuple
        Hard floor below which the pipeline refuses to emit (V2).
    floor_soft : tuple
        Soft floor below which certain optional features are gated
        (e.g. admm-dzp — V4).
    """
    version: object
    raw_version_line: str
    keywords: object
    floor_hard: object
    floor_soft: object


# Hard/soft floors for the V2 two-tier gate.
#
# * Hard floor 7.1 — the minimum release at which every non-optional
#   keyword the pipeline emits is stably documented: GEEP-periodic
#   QM/MM (Laino 2006; CP2K 6.1 but the full &PERIODIC/&MULTIPOLE RCUT
#   default semantics were refined through 7.1), ADMM with cpFIT3
#   (Guidon 2010; stable since 5.1), modern MOLOPT/GTH (stable since
#   2.x), and the full &EXT_RESTART flag set (stable since 5.1).
#   7.1 is also the minimum version at which the CUDA QMMM path is
#   documented stable.
# * Soft floor 8.1 — required only when the user selects ``admm-dzp``
#   as the ADMM auxiliary basis (V4 substitutes cpFIT3 below this
#   floor).  Ref: CP2K 8.1 release notes.
CP2K_VERSION_FLOOR_HARD = (7, 1)
CP2K_VERSION_FLOOR_SOFT = (8, 1)


def build_cp2k_capability(version_tuple, raw_version_line="",
                          floor_hard=CP2K_VERSION_FLOOR_HARD,
                          floor_soft=CP2K_VERSION_FLOOR_SOFT):
    """Construct a ``ResolvedCP2KCapability`` from a parsed version tuple."""
    keywords = {}
    for kw, required in CP2K_KEYWORD_MIN_VERSION.items():
        keywords[kw] = cp2k_version_at_least(version_tuple, required)
    return ResolvedCP2KCapability(
        version=tuple(version_tuple) if version_tuple else None,
        raw_version_line=str(raw_version_line or ''),
        keywords=keywords,
        floor_hard=tuple(floor_hard),
        floor_soft=tuple(floor_soft),
    )


# ── V10: internal coherence check for the version-gate constants ─────────────
#
# This self-check runs at module scope so any edit that breaks the
# invariants of the two-tier gate is caught on the very first CLI
# invocation after the change — long before any user-visible misbehavior.
# The four invariants checked are:
#
#   1. Every (major, minor) tuple in ``CP2K_KEYWORD_MIN_VERSION`` has
#      exactly two non-negative integer components.  The code that
#      compares versions (``cp2k_version_at_least``) assumes this shape.
#
#   2. ``CP2K_VERSION_FLOOR_HARD`` <= ``CP2K_VERSION_FLOOR_SOFT``.  The
#      soft floor documents the "optional feature" boundary above the
#      hard floor; inverting them would silently break V4 substitution
#      logic and the compat-report wording.
#
#   3. Every keyword with a min version > floor_hard is *optional* —
#      i.e., either it's covered by a documented V4 substitution path,
#      or it's a keyword the emitter never forces.  We enforce this via
#      an explicit allow-list so adding a mandatory keyword above the
#      hard floor is an affirmative choice, not an oversight.
#
#   4. At least one keyword sits at or above the soft floor (sanity
#      check: if not, soft floor has nothing to gate and should be
#      lowered).  We surface this as a soft warning, not an error.
#
# Any violation of invariants (1)–(3) raises ``AssertionError`` so the
# problem is seen immediately in development.  (4) logs via
# sys.stderr because it's informational.
CP2K_OPTIONAL_ABOVE_HARD_FLOOR = frozenset({
    # admm-dzp is optional: V4 substitutes cpFIT3 when it is unavailable.
    'BASIS_ADMM_MOLOPT/admm-dzp',
})


def assert_version_gate_coherence():
    """Self-check that the version-gate constants are internally consistent.

    Called from ``main()`` before emission.  Returns ``True`` on success
    and raises ``AssertionError`` on a hard invariant violation.  A soft
    warning may be printed for informational-only concerns.
    """
    # (1) Tuple shape
    for kw, req in CP2K_KEYWORD_MIN_VERSION.items():
        if (not isinstance(req, tuple) or len(req) != 2 or
                not all(isinstance(x, int) and x >= 0 for x in req)):
            raise AssertionError(
                f"CP2K_KEYWORD_MIN_VERSION[{kw!r}] must be a "
                f"(major, minor) pair of non-negative ints; got {req!r}."
            )
    # (2) Hard <= Soft
    if not cp2k_version_at_least(CP2K_VERSION_FLOOR_SOFT, CP2K_VERSION_FLOOR_HARD):
        raise AssertionError(
            "CP2K_VERSION_FLOOR_HARD "
            f"({format_cp2k_version(CP2K_VERSION_FLOOR_HARD)}) exceeds "
            "CP2K_VERSION_FLOOR_SOFT "
            f"({format_cp2k_version(CP2K_VERSION_FLOOR_SOFT)})."
        )
    # (3) Every above-hard keyword is explicitly optional
    for kw, req in CP2K_KEYWORD_MIN_VERSION.items():
        if cp2k_version_at_least(req, CP2K_VERSION_FLOOR_HARD) and req != CP2K_VERSION_FLOOR_HARD:
            # req > floor_hard — treat as above-hard if strictly greater.
            if req[0] > CP2K_VERSION_FLOOR_HARD[0] or (
                req[0] == CP2K_VERSION_FLOOR_HARD[0] and req[1] > CP2K_VERSION_FLOOR_HARD[1]
            ):
                if kw not in CP2K_OPTIONAL_ABOVE_HARD_FLOOR:
                    raise AssertionError(
                        f"Keyword {kw!r} requires CP2K "
                        f">= {format_cp2k_version(req)} which is above the "
                        f"hard floor {format_cp2k_version(CP2K_VERSION_FLOOR_HARD)}, "
                        "but is not listed in CP2K_OPTIONAL_ABOVE_HARD_FLOOR. "
                        "Either lower the keyword's requirement, raise the "
                        "hard floor, or declare the keyword optional with a "
                        "documented substitution path."
                    )
    # (4) Soft floor has at least one gated keyword (informational)
    soft_gated = [
        kw for kw, req in CP2K_KEYWORD_MIN_VERSION.items()
        if cp2k_version_at_least(req, CP2K_VERSION_FLOOR_SOFT)
    ]
    if not soft_gated:
        sys.stderr.write(
            "NOTE: CP2K_VERSION_FLOOR_SOFT "
            f"({format_cp2k_version(CP2K_VERSION_FLOOR_SOFT)}) gates no "
            "keywords; consider lowering it to match the highest required "
            "version in CP2K_KEYWORD_MIN_VERSION.\n"
        )
    return True


def _detect_physical_cores():
    """Best-effort physical core detection (falls back to logical count)."""
    logical = max(int(os.cpu_count() or 1), 1)
    if not sys.platform.startswith('linux'):
        return logical

    try:
        with open('/proc/cpuinfo', 'r') as f:
            text = f.read()
        phys_core_pairs = set()
        block_phys = None
        block_core = None
        for line in text.splitlines():
            if not line.strip():
                if block_phys is not None and block_core is not None:
                    phys_core_pairs.add((block_phys, block_core))
                block_phys = None
                block_core = None
                continue
            if line.startswith('physical id'):
                block_phys = line.split(':', 1)[1].strip()
            elif line.startswith('core id'):
                block_core = line.split(':', 1)[1].strip()
        if block_phys is not None and block_core is not None:
            phys_core_pairs.add((block_phys, block_core))
        if phys_core_pairs:
            return max(len(phys_core_pairs), 1)
    except Exception:
        pass
    return logical


def _find_nvidia_smi():
    """Locate nvidia-smi executable via PATH or common absolute locations."""
    path = shutil.which('nvidia-smi')
    if path:
        return path
    for candidate in ('/usr/bin/nvidia-smi', '/usr/local/bin/nvidia-smi'):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _parse_nvidia_smi_l_output_devices(stdout_text):
    """
    Parse `nvidia-smi -L` output into GPU device dicts.
    """
    gpus = []
    for line in str(stdout_text or "").splitlines():
        raw = line.strip()
        if not raw:
            continue
        m = re.match(r'^GPU\s+(\d+)\s*:\s*(.+?)(?:\s+\(UUID:.*\))?$', raw)
        if m:
            gpus.append({
                'index': int(m.group(1)),
                'name': m.group(2).strip(),
                'memory_mb': None,
            })
    return gpus


def _parse_nvidia_memory_mb(raw):
    """Parse memory strings like '40536 MiB' to integer MiB."""
    m = re.search(r'(\d+(?:\.\d+)?)\s*MiB', str(raw))
    if not m:
        return None
    try:
        return int(float(m.group(1)))
    except Exception:
        return None


def _parse_nvidia_smi_query_output_devices(stdout_text):
    """
    Parse `nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader`.
    """
    devices = []
    for line in str(stdout_text or "").splitlines():
        raw = line.strip()
        if not raw:
            continue
        parts = [p.strip() for p in raw.split(',')]
        if len(parts) < 3:
            continue
        idx_raw = parts[0]
        name = parts[1]
        mem = _parse_nvidia_memory_mb(parts[2])
        try:
            idx = int(idx_raw)
        except Exception:
            continue
        devices.append({'index': idx, 'name': name, 'memory_mb': mem})
    return devices


def _detect_gpus_via_nvidia_smi(nvidia_smi_path):
    """Best-effort GPU detection from nvidia-smi with multiple query modes."""
    if not nvidia_smi_path:
        return [], None

    try:
        p = subprocess.run(
            [nvidia_smi_path, '--query-gpu=index,name,memory.total', '--format=csv,noheader'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=12,
            check=False,
        )
        if p.returncode == 0:
            parsed = _parse_nvidia_smi_query_output_devices(p.stdout)
            if parsed:
                return parsed, 'nvidia-smi --query-gpu'
    except Exception:
        pass

    try:
        p = subprocess.run(
            [nvidia_smi_path, '-L'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=12,
            check=False,
        )
        if p.returncode == 0:
            parsed = _parse_nvidia_smi_l_output_devices(p.stdout)
            if parsed:
                return parsed, 'nvidia-smi -L'
    except Exception:
        pass

    return [], None


def _detect_gpu_count_from_proc():
    """Fallback GPU count from /proc/driver/nvidia/gpus."""
    base = '/proc/driver/nvidia/gpus'
    if not os.path.isdir(base):
        return 0
    try:
        return len([e for e in os.listdir(base) if os.path.isdir(os.path.join(base, e))])
    except Exception:
        return 0


def _detect_gpu_count_from_dev():
    """Fallback GPU count from /dev/nvidia[0-9]+ nodes."""
    try:
        nodes = glob.glob('/dev/nvidia[0-9]*')
        return len(sorted(set(nodes)))
    except Exception:
        return 0


def _detect_gpu_count_from_cuda_visible_devices():
    """
    Fallback GPU count from CUDA_VISIBLE_DEVICES when explicit devices are listed.
    """
    raw = os.environ.get('CUDA_VISIBLE_DEVICES')
    if raw is None:
        return 0
    text = str(raw).strip()
    if not text:
        return 0
    lower = text.lower()
    if lower in {'none', 'void', 'no', '-1'}:
        return 0
    if lower == 'all':
        return 0
    parts = [p.strip() for p in text.split(',')]
    parts = [p for p in parts if p]
    return len(parts)


def detect_local_hardware():
    """Detect local CPU/GPU/memory resources for wrapper auto-tuning."""
    logical = max(int(os.cpu_count() or 1), 1)
    physical = max(int(_detect_physical_cores() or logical), 1)

    memory_gb = None
    try:
        with open('/proc/meminfo', 'r') as f:
            for line in f:
                if line.startswith('MemTotal:'):
                    parts = line.split()
                    if len(parts) >= 2:
                        kb = float(parts[1])
                        memory_gb = kb / (1024.0 * 1024.0)
                    break
    except Exception:
        memory_gb = None

    gpu_devices = []
    gpu_method = 'none'
    nvidia_smi = _find_nvidia_smi()
    if nvidia_smi:
        gpu_devices, gpu_method = _detect_gpus_via_nvidia_smi(nvidia_smi)

    if not gpu_devices:
        proc_count = _detect_gpu_count_from_proc()
        if proc_count > 0:
            gpu_devices = [
                {'index': i, 'name': f"NVIDIA GPU {i}", 'memory_mb': None}
                for i in range(proc_count)
            ]
            gpu_method = '/proc/driver/nvidia/gpus'

    if not gpu_devices:
        dev_count = _detect_gpu_count_from_dev()
        if dev_count > 0:
            gpu_devices = [
                {'index': i, 'name': f"NVIDIA GPU {i}", 'memory_mb': None}
                for i in range(dev_count)
            ]
            gpu_method = '/dev/nvidia*'

    if not gpu_devices:
        env_count = _detect_gpu_count_from_cuda_visible_devices()
        if env_count > 0:
            gpu_devices = [
                {'index': i, 'name': f"CUDA_VISIBLE_DEVICES GPU {i}", 'memory_mb': None}
                for i in range(env_count)
            ]
            gpu_method = 'CUDA_VISIBLE_DEVICES'

    gpus = []
    for d in gpu_devices:
        mem = d.get('memory_mb')
        if mem is None:
            gpus.append(str(d.get('name', f"GPU {d.get('index', '?')}")))
        else:
            gpus.append(f"{d.get('name')} ({int(mem)} MiB)")

    return {
        'logical_cores': logical,
        'physical_cores': physical,
        'memory_gb': memory_gb,
        'gpus': gpus,
        'gpu_devices': gpu_devices,
        'gpu_count': len(gpu_devices),
        'gpu_detection_method': gpu_method,
        'nvidia_smi_path': nvidia_smi,
    }


def select_best_gpu_device(hardware_info):
    """
    Select best single GPU candidate.
    Priority: highest total memory, then lowest index.
    """
    hw = dict(hardware_info or {})
    devices = list(hw.get('gpu_devices') or [])
    if not devices:
        gpu_names = list(hw.get('gpus') or [])
        if gpu_names:
            devices = [
                {'index': i, 'name': str(name), 'memory_mb': None}
                for i, name in enumerate(gpu_names)
            ]
        else:
            gpu_count = max(int(hw.get('gpu_count') or 0), 0)
            if gpu_count > 0:
                devices = [
                    {'index': i, 'name': f"GPU {i}", 'memory_mb': None}
                    for i in range(gpu_count)
                ]
    if not devices:
        return None

    def _key(dev):
        mem = dev.get('memory_mb')
        mem_score = float(mem) if mem is not None else -1.0
        idx = int(dev.get('index', 99999))
        return (-mem_score, idx)

    best = sorted(devices, key=_key)[0]
    return {
        'index': int(best.get('index', 0)),
        'name': str(best.get('name', f"GPU {best.get('index', 0)}")),
        'memory_mb': best.get('memory_mb'),
    }


def detect_cp2k_installation(probe_version=True):
    """Detect CP2K executables, MPI launchers in PATH, and (optionally) the version.

    When ``probe_version`` is True, invoke ``--version`` on the first
    detected CP2K binary to populate ``version`` (a ``(major, minor, patch)``
    tuple, or None on failure) and ``version_line`` (the raw first line,
    retained for the compat report).  Runs only once per pipeline
    invocation; the tuple is cached for reuse by downstream gates (V2),
    capability-based emission (V4), and the compat report (V6/V9).
    """
    binaries = OrderedDict()
    for name in CP2K_BINARY_CANDIDATES:
        path = shutil.which(name)
        if path:
            binaries[name] = path

    mpi_launchers = OrderedDict()
    for name in MPI_LAUNCHER_CANDIDATES:
        path = shutil.which(name)
        if path:
            mpi_launchers[name] = path

    preferred_mpi = None
    for name in MPI_LAUNCHER_CANDIDATES:
        if name in mpi_launchers:
            preferred_mpi = mpi_launchers[name]
            break

    version_tuple = None
    version_line = ''
    if probe_version and binaries:
        # Probe the first detected binary — matches the priority order in
        # CP2K_BINARY_CANDIDATES (psmp > popt > ssmp > sopt > cp2k).
        first_bin_path = next(iter(binaries.values()))
        version_tuple, version_line = query_cp2k_version(first_bin_path)

    return {
        'binaries': binaries,
        'mpi_launchers': mpi_launchers,
        'mpi_launcher': preferred_mpi,
        'version': version_tuple,
        'version_line': version_line,
    }


def _parse_cp2k_runtime_monitor_metadata(input_text):
    """Extract lightweight runtime hints from a CP2K input string."""
    text = str(input_text or "")
    project = None
    run_type = None
    md_steps = None
    step_start_val = None
    geo_opt_max_iter = None
    trajectory_format = None
    free_energy_method = None

    m = re.search(r'(?im)^\s*PROJECT\s+(\S+)\s*$', text)
    if m:
        project = m.group(1).strip()

    m = re.search(r'(?im)^\s*RUN_TYPE\s+(\S+)\s*$', text)
    if m:
        run_type = m.group(1).strip().upper()

    md_block = re.search(r'(?is)&MD\b(.*?)&END\s+MD\b', text)
    if md_block:
        m = re.search(r'(?im)^\s*STEPS\s+([0-9]+)\s*$', md_block.group(1))
        if m:
            md_steps = int(m.group(1))
        m = re.search(r'(?im)^\s*STEP_START_VAL\s+([0-9]+)\s*$', md_block.group(1))
        if m:
            step_start_val = int(m.group(1))

    geo_block = re.search(r'(?is)&GEO_OPT\b(.*?)&END\s+GEO_OPT\b', text)
    if geo_block:
        m = re.search(r'(?im)^\s*MAX_ITER\s+([0-9]+)\s*$', geo_block.group(1))
        if m:
            geo_opt_max_iter = int(m.group(1))

    traj_block = re.search(r'(?is)&TRAJECTORY\b(.*?)&END\s+TRAJECTORY\b', text)
    if traj_block:
        m = re.search(r'(?im)^\s*FORMAT\s+(\S+)\s*$', traj_block.group(1))
        if m:
            trajectory_format = m.group(1).strip().upper()
    free_energy_block = re.search(r'(?is)&FREE_ENERGY\b(.*?)&END\s+FREE_ENERGY\b', text)
    if free_energy_block:
        m = re.search(r'(?im)^\s*METHOD\s+(\S+)\s*$', free_energy_block.group(1))
        if m:
            free_energy_method = m.group(1).strip().upper()

    return {
        'project': project,
        'run_type': run_type,
        'md_steps': md_steps,
        'step_start_val': step_start_val,
        'geo_opt_max_iter': geo_opt_max_iter,
        'trajectory_format': trajectory_format,
        'free_energy_method': free_energy_method,
        'has_dft': bool(re.search(r'(?im)^\s*&DFT\b', text)),
    }


def _build_stage_wrapper_manifest(stage_inputs, stage_meta):
    """Build canonical per-stage metadata for wrapper orchestration and monitoring."""
    stage_inputs = OrderedDict(stage_inputs or {})
    meta = dict(stage_meta or {})
    declared_order = [os.path.basename(str(s)) for s in (meta.get('stage_order') or stage_inputs.keys())]
    stage_order = [stage for stage in declared_order if stage in stage_inputs]
    for stage in stage_inputs.keys():
        base = os.path.basename(str(stage))
        if base not in stage_order:
            stage_order.append(base)

    dep_map = {}
    consumers = {}
    for dep in meta.get('dependencies') or []:
        consumer_stage = os.path.basename(str(dep.get('stage') or ''))
        if consumer_stage:
            dep_map[consumer_stage] = dict(dep)
        for key in ('restart_from', 'wfn_restart_from'):
            artifact = str(dep.get(key) or '').strip()
            if artifact:
                consumers.setdefault(artifact, []).append(consumer_stage)

    stage_map = OrderedDict()
    for idx, base in enumerate(stage_order):
        input_text = stage_inputs.get(base, "")
        stem = os.path.splitext(base)[0]
        runtime_meta = _parse_cp2k_runtime_monitor_metadata(input_text)
        project = runtime_meta.get('project') or stem
        dep = dict(dep_map.get(base) or {})
        upstream_artifacts = []
        for dep_key, dep_kind in (('restart_from', 'restart'), ('wfn_restart_from', 'wfn')):
            artifact = str(dep.get(dep_key) or '').strip()
            if artifact:
                upstream_artifacts.append({
                    'path': artifact,
                    'kind': dep_kind,
                })
        required_outputs = []
        # SSOT derivation (S10): the two per-stage artifacts CP2K writes are
        # fully determined by the &GLOBAL/PROJECT identifier; route through
        # StageRestartSpec so any future rename of the suffix convention
        # touches exactly one place.
        _stage_spec = StageRestartSpec(project)
        restart_name = _stage_spec.ext_restart
        wfn_name = _stage_spec.wfn_restart
        if restart_name in consumers:
            required_outputs.append(restart_name)
        if wfn_name in consumers:
            required_outputs.append(wfn_name)
        stage_map[base] = {
            'stage_name': stem,
            'input_file': base,
            'default_log': f"{stem}.log",
            'project': project,
            'run_type': runtime_meta.get('run_type'),
            'md_steps': runtime_meta.get('md_steps'),
            'step_start_val': runtime_meta.get('step_start_val'),
            'geo_opt_max_iter': runtime_meta.get('geo_opt_max_iter'),
            'trajectory_format': runtime_meta.get('trajectory_format'),
            'free_energy_method': runtime_meta.get('free_energy_method'),
            'has_dft': bool(runtime_meta.get('has_dft')),
            'pre_relaxation': bool(dep.get('pre_relaxation')),
            'upstream_artifacts': upstream_artifacts,
            'required_outputs': required_outputs,
            'next_stage': (stage_order[idx + 1] if (idx + 1) < len(stage_order) else ''),
        }
    return {
        'stage_order': stage_order,
        'stages': stage_map,
    }


def _bash_double_quote(text):
    """Escape a Python string for inclusion inside a bash double-quoted literal."""
    return str(text).replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace('`', '\\`')


def recommend_cp2k_launch_settings(hardware_info, cp2k_info):
    """
    Recommend MPI/OpenMP launch settings for CP2K wrapper generation.
    """
    hw = dict(hardware_info or {})
    cp2k = dict(cp2k_info or {})
    bins = cp2k.get('binaries') or {}

    selected_name = None
    selected_path = None
    for name in CP2K_BINARY_CANDIDATES:
        if name in bins:
            selected_name = name
            selected_path = bins[name]
            break

    logical = max(int(hw.get('logical_cores') or 1), 1)
    physical = max(int(hw.get('physical_cores') or logical), 1)
    gpu_count = max(int(hw.get('gpu_count') or 0), 0)
    best_gpu = select_best_gpu_device(hw)
    mpi_launcher = cp2k.get('mpi_launcher')
    mpi_np_flag = '-n' if mpi_launcher and os.path.basename(mpi_launcher) == 'srun' else '-np'

    notes = []
    if selected_path is None:
        notes.append("No CP2K binary detected in PATH; wrapper uses cp2k.psmp placeholder.")
        return {
            'available': False,
            'cp2k_binary_name': 'cp2k.psmp',
            'cp2k_binary': 'cp2k.psmp',
            'use_mpi': False,
            'mpi_launcher': mpi_launcher,
            'mpi_np_flag': mpi_np_flag,
            'mpi_ranks': 1,
            'omp_threads': max(1, min(physical, 8)),
            'selected_gpu_index': (best_gpu['index'] if best_gpu else None),
            'selected_gpu_name': (best_gpu['name'] if best_gpu else None),
            'notes': notes,
        }

    use_mpi = False
    ranks = 1
    omp_threads = 1

    if selected_name == 'cp2k.psmp':
        # Safe policy requested: CPU threading over physical cores + single selected GPU, no MPI fan-out.
        use_mpi = False
        ranks = 1
        omp_threads = max(1, physical)
        if gpu_count > 0 and best_gpu is not None:
            notes.append(
                "Safe mode: single-GPU run (best detected GPU) with OpenMP over physical CPU cores; MPI disabled."
            )
        else:
            notes.append("Safe mode: CPU-only OpenMP over physical cores; MPI disabled.")

    elif selected_name == 'cp2k.popt':
        omp_threads = 1
        if mpi_launcher:
            use_mpi = True
            ranks = max(1, min(logical, 64))
        else:
            notes.append("MPI launcher not found; popt will run serially.")

    elif selected_name == 'cp2k.ssmp':
        use_mpi = False
        omp_threads = max(1, physical)

    else:
        use_mpi = False
        omp_threads = 1

    return {
        'available': True,
        'cp2k_binary_name': selected_name,
        'cp2k_binary': selected_path,
        'use_mpi': bool(use_mpi and mpi_launcher and int(ranks) > 1),
        'mpi_launcher': mpi_launcher,
        'mpi_np_flag': mpi_np_flag,
        'mpi_ranks': int(max(1, ranks)),
        'omp_threads': int(max(1, omp_threads)),
        'selected_gpu_index': (best_gpu['index'] if best_gpu else None),
        'selected_gpu_name': (best_gpu['name'] if best_gpu else None),
        'notes': notes,
    }


def write_cp2k_execution_wrapper(
    wrapper_path,
    input_filename,
    log_filename,
    launch_cfg,
    hardware_info=None,
    cp2k_info=None,
    detection_enabled=False,
    stage_inputs=None,
    stage_meta=None,
    cp2k_min_version_override=None,
    cp2k_skip_version_check_default=False,
):
    """Write a runnable shell wrapper that captures CP2K stdout/stderr into a log.

    Version-gate overrides (V8)
    ---------------------------
    * ``cp2k_min_version_override``: if provided (e.g. ``"7.0"``), it is baked
      into the wrapper as the default for the ``CP2K_MIN_VERSION`` shell
      variable, replacing the compile-time ``CP2K_VERSION_FLOOR_HARD``
      default.  Users can still override at runtime by exporting
      ``CP2K_MIN_VERSION`` before invoking the wrapper.
    * ``cp2k_skip_version_check_default``: if ``True``, the generated
      wrapper defaults ``CP2K_SKIP_VERSION_CHECK`` to ``"1"`` so the gate
      is bypassed without the user having to set the env var.  Used when
      the user passed ``--cp2k-skip-version-check`` at generation time.
    """
    cfg = dict(launch_cfg or {})
    hw = dict(hardware_info or {})
    cp2k = dict(cp2k_info or {})
    stage_wrapper_manifest = _build_stage_wrapper_manifest(stage_inputs, stage_meta)
    stage_order = list(stage_wrapper_manifest.get('stage_order') or [])
    stage_specs = OrderedDict(stage_wrapper_manifest.get('stages') or {})

    cp2k_bin = str(cfg.get('cp2k_binary') or 'cp2k.psmp')
    mpi_launcher = cfg.get('mpi_launcher')
    mpi_np_flag = str(cfg.get('mpi_np_flag') or '-np')
    mpi_ranks = int(max(1, int(cfg.get('mpi_ranks') or 1)))
    omp_threads = int(max(1, int(cfg.get('omp_threads') or 1)))
    use_mpi = bool(cfg.get('use_mpi')) and bool(mpi_launcher) and mpi_ranks > 1
    selected_gpu_index = cfg.get('selected_gpu_index')
    selected_gpu_name = cfg.get('selected_gpu_name')

    lines = []
    lines.append("#!/usr/bin/env bash\n")
    lines.append("set -euo pipefail\n\n")
    lines.append("# Auto-generated by charmmgui2cp2k.py\n")
    lines.append(f"# Hardware probing enabled: {'yes' if detection_enabled else 'no'}\n")
    lines.append(f"# Detected logical cores: {int(hw.get('logical_cores') or 1)}\n")
    lines.append(f"# Detected physical cores: {int(hw.get('physical_cores') or int(hw.get('logical_cores') or 1))}\n")
    if hw.get('memory_gb') is not None:
        lines.append(f"# Detected memory [GB]: {float(hw['memory_gb']):.1f}\n")
    lines.append(f"# Detected GPUs: {int(hw.get('gpu_count') or 0)}\n")
    if hw.get('gpu_detection_method'):
        lines.append(f"# GPU detection method: {hw.get('gpu_detection_method')}\n")
    if hw.get('nvidia_smi_path'):
        lines.append(f"# nvidia-smi path: {hw.get('nvidia_smi_path')}\n")
    if cp2k.get('binaries'):
        lines.append(
            "# Detected CP2K binaries: "
            + ", ".join(f"{k}={v}" for k, v in cp2k['binaries'].items())
            + "\n"
        )
    else:
        lines.append("# Detected CP2K binaries: none\n")
    if cp2k.get('mpi_launcher'):
        lines.append(f"# Detected MPI launcher: {cp2k['mpi_launcher']}\n")
    else:
        lines.append("# Detected MPI launcher: none\n")
    if selected_gpu_index is not None:
        lines.append(
            f"# Selected GPU: index {int(selected_gpu_index)}"
            + (f" ({selected_gpu_name})" if selected_gpu_name else "")
            + "\n"
        )
    else:
        lines.append("# Selected GPU: none\n")
    for note in cfg.get('notes') or []:
        lines.append(f"# Note: {note}\n")
    lines.append("\n")

    lines.append('RUN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n')
    lines.append('WRAPPER_NAME="$(basename "${BASH_SOURCE[0]}")"\n')
    lines.append(f'DEFAULT_INPUT_FILE="{input_filename}"\n')
    lines.append(f'DEFAULT_LOG_FILE="{log_filename}"\n')
    lines.append('CHAIN_STATE_FILE_DEFAULT="$RUN_DIR/cp2k_chain_state.json"\n')
    lines.append(f'CP2K_BIN="{cp2k_bin}"\n')
    lines.append(f'OMP_NUM_THREADS_DEFAULT="{omp_threads}"\n')
    lines.append(f'MPI_RANKS_DEFAULT="{mpi_ranks}"\n')
    lines.append(f'MPI_LAUNCHER="{mpi_launcher or ""}"\n')
    lines.append(f'MPI_NP_FLAG="{mpi_np_flag}"\n')
    lines.append(f'USE_MPI_DEFAULT="{"1" if use_mpi else "0"}"\n\n')
    lines.append(f'SELECTED_GPU_DEFAULT="{"" if selected_gpu_index is None else int(selected_gpu_index)}"\n\n')

    lines.append("STAGE_ORDER=(")
    for stage in stage_order:
        lines.append(f'"{_bash_double_quote(stage)}" ')
    lines.append(")\n")
    lines.append("\n")

    lines.append('STREAM_OUTPUT="${STREAM_OUTPUT:-}"\n')
    lines.append('MONITOR_MODE="${MONITOR_MODE:-}"\n')
    lines.append('MONITOR_INTERVAL="${MONITOR_INTERVAL:-15}"\n')
    lines.append('MONITOR_TAIL_LINES="${MONITOR_TAIL_LINES:-120}"\n\n')
    lines.append('CP2K_PID=""\n')
    lines.append('TEE_PID=""\n')
    lines.append('STREAM_PIPE_PATH=""\n')
    lines.append('STREAM_PIPE_DIR=""\n')
    lines.append('WRAPPER_SHUTDOWN=0\n')
    lines.append('RUN_ACTIVE=0\n')
    lines.append('WRAPPER_PGID=""\n\n')
    lines.append('INPUT_FILE="$DEFAULT_INPUT_FILE"\n')
    lines.append('LOG_FILE="$DEFAULT_LOG_FILE"\n')
    lines.append('STAGE_LOG_OVERRIDE=""\n')
    lines.append('CHAIN_STATE_FILE="$CHAIN_STATE_FILE_DEFAULT"\n')
    lines.append('AUTO_CHAIN=0\n')
    lines.append('RESUME_CHAIN=0\n')
    lines.append('START_STAGE_REQUEST=""\n')
    lines.append('END_STAGE_REQUEST=""\n')
    lines.append('CHAIN_START_STAGE=""\n')
    lines.append('CHAIN_END_STAGE=""\n')
    lines.append('CURRENT_STAGE_INDEX=-1\n')
    lines.append('CURRENT_STAGE_NAME=""\n')
    lines.append('NEXT_STAGE_NAME=""\n')
    lines.append('CHAIN_MODE_LABEL="single-stage"\n')
    lines.append('CHAIN_GATE_OUTCOME=""\n')
    lines.append('CHAIN_STATUS_TEXT=""\n')
    lines.append('RESUME_LAST_PASS_STAGE=""\n')
    lines.append('LAST_PASS_STAGE=""\n')
    lines.append('NORMAL_TERMINATION=0\n')
    lines.append('GEO_OPT_CONVERGED=0\n')
    lines.append('MD_LAST_STEP=""\n')
    lines.append('MD_EXPECTED_FINAL_STEP=""\n')
    lines.append('COMPLETION_EVIDENCE=""\n')
    lines.append('FATAL_MARKERS_FOUND=()\n')
    lines.append('MISSING_UPSTREAM_ARTIFACTS=()\n')
    lines.append('MISSING_REQUIRED_OUTPUTS=()\n')
    lines.append('STAGE_MANUAL_COMMAND=""\n')
    lines.append('PROGRESS_CURRENT_ABS=""\n')
    lines.append('PROGRESS_RELATIVE=""\n')
    lines.append('PROGRESS_TOTAL=""\n')
    lines.append('PROGRESS_PCT=""\n')
    lines.append('PROGRESS_SCF_ITER=""\n\n')

    lines.append("""format_duration() {
  local total="${1:-0}"
  if [[ ! "$total" =~ ^[0-9]+$ ]]; then
    total=0
  fi
  local hours=$((total / 3600))
  local mins=$(((total % 3600) / 60))
  local secs=$((total % 60))
  printf "%02d:%02d:%02d" "$hours" "$mins" "$secs"
}

format_bytes() {
  local bytes="${1:-0}"
  if [[ ! "$bytes" =~ ^[0-9]+$ ]]; then
    bytes=0
  fi
  awk -v b="$bytes" 'BEGIN {
    split("B KB MB GB TB", u, " ")
    i = 1
    while (b >= 1024 && i < 5) {
      b /= 1024
      i++
    }
    printf "%.1f%s", b, u[i]
  }'
}

short_text() {
  local text="${1:-}"
  text="${text//$'\\r'/ }"
  text="${text//$'\\t'/ }"
  while [[ "$text" == *"  "* ]]; do
    text="${text//  / }"
  done
  text="${text#"${text%%[![:space:]]*}"}"
  text="${text%"${text##*[![:space:]]}"}"
  if ((${#text} > 110)); then
    printf "%s..." "${text:0:107}"
  else
    printf "%s" "$text"
  fi
}

last_meaningful_log_line() {
  local log_file="$1"
  if [[ ! -s "$log_file" ]]; then
    return 0
  fi
  tail -n "$MONITOR_TAIL_LINES" "$log_file" 2>/dev/null | awk '
    {
      line=$0
      sub(/^[[:space:]]+/, "", line)
      sub(/[[:space:]]+$/, "", line)
      if (line == "") {
        next
      }
      last=line
    }
    END {
      if (last != "") {
        print last
      }
    }'
}

resolve_monitor_mode() {
  EFFECTIVE_MONITOR_MODE="${MONITOR_MODE:-}"
  if [[ -z "$EFFECTIVE_MONITOR_MODE" && -n "${STREAM_OUTPUT:-}" ]]; then
    if [[ "$STREAM_OUTPUT" == "1" ]]; then
      EFFECTIVE_MONITOR_MODE="hybrid"
    else
      EFFECTIVE_MONITOR_MODE="monitor"
    fi
  fi
  if [[ -z "$EFFECTIVE_MONITOR_MODE" ]]; then
    EFFECTIVE_MONITOR_MODE="hybrid"
  fi
  if [[ "$EFFECTIVE_MONITOR_MODE" != "hybrid" && "$EFFECTIVE_MONITOR_MODE" != "monitor" && "$EFFECTIVE_MONITOR_MODE" != "stream" ]]; then
    EFFECTIVE_MONITOR_MODE="hybrid"
  fi
  if [[ ! "$MONITOR_INTERVAL" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    MONITOR_INTERVAL="15"
  fi
  if [[ ! "$MONITOR_TAIL_LINES" =~ ^[0-9]+$ ]]; then
    MONITOR_TAIL_LINES="120"
  fi
}

stage_index() {
  local target="${1:-}"
  local idx=0
  local stage=""
  for stage in "${STAGE_ORDER[@]}"; do
    if [[ "$stage" == "$target" ]]; then
      printf "%s" "$idx"
      return 0
    fi
    idx=$((idx + 1))
  done
  return 1
}

resolve_stage_token() {
  local raw="${1:-}"
  local token=""
  local stage=""
  local stem=""
  token="$(basename "$raw")"
  if [[ -z "$token" ]]; then
    return 1
  fi
  for stage in "${STAGE_ORDER[@]}"; do
    stem="${stage%.*}"
    if [[ "$token" == "$stage" || "$token" == "$stem" ]]; then
      printf "%s" "$stage"
      return 0
    fi
  done
  return 1
}

default_log_for_stage() {
  local stage_name="${1:-}"
  case "$stage_name" in
""")
    for stage_file, spec in stage_specs.items():
        lines.append(f'    "{_bash_double_quote(stage_file)}")\n')
        lines.append(f'      printf "%s" "{_bash_double_quote(spec.get("default_log") or (os.path.splitext(stage_file)[0] + ".log"))}"\n')
        lines.append('      return 0\n')
        lines.append('      ;;\n')
    lines.append("""    *)
      ;;
  esac
  return 1
}

next_stage_for() {
  local stage_name="${1:-}"
  local idx=""
  idx="$(stage_index "$stage_name" || true)"
  if [[ "$idx" =~ ^[0-9]+$ ]]; then
    idx=$((idx + 1))
    if ((idx < ${#STAGE_ORDER[@]})); then
      printf "%s" "${STAGE_ORDER[$idx]}"
    fi
  fi
}

parse_input_metadata() {
  STAGE_BASENAME="$(basename "$INPUT_FILE")"
  STAGE_LABEL="${STAGE_BASENAME%.*}"
  PROJECT_NAME="$(awk 'BEGIN { IGNORECASE=1 } $1 == "PROJECT" { print $2; exit }' "$INPUT_FILE" 2>/dev/null || true)"
  RUN_TYPE="$(awk 'BEGIN { IGNORECASE=1 } $1 == "RUN_TYPE" { print toupper($2); exit }' "$INPUT_FILE" 2>/dev/null || true)"
  TRAJECTORY_FORMAT="$(awk '
    BEGIN { IGNORECASE=1; in_traj=0 }
    /^[[:space:]]*&TRAJECTORY([[:space:]]|$)/ { in_traj=1; next }
    /^[[:space:]]*&END[[:space:]]+TRAJECTORY([[:space:]]|$)/ { if (in_traj) exit }
    in_traj && $1 == "FORMAT" { print toupper($2); exit }
  ' "$INPUT_FILE" 2>/dev/null || true)"
  TOTAL_STEPS="$(awk '
    BEGIN { IGNORECASE=1; in_md=0 }
    /^[[:space:]]*&MD([[:space:]]|$)/ { in_md=1; next }
    /^[[:space:]]*&END[[:space:]]+MD([[:space:]]|$)/ { if (in_md) exit }
    in_md && $1 == "STEPS" { print $2; exit }
  ' "$INPUT_FILE" 2>/dev/null || true)"
  STEP_START_VAL="$(awk '
    BEGIN { IGNORECASE=1; in_md=0 }
    /^[[:space:]]*&MD([[:space:]]|$)/ { in_md=1; next }
    /^[[:space:]]*&END[[:space:]]+MD([[:space:]]|$)/ { if (in_md) exit }
    in_md && $1 == "STEP_START_VAL" { print $2; exit }
  ' "$INPUT_FILE" 2>/dev/null || true)"
  TOTAL_ITER="$(awk '
    BEGIN { IGNORECASE=1; in_geo=0 }
    /^[[:space:]]*&GEO_OPT([[:space:]]|$)/ { in_geo=1; next }
    /^[[:space:]]*&END[[:space:]]+GEO_OPT([[:space:]]|$)/ { if (in_geo) exit }
    in_geo && $1 == "MAX_ITER" { print $2; exit }
  ' "$INPUT_FILE" 2>/dev/null || true)"
  HAS_DFT=0
  if grep -Eiq '^[[:space:]]*&DFT([[:space:]]|$)' "$INPUT_FILE" 2>/dev/null; then
    HAS_DFT=1
  fi
  HAS_HF=0
  HF_MAX_MEMORY="$(awk '
    BEGIN { IGNORECASE=1; in_hf=0; in_mem=0 }
    /^[[:space:]]*&HF([[:space:]]|$)/ { in_hf=1; next }
    in_hf && /^[[:space:]]*&END[[:space:]]+HF([[:space:]]|$)/ { exit }
    in_hf && /^[[:space:]]*&MEMORY([[:space:]]|$)/ { in_mem=1; next }
    in_hf && in_mem && /^[[:space:]]*&END[[:space:]]+MEMORY([[:space:]]|$)/ { in_mem=0; next }
    in_hf && in_mem && $1 == "MAX_MEMORY" { print $2; exit }
  ' "$INPUT_FILE" 2>/dev/null || true)"
  if [[ -n "$HF_MAX_MEMORY" ]]; then
    HAS_HF=1
  fi
  if [[ -z "$PROJECT_NAME" ]]; then
    PROJECT_NAME="$STAGE_LABEL"
  fi
  if [[ -z "$STEP_START_VAL" || ! "$STEP_START_VAL" =~ ^[0-9]+$ ]]; then
    STEP_START_VAL=0
  fi
  # ── Inherited step-counter detection ──────────────────────────────
  # When EXT_RESTART sets RESTART_COUNTERS .TRUE., CP2K inherits the
  # MD step counter from the restart file at runtime — it never appears
  # as STEP_START_VAL in the static .inp.  Without correction, progress
  # tracking, ETA, and the completion gate all use a wrong baseline.
  # Fix: parse the predecessor's .ener file (whose last step IS the
  # inherited counter) to recover the effective offset.
  RESTART_COUNTERS_ACTIVE=""
  RESTART_SOURCE_FILE=""
  if [[ "$STEP_START_VAL" == "0" && "$RUN_TYPE" == "MD" ]]; then
    RESTART_COUNTERS_ACTIVE="$(awk '
      BEGIN { IGNORECASE=1; in_ext=0 }
      /^[[:space:]]*&EXT_RESTART([[:space:]]|$)/ { in_ext=1; next }
      /^[[:space:]]*&END[[:space:]]+EXT_RESTART([[:space:]]|$)/ { exit }
      in_ext && $1 == "RESTART_COUNTERS" {
        v = toupper($2)
        gsub(/[.]/, "", v)
        if (v == "TRUE" || v == "T" || v == "1") print "1"
        exit
      }
    ' "$INPUT_FILE" 2>/dev/null || true)"
    if [[ "$RESTART_COUNTERS_ACTIVE" == "1" ]]; then
      RESTART_SOURCE_FILE="$(awk '
        BEGIN { IGNORECASE=1; in_ext=0 }
        /^[[:space:]]*&EXT_RESTART([[:space:]]|$)/ { in_ext=1; next }
        /^[[:space:]]*&END[[:space:]]+EXT_RESTART([[:space:]]|$)/ { exit }
        in_ext && $1 == "RESTART_FILE_NAME" { print $2; exit }
      ' "$INPUT_FILE" 2>/dev/null || true)"
      if [[ -n "$RESTART_SOURCE_FILE" ]]; then
        # Derive predecessor .ener: 20_nvt_mm-1.restart → 20_nvt_mm-1.ener
        _pred_ener="${RESTART_SOURCE_FILE%.restart}.ener"
        if [[ -s "$_pred_ener" ]]; then
          _pred_last="$(parse_last_md_step_from_energy_file "$_pred_ener" || true)"
          if [[ "$_pred_last" =~ ^[0-9]+$ && "$_pred_last" -gt 0 ]]; then
            STEP_START_VAL="$_pred_last"
          fi
        fi
      fi
    fi
  fi
}

load_stage_manifest() {
  REQUIRED_OUTPUTS=()
  UPSTREAM_ARTIFACTS=()
  NEXT_STAGE_NAME=""
  PRE_RELAXATION=0
  case "$STAGE_BASENAME" in
""")
    for stage_file, spec in stage_specs.items():
        lines.append(f'    "{_bash_double_quote(stage_file)}")\n')
        next_stage = str(spec.get('next_stage') or '')
        if next_stage:
            lines.append(f'      NEXT_STAGE_NAME="{_bash_double_quote(next_stage)}"\n')
        if spec.get('pre_relaxation'):
            lines.append('      PRE_RELAXATION=1\n')
        for artifact in spec.get('upstream_artifacts') or []:
            lines.append(f'      UPSTREAM_ARTIFACTS+=("{_bash_double_quote(str(artifact.get("path") or ""))}")\n')
        for artifact in spec.get('required_outputs') or []:
            lines.append(f'      REQUIRED_OUTPUTS+=("{_bash_double_quote(artifact)}")\n')
        lines.append('      ;;\n')
    lines.append("""    *)
      ;;
  esac
}

build_output_patterns() {
  OUTPUT_LABELS=()
  OUTPUT_PATTERNS=()
  if [[ -n "$PROJECT_NAME" ]]; then
    OUTPUT_LABELS+=("restart")
    OUTPUT_PATTERNS+=("$PROJECT_NAME-1.restart")
    if [[ -n "${TRAJECTORY_FORMAT:-}" ]]; then
      OUTPUT_LABELS+=("trajectory")
      case "${TRAJECTORY_FORMAT:-XMOL}" in
        DCD)
          OUTPUT_PATTERNS+=("$PROJECT_NAME-pos-*.dcd")
          ;;
        XMOL)
          OUTPUT_PATTERNS+=("$PROJECT_NAME-pos-*.xyz")
          ;;
        *)
          OUTPUT_PATTERNS+=("$PROJECT_NAME-pos-*")
          ;;
      esac
    fi
    if [[ "$RUN_TYPE" == "MD" ]]; then
      OUTPUT_LABELS+=("cell")
      OUTPUT_PATTERNS+=("$PROJECT_NAME-*.cell*")
      OUTPUT_LABELS+=("energy")
      OUTPUT_PATTERNS+=("$PROJECT_NAME-*.ener*")
      OUTPUT_LABELS+=("restart_history")
      OUTPUT_PATTERNS+=("$PROJECT_NAME-*.restart.bak*")
    fi
    if [[ "$HAS_DFT" == "1" ]]; then
      OUTPUT_LABELS+=("wfn")
      OUTPUT_PATTERNS+=("$PROJECT_NAME-RESTART.wfn")
    fi
  fi
}

print_wrapper_usage() {
  cat <<EOF
Usage:
  ./$WRAPPER_NAME [stage.inp [stage.log]]
  ./$WRAPPER_NAME --auto-chain [--start-stage STAGE] [--end-stage STAGE]
  ./$WRAPPER_NAME --resume [--end-stage STAGE]

Single-stage mode remains backward compatible.
Auto-chain mode walks the canonical stage manifest embedded in this wrapper.
Stage selectors accept either the input filename or its stem.
EOF
}

find_output_file() {
  local pattern="${1:-}"
  local exact="${2:-}"
  local matches=()
  local last_idx=0
  if [[ -n "$exact" && -s "$exact" ]]; then
    printf "%s" "$exact"
    return 0
  fi
  if [[ -z "$pattern" ]]; then
    return 1
  fi
  mapfile -t matches < <(compgen -G "$pattern" 2>/dev/null | LC_ALL=C sort || true)
  if ((${#matches[@]} > 0)); then
    last_idx=$((${#matches[@]} - 1))
    printf "%s" "${matches[$last_idx]}"
    return 0
  fi
  return 1
}

parse_last_md_step_from_energy_file() {
  local ener_file="${1:-}"
  if [[ ! -s "$ener_file" ]]; then
    return 1
  fi
  awk '
    /^[[:space:]]*#/ { next }
    /^[[:space:]]*@/ { next }
    NF > 0 && $1 ~ /^[0-9]+$/ { step=$1 }
    END {
      if (step != "") {
        print step
      }
    }' "$ener_file" 2>/dev/null
}

parse_last_md_step_from_log() {
  local log_file="${1:-}"
  if [[ ! -s "$log_file" ]]; then
    return 1
  fi
  awk '
    /MD\|[[:space:]]*Step[[:space:]]+number|STEP[[:space:]]+NUMBER|[Ss]tep[[:space:]]*=|[Ii]nformations?[[:space:]]+at[[:space:]]+step/ {
      line=$0
      gsub(/[^0-9]+/, " ", line)
      n=split(line, parts, /[[:space:]]+/)
      for (i=n; i>=1; i--) {
        if (parts[i] ~ /^[0-9]+$/) {
          step=parts[i]
          break
        }
      }
    }
    END {
      if (step != "") {
        print step
      }
    }' "$log_file" 2>/dev/null
}

collect_fatal_markers() {
  FATAL_MARKERS_FOUND=()
  if [[ -s "$LOG_FILE" ]]; then
    mapfile -t FATAL_MARKERS_FOUND < <(grep -En 'ABORT|CPASSERT' "$LOG_FILE" 2>/dev/null | tail -n 5 || true)
  fi
}

collect_missing_upstream_artifacts() {
  MISSING_UPSTREAM_ARTIFACTS=()
  local path=""
  for path in "${UPSTREAM_ARTIFACTS[@]}"; do
    if [[ ! -s "$path" ]]; then
      MISSING_UPSTREAM_ARTIFACTS+=("$path")
    fi
  done
}

collect_missing_required_outputs() {
  MISSING_REQUIRED_OUTPUTS=()
  local path=""
  for path in "${REQUIRED_OUTPUTS[@]}"; do
    if [[ ! -s "$path" ]]; then
      MISSING_REQUIRED_OUTPUTS+=("$path")
    fi
  done
}

detect_normal_termination() {
  if [[ -s "$LOG_FILE" ]] && grep -Eq 'PROGRAM ENDED AT' "$LOG_FILE" 2>/dev/null; then
    NORMAL_TERMINATION=1
  else
    NORMAL_TERMINATION=0
  fi
}

detect_geo_opt_convergence() {
  GEO_OPT_CONVERGED=0
  if [[ ! -s "$LOG_FILE" ]]; then
    return 1
  fi
  if grep -Eiq 'GEOMETRY OPTIMIZATION COMPLETED|OPTIMIZATION COMPLETED|GEOMETRY OPTIMIZATION CONVERGED' "$LOG_FILE" 2>/dev/null; then
    GEO_OPT_CONVERGED=1
    return 0
  fi
  return 1
}

update_stage_manual_command() {
  STAGE_MANUAL_COMMAND="./$WRAPPER_NAME $CURRENT_STAGE_NAME $LOG_FILE"
}

set_stage_context() {
  local requested_stage="${1:-}"
  local resolved_stage=""
  resolved_stage="$(resolve_stage_token "$requested_stage" || true)"
  if [[ -z "$resolved_stage" ]]; then
    echo "ERROR: Unknown stage '$requested_stage'." >&2
    return 1
  fi
  CURRENT_STAGE_NAME="$resolved_stage"
  INPUT_FILE="$CURRENT_STAGE_NAME"
  if [[ -n "$STAGE_LOG_OVERRIDE" ]]; then
    LOG_FILE="$STAGE_LOG_OVERRIDE"
  else
    LOG_FILE="$(default_log_for_stage "$CURRENT_STAGE_NAME" || printf "%s.log" "${CURRENT_STAGE_NAME%.*}")"
  fi
  CURRENT_STAGE_INDEX="$(stage_index "$CURRENT_STAGE_NAME" || echo -1)"
  STAGE_BASENAME="$(basename "$INPUT_FILE")"
  STAGE_LABEL="${STAGE_BASENAME%.*}"
  load_stage_manifest
  parse_input_metadata
  build_output_patterns
  if [[ -z "$NEXT_STAGE_NAME" ]]; then
    NEXT_STAGE_NAME="$(next_stage_for "$CURRENT_STAGE_NAME" || true)"
  fi
  update_stage_manual_command
  return 0
}

preflight_stage() {
  collect_missing_upstream_artifacts
  if [[ ! -s "$INPUT_FILE" ]]; then
    echo "ERROR: Input file not found or empty: $INPUT_FILE" >&2
    return 2
  fi
  if ((${#MISSING_UPSTREAM_ARTIFACTS[@]} > 0)); then
    echo "ERROR: Preflight failed for $CURRENT_STAGE_NAME; required upstream artifacts are missing or empty." >&2
    local path=""
    for path in "${MISSING_UPSTREAM_ARTIFACTS[@]}"; do
      echo "  missing upstream: $path" >&2
    done
    return 6
  fi
  return 0
}

classify_stage_outcome() {
  local cp2k_exit="${1:-1}"
  local ener_file=""
  local last_step=""
  local expected_step=""

  CHAIN_GATE_OUTCOME="PASS"
  CHAIN_STATUS_TEXT="completion checks satisfied"
  NORMAL_TERMINATION=0
  GEO_OPT_CONVERGED=0
  MD_LAST_STEP=""
  MD_EXPECTED_FINAL_STEP=""
  COMPLETION_EVIDENCE=""
  collect_fatal_markers
  collect_missing_required_outputs
  detect_normal_termination

  if [[ "$cp2k_exit" != "0" ]]; then
    CHAIN_GATE_OUTCOME="FAIL"
    CHAIN_STATUS_TEXT="CP2K exited with code $cp2k_exit"
    COMPLETION_EVIDENCE="cp2k_exit=$cp2k_exit"
    return 0
  fi

  if ((${#FATAL_MARKERS_FOUND[@]} > 0)); then
    CHAIN_GATE_OUTCOME="FAIL"
    CHAIN_STATUS_TEXT="fatal markers detected in log"
    COMPLETION_EVIDENCE="fatal markers: ${FATAL_MARKERS_FOUND[0]}"
    return 0
  fi

  if [[ "$NORMAL_TERMINATION" != "1" ]]; then
    CHAIN_GATE_OUTCOME="REVIEW"
    CHAIN_STATUS_TEXT="normal termination marker not found"
    COMPLETION_EVIDENCE="PROGRAM ENDED AT marker not found"
    return 0
  fi

  if [[ "$RUN_TYPE" == "MD" ]]; then
    expected_step=""
    if [[ "${TOTAL_STEPS:-}" =~ ^[0-9]+$ ]]; then
      expected_step=$((TOTAL_STEPS + STEP_START_VAL))
      MD_EXPECTED_FINAL_STEP="$expected_step"
    fi
    ener_file="$(find_output_file "$PROJECT_NAME-*.ener*" "$PROJECT_NAME-1.ener" || true)"
    if [[ -n "$ener_file" ]]; then
      last_step="$(parse_last_md_step_from_energy_file "$ener_file" || true)"
      if [[ -n "$last_step" ]]; then
        MD_LAST_STEP="$last_step"
        COMPLETION_EVIDENCE=".ener last_step=$last_step"
      fi
    fi
    if [[ -z "$MD_LAST_STEP" ]]; then
      last_step="$(parse_last_md_step_from_log "$LOG_FILE" || true)"
      if [[ -n "$last_step" ]]; then
        MD_LAST_STEP="$last_step"
        COMPLETION_EVIDENCE="log last_step=$last_step"
      fi
    fi
    if [[ -z "$MD_LAST_STEP" || -z "$MD_EXPECTED_FINAL_STEP" ]]; then
      CHAIN_GATE_OUTCOME="REVIEW"
      CHAIN_STATUS_TEXT="unable to verify MD completion analytically"
      if [[ -z "$COMPLETION_EVIDENCE" ]]; then
        COMPLETION_EVIDENCE="MD completion evidence unavailable"
      fi
      return 0
    fi
    if ((MD_LAST_STEP < MD_EXPECTED_FINAL_STEP)); then
      CHAIN_GATE_OUTCOME="REVIEW"
      CHAIN_STATUS_TEXT="MD stage terminated before the intended final step"
      COMPLETION_EVIDENCE="$COMPLETION_EVIDENCE expected=$MD_EXPECTED_FINAL_STEP"
      return 0
    fi
    COMPLETION_EVIDENCE="$COMPLETION_EVIDENCE expected=$MD_EXPECTED_FINAL_STEP"
  elif [[ "$RUN_TYPE" == "GEO_OPT" ]]; then
    if detect_geo_opt_convergence; then
      COMPLETION_EVIDENCE="explicit geometry-optimization convergence marker found"
    elif [[ "${PRE_RELAXATION:-0}" == "1" ]]; then
      # ── Pre-relaxation gate: accept clean MAX_ITER exhaustion ────────
      # This stage is a preparatory energy minimization whose purpose is
      # bad-contact removal, not strict stationary-point convergence.
      # For large solvated biomolecular boxes (>10^5 atoms), the single
      # worst-atom criteria (MAX_FORCE, MAX_DR) are dominated by outlier
      # solvent molecules rather than meaningful structural defects, so
      # GEO_OPT routinely exhausts MAX_ITER without converging.  CP2K
      # terminates normally in this case (exit code 0, PROGRAM ENDED AT
      # marker present) and writes a valid restart file.
      #
      # Downstream MD equilibration (NVT → NPT) heals any residual
      # strain through thermal sampling at kT >> residual forces.
      # Genuinely broken systems (bad topology, atom overlap, SCF
      # divergence) are caught upstream: non-zero exit code → FAIL,
      # fatal markers → FAIL, no normal termination → REVIEW.
      #
      # Ref: CP2K QM/MM Tutorial (chorismate mutase) — 1000-step capped
      #      minimization before MD equilibration is standard protocol;
      #      Senn & Thiel, Angew. Chem. Int. Ed. 48, 1198 (2009) — MM
      #      equilibration precedes QM/MM production in staged workflows.
      if [[ -s "${PROJECT_NAME}-1.restart" ]]; then
        CHAIN_GATE_OUTCOME="PASS"
        CHAIN_STATUS_TEXT="pre-relaxation completed (MAX_ITER reached; convergence not required for this stage)"
        COMPLETION_EVIDENCE="pre-relaxation: normal termination + restart checkpoint present"
      else
        CHAIN_GATE_OUTCOME="REVIEW"
        CHAIN_STATUS_TEXT="pre-relaxation finished but restart checkpoint missing"
        COMPLETION_EVIDENCE="pre-relaxation: normal termination without restart file"
      fi
    else
      CHAIN_GATE_OUTCOME="REVIEW"
      CHAIN_STATUS_TEXT="geometry optimization convergence marker not found"
      COMPLETION_EVIDENCE="GEO_OPT convergence marker not found"
      return 0
    fi
  else
    COMPLETION_EVIDENCE="normal termination marker found"
  fi

  if ((${#MISSING_REQUIRED_OUTPUTS[@]} > 0)); then
    CHAIN_GATE_OUTCOME="REVIEW"
    CHAIN_STATUS_TEXT="downstream-required artifacts are missing or empty"
  fi
}

ensure_chain_state_support() {
  if [[ "$AUTO_CHAIN" == "1" || "$RESUME_CHAIN" == "1" ]]; then
    if ! command -v python3 >/dev/null 2>&1; then
      echo "ERROR: python3 is required for --auto-chain/--resume state persistence." >&2
      exit 5
    fi
  fi
}

write_chain_state_json() {
  if [[ "$AUTO_CHAIN" != "1" ]]; then
    return 0
  fi
  if ! command -v python3 >/dev/null 2>&1; then
    return 0
  fi
  local state_phase="${1:-stage}"
  local state_exit="${2:-}"
  local state_next="${3:-$NEXT_STAGE_NAME}"
  local missing_upstream_text=""
  local missing_required_text=""
  local fatal_markers_text=""
  missing_upstream_text="$(printf '%s\n' "${MISSING_UPSTREAM_ARTIFACTS[@]}")"
  missing_required_text="$(printf '%s\n' "${MISSING_REQUIRED_OUTPUTS[@]}")"
  fatal_markers_text="$(printf '%s\n' "${FATAL_MARKERS_FOUND[@]}")"
  export STATE_FILE="$CHAIN_STATE_FILE"
  export STATE_PHASE="$state_phase"
  export STATE_EXIT="$state_exit"
  export STATE_STAGE="$CURRENT_STAGE_NAME"
  export STATE_CURRENT_STAGE="$CURRENT_STAGE_NAME"
  export STATE_NEXT_STAGE="$state_next"
  export STATE_LAST_PASS="$LAST_PASS_STAGE"
  export STATE_CHAIN_STATUS="$CHAIN_STATUS_TEXT"
  export STATE_GATE="$CHAIN_GATE_OUTCOME"
  export STATE_MANUAL_COMMAND="$STAGE_MANUAL_COMMAND"
  export STATE_COMPLETION_EVIDENCE="$COMPLETION_EVIDENCE"
  export STATE_MISSING_UPSTREAM="$missing_upstream_text"
  export STATE_MISSING_REQUIRED="$missing_required_text"
  export STATE_FATAL_MARKERS="$fatal_markers_text"
  export STATE_STAGE_ORDER="$(printf '%s\n' "${STAGE_ORDER[@]}")"
  export STATE_START_STAGE="$CHAIN_START_STAGE"
  export STATE_END_STAGE="$CHAIN_END_STAGE"
  export STATE_WRAPPER="$WRAPPER_NAME"
  export STATE_RUN_DIR="$RUN_DIR"
  export STATE_MODE="$CHAIN_MODE_LABEL"
  export STATE_NORMAL_TERMINATION="$NORMAL_TERMINATION"
  export STATE_GEO_OPT_CONVERGED="$GEO_OPT_CONVERGED"
  export STATE_PRE_RELAXATION="${PRE_RELAXATION:-0}"
  export STATE_MD_LAST_STEP="$MD_LAST_STEP"
  export STATE_MD_EXPECTED_FINAL_STEP="$MD_EXPECTED_FINAL_STEP"
  python3 - <<'PY'
import json
import os
import time

path = os.environ["STATE_FILE"]
state = {}
if os.path.exists(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    except Exception:
        state = {}

state["version"] = 1
state["wrapper"] = os.environ.get("STATE_WRAPPER", "")
state["run_dir"] = os.environ.get("STATE_RUN_DIR", "")
state["mode"] = os.environ.get("STATE_MODE", "")
state["phase"] = os.environ.get("STATE_PHASE", "")
state["stage_order"] = [x for x in os.environ.get("STATE_STAGE_ORDER", "").splitlines() if x]
state["start_stage"] = os.environ.get("STATE_START_STAGE", "")
state["end_stage"] = os.environ.get("STATE_END_STAGE", "")
state["current_stage"] = os.environ.get("STATE_CURRENT_STAGE", "")
state["next_stage"] = os.environ.get("STATE_NEXT_STAGE", "")
state["last_pass_stage"] = os.environ.get("STATE_LAST_PASS", "")
state["chain_status"] = os.environ.get("STATE_CHAIN_STATUS", "")
state["updated_at_epoch"] = int(time.time())
state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(state["updated_at_epoch"]))

stages = state.setdefault("stages", {})
stage_name = os.environ.get("STATE_STAGE", "")
if stage_name:
    stages[stage_name] = {
        "gate": os.environ.get("STATE_GATE", ""),
        "phase": os.environ.get("STATE_PHASE", ""),
        "exit_code": os.environ.get("STATE_EXIT", ""),
        "manual_command": os.environ.get("STATE_MANUAL_COMMAND", ""),
        "completion_evidence": os.environ.get("STATE_COMPLETION_EVIDENCE", ""),
        "missing_upstream": [x for x in os.environ.get("STATE_MISSING_UPSTREAM", "").splitlines() if x],
        "missing_required_outputs": [x for x in os.environ.get("STATE_MISSING_REQUIRED", "").splitlines() if x],
        "fatal_markers": [x for x in os.environ.get("STATE_FATAL_MARKERS", "").splitlines() if x],
        "normal_termination": os.environ.get("STATE_NORMAL_TERMINATION", "0") == "1",
        "geo_opt_converged": os.environ.get("STATE_GEO_OPT_CONVERGED", "0") == "1",
        "pre_relaxation": os.environ.get("STATE_PRE_RELAXATION", "0") == "1",
        "md_last_step": os.environ.get("STATE_MD_LAST_STEP", ""),
        "md_expected_final_step": os.environ.get("STATE_MD_EXPECTED_FINAL_STEP", ""),
    }

with open(path, "w", encoding="utf-8") as fh:
    json.dump(state, fh, indent=2, sort_keys=True)
    fh.write("\\n")
PY
}

load_resume_state() {
  if [[ ! -s "$CHAIN_STATE_FILE" ]]; then
    echo "ERROR: Resume requested but state file is missing: $CHAIN_STATE_FILE" >&2
    exit 5
  fi
  mapfile -t _resume_state_fields < <(
    STATE_FILE="$CHAIN_STATE_FILE" python3 - <<'PY'
import json
import os

with open(os.environ["STATE_FILE"], "r", encoding="utf-8") as fh:
    state = json.load(fh)

for key in ("last_pass_stage", "current_stage", "next_stage", "chain_status", "start_stage", "end_stage"):
    value = state.get(key, "")
    if value is None:
        value = ""
    print(str(value))
PY
  )
  RESUME_LAST_PASS_STAGE="${_resume_state_fields[0]:-}"
  RESUME_CURRENT_STAGE="${_resume_state_fields[1]:-}"
  RESUME_NEXT_STAGE="${_resume_state_fields[2]:-}"
  RESUME_CHAIN_STATUS="${_resume_state_fields[3]:-}"
  RESUME_START_STAGE="${_resume_state_fields[4]:-}"
  RESUME_END_STAGE="${_resume_state_fields[5]:-}"
}

resolve_chain_window() {
  local start_stage=""
  local end_stage=""
  local last_index=0
  local start_idx=0
  local end_idx=0

  if ((${#STAGE_ORDER[@]} == 0)); then
    echo "ERROR: No stage manifest embedded in wrapper." >&2
    exit 2
  fi

  last_index=$((${#STAGE_ORDER[@]} - 1))
  start_stage="${STAGE_ORDER[0]}"
  end_stage="${STAGE_ORDER[$last_index]}"

  if [[ -n "$START_STAGE_REQUEST" ]]; then
    start_stage="$(resolve_stage_token "$START_STAGE_REQUEST" || true)"
    if [[ -z "$start_stage" ]]; then
      echo "ERROR: Unknown --start-stage '$START_STAGE_REQUEST'." >&2
      exit 2
    fi
  fi
  if [[ -n "$END_STAGE_REQUEST" ]]; then
    end_stage="$(resolve_stage_token "$END_STAGE_REQUEST" || true)"
    if [[ -z "$end_stage" ]]; then
      echo "ERROR: Unknown --end-stage '$END_STAGE_REQUEST'." >&2
      exit 2
    fi
  fi

  if [[ "$RESUME_CHAIN" == "1" ]]; then
    load_resume_state
    if [[ -n "$RESUME_LAST_PASS_STAGE" ]]; then
      start_stage="$(next_stage_for "$RESUME_LAST_PASS_STAGE" || true)"
      if [[ -z "$start_stage" ]]; then
        echo "Resume state indicates the last PASS was the final stage; nothing left to run." >&2
        exit 0
      fi
    elif [[ -n "$RESUME_START_STAGE" && -z "$START_STAGE_REQUEST" ]]; then
      start_stage="$(resolve_stage_token "$RESUME_START_STAGE" || true)"
    fi
    if [[ -n "$RESUME_END_STAGE" && -z "$END_STAGE_REQUEST" ]]; then
      end_stage="$(resolve_stage_token "$RESUME_END_STAGE" || true)"
    fi
  fi

  start_idx="$(stage_index "$start_stage" || echo -1)"
  end_idx="$(stage_index "$end_stage" || echo -1)"
  if ((start_idx < 0 || end_idx < 0 || start_idx > end_idx)); then
    echo "ERROR: Invalid stage window: start=$start_stage end=$end_stage" >&2
    exit 2
  fi

  CHAIN_START_STAGE="$start_stage"
  CHAIN_END_STAGE="$end_stage"
}

count_required_outputs() {
  local found=0
  local path=""
  for path in "${REQUIRED_OUTPUTS[@]}"; do
    if [[ -s "$path" ]]; then
      found=$((found + 1))
    fi
  done
  printf "%s/%s" "$found" "${#REQUIRED_OUTPUTS[@]}"
}

count_observed_outputs() {
  local found=0
  local pattern=""
  for pattern in "${OUTPUT_PATTERNS[@]}"; do
    if compgen -G "$pattern" >/dev/null 2>&1; then
      found=$((found + 1))
    fi
  done
  printf "%s/%s" "$found" "${#OUTPUT_PATTERNS[@]}"
}

detect_checkpoint() {
  if [[ -n "$PROJECT_NAME" ]]; then
    if [[ -s "$PROJECT_NAME-1.restart" ]]; then
      printf "ckpt=yes"
      return 0
    fi
    if find_output_file "$PROJECT_NAME-*.restart" "" >/dev/null 2>&1; then
      printf "ckpt=yes"
      return 0
    fi
  fi
}

infer_progress() {
  local tail_text=""
  local current=""
  local total=""
  local label=""
  local pct=""
  local eta_s=0
  local scf_iter=""
  local line=""
  tail_text="$(tail -n "$MONITOR_TAIL_LINES" "$LOG_FILE" 2>/dev/null || true)"
  if [[ -z "$tail_text" ]]; then
    return 0
  fi

  while IFS= read -r line; do
    if [[ "$RUN_TYPE" == "MD" ]]; then
      if [[ "$line" =~ MD\|[[:space:]]*Step[[:space:]]+number[[:space:]]*([0-9]+) ]]; then
        current="${BASH_REMATCH[1]}"
      elif [[ "$line" =~ STEP[[:space:]]+NUMBER[[:space:]:=]*([0-9]+) ]]; then
        current="${BASH_REMATCH[1]}"
      elif [[ "$line" =~ [Ss]tep[[:space:]]*=[[:space:]]*([0-9]+) ]]; then
        current="${BASH_REMATCH[1]}"
      elif [[ "$line" =~ [Ii]nformations?[[:space:]]+at[[:space:]]+step[[:space:]]*=?[[:space:]]*([0-9]+) ]]; then
        current="${BASH_REMATCH[1]}"
      fi
    elif [[ "$RUN_TYPE" == "GEO_OPT" ]]; then
      if [[ "$line" =~ (OPTIMIZATION[[:space:]]+STEP|Optimization[[:space:]]+step)[^0-9]*([0-9]+) ]]; then
        current="${BASH_REMATCH[2]}"
      elif [[ "$line" =~ GEO_OPT\|[[:space:]]*Step[[:space:]]+number[[:space:]]*([0-9]+) ]]; then
        current="${BASH_REMATCH[1]}"
      elif [[ "$line" =~ [Ii]nformations?[[:space:]]+at[[:space:]]+step[[:space:]]*=?[[:space:]]*([0-9]+) ]]; then
        current="${BASH_REMATCH[1]}"
      fi
    fi

    if [[ "$line" =~ ([Oo]uter[[:space:]]+[Ss][Cc][Ff][[:space:]]+loop[[:space:]]+converged[[:space:]]+in|[Ss][Cc][Ff][[:space:]]+run[[:space:]]+converged[[:space:]]+in)[^0-9]*([0-9]+) ]]; then
      scf_iter="${BASH_REMATCH[2]}"
    elif [[ "$line" =~ [Ss][Cc][Ff][[:space:]]+ITERATION[[:space:]]+([0-9]+) ]]; then
      scf_iter="${BASH_REMATCH[1]}"
    fi
  done <<< "$tail_text"

  if [[ "$RUN_TYPE" == "MD" ]]; then
    total="$TOTAL_STEPS"
    label="step"
  elif [[ "$RUN_TYPE" == "GEO_OPT" ]]; then
    total="$TOTAL_ITER"
    label="iter"
  fi

  # ── Offset-corrected progress arithmetic ────────────────────────
  # When RESTART_COUNTERS inherits a step counter from a predecessor,
  # STEP_START_VAL holds the offset (e.g. 5000 from NVT).  The
  # absolute step counter in the log (e.g. 12896) must be converted
  # to relative progress: relative = absolute - offset.  TOTAL_STEPS
  # is already the number of steps to run (not the final step number).
  if [[ -n "$current" ]]; then
    if [[ -n "$total" && "$current" =~ ^[0-9]+$ && "$total" =~ ^[0-9]+$ && "$total" -gt 0 ]]; then
      local offset="${STEP_START_VAL:-0}"
      local relative=$((current - offset))
      if ((relative < 0)); then
        relative=0
      fi
      pct="$(awk -v r="$relative" -v t="$total" 'BEGIN { printf "%.1f", (100.0 * r) / t }')"
      if ((relative > 0 && relative < total)) && [[ "$ELAPSED_SECONDS" =~ ^[0-9]+$ ]] && ((ELAPSED_SECONDS > 0)); then
        eta_s=$(( (ELAPSED_SECONDS * (total - relative)) / relative ))
        printf "%s=%s/%s (%s%%, eta %s)" "$label" "$relative" "$total" "$pct" "$(format_duration "$eta_s")"
      else
        printf "%s=%s/%s (%s%%)" "$label" "$relative" "$total" "$pct"
      fi
    else
      printf "%s=%s" "$label" "$current"
    fi
    # Export for the status display to use
    PROGRESS_CURRENT_ABS="$current"
    PROGRESS_RELATIVE="${relative:-$current}"
    PROGRESS_TOTAL="${total:-}"
    PROGRESS_PCT="${pct:-}"
    return 0
  fi

  if [[ -n "$scf_iter" ]]; then
    printf "scf=%s" "$scf_iter"
    PROGRESS_SCF_ITER="$scf_iter"
  fi
}

# ── btop-inspired monitor display helpers ─────────────────────────────
# Compact boxed status line with Unicode progress bar, ETA, and
# throughput metrics.  Designed for 80-column terminals; inner content
# width is 74 characters, total box width 78.
#
# Layout (3 content lines):
#   ╭─ header ────────────────────────────────────────────────────────────╮
#   │  stage  type  ● status  elapsed                                    │
#   │  ████████████████░░░░ pct%  rel/total  eta HH:MM:SS  Xs/step      │
#   │  log size  ckpt ✓  req N/M  out N/M                               │
#   ╰────────────────────────────────────────────────────────────────────╯

render_progress_bar() {
  # Render a fixed-width bar of filled (█) and empty (░) segments.
  # $1: percentage (0-100+), $2: bar width in characters (default 20).
  local pct_num="${1:-0}"
  local width="${2:-20}"
  local filled=0 empty=0 i=0 bar=""
  filled=$(awk -v p="$pct_num" -v w="$width" 'BEGIN {
    f = int(p * w / 100 + 0.5)
    if (f > w) f = w
    if (f < 0) f = 0
    print f
  }')
  empty=$((width - filled))
  for ((i = 0; i < filled; i++)); do bar+="█"; done
  for ((i = 0; i < empty; i++)); do bar+="░"; done
  printf "%s" "$bar"
}

_pad_right() {
  # Pad $1 with trailing spaces to reach visible width $2.
  # Uses ${#text} which counts code points — correct for the single-
  # width Unicode characters used in this display (box-drawing, block
  # elements, geometric shapes).  CJK double-width characters are not
  # used and do not need wcwidth() handling.
  local text="$1"
  local target="$2"
  local vlen=${#text}
  local pad=$((target - vlen))
  if ((pad > 0)); then
    printf "%s%*s" "$text" "$pad" ""
  else
    printf "%s" "$text"
  fi
}

update_progress_data() {
  # Parse the most recent MD/GEO_OPT step from the log tail and compute
  # offset-corrected progress metrics.  Sets PROGRESS_* globals for use
  # by emit_status_line() — called directly (not in a subshell) so the
  # variable assignments persist in the caller's scope.
  PROGRESS_CURRENT_ABS=""
  PROGRESS_RELATIVE=""
  PROGRESS_TOTAL=""
  PROGRESS_PCT=""
  PROGRESS_ETA_S=""
  PROGRESS_RATE=""
  PROGRESS_SCF_ITER=""
  PROGRESS_LABEL=""

  local tail_text=""
  local current=""
  local scf_iter=""
  local line=""
  tail_text="$(tail -n "$MONITOR_TAIL_LINES" "$LOG_FILE" 2>/dev/null || true)"
  if [[ -z "$tail_text" ]]; then
    return 0
  fi

  while IFS= read -r line; do
    if [[ "$RUN_TYPE" == "MD" ]]; then
      if [[ "$line" =~ MD\|[[:space:]]*Step[[:space:]]+number[[:space:]]*([0-9]+) ]]; then
        current="${BASH_REMATCH[1]}"
      elif [[ "$line" =~ STEP[[:space:]]+NUMBER[[:space:]:=]*([0-9]+) ]]; then
        current="${BASH_REMATCH[1]}"
      elif [[ "$line" =~ [Ss]tep[[:space:]]*=[[:space:]]*([0-9]+) ]]; then
        current="${BASH_REMATCH[1]}"
      elif [[ "$line" =~ [Ii]nformations?[[:space:]]+at[[:space:]]+step[[:space:]]*=?[[:space:]]*([0-9]+) ]]; then
        current="${BASH_REMATCH[1]}"
      fi
    elif [[ "$RUN_TYPE" == "GEO_OPT" ]]; then
      if [[ "$line" =~ (OPTIMIZATION[[:space:]]+STEP|Optimization[[:space:]]+step)[^0-9]*([0-9]+) ]]; then
        current="${BASH_REMATCH[2]}"
      elif [[ "$line" =~ GEO_OPT\|[[:space:]]*Step[[:space:]]+number[[:space:]]*([0-9]+) ]]; then
        current="${BASH_REMATCH[1]}"
      elif [[ "$line" =~ [Ii]nformations?[[:space:]]+at[[:space:]]+step[[:space:]]*=?[[:space:]]*([0-9]+) ]]; then
        current="${BASH_REMATCH[1]}"
      fi
    fi
    if [[ "$line" =~ ([Oo]uter[[:space:]]+[Ss][Cc][Ff][[:space:]]+loop[[:space:]]+converged[[:space:]]+in|[Ss][Cc][Ff][[:space:]]+run[[:space:]]+converged[[:space:]]+in)[^0-9]*([0-9]+) ]]; then
      scf_iter="${BASH_REMATCH[2]}"
    elif [[ "$line" =~ [Ss][Cc][Ff][[:space:]]+ITERATION[[:space:]]+([0-9]+) ]]; then
      scf_iter="${BASH_REMATCH[1]}"
    fi
  done <<< "$tail_text"

  local total=""
  if [[ "$RUN_TYPE" == "MD" ]]; then
    total="$TOTAL_STEPS"
    PROGRESS_LABEL="step"
  elif [[ "$RUN_TYPE" == "GEO_OPT" ]]; then
    total="$TOTAL_ITER"
    PROGRESS_LABEL="iter"
  fi

  if [[ -n "$current" && -n "$total" && "$current" =~ ^[0-9]+$ && "$total" =~ ^[0-9]+$ && "$total" -gt 0 ]]; then
    local offset="${STEP_START_VAL:-0}"
    local relative=$((current - offset))
    if ((relative < 0)); then relative=0; fi
    PROGRESS_CURRENT_ABS="$current"
    PROGRESS_RELATIVE="$relative"
    PROGRESS_TOTAL="$total"
    PROGRESS_PCT="$(awk -v r="$relative" -v t="$total" 'BEGIN { printf "%.1f", (100.0 * r) / t }')"
    if ((relative > 0 && ELAPSED_SECONDS > 0)); then
      PROGRESS_ETA_S=$(( (ELAPSED_SECONDS * (total - relative)) / relative ))
      PROGRESS_RATE="$(awk -v e="$ELAPSED_SECONDS" -v r="$relative" 'BEGIN { printf "%.1f", e / r }')"
    fi
  elif [[ -n "$current" ]]; then
    PROGRESS_CURRENT_ABS="$current"
    PROGRESS_RELATIVE="$current"
  fi

  if [[ -n "$scf_iter" ]]; then
    PROGRESS_SCF_ITER="$scf_iter"
  fi
}

emit_status_line() {
  local status="$1"
  local now=0 log_size=0 log_delta=0

  # ── Gather timing ──
  now="$(date +%s 2>/dev/null || echo 0)"
  if [[ "$now" =~ ^[0-9]+$ && "$START_EPOCH" =~ ^[0-9]+$ ]]; then
    ELAPSED_SECONDS=$((now - START_EPOCH))
  else
    ELAPSED_SECONDS=0
  fi

  # ── Log metrics ──
  log_size="$(wc -c <"$LOG_FILE" 2>/dev/null || echo 0)"
  log_size="${log_size//[[:space:]]/}"
  if [[ ! "$log_size" =~ ^[0-9]+$ ]]; then log_size=0; fi
  log_delta=$((log_size - PREV_LOG_SIZE))
  if ((log_delta < 0)); then log_delta=0; fi
  PREV_LOG_SIZE="$log_size"

  local last_line=""
  last_line="$(last_meaningful_log_line "$LOG_FILE")"
  if [[ -n "$last_line" ]]; then
    LAST_MEANINGFUL_LINE="$last_line"
  fi

  # ── Progress data (sets PROGRESS_* globals in-scope) ──
  update_progress_data

  # ── Status indicator ──
  local indicator=""
  case "$status" in
    running)  indicator="● run" ;;
    finished) indicator="✓ done" ;;
    review)   indicator="⚠ review" ;;
    failed)   indicator="✗ fail" ;;
    *)        indicator="… $status" ;;
  esac

  # ── Build content lines ──
  local W=74  # inner width; total box = 78 cols (fits 80-col terminals)

  # Header: stage, run type, status, elapsed
  local hdr="$STAGE_LABEL  $RUN_TYPE  $indicator  $(format_duration "$ELAPSED_SECONDS")"

  # Progress line: bar + percentage + steps + ETA + rate
  local prog=""
  if [[ -n "$PROGRESS_PCT" && -n "$PROGRESS_TOTAL" ]]; then
    local bar=""
    bar="$(render_progress_bar "$PROGRESS_PCT" 20)"
    prog="$bar ${PROGRESS_PCT}%  ${PROGRESS_RELATIVE}/${PROGRESS_TOTAL}"
    if [[ -n "$PROGRESS_ETA_S" && "$PROGRESS_ETA_S" =~ ^[0-9]+$ ]] && ((PROGRESS_ETA_S >= 0)); then
      prog="$prog  eta $(format_duration "$PROGRESS_ETA_S")"
    fi
    if [[ -n "$PROGRESS_RATE" ]]; then
      prog="$prog  ${PROGRESS_RATE}s/${PROGRESS_LABEL:-step}"
    fi
  elif [[ -n "$PROGRESS_CURRENT_ABS" ]]; then
    prog="${PROGRESS_LABEL:-step} ${PROGRESS_CURRENT_ABS}"
    if [[ -n "$PROGRESS_SCF_ITER" ]]; then
      prog="$prog  scf=$PROGRESS_SCF_ITER"
    fi
  elif [[ -n "$PROGRESS_SCF_ITER" ]]; then
    prog="scf iter $PROGRESS_SCF_ITER"
  else
    prog="awaiting first output"
  fi

  # Detail line: log, checkpoint, outputs
  local det="log $(format_bytes "$log_size")"
  if ((log_delta > 0)); then
    det="$det (+$(format_bytes "$log_delta"))"
  fi
  local ckpt=""
  ckpt="$(detect_checkpoint)"
  if [[ -n "$ckpt" ]]; then
    det="$det  ckpt ✓"
  fi
  if ((${#REQUIRED_OUTPUTS[@]} > 0)); then
    det="$det  req $(count_required_outputs)"
  fi
  if ((${#OUTPUT_PATTERNS[@]} > 0)); then
    det="$det  out $(count_observed_outputs)"
  fi

  # ── Render box ──
  local border_fill=""
  printf -v border_fill '%*s' "$W" ''
  border_fill="${border_fill// /─}"
  {
    printf "\n╭─%s─╮\n" "$border_fill"
    printf "│ %s │\n" "$(_pad_right "$hdr" "$W")"
    printf "│ %s │\n" "$(_pad_right "$prog" "$W")"
    printf "│ %s │\n" "$(_pad_right "$det" "$W")"
    printf "╰─%s─╯\n" "$border_fill"
  } >&2
}

print_output_summary() {
  local path=""
  local idx=0
  local label=""
  local pattern=""
  local matches=()

  echo "Required outputs:"
  if ((${#REQUIRED_OUTPUTS[@]} == 0)); then
    echo "  [none]"
  else
    for path in "${REQUIRED_OUTPUTS[@]}"; do
      if [[ -s "$path" ]]; then
        echo "  [ok] $path"
      else
        echo "  [missing] $path"
      fi
    done
  fi

  echo "Detected outputs:"
  if ((${#OUTPUT_PATTERNS[@]} == 0)); then
    echo "  [none]"
  else
    for idx in "${!OUTPUT_PATTERNS[@]}"; do
      label="${OUTPUT_LABELS[$idx]}"
      pattern="${OUTPUT_PATTERNS[$idx]}"
      matches=()
      mapfile -t matches < <(compgen -G "$pattern" 2>/dev/null | LC_ALL=C sort || true)
      if ((${#matches[@]} > 0)); then
        echo "  [ok] $label: ${matches[*]}"
      else
        echo "  [missing] $label: $pattern"
      fi
    done
  fi
}

print_final_summary() {
  local cp2k_exit="$1"
  local status="finished"
  local now=0
  local final_line=""
  if [[ "$CHAIN_GATE_OUTCOME" == "REVIEW" ]]; then
    status="review"
  elif [[ "$cp2k_exit" != "0" || "$CHAIN_GATE_OUTCOME" == "FAIL" ]]; then
    status="failed"
  fi
  now="$(date +%s 2>/dev/null || echo 0)"
  if [[ "$now" =~ ^[0-9]+$ && "$START_EPOCH" =~ ^[0-9]+$ ]]; then
    ELAPSED_SECONDS=$((now - START_EPOCH))
  fi
  if [[ -z "${LAST_MEANINGFUL_LINE:-}" ]]; then
    final_line="$(last_meaningful_log_line "$LOG_FILE")"
    if [[ -n "$final_line" ]]; then
      LAST_MEANINGFUL_LINE="$final_line"
    fi
  fi
  echo
  echo "Stage summary:"
  echo "  stage: $STAGE_LABEL"
  echo "  run type: ${RUN_TYPE:-unknown}"
  echo "  status: $status"
  if [[ -n "$CHAIN_GATE_OUTCOME" ]]; then
    echo "  gate: $CHAIN_GATE_OUTCOME"
  fi
  echo "  command: ${CMD[*]}"
  echo "  wall time: $(format_duration "$ELAPSED_SECONDS")"
  echo "  exit code: $cp2k_exit"
  if [[ -n "$CHAIN_STATUS_TEXT" ]]; then
    echo "  gate reason: $CHAIN_STATUS_TEXT"
  fi
  if [[ -n "$COMPLETION_EVIDENCE" ]]; then
    echo "  completion evidence: $COMPLETION_EVIDENCE"
  fi
  if [[ "$RUN_TYPE" == "MD" && -n "$MD_LAST_STEP" ]]; then
    echo "  parsed MD step: $MD_LAST_STEP"
    if [[ -n "$MD_EXPECTED_FINAL_STEP" ]]; then
      echo "  expected final step: $MD_EXPECTED_FINAL_STEP"
    fi
  fi
  if [[ "$RUN_TYPE" == "GEO_OPT" ]]; then
    echo "  geo_opt convergence: $([[ "$GEO_OPT_CONVERGED" == "1" ]] && echo yes || echo no)"
    if [[ "$GEO_OPT_CONVERGED" != "1" && "${PRE_RELAXATION:-0}" == "1" && "$CHAIN_GATE_OUTCOME" == "PASS" ]]; then
      echo "  note: GEO_OPT did not converge within MAX_ITER.  This is expected"
      echo "        for large solvated systems where outlier solvent atoms dominate"
      echo "        MAX_FORCE/MAX_DR.  The restart coordinates are valid for"
      echo "        downstream MD equilibration.  If you suspect a topology defect,"
      echo "        inspect final forces: grep 'MAX. GRADIENT' ${LOG_FILE}"
    fi
  fi
  echo "  normal termination: $([[ "$NORMAL_TERMINATION" == "1" ]] && echo yes || echo no)"
  if [[ -n "${LAST_MEANINGFUL_LINE:-}" ]]; then
    echo "  last line: $(short_text "$LAST_MEANINGFUL_LINE")"
  fi
  if ((${#FATAL_MARKERS_FOUND[@]} > 0)); then
    echo "  fatal markers:"
    local marker=""
    for marker in "${FATAL_MARKERS_FOUND[@]}"; do
      echo "    $marker"
    done
  fi
  if ((${#MISSING_REQUIRED_OUTPUTS[@]} > 0)); then
    echo "  missing downstream artifacts:"
    local missing_output=""
    for missing_output in "${MISSING_REQUIRED_OUTPUTS[@]}"; do
      echo "    $missing_output"
    done
  fi
  if ((${#MISSING_UPSTREAM_ARTIFACTS[@]} > 0)); then
    echo "  missing upstream artifacts:"
    local missing_input=""
    for missing_input in "${MISSING_UPSTREAM_ARTIFACTS[@]}"; do
      echo "    $missing_input"
    done
  fi
  if [[ -n "$STAGE_MANUAL_COMMAND" && "$CHAIN_GATE_OUTCOME" != "PASS" ]]; then
    echo "  manual command: $STAGE_MANUAL_COMMAND"
  fi
  print_output_summary
}

signal_exit_code() {
  case "${1:-}" in
    INT) echo 130 ;;
    TERM) echo 143 ;;
    HUP) echo 129 ;;
    *) echo 1 ;;
  esac
}

pid_group_id() {
  local pid="${1:-}"
  local pgid=""
  if [[ -z "$pid" ]] || ! kill -0 "$pid" >/dev/null 2>&1; then
    return 1
  fi
  pgid="$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d '[:space:]' || true)"
  if [[ "$pgid" =~ ^[0-9]+$ ]]; then
    printf "%s" "$pgid"
    return 0
  fi
  return 1
}

terminate_pid() {
  local pid="${1:-}"
  local sig="${2:-TERM}"
  local pgid=""
  pgid="$(pid_group_id "$pid" || true)"
  if [[ -n "$pgid" && "$pgid" != "${WRAPPER_PGID:-}" ]]; then
    kill -s "$sig" -- "-$pgid" >/dev/null 2>&1 || true
  fi
  if [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1; then
    kill -s "$sig" "$pid" >/dev/null 2>&1 || true
  fi
}

terminate_active_children() {
  local sig="${1:-TERM}"
  terminate_pid "${CP2K_PID:-}" "$sig"
  terminate_pid "${TEE_PID:-}" "$sig"
}

cleanup_stream_pipe() {
  if [[ -n "${TEE_PID:-}" ]]; then
    wait "$TEE_PID" >/dev/null 2>&1 || true
    TEE_PID=""
  fi
  if [[ -n "${STREAM_PIPE_PATH:-}" && -p "$STREAM_PIPE_PATH" ]]; then
    rm -f "$STREAM_PIPE_PATH" >/dev/null 2>&1 || true
  fi
  if [[ -n "${STREAM_PIPE_DIR:-}" && -d "$STREAM_PIPE_DIR" ]]; then
    rmdir "$STREAM_PIPE_DIR" >/dev/null 2>&1 || true
  fi
  STREAM_PIPE_PATH=""
  STREAM_PIPE_DIR=""
}

launch_background_command() {
  local output_target="$1"
  shift
  if command -v setsid >/dev/null 2>&1; then
    (trap - INT TERM; exec setsid "$@" >"$output_target" 2>&1) &
  else
    (trap - INT TERM; exec "$@" >"$output_target" 2>&1) &
  fi
}

handle_wrapper_signal() {
  local sig="${1:-INT}"
  local exit_code=""
  if [[ "${WRAPPER_SHUTDOWN:-0}" == "1" ]]; then
    exit "$(signal_exit_code "$sig")"
  fi
  WRAPPER_SHUTDOWN=1
  echo >&2
  echo "Interrupt received ($sig); stopping CP2K stage..." >&2
  terminate_active_children TERM
  sleep 0.2
  terminate_active_children KILL
  cleanup_stream_pipe
  exit_code="$(signal_exit_code "$sig")"
  exit "$exit_code"
}

cleanup_on_exit() {
  local status=$?
  trap - EXIT INT TERM
  if [[ -n "${CP2K_PID:-}" || -n "${TEE_PID:-}" || -n "${STREAM_PIPE_PATH:-}" || -n "${STREAM_PIPE_DIR:-}" ]]; then
    terminate_active_children TERM
    sleep 0.1
    terminate_active_children KILL
    cleanup_stream_pipe
  fi
  exit "$status"
}

run_cp2k_streaming_mode() {
  local enable_monitor="${1:-0}"
  local cp2k_exit=0
  STREAM_PIPE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/cp2k_wrapper_stream.XXXXXX" 2>/dev/null || true)"
  if [[ -z "$STREAM_PIPE_DIR" ]]; then
    echo "WARN: monitor stream setup failed; falling back to direct tee." >&2
    "${CMD[@]}" 2>&1 | tee "$LOG_FILE"
    return "${PIPESTATUS[0]}"
  fi
  STREAM_PIPE_PATH="$STREAM_PIPE_DIR/cp2k.stream"
  if ! mkfifo "$STREAM_PIPE_PATH" 2>/dev/null; then
    echo "WARN: monitor stream FIFO setup failed; falling back to direct tee." >&2
    rmdir "$STREAM_PIPE_DIR" >/dev/null 2>&1 || true
    STREAM_PIPE_DIR=""
    STREAM_PIPE_PATH=""
    "${CMD[@]}" 2>&1 | tee "$LOG_FILE"
    return "${PIPESTATUS[0]}"
  fi

  (trap - INT TERM; exec tee "$LOG_FILE" <"$STREAM_PIPE_PATH") &
  TEE_PID=$!
  launch_background_command "$STREAM_PIPE_PATH" "${CMD[@]}"
  CP2K_PID=$!

  if [[ "$enable_monitor" == "1" ]]; then
    emit_status_line "running" || true
    while kill -0 "$CP2K_PID" >/dev/null 2>&1; do
      sleep "$MONITOR_INTERVAL"
      if kill -0 "$CP2K_PID" >/dev/null 2>&1; then
        emit_status_line "running" || true
      fi
    done
  fi

  wait "$CP2K_PID"
  cp2k_exit=$?
  CP2K_PID=""
  wait "$TEE_PID" >/dev/null 2>&1 || true
  TEE_PID=""
  cleanup_stream_pipe
  return "$cp2k_exit"
}

run_cp2k_quiet_monitor_mode() {
  local cp2k_exit=0
  : >"$LOG_FILE"
  launch_background_command "$LOG_FILE" "${CMD[@]}"
  CP2K_PID=$!
  emit_status_line "running" || true
  while kill -0 "$CP2K_PID" >/dev/null 2>&1; do
    sleep "$MONITOR_INTERVAL"
    if kill -0 "$CP2K_PID" >/dev/null 2>&1; then
      emit_status_line "running" || true
    fi
  done
  wait "$CP2K_PID"
  cp2k_exit=$?
  CP2K_PID=""
  return "$cp2k_exit"
}

""")

    lines.append("""print_chain_stop_message() {
  echo
  echo "Chain stop:"
  echo "  stage: $CURRENT_STAGE_NAME"
  echo "  gate: ${CHAIN_GATE_OUTCOME:-unknown}"
  if [[ -n "$CHAIN_STATUS_TEXT" ]]; then
    echo "  reason: $CHAIN_STATUS_TEXT"
  fi
  if [[ -n "$COMPLETION_EVIDENCE" ]]; then
    echo "  completion evidence: $COMPLETION_EVIDENCE"
  fi
  if ((${#MISSING_UPSTREAM_ARTIFACTS[@]} > 0)); then
    echo "  missing upstream artifacts:"
    local path=""
    for path in "${MISSING_UPSTREAM_ARTIFACTS[@]}"; do
      echo "    $path"
    done
  fi
  if ((${#MISSING_REQUIRED_OUTPUTS[@]} > 0)); then
    echo "  missing downstream artifacts:"
    local path=""
    for path in "${MISSING_REQUIRED_OUTPUTS[@]}"; do
      echo "    $path"
    done
  fi
  if [[ -n "$STAGE_MANUAL_COMMAND" ]]; then
    echo "  manual command: $STAGE_MANUAL_COMMAND"
  fi
}

parse_wrapper_args() {
  POSITIONAL_ARGS=()
  while (($# > 0)); do
    case "$1" in
      --auto-chain)
        AUTO_CHAIN=1
        CHAIN_MODE_LABEL="auto-chain"
        ;;
      --resume)
        AUTO_CHAIN=1
        RESUME_CHAIN=1
        CHAIN_MODE_LABEL="resume"
        ;;
      --start-stage)
        shift
        if (($# == 0)); then
          echo "ERROR: --start-stage requires a value." >&2
          exit 2
        fi
        START_STAGE_REQUEST="$1"
        ;;
      --end-stage)
        shift
        if (($# == 0)); then
          echo "ERROR: --end-stage requires a value." >&2
          exit 2
        fi
        END_STAGE_REQUEST="$1"
        ;;
      -h|--help)
        print_wrapper_usage
        exit 0
        ;;
      --)
        shift
        while (($# > 0)); do
          POSITIONAL_ARGS+=("$1")
          shift
        done
        break
        ;;
      -*)
        echo "ERROR: Unknown option: $1" >&2
        print_wrapper_usage >&2
        exit 2
        ;;
      *)
        POSITIONAL_ARGS+=("$1")
        ;;
    esac
    shift
  done

  if [[ "$AUTO_CHAIN" == "1" && ${#POSITIONAL_ARGS[@]} -gt 0 ]]; then
    echo "ERROR: Positional stage/log arguments are only supported in single-stage mode." >&2
    exit 2
  fi

  if [[ "$AUTO_CHAIN" != "1" ]]; then
    INPUT_FILE="${POSITIONAL_ARGS[0]:-$DEFAULT_INPUT_FILE}"
    if [[ ${#POSITIONAL_ARGS[@]} -ge 2 ]]; then
      STAGE_LOG_OVERRIDE="${POSITIONAL_ARGS[1]}"
    fi
  fi
}

run_current_stage() {
  local requested_stage="${1:-$INPUT_FILE}"
  local cp2k_exit=0
  local preflight_rc=0

  if ! set_stage_context "$requested_stage"; then
    return 2
  fi
  if preflight_stage; then
    :
  else
    preflight_rc=$?
    CHAIN_GATE_OUTCOME="FAIL"
    CHAIN_STATUS_TEXT="stage preflight failed"
    COMPLETION_EVIDENCE="required upstream artifacts are missing or empty"
    print_chain_stop_message
    return "$preflight_rc"
  fi

  START_EPOCH="$(date +%s 2>/dev/null || echo 0)"
  PREV_LOG_SIZE=0
  ELAPSED_SECONDS=0
  LAST_MEANINGFUL_LINE=""
  FATAL_MARKERS_FOUND=()
  MISSING_REQUIRED_OUTPUTS=()
  update_stage_manual_command

  if [[ "$USE_MPI" == "1" ]]; then
    if [[ -z "$MPI_LAUNCHER" ]]; then
      echo "ERROR: USE_MPI=1 but no MPI launcher detected." >&2
      return 4
    fi
    CMD=("$MPI_LAUNCHER" "$MPI_NP_FLAG" "$MPI_RANKS" "$CP2K_BIN" "-i" "$INPUT_FILE")
  else
    CMD=("$CP2K_BIN" "-i" "$INPUT_FILE")
  fi

  echo "Input: $INPUT_FILE"
  echo "Log:   $LOG_FILE"
  echo "Command: ${CMD[*]}"
  echo "Stage: $STAGE_LABEL (${RUN_TYPE:-unknown})"
  if [[ "$HAS_HF" == "1" && -n "$HF_MAX_MEMORY" ]]; then
    echo "HF MAX_MEMORY: $HF_MAX_MEMORY per MPI rank (input setting; review if you override MPI_RANKS)"
  fi
  echo "Console mode: $EFFECTIVE_MONITOR_MODE (default hybrid; MONITOR_MODE=stream for raw-only, monitor for quiet)"
  echo "Press Ctrl-C once to stop the current stage cleanly."
  if [[ -n "$STREAM_OUTPUT" ]]; then
    echo "STREAM_OUTPUT compatibility override detected: $STREAM_OUTPUT"
  fi
  echo

  RUN_ACTIVE=1
  set +e
  if [[ "$EFFECTIVE_MONITOR_MODE" == "stream" ]]; then
    run_cp2k_streaming_mode 0
    cp2k_exit=$?
  elif [[ "$EFFECTIVE_MONITOR_MODE" == "hybrid" ]]; then
    run_cp2k_streaming_mode 1
    cp2k_exit=$?
  else
    run_cp2k_quiet_monitor_mode
    cp2k_exit=$?
  fi
  set -e
  RUN_ACTIVE=0

  classify_stage_outcome "$cp2k_exit"

  if [[ "$EFFECTIVE_MONITOR_MODE" != "stream" ]]; then
    if [[ "$CHAIN_GATE_OUTCOME" == "PASS" ]]; then
      emit_status_line "finished" || true
    elif [[ "$CHAIN_GATE_OUTCOME" == "REVIEW" ]]; then
      emit_status_line "review" || true
    else
      emit_status_line "failed" || true
    fi
  fi

  print_final_summary "$cp2k_exit" || true
  echo "CP2K exit code: $cp2k_exit"
  return "$cp2k_exit"
}

run_auto_chain() {
  local current_stage=""
  local cp2k_exit=0
  local rc=0

  resolve_chain_window
  current_stage="$CHAIN_START_STAGE"
  echo "Auto-chain window: $CHAIN_START_STAGE -> $CHAIN_END_STAGE"

  while [[ -n "$current_stage" ]]; do
    STAGE_LOG_OVERRIDE=""
    if ! set_stage_context "$current_stage"; then
      return 2
    fi
    if preflight_stage; then
      :
    else
      rc=$?
      CHAIN_GATE_OUTCOME="FAIL"
      CHAIN_STATUS_TEXT="stage preflight failed"
      COMPLETION_EVIDENCE="required upstream artifacts are missing or empty"
      write_chain_state_json "preflight" "$rc" "$current_stage" || true
      print_chain_stop_message
      return "$rc"
    fi

    # Reset gate variables from the previous stage so the "running"
    # state snapshot does not carry stale completion evidence.
    CHAIN_GATE_OUTCOME=""
    CHAIN_STATUS_TEXT=""
    COMPLETION_EVIDENCE=""
    MD_LAST_STEP=""
    MD_EXPECTED_FINAL_STEP=""
    write_chain_state_json "running" "" "$NEXT_STAGE_NAME" || true
    run_current_stage "$CURRENT_STAGE_NAME"
    cp2k_exit=$?

    if [[ "$CHAIN_GATE_OUTCOME" == "PASS" ]]; then
      LAST_PASS_STAGE="$CURRENT_STAGE_NAME"
      if [[ "$CURRENT_STAGE_NAME" == "$CHAIN_END_STAGE" ]]; then
        CHAIN_STATUS_TEXT="chain completed"
        write_chain_state_json "completed" "$cp2k_exit" "" || true
        echo "Auto-chain completed through $CURRENT_STAGE_NAME."
        return 0
      fi
      write_chain_state_json "pass" "$cp2k_exit" "$NEXT_STAGE_NAME" || true
      echo "Auto-chain advancing: $CURRENT_STAGE_NAME -> $NEXT_STAGE_NAME"
      current_stage="$NEXT_STAGE_NAME"
      continue
    fi

    if [[ "$CHAIN_GATE_OUTCOME" == "REVIEW" ]]; then
      write_chain_state_json "review" "$cp2k_exit" "$CURRENT_STAGE_NAME" || true
      print_chain_stop_message
      return 0
    fi

    write_chain_state_json "fail" "$cp2k_exit" "$CURRENT_STAGE_NAME" || true
    print_chain_stop_message
    if [[ "$cp2k_exit" == "0" ]]; then
      return 7
    fi
    return "$cp2k_exit"
  done

  return 0
}

cd "$RUN_DIR"
CHAIN_STATE_FILE="${CHAIN_STATE_FILE:-$CHAIN_STATE_FILE_DEFAULT}"
USE_MPI="${USE_MPI:-$USE_MPI_DEFAULT}"
MPI_RANKS="${MPI_RANKS:-$MPI_RANKS_DEFAULT}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-$OMP_NUM_THREADS_DEFAULT}"
export OMP_PROC_BIND="${OMP_PROC_BIND:-spread}"
export OMP_PLACES="${OMP_PLACES:-cores}"
if [[ -n "$SELECTED_GPU_DEFAULT" ]]; then
  export CUDA_DEVICE_ORDER="${CUDA_DEVICE_ORDER:-PCI_BUS_ID}"
  export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-$SELECTED_GPU_DEFAULT}"
fi

parse_wrapper_args "$@"
resolve_monitor_mode
ensure_chain_state_support

if ! command -v "$CP2K_BIN" >/dev/null 2>&1; then
  echo "ERROR: CP2K binary not found/executable: $CP2K_BIN" >&2
  exit 3
fi

# ── CP2K version pre-flight check (V2, V8, V11) ─────────────────────────────
# Two-tier version gate.  The hard floor is the minimum release at which
# every non-optional keyword the pipeline emits is documented stable:
#   * GEEP-periodic QM/MM and &QMMM/&PERIODIC/&MULTIPOLE/RCUT
#     — Laino et al., JCTC 2, 1370 (2006); CP2K 6.1 release notes.
#   * ADMM with cpFIT3 auxiliary basis
#     — Guidon-Hutter-VandeVondele, JCTC 6, 2348 (2010); CP2K 5.1+.
#   * USE_GEEP_LIB up to depth 9
#     — Laino et al., JCTC 1, 1176 (2005); CP2K 4.1+.
#   * Full &EXT_RESTART flag set (RESTART_POS/VEL/CELL/COUNTERS/…)
#     — CP2K 5.1+ manual §MOTION/MD/&PRINT/RESTART.
# The soft floor (8.1) is consulted separately by the Python emitter
# when the user selects the ``admm-dzp`` auxiliary basis (V4), which
# is new in CP2K 8.1; older builds get the cpFIT3 fallback.
#
# ``CP2K_VERSION_RE`` accepts both the semantic ("CP2K 7.7.0") and the
# year-based ("CP2K 2022.2") naming schemes that CP2K has used through
# its history.  The regex captures ``major.minor[.patch]`` regardless
# of surrounding "version" tokens or "(Development Version)" suffixes.
# Escape hatches (V8):
#   * ``CP2K_SKIP_VERSION_CHECK=1`` — skip the gate entirely.
#   * ``CP2K_MIN_VERSION="major.minor"`` — override the hard floor
#     (tighter or looser).
# Ref: CP2K release notes at https://www.cp2k.org/version_history.
: "${CP2K_MIN_VERSION:=__CP2K_VERSION_FLOOR_HARD__}"
: "${CP2K_SKIP_VERSION_CHECK:=__CP2K_SKIP_VERSION_CHECK_DEFAULT__}"

if [[ "$CP2K_SKIP_VERSION_CHECK" == "1" ]]; then
  echo "WARNING: CP2K_SKIP_VERSION_CHECK=1 — version gate bypassed by user override." >&2
else
  CP2K_VERSION_LINE="$("$CP2K_BIN" --version 2>/dev/null | head -n 1 || true)"
  if [[ -n "$CP2K_VERSION_LINE" ]]; then
    # Accept: "CP2K 7.7.0", "CP2K version 8.1", "CP2K 2022.2", and any
    # combination with a trailing "(Development Version)" banner.
    CP2K_VERSION_STRING="$(echo "$CP2K_VERSION_LINE" \
      | grep -oiE 'CP2K[[:space:]]+(version[[:space:]]+)?[0-9]+\.[0-9]+([.][0-9]+)?' \
      | head -n 1 \
      | grep -oE '[0-9]+\.[0-9]+([.][0-9]+)?' \
      | head -n 1 || true)"
    if [[ -n "$CP2K_VERSION_STRING" ]]; then
      CP2K_MAJOR="${CP2K_VERSION_STRING%%.*}"
      CP2K_REST="${CP2K_VERSION_STRING#*.}"
      CP2K_MINOR="${CP2K_REST%%.*}"
      REQ_MAJOR="${CP2K_MIN_VERSION%%.*}"
      REQ_REST="${CP2K_MIN_VERSION#*.}"
      REQ_MINOR="${REQ_REST%%.*}"
      if [[ "$CP2K_MAJOR" =~ ^[0-9]+$ && "$CP2K_MINOR" =~ ^[0-9]+$ \
         && "$REQ_MAJOR"  =~ ^[0-9]+$ && "$REQ_MINOR"  =~ ^[0-9]+$ ]]; then
        if (( CP2K_MAJOR < REQ_MAJOR || (CP2K_MAJOR == REQ_MAJOR && CP2K_MINOR < REQ_MINOR) )); then
          echo "ERROR: detected CP2K ${CP2K_VERSION_STRING} at $CP2K_BIN." >&2
          echo "       This pipeline emits inputs that require CP2K >= ${CP2K_MIN_VERSION}." >&2
          echo "       Missing or unstable at < ${CP2K_MIN_VERSION}:" >&2
          echo "         * &QMMM/&PERIODIC/&MULTIPOLE/RCUT (Laino et al., JCTC 2, 1370 (2006))" >&2
          echo "         * ADMM + cpFIT3 auxiliary basis (Guidon et al., JCTC 6, 2348 (2010))" >&2
          echo "         * &EXT_RESTART full flag set (CP2K >= 5.1)" >&2
          echo "       Options:" >&2
          echo "         1) point CP2K_BIN at a supported build (>= ${CP2K_MIN_VERSION})" >&2
          echo "         2) override with CP2K_MIN_VERSION=X.Y if you know your build" >&2
          echo "            supports the emitted keywords." >&2
          echo "         3) opt out entirely with CP2K_SKIP_VERSION_CHECK=1 (advanced)." >&2
          exit 5
        fi
        echo "CP2K version check: ${CP2K_VERSION_STRING} (>= ${CP2K_MIN_VERSION} required)."
      fi
    fi
  else
    echo "WARNING: could not read CP2K version from '$CP2K_BIN --version'; skipping version check." >&2
  fi
fi

WRAPPER_PGID="$(ps -o pgid= -p $$ 2>/dev/null | tr -d '[:space:]' || true)"
trap 'handle_wrapper_signal INT' INT
trap 'handle_wrapper_signal TERM' TERM
trap cleanup_on_exit EXIT

echo "CP2K wrapper start: $(date)"
echo "Mode:  $CHAIN_MODE_LABEL"
echo "CP2K:  $CP2K_BIN"
echo "OMP_NUM_THREADS=$OMP_NUM_THREADS"
if [[ -n "${CUDA_VISIBLE_DEVICES:-}" ]]; then
  echo "CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES"
fi
if [[ "$USE_MPI" == "1" ]]; then
  if [[ -z "$MPI_LAUNCHER" ]]; then
    echo "ERROR: USE_MPI=1 but no MPI launcher detected." >&2
    exit 4
  fi
  echo "MPI launcher: $MPI_LAUNCHER $MPI_NP_FLAG $MPI_RANKS"
fi

if [[ "$AUTO_CHAIN" == "1" ]]; then
  run_auto_chain
  wrapper_exit=$?
else
  run_current_stage "$INPUT_FILE"
  wrapper_exit=$?
  if [[ "$CHAIN_GATE_OUTCOME" == "FAIL" && "$wrapper_exit" == "0" ]]; then
    wrapper_exit=7
  fi
fi

echo "CP2K wrapper end: $(date)"
exit "$wrapper_exit"
""")

    # ── Bake generator-time Python constants into the bash template ────
    # The bash pre-flight (V2) references the hard version floor by a
    # placeholder so the SSOT for "minimum supported CP2K" lives in
    # Python (``CP2K_VERSION_FLOOR_HARD``) and the bash script simply
    # inherits whatever value was current at generation time.
    #
    # V8: honor the CLI overrides --cp2k-min-version and
    # --cp2k-skip-version-check.  The override string is validated by the
    # caller (CLI layer) before reaching this emitter.  At runtime either
    # can still be overridden by exporting the corresponding env var
    # (CP2K_MIN_VERSION / CP2K_SKIP_VERSION_CHECK) — see the bash `: ${...:=...}`
    # defaulting idiom which applies the baked default only when the
    # env var is unset or empty.
    if cp2k_min_version_override:
        _floor_hard_str = str(cp2k_min_version_override).strip()
    else:
        _floor_hard_str = f"{CP2K_VERSION_FLOOR_HARD[0]}.{CP2K_VERSION_FLOOR_HARD[1]}"
    _skip_default_str = "1" if bool(cp2k_skip_version_check_default) else "0"
    lines = [
        ln.replace('__CP2K_VERSION_FLOOR_HARD__', _floor_hard_str)
          .replace('__CP2K_SKIP_VERSION_CHECK_DEFAULT__', _skip_default_str)
        for ln in lines
    ]

    with open(wrapper_path, 'w') as f:
        f.writelines(lines)

    os.chmod(wrapper_path, 0o755)
    return wrapper_path


def write_cp2k_compat_report(
    out_path,
    cp2k_capability,
    substitutions=None,
    hardware_info=None,
    launch_cfg=None,
    dft_config=None,
    mgrid_provenance=None,
    cp2k_binary=None,
):
    """Write the structured CP2K compatibility + provenance report (V6/V9).

    Consolidates into a single artifact:
      * The detected CP2K version, the hard/soft floors, and whether the
        pipeline proceeded or was bypassed via override (V2, V8).
      * Any feature substitutions the Python emitter applied based on
        the resolved capability (V4) — e.g. ``admm-dzp → cpFIT3`` below
        CP2K 8.1.
      * The hardware-aware provenance originally planned for S12: the
        detected core/memory/GPU topology, the chosen MPI_RANKS and
        OMP_NUM_THREADS, and the CUTOFF/REL_CUTOFF/NGRIDS values with
        a short rationale citing VandeVondele & Hutter, JCP 127,
        114105 (2007) for the default MOLOPT/MGRID recipe.

    The report is plain text so it can travel with the emitted inputs
    under version control or in an archive without special tooling.

    Parameters
    ----------
    out_path : str
        Destination for the ``cp2k_compat_report.txt`` artifact.
    cp2k_capability : ResolvedCP2KCapability
        Capability snapshot built from the detected version.
    substitutions : list[dict], optional
        Structured substitution records written by the emitters (V4).
    hardware_info : dict, optional
        Output of :func:`detect_local_hardware` (or the fallback dict).
    launch_cfg : dict, optional
        Output of :func:`recommend_cp2k_launch_settings`.
    dft_config : DFTConfig, optional
        Resolved DFT config — source for CUTOFF/REL_CUTOFF/NGRIDS.
    mgrid_provenance : dict, optional
        Dict with keys ``cutoff_source``, ``rel_cutoff_source``,
        ``ngrids_source`` documenting whether each value came from the
        hardware-aware recommender, the CLI, or the interactive prompt.
    cp2k_binary : str, optional
        Path to the CP2K binary that was probed.
    """
    cap = cp2k_capability
    hw = dict(hardware_info or {})
    cfg = dict(launch_cfg or {})
    subs = list(substitutions or [])
    prov = dict(mgrid_provenance or {})

    lines = []
    lines.append("CP2K Compatibility & Provenance Report\n")
    lines.append("======================================\n\n")

    lines.append("[CP2K version]\n")
    if cp2k_binary:
        lines.append(f"  Binary: {cp2k_binary}\n")
    if cap is None:
        lines.append("  Detected: unknown (capability not built)\n")
    else:
        lines.append(
            "  Detected: "
            + (format_cp2k_version(cap.version) if cap.version else "unknown")
            + (f"    (raw: {cap.raw_version_line})" if cap.raw_version_line else '')
            + "\n"
        )
        lines.append(
            f"  Hard floor: >= {cap.floor_hard[0]}.{cap.floor_hard[1]}   "
            "(every non-optional emitted keyword is documented stable at this floor)\n"
        )
        lines.append(
            f"  Soft floor: >= {cap.floor_soft[0]}.{cap.floor_soft[1]}   "
            "(required only when admm-dzp auxiliary basis is selected)\n"
        )
        lines.append("  References:\n")
        lines.append("    - Laino et al., JCTC 1, 1176 (2005); JCTC 2, 1370 (2006) — GEEP/periodic QMMM\n")
        lines.append("    - Guidon et al., JCTC 5, 3010 (2009) — truncated HFX\n")
        lines.append("    - Guidon et al., JCTC 6, 2348 (2010) — ADMM\n")
        lines.append("    - VandeVondele & Hutter, JCP 127, 114105 (2007) — MOLOPT basis sets\n")
        lines.append("    - CP2K release notes: https://www.cp2k.org/version_history\n")
    lines.append("\n")

    lines.append("[Keyword availability]\n")
    if cap is not None:
        for kw, available in sorted(cap.keywords.items()):
            needed = CP2K_KEYWORD_MIN_VERSION.get(kw)
            needed_str = format_cp2k_version(needed) if needed else '?'
            lines.append(
                f"  [{'x' if available else ' '}] {kw}   (needs >= {needed_str})\n"
            )
    else:
        lines.append("  (no capability snapshot)\n")
    lines.append("\n")

    lines.append("[Feature substitutions applied]\n")
    if subs:
        for s in subs:
            lines.append(
                f"  - {s.get('kind', 'substitution')}: "
                f"{s.get('from', '?')} -> {s.get('to', '?')}\n"
            )
            if s.get('reason'):
                lines.append(f"      reason: {s['reason']}\n")
            if s.get('citation'):
                lines.append(f"      cite:   {s['citation']}\n")
    else:
        lines.append("  (none — all requested features are supported at the detected version)\n")
    lines.append("\n")

    lines.append("[Hardware-aware provenance]\n")
    if hw:
        lines.append(
            f"  logical_cores={int(hw.get('logical_cores') or 0)}, "
            f"physical_cores={int(hw.get('physical_cores') or 0)}\n"
        )
        if hw.get('memory_gb') is not None:
            lines.append(f"  memory_gb={float(hw['memory_gb']):.1f}\n")
        lines.append(
            f"  gpu_count={int(hw.get('gpu_count') or 0)}, "
            f"gpu_detection_method={hw.get('gpu_detection_method', 'n/a')}\n"
        )
    if cfg:
        lines.append(
            f"  launch: use_mpi={bool(cfg.get('use_mpi'))}, "
            f"mpi_ranks={int(cfg.get('mpi_ranks') or 1)}, "
            f"omp_threads={int(cfg.get('omp_threads') or 1)}\n"
        )
        if cfg.get('selected_gpu_index') is not None:
            lines.append(
                f"  selected_gpu_index={cfg.get('selected_gpu_index')}"
                + (f" ({cfg.get('selected_gpu_name')})" if cfg.get('selected_gpu_name') else '')
                + "\n"
            )
    lines.append("\n")

    lines.append("[MGRID / DFT grid provenance]\n")
    if dft_config is not None:
        # VandeVondele-Hutter MOLOPT: 400-600 Ry CUTOFF with REL_CUTOFF 60 Ry
        # and NGRIDS 5 captures diffuse functions accurately without overspending
        # on the finest grid.  Ref: JCP 127, 114105 (2007).
        d = dft_config._asdict() if hasattr(dft_config, '_asdict') else dict(dft_config)
        lines.append(
            f"  CUTOFF     [Ry] = {float(d.get('cutoff', 0.0)):g}"
            + (f"   (source: {prov['cutoff_source']})" if prov.get('cutoff_source') else '')
            + "\n"
        )
        lines.append(
            f"  REL_CUTOFF [Ry] = {float(d.get('rel_cutoff', 0.0)):g}"
            + (f"   (source: {prov['rel_cutoff_source']})" if prov.get('rel_cutoff_source') else '')
            + "\n"
        )
        lines.append(
            f"  NGRIDS         = {int(d.get('ngrids', 0))}"
            + (f"   (source: {prov['ngrids_source']})" if prov.get('ngrids_source') else '')
            + "\n"
        )
        lines.append(
            "  Rationale: MOLOPT/GTH grid convergence follows VandeVondele &\n"
            "  Hutter, JCP 127, 114105 (2007).  NGRIDS=5 with COMMENSURATE=T\n"
            "  captures diffuse polarisation functions efficiently for the\n"
            "  standard DZVP-MOLOPT family.\n"
        )
    else:
        lines.append("  (no DFT config available)\n")
    lines.append("\n")

    lines.append("[Override status]\n")
    lines.append(
        "  This report records the state at generation time.  At runtime\n"
        "  the wrapper honors two environment overrides:\n"
        "    CP2K_MIN_VERSION=X.Y        tighten or loosen the hard floor\n"
        "    CP2K_SKIP_VERSION_CHECK=1   bypass the gate entirely (advanced)\n"
        "  Any override is echoed into the wrapper stdout so runs under it\n"
        "  remain auditable.\n"
    )

    with open(out_path, 'w') as f:
        f.writelines(lines)
    return out_path


def write_readme_next_steps(
    out_path,
    wrapper_filename,
    stage_meta,
    cp2k_binary=None,
):
    """Write deterministic staged-workflow execution guidance."""
    meta = dict(stage_meta or {})
    stage_order = list(meta.get('stage_order') or [])
    deps = list(meta.get('dependencies') or [])
    warmup_enabled = bool(meta.get('warmup_enabled', True))
    handoff_vel = bool(meta.get('handoff_restart_velocities', False))
    qmmm_handoff_mode = str(meta.get('qmmm_handoff_policy_mode') or DEFAULT_QMMM_HANDOFF_POLICY)
    qmmm_handoff_label = str(meta.get('qmmm_handoff_policy_label') or '')
    qmmm_handoff_reason = str(meta.get('qmmm_handoff_policy_reason') or '')
    qmmm_transition_init = str(meta.get('qmmm_transition_initialization_method') or '')
    qmmm_transition_seed = meta.get('qmmm_transition_global_seed')
    qmmm_transition_tau = meta.get('qmmm_transition_thermostat_timecon_fs')
    qmmm_transition_label = str(meta.get('qmmm_transition_label') or '')
    qmmm_transition_reason = str(meta.get('qmmm_transition_reason') or '')
    mm_rest = bool(meta.get('mm_equil_restraints', False))
    warmup_rest = bool(meta.get('warmup_restraints', False))
    stateless_restart = bool(meta.get('stateless_restart', False))
    mm_prmtop_file = str(meta.get('mm_prmtop_file') or 'system_mm.prmtop')
    qmmm_prmtop_file = str(meta.get('qmmm_prmtop_file') or mm_prmtop_file)
    split_stage_topologies = bool(meta.get('split_stage_topologies', False))

    lines = []
    lines.append("Staged CP2K Workflow: MM -> QM/MM (enzyme-safe handoff)\n")
    lines.append("=====================================================\n\n")
    lines.append("Run Order (deterministic filenames)\n")
    for i, stage in enumerate(stage_order, start=1):
        lines.append(f"{i}. {stage}\n")
    lines.append("\n")

    lines.append("Restart Dependencies and Semantics\n")
    for d in deps:
        stage = d.get('stage')
        rfile = d.get('restart_from')
        wfile = d.get('wfn_restart_from')
        if not rfile:
            lines.append(f"- {stage}: no EXT_RESTART (fresh start)\n")
            continue
        row = (
            f"- {stage}: RESTART_FILE_NAME={rfile}, "
            f"RESTART_POS={_cp2k_bool(d.get('restart_pos'))}, "
            f"RESTART_VEL={_cp2k_bool(d.get('restart_vel'))}, "
            f"RESTART_CELL={_cp2k_bool(d.get('restart_cell'))}, "
            f"RESTART_COUNTERS={_cp2k_bool(d.get('restart_counters'))}, "
            f"RESTART_THERMOSTAT={_cp2k_bool(d.get('restart_thermostat'))}, "
            f"RESTART_BAROSTAT={_cp2k_bool(d.get('restart_barostat'))}, "
            f"RESTART_RANDOMG={_cp2k_bool(d.get('restart_randomg'))}, "
            "RESTART_DEFAULT=FALSE"
        )
        if wfile:
            row += f", WFN_RESTART_FILE_NAME={wfile}, SCF_GUESS=RESTART"
        lines.append(row + "\n")
    lines.append("\n")

    lines.append("Method Transitions and Safety Rules\n")
    lines.append(
        f"- MM stages (10/20/30) are MM-only (METHOD FIST; no DFT/QMMM blocks) and use {mm_prmtop_file}.\n"
    )
    if split_stage_topologies:
        lines.append(
            f"- QM/MM stages (35/40) use {qmmm_prmtop_file}, which preserves split-residue charge redistribution for QM/MM only.\n"
        )
    else:
        lines.append(
            f"- QM/MM stages (35/40) use {qmmm_prmtop_file}; this workflow does not need separate MM/QM/MM topology variants.\n"
        )
    lines.append("- All stages preserve the same atom ordering and coordinate file.\n")
    lines.append(
        "- QM/MM stages write an explicit periodic MULTIPOLE RCUT target; if the QM cell or MM box "
        "cannot support that target, the generator emits a reduced RCUT and warns for review.\n"
    )
    lines.append("- For QM/MM->QM/MM continuation, wavefunction restart is explicit (SCF_GUESS=RESTART + WFN_RESTART_FILE_NAME).\n")
    lines.append(
        "- Restart state policy: "
        + (
            "EXPERT stateless mode (counters/thermostat/barostat/random disabled)."
            if stateless_restart
            else "conservative staged MD continuity (restart counters/thermostat/barostat/random for MD->MD transitions)."
        )
        + "\n"
    )
    lines.append(
        f"- MM->QM/MM handoff policy: {qmmm_handoff_mode} "
        + (f"({qmmm_handoff_label}).\n" if qmmm_handoff_label else "\n")
    )
    if qmmm_handoff_reason:
        lines.append(f"  {qmmm_handoff_reason}\n")
    lines.append(
        f"- NPT->QM/MM handoff velocity restart is {'ENABLED' if handoff_vel else 'DISABLED'}.\n"
    )
    if qmmm_transition_label:
        lines.append(f"- First-QM/MM-stage transition control: {qmmm_transition_label}.\n")
    if qmmm_transition_reason:
        lines.append(f"  {qmmm_transition_reason}\n")
    if qmmm_transition_init:
        lines.append(f"- First-QM/MM-stage INITIALIZATION_METHOD: {qmmm_transition_init}.\n")
    if qmmm_transition_seed is not None:
        lines.append(f"- First-QM/MM-stage GLOBAL SEED: {int(qmmm_transition_seed)}.\n")
    if qmmm_transition_tau is not None:
        lines.append(f"- First-QM/MM-stage CSVR TIMECON: {float(qmmm_transition_tau):g} fs.\n")
    lines.append(f"- MM equilibration active-site restraints (fixed QM atoms): {'ENABLED' if mm_rest else 'DISABLED'}.\n")
    lines.append(f"- QM/MM warmup restraints (fixed QM atoms): {'ENABLED' if warmup_rest else 'DISABLED'}.\n")
    lines.append(f"- QM/MM warmup stage (35_qmmm_warmup.inp): {'ENABLED' if warmup_enabled else 'DISABLED'}.\n")
    lines.append("\n")

    lines.append("Manual Run Commands\n")
    lines.append(f"- Wrapper: ./{wrapper_filename}\n")
    lines.append(f"  ./{wrapper_filename} --auto-chain\n")
    lines.append(f"  ./{wrapper_filename} --auto-chain --start-stage 20_nvt_mm --end-stage 40_qmmm_md\n")
    lines.append(f"  ./{wrapper_filename} --resume\n")
    for stage in stage_order:
        stem = os.path.splitext(stage)[0]
        lines.append(f"  ./{wrapper_filename} {stage} {stem}.log\n")
    lines.append("\n")

    lines.append("Direct CP2K Commands (if not using wrapper)\n")
    cp2k_hint = cp2k_binary or "cp2k.psmp"
    for stage in stage_order:
        stem = os.path.splitext(stage)[0]
        lines.append(f"  {cp2k_hint} -i {stage} > {stem}.log 2>&1\n")
    lines.append("\n")

    lines.append("Resume Instructions\n")
    lines.append("- Auto-chain state is persisted to cp2k_chain_state.json after each stage transition.\n")
    lines.append("- Use ./" + wrapper_filename + " --resume to continue from the last PASS stage.\n")
    lines.append("- If a stage completed, resume from the next stage in run order.\n")
    lines.append("- If a stage was interrupted, rerun that stage command first; keep its restart/output files in the same directory.\n")
    lines.append("- Do not skip dependencies: each stage expects the previous stage's PROJECT-1.restart file.\n")
    lines.append("- Hybrid stages write HF/MEMORY/MAX_MEMORY as a per-MPI-rank limit; if you change MPI_RANKS at launch, review or regenerate that setting.\n")
    lines.append("- If you re-run an earlier stage, re-run all downstream stages to keep thermodynamic history consistent.\n")
    lines.append("\n")

    lines.append("MM->QM/MM Handoff Explanation\n")
    lines.append("- 30_npt_mm equilibrates density/cell in pure MM.\n")
    if warmup_enabled:
        lines.append(
            "- 35_qmmm_warmup performs the deliberate QM/MM re-equilibration after the MM->QM/MM Hamiltonian switch "
            "(smaller timestep; optional restraints; handoff policy applied here).\n"
        )
        if qmmm_transition_init:
            lines.append(
                f"  It writes INITIALIZATION_METHOD={qmmm_transition_init} explicitly because velocities are not inherited silently.\n"
            )
        if qmmm_transition_seed is not None:
            lines.append(f"  It writes GLOBAL SEED={int(qmmm_transition_seed)} explicitly for reproducible fresh stochastic initialization.\n")
        lines.append("- 40_qmmm_md starts production from 35_qmmm_warmup restart.\n")
    else:
        lines.append("- 40_qmmm_md starts directly from 30_npt_mm using conservative restart flags.\n")
    lines.append(
        "- Coordinates and cell are always restarted across stage boundaries; velocity carry-over follows explicit stage policy.\n"
    )

    with open(out_path, 'w') as f:
        f.writelines(lines)
    return out_path


# ─── CP2K Input Assembler ────────────────────────────────────────────────────

PRESETS = {
    'test': {'steps': 10, 'timestep': 0.5, 'temperature': 300.0, 'ensemble': 'NVT', 'desc': 'Quick validation (10 steps)'},
    'equilibration': {'steps': 1000, 'timestep': 0.5, 'temperature': 300.0, 'ensemble': 'NVT', 'desc': 'Short equilibration (1000 steps, 0.5 fs)'},
    # 0.5 fs: QM hydrogens cannot use SHAKE/RATTLE constraints, so 1.0 fs
    # risks energy drift and SCF failures from overstretched bonds.
    'production': {'steps': 100000, 'timestep': 0.5, 'temperature': 300.0, 'ensemble': 'NVT', 'desc': 'Production MD (100k steps, 0.5 fs)'},
    'custom': {'steps': 100000, 'timestep': 1.0, 'temperature': 300.0, 'ensemble': 'NVT', 'desc': 'Custom MD setup (prompt for all MD parameters)'},
}
MD_ENSEMBLES = ('NVE', 'NVT', 'NPT_I', 'NPT_F', 'NPT_IA')
TRAJECTORY_FORMAT_CHOICES = ('DCD', 'XMOL')
DEFAULT_TRAJECTORY_FORMAT = 'DCD'
CP2K_RUN_TYPES = ('MD', 'GEO_OPT')
DFT_FUNCTIONALS = ('B3LYP', 'PBE0', 'PBE')
DFT_FUNCTIONAL_DESCRIPTIONS = {
    'B3LYP': 'Hybrid GGA (default; robust for enzyme active sites and charge analysis).',
    'PBE0': 'Hybrid PBE (robust general-purpose hybrid with PBE exchange/correlation).',
    'PBE': 'GGA (faster than hybrids; useful for screening runs).',
}
DEFAULT_QMMM_GEEP_LIB = 9
HYBRID_DFT_FUNCTIONALS = {'B3LYP', 'PBE0'}
QM_BASIS_SET_PRESETS = (
    'DZVP-MOLOPT-GTH',
    'DZVP-MOLOPT-SR-GTH',
    'TZVP-MOLOPT-GTH',
    'TZVP-MOLOPT-SR-GTH',
    'TZV2P-MOLOPT-GTH',
    'TZV2P-MOLOPT-SR-GTH',
)
ADMM_AUX_BASIS_CHOICES = ('cpFIT3', 'cFIT3', 'admm-dzp')
DEFAULT_ADMM_AUX_BASIS = 'cpFIT3'
ADMM_EXCH_CORRECTION_CHOICES = ('BECKE88X', 'PBEX')
STANDARD_BIO_ADMM_ELEMENTS = {'H', 'C', 'N', 'O', 'S', 'P'}
FIT3_AUX_ELEMENTS = {
    'H', 'B', 'C', 'N', 'O', 'F', 'AL', 'SI', 'P', 'S', 'CL', 'BR',
}
# ── admm-dzp (BASIS_ADMM_MOLOPT) curated element coverage ─────────────────────
# admm-dzp is a double-zeta polarised auxiliary basis distributed with CP2K in
# data/BASIS_ADMM_MOLOPT.  Its coverage is broader than the FIT3 families but
# still bounded: only elements for which Guidon, Hutter & VandeVondele
# parameterised an ADMM fit are present in the shipped file.  We pin the
# supported set here from the CP2K 2024.x release so the pre-flight check can
# refuse silently-missing Kinds *before* SCF initialisation instead of after a
# runtime parse error.  When the user has a newer CP2K release that extends the
# coverage, `scan_basis_file_for_admm_elements()` (below) opportunistically
# widens the set by reading the actual file on disk, and `--admm-allow-unverified`
# provides an expert override.
# Reference: Guidon, Hutter, VandeVondele, JCTC 6, 2348 (2010), Tables I–III;
#            CP2K manual §FORCE_EVAL/DFT/AUXILIARY_DENSITY_MATRIX_METHOD.
ADMM_DZP_CURATED_ELEMENTS = frozenset({
    'H', 'HE',
    'LI', 'BE', 'B', 'C', 'N', 'O', 'F', 'NE',
    'NA', 'MG', 'AL', 'SI', 'P', 'S', 'CL', 'AR',
    'K', 'CA',
    # First-row transition metals with published ADMM-DZP fits.
    'SC', 'TI', 'V', 'CR', 'MN', 'FE', 'CO', 'NI', 'CU', 'ZN',
    'GA', 'GE', 'AS', 'SE', 'BR', 'KR',
    'RB', 'SR',
    # Selected second-row TMs of biological relevance (Mo cofactors, W, Ag, Cd).
    'Y', 'ZR', 'NB', 'MO', 'RU', 'RH', 'PD', 'AG', 'CD',
    'I',
})
ADMM_EXCH_CORRECTION_DEFAULTS = {
    'B3LYP': 'BECKE88X',
    'PBE': 'PBEX',
    'PBE0': 'PBEX',
}
ADMM_AUX_BASIS_INFO = {
    'cpFIT3': {
        'basis_files': ('BASIS_ADMM',),
        'supported_elements': FIT3_AUX_ELEMENTS,
        'source': 'FIT3 family (Guidon et al. JCTC 2010, Table II)',
    },
    'cFIT3': {
        'basis_files': ('BASIS_ADMM',),
        'supported_elements': FIT3_AUX_ELEMENTS,
        'source': 'FIT3 family (Guidon et al. JCTC 2010, Table II)',
    },
    'admm-dzp': {
        'basis_files': ('BASIS_ADMM_MOLOPT',),
        'supported_elements': ADMM_DZP_CURATED_ELEMENTS,
        'source': 'ADMM-DZP (BASIS_ADMM_MOLOPT); curated pin, extensible via scan',
    },
}

TRANSITION_METALS = {
    'SC', 'TI', 'V', 'CR', 'MN', 'FE', 'CO', 'NI', 'CU', 'ZN',
    'Y', 'ZR', 'NB', 'MO', 'TC', 'RU', 'RH', 'PD', 'AG', 'CD',
    'HF', 'TA', 'W', 'RE', 'OS', 'IR', 'PT', 'AU', 'HG'
}

# ── Spectator d¹⁰ transition metals (A.1.b) ──────────────────────────────────
# Zn²⁺, Cd²⁺, and Hg²⁺ adopt d¹⁰ configurations in their standard
# biomolecular oxidation states and are closed-shell under routine SCF.
# They appear overwhelmingly as structural/Lewis-acid cofactors (zinc
# fingers, carbonic anhydrase, matrix metalloproteinases, cadmium-
# substitution probes) rather than as redox-active centres, so an
# "open-shell SCF" promotion triggered solely by their presence is
# usually unnecessary — the appropriate open-shell recipe when
# *multiplicity > 1* here is the ORGANIC_RADICAL_DIAG path (radical on a
# ligand) rather than METAL_RADICAL_DIAG (radical on the d-manifold,
# expects smearing).  Cu⁺ and Ag⁺/Au⁺ are nominally d¹⁰ as well but in
# proteins their oxidation state is not always known a priori (Cu¹⁺/Cu²⁺
# redox couples are common in blue copper sites, galactose oxidase,
# etc.) so they are NOT included in the spectator set — the user must
# opt in explicitly if their Cu centre is a pure Cu(I) spectator.
# Refs: Holm, Kennepohl, Solomon, Chem. Rev. 96, 2239 (1996) — structural
# vs redox roles of bioinorganic metals; Andreini et al., J. Biol. Inorg.
# Chem. 13, 1205 (2008) — metalloproteome distribution, d¹⁰ Zn/Cd/Hg.
SPECTATOR_D10_TM = {'ZN', 'CD', 'HG'}


def classify_tm_presence(qm_elements_upper):
    """Split TM presence in the QM region into redox vs spectator subsets.

    Parameters
    ----------
    qm_elements_upper : iterable of str
        Upper-case element symbols present in the QM region.

    Returns
    -------
    dict with keys:
        ``tm_present`` (set[str])         — all TMs in QM,
        ``redox_tm_present`` (set[str])   — TMs outside SPECTATOR_D10_TM,
        ``spectator_tm_present`` (set[str]) — TMs inside SPECTATOR_D10_TM,
        ``has_tm`` / ``has_redox_tm`` / ``has_spectator_tm`` booleans.

    The caller decides how to use the split — per
    feedback_no_silent_modifications the policy is to keep the existing
    behaviour (promote on *any* TM) as the non-interactive default and
    surface the spectator-only refinement as an advisory / opt-in prompt.
    """
    elems = {str(e).upper() for e in (qm_elements_upper or ())}
    tm_present = elems & TRANSITION_METALS
    redox = tm_present - SPECTATOR_D10_TM
    spectator = tm_present & SPECTATOR_D10_TM
    return {
        'tm_present': tm_present,
        'redox_tm_present': redox,
        'spectator_tm_present': spectator,
        'has_tm': bool(tm_present),
        'has_redox_tm': bool(redox),
        'has_spectator_tm': bool(spectator),
    }


# ── OT↔DIAG routing threshold (A.1.a) ────────────────────────────────────────
# Closed-shell QM regions above this atom-count cutoff route to the DIAG-mode
# (eigenvalue-resolving) ``MECHANISM_DIAG`` profile rather than to the
# ``ROUTINE_OT`` orbital-transformation profile.  The boundary surfaces as a
# named, citable constant — rather than a bare literal inside the recommender —
# so operators can audit and override it without patching the routing function.
#
# Rationale for the value (120 atoms):
#
#   • The CP2K OT minimiser (VandeVondele & Hutter, J. Chem. Phys. 127, 114105
#     (2007)) scales well for well-conditioned closed-shell problems up to a
#     few hundred atoms per QM region, but its linear-search preconditioner
#     becomes increasingly sensitive to near-degenerate frontier orbitals as
#     the QM region grows.  Empirically, biomolecular QM regions >≈120 atoms
#     (typical second-shell active site + two cofactor-coordinating residues)
#     start to benefit from an eigenvalue-resolving DIAG engine that can
#     observe the HOMO-LUMO gap directly during each SCF cycle.
#
#   • Goedecker, Rev. Mod. Phys. 71, 1085 (1999) — crossover analysis of
#     O(N) vs O(N³) SCF methods; establishes that the practical crossover
#     between OT-style and diagonalisation-style SCF is system-dependent
#     (conditioning, band-gap, basis-set quality) rather than a strict
#     function of atom count, motivating an adjustable threshold constant
#     rather than a hard-coded limit.
#
#   • BioExcel CP2K biomolecular best-practice notes (bioexcel.eu/cp2k) and
#     the CP2K tutorial "QM/MM with large QM regions" recommend the DIAG
#     engine for QM regions beyond roughly the size of a metal coordination
#     sphere + first solvation shell (≈100–150 atoms), matching the value
#     chosen here.
#
# Operators who want to override the threshold (e.g. for a large OT-suitable
# hybrid-DFT mechanism study that has been shown to converge well under OT)
# should rebind this constant before importing the recommender, or adjust it
# in their site-local fork with an explanatory comment.  Per the
# no-silent-modifications policy, the pipeline itself never promotes across
# this boundary without surfacing the decision in the run provenance.
QM_ATOM_COUNT_THRESHOLD_FOR_DIAG = 120


# ── SCF Electronic-Structure Profiles ─────────────────────────────────────────
#
# Each profile pairs a biomolecular application with the CP2K SCF engine it
# actually uses.  The 'engine' field ('OT' or 'DIAG') is authoritative: the
# assembler consults it to decide whether to emit &OT or &DIAGONALIZATION+&MIXING,
# so the numeric defaults inside each profile only carry parameters relevant to
# that engine.  OT profiles carry OT-relevant outer-loop settings; DIAG profiles
# carry ADDED_MOS and MIXING settings.  This prevents cross-contamination of
# controls that belong to different CP2K SCF regimes.
#
# ── Declarative metadata (read by the emitter at input-file assembly time) ─
#   'expects_smearing'  — whether the profile asks for Fermi-Dirac occupation
#                         smearing.  Smearing is a *metallic-prior* tool: it
#                         damps charge sloshing near the Fermi level of
#                         systems with a continuum of near-degenerate MOs
#                         (transition-metal clusters, solid-state DFT).  For
#                         organic π-radicals the HOMO-SOMO-LUMO spacing is
#                         chemically discrete and Fermi smearing introduces
#                         spurious fractional occupation that *prevents* the
#                         spin-polarised ground state from being found.
#                         Refs: Mermin, Phys. Rev. 137, A1441 (1965) —
#                         finite-T DFT foundation for metallic smearing;
#                         Rabuck & Scuseria, J. Chem. Phys. 110, 695 (1999) —
#                         smearing as a convergence aid for near-degenerate
#                         transition-metal systems only.
#   'level_shift'       — SCF level-shift parameter (a.u.).  Virtual orbitals
#                         are shifted up during density construction to
#                         prevent occupied/virtual swaps that drive sloshing
#                         in open-shell π-systems with near-degenerate
#                         frontier orbitals.  Ref: Saunders & Hillier,
#                         Int. J. Quantum Chem. 7, 699 (1973); CP2K Manual
#                         §CP2K_INPUT/FORCE_EVAL/DFT/SCF/LEVEL_SHIFT.
#                         None disables emission; positive values are Hartree.
#
# The old "FAST" profile is intentionally removed: quick-validation runs are
# handled by the pipeline's test preset and short-step MM stages, not by a
# separate SCF strategy with loosened convergence criteria.  Mixing SCF rigor
# with convenience shortcuts would misrepresent the electronic-structure quality.

SCF_PROFILES = {
    # ── OT engine ──────────────────────────────────────────────────────────
    'ROUTINE_OT': {
        'label': 'Protein binding / recognition QM/MM (routine OT)',
        'description': (
            'Routine closed-shell ground-state QM/MM for protein–ligand, '
            'protein–peptide, and enzyme–substrate binding.  Uses the CP2K '
            'Orbital Transformation (OT) minimiser, which is the documented '
            'efficient path for large biomolecular QM/MM with ADMM.'
        ),
        'engine': 'OT',
        'max_scf': 140,
        'eps_scf': 1.0e-6,
        'scf_guess': 'ATOMIC',
        'cholesky': None,
        'qs_eps_default': None,
        # OT profiles do not use ADDED_MOS or MIXING; these placeholders are
        # kept at zero / inert so the assembler never emits them for OT.
        'added_mos': 0,
        'mixing_method': 'DIRECT_P_MIXING',
        'mixing_alpha': 0.35,
        'nbroyden': 8,
        'outer_max_scf': 15,
        'outer_eps_scf': 1.0e-6,
        # OT minimises |ψ_occ⟩ directly; there is no virtual manifold to
        # smear or level-shift, so both knobs are inert here.
        'expects_smearing': False,
        'level_shift': None,
    },
    # ── DIAG engine ────────────────────────────────────────────────────────
    'MECHANISM_DIAG': {
        'label': 'Enzyme mechanism / higher-accuracy QM/MM (hybrid diagonalization)',
        'description': (
            'Reaction-mechanism studies, transition-state searches, or '
            'higher-accuracy hybrid-functional QM/MM that benefits from '
            'explicit eigenvalue resolution via diagonalisation with Broyden '
            'density mixing.  Use when larger QM regions (>120 atoms) or '
            'near-degenerate frontier orbitals make OT less robust.'
        ),
        'engine': 'DIAG',
        'max_scf': 220,
        'eps_scf': 3.0e-7,
        'scf_guess': 'ATOMIC',
        'cholesky': None,
        'qs_eps_default': None,
        'added_mos': 220,
        'mixing_method': 'BROYDEN_MIXING',
        'mixing_alpha': 0.18,
        'nbroyden': 8,
        'outer_max_scf': 25,
        'outer_eps_scf': 3.0e-7,
        # Closed-shell mechanism profile: no smearing, no level shift by
        # default; promotion to a radical profile (post-hoc) flips these.
        'expects_smearing': False,
        'level_shift': None,
    },
    # ── Organic open-shell π-radical profile ───────────────────────────────
    # Targets QM regions that are open-shell (UKS) but contain NO transition
    # metals: flavin semiquinones, quinones, phenoxyl/tyrosyl radicals,
    # nitroxides, porphyrin π-cation radicals, NADH/NAD•, etc.  In these
    # systems the unpaired-spin density lives on a small set of discrete
    # π-type orbitals, not on a continuum; Fermi smearing is inappropriate
    # and actively harmful (it fractionalises the SOMO and drives the SCF
    # into charge-transfer sloshing between π-systems, e.g. between FAD and
    # a bound aromatic substrate in flavoenzymes).
    #
    # The convergence recipe here is:
    #   (i) Pulay DIIS (BROYDEN_MIXING in CP2K's &MIXING with moderate
    #       alpha and deeper history is Pulay-equivalent in practice;
    #       Pulay, Chem. Phys. Lett. 73, 393 (1980); Kudin–Scuseria–Cances,
    #       J. Chem. Phys. 116, 8255 (2002) on EDIIS/ADIIS refinements).
    #   (ii) LEVEL_SHIFT ≈ 0.15 Ha to penalise occ↔virt swaps during
    #        density construction (Saunders & Hillier 1973).
    #   (iii) A modest ADDED_MOS buffer so the diagonaliser exposes the
    #        low-lying virtuals that define the radical without enabling
    #        smearing over them.
    #   (iv) No &SMEAR.  The SOMO is physically discrete.
    #   (v) Deeper OUTER_SCF so residual linear-response instabilities
    #        (e.g. admixture of diradical character in a nominal doublet)
    #        can relax before declaring convergence.
    'ORGANIC_RADICAL_DIAG': {
        'label': 'Organic open-shell π-radical QM/MM (UKS diagonalization, no smearing)',
        'description': (
            'Open-shell biomolecular QM regions with no transition metals: '
            'flavin/semiquinone, tyrosyl/phenoxyl radical, nitroxide, '
            'NADH·/NAD•, porphyrin π-cation radical, and similar organic '
            'radicals.  Uses DIAG+Broyden mixing with a level shift, no '
            'Fermi smearing, and a modest ADDED_MOS buffer — the strategy '
            'that matches the discrete SOMO structure of organic radicals '
            'and avoids the metallic-prior bias of smearing.'
        ),
        'engine': 'DIAG',
        'max_scf': 240,
        'eps_scf': 5.0e-7,
        'scf_guess': 'ATOMIC',
        'cholesky': None,
        'qs_eps_default': None,
        # ADDED_MOS = 50 exposes enough virtual orbitals for the diagonaliser
        # to see the SOMO/LUMO neighbourhood without turning on occupation
        # fractionation.  Larger values waste memory; smaller values risk
        # premature cutoff of the virtual manifold needed for DIIS stability.
        'added_mos': 50,
        # Broyden mixing with alpha≈0.15 and depth≈10 is the Pulay-regime
        # sweet spot for organic open-shell SCF: enough history to damp the
        # two-cycle π↔π charge-transfer oscillation without over-damping
        # legitimate density updates.  Alpha was chosen inside the CP2K
        # recommended range [0.05, 0.2] for DIIS-like mixing on difficult
        # SCF problems (CP2K Manual, MIXING section).
        'mixing_method': 'BROYDEN_MIXING',
        'mixing_alpha': 0.15,
        'nbroyden': 10,
        'outer_max_scf': 30,
        'outer_eps_scf': 5.0e-7,
        # ── Profile-declarative metadata ─────────────────────────────────
        # No smearing: see header commentary (Mermin 1965 applies to the
        # metallic limit only; organic SOMO is discrete).
        'expects_smearing': False,
        # LEVEL_SHIFT in Hartree.  0.15 Ha ≈ 4.1 eV is large enough to
        # dominate typical organic π-HOMO/π-LUMO near-degeneracies but
        # small enough to leave the converged energies essentially
        # unaffected (the level shift is removed at convergence by the
        # self-consistent rediagonalisation).
        # Ref: Saunders & Hillier, Int. J. Quantum Chem. 7, 699 (1973).
        'level_shift': 0.15,
    },
    'METAL_RADICAL_DIAG': {
        'label': 'Metal or radical active site (UKS diagonalization)',
        'description': (
            'Transition-metal active sites with open-shell d-electron '
            'configurations.  Uses conservative Broyden mixing with low '
            'alpha, deep history, and Fermi-Dirac smearing because d-block '
            'ligand-field manifolds are genuinely near-degenerate and the '
            'metallic-prior smearing kernel is the physically correct aid. '
            'For organic radicals without a transition metal, use '
            'ORGANIC_RADICAL_DIAG instead — smearing there is harmful.'
        ),
        'engine': 'DIAG',
        'max_scf': 260,
        'eps_scf': 5.0e-7,
        'scf_guess': 'ATOMIC',
        'cholesky': None,
        'qs_eps_default': None,
        'added_mos': 260,
        'mixing_method': 'BROYDEN_MIXING',
        'mixing_alpha': 0.10,
        'nbroyden': 15,
        'outer_max_scf': 35,
        'outer_eps_scf': 5.0e-7,
        # Smearing on: justified by the near-degenerate d-manifold of TMs.
        # Ref: Rabuck & Scuseria, J. Chem. Phys. 110, 695 (1999).
        'expects_smearing': True,
        # No LEVEL_SHIFT by default: when combined with smearing on a
        # near-degenerate d-manifold, a static level shift can trap the
        # wrong spin state by locking an incorrect occupation pattern.
        'level_shift': None,
    },
    'ADVANCED': {
        'label': 'Advanced electronic-structure controls (manual)',
        'description': (
            'Full manual control over diagonalisation SCF parameters, '
            'CHOLESKY mode, and Quickstep EPS_DEFAULT.  Intended for '
            'specialists who need non-standard convergence strategies.'
        ),
        'engine': 'DIAG',
        'max_scf': 140,
        'eps_scf': 1.0e-6,
        'scf_guess': 'ATOMIC',
        'cholesky': None,
        'qs_eps_default': None,
        'added_mos': 120,
        'mixing_method': 'DIRECT_P_MIXING',
        'mixing_alpha': 0.35,
        'nbroyden': 8,
        'outer_max_scf': 15,
        'outer_eps_scf': 1.0e-6,
        # ADVANCED is opt-in: user is assumed to know what they want.
        'expects_smearing': False,
        'level_shift': None,
    },
}

# Ordered list for the interactive wizard display.
SCF_PROFILE_DISPLAY_ORDER = (
    'ROUTINE_OT',
    'MECHANISM_DIAG',
    # Organic π-radicals (flavin, tyrosyl, quinone, nitroxide, …) go
    # through their own DIAG recipe without Fermi smearing; displayed
    # separately from METAL_RADICAL_DIAG because the two populations
    # need opposite convergence strategies.
    'ORGANIC_RADICAL_DIAG',
    'METAL_RADICAL_DIAG',
    'ADVANCED',
)

def _validate_scf_profile_key(raw_key):
    """Validate that *raw_key* is one of the canonical SCF_PROFILES keys."""
    key = str(raw_key or '').strip().upper()
    if key in SCF_PROFILES:
        return key
    allowed = ', '.join(SCF_PROFILES.keys())
    raise ValueError(f"Unknown SCF profile '{raw_key}'.  Allowed: {allowed}")
SCF_CHOLESKY_MODES = ('RESTORE', 'INVERSE', 'OFF')

# ── SCF_GUESS canonical choice list (A.3.a) ──────────────────────────────────
# CP2K accepts several flavours for the initial-guess method in
# &FORCE_EVAL/DFT/SCF/SCF_GUESS (CP2K Manual §CP2K_INPUT/FORCE_EVAL/DFT/SCF).
# The pipeline exposes four here because they cover every realistic
# biomolecular QM/MM entry point while refusing the ones that are unsound for
# a production run (HISTORY_RESTART requires a specific CP2K build; NONE is a
# debug placeholder).  Surfacing the canonical enum as a module-level tuple
# lets the interactive wizard, the downstream emitter, and future bulk
# invocations share one source of truth and lets the validator catch silent
# typos early rather than at CP2K parse time.
#
#   * ATOMIC  — superposition of atomic densities.  Cheap and adequate for
#               most closed-shell organic/biomolecular QM regions.  This is
#               the pipeline's conservative default.
#   * RESTART — reuse a wavefunction file from a previous converged run
#               (WFN_RESTART_FILE_NAME).  The emitter promotes to RESTART
#               automatically when a restart filename is wired up.
#   * MOPAC   — semi-empirical PM6/PM7 pre-SCF.  Provides a non-trivial
#               initial density with realistic spin distribution and is the
#               recommended choice for transition-metal d-manifold systems
#               where ATOMIC oscillates between charge-transfer states.
#               Refs: Stewart, J. Mol. Model. 13, 1173 (2007) (PM6);
#               J. Mol. Model. 19, 1 (2013) (PM7).
#   * CORE    — bare-Hamiltonian eigenvectors.  Mostly a diagnostic
#               fallback; rarely competitive with ATOMIC in practice, but
#               documented in the CP2K manual so we retain it as a
#               user-selectable option.
#
# Policy: per feedback_no_silent_modifications the pipeline never auto-
# promotes between these choices outside of the RESTART-filename path
# (which is an explicit wiring signal from the caller, not a silent
# promotion).  Every other transition requires an interactive prompt or a
# WARN in non-interactive mode and is recorded in run_provenance.
SCF_GUESS_CHOICES = ('ATOMIC', 'RESTART', 'MOPAC', 'CORE')


def validate_scf_guess(scf_guess):
    """Normalize and validate an SCF_GUESS value against ``SCF_GUESS_CHOICES``.

    Returns the canonical upper-case token.  Raises ``ValueError`` for any
    token outside the canonical choice list so a typo in a wizard transcript,
    config file, or programmatic caller is caught before CP2K sees it.
    """
    if scf_guess is None:
        return 'ATOMIC'
    value = str(scf_guess).strip().upper()
    if not value:
        return 'ATOMIC'
    if value not in SCF_GUESS_CHOICES:
        allowed = ', '.join(SCF_GUESS_CHOICES)
        raise ValueError(
            f"Invalid SCF_GUESS '{scf_guess}'. Allowed values: {allowed}"
        )
    return value

QUICKSTEP_EPS_DEFAULT = 1.0e-10
DEFAULT_MGRID_NGRIDS = 4
MOLOPT_DIFFUSE_MGRID_NGRIDS = 5
# CP2K &QS defaults are generic ASPC/3, but the CP2K MD guide is more
# specific: for MD a good extrapolation is PS with EXTRAPOLATION_ORDER 3.
MD_QS_EXTRAPOLATION = 'PS'
MD_QS_EXTRAPOLATION_ORDER = 3
# CP2K defaults TRAJECTORY/FORMAT to XMOL, but this pipeline intentionally
# promotes DCD for large periodic biomolecular MD because CP2K documents it as
# the binary trajectory format with cell information and it is more practical
# than text XYZ-style output for large runs.
TRAJECTORY_FORMAT_SUMMARY = {
    'DCD': 'binary trajectory with cell information',
    'XMOL': 'text XYZ-style trajectory',
}
# CP2K FORCEFIELD defaults EI_SCALE14/VDW_SCALE14 to 1.0/1.0. The pipeline
# writes explicit runtime 1-4 scaling instead of leaving AMBER behavior as an
# implicit side effect of preserved PRMTOP SCEE/SCNB arrays.
MM_SCALE14_POLICIES = OrderedDict((
    (
        'AMBER_RECOMMENDED',
        'Recommended standard AMBER biomolecular runtime scaling '
        '(EI_SCALE14 1/1.2, VDW_SCALE14 1/2.0)',
    ),
    (
        'CP2K_EXPLICIT',
        'Explicit CP2K EI_SCALE14/VDW_SCALE14 runtime scaling values',
    ),
    (
        'MANUAL_OVERRIDE',
        'Expert override with explicit CP2K EI_SCALE14/VDW_SCALE14 values',
    ),
))
DEFAULT_MM_SCALE14_POLICY = 'AMBER_RECOMMENDED'
AMBER_BIOMOLECULAR_SCEE = 1.2
AMBER_BIOMOLECULAR_SCNB = 2.0
DEFAULT_EI_SCALE14 = 1.0 / AMBER_BIOMOLECULAR_SCEE
DEFAULT_VDW_SCALE14 = 1.0 / AMBER_BIOMOLECULAR_SCNB
SAMPLING_METHODS = OrderedDict((
    ('METADYNAMICS', 'CP2K FREE_ENERGY/METADYN with explicit COLVAR definitions'),
    ('UMBRELLA', 'CP2K FREE_ENERGY METHOD UI with harmonic COLLECTIVE/RESTRAINT windows'),
))
SAMPLING_COLVAR_TYPES = ('DISTANCE', 'ANGLE', 'TORSION', 'COORDINATION')
# CP2K OT guidance: FULL_ALL with an explicit small ENERGY_GAP=1.0E-3 is the
# robust default for most systems, and FULL_ALL expects that gap to be an
# underestimate of the HOMO-LUMO gap. CG is the most reliable OT minimizer.
OT_MINIMIZERS = ('CG', 'DIIS')
DEFAULT_OT_MINIMIZER = 'CG'
DEFAULT_OT_PRECONDITIONER = 'FULL_ALL'
DEFAULT_OT_ENERGY_GAP = 1.0e-3
# CP2K documents OT/STEPSIZE as the initial line-search step and allows
# negative values to delegate the choice back to CP2K, which then selects a
# preconditioner-dependent value. The pipeline therefore makes the ownership of
# STEPSIZE explicit: automatic by default, manual only on user request.
OT_STEPSIZE_POLICIES = OrderedDict((
    (
        'AUTO',
        'Recommended: emit STEPSIZE -1.0 so CP2K chooses the preconditioner-dependent initial line-search step',
    ),
    (
        'MANUAL',
        'Expert/reproducibility override: emit an explicit positive STEPSIZE value',
    ),
))
DEFAULT_OT_STEPSIZE_POLICY = 'AUTO'
CP2K_AUTO_OT_STEPSIZE = -1.0
OT_PRECONDITIONER_DEFAULT_STEPSIZES = {
    'NONE': 0.15,
    'FULL_SINGLE': 0.15,
    'FULL_SINGLE_INVERSE': 0.08,
    'FULL_ALL': 0.15,
    'FULL_KINETIC': 0.15,
    'FULL_S_INVERSE': 0.15,
}

# ── A.4.a: OT ENERGY_GAP ↔ preconditioner guidance ────────────────────────────
# CP2K's OT minimiser solves the inner linear system with a preconditioner
# that is regularised by ENERGY_GAP (an *underestimate* of the HOMO-LUMO gap
# — CP2K Manual §FORCE_EVAL/DFT/SCF/OT/ENERGY_GAP).  Each preconditioner
# responds to that regulariser differently:
#
#   * FULL_ALL — inverts the full projected matrix.  The CP2K documentation
#     and benchmark set (VandeVondele & Hutter, J. Chem. Phys. 118, 4365
#     (2003), §III) recommend ENERGY_GAP ≈ 1.0E-3 as a gap underestimate
#     that stabilises the inversion without over-damping the line search.
#     This is the pipeline's DEFAULT_OT_ENERGY_GAP.
#   * FULL_SINGLE_INVERSE — single-precision O(N²) inverse, cheaper but
#     numerically looser.  The CP2K tutorials (Iannuzzi, CECAM QM/MM and
#     BioExcel QM/MM best-practice notes) suggest a larger gap, ~1.0E-2,
#     because the approximate inverse amplifies small-gap sensitivity and
#     1.0E-3 tends to over-shoot in open-shell or near-metallic systems.
#   * FULL_KINETIC — diagonal kinetic-energy preconditioner, much milder;
#     the ENERGY_GAP is largely a safety net and the value is not
#     critical (see CP2K Manual notes; ~1.0E-3 remains acceptable).
#   * FULL_S_INVERSE / FULL_SINGLE — intermediate regimes; CP2K documentation
#     recommends using the FULL_ALL default unless specific evidence suggests
#     otherwise.
#   * NONE — no preconditioner; ENERGY_GAP is effectively unused.
#
# The table below encodes the *recommended* gap per preconditioner.  It is
# consulted by ``advise_ot_energy_gap_for_preconditioner`` which surfaces an
# advisory (interactive prompt or WARN) whenever the operator leaves
# ENERGY_GAP at the FULL_ALL default while selecting a non-FULL_ALL
# preconditioner — a commonly overlooked mismatch that silently degrades
# OT convergence without changing any explicit keyword.  Per
# feedback_no_silent_modifications, the helper never rewrites the value on
# its own; it only prompts or warns.
OT_PRECONDITIONER_RECOMMENDED_ENERGY_GAP = {
    'FULL_ALL':            1.0e-3,
    'FULL_SINGLE_INVERSE': 1.0e-2,
    'FULL_SINGLE':         1.0e-3,
    'FULL_KINETIC':        1.0e-3,
    'FULL_S_INVERSE':      1.0e-3,
    'NONE':                None,  # gap unused
}


def advise_ot_energy_gap_for_preconditioner(
    ot_preconditioner,
    ot_energy_gap,
    interactive=False,
    run_provenance=None,
):
    """Advise the operator when ENERGY_GAP may be miscalibrated for the
    chosen OT preconditioner.

    Returns the (possibly-updated) ``ot_energy_gap``.  The value is only
    changed when the operator explicitly consents in an interactive prompt.
    In non-interactive mode a WARN is emitted and the input value is
    returned unchanged, per feedback_no_silent_modifications.

    References
    ----------
    VandeVondele & Hutter, J. Chem. Phys. 118, 4365 (2003) — original OT
    convergence study and the source of ENERGY_GAP=1.0E-3 for FULL_ALL.
    CP2K Manual §FORCE_EVAL/DFT/SCF/OT (ENERGY_GAP, PRECONDITIONER).
    """
    precond_key = str(ot_preconditioner or '').strip().upper()
    recommended = OT_PRECONDITIONER_RECOMMENDED_ENERGY_GAP.get(precond_key)
    # If the preconditioner is not in the table, fall back silently: this is
    # not a known/advised preconditioner, so we have no authoritative gap
    # guidance to offer.  Unknown-preconditioner handling is a separate concern.
    if recommended is None:
        return float(ot_energy_gap)
    current = float(ot_energy_gap)
    # Tolerate small floating-point drift (the emitter formats with one
    # significant figure; don't prompt on 9.999E-4 vs 1.000E-3).
    if abs(current - recommended) <= 0.05 * recommended:
        return current
    message = (
        f"OT ENERGY_GAP={current:.1E} is set for the FULL_ALL default regime; "
        f"with PRECONDITIONER={precond_key} the CP2K-documented recommendation "
        f"is ENERGY_GAP≈{recommended:.1E} (gap underestimate scales with the "
        "preconditioner's numerical looseness)."
    )
    updated = current
    accepted = False
    source = 'non_interactive_warn'
    if interactive:
        source = 'interactive_prompt'
        detail(message)
        if ask_yes(
            f"Adjust ENERGY_GAP to the preconditioner-matched recommendation "
            f"({recommended:.1E})?",
            default=True,
        ):
            updated = float(recommended)
            accepted = True
    else:
        warn(message)
    if run_provenance is not None:
        run_provenance.record(
            kind='ot_energy_gap_preconditioner_mismatch',
            severity='recommendation',
            source=source,
            from_value=f"{current:.1E}",
            to_value=f"{updated:.1E}",
            accepted=accepted,
            reason=(
                f"ENERGY_GAP default (1.0E-3) is FULL_ALL-tuned; "
                f"{precond_key} benefits from a preconditioner-matched gap."
            ),
            citation=(
                "VandeVondele & Hutter, J. Chem. Phys. 118, 4365 (2003); "
                "CP2K Manual §FORCE_EVAL/DFT/SCF/OT/ENERGY_GAP"
            ),
        )
    return updated
# CP2K HF/MEMORY/MAX_MEMORY is a per-MPI-rank limit, not a whole-job limit.
# Keep the pipeline default conservative and explicit rather than trying to
# infer a safe value from node memory without knowing the final launch layout.
DEFAULT_HF_MAX_MEMORY = 2000
# Periodic QM/MM MULTIPOLE/RCUT is limited by half the QM cell. The pipeline
# therefore treats QM-cell padding and target RCUT as one linked policy: try to
# size the QM cell so the target RCUT is geometrically safe, but make any
# box-limited relaxation explicit instead of hiding it in a clamp heuristic.
DEFAULT_QMMM_QM_CELL_PADDING = 6.0
DEFAULT_QMMM_TARGET_MULTIPOLE_RCUT = 8.0
DEFAULT_QMMM_MINIMUM_IMAGE_BUFFER = 1.0
MIN_QMMM_GEOMETRIC_RCUT_MARGIN = 0.1
# CP2K's built-in tutorials and thermostat documentation distinguish short
# CSVR time constants for active equilibration from weaker production coupling.
# Keep the standard production MD thermostat conservative, but make the first
# QM/MM transition stage explicitly use a stronger coupling so the Hamiltonian
# switch is treated as re-equilibration rather than as a silent restart detail.
DEFAULT_MD_THERMOSTAT_TIMECON_FS = 100.0
DEFAULT_MD_BAROSTAT_TIMECON_FS = 1000.0
DEFAULT_QMMM_TRANSITION_THERMOSTAT_TIMECON_FS = 10.0
# CP2K's documented GLOBAL%SEED default is 2000. Emit it explicitly on the
# first QM/MM stage when fresh stochastic initialization/state is desired so the
# handoff remains reviewable and reproducible instead of relying on omission.
DEFAULT_QMMM_TRANSITION_SEED = 2000
QMMM_HANDOFF_POLICIES = OrderedDict((
    (
        'RESET_DYNAMICS',
        'Recommended: restart positions and cell only at the first QM/MM stage; let CP2K generate fresh velocities and fresh thermostat/barostat/RNG state on the new Hamiltonian',
    ),
    (
        'REUSE_VELOCITIES',
        'Expert: restart positions, cell, and velocities at the first QM/MM stage, but reset thermostat/barostat/RNG/counters',
    ),
    (
        'FULL_STATE_CONTINUITY',
        'Expert/diagnostic: restart positions, cell, velocities, and thermostat/barostat/RNG/counters across the MM->QM/MM Hamiltonian switch',
    ),
))
DEFAULT_QMMM_HANDOFF_POLICY = 'RESET_DYNAMICS'

def validate_run_type(run_type):
    """Normalize and validate CP2K RUN_TYPE."""
    value = str(run_type or "").strip().upper()
    if value not in CP2K_RUN_TYPES:
        allowed = ", ".join(CP2K_RUN_TYPES)
        raise ValueError(f"Invalid CP2K RUN_TYPE '{run_type}'. Allowed values: {allowed}")
    return value


def validate_qmmm_periodic_value(value, keyword, minimum=1.0e-8):
    """Validate one numeric QM/MM periodic electrostatics policy value."""
    try:
        parsed = float(value)
    except Exception as exc:
        raise ValueError(f"{keyword} must be numeric. Got {value!r}.") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{keyword} must be finite. Got {parsed!r}.")
    if parsed < float(minimum):
        raise ValueError(f"{keyword} must be >= {float(minimum):g}. Got {parsed}.")
    return parsed


def make_qmmm_periodic_policy(
    qm_cell_padding=DEFAULT_QMMM_QM_CELL_PADDING,
    target_multipole_rcut=DEFAULT_QMMM_TARGET_MULTIPOLE_RCUT,
    minimum_image_buffer=DEFAULT_QMMM_MINIMUM_IMAGE_BUFFER,
):
    """Create a validated linked policy for periodic QM/MM cell sizing and RCUT."""
    padding = validate_qmmm_periodic_value(qm_cell_padding, "QM cell padding")
    target_rcut = validate_qmmm_periodic_value(
        target_multipole_rcut,
        "QMMM MULTIPOLE target RCUT",
    )
    image_buffer = validate_qmmm_periodic_value(
        minimum_image_buffer,
        "QMMM minimum-image buffer",
    )
    is_default = (
        abs(padding - DEFAULT_QMMM_QM_CELL_PADDING) <= 1.0e-12
        and abs(target_rcut - DEFAULT_QMMM_TARGET_MULTIPOLE_RCUT) <= 1.0e-12
        and abs(image_buffer - DEFAULT_QMMM_MINIMUM_IMAGE_BUFFER) <= 1.0e-12
    )
    if is_default:
        label = "Biomolecular periodic QM/MM default"
        reason = (
            "Links QM-cell padding and MULTIPOLE RCUT explicitly so compact QM regions "
            "still target a reviewable biomolecular real-space electrostatic reach."
        )
    else:
        label = "Manual periodic QM/MM override"
        reason = (
            "User-selected QM-cell padding and/or target MULTIPOLE RCUT. "
            "The generator will still enforce geometric safety and warn if the MM box limits the target."
        )
    return QMMMPeriodicPolicy(
        qm_cell_padding=float(padding),
        target_multipole_rcut=float(target_rcut),
        minimum_image_buffer=float(image_buffer),
        label=label,
        reason=reason,
    )


def normalize_qmmm_handoff_policy_mode(mode):
    """Normalize the MM→QM/MM handoff policy mode."""
    value = str(mode or DEFAULT_QMMM_HANDOFF_POLICY).strip().upper()
    aliases = {
        'DEFAULT': 'RESET_DYNAMICS',
        'CONSERVATIVE': 'RESET_DYNAMICS',
        'RESET': 'RESET_DYNAMICS',
        'RESET_STATE': 'RESET_DYNAMICS',
        'REGENERATE_VELOCITIES': 'RESET_DYNAMICS',
        'FRESH_VELOCITIES': 'RESET_DYNAMICS',
        'REUSE': 'REUSE_VELOCITIES',
        'VELOCITIES': 'REUSE_VELOCITIES',
        'FULL_STATE': 'FULL_STATE_CONTINUITY',
        'CONTINUITY': 'FULL_STATE_CONTINUITY',
        'FULL': 'FULL_STATE_CONTINUITY',
    }
    resolved = aliases.get(value, value)
    if resolved not in QMMM_HANDOFF_POLICIES:
        allowed = ", ".join(QMMM_HANDOFF_POLICIES.keys())
        raise ValueError(f"Invalid QM/MM handoff policy '{mode}'. Allowed values: {allowed}")
    return resolved


def make_qmmm_handoff_policy(mode=None, handoff_restart_velocities=None):
    """Create a validated MM→QM/MM handoff policy.

    Positions and cell continuity are always preserved at the first QM/MM
    stage. This policy only governs whether velocities and dynamical state
    (thermostat/barostat/RNG/counters) are reused across the Hamiltonian
    change from MM to QM/MM.
    """
    if mode is None and handoff_restart_velocities is not None:
        mode = 'REUSE_VELOCITIES' if bool(handoff_restart_velocities) else DEFAULT_QMMM_HANDOFF_POLICY
    resolved = normalize_qmmm_handoff_policy_mode(mode)
    if resolved == 'RESET_DYNAMICS':
        return QMMMHandoffPolicy(
            mode=resolved,
            restart_velocities=False,
            restart_counters=False,
            restart_thermostat=False,
            restart_barostat=False,
            restart_randomg=False,
            label='Reset MM dynamical state at the first QM/MM stage',
            reason=(
                'Carry coordinates and cell across the Hamiltonian change, but start QM/MM '
                'with fresh velocities and fresh thermostat/barostat/RNG state.'
            ),
        )
    if resolved == 'REUSE_VELOCITIES':
        return QMMMHandoffPolicy(
            mode=resolved,
            restart_velocities=True,
            restart_counters=False,
            restart_thermostat=False,
            restart_barostat=False,
            restart_randomg=False,
            label='Reuse MM velocities only at the first QM/MM stage',
            reason=(
                'Carry velocities across the Hamiltonian change, but reset thermostat/barostat/RNG '
                'state so the first QM/MM stage can re-equilibrate explicitly.'
            ),
        )
    return QMMMHandoffPolicy(
        mode='FULL_STATE_CONTINUITY',
        restart_velocities=True,
        restart_counters=True,
        restart_thermostat=True,
        restart_barostat=True,
        restart_randomg=True,
        label='Full MM dynamical-state continuity into QM/MM',
        reason=(
            'Carry velocities and thermostat/barostat/RNG/counters across the MM→QM/MM '
            'Hamiltonian switch. Use only when deliberate continuity is more important than conservative re-equilibration.'
        ),
    )


def qmmm_handoff_ext_restart_config(restart_file_name, qmmm_handoff_policy):
    """Create the first-QM/MM EXT_RESTART block from a handoff policy."""
    policy = qmmm_handoff_policy or make_qmmm_handoff_policy()
    if not isinstance(policy, QMMMHandoffPolicy):
        raise TypeError("qmmm_handoff_policy must be a QMMMHandoffPolicy instance or None.")
    return make_ext_restart_config(
        restart_file_name=restart_file_name,
        restart_pos=True,
        restart_vel=policy.restart_velocities,
        restart_cell=True,
        restart_counters=policy.restart_counters,
        restart_thermostat=policy.restart_thermostat,
        restart_barostat=policy.restart_barostat,
        restart_randomg=policy.restart_randomg,
    )


def validate_md_timecon(timecon_fs, label, minimum=1.0e-8):
    """Validate one MD thermostat/barostat time constant."""
    try:
        parsed = float(timecon_fs)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {label} '{timecon_fs}'.") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{label} must be finite. Got {parsed!r}.")
    if parsed < minimum:
        raise ValueError(f"{label} must be >= {minimum}. Got {parsed}.")
    return float(parsed)


def validate_global_seed(seed, label="GLOBAL SEED"):
    """Validate an explicit CP2K integer seed or None."""
    if seed is None or seed == "":
        return None
    try:
        parsed = int(seed)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {label} '{seed}'.") from exc
    if parsed < 0:
        raise ValueError(f"{label} must be >= 0. Got {parsed}.")
    return int(parsed)


def normalize_md_initialization_method(method):
    """Normalize CP2K MD INITIALIZATION_METHOD or None."""
    if method is None:
        return None
    value = str(method).strip().upper()
    if not value:
        return None
    allowed = ("DEFAULT", "VIBRATIONAL")
    if value not in allowed:
        raise ValueError(
            f"Invalid MD INITIALIZATION_METHOD '{method}'. Allowed values: {', '.join(allowed)}"
        )
    return value


def make_md_dynamics_config(
    thermostat_timecon_fs=DEFAULT_MD_THERMOSTAT_TIMECON_FS,
    barostat_timecon_fs=DEFAULT_MD_BAROSTAT_TIMECON_FS,
    initialization_method=None,
    global_seed=None,
    label="Standard MD control",
    reason=(
        "Standard staged MD control: inherit or continue dynamical state when restart policy allows it, "
        "with conservative production-strength thermostat/barostat coupling."
    ),
):
    """Create validated stage-local MD control settings."""
    return MDDynamicsConfig(
        thermostat_timecon_fs=validate_md_timecon(thermostat_timecon_fs, "MD thermostat TIMECON"),
        barostat_timecon_fs=validate_md_timecon(barostat_timecon_fs, "MD barostat TIMECON"),
        initialization_method=normalize_md_initialization_method(initialization_method),
        global_seed=validate_global_seed(global_seed),
        label=str(label),
        reason=str(reason),
    )


def make_first_qmmm_stage_dynamics(
    qmmm_handoff_policy,
    transition_thermostat_timecon_fs=DEFAULT_QMMM_TRANSITION_THERMOSTAT_TIMECON_FS,
    transition_seed=DEFAULT_QMMM_TRANSITION_SEED,
):
    """Create explicit MD control for the first QM/MM stage after MM.

    This stage owns the Hamiltonian switch. When thermostat/RNG state is not
    restarted, make the re-equilibration policy explicit instead of relying on
    generic MD defaults.
    """
    policy = qmmm_handoff_policy or make_qmmm_handoff_policy()
    if not isinstance(policy, QMMMHandoffPolicy):
        raise TypeError("qmmm_handoff_policy must be a QMMMHandoffPolicy instance or None.")
    if policy.restart_thermostat or policy.restart_barostat or policy.restart_randomg:
        return make_md_dynamics_config(
            label="Full-state MM->QM/MM continuity",
            reason=(
                "Expert continuity override: the first QM/MM stage restarts thermostat/barostat/RNG state, "
                "so the standard production-strength MD control is preserved."
            ),
        )
    init_method = None
    reason = (
        "First QM/MM stage after the MM->QM/MM Hamiltonian switch: keep coordinates/cell continuity, "
        "but make the new-stage thermalization explicit with a short CSVR time constant."
    )
    if not policy.restart_velocities:
        init_method = "DEFAULT"
        reason += (
            " Velocities are regenerated explicitly from TEMPERATURE with CP2K INITIALIZATION_METHOD DEFAULT."
        )
    seed_value = validate_global_seed(transition_seed)
    if seed_value is not None:
        reason += " An explicit GLOBAL SEED keeps the first-QM/MM-stage stochastic initialization reviewable."
    return make_md_dynamics_config(
        thermostat_timecon_fs=transition_thermostat_timecon_fs,
        initialization_method=init_method,
        global_seed=seed_value,
        label="Explicit QM/MM transition thermalization",
        reason=reason,
    )


def evaluate_qmmm_periodic_electrostatics(qm_cell_abc, qmmm_periodic_policy=None):
    """Resolve the effective periodic QM/MM MULTIPOLE RCUT from the QM cell."""
    policy = qmmm_periodic_policy or make_qmmm_periodic_policy()
    if not isinstance(policy, QMMMPeriodicPolicy):
        raise TypeError("qmmm_periodic_policy must be a QMMMPeriodicPolicy instance or None.")
    cell_parts = [float(x) for x in str(qm_cell_abc).split()]
    if len(cell_parts) < 3:
        raise ValueError(f"QM cell ABC must contain three lengths. Got {qm_cell_abc!r}.")
    cell_lengths = tuple(float(x) for x in cell_parts[:3])
    half_min_cell = 0.5 * min(cell_lengths)
    target_rcut = float(policy.target_multipole_rcut)
    requested_buffer = float(policy.minimum_image_buffer)
    buffered_limit = half_min_cell - requested_buffer
    buffer_relaxed = buffered_limit <= 0.0
    if buffer_relaxed:
        # If the requested buffer does not fit inside the QM cell, keep RCUT
        # strictly below half the cell with a tiny explicit geometric margin.
        max_valid_rcut = max(1.0e-3, half_min_cell - MIN_QMMM_GEOMETRIC_RCUT_MARGIN)
    else:
        max_valid_rcut = buffered_limit
    effective_rcut = min(target_rcut, max_valid_rcut)
    rcut_relaxed = effective_rcut + 1.0e-8 < target_rcut
    return {
        'cell_lengths': cell_lengths,
        'half_min_cell': float(half_min_cell),
        'target_rcut': float(target_rcut),
        'requested_buffer': float(requested_buffer),
        'buffer_relaxed': bool(buffer_relaxed),
        'max_valid_rcut': float(max_valid_rcut),
        'effective_rcut': float(effective_rcut),
        'rcut_relaxed': bool(rcut_relaxed),
        'rcut_shortfall': float(max(0.0, target_rcut - effective_rcut)),
    }


def normalize_trajectory_format(trajectory_format):
    """Normalize supported CP2K trajectory formats exposed by the pipeline."""
    value = str(trajectory_format or DEFAULT_TRAJECTORY_FORMAT).strip().upper()
    if value not in TRAJECTORY_FORMAT_CHOICES:
        allowed = ", ".join(TRAJECTORY_FORMAT_CHOICES)
        raise ValueError(
            f"Invalid trajectory FORMAT '{trajectory_format}'. Allowed values: {allowed}"
        )
    return value


def normalize_mm_scale14_policy_mode(mode):
    """Normalize the MM 1-4 scaling policy mode."""
    value = str(mode or DEFAULT_MM_SCALE14_POLICY).strip().upper()
    aliases = {
        'AMBER': 'AMBER_RECOMMENDED',
        'STANDARD_AMBER': 'AMBER_RECOMMENDED',
        'RECOMMENDED': 'AMBER_RECOMMENDED',
        'CP2K': 'CP2K_EXPLICIT',
        'EXPLICIT': 'CP2K_EXPLICIT',
        'MANUAL': 'MANUAL_OVERRIDE',
        'OVERRIDE': 'MANUAL_OVERRIDE',
    }
    resolved = aliases.get(value, value)
    if resolved not in MM_SCALE14_POLICIES:
        allowed = ", ".join(MM_SCALE14_POLICIES.keys())
        raise ValueError(f"Invalid MM 1-4 scaling policy '{mode}'. Allowed values: {allowed}")
    return resolved


def validate_mm_scale14_value(value, keyword):
    """Validate one CP2K MM 1-4 scaling factor."""
    try:
        parsed = float(value)
    except Exception as exc:
        raise ValueError(f"{keyword} must be numeric. Got {value!r}.") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{keyword} must be finite. Got {parsed!r}.")
    if parsed < 0.0:
        raise ValueError(f"{keyword} must be >= 0. Got {parsed}.")
    return parsed


def make_mm_scale14_policy(mode=None, ei_scale14=None, vdw_scale14=None):
    """Create a validated explicit MM 1-4 scaling policy for CP2K FORCEFIELD."""
    resolved = normalize_mm_scale14_policy_mode(mode)
    if resolved == 'AMBER_RECOMMENDED':
        if ei_scale14 is not None or vdw_scale14 is not None:
            raise ValueError(
                "AMBER_RECOMMENDED does not accept explicit numeric overrides. "
                "Use MANUAL_OVERRIDE or CP2K_EXPLICIT."
            )
        return MMScale14Policy(
            mode=resolved,
            ei_scale14=float(DEFAULT_EI_SCALE14),
            vdw_scale14=float(DEFAULT_VDW_SCALE14),
            label='Standard AMBER biomolecular 1-4 scaling',
            reason=(
                'Explicit CP2K runtime scaling matching conventional AMBER biomolecular '
                'SCEE=1.2 and SCNB=2.0.'
            ),
        )
    ei = validate_mm_scale14_value(ei_scale14, 'EI_SCALE14')
    vdw = validate_mm_scale14_value(vdw_scale14, 'VDW_SCALE14')
    if resolved == 'CP2K_EXPLICIT':
        label = 'Explicit CP2K 1-4 scaling'
        reason = 'Explicit runtime scaling values provided for CP2K FORCEFIELD.'
    else:
        label = 'Manual 1-4 scaling override'
        reason = 'Expert override of the recommended AMBER biomolecular runtime scaling.'
    return MMScale14Policy(
        mode=resolved,
        ei_scale14=float(ei),
        vdw_scale14=float(vdw),
        label=label,
        reason=reason,
    )


def resolve_mm_scale14_policy(mode=None, ei_scale14=None, vdw_scale14=None):
    """Resolve MM 1-4 scaling policy from optional mode and explicit factors."""
    resolved_mode = mode
    if resolved_mode is None and (ei_scale14 is not None or vdw_scale14 is not None):
        resolved_mode = 'MANUAL_OVERRIDE'
    return make_mm_scale14_policy(resolved_mode, ei_scale14=ei_scale14, vdw_scale14=vdw_scale14)


def format_mm_scale14_policy(policy):
    """Build a concise human-readable MM 1-4 scaling summary."""
    if not isinstance(policy, MMScale14Policy):
        raise TypeError("format_mm_scale14_policy() requires an MMScale14Policy instance.")
    return (
        f"{policy.mode} (EI_SCALE14 {policy.ei_scale14:.10f}, "
        f"VDW_SCALE14 {policy.vdw_scale14:.10f})"
    )


def normalize_sampling_method(method):
    """Normalize supported advanced sampling modes."""
    value = str(method or '').strip().upper()
    aliases = {
        'METADYN': 'METADYNAMICS',
        'METADYNAMICS': 'METADYNAMICS',
        'META': 'METADYNAMICS',
        'UMBRELLA': 'UMBRELLA',
        'UMBRELLA_SAMPLING': 'UMBRELLA',
        'US': 'UMBRELLA',
    }
    if value in aliases:
        return aliases[value]
    allowed = ", ".join(SAMPLING_METHODS.keys())
    raise ValueError(f"Invalid sampling method '{method}'. Allowed values: {allowed}")


def normalize_sampling_colvar_type(colvar_type):
    """Normalize supported CP2K-native collective-variable types."""
    value = str(colvar_type or '').strip().upper()
    aliases = {
        'DISTANCE': 'DISTANCE',
        'ANGLE': 'ANGLE',
        'TORSION': 'TORSION',
        'DIHEDRAL': 'TORSION',
        'COORDINATION': 'COORDINATION',
    }
    if value in aliases:
        return aliases[value]
    allowed = ", ".join(SAMPLING_COLVAR_TYPES)
    raise ValueError(f"Invalid sampling CV type '{colvar_type}'. Allowed values: {allowed}")


def _validate_sampling_atom_tuple(values, field_name, exact_len=None):
    """Validate a 1-based atom-index tuple from the external sampling spec."""
    if values is None:
        raise ValueError(f"Sampling spec field '{field_name}' is required.")
    try:
        atoms = tuple(int(v) for v in values)
    except Exception:
        raise ValueError(f"Sampling spec field '{field_name}' must be a list of 1-based atom indices.")
    if exact_len is not None and len(atoms) != exact_len:
        raise ValueError(f"Sampling spec field '{field_name}' must contain exactly {exact_len} atom indices.")
    if not atoms or any(a < 1 for a in atoms):
        raise ValueError(f"Sampling spec field '{field_name}' must contain positive 1-based atom indices.")
    return atoms


def _sampling_bool(raw, default=False):
    """Interpret booleans from JSON/YAML scalars without guessing chemistry."""
    if raw is None:
        return bool(default)
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in ('1', 'true', 'yes', 'on'):
        return True
    if text in ('0', 'false', 'no', 'off'):
        return False
    raise ValueError(f"Expected boolean value, got {raw!r}.")


def _sampling_float(raw, field_name, minimum=None):
    """Validate a numeric sampling hyperparameter."""
    try:
        value = float(raw)
    except Exception:
        raise ValueError(f"Sampling spec field '{field_name}' must be numeric.")
    if minimum is not None and value < minimum:
        raise ValueError(f"Sampling spec field '{field_name}' must be >= {minimum}.")
    return value


def _sampling_int(raw, field_name, minimum=None):
    """Validate an integer sampling hyperparameter."""
    try:
        value = int(raw)
    except Exception:
        raise ValueError(f"Sampling spec field '{field_name}' must be an integer.")
    if minimum is not None and value < minimum:
        raise ValueError(f"Sampling spec field '{field_name}' must be >= {minimum}.")
    return value


def make_sampling_config(spec_data, source_path="<inline>", source_format="json"):
    """Validate an external metadynamics/umbrella sampling declaration."""
    if spec_data is None:
        return None
    if not isinstance(spec_data, dict):
        raise ValueError("Sampling specification must be a JSON/YAML mapping at the top level.")

    method = normalize_sampling_method(spec_data.get('method'))
    colvars_raw = list(spec_data.get('colvars') or [])
    if not colvars_raw:
        raise ValueError("Sampling specification must define at least one collective variable in 'colvars'.")

    colvars = []
    colvar_names = set()
    for idx, raw_cv in enumerate(colvars_raw, start=1):
        if not isinstance(raw_cv, dict):
            raise ValueError(f"Sampling colvar #{idx} must be a mapping.")
        name = str(raw_cv.get('name') or f"cv{idx}").strip()
        if not name:
            raise ValueError(f"Sampling colvar #{idx} has an empty name.")
        if name in colvar_names:
            raise ValueError(f"Sampling colvar name '{name}' is duplicated.")
        colvar_names.add(name)
        kind = normalize_sampling_colvar_type(raw_cv.get('type'))
        atoms = ()
        atoms_from = ()
        atoms_to = ()
        r0 = None
        nn = None
        nd = None
        if kind == 'DISTANCE':
            atoms = _validate_sampling_atom_tuple(raw_cv.get('atoms'), 'atoms', exact_len=2)
        elif kind == 'ANGLE':
            atoms = _validate_sampling_atom_tuple(raw_cv.get('atoms'), 'atoms', exact_len=3)
        elif kind == 'TORSION':
            atoms = _validate_sampling_atom_tuple(raw_cv.get('atoms'), 'atoms', exact_len=4)
        elif kind == 'COORDINATION':
            atoms_from = _validate_sampling_atom_tuple(raw_cv.get('atoms_from'), 'atoms_from')
            atoms_to = _validate_sampling_atom_tuple(raw_cv.get('atoms_to'), 'atoms_to')
            r0 = _sampling_float(raw_cv.get('r0'), 'r0', minimum=0.0)
            nn = _sampling_float(raw_cv.get('nn', 6.0), 'nn', minimum=0.0)
            nd = _sampling_float(raw_cv.get('nd', 12.0), 'nd', minimum=0.0)
        colvars.append(SamplingColvar(
            name=name,
            kind=kind,
            atoms=atoms,
            atoms_from=atoms_from,
            atoms_to=atoms_to,
            r0=r0,
            nn=nn,
            nd=nd,
        ))

    metadynamics = None
    restraints = []
    if method == 'METADYNAMICS':
        raw_meta = dict(spec_data.get('metadynamics') or spec_data.get('metadyn') or {})
        height = _sampling_float(raw_meta.get('height'), 'metadynamics.height', minimum=0.0)
        pace = _sampling_int(raw_meta.get('pace'), 'metadynamics.pace', minimum=1)
        raw_sigma = raw_meta.get('sigma')
        if not isinstance(raw_sigma, (list, tuple)) or not raw_sigma:
            raise ValueError("Sampling spec field 'metadynamics.sigma' must be a non-empty list.")
        sigma = tuple(_sampling_float(v, 'metadynamics.sigma', minimum=0.0) for v in raw_sigma)
        if len(sigma) != len(colvars):
            raise ValueError(
                "Sampling spec field 'metadynamics.sigma' must provide one width per COLVAR."
            )
        well_tempered = _sampling_bool(raw_meta.get('well_tempered'), default=False)
        delta_t = raw_meta.get('delta_t')
        if delta_t is not None:
            delta_t = _sampling_float(delta_t, 'metadynamics.delta_t', minimum=0.0)
        wtgamma = raw_meta.get('wtgamma')
        if wtgamma is not None:
            wtgamma = _sampling_float(wtgamma, 'metadynamics.wtgamma', minimum=0.0)
        if well_tempered and delta_t is None and wtgamma is None:
            raise ValueError(
                "Well-tempered metadynamics requires 'delta_t' or 'wtgamma' in the sampling spec."
            )
        metadynamics = SamplingMetadynamicsConfig(
            height=height,
            pace=pace,
            sigma=sigma,
            do_hills=_sampling_bool(raw_meta.get('do_hills'), default=True),
            well_tempered=well_tempered,
            delta_t=delta_t,
            wtgamma=wtgamma,
        )
    else:
        raw_umbrella = dict(spec_data.get('umbrella') or {})
        raw_restraints = list(raw_umbrella.get('restraints') or raw_umbrella.get('windows') or [])
        if not raw_restraints:
            raise ValueError("Umbrella sampling spec must define at least one restraint/window.")
        colvar_lookup = {cv.name: cv for cv in colvars}
        for idx, raw_restraint in enumerate(raw_restraints, start=1):
            if not isinstance(raw_restraint, dict):
                raise ValueError(f"Umbrella restraint #{idx} must be a mapping.")
            colvar_token = raw_restraint.get('colvar')
            if isinstance(colvar_token, int):
                if colvar_token < 1 or colvar_token > len(colvars):
                    raise ValueError(f"Umbrella restraint #{idx} references invalid colvar index {colvar_token}.")
                colvar_name = colvars[colvar_token - 1].name
            else:
                colvar_name = str(colvar_token or '').strip()
                if colvar_name not in colvar_lookup:
                    raise ValueError(
                        f"Umbrella restraint #{idx} references unknown colvar '{colvar_token}'."
                    )
            restraints.append(SamplingRestraint(
                colvar=colvar_name,
                target=_sampling_float(raw_restraint.get('target'), 'umbrella.target'),
                k=_sampling_float(raw_restraint.get('k'), 'umbrella.k', minimum=0.0),
                intermolecular=_sampling_bool(raw_restraint.get('intermolecular'), default=False),
            ))

    return SamplingConfig(
        source_path=str(source_path),
        source_format=str(source_format).upper(),
        method=method,
        colvars=tuple(colvars),
        metadynamics=metadynamics,
        restraints=tuple(restraints),
    )


def validate_sampling_config_indices(sampling_config, natom):
    """Fail fast when any sampling-spec atom index lies outside the loaded topology."""
    if not sampling_config:
        return
    if natom is None:
        raise ValueError(
            "Sampling spec atom-index validation requires a known NATOM in the SystemModel/topology."
        )
    natom = int(natom)
    if natom < 1:
        raise ValueError(f"Sampling spec atom-index validation requires NATOM >= 1. Got {natom}.")
    for cv_idx, colvar in enumerate(sampling_config.colvars, start=1):
        atom_fields = []
        if colvar.atoms:
            atom_fields.append(('atoms', colvar.atoms))
        if colvar.atoms_from:
            atom_fields.append(('atoms_from', colvar.atoms_from))
        if colvar.atoms_to:
            atom_fields.append(('atoms_to', colvar.atoms_to))
        for field_name, atoms in atom_fields:
            for atom_index in atoms:
                if atom_index < 1 or atom_index > natom:
                    raise ValueError(
                        f"Sampling spec atom index {atom_index} in colvars[{cv_idx}] "
                        f"('{colvar.name}') field '{field_name}' is outside the loaded topology "
                        f"(NATOM={natom})."
                    )


def load_sampling_spec(path):
    """Load an external JSON/YAML sampling specification."""
    resolved = os.path.abspath(str(path))
    ext = os.path.splitext(resolved)[1].lower()
    if ext not in ('.json', '.yaml', '.yml'):
        raise ValueError("Sampling spec must end with .json, .yaml, or .yml.")
    with open(resolved, 'r', encoding='utf-8') as f:
        text = f.read()
    if ext == '.json':
        data = json.loads(text)
        source_format = 'JSON'
    else:
        if yaml is None:
            raise ValueError("YAML sampling specs require PyYAML to be available.")
        data = yaml.safe_load(text)
        source_format = 'YAML'
    return make_sampling_config(data, source_path=resolved, source_format=source_format)


def sampling_spec_template_data():
    """Return a boilerplate sampling spec template with both supported modes."""
    return OrderedDict((
        ('method', 'METADYNAMICS'),
        ('notes', [
            'Collective variables encode a mechanistic hypothesis and must be chosen explicitly.',
            'Edit atom indices and hyperparameters deliberately; the generator will not infer CVs from topology.',
            'Numeric values are passed through to CP2K-native keywords, so use units consistent with your intended CP2K setup.',
        ]),
        ('colvars', [
            OrderedDict((
                ('name', 'cv_distance'),
                ('type', 'DISTANCE'),
                ('atoms', [101, 205]),
            )),
        ]),
        ('metadynamics', OrderedDict((
            ('height', 0.0005),
            ('sigma', [0.20]),
            ('pace', 100),
            ('do_hills', True),
            ('well_tempered', False),
            ('delta_t', 1500.0),
        ))),
        ('umbrella', OrderedDict((
            ('restraints', [
                OrderedDict((
                    ('colvar', 'cv_distance'),
                    ('target', 2.50),
                    ('k', 0.0100),
                    ('intermolecular', False),
                )),
            ]),
        ))),
    ))


def _plain_data(obj):
    """Convert OrderedDict/NamedTuple containers into plain dumpable data."""
    if isinstance(obj, OrderedDict):
        return {k: _plain_data(v) for k, v in obj.items()}
    if isinstance(obj, dict):
        return {k: _plain_data(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain_data(v) for v in obj]
    return obj


def render_sampling_spec_template(fmt='yaml'):
    """Render a standard boilerplate sampling template as JSON or YAML."""
    fmt_key = str(fmt or 'yaml').strip().lower()
    data = _plain_data(sampling_spec_template_data())
    if fmt_key == 'json':
        return json.dumps(data, indent=2) + "\n"
    if fmt_key in ('yaml', 'yml'):
        if yaml is None:
            raise ValueError("YAML template generation requires PyYAML to be available.")
        return yaml.safe_dump(data, sort_keys=False)
    raise ValueError("Sampling template format must be 'json' or 'yaml'.")


def write_sampling_spec_template(path, fmt=None):
    """Write a boilerplate sampling spec template to disk."""
    ext = os.path.splitext(str(path))[1].lower()
    fmt_key = fmt or ('json' if ext == '.json' else 'yaml')
    text = render_sampling_spec_template(fmt_key)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    return os.path.abspath(path)


def resolve_sampling_spec_path(raw_path, base_dir):
    """Resolve a sampling spec path against the working directory when needed."""
    text = str(raw_path or '').strip()
    if not text:
        return ''
    if os.path.isabs(text):
        return text
    local = os.path.abspath(text)
    if os.path.exists(local):
        return local
    return os.path.abspath(os.path.join(base_dir, text))

def validate_functional(functional):
    """Normalize and validate supported QM functionals."""
    value = str(functional or "").strip().upper()
    if value not in DFT_FUNCTIONALS:
        allowed = ", ".join(DFT_FUNCTIONALS)
        raise ValueError(f"Invalid DFT functional '{functional}'. Allowed values: {allowed}")
    return value

def validate_basis_set(basis_set):
    """Validate basis-set label used in QM KIND blocks."""
    value = str(basis_set or "").strip()
    if not value:
        raise ValueError("QM basis set label cannot be empty.")
    return value


def is_standard_molopt_basis_set(basis_set):
    """Return True for non-short-range MOLOPT basis labels."""
    value = validate_basis_set(basis_set).upper()
    return 'MOLOPT' in value and 'MOLOPT-SR' not in value and '-SR-' not in value


def validate_mgrid_ngrids(ngrids):
    """Validate CP2K MGRID NGRIDS value."""
    try:
        count = int(ngrids)
    except (TypeError, ValueError):
        raise ValueError(f"MGRID NGRIDS must be an integer >= 1. Got {ngrids!r}.")
    if count < 1:
        raise ValueError(f"MGRID NGRIDS must be >= 1. Got {count}.")
    return count


def recommend_mgrid_ngrids(basis_set):
    """Choose a conservative MGRID NGRIDS default from the QM basis label."""
    if is_standard_molopt_basis_set(basis_set):
        return MOLOPT_DIFFUSE_MGRID_NGRIDS
    return DEFAULT_MGRID_NGRIDS


def resolve_mgrid_ngrids(basis_set, ngrids=None):
    """Resolve the effective MGRID NGRIDS value."""
    if ngrids is None:
        return recommend_mgrid_ngrids(basis_set)
    return validate_mgrid_ngrids(ngrids)


def normalize_admm_aux_basis(aux_basis):
    """Normalize supported ADMM auxiliary basis labels."""
    if aux_basis is None:
        return None
    value = str(aux_basis or "").strip()
    if not value:
        return None
    allowed = {name.upper(): name for name in ADMM_AUX_BASIS_CHOICES}
    key = value.upper()
    if key not in allowed:
        allowed_text = ", ".join(ADMM_AUX_BASIS_CHOICES)
        raise ValueError(
            f"Invalid ADMM auxiliary basis '{aux_basis}'. Allowed values: {allowed_text}"
        )
    return allowed[key]


def recommend_admm_aux_basis(qm_elements, basis_set=None):
    """Pick an ADMM auxiliary basis that is smaller than the primary basis.

    ADMM acceleration is proportional to (N_aux/N_primary)².  When the
    auxiliary has the same (or more) contracted functions as the primary,
    the HFX evaluation is not accelerated and only overhead is added.

    For double-zeta primary bases (DZVP-MOLOPT-GTH and variants), cpFIT3
    has an identical contracted size → no speedup.  cFIT3 omits polarization
    functions, giving genuine basis reduction.

    For triple-zeta and larger primary bases, cpFIT3 is genuinely smaller
    and provides the expected ADMM acceleration.

    Ref: Guidon et al. JCTC 6, 2348 (2010) — ADMM method and basis requirements.
    """
    elems = {str(e).strip().upper() for e in (qm_elements or []) if str(e).strip()}
    basis_upper = str(basis_set or '').strip().upper()
    # Double-zeta primary bases: cpFIT3 ≈ same size → use cFIT3
    is_double_zeta = any(tag in basis_upper for tag in ('DZVP', 'DZV'))
    if is_double_zeta:
        return 'cFIT3'
    if not elems or elems <= STANDARD_BIO_ADMM_ELEMENTS:
        return DEFAULT_ADMM_AUX_BASIS
    return 'cFIT3'


def resolve_admm_aux_basis(qm_elements, aux_basis=None, use_admm=True, basis_set=None,
                           cp2k_capability=None, substitutions_log=None):
    """Resolve the effective ADMM auxiliary basis label.

    When a ``cp2k_capability`` is provided and the requested label is not
    supported by the detected CP2K version (V4), gracefully substitute the
    next best documented alternative and append a structured record to
    ``substitutions_log`` (when supplied).  This preserves the scientific
    invariant — ADMM still fires with a complete auxiliary basis — while
    letting the pipeline run on older CP2K builds.

    Substitution rules, anchored in citations:
      * ``admm-dzp`` → ``cpFIT3`` when CP2K < 8.1.  admm-dzp was added
        in CP2K 8.1 (release notes; BASIS_ADMM_MOLOPT header); cpFIT3 is
        the canonical pre-8.1 polarised double-zeta auxiliary set.
        Ref: Guidon et al. JCTC 6, 2348 (2010); Merlot-Iannuzzi curation.
    """
    if not use_admm:
        return None
    resolved = normalize_admm_aux_basis(aux_basis) or recommend_admm_aux_basis(
        qm_elements, basis_set=basis_set
    )
    if cp2k_capability is not None and resolved:
        key = f'BASIS_ADMM_MOLOPT/{resolved}'
        if key in CP2K_KEYWORD_MIN_VERSION and not cp2k_capability.keywords.get(key, True):
            # Pick the fallback that is known to CP2K ≥ 5.1 and covers
            # the same elements at slightly lower polarisation fidelity.
            fallback = 'cpFIT3'
            if substitutions_log is not None:
                substitutions_log.append({
                    'kind': 'admm_aux_basis',
                    'from': resolved,
                    'to': fallback,
                    'reason': (
                        f"{resolved} requires CP2K >= "
                        f"{format_cp2k_version(CP2K_KEYWORD_MIN_VERSION[key])}; "
                        f"detected {format_cp2k_version(cp2k_capability.version)}."
                    ),
                    'citation': (
                        'CP2K 8.1 release notes (admm-dzp); '
                        'Guidon et al. JCTC 6, 2348 (2010) (ADMM)'
                    ),
                })
            return fallback
    return resolved


def admm_aux_basis_file_names(aux_basis):
    """Return the CP2K basis files required for the selected ADMM auxiliary basis."""
    resolved = normalize_admm_aux_basis(aux_basis)
    if not resolved:
        return ()
    return tuple(ADMM_AUX_BASIS_INFO[resolved]['basis_files'])


def scan_basis_file_for_admm_elements(basis_file_path):
    """
    Scan a CP2K basis-set file for element symbols that carry at least one
    named basis block.  CP2K basis files use the convention:

        <ELEMENT_SYMBOL>  <BASIS_NAME>[  <ALIAS>...]
        <number of exponent sets>
        <l_min l_max n_exp n_cont ...>
        <exponents and coefficients>

    so the element symbol is always the first token on any non-comment,
    non-indented header line.  This scan is intentionally conservative:
    it opportunistically *widens* the curated pin when a newer CP2K
    release ships additional elements, but it never narrows it.  If the
    file is unreadable we return an empty set and the caller falls back
    to the curated pin.

    Reference: CP2K manual §FORCE_EVAL/DFT/BASIS_SET_FILE_NAME file format.
    """
    try:
        with open(basis_file_path, 'r') as fh:
            lines = fh.readlines()
    except (OSError, UnicodeDecodeError):
        return set()
    found = set()
    for line in lines:
        # Basis-set header lines start at column 0 with the element symbol.
        # Exponent/coefficient lines are either indented or begin with a digit,
        # and comments begin with '#' or '!'.  Rejecting all three leaves only
        # header lines, whose first token is the element symbol.
        if not line or line[0].isspace():
            continue
        stripped = line.strip()
        if not stripped or stripped[0] in '#!0123456789':
            continue
        first = stripped.split()[0].upper()
        # Element symbols are 1–2 alphabetic characters.
        if 1 <= len(first) <= 2 and first.isalpha():
            found.add(first)
    return found


def _resolve_admm_supported_elements(aux_basis_label, cp2k_data_dir=None):
    """
    Resolve the effective supported-element set for an ADMM auxiliary basis.

    Starts from the curated pin in ADMM_AUX_BASIS_INFO and, if a CP2K data
    directory is provided and the file is readable, augments the set with
    whatever element symbols the shipped basis file declares.  Returns a
    frozenset; an empty return signals 'coverage unknown, do not gate'.
    """
    entry = ADMM_AUX_BASIS_INFO.get(aux_basis_label)
    if not entry:
        return frozenset()
    supported = entry.get('supported_elements') or frozenset()
    supported = set(supported)
    if cp2k_data_dir:
        for basis_file in entry.get('basis_files', ()):
            candidate = os.path.join(cp2k_data_dir, basis_file)
            if os.path.isfile(candidate):
                supported |= scan_basis_file_for_admm_elements(candidate)
    return frozenset(supported)


def missing_admm_aux_basis_elements(qm_elements, aux_basis, cp2k_data_dir=None):
    """
    Return unsupported QM elements for the selected ADMM auxiliary basis.

    Coverage resolution is layered:
      1) Authoritative curated pin from ADMM_AUX_BASIS_INFO.
      2) Opportunistic widening via `scan_basis_file_for_admm_elements`
         when cp2k_data_dir points at a real CP2K install.
    The caller gates on a non-empty return to either disable ADMM or
    require an explicit expert override (--admm-allow-unverified).

    Reference: Guidon, Hutter, VandeVondele, JCTC 6, 2348 (2010) §II.
    """
    resolved = normalize_admm_aux_basis(aux_basis)
    if not resolved:
        return set()
    elems = {str(e).strip().upper() for e in (qm_elements or []) if str(e).strip()}
    supported = _resolve_admm_supported_elements(resolved, cp2k_data_dir=cp2k_data_dir)
    if not supported:
        # No coverage data available: do not block, but the caller is
        # expected to warn and require --admm-allow-unverified.
        return set()
    return elems - supported


def normalize_admm_exch_correction_func(exch_correction_func):
    """Normalize supported ADMM exchange correction functionals."""
    if exch_correction_func is None:
        return None
    value = str(exch_correction_func or "").strip()
    if not value:
        return None
    allowed = {name.upper(): name for name in ADMM_EXCH_CORRECTION_CHOICES}
    key = value.upper()
    if key not in allowed:
        allowed_text = ", ".join(ADMM_EXCH_CORRECTION_CHOICES)
        raise ValueError(
            f"Invalid ADMM EXCH_CORRECTION_FUNC '{exch_correction_func}'. Allowed values: {allowed_text}"
        )
    return allowed[key]


def prompt_default_admm_exch_correction_func(functional):
    """Return the prompt default for ADMM EXCH_CORRECTION_FUNC."""
    func = str(functional or "").strip().upper()
    return ADMM_EXCH_CORRECTION_DEFAULTS.get(func)


def recommended_admm_exch_correction_func(functional):
    """Return the exchange correction matching the parent hybrid functional."""
    func = str(functional or "").strip().upper()
    if func not in HYBRID_DFT_FUNCTIONALS:
        return None
    return ADMM_EXCH_CORRECTION_DEFAULTS.get(func)


def resolve_admm_exch_correction_func(functional, exch_correction_func=None, use_admm=True):
    """Resolve EXCH_CORRECTION_FUNC for hybrid ADMM runs."""
    if not use_admm:
        return None
    func = str(functional or "").strip().upper()
    if func not in HYBRID_DFT_FUNCTIONALS:
        return None
    return (
        normalize_admm_exch_correction_func(exch_correction_func)
        or recommended_admm_exch_correction_func(func)
    )


def admm_exch_correction_prompt(functional):
    """Build a concise, context-aware ADMM exchange correction prompt."""
    func = str(functional or "").strip().upper()
    prompt = "ADMM EXCH_CORRECTION_FUNC (B3LYP->BECKE88X, PBE0/PBE->PBEX)"
    default = prompt_default_admm_exch_correction_func(func)
    return prompt, default


def qmmm_md_ensemble_prompt():
    """Build a concise QM/MM ensemble prompt with the NPT stress-tensor rule."""
    return "QM/MM thermodynamic ensemble (NPT auto-enforces STRESS_TENSOR ANALYTICAL)"


def validate_qmmm_geep_lib(value):
    """Validate CP2K USE_GEEP_LIB count for GAUSS electrostatic coupling."""
    try:
        count = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"USE_GEEP_LIB must be an integer >= 1. Got {value!r}.")
    if count < 1:
        raise ValueError(f"USE_GEEP_LIB must be >= 1. Got {count}.")
    return count


def validate_hf_max_memory(value):
    """Validate CP2K HF/MEMORY/MAX_MEMORY as an explicit per-rank integer."""
    if value is None:
        return int(DEFAULT_HF_MAX_MEMORY)
    try:
        count = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"HF MAX_MEMORY must be an integer >= 1. Got {value!r}.") from exc
    if count < 1:
        raise ValueError(f"HF MAX_MEMORY must be >= 1. Got {count}.")
    return count


def normalize_scf_cholesky(scf_cholesky):
    """Normalize optional SCF CHOLESKY mode.

    Returns None to leave CP2K at its documented default (RESTORE).
    """
    if scf_cholesky is None:
        return None
    value = str(scf_cholesky).strip().upper()
    if not value or value in {'DEFAULT', 'AUTO', 'CP2K_DEFAULT'}:
        return None
    if value not in SCF_CHOLESKY_MODES:
        allowed = ", ".join(('DEFAULT',) + SCF_CHOLESKY_MODES)
        raise ValueError(f"Invalid SCF CHOLESKY mode '{scf_cholesky}'. Allowed values: {allowed}")
    return value


def normalize_qs_eps_default(qs_eps_default):
    """Normalize optional Quickstep EPS_DEFAULT override.

    Returns None to keep CP2K's documented default (1.0E-10).
    """
    if qs_eps_default is None:
        return None
    value = str(qs_eps_default).strip().upper()
    if not value or value in {'DEFAULT', 'AUTO', 'CP2K_DEFAULT'}:
        return None
    try:
        parsed = float(qs_eps_default)
    except Exception as exc:
        raise ValueError(f"Invalid Quickstep EPS_DEFAULT '{qs_eps_default}'.") from exc
    if parsed <= 0.0:
        raise ValueError(f"Quickstep EPS_DEFAULT must be > 0. Got {parsed}.")
    return parsed


def validate_scf_cfg(scf_cfg, engine='OT'):
    """Boundary validator for an SCF configuration dict (A.2.b).

    Enforces ranges that CP2K either rejects outright or that produce
    unstable convergence outside published norms.  This runs *after* the
    interactive wizard / CLI overrides and *before* the SCF block is
    emitted, so it catches user-supplied values that slipped past the
    individual ``ask_*`` prompts (for example, an ``--scf-mixing-alpha``
    CLI override or a programmatic override that bypassed the wizard).

    Engine-relevant ranges (sources cited inline so the rule is auditable):
      * ``mixing_alpha`` ∈ (0, 1].  CP2K Manual §FORCE_EVAL/DFT/SCF/MIXING
        documents ALPHA as a damping factor; values outside (0, 1] are
        either undefined (negative) or unstable (>1, amplification).
      * ``nbroyden`` ∈ [3, 12].  Broyden, Math. Comp. 19, 577 (1965)
        established convergence stability for histories of length ≥ 3;
        depths beyond ~12 incur memory/stagnation cost without payoff
        (Johnson, Phys. Rev. B 38, 12807 (1988); CP2K MIXING NBROYDEN doc).
      * ``level_shift`` ∈ [0.0, 1.0] Hartree.  Saunders & Hillier,
        Int. J. Quantum Chem. 7, 699 (1973) define LEVEL_SHIFT as a
        positive virtual-orbital displacement; >1 Ha (~27 eV) is far
        beyond any realistic frontier-orbital gap and prevents
        convergence to the physical density.
      * ``max_scf`` ≥ 1; ``outer_max_scf`` ≥ 1.
      * ``eps_scf`` > 0; ``outer_eps_scf`` > 0 and ≤ ``eps_scf``.

    Raises ValueError with an actionable message on the first violation.
    Returns the validated dict (same instance) on success.
    """
    eng = str(engine or 'OT').strip().upper()

    def _bad(key, value, expected):
        raise ValueError(
            f"SCF configuration violates documented range: "
            f"{key}={value!r} (expected {expected}). "
            "Edit the wizard input, the corresponding CLI flag, or the "
            "selected SCF profile to a value within the cited range."
        )

    try:
        max_scf_val = int(scf_cfg.get('max_scf', 0))
    except (TypeError, ValueError):
        _bad('max_scf', scf_cfg.get('max_scf'), 'positive integer')
    if max_scf_val < 1:
        _bad('max_scf', max_scf_val, '>= 1')

    try:
        outer_max_scf_val = int(scf_cfg.get('outer_max_scf', 0))
    except (TypeError, ValueError):
        _bad('outer_max_scf', scf_cfg.get('outer_max_scf'), 'positive integer')
    if outer_max_scf_val < 1:
        _bad('outer_max_scf', outer_max_scf_val, '>= 1')

    try:
        eps_scf_val = float(scf_cfg.get('eps_scf', 0.0))
    except (TypeError, ValueError):
        _bad('eps_scf', scf_cfg.get('eps_scf'), 'positive float')
    if not (eps_scf_val > 0.0):
        _bad('eps_scf', eps_scf_val, '> 0.0')

    try:
        outer_eps_scf_val = float(scf_cfg.get('outer_eps_scf', 0.0))
    except (TypeError, ValueError):
        _bad('outer_eps_scf', scf_cfg.get('outer_eps_scf'), 'positive float')
    if not (outer_eps_scf_val > 0.0):
        _bad('outer_eps_scf', outer_eps_scf_val, '> 0.0')
    if outer_eps_scf_val > eps_scf_val:
        _bad(
            'outer_eps_scf',
            outer_eps_scf_val,
            f'<= eps_scf ({eps_scf_val:.1e})',
        )

    # Mixing parameters are only meaningful for DIAG-engine profiles; for
    # OT they are inert placeholders the emitter does not write.  Only
    # validate them when they would actually reach CP2K.
    if eng == 'DIAG':
        try:
            mixing_alpha_val = float(scf_cfg.get('mixing_alpha', 0.0))
        except (TypeError, ValueError):
            _bad('mixing_alpha', scf_cfg.get('mixing_alpha'), 'float in (0, 1]')
        if not (0.0 < mixing_alpha_val <= 1.0):
            _bad('mixing_alpha', mixing_alpha_val, 'float in (0, 1]')

        try:
            nbroyden_val = int(scf_cfg.get('nbroyden', 0))
        except (TypeError, ValueError):
            _bad('nbroyden', scf_cfg.get('nbroyden'), 'integer in [3, 12]')
        if not (3 <= nbroyden_val <= 12):
            _bad('nbroyden', nbroyden_val, 'integer in [3, 12] (Broyden 1965; Johnson 1988)')

        try:
            added_mos_val = int(scf_cfg.get('added_mos', 0))
        except (TypeError, ValueError):
            _bad('added_mos', scf_cfg.get('added_mos'), 'non-negative integer')
        if added_mos_val < 0:
            _bad('added_mos', added_mos_val, '>= 0')

    # LEVEL_SHIFT, when present, must be a non-negative finite Hartree value.
    level_shift_raw = scf_cfg.get('level_shift')
    if level_shift_raw is not None:
        try:
            level_shift_val = float(level_shift_raw)
        except (TypeError, ValueError):
            _bad('level_shift', level_shift_raw, 'None or float in [0.0, 1.0] Hartree')
        if not math.isfinite(level_shift_val):
            _bad('level_shift', level_shift_val, 'finite float')
        if not (0.0 <= level_shift_val <= 1.0):
            _bad(
                'level_shift', level_shift_val,
                'float in [0.0, 1.0] Hartree (Saunders & Hillier 1973 range)',
            )

    return scf_cfg


def normalize_ot_minimizer(ot_minimizer):
    """Normalize the OT minimizer choice."""
    value = str(ot_minimizer or DEFAULT_OT_MINIMIZER).strip().upper()
    if value not in OT_MINIMIZERS:
        allowed = ", ".join(OT_MINIMIZERS)
        raise ValueError(f"Invalid OT MINIMIZER '{ot_minimizer}'. Allowed values: {allowed}")
    return value


def validate_ot_energy_gap(ot_energy_gap):
    """Validate the OT ENERGY_GAP value."""
    try:
        parsed = float(ot_energy_gap)
    except Exception as exc:
        raise ValueError(f"Invalid OT ENERGY_GAP '{ot_energy_gap}'.") from exc
    if parsed <= 0.0:
        raise ValueError(f"OT ENERGY_GAP must be > 0. Got {parsed}.")
    return parsed


def normalize_ot_stepsize_mode(mode):
    """Normalize the OT STEPSIZE ownership policy."""
    value = str(mode or DEFAULT_OT_STEPSIZE_POLICY).strip().upper()
    aliases = {
        'AUTOMATIC': 'AUTO',
        'CP2K': 'AUTO',
        'CP2K_DEFAULT': 'AUTO',
        'DEFAULT': 'AUTO',
        'EXPLICIT': 'MANUAL',
        'OVERRIDE': 'MANUAL',
        'MANUAL_OVERRIDE': 'MANUAL',
    }
    resolved = aliases.get(value, value)
    if resolved not in OT_STEPSIZE_POLICIES:
        allowed = ", ".join(OT_STEPSIZE_POLICIES.keys())
        raise ValueError(f"Invalid OT STEPSIZE policy '{mode}'. Allowed values: {allowed}")
    return resolved


def validate_ot_stepsize(ot_stepsize):
    """Validate a manual positive OT STEPSIZE value."""
    try:
        parsed = float(ot_stepsize)
    except Exception as exc:
        raise ValueError(f"Invalid OT STEPSIZE '{ot_stepsize}'.") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"OT STEPSIZE must be finite. Got {parsed!r}.")
    if parsed <= 0.0:
        raise ValueError(
            f"Manual OT STEPSIZE must be > 0. Got {parsed}. "
            "Use AUTO mode to delegate to CP2K."
        )
    return parsed


def cp2k_default_ot_stepsize(ot_preconditioner):
    """Return the current CP2K automatic OT STEPSIZE for a preconditioner."""
    precond = str(ot_preconditioner or DEFAULT_OT_PRECONDITIONER).strip().upper()
    return float(OT_PRECONDITIONER_DEFAULT_STEPSIZES.get(precond, 0.15))


def make_ot_stepsize_policy(mode=None, stepsize=None, ot_preconditioner=DEFAULT_OT_PRECONDITIONER):
    """Create a validated OT STEPSIZE policy.

    AUTO emits STEPSIZE -1.0 so CP2K chooses the initial line-search step for
    the selected preconditioner. MANUAL emits an explicit positive stepsize.
    """
    inferred_mode = mode
    if inferred_mode is None and stepsize is not None:
        inferred_mode = 'MANUAL'
    resolved_mode = normalize_ot_stepsize_mode(inferred_mode)
    precond = str(ot_preconditioner or DEFAULT_OT_PRECONDITIONER).strip().upper() or DEFAULT_OT_PRECONDITIONER
    if resolved_mode == 'AUTO':
        if stepsize is not None:
            raise ValueError(
                "AUTO OT STEPSIZE policy does not accept an explicit stepsize. "
                "Use MANUAL if you want to emit a numeric STEPSIZE."
            )
        return OTStepSizePolicy(
            mode='AUTO',
            stepsize=float(CP2K_AUTO_OT_STEPSIZE),
            label='CP2K automatic OT initial stepsize',
            reason=(
                f"Emit STEPSIZE {CP2K_AUTO_OT_STEPSIZE:.1f} so CP2K chooses the initial "
                f"line-search step for PRECONDITIONER {precond}."
            ),
        )
    manual = validate_ot_stepsize(stepsize)
    return OTStepSizePolicy(
        mode='MANUAL',
        stepsize=float(manual),
        label='Manual OT initial stepsize override',
        reason=(
            f"Explicit reproducible OT initial line-search step; CP2K automatic value for "
            f"PRECONDITIONER {precond} is currently {cp2k_default_ot_stepsize(precond):.2f}."
        ),
    )

def resolve_dft_qm_settings(functional, cutoff, rel_cutoff, use_admm, basis_set, ngrids=None, hf_max_memory=None):
    """Validate and normalize DFT/QM settings selected by CLI or wizard."""
    func = validate_functional(functional)
    basis = validate_basis_set(basis_set)
    try:
        cutoff_val = float(cutoff)
    except Exception as exc:
        raise ValueError(f"Invalid MGRID CUTOFF '{cutoff}'.") from exc
    if cutoff_val <= 0.0:
        raise ValueError(f"MGRID CUTOFF must be > 0. Got {cutoff_val}.")

    try:
        rel_cutoff_val = float(rel_cutoff)
    except Exception as exc:
        raise ValueError(f"Invalid MGRID REL_CUTOFF '{rel_cutoff}'.") from exc
    if rel_cutoff_val <= 0.0:
        raise ValueError(f"MGRID REL_CUTOFF must be > 0. Got {rel_cutoff_val}.")

    return {
        'functional': func,
        'cutoff': cutoff_val,
        'rel_cutoff': rel_cutoff_val,
        'use_admm': bool(use_admm),
        'basis_set': basis,
        'ngrids': resolve_mgrid_ngrids(basis, ngrids),
        'hf_max_memory': validate_hf_max_memory(hf_max_memory),
    }


# ── D.4.a: MGRID CUTOFF / REL_CUTOFF threshold validator ─────────────────
#
# CP2K's plane-wave auxiliary mesh (MGRID/CUTOFF) must resolve the steepest
# Gaussian primitives of the chosen GTH/MOLOPT basis set; a too-small cutoff
# under-converges total energy and (more painfully) forces, producing
# spurious oscillations in QM/MM MD.  REL_CUTOFF anchors the gridding of
# diffuse functions across the multigrid hierarchy and should be tightened
# in lock-step.  Conservative thresholds drawn from:
#   * VandeVondele & Hutter, JCP 127, 114105 (2007)  (MOLOPT design)
#   * Krack & Parrinello, PCCP 2, 2105 (2000)        (GPW with Gaussians)
#   * CP2K Manual §FORCE_EVAL/DFT/MGRID; the convergence test recipe in
#     the official tutorial recommends increasing CUTOFF until the total
#     energy is converged to <0.01 mHa/atom (typically 280-500 Ry for
#     MOLOPT-DZVP/-TZV2P with PBE/B3LYP/PBE0 in molecular systems).
#
# This is an *advisory* validator — it never modifies the user's value, in
# line with feedback_no_silent_modifications.  The thresholds are
# deliberately conservative recommendations (not hard floors) so the
# advisory aligns with the SCF-engine routing audit and run_provenance.txt.

MGRID_CUTOFF_RECOMMENDED_FLOOR_RY = 280.0
MGRID_REL_CUTOFF_RECOMMENDED_FLOOR_RY = 40.0
MGRID_REL_CUTOFF_PRODUCTION_DEFAULT_RY = 60.0


def evaluate_mgrid_cutoff_balance(cutoff_ry, rel_cutoff_ry, basis_set=None,
                                  use_admm=False, has_hybrid=False):
    """Diagnose under-converged MGRID cutoffs and return advisories.

    Returns ``{'ok': bool, 'severity': 'recommendation', 'messages': [...],
    'cutoff': float, 'rel_cutoff': float, 'basis_set': str|None}``.
    Never modifies the input — purely advisory per project policy.
    """
    cutoff_val = float(cutoff_ry)
    rel_cutoff_val = float(rel_cutoff_ry)
    basis_label = (str(basis_set).upper() if basis_set is not None else None)
    is_molopt = bool(basis_label and is_standard_molopt_basis_set(basis_label))
    messages = []
    # CUTOFF below the documented MOLOPT/GTH convergence floor.
    if cutoff_val < MGRID_CUTOFF_RECOMMENDED_FLOOR_RY - 1.0e-6:
        messages.append(
            f"MGRID CUTOFF {cutoff_val:g} Ry is below the conservative "
            f"convergence floor ({MGRID_CUTOFF_RECOMMENDED_FLOOR_RY:g} Ry) "
            "for MOLOPT/GTH bases — under-converged Gaussian projection on "
            "the auxiliary plane-wave mesh distorts energies and forces. "
            "Run a CUTOFF convergence test "
            "(VandeVondele-Hutter, JCP 127, 114105 (2007); CP2K Manual "
            "§FORCE_EVAL/DFT/MGRID) before production."
        )
    # REL_CUTOFF below the conservative production minimum.
    if rel_cutoff_val < MGRID_REL_CUTOFF_RECOMMENDED_FLOOR_RY - 1.0e-6:
        messages.append(
            f"MGRID REL_CUTOFF {rel_cutoff_val:g} Ry is below the "
            f"conservative floor ({MGRID_REL_CUTOFF_RECOMMENDED_FLOOR_RY:g} Ry); "
            "diffuse Gaussian projection across the multigrid hierarchy "
            "becomes uneven (visible as grid-noise on forces). The CP2K "
            "tutorial production default is "
            f"{MGRID_REL_CUTOFF_PRODUCTION_DEFAULT_RY:g} Ry."
        )
    # Hybrid + ADMM benefit from a slightly tighter mesh because the
    # ADMM auxiliary basis still uses the same MGRID grid for the local
    # exchange correction (Guidon, Hutter, VandeVondele, JCTC 6, 2348
    # (2010)); flag a separate, milder advisory when CUTOFF is at the
    # floor or just above it for hybrids.
    if (use_admm or has_hybrid) and cutoff_val < 400.0 - 1.0e-6:
        messages.append(
            "Hybrid functional with ADMM acceleration typically benefits "
            f"from CUTOFF ≥ 400 Ry; current value {cutoff_val:g} Ry may "
            "leave HFX-correction noise on the table "
            "(Guidon, Hutter, VandeVondele, JCTC 6, 2348 (2010))."
        )
    # MOLOPT-specific: REL_CUTOFF should be at the production default.
    if is_molopt and rel_cutoff_val < MGRID_REL_CUTOFF_PRODUCTION_DEFAULT_RY - 1.0e-6:
        messages.append(
            f"MOLOPT basis {basis_label} pairs best with REL_CUTOFF "
            f"≥ {MGRID_REL_CUTOFF_PRODUCTION_DEFAULT_RY:g} Ry per the "
            "CP2K MOLOPT tutorial; lower values can leave the multi-grid "
            "speedup partially on the table even when COMMENSURATE=T."
        )
    return {
        'ok': not messages,
        'severity': 'recommendation',
        'messages': tuple(messages),
        'cutoff': cutoff_val,
        'rel_cutoff': rel_cutoff_val,
        'basis_set': basis_label,
    }


def recommended_scf_profile(qm_elements, functional, qm_atom_count, multiplicity=1):
    """Infer recommended SCF profile from system chemistry and DFT level.

    Returns (canonical_profile_key, human_reason_string).

    The *multiplicity* parameter defaults to 1 (singlet) so callers that
    invoke the recommender before the spin state is known still get a
    reasonable preliminary answer.  When multiplicity is available, passing
    it allows the recommender to route open-shell systems into the profile
    that matches their electronic character.

    ── Routing logic ────────────────────────────────────────────────────
    The decision axis ordering is deliberate.  We branch on the *presence
    of a transition metal* strictly before we branch on *open-shell*,
    because the two populations require opposite SCF strategies:

      • Transition-metal open-shell → METAL_RADICAL_DIAG (Fermi smearing
        on near-degenerate d-manifolds; Rabuck & Scuseria, J. Chem. Phys.
        110, 695 (1999) — smearing as a convergence aid for metals).
      • Organic open-shell (no TM) → ORGANIC_RADICAL_DIAG (level shift,
        no smearing; Saunders & Hillier, Int. J. Quantum Chem. 7, 699
        (1973) — level shift for discrete near-degenerate organic SOMOs).

    Collapsing both into one "radical" profile misroutes flavoenzymes,
    quinones, tyrosyl radicals, and other organic-radical QM regions
    into a metallic-prior SCF that then fails to converge by oscillating
    between charge-transfer configurations (observed in LAAO QM/MM
    warmup: flavin-isoalloxazine ↔ bound phenylalanine π-system).
    """
    func = str(functional).upper()
    elems = {str(e).upper() for e in qm_elements}
    has_tm = bool(elems & TRANSITION_METALS)
    is_open_shell = int(multiplicity) > 1
    # QM region size routes to the DIAG engine above the named cutoff; the
    # threshold is exposed as QM_ATOM_COUNT_THRESHOLD_FOR_DIAG so the routing
    # boundary is auditable rather than hidden in a literal.  See the
    # constant's docstring for the scaling/crossover citations.
    large_qm = int(qm_atom_count) >= QM_ATOM_COUNT_THRESHOLD_FOR_DIAG

    # Branch order is load-bearing: TM presence is checked before spin
    # multiplicity so a transition metal in a formally closed-shell
    # complex (rare but possible via strong-field diamagnetic config)
    # still routes to the metal profile for its richer diagonalisation
    # safety net, and an organic radical never lands in the metal branch.
    # ── Evidence-tagged rationale (A.1.c) ────────────────────────────────
    # Every branch surfaces the concrete evidence behind the choice so the
    # user can audit (and the audit file can record) why the recommender
    # picked this profile.  All branches here are LOW_RISK_INFERRED in the
    # existing decision-class taxonomy — they rely on directly observable
    # facts (element identity, multiplicity, atom count) — but the
    # *evidence kind* differs and is informative when reviewing the run.
    if has_tm and is_open_shell:
        return 'METAL_RADICAL_DIAG', (
            "open-shell system with transition-metal element(s); "
            "d-manifold near-degeneracy → DIAG+Broyden+Fermi smearing "
            "[evidence: TM-element + multiplicity>1]"
        )
    if has_tm:
        # Formally closed-shell TM complex: still route to the metal
        # profile because closed-shell TM SCFs can exhibit the same
        # near-degenerate d-manifold pathologies that smearing addresses.
        return 'METAL_RADICAL_DIAG', (
            "QM region contains transition-metal element(s); "
            "using conservative metal SCF recipe "
            "[evidence: TM-element, formally closed-shell]"
        )
    if is_open_shell:
        # Organic open-shell: discrete SOMO, no d-manifold.  Smearing is
        # wrong here; level shift is the appropriate convergence aid.
        return 'ORGANIC_RADICAL_DIAG', (
            "open-shell system (multiplicity > 1) with no transition metals; "
            "organic π-radical recipe (LEVEL_SHIFT, no Fermi smearing) "
            "[evidence: multiplicity>1, no TM]"
        )
    if large_qm:
        # Large QM regions benefit from diag-mode eigenvalue resolution.
        return 'MECHANISM_DIAG', (
            f"large QM region detected "
            f"(>={QM_ATOM_COUNT_THRESHOLD_FOR_DIAG} atoms) "
            "[evidence: qm_atom_count heuristic vs "
            "QM_ATOM_COUNT_THRESHOLD_FOR_DIAG — see CP2K BioExcel guides, "
            "VandeVondele & Hutter JCP 127, 114105 (2007)]"
        )
    # OT+ADMM is the documented efficient path for closed-shell hybrid DFT
    # in biomolecular QM/MM (CP2K docs; BioExcel best-practice guides).
    return 'ROUTINE_OT', (
        "closed-shell biomolecular QM region "
        f"[evidence: no TM, parity-default singlet, "
        f"qm_atoms<{QM_ATOM_COUNT_THRESHOLD_FOR_DIAG}]"
    )

def should_use_diagonalization_scf(functional, multiplicity, qm_elements, scf_profile):
    """Decide if diagonalization-style SCF controls should be used.

    The profile's declared engine is authoritative when the profile is a DIAG
    profile.  For OT profiles, the function still forces diag when the physics
    demands it (open-shell or transition metals), emitting the DIAG engine
    regardless of what the user selected.  This keeps OT reserved for the
    cases where it is documented as robust (closed-shell, no d-block metals).
    """
    validate_functional(functional)
    resolved = _validate_scf_profile_key(scf_profile or 'ROUTINE_OT')
    profile_engine = SCF_PROFILES[resolved].get('engine', 'OT')
    qm_mult = max(1, int(multiplicity))
    elems = {str(e).upper() for e in (qm_elements or {})}
    has_tm = bool(elems & TRANSITION_METALS)

    # Profiles that declare DIAG always use diag.
    if profile_engine == 'DIAG':
        return True
    # OT profiles are overridden to diag when physics requires it.
    if has_tm or qm_mult != 1:
        return True
    return False

def _cp2k_bool(flag):
    """Render Python truthiness as CP2K boolean token."""
    return 'TRUE' if bool(flag) else 'FALSE'

def make_ext_restart_config(
    restart_file_name,
    restart_pos=True,
    restart_vel=False,
    restart_cell=True,
    restart_counters=True,
    restart_thermostat=True,
    restart_barostat=True,
    restart_randomg=True,
):
    """Create explicit &EXT_RESTART restart semantics config."""
    return {
        'restart_file_name': str(restart_file_name),
        'restart_pos': bool(restart_pos),
        'restart_vel': bool(restart_vel),
        'restart_cell': bool(restart_cell),
        'restart_counters': bool(restart_counters),
        'restart_thermostat': bool(restart_thermostat),
        'restart_barostat': bool(restart_barostat),
        'restart_randomg': bool(restart_randomg),
    }

def _append_ext_restart_lines(out, ext_restart_cfg):
    """Append a strict &EXT_RESTART block with explicit restart controls."""
    if not ext_restart_cfg:
        return
    cfg = dict(ext_restart_cfg)
    restart_file = str(cfg.get('restart_file_name') or '').strip()
    if not restart_file:
        raise ValueError("EXT_RESTART config requires restart_file_name.")
    out.append("&EXT_RESTART\n")
    out.append(f"  RESTART_FILE_NAME {restart_file}\n")
    out.append("  RESTART_DEFAULT FALSE\n")
    out.append(f"  RESTART_POS {_cp2k_bool(cfg.get('restart_pos', True))}\n")
    out.append(f"  RESTART_VEL {_cp2k_bool(cfg.get('restart_vel', False))}\n")
    out.append(f"  RESTART_CELL {_cp2k_bool(cfg.get('restart_cell', True))}\n")
    out.append(f"  RESTART_COUNTERS {_cp2k_bool(cfg.get('restart_counters', True))}\n")
    out.append(f"  RESTART_THERMOSTAT {_cp2k_bool(cfg.get('restart_thermostat', True))}\n")
    out.append(f"  RESTART_BAROSTAT {_cp2k_bool(cfg.get('restart_barostat', True))}\n")
    out.append(f"  RESTART_RANDOMG {_cp2k_bool(cfg.get('restart_randomg', True))}\n")
    out.append("&END EXT_RESTART\n\n")

def _normalize_fixed_atom_indices(fixed_atom_indices):
    """Normalize fixed-atom index list into sorted unique positive 1-based integers."""
    if not fixed_atom_indices:
        return []
    normalized = []
    for i in fixed_atom_indices:
        try:
            idx = int(i)
        except Exception:
            continue
        if idx > 0:
            normalized.append(idx)
    return sorted(set(normalized))

def _append_fixed_atoms_constraint_lines(out, fixed_atom_indices, indent="  ", sampling_config=None):
    """Append optional &CONSTRAINT contents for fixed atoms and umbrella restraints."""
    indices = _normalize_fixed_atom_indices(fixed_atom_indices)
    if not indices and not (sampling_config and sampling_config.method == 'UMBRELLA'):
        return
    out.append(f"{indent}&CONSTRAINT\n")
    if indices:
        out.append(f"{indent}  &FIXED_ATOMS\n")
        out.append(f"{indent}    COMPONENTS_TO_FIX XYZ\n")
        for i in range(0, len(indices), 12):
            chunk = " ".join(str(x) for x in indices[i:i+12])
            out.append(f"{indent}    LIST {chunk}\n")
        out.append(f"{indent}  &END FIXED_ATOMS\n")
    if sampling_config and sampling_config.method == 'UMBRELLA':
        colvar_lookup = OrderedDict((cv.name, idx) for idx, cv in enumerate(sampling_config.colvars, start=1))
        for restraint in sampling_config.restraints:
            out.append(f"{indent}  &COLLECTIVE\n")
            out.append(f"{indent}    COLVAR {int(colvar_lookup[restraint.colvar])}\n")
            out.append(f"{indent}    TARGET {float(restraint.target):.10f}\n")
            if restraint.intermolecular:
                out.append(f"{indent}    INTERMOLECULAR\n")
            out.append(f"{indent}    &RESTRAINT\n")
            out.append(f"{indent}      K {float(restraint.k):.10f}\n")
            out.append(f"{indent}    &END RESTRAINT\n")
            out.append(f"{indent}  &END COLLECTIVE\n")
    out.append(f"{indent}&END CONSTRAINT\n")


def _md_ensemble_requires_stress_tensor(md_ensemble):
    """Return True for pressure-coupled ensemble families that need stress tensor support."""
    value = str(md_ensemble or "").strip().upper()
    return value.startswith(('NPT', 'NPH', 'NPE'))


def _next_fft_friendly(n):
    """Round up to the next integer whose only prime factors are 2, 3, and 5.

    Such values let CP2K's SPME FFT run at optimal speed."""
    n = max(int(math.ceil(n)), 1)
    while True:
        m = n
        for p in (2, 3, 5):
            while m % p == 0:
                m //= p
        if m == 1:
            return n
        n += 1


# ─── Shared CP2K Input Emitters ──────────────────────────────────────────────
#
# Internal helpers that emit the CP2K input blocks shared between QM/MM and
# MM-only assemblers.  Each helper appends lines to an existing list and
# returns nothing.  This eliminates the duplication that previously required
# every shared-section fix to be applied in two places.


# ── PME (SPME) accuracy diagnostics ──────────────────────────────────────────
# CP2K's SPME splits the Coulomb sum into a short-range (real-space) part
# damped by erfc(α·r), and a long-range (reciprocal-space) part evaluated on
# an FFT grid.  The two contributions each carry a controllable error that
# *scale oppositely* with α: increasing α improves the reciprocal-space
# error and worsens the real-space error at fixed cutoff (and vice-versa).
# Kolafa & Perram (Mol. Sim. 9, 351, 1992) give leading-order estimates:
#   real-space  error ~ erfc(α · r_c) / r_c
#   recip-space error ~ (2 α / sqrt(π)) · exp(-k_max² / (4 α²)) / k_max
# where the Fourier cutoff is k_max = π · GMAX / L for a box edge L.  A
# well-tuned PME has the two errors of comparable magnitude; a large
# imbalance means one side is over-spent relative to the other.
#
# The function below computes these estimates given α, the real-space
# RCUT_NB, the box edges (Å), and per-axis GMAX.  It returns a dict that
# the emitter can render as diagnostic comments and, when the imbalance
# is severe, as an actionable warning.
#
# References:
#   - Essmann, Perera, Berkowitz, Darden, Lee, Pedersen, JCP 103, 8577 (1995).
#   - Kolafa, Perram, Mol. Simul. 9, 351 (1992).
#   - Darden, York, Pedersen, JCP 98, 10089 (1993).
#   - CP2K manual §FORCE_EVAL/MM/POISSON/EWALD.
PME_TARGET_ABSOLUTE_TOLERANCE = 1.0e-5
PME_WARN_THRESHOLD_TOLERANCE = 1.0e-4


def evaluate_pme_tolerance_balance(alpha, rcut_nb, box_edges, gmax_values,
                                   target_tolerance=PME_TARGET_ABSOLUTE_TOLERANCE,
                                   warn_threshold=PME_WARN_THRESHOLD_TOLERANCE):
    """
    Estimate SPME real-/reciprocal-space error given α, RCUT_NB, and GMAX.

    `box_edges` and `gmax_values` are iterables of the same length (one per
    periodic axis).  Returns a dict with per-axis estimates, a global
    worst-case, and a list of advisory messages.  Errors are dimensionless
    (leading-order Kolafa-Perram tails).
    """
    import math as _math
    a_list = [float(x) for x in (box_edges or ())]
    g_list = [int(round(float(x))) for x in (gmax_values or ())]
    if not a_list or len(a_list) != len(g_list):
        return {
            'real_error': None,
            'recip_error_per_axis': (),
            'worst_recip_error': None,
            'messages': ['PME accuracy estimate skipped: missing or inconsistent box/GMAX.'],
            'under_density_axes': (),
        }

    real_err = _math.erfc(alpha * rcut_nb) / rcut_nb if rcut_nb > 0 else _math.inf
    recip_per_axis = []
    under_density_axes = []
    for L, G in zip(a_list, g_list):
        if L <= 0 or G <= 0:
            recip_per_axis.append(None)
            continue
        k_max = _math.pi * G / L
        # Leading-order reciprocal-space tail (Kolafa-Perram 1992).
        recip_err = (2.0 * alpha / _math.sqrt(_math.pi)) * \
                    _math.exp(-(k_max * k_max) / (4.0 * alpha * alpha)) / max(k_max, 1.0e-30)
        recip_per_axis.append(recip_err)
        if recip_err > warn_threshold:
            under_density_axes.append((L, G, recip_err))
    recip_valid = [e for e in recip_per_axis if e is not None]
    worst = max(recip_valid) if recip_valid else None

    messages = [
        f"PME α = {alpha:.3f} Å⁻¹; RCUT_NB = {rcut_nb:.2f} Å.",
        f"Real-space tail  ≈ {real_err:.2e}  (target {target_tolerance:.1e}).",
    ]
    if worst is not None:
        messages.append(
            f"Recip-space tail ≈ {worst:.2e} (worst axis; target {target_tolerance:.1e})."
        )
    if real_err > warn_threshold:
        messages.append(
            f"Real-space PME error {real_err:.2e} exceeds {warn_threshold:.1e}. "
            "Either tighten RCUT_NB or increase α (note: increasing α raises the "
            "GMAX needed for reciprocal-space accuracy)."
        )
    for (L, G, recip_err) in under_density_axes:
        messages.append(
            f"Recip-space PME error {recip_err:.2e} on axis L={L:.2f} Å, GMAX={G}; "
            "grid appears under-dense for the selected α. "
            "Consider increasing GMAX on that axis or relaxing α."
        )
    return {
        'real_error': real_err,
        'recip_error_per_axis': tuple(recip_per_axis),
        'worst_recip_error': worst,
        'messages': tuple(messages),
        'under_density_axes': tuple(under_density_axes),
    }


def _resolve_box_params(box_dims):
    """Compute cell_abc, cell_angles, gmax_a/b/c from raw box dimensions.

    Returns (cell_abc, cell_angles, gmax_a, gmax_b, gmax_c).
    """
    norm_box = _normalize_box_dims(box_dims) if box_dims else None
    if norm_box:
        a, b, c, alpha, beta, gamma = norm_box
        cell_abc = f"{a:.4f} {b:.4f} {c:.4f}"
        cell_angles = f"{alpha:.4f} {beta:.4f} {gamma:.4f}"
        # GMAX: ~1.0 grid point per Å, matching AMBER PME defaults and
        # providing adequate SPME precision with ALPHA 0.40.  SPME accuracy
        # is ~1E-5 kcal/mol/atom at this density.  For denser grids, scale
        # by a factor f: _next_fft_friendly(int(a * f)).  FFT-friendly
        # values (2^n·3^m·5^k) ensure optimal SPME performance.
        # Ref: Essmann et al., J. Chem. Phys. 103, 8577 (1995) — PME;
        #      CP2K Manual §MM/POISSON/EWALD — GMAX, ALPHA, EWALD_TYPE.
        gmax_a = _next_fft_friendly(a)
        gmax_b = _next_fft_friendly(b)
        gmax_c = _next_fft_friendly(c)
    else:
        cell_abc = "100.0 100.0 100.0"
        cell_angles = "90.0 90.0 90.0"
        gmax_a = gmax_b = gmax_c = 100
    return cell_abc, cell_angles, gmax_a, gmax_b, gmax_c


def _emit_global(out, project_name, run_type, global_seed=None):
    """Emit &GLOBAL section."""
    out.append("&GLOBAL\n")
    out.append(f"  PROJECT {project_name}\n")
    out.append(f"  RUN_TYPE {run_type}\n")
    if global_seed is not None:
        out.append("  ! Explicit seed for reproducible first-stage stochastic initialization when velocities/RNG are not restarted.\n")
        out.append(f"  SEED {int(global_seed)}\n")
    out.append("  PRINT_LEVEL LOW\n")
    out.append("&END GLOBAL\n\n")


_MM_EMIT_PME_ALPHA = 0.40        # Å⁻¹; AMBER-compatible Ewald splitting coefficient.
_MM_EMIT_PME_RCUT_NB = 10.0      # Å; must match the FORCEFIELD/SPLINE RCUT_NB below.

# ── PME override state (E.1.b) ───────────────────────────────────────────────
# When the Kolafa-Perram leading-order diagnostic flags a tolerance imbalance
# and the user consents (interactive mode only), main() may assign tightened
# values here; _emit_mm_section() consults the overrides at emission time.
# Non-interactive runs never assign these — per feedback_no_silent_modifications
# policy the defaults are preserved and only a WARN + provenance entry fire.
_MM_EMIT_PME_ALPHA_OVERRIDE = None
_MM_EMIT_PME_RCUT_NB_OVERRIDE = None


def _effective_pme_alpha():
    """Active SPME α (Å⁻¹), honoring an E.1.b user-consented override."""
    return (float(_MM_EMIT_PME_ALPHA_OVERRIDE)
            if _MM_EMIT_PME_ALPHA_OVERRIDE is not None
            else _MM_EMIT_PME_ALPHA)


def _effective_pme_rcut_nb():
    """Active SPME real-space cutoff (Å), honoring an E.1.b user override."""
    return (float(_MM_EMIT_PME_RCUT_NB_OVERRIDE)
            if _MM_EMIT_PME_RCUT_NB_OVERRIDE is not None
            else _MM_EMIT_PME_RCUT_NB)


def _emit_mm_section(out, prmtop_file, ff_info_filename, gmax_a, gmax_b, gmax_c,
                     mm_scale14_policy, box_edges=None):
    """Emit &MM section with FORCEFIELD, SPLINE, FF_INFO PRINT, and POISSON/EWALD.

    `box_edges`, when supplied as (a,b,c) in Å, is used solely to emit a
    leading-order PME accuracy diagnostic (Kolafa & Perram, Mol. Simul. 9,
    351, 1992) that cross-checks the α/GMAX balance against the
    real-space RCUT_NB.  When omitted, only the emission is produced
    (backward-compatible).
    """
    if not isinstance(mm_scale14_policy, MMScale14Policy):
        raise TypeError("_emit_mm_section() requires an MMScale14Policy instance.")
    out.append("  &MM\n")
    out.append("    &FORCEFIELD\n")
    out.append("      PARMTYPE AMBER\n")
    out.append(f"      PARM_FILE_NAME {prmtop_file}\n")
    out.append("      ! Runtime 1-4 scaling is explicit here via CP2K FORCEFIELD keywords.\n")
    out.append("      ! Preserved PRMTOP SCEE/SCNB arrays are retained for topology fidelity only.\n")
    out.append(f"      ! Policy {mm_scale14_policy.mode}: {mm_scale14_policy.reason}\n")
    out.append(f"      EI_SCALE14 {mm_scale14_policy.ei_scale14:.10f}\n")
    out.append(f"      VDW_SCALE14 {mm_scale14_policy.vdw_scale14:.10f}\n")
    out.append("      &SPLINE\n")
    out.append("        EMAX_SPLINE 1.0E8\n")
    _effective_rcut = _effective_pme_rcut_nb()
    _effective_alpha = _effective_pme_alpha()
    out.append(f"        RCUT_NB [angstrom] {_effective_rcut:.1f}\n")
    out.append("      &END SPLINE\n")
    out.append("    &END FORCEFIELD\n")
    out.append("    &PRINT\n")
    out.append("      &FF_INFO\n")
    out.append(f"        FILENAME {ff_info_filename}\n")
    out.append("      &END FF_INFO\n")
    out.append("    &END PRINT\n")
    out.append("    &POISSON\n")
    out.append("    ! ── SPME accuracy diagnostic (Kolafa-Perram leading-order tails) ──\n")
    out.append("    ! Real-space error ≈ erfc(α·RCUT)/RCUT; reciprocal ≈ (2α/√π)·exp(-k²/4α²)/k.\n")
    out.append("    ! A well-tuned PME keeps both tails of the same magnitude (~target tol.).\n")
    if (_MM_EMIT_PME_ALPHA_OVERRIDE is not None
            or _MM_EMIT_PME_RCUT_NB_OVERRIDE is not None):
        out.append(
            "    ! NOTE: α and/or RCUT_NB overridden by user consent (E.1.b)"
            f" — α={_effective_alpha:.3f}, RCUT_NB={_effective_rcut:.2f} Å"
            f" (defaults {_MM_EMIT_PME_ALPHA:.3f} / {_MM_EMIT_PME_RCUT_NB:.1f} Å).\n"
        )
    if box_edges is not None:
        balance = evaluate_pme_tolerance_balance(
            _effective_alpha, _effective_rcut, box_edges,
            (gmax_a, gmax_b, gmax_c),
        )
        for msg in balance['messages']:
            out.append(f"    ! {msg}\n")
    else:
        out.append("    ! (box edges unavailable at emission — diagnostic suppressed)\n")
    out.append("      &EWALD\n")
    out.append("        EWALD_TYPE SPME\n")
    out.append(f"        ALPHA {_effective_alpha:.2f}\n")
    out.append("        ! GMAX: ~1.0 grid point per Angstrom (AMBER PME default density).\n")
    out.append("        ! For tighter MM electrostatics, increase by 20-50% (higher FFT cost).\n")
    out.append(f"        GMAX {gmax_a} {gmax_b} {gmax_c}\n")
    out.append("      &END EWALD\n")
    out.append("    &END POISSON\n")
    out.append("  &END MM\n\n")


def _emit_sampling_colvar_lines(out, sampling_config, indent="    "):
    """Emit CP2K-native &COLVAR blocks from an external sampling spec."""
    if not sampling_config:
        return
    for colvar in sampling_config.colvars:
        out.append(f"{indent}&COLVAR\n")
        if colvar.kind == 'DISTANCE':
            out.append(f"{indent}  &DISTANCE\n")
            out.append(f"{indent}    ATOMS {' '.join(str(i) for i in colvar.atoms)}\n")
            out.append(f"{indent}  &END DISTANCE\n")
        elif colvar.kind == 'ANGLE':
            out.append(f"{indent}  &ANGLE\n")
            out.append(f"{indent}    ATOMS {' '.join(str(i) for i in colvar.atoms)}\n")
            out.append(f"{indent}  &END ANGLE\n")
        elif colvar.kind == 'TORSION':
            out.append(f"{indent}  &TORSION\n")
            out.append(f"{indent}    ATOMS {' '.join(str(i) for i in colvar.atoms)}\n")
            out.append(f"{indent}  &END TORSION\n")
        elif colvar.kind == 'COORDINATION':
            out.append(f"{indent}  &COORDINATION\n")
            out.append(f"{indent}    ATOMS_FROM {' '.join(str(i) for i in colvar.atoms_from)}\n")
            out.append(f"{indent}    ATOMS_TO {' '.join(str(i) for i in colvar.atoms_to)}\n")
            out.append(f"{indent}    R0 {float(colvar.r0):.10f}\n")
            out.append(f"{indent}    NN {float(colvar.nn):.10f}\n")
            out.append(f"{indent}    ND {float(colvar.nd):.10f}\n")
            out.append(f"{indent}  &END COORDINATION\n")
        out.append(f"{indent}&END COLVAR\n")


def _emit_sampling_free_energy_lines(out, sampling_config, indent="  "):
    """Emit &FREE_ENERGY with METADYN or UI controls when requested."""
    if not sampling_config:
        return
    out.append(f"{indent}&FREE_ENERGY\n")
    if sampling_config.method == 'METADYNAMICS':
        meta = sampling_config.metadynamics
        out.append(f"{indent}  METHOD METADYN\n")
        out.append(f"{indent}  &METADYN\n")
        if meta.do_hills:
            out.append(f"{indent}    DO_HILLS\n")
        out.append(f"{indent}    NT_HILLS {int(meta.pace)}\n")
        out.append(f"{indent}    WW {float(meta.height):.10f}\n")
        if meta.well_tempered:
            out.append(f"{indent}    WELL_TEMPERED\n")
        if meta.delta_t is not None:
            out.append(f"{indent}    DELTA_T {float(meta.delta_t):.10f}\n")
        if meta.wtgamma is not None:
            out.append(f"{indent}    WTGAMMA {float(meta.wtgamma):.10f}\n")
        for idx, sigma in enumerate(meta.sigma, start=1):
            out.append(f"{indent}    &METAVAR\n")
            out.append(f"{indent}      COLVAR {idx}\n")
            out.append(f"{indent}      SCALE {float(sigma):.10f}\n")
            out.append(f"{indent}    &END METAVAR\n")
        out.append(f"{indent}  &END METADYN\n")
    else:
        out.append(f"{indent}  METHOD UI\n")
        out.append(f"{indent}  &UMBRELLA_INTEGRATION\n")
        out.append(f"{indent}  &END UMBRELLA_INTEGRATION\n")
    out.append(f"{indent}&END FREE_ENERGY\n\n")


def _emit_subsys(out, cell_abc, cell_angles, prmtop_file, xyz_file,
                 mm_kinds_lines, qm_kinds_preamble=None, qm_kinds_lines=None,
                 sampling_config=None):
    """Emit &SUBSYS with CELL, TOPOLOGY, optional QM KINDs, then MM KINDs."""
    out.append("  &SUBSYS\n")
    out.append("    &CELL\n")
    out.append(f"      ABC [angstrom] {cell_abc}\n")
    out.append(f"      ALPHA_BETA_GAMMA [deg] {cell_angles}\n")
    out.append("      PERIODIC XYZ\n")
    out.append("    &END CELL\n")
    out.append("    &TOPOLOGY\n")
    out.append(f"      CONN_FILE_NAME {prmtop_file}\n")
    out.append("      CONNECTIVITY AMBER\n")
    out.append(f"      COORD_FILE_NAME {xyz_file}\n")
    out.append("      COORDINATE XYZ\n")
    out.append("    &END TOPOLOGY\n\n")
    if qm_kinds_preamble:
        out.extend(qm_kinds_preamble)
    if qm_kinds_lines:
        out.extend(qm_kinds_lines)
        out.append("\n")
    _emit_sampling_colvar_lines(out, sampling_config, indent="    ")
    out.append("    ! ======================================\n")
    out.append("    ! MM ELEMENT MAPPINGS (CONFORMER KINDS)\n")
    out.append("    ! ======================================\n")
    out.extend(mm_kinds_lines)
    out.append("  &END SUBSYS\n")
    out.append("&END FORCE_EVAL\n\n")


def _emit_md_block(out, md_ensemble, md_steps, md_timestep, md_temperature,
                   md_energy_each=10, md_dynamics_config=None):
    """Emit &MD with ensemble, thermostat, barostat, and energy print."""
    if md_dynamics_config is None:
        md_dynamics_config = make_md_dynamics_config()
    elif not isinstance(md_dynamics_config, MDDynamicsConfig):
        raise TypeError("_emit_md_block() requires an MDDynamicsConfig instance or None.")
    out.append("  &MD\n")
    out.append(f"    ENSEMBLE {md_ensemble}\n")
    out.append(f"    STEPS {int(md_steps)}\n")
    out.append(f"    TIMESTEP [fs] {float(md_timestep)}\n")
    if md_ensemble != 'NVE' or md_dynamics_config.initialization_method:
        out.append(f"    TEMPERATURE [K] {float(md_temperature)}\n")
        if md_dynamics_config.initialization_method:
            out.append("    ! First-QM/MM-stage dynamics are explicit: fresh velocities are generated from TEMPERATURE instead of being inherited implicitly.\n")
            out.append(f"    INITIALIZATION_METHOD {md_dynamics_config.initialization_method}\n")
    if md_ensemble != 'NVE':
        out.append("    &THERMOSTAT\n")
        out.append("      TYPE CSVR\n")
        out.append("      &CSVR\n")
        if abs(float(md_dynamics_config.thermostat_timecon_fs) - float(DEFAULT_MD_THERMOSTAT_TIMECON_FS)) > 1.0e-12:
            out.append("        ! Shorter CSVR coupling is used here deliberately for explicit QM/MM transition equilibration.\n")
        out.append(f"        TIMECON [fs] {float(md_dynamics_config.thermostat_timecon_fs)}\n")
        out.append("      &END CSVR\n")
        out.append("    &END THERMOSTAT\n")
    if md_ensemble.startswith('NPT'):
        out.append("    &BAROSTAT\n")
        out.append("      PRESSURE [bar] 1.0\n")
        out.append(f"      TIMECON [fs] {float(md_dynamics_config.barostat_timecon_fs)}\n")
        out.append("    &END BAROSTAT\n")
    # Control center-of-mass drift with the CP2K 2025.2 MD keyword.  Older
    # generator drafts used a non-existent &COMVEL subsection; the schema and
    # bundled CP2K tests use COMVEL_TOL directly under &MD.
    out.append("    COMVEL_TOL 1.0E-6\n")
    out.append("    &PRINT\n")
    out.append("      &ENERGY\n")
    out.append("        &EACH\n")
    out.append(f"          MD {int(md_energy_each)}\n")
    out.append("        &END EACH\n")
    out.append("      &END ENERGY\n")
    out.append("    &END PRINT\n")
    out.append("  &END MD\n\n")


def _emit_md_motion_print(out, trajectory_format):
    """Emit &MOTION/&PRINT for MD: trajectory, cell, restart, restart history."""
    out.append("  &PRINT\n")
    out.append("    &TRAJECTORY\n")
    if trajectory_format == 'DCD':
        out.append("      ! CP2K defaults TRAJECTORY FORMAT to XMOL.\n")
        out.append("      ! Pipeline default is DCD for large periodic biomolecular MD because it is binary and stores cell information.\n")
    out.append(f"      FORMAT {trajectory_format}\n")
    out.append("      &EACH\n")
    out.append("        MD 100\n")
    out.append("      &END EACH\n")
    out.append("    &END TRAJECTORY\n")
    out.append("    &CELL\n")
    out.append("      &EACH\n")
    out.append("        MD 100\n")
    out.append("      &END EACH\n")
    out.append("    &END CELL\n")
    out.append("    &RESTART\n")
    out.append("      BACKUP_COPIES 3\n")
    out.append("      &EACH\n")
    out.append("        MD 1000\n")
    out.append("      &END EACH\n")
    out.append("    &END RESTART\n")
    out.append("    &RESTART_HISTORY\n")
    out.append("      &EACH\n")
    out.append("        MD 5000\n")
    out.append("      &END EACH\n")
    out.append("    &END RESTART_HISTORY\n")
    out.append("  &END PRINT\n")


def _emit_geo_opt_block(out, max_iter=200, pre_relaxation=False):
    """Emit &GEO_OPT with LBFGS optimizer.

    When pre_relaxation=True, emit relaxed convergence criteria appropriate
    for pre-equilibration energy minimization of large solvated biomolecular
    boxes, where strict convergence is not expected or required.
    """
    out.append("  &GEO_OPT\n")
    # LBFGS: linear-scaling memory; BFGS needs a full N×N Hessian which is
    # prohibitive for large biomolecular systems (>3000 degrees of freedom).
    # Ref: Nocedal, Math. Comp. 35, 773 (1980) — L-BFGS algorithm;
    #      CP2K Manual §MOTION/GEO_OPT/OPTIMIZER.
    out.append("    OPTIMIZER LBFGS\n")
    out.append(f"    MAX_ITER {int(max(1, max_iter))}\n")
    if pre_relaxation:
        # ── Pre-relaxation convergence criteria ─────────────────────────
        # Purpose: remove bad contacts and steric clashes before MD
        # equilibration.  CP2K defaults (MAX_FORCE 4.5e-4, RMS_FORCE
        # 3.0e-4, MAX_DR 3.0e-3, RMS_DR 1.5e-3 — all four must be
        # satisfied simultaneously) are designed for small-molecule or
        # crystal geometry optimization and are unnecessarily tight for
        # pre-equilibration of large solvated systems.  In boxes with
        # >10^5 atoms, the single worst-atom criteria (MAX_FORCE, MAX_DR)
        # are dominated by outlier solvent molecules or ions rather than
        # meaningful structural defects, causing the optimizer to exhaust
        # MAX_ITER even though the protein/QM-region is fully relaxed.
        #
        # The thresholds below (~5x CP2K defaults) ensure bad contacts are
        # resolved while remaining achievable for large solvated boxes.
        # Downstream MD equilibration (NVT, NPT) provides the real
        # structural relaxation through thermal sampling at kT >> residual
        # gradient magnitudes.
        #
        # Ref: CP2K Manual §MOTION/GEO_OPT — convergence criteria;
        #      CP2K QM/MM Tutorial (chorismate mutase) — 1000-step capped
        #      minimization before MD equilibration is standard protocol.
        out.append("    ! ── Pre-relaxation convergence criteria ─────────────────────\n")
        out.append("    ! Relaxed thresholds for pre-equilibration energy minimization\n")
        out.append("    ! of large solvated biomolecular boxes.  The purpose of this\n")
        out.append("    ! stage is to remove bad contacts before MD equilibration —\n")
        out.append("    ! strict convergence is neither required nor expected for\n")
        out.append("    ! systems with >10^5 atoms, where outlier solvent molecules\n")
        out.append("    ! dominate MAX_FORCE/MAX_DR.  Values are ~5x CP2K defaults.\n")
        out.append("    ! Ref: CP2K Manual §MOTION/GEO_OPT; CP2K QM/MM Tutorial.\n")
        out.append("    MAX_FORCE 2.0E-03\n")
        out.append("    RMS_FORCE 1.0E-03\n")
        out.append("    MAX_DR    1.5E-02\n")
        out.append("    RMS_DR   5.0E-03\n")
    out.append("  &END GEO_OPT\n")


def _emit_geo_opt_motion_print(out, trajectory_format):
    """Emit &MOTION/&PRINT for GEO_OPT: trajectory and restart."""
    out.append("  &PRINT\n")
    out.append("    &TRAJECTORY\n")
    if trajectory_format == 'DCD':
        out.append("      ! CP2K defaults TRAJECTORY FORMAT to XMOL.\n")
        out.append("      ! Pipeline default is DCD for large periodic biomolecular trajectories because it is binary and stores cell information.\n")
    out.append(f"      FORMAT {trajectory_format}\n")
    out.append("      &EACH\n")
    # Every-step output (GEO_OPT 1) generates ~3 GB for 143K-atom
    # pre-relaxations.  50 retains useful structural snapshots while
    # reducing I/O ~50×; the restart file captures the final geometry.
    out.append("        GEO_OPT 50\n")
    out.append("      &END EACH\n")
    out.append("    &END TRAJECTORY\n")
    out.append("    &RESTART\n")
    out.append("      BACKUP_COPIES 3\n")
    out.append("    &END RESTART\n")
    out.append("  &END PRINT\n")


def _make_ff_info_filename(project_name):
    """Derive the FF_INFO filename tag from the project name."""
    tag = re.sub(r'[^A-Za-z0-9_.-]+', '_', str(project_name or '').strip()) or 'cp2k'
    return f"{tag.lower()}_ff_info"


# ─── Assembler Data Model ────────────────────────────────────────────────────
#
# Core immutable config objects group the parameters that were previously
# passed as 40+ positional/keyword arguments. The assemblers now accept only
# these validated objects, which keeps routing explicit without proliferating
# adapter wrappers or keyword fan-out across the pipeline.
#
#   MMScale14Policy — explicit CP2K MM/FORCEFIELD 1-4 runtime scaling
#   QMMMPeriodicPolicy — linked QM-cell padding and MULTIPOLE RCUT policy
#   OTStepSizePolicy — OT initial line-search ownership (CP2K auto vs manual)
#   SystemModel      — invariant physical system: files, box, QM region, kinds
#   DFTConfig        — electronic-structure settings: functional, SCF, ADMM, OT
#   RunConfig        — one concrete CP2K run: project, run type, restart, output
#   WorkflowConfig   — staged MM→QM/MM plan that expands into RunConfig objects


class MMScale14Policy(NamedTuple):
    """Validated explicit CP2K MM 1-4 runtime scaling policy."""

    mode: str
    ei_scale14: float
    vdw_scale14: float
    label: str
    reason: str


class QMMMPeriodicPolicy(NamedTuple):
    """Validated linked policy for QM/MM periodic cell sizing and MULTIPOLE RCUT."""

    qm_cell_padding: float
    target_multipole_rcut: float
    minimum_image_buffer: float
    label: str
    reason: str


class QMMMHandoffPolicy(NamedTuple):
    """Validated MM→QM/MM handoff policy for the first QM/MM stage."""

    mode: str
    restart_velocities: bool
    restart_counters: bool
    restart_thermostat: bool
    restart_barostat: bool
    restart_randomg: bool
    label: str
    reason: str


class OTStepSizePolicy(NamedTuple):
    """Validated OT STEPSIZE ownership policy."""

    mode: str
    stepsize: float
    label: str
    reason: str


class MDDynamicsConfig(NamedTuple):
    """Validated stage-local MD initialization and thermostat/barostat control."""

    thermostat_timecon_fs: float
    barostat_timecon_fs: float
    initialization_method: object
    global_seed: object
    label: str
    reason: str


class TopologyVariant(NamedTuple):
    """Stage-specific topology view with one PRMTOP and matching MM KIND lines."""

    prmtop_file: str
    mm_kinds_lines: tuple
    label: str
    reason: str


class SystemModel(NamedTuple):
    """Validated physical system shared across MM-only and QM/MM stages."""

    xyz_file: str
    natom: object
    box_dims: object
    cell_abc: str
    cell_angles: str
    gmax_a: int
    gmax_b: int
    gmax_c: int
    qm_elements: OrderedDict
    link_bonds: tuple
    qm_kinds_lines: tuple
    mm_topology: TopologyVariant
    qmmm_topology: TopologyVariant
    mm_scale14_policy: MMScale14Policy
    qmmm_periodic_policy: QMMMPeriodicPolicy
    qm_cell_abc: str
    qm_charge: int
    multiplicity: int


class DFTConfig(NamedTuple):
    """Validated electronic-structure configuration for QM/MM assembly."""

    functional: str
    basis_set: str
    cutoff: float
    rel_cutoff: float
    use_admm: bool
    admm_aux_basis: object
    admm_exch_correction_func: object
    mgrid_ngrids: int
    scf_profile: str
    scf_max_scf: int
    scf_eps_scf: float
    scf_guess: str
    scf_cholesky_mode: object
    qs_eps_effective: float
    scf_added_mos: int
    scf_mixing_method: str
    scf_mixing_alpha: float
    scf_nbroyden: int
    outer_max_scf: int
    outer_eps_scf: float
    ot_minimizer: str
    ot_preconditioner: str
    ot_energy_gap: float
    ot_stepsize_policy: OTStepSizePolicy
    hf_max_memory: int
    qmmm_geep_lib: int
    boundary_charge_scheme: str
    is_hybrid: bool
    # D.1.a: whether to emit &VDW_POTENTIAL TYPE DFTD3(BJ).  Resolved at
    # config-construction time via ``validate_functional_dftd3_availability``
    # so an unparameterised functional cannot silently propagate to a
    # CP2K runtime error.  Defaults to True for the pipeline's current
    # functional set (PBE/PBE0/B3LYP — all DFTD3(BJ)-parameterised).
    emit_dftd3_vdw: bool = True
    # D.1.b: selected dispersion scheme written into &VDW_POTENTIAL.
    # Values: 'DFTD3_BJ' (default, CP2K-universal), 'DFTD4' (CP2K ≥ 8.1),
    # or 'NONE' (no dispersion correction — paired with emit_dftd3_vdw=False).
    # Promoted from 'DFTD3_BJ' to 'DFTD4' only via an explicit interactive
    # consent path in ``recommend_dftd4_upgrade``.
    dispersion_scheme: str = 'DFTD3_BJ'
    # D.2.a: optional ADVANCED-mode override of the auto-selected
    # ADMM_PURIFICATION_METHOD.  When None (default) the emitter picks
    # MO_DIAG for OT and NONE for DIAG per Guidon 2010 / Watkins 2015.
    # Setting it to one of ADMM_PURIFICATION_METHODS ({NONE,
    # NON_PURIFICATION, MO_DIAG}) forces that method; the emitter still
    # prevents the OT-only MO_DIAG from being written under DIAG SCF.
    admm_purification_override: object = None


class RunConfig(NamedTuple):
    """Validated configuration for one concrete CP2K stage/input."""

    project_name: str
    run_type: str
    ff_info_filename: str
    md_steps: int
    md_timestep: float
    md_temperature: float
    md_ensemble: str
    geo_opt_max_iter: int
    ext_restart_cfg: object
    wfn_restart_file: str
    fixed_atom_indices: object
    md_dynamics_config: MDDynamicsConfig
    trajectory_format: str
    sampling_config: object
    # Pre-relaxation flag: when True, the stage is a preparatory energy
    # minimization (bad-contact removal) whose strict GEO_OPT convergence
    # is not required before advancing to MD equilibration.
    # Ref: CP2K QM/MM Tutorial (chorismate mutase) — capped minimization
    #      before MD equilibration is standard biomolecular protocol.
    pre_relaxation: bool
    # QM/MM verbose-diagnostics flag (S9): when True the assembler injects
    # &PRINT/&PROGRAM_RUN_INFO HIGH and &PRINT/&GRID_INFORMATION into the
    # &QMMM block so the effective multipole RCUT, GEEP grid depth, and
    # FFT plan are visible in the output log.  Intended for the
    # 35_qmmm_warmup diagnostic stage only; production stages leave it
    # off so the log volume stays manageable.
    qmmm_verbose_diagnostics: bool = False


# ── StageRestartSpec: SSOT for CP2K per-stage restart filenames (S10) ────────
#
# CP2K emits two per-stage restart artifacts whose names are fixed by the
# CP2K runtime given the PROJECT identifier declared under &GLOBAL:
#   ``{PROJECT}-1.restart``   – external restart file (geometry/velocity/
#                               cell/thermostat/barostat/random-generator
#                               snapshot) consumed by &EXT_RESTART to
#                               continue a run without re-building the
#                               dynamical state.
#   ``{PROJECT}-RESTART.wfn`` – SCF wavefunction restart consumed by
#                               ``WFN_RESTART_FILE_NAME`` on any
#                               subsequent QS/QMMM stage to skip the
#                               cold-start guess.
# Neither suffix is configurable at input-file level; centralising them in
# one place eliminates the class of bugs where a stage handoff points to a
# filename that does not match what CP2K actually wrote (e.g. a typo in
# ``"35_qmmm_warmup-1.restart"`` versus the ``project_name`` declared for
# the same stage).  Ref: CP2K manual §GLOBAL/PROJECT, §MOTION/MD/&PRINT
# /RESTART, §FORCE_EVAL/DFT/SCF/&PRINT/RESTART.
class StageRestartSpec(NamedTuple):
    """Single source of truth for one CP2K stage's restart filenames."""

    # PROJECT identifier the stage emits under &GLOBAL; the filenames are
    # derived from this string by the CP2K runtime itself.
    project_name: str

    @property
    def ext_restart(self) -> str:
        """External restart filename ('{project}-1.restart')."""
        return f"{self.project_name}-1.restart"

    @property
    def wfn_restart(self) -> str:
        """SCF wavefunction restart filename ('{project}-RESTART.wfn')."""
        return f"{self.project_name}-RESTART.wfn"


# Canonical stage specs.  Any place in the assembler that needs either the
# ``project_name`` or one of the two restart filenames should reach for
# these constants rather than build the strings inline — keeping the
# relationship PROJECT ↔ restart-filename captured exactly once.
STAGE_EM_MM = StageRestartSpec('10_em_mm')
STAGE_NVT_MM = StageRestartSpec('20_nvt_mm')
STAGE_NPT_MM = StageRestartSpec('30_npt_mm')
STAGE_QMMM_WARMUP = StageRestartSpec('35_qmmm_warmup')
STAGE_QMMM_MD = StageRestartSpec('40_qmmm_md')


class WorkflowConfig(NamedTuple):
    """Validated staged MM→QM/MM workflow plan, including handoff semantics."""

    production_steps: int
    production_timestep: float
    production_temperature: float
    production_ensemble: str
    em_max_iter: int
    mm_nvt_steps: int
    mm_npt_steps: int
    mm_timestep: float
    enable_qmmm_warmup: bool
    qmmm_handoff_policy: QMMMHandoffPolicy
    qmmm_transition_thermostat_timecon_fs: float
    qmmm_transition_seed: object
    warmup_steps: int
    warmup_timestep: float
    warmup_ensemble: str
    warmup_restraints: bool
    mm_equil_restraints: bool
    stateless_restart: bool
    restraint_indices: tuple
    trajectory_format: str
    sampling_config: object
    # Opt-in verbose &QMMM/&PRINT diagnostics (S9).  When True the staged
    # assembler activates &PROGRAM_RUN_INFO and &GRID_INFORMATION on the
    # 35_qmmm_warmup diagnostic stage only (production stages remain
    # silent).  Typical use: first-run verification of the effective
    # &PERIODIC/&MULTIPOLE RCUT and the GEEP grid depth that CP2K
    # actually applied.  Ref: CP2K manual §FORCE_EVAL/QMMM/PRINT.
    qmmm_verbose_diagnostics: bool = False


class SamplingColvar(NamedTuple):
    """One externally declared collective variable."""

    name: str
    kind: str
    atoms: tuple
    atoms_from: tuple
    atoms_to: tuple
    r0: object
    nn: object
    nd: object


class SamplingMetadynamicsConfig(NamedTuple):
    """Metadynamics control parameters mapped to CP2K &METADYN."""

    height: float
    pace: int
    sigma: tuple
    do_hills: bool
    well_tempered: bool
    delta_t: object
    wtgamma: object


class SamplingRestraint(NamedTuple):
    """Umbrella/collective restraint mapped to CP2K &COLLECTIVE/&RESTRAINT."""

    colvar: str
    target: float
    k: float
    intermolecular: bool


class SamplingConfig(NamedTuple):
    """Optional advanced free-energy sampling declaration."""

    source_path: str
    source_format: str
    method: str
    colvars: tuple
    metadynamics: object
    restraints: tuple


def make_system_spec(
    prmtop_file, xyz_file, box_dims,
    qm_elements=None, link_bonds=None,
    qm_kinds_lines=None, mm_kinds_lines=None,
    qm_cell_abc="25.0 25.0 25.0",
    qm_charge=0, multiplicity=1,
    natom=None,
    mm_scale14_policy=None,
    qmmm_periodic_policy=None,
    mm_prmtop_file=None,
    qmmm_prmtop_file=None,
    mm_stage_kinds_lines=None,
    qmmm_stage_kinds_lines=None,
):
    """Create a validated SystemModel describing the physical system.

    Groups topology file paths, periodic box, QM/MM region definition,
    pre-generated KIND lines, and the QM charge/multiplicity that together
    define the invariant chemistry of the system, including explicit MM-only
    and QM/MM topology variants so the staged workflow can preserve the
    original classical charge model for FIST stages while using a redistributed
    topology for split-residue QM/MM stages.
    """
    cell_abc, cell_angles, gmax_a, gmax_b, gmax_c = _resolve_box_params(box_dims)
    resolved_natom = None if natom is None else int(natom)
    if resolved_natom is not None and resolved_natom < 1:
        raise ValueError(f"natom must be >= 1 when provided. Got {resolved_natom}.")
    if mm_scale14_policy is None:
        mm_scale14_policy = make_mm_scale14_policy()
    elif not isinstance(mm_scale14_policy, MMScale14Policy):
        raise TypeError("mm_scale14_policy must be an MMScale14Policy instance or None.")
    if qmmm_periodic_policy is None:
        qmmm_periodic_policy = make_qmmm_periodic_policy()
    elif not isinstance(qmmm_periodic_policy, QMMMPeriodicPolicy):
        raise TypeError("qmmm_periodic_policy must be a QMMMPeriodicPolicy instance or None.")
    qm_map = OrderedDict()
    for elem, indices in OrderedDict(qm_elements or {}).items():
        qm_map[str(elem)] = tuple(str(i) for i in indices)
    shared_prmtop = str(prmtop_file or '').strip()
    resolved_mm_prmtop = str(mm_prmtop_file or shared_prmtop).strip()
    resolved_qmmm_prmtop = str(qmmm_prmtop_file or shared_prmtop).strip()
    if not resolved_mm_prmtop:
        raise ValueError("MM-stage PRMTOP path must not be empty.")
    if not resolved_qmmm_prmtop:
        raise ValueError("QM/MM-stage PRMTOP path must not be empty.")
    shared_mm_kinds = tuple(mm_kinds_lines or [])
    mm_variant_kinds = tuple(mm_stage_kinds_lines if mm_stage_kinds_lines is not None else shared_mm_kinds)
    qmmm_variant_kinds = tuple(qmmm_stage_kinds_lines if qmmm_stage_kinds_lines is not None else shared_mm_kinds)
    return SystemModel(
        xyz_file=str(xyz_file),
        natom=resolved_natom,
        box_dims=tuple(box_dims) if box_dims is not None else None,
        cell_abc=cell_abc,
        cell_angles=cell_angles,
        gmax_a=gmax_a,
        gmax_b=gmax_b,
        gmax_c=gmax_c,
        qm_elements=qm_map,
        link_bonds=tuple(dict(link) for link in (link_bonds or [])),
        qm_kinds_lines=tuple(qm_kinds_lines or []),
        mm_topology=TopologyVariant(
            prmtop_file=resolved_mm_prmtop,
            mm_kinds_lines=mm_variant_kinds,
            label='MM',
            reason='Original-charge classical topology for MM-only FIST stages.',
        ),
        qmmm_topology=TopologyVariant(
            prmtop_file=resolved_qmmm_prmtop,
            mm_kinds_lines=qmmm_variant_kinds,
            label='QM/MM',
            reason='Split-residue charge-redistributed topology for QM/MM stages.',
        ),
        mm_scale14_policy=mm_scale14_policy,
        qmmm_periodic_policy=qmmm_periodic_policy,
        qm_cell_abc=str(qm_cell_abc),
        qm_charge=int(qm_charge),
        multiplicity=max(1, int(multiplicity)),
    )


def make_dft_config(
    functional='B3LYP', basis_set='DZVP-MOLOPT-GTH',
    cutoff=500, rel_cutoff=60,
    use_admm=True, admm_aux_basis=None, admm_exch_correction_func=None,
    mgrid_ngrids=None,
    scf_profile='ROUTINE_OT',
    scf_max_scf=140, scf_eps_scf=1.0e-6, scf_guess='ATOMIC',
    scf_cholesky=None, qs_eps_default=None,
    scf_added_mos=120, scf_mixing_method='DIRECT_P_MIXING',
    scf_mixing_alpha=0.35, scf_nbroyden=8,
    outer_max_scf=15, outer_eps_scf=1.0e-6,
    ot_minimizer=DEFAULT_OT_MINIMIZER,
    ot_preconditioner=DEFAULT_OT_PRECONDITIONER,
    ot_energy_gap=DEFAULT_OT_ENERGY_GAP,
    ot_stepsize=None,
    ot_stepsize_mode=DEFAULT_OT_STEPSIZE_POLICY,
    hf_max_memory=DEFAULT_HF_MAX_MEMORY,
    qmmm_geep_lib=DEFAULT_QMMM_GEEP_LIB,
    boundary_charge_scheme=DEFAULT_BOUNDARY_CHARGE_SCHEME,
    qm_elements_for_admm=None,
    qm_kinds_lines_for_admm=None,
    emit_dftd3_vdw=None,
    dftd3_interactive=False,
    dftd3_run_provenance=None,
    dispersion_scheme='DFTD3_BJ',
    admm_purification_override=None,
):
    """Create a validated DFTConfig with all electronic-structure settings.

    Performs every normalization and cross-validation (functional ↔ PP prefix,
    ADMM coverage, SCF profile → engine, OT gap, boundary charge scheme) so
    the downstream emitters receive only validated values.
    """
    functional_upper = validate_functional(functional)
    basis_set = validate_basis_set(basis_set)
    qmmm_geep_lib = validate_qmmm_geep_lib(qmmm_geep_lib)
    mgrid_ngrids = resolve_mgrid_ngrids(basis_set, mgrid_ngrids)
    admm_aux_basis = resolve_admm_aux_basis(
        qm_elements_for_admm,
        admm_aux_basis or _infer_admm_aux_basis_from_qm_kinds(qm_kinds_lines_for_admm),
        use_admm=use_admm,
        basis_set=basis_set,
    )
    admm_exch_correction_func = resolve_admm_exch_correction_func(
        functional, admm_exch_correction_func, use_admm=use_admm,
    )
    ot_minimizer = normalize_ot_minimizer(ot_minimizer)
    ot_preconditioner = str(ot_preconditioner or DEFAULT_OT_PRECONDITIONER).strip().upper() or DEFAULT_OT_PRECONDITIONER
    ot_energy_gap = validate_ot_energy_gap(
        DEFAULT_OT_ENERGY_GAP if ot_energy_gap is None else ot_energy_gap
    )
    ot_stepsize_policy = make_ot_stepsize_policy(
        mode=ot_stepsize_mode,
        stepsize=ot_stepsize,
        ot_preconditioner=ot_preconditioner,
    )
    hf_max_memory = validate_hf_max_memory(hf_max_memory)
    raw_bcs = str(boundary_charge_scheme or DEFAULT_BOUNDARY_CHARGE_SCHEME).strip().upper()
    boundary_charge_scheme = normalize_boundary_charge_scheme(raw_bcs)
    if raw_bcs not in BOUNDARY_CHARGE_SCHEMES:
        warn(f"Unknown boundary charge scheme '{raw_bcs}'; using {DEFAULT_BOUNDARY_CHARGE_SCHEME}.")
    scf_cholesky_mode = normalize_scf_cholesky(scf_cholesky)
    qs_eps_mode = normalize_qs_eps_default(qs_eps_default)
    scf_profile_mode = _validate_scf_profile_key(scf_profile or 'ROUTINE_OT')
    if scf_profile_mode != 'ADVANCED':
        scf_cholesky_mode = None
        qs_eps_mode = None
    elif qs_eps_mode is not None and qs_eps_mode > QUICKSTEP_EPS_DEFAULT:
        raise ValueError(
            f"ADVANCED Quickstep EPS_DEFAULT must be <= {QUICKSTEP_EPS_DEFAULT:.1E} "
            f"(tighter than CP2K default). Got {qs_eps_mode:.1E}."
        )
    qs_eps_effective = qs_eps_mode if qs_eps_mode is not None else QUICKSTEP_EPS_DEFAULT

    return DFTConfig(
        functional=functional_upper,
        basis_set=basis_set,
        cutoff=float(cutoff),
        rel_cutoff=float(rel_cutoff),
        use_admm=bool(use_admm),
        admm_aux_basis=admm_aux_basis,
        admm_exch_correction_func=admm_exch_correction_func,
        mgrid_ngrids=int(mgrid_ngrids),
        scf_profile=scf_profile_mode,
        scf_max_scf=int(scf_max_scf),
        scf_eps_scf=float(scf_eps_scf),
        # A.3.a: SCF_GUESS is validated against the canonical choice list
        # (ATOMIC / RESTART / MOPAC / CORE) at config-construction time so
        # typos are caught before CP2K parses them; the automatic promotion
        # to RESTART when WFN_RESTART_FILE_NAME is wired up happens later
        # in _assemble_qmmm_input (not a silent config change — it is the
        # explicit RESTART path indicated by the caller).  Per
        # feedback_no_silent_modifications, the validator returns the
        # canonical spelling exactly; it never rewrites the token.
        scf_guess=validate_scf_guess(scf_guess),
        scf_cholesky_mode=scf_cholesky_mode,
        qs_eps_effective=float(qs_eps_effective),
        scf_added_mos=int(scf_added_mos),
        scf_mixing_method=str(scf_mixing_method).upper(),
        scf_mixing_alpha=float(scf_mixing_alpha),
        scf_nbroyden=int(scf_nbroyden),
        outer_max_scf=int(outer_max_scf),
        outer_eps_scf=float(outer_eps_scf),
        ot_minimizer=ot_minimizer,
        ot_preconditioner=ot_preconditioner,
        ot_energy_gap=float(ot_energy_gap),
        ot_stepsize_policy=ot_stepsize_policy,
        hf_max_memory=int(hf_max_memory),
        qmmm_geep_lib=int(qmmm_geep_lib),
        boundary_charge_scheme=boundary_charge_scheme,
        is_hybrid=functional_upper in HYBRID_DFT_FUNCTIONALS,
        # D.1.a: DFTD3(BJ) availability gate.  When the caller passes an
        # explicit emit_dftd3_vdw we trust it (override hook for runs that
        # deliberately skip dispersion), otherwise we consult the
        # availability table.  An unknown functional returns None → treated
        # as False (safer default) per feedback_no_silent_modifications.
        emit_dftd3_vdw=(
            bool(emit_dftd3_vdw)
            if emit_dftd3_vdw is not None
            else bool(
                validate_functional_dftd3_availability(
                    functional_upper,
                    interactive=bool(dftd3_interactive),
                    run_provenance=dftd3_run_provenance,
                )
            )
        ),
        dispersion_scheme=_validate_dispersion_scheme(dispersion_scheme),
        admm_purification_override=validate_admm_purification_override(admm_purification_override),
    )


def make_run_config(
    project_name, run_type='MD',
    preset='production',
    md_steps=None, md_timestep=None, md_temperature=None, md_ensemble=None,
    temperature=None,
    geo_opt_max_iter=200,
    ext_restart_cfg=None,
    wfn_restart_file=None,
    fixed_atom_indices=None,
    md_dynamics_config=None,
    trajectory_format=DEFAULT_TRAJECTORY_FORMAT,
    sampling_config=None,
    pre_relaxation=False,
    qmmm_verbose_diagnostics=False,
):
    """Create a validated RunConfig with execution parameters.

    Resolves MD defaults from the named preset when individual values are
    None, validates the run type, and normalizes the trajectory format.
    """
    run_type = validate_run_type(run_type)
    trajectory_format = normalize_trajectory_format(trajectory_format)
    if sampling_config is not None and not isinstance(sampling_config, SamplingConfig):
        raise TypeError("sampling_config must be a SamplingConfig instance or None.")
    if md_dynamics_config is None:
        md_dynamics_config = make_md_dynamics_config()
    elif not isinstance(md_dynamics_config, MDDynamicsConfig):
        raise TypeError("md_dynamics_config must be an MDDynamicsConfig instance or None.")
    ff_info_filename = _make_ff_info_filename(project_name)

    p = PRESETS.get(preset, PRESETS['production'])
    resolved_md_steps = int(md_steps if md_steps is not None else p['steps'])
    resolved_md_timestep = float(md_timestep if md_timestep is not None else p['timestep'])
    resolved_md_ensemble = str(md_ensemble if md_ensemble is not None else p.get('ensemble', 'NVT')).upper()
    resolved_md_temperature = md_temperature
    if resolved_md_temperature is None:
        resolved_md_temperature = temperature
    if resolved_md_temperature is None:
        resolved_md_temperature = p.get('temperature', 300.0)
    resolved_md_temperature = float(resolved_md_temperature)

    return RunConfig(
        project_name=str(project_name),
        run_type=run_type,
        ff_info_filename=ff_info_filename,
        md_steps=resolved_md_steps,
        md_timestep=resolved_md_timestep,
        md_temperature=resolved_md_temperature,
        md_ensemble=resolved_md_ensemble,
        geo_opt_max_iter=int(geo_opt_max_iter),
        ext_restart_cfg=ext_restart_cfg,
        wfn_restart_file=str(wfn_restart_file or '').strip(),
        fixed_atom_indices=fixed_atom_indices,
        md_dynamics_config=md_dynamics_config,
        trajectory_format=trajectory_format,
        sampling_config=sampling_config,
        pre_relaxation=bool(pre_relaxation),
        qmmm_verbose_diagnostics=bool(qmmm_verbose_diagnostics),
    )


def make_workflow_config(
    production_steps=100000,
    production_timestep=1.0,
    production_temperature=300.0,
    production_ensemble='NVT',
    em_max_iter=2000,
    mm_nvt_steps=5000,
    mm_npt_steps=10000,
    mm_timestep=1.0,
    enable_qmmm_warmup=True,
    qmmm_handoff_policy=None,
    handoff_restart_velocities=None,
    qmmm_transition_thermostat_timecon_fs=DEFAULT_QMMM_TRANSITION_THERMOSTAT_TIMECON_FS,
    qmmm_transition_seed=DEFAULT_QMMM_TRANSITION_SEED,
    warmup_steps=2000,
    warmup_timestep=0.25,
    warmup_ensemble='NVT',
    warmup_restraints=False,
    mm_equil_restraints=False,
    stateless_restart=False,
    restraint_indices=None,
    trajectory_format=DEFAULT_TRAJECTORY_FORMAT,
    sampling_config=None,
    qmmm_verbose_diagnostics=False,
):
    """Create a validated WorkflowConfig for the staged MM→QM/MM pipeline."""
    if sampling_config is not None and not isinstance(sampling_config, SamplingConfig):
        raise TypeError("sampling_config must be a SamplingConfig instance or None.")
    if qmmm_handoff_policy is None:
        qmmm_handoff_policy = make_qmmm_handoff_policy(
            handoff_restart_velocities=handoff_restart_velocities
        )
    elif not isinstance(qmmm_handoff_policy, QMMMHandoffPolicy):
        if handoff_restart_velocities is not None:
            raise TypeError(
                "Provide either qmmm_handoff_policy or handoff_restart_velocities, not both as non-policy values."
            )
        qmmm_handoff_policy = make_qmmm_handoff_policy(mode=qmmm_handoff_policy)
    return WorkflowConfig(
        production_steps=max(1, int(production_steps)),
        production_timestep=float(production_timestep),
        production_temperature=float(production_temperature),
        production_ensemble=str(production_ensemble).upper(),
        em_max_iter=max(1, int(em_max_iter)),
        mm_nvt_steps=max(1, int(mm_nvt_steps)),
        mm_npt_steps=max(1, int(mm_npt_steps)),
        mm_timestep=float(mm_timestep),
        enable_qmmm_warmup=bool(enable_qmmm_warmup),
        qmmm_handoff_policy=qmmm_handoff_policy,
        qmmm_transition_thermostat_timecon_fs=validate_md_timecon(
            qmmm_transition_thermostat_timecon_fs,
            "First QM/MM-stage thermostat TIMECON",
        ),
        qmmm_transition_seed=validate_global_seed(qmmm_transition_seed, "First QM/MM-stage GLOBAL SEED"),
        warmup_steps=max(1, int(warmup_steps)),
        warmup_timestep=float(warmup_timestep),
        warmup_ensemble=str(warmup_ensemble or 'NVT').strip().upper(),
        warmup_restraints=bool(warmup_restraints),
        mm_equil_restraints=bool(mm_equil_restraints),
        stateless_restart=bool(stateless_restart),
        restraint_indices=tuple(_normalize_fixed_atom_indices(restraint_indices)),
        trajectory_format=normalize_trajectory_format(trajectory_format),
        sampling_config=sampling_config,
        qmmm_verbose_diagnostics=bool(qmmm_verbose_diagnostics),
    )


def assemble_cp2k_input(system_model, dft_config, run_config):
    """Assemble a QM/MM CP2K input from validated SystemModel/DFTConfig/RunConfig."""
    if not isinstance(system_model, SystemModel):
        raise TypeError("assemble_cp2k_input() requires a SystemModel instance.")
    if not isinstance(dft_config, DFTConfig):
        raise TypeError("assemble_cp2k_input() requires a DFTConfig instance.")
    if not isinstance(run_config, RunConfig):
        raise TypeError("assemble_cp2k_input() requires a RunConfig instance.")
    validate_sampling_config_indices(run_config.sampling_config, system_model.natom)
    return _assemble_qmmm_input(system_model, dft_config, run_config)


def _assemble_qmmm_input(system_model, dft_config, run_config):
    """Core QM/MM CP2K input assembler operating on validated config objects."""
    s = system_model
    d = dft_config._asdict()
    r = run_config._asdict()
    run_type = r['run_type']
    if r['sampling_config'] and run_type != 'MD':
        raise ValueError("Advanced free-energy sampling is only supported for RUN_TYPE MD.")
    functional_upper = d['functional']
    basis_set = d['basis_set']
    is_hybrid = d['is_hybrid']
    qmmm_topology = s.qmmm_topology
    cell_abc = s.cell_abc
    cell_angles = s.cell_angles
    gmax_a, gmax_b, gmax_c = s.gmax_a, s.gmax_b, s.gmax_c
    qm_cell_abc = s.qm_cell_abc
    qm_mult = s.multiplicity
    ff_info_filename = r['ff_info_filename']
    wfn_restart_name = r['wfn_restart_file']
    md_ensemble = r['md_ensemble']
    qmmm_periodic = evaluate_qmmm_periodic_electrostatics(qm_cell_abc, s.qmmm_periodic_policy)

    dft_population_each = 1
    scf_iteration_info_each = 1
    md_energy_each = 1
    if run_type == 'MD':
        dft_population_each = 10
        scf_iteration_info_each = 5
        md_energy_each = 10

    out = []
    _emit_global(out, r['project_name'], run_type, global_seed=r['md_dynamics_config'].global_seed)
    _append_ext_restart_lines(out, r['ext_restart_cfg'])

    # ——— &FORCE_EVAL ———
    out.append("&FORCE_EVAL\n")
    out.append("  METHOD QMMM\n\n")
    if run_type == 'MD' and _md_ensemble_requires_stress_tensor(md_ensemble):
        out.append("  STRESS_TENSOR ANALYTICAL\n\n")

    # &DFT
    out.append("  &DFT\n")
    out.append("    BASIS_SET_FILE_NAME BASIS_MOLOPT\n")
    if d['use_admm']:
        for basis_file in admm_aux_basis_file_names(d['admm_aux_basis']):
            out.append(f"    BASIS_SET_FILE_NAME {basis_file}\n")
    out.append("    POTENTIAL_FILE_NAME GTH_POTENTIALS\n\n")
    if wfn_restart_name:
        out.append(f"    WFN_RESTART_FILE_NAME {wfn_restart_name}\n")
    use_diag_scf = should_use_diagonalization_scf(
        functional=functional_upper,
        multiplicity=qm_mult,
        qm_elements=s.qm_elements,
        scf_profile=d['scf_profile'],
    )
    out.append(f"    CHARGE {int(s.qm_charge)}\n")
    out.append(f"    MULTIPLICITY {qm_mult}\n")
    if qm_mult != 1:
        out.append("    UKS\n")
    out.append(f"    &MGRID\n")
    out.append(f"      CUTOFF [Ry] {d['cutoff']:g}\n")
    out.append(f"      REL_CUTOFF [Ry] {d['rel_cutoff']:g}\n")
    out.append(f"      NGRIDS {d['mgrid_ngrids']}\n")
    out.append("      COMMENSURATE T\n")
    out.append(f"    &END MGRID\n\n")
    out.append("    &QS\n")
    out.append("      METHOD GPW\n")
    out.append(f"      EPS_DEFAULT {d['qs_eps_effective']:.1E}\n")
    if run_type == 'MD':
        out.append("      ! Explicit MD-specific QS extrapolation per CP2K MD guidance.\n")
        out.append("      ! Omitting this would inherit the generic QS default ASPC/3.\n")
        out.append(f"      EXTRAPOLATION {MD_QS_EXTRAPOLATION}\n")
        out.append(f"      EXTRAPOLATION_ORDER {int(MD_QS_EXTRAPOLATION_ORDER)}\n")
    if is_hybrid:
        # Guarantee a fully occupied KS matrix for HFX pair list construction.
        # Without this, CP2K may skip long-range HFX pairs, corrupting the
        # exact-exchange energy and preventing SCF convergence.
        # Ref: CP2K FAQ hfx_eps_warning; hfx_energy_potential.F:587 warning.
        out.append("      MIN_PAIR_LIST_RADIUS -1\n")
    out.append("    &END QS\n\n")
    out.append("    ! Explicit periodic QM Poisson solver for periodic QM/MM electrostatics.\n")
    out.append("    ! This avoids relying on CP2K defaults when QMMM uses periodic Gauss embedding.\n")
    out.append("    &POISSON\n")
    out.append("      PERIODIC XYZ\n")
    out.append("      PSOLVER PERIODIC\n")
    out.append("    &END POISSON\n\n")

    out.append("    &SCF\n")
    out.append(f"      MAX_SCF {d['scf_max_scf']}\n")
    out.append(f"      EPS_SCF {d['scf_eps_scf']:.1E}\n")
    scf_guess_token = d['scf_guess']
    if wfn_restart_name:
        scf_guess_token = 'RESTART'
    out.append(f"      SCF_GUESS {scf_guess_token}\n")
    if d['scf_cholesky_mode']:
        out.append(f"      CHOLESKY {d['scf_cholesky_mode']}\n")
    if use_diag_scf:
        added_mos = max(0, d['scf_added_mos'])
        if added_mos > 0:
            out.append(f"      ADDED_MOS {added_mos}\n")
        out.append("      &DIAGONALIZATION\n")
        out.append("        ALGORITHM STANDARD\n")
        out.append("      &END DIAGONALIZATION\n")
        out.append("      &MIXING\n")
        out.append(f"        METHOD {d['scf_mixing_method']}\n")
        out.append(f"        ALPHA {d['scf_mixing_alpha']:.2f}\n")
        out.append(f"        NBROYDEN {d['scf_nbroyden']}\n")
        out.append("      &END MIXING\n")

        # ── Profile-driven emission of LEVEL_SHIFT and &SMEAR ──────────
        # The emitter consults the selected profile's declarative
        # metadata (SCF_PROFILES[d['scf_profile']]) rather than inferring
        # from multiplicity alone.  This is the seam that separates the
        # two open-shell populations:
        #   • TM radicals  → expects_smearing=True, level_shift=None
        #   • organic π    → expects_smearing=False, level_shift≈0.15 Ha
        # Gating smearing on multiplicity alone (the previous behaviour)
        # collapsed both into a metallic-prior recipe and caused
        # charge-transfer sloshing in organic-radical QM regions such as
        # flavoenzymes.  SCF_PROFILES.get(..., {}) is defensive against
        # unknown profile names; .get('key') on an empty dict yields None.
        _profile_meta = SCF_PROFILES.get(d['scf_profile'], {})

        # LEVEL_SHIFT: shift unoccupied orbitals upward during density
        # construction to suppress occ↔virt swaps in near-degenerate
        # frontier manifolds (organic π-radicals).  The shift is lifted
        # at convergence by self-consistent re-diagonalisation, so it
        # does not bias converged energies.
        # Ref: Saunders & Hillier, Int. J. Quantum Chem. 7, 699 (1973);
        #      CP2K Manual §CP2K_INPUT/FORCE_EVAL/DFT/SCF/LEVEL_SHIFT.
        _level_shift_ha = _profile_meta.get('level_shift')
        if _level_shift_ha is not None and float(_level_shift_ha) > 0.0:
            out.append(
                f"      LEVEL_SHIFT [hartree] {float(_level_shift_ha):.3f}\n"
            )

        # Fermi-Dirac smearing: finite electronic temperature assigns
        # fractional occupations near the Fermi level.  This is the
        # physically correct tool ONLY for systems whose frontier
        # manifold is a quasi-continuum (transition-metal d-manifolds).
        # For organic π-radicals the SOMO is discrete and smearing
        # fractionalises it, preventing convergence to the true
        # spin-polarised ground state.
        # Refs: Mermin, Phys. Rev. 137, A1441 (1965) — finite-T DFT;
        #       Rabuck & Scuseria, J. Chem. Phys. 110, 695 (1999) —
        #       smearing as a convergence aid for metals.
        _expects_smearing = bool(_profile_meta.get('expects_smearing', False))
        if _expects_smearing and qm_mult > 1:
            out.append("      &SMEAR\n")
            out.append("        METHOD FERMI_DIRAC\n")
            out.append("        ELECTRONIC_TEMPERATURE [K] 300\n")
            out.append("      &END SMEAR\n")
    else:
        out.append("      &OT\n")
        out.append(f"        MINIMIZER {d['ot_minimizer']}\n")
        out.append(f"        PRECONDITIONER {d['ot_preconditioner']}\n")
        out.append(f"        ENERGY_GAP {d['ot_energy_gap']:.1E}\n")
        if d['ot_stepsize_policy'].mode == 'AUTO':
            out.append("        ! STEPSIZE is the initial OT line-search step only.\n")
            out.append("        ! Emit -1.0 explicitly so CP2K chooses the preconditioner-dependent value.\n")
            ot_stepsize_text = f"{d['ot_stepsize_policy'].stepsize:.1f}"
        else:
            out.append("        ! Explicit manual OT initial line-search step for reproducible tuning.\n")
            ot_stepsize_text = f"{d['ot_stepsize_policy'].stepsize:g}"
        out.append(f"        STEPSIZE {ot_stepsize_text}\n")
        out.append("      &END OT\n")
    out.append("      &OUTER_SCF\n")
    out.append(f"        MAX_SCF {d['outer_max_scf']}\n")
    out.append(f"        EPS_SCF {d['outer_eps_scf']:.1E}\n")
    out.append("      &END OUTER_SCF\n")
    out.append("      &PRINT\n")
    out.append("        &ITERATION_INFO\n")
    out.append("          &EACH\n")
    out.append(f"            QS_SCF {int(scf_iteration_info_each)}\n")
    out.append("          &END EACH\n")
    out.append("        &END ITERATION_INFO\n")
    out.append("      &END PRINT\n")
    out.append("    &END SCF\n\n")

    # Population-analysis telemetry for QM charge redistribution monitoring.
    dft_each_key = 'MD' if run_type == 'MD' else ('GEO_OPT' if run_type == 'GEO_OPT' else 'QS_SCF')
    out.append("    &PRINT\n")
    out.append("      &MULLIKEN\n")
    out.append("        &EACH\n")
    out.append(f"          {dft_each_key} {int(dft_population_each)}\n")
    out.append("        &END EACH\n")
    out.append("      &END MULLIKEN\n")
    out.append("      &HIRSHFELD\n")
    out.append("        SELF_CONSISTENT T\n")
    out.append("        SHAPE_FUNCTION DENSITY\n")
    out.append("        &EACH\n")
    out.append(f"          {dft_each_key} {int(dft_population_each)}\n")
    out.append("        &END EACH\n")
    out.append("      &END HIRSHFELD\n")
    out.append("    &END PRINT\n\n")

    # XC functional
    out.append("    &XC\n")
    out.append("      &XC_FUNCTIONAL\n")
    if functional_upper == 'B3LYP':
        # Explicit B3LYP(VWN3) decomposition for cross-code reproducibility.
        # Stephens et al., J. Phys. Chem. 98, 11623 (1994).
        out.append("        ! ── B3LYP (Gaussian convention, VWN III) ──────────────────\n")
        out.append("        ! Explicit component decomposition of the Gaussian-convention\n")
        out.append("        ! B3LYP functional.  This uses VWN(III) local correlation,\n")
        out.append("        ! NOT VWN(V).  CP2K's shortcut '&XC_FUNCTIONAL B3LYP' uses\n")
        out.append("        ! VWN(V) instead, giving different energies (~0.5-2 kcal/mol).\n")
        out.append("        ! The Gaussian convention matches ORCA, Gaussian, GAMESS, and\n")
        out.append("        ! the majority of published QM/MM literature.\n")
        out.append("        ! Do NOT replace this decomposition with the B3LYP shortcut.\n")
        out.append("        ! Ref: Stephens et al., J. Phys. Chem. 98, 11623 (1994);\n")
        out.append("        !      Vosko, Wilk, Nusair, Can. J. Phys. 58, 1200 (1980).\n")
        out.append("        &LYP\n")
        out.append("          SCALE_C 0.81\n")
        out.append("        &END LYP\n")
        out.append("        &BECKE88\n")
        out.append("          SCALE_X 0.72\n")
        out.append("        &END BECKE88\n")
        out.append("        &VWN\n")
        out.append("          FUNCTIONAL_TYPE VWN3\n")
        out.append("          SCALE_C 0.19\n")
        out.append("        &END VWN\n")
        out.append("        &XALPHA\n")
        out.append("          SCALE_X 0.08\n")
        out.append("        &END XALPHA\n")
    elif functional_upper == 'PBE0':
        # PBE0 = 0.75·PBE_X + 0.25·HF_X + PBE_C; SCALE_X must be set
        # explicitly because CP2K does not auto-rescale DFT exchange
        # when &HF FRACTION is present (CP2K regtests: regtest-hybrid-1).
        out.append("        &PBE\n")
        out.append("          SCALE_X 0.75\n")
        out.append("          SCALE_C 1.0\n")
        out.append("        &END PBE\n")
    elif functional_upper == 'PBE':
        # Explicit subsection required; bare "PBE" is not valid CP2K syntax
        # inside &XC_FUNCTIONAL without the section-parameter shortcut.
        out.append("        &PBE\n")
        out.append("        &END PBE\n")
    out.append("      &END XC_FUNCTIONAL\n\n")

    if is_hybrid:
        # ── Hybrid HFX truncated-Coulomb cutoff ───────────────────────────
        # Periodic hybrid QM/MM uses the TRUNCATED interaction potential
        # (Spencer & Alavi, Phys. Rev. B 77, 193110 (2008); Guidon, Hutter,
        # VandeVondele, JCTC 5, 3010 (2009)).  The cutoff radius must be
        # strictly less than half the shortest QM-cell edge (L/2) so that
        # the truncated kernel does not include self-images in the
        # real-space sum.  The contract with compute_qm_cell() is that
        # `qm_cell_abc` is always a three-float string; violating that is
        # an upstream bug, not a runtime edge case, so we surface it as a
        # RuntimeError rather than silently falling back to a non-physical
        # default.
        cell_parts = [float(x) for x in str(qm_cell_abc).split()]
        if len(cell_parts) < 3:
            raise RuntimeError(
                f"Internal error: qm_cell_abc must carry three floats, got {qm_cell_abc!r}. "
                "compute_qm_cell() contract violated — refusing to emit a hybrid "
                "QM/MM input with an unverifiable HF CUTOFF_RADIUS."
            )
        half_min_hf = 0.5 * min(cell_parts)
        # 1.0 Å margin below L/2 to avoid HF exchange self-interaction; drop
        # to 0.5 Å only if the QM cell is too tight for the 1.0 Å margin,
        # subject to the absolute floor hf_cutoff_min derived from physics:
        # the HFX kernel loses meaning below ~2 Å because it no longer
        # couples any bonded electron-pair density on an organic fragment
        # (Stephens 1994 §III; Guidon 2009 Fig. 2).  When the QM cell is
        # so small that even the 2 Å floor is unreachable we refuse rather
        # than silently emit a physically meaningless input.
        hf_cutoff_min = 2.0
        hf_cutoff = max(hf_cutoff_min, half_min_hf - 1.0)
        if hf_cutoff >= half_min_hf:
            hf_cutoff = max(hf_cutoff_min, half_min_hf - 0.5)
        if hf_cutoff >= half_min_hf or half_min_hf <= hf_cutoff_min:
            raise RuntimeError(
                f"Periodic hybrid QM/MM requires half(min QM cell edge) > {hf_cutoff_min} Å "
                f"for a meaningful TRUNCATED HFX cutoff, but half(min edge) = "
                f"{half_min_hf:.2f} Å from QM cell {qm_cell_abc!r}. "
                "Enlarge the QM cell via --qm-cell-padding, switch to a non-hybrid "
                "functional (PBE), or expand the QM region so the bounding box "
                "leaves sufficient HFX headroom. "
                "See Guidon, Hutter, VandeVondele, JCTC 5, 3010 (2009)."
            )

        out.append("      &HF\n")
        if functional_upper == 'B3LYP':
            out.append("        FRACTION 0.20\n")
        elif functional_upper == 'PBE0':
            out.append("        FRACTION 0.25\n")
        out.append("        &SCREENING\n")
        out.append("          EPS_SCHWARZ 1.0E-6\n")
        # Force screening must be at least as tight as energy screening
        # to prevent shell pairs that contribute to the energy from being
        # silently dropped in the force evaluation, degrading energy
        # conservation in Born-Oppenheimer MD.
        # Ref: Guidon et al. JCTC 5, 3010 (2009) — force-consistent HFX.
        out.append("          EPS_SCHWARZ_FORCES 1.0E-6\n")
        out.append("          SCREEN_ON_INITIAL_P T\n")
        out.append("        &END SCREENING\n")
        out.append("        &MEMORY\n")
        out.append("          ! MAX_MEMORY is a per-MPI-rank HFX memory cap, not a whole-job limit.\n")
        out.append("          ! Conservative default stays explicit because launch-time MPI ranks may change outside the generator.\n")
        out.append(f"          MAX_MEMORY {d['hf_max_memory']}\n")
        out.append("          EPS_STORAGE_SCALING 1.0E-2\n")
        out.append("        &END MEMORY\n")
        out.append("        &INTERACTION_POTENTIAL\n")
        out.append("          POTENTIAL_TYPE TRUNCATED\n")
        out.append(f"          CUTOFF_RADIUS [angstrom] {hf_cutoff:.3f}\n")
        out.append("          T_C_G_DATA t_c_g.dat\n")
        out.append("        &END INTERACTION_POTENTIAL\n")
        out.append("      &END HF\n\n")

    # D.1.a/D.1.b: &VDW_POTENTIAL emission is gated by (a) whether the
    # functional has parameters for the selected dispersion scheme, and
    # (b) which scheme the operator chose.  Both decisions are recorded in
    # run_provenance at config construction; this emitter is a pure
    # consumer of the resolved flags.
    _dispersion_scheme = str(d.get('dispersion_scheme') or 'DFTD3_BJ').upper()
    _emit_vdw = d.get('emit_dftd3_vdw', True) and _dispersion_scheme != 'NONE'
    if _emit_vdw:
        out.append("      &VDW_POTENTIAL\n")
        out.append("        POTENTIAL_TYPE PAIR_POTENTIAL\n")
        out.append("        &PAIR_POTENTIAL\n")
        if _dispersion_scheme == 'DFTD4':
            # DFTD4: Caldeweyher et al., JCP 150, 154122 (2019); available
            # from CP2K 8.1.  CP2K reads the s-dftd4 parameter set directly
            # (no PARAMETER_FILE_NAME needed) — keyword documented in
            # CP2K Manual §FORCE_EVAL/DFT/XC/VDW_POTENTIAL/PAIR_POTENTIAL.
            out.append("          TYPE DFTD4\n")
            out.append(f"          REFERENCE_FUNCTIONAL {functional_upper}\n")
        else:
            # DFTD3(BJ): Grimme et al., JCP 132, 154104 (2010) +
            # Becke–Johnson damping, Grimme et al., JCC 32, 1456 (2011).
            # Universal CP2K support; parameter table in data/dftd3.dat.
            out.append("          TYPE DFTD3(BJ)\n")
            out.append("          PARAMETER_FILE_NAME dftd3.dat\n")
            out.append(f"          REFERENCE_FUNCTIONAL {functional_upper}\n")
        out.append("        &END PAIR_POTENTIAL\n")
        out.append("      &END VDW_POTENTIAL\n")
    else:
        out.append(
            f"      ! VDW_POTENTIAL omitted: dispersion_scheme={_dispersion_scheme}, "
            f"emit_dftd3_vdw={bool(d.get('emit_dftd3_vdw', True))}, "
            f"functional={functional_upper} (see run audit).\n"
        )
    out.append("    &END XC\n\n")

    if d['use_admm']:
        out.append("    &AUXILIARY_DENSITY_MATRIX_METHOD\n")
        out.append("      METHOD BASIS_PROJECTION\n")
        if d['admm_exch_correction_func']:
            out.append(f"      EXCH_CORRECTION_FUNC {d['admm_exch_correction_func']}\n")
        # ── ADMM purification method ──────────────────────────────────────
        # MO_DIAG (default, recommended for MD) enforces idempotency of the
        # auxiliary density matrix via Cauchy-representation diagonalization
        # and yields more accurate HFX with compact auxiliary bases.
        # However, CP2K requires OT when MO_DIAG or MO_NO_DIAG is selected
        # (cp_control_utils.F:375; Guidon et al., JCTC 6, 2348, 2010).
        #
        # When the SCF engine is diagonalization (open-shell, TM, or large
        # QM regions), the only developer-endorsed purification is NONE
        # (ADMM2 of Guidon et al., 2010).  Forces and stress tensors remain
        # available.  The loss of purification is partially compensated by
        # using a higher-quality auxiliary basis (cpFIT3 > cFIT3).
        # Ref: CP2K-user mailing list 2015-03, M. Watkins:
        #   "use purification_method none … with non OT methods"
        # Ref: Merlot et al., J. Chem. Phys. 141, 094104, 2014.
        # D.2.a: honour an ADVANCED-mode override when the operator has
        # explicitly selected one; otherwise keep the engine-matched
        # default (MO_DIAG for OT, NONE for DIAG).  MO_DIAG under DIAG SCF
        # is still refused — CP2K enforces OT-only for MO-based
        # purification and silent emission would cause a hard CP2K parse
        # error downstream, so we trap that combination here.
        _admm_override = d.get('admm_purification_override')
        if _admm_override == 'MO_DIAG' and use_diag_scf:
            out.append("      ! DIAG SCF: MO_DIAG override rejected (CP2K requires OT); using NONE.\n")
            out.append("      ADMM_PURIFICATION_METHOD NONE\n")
        elif _admm_override is not None:
            out.append(
                f"      ! ADMM_PURIFICATION_METHOD override: {_admm_override} "
                "(ADVANCED SCF profile; see run audit).\n"
            )
            out.append("      ! Refs: Guidon et al. JCTC 6, 2348 (2010); "
                       "Merlot et al. JCP 141, 094104 (2014).\n")
            out.append(f"      ADMM_PURIFICATION_METHOD {_admm_override}\n")
        elif use_diag_scf:
            out.append("      ! DIAG SCF: MO-based purification (MO_DIAG) requires OT.\n")
            out.append("      ! Falling back to NONE (= ADMM2, Guidon et al. JCTC 2010).\n")
            out.append("      ADMM_PURIFICATION_METHOD NONE\n")
        else:
            out.append("      ! OT SCF: MO_DIAG enforces auxiliary density idempotency\n")
            out.append("      ! via Cauchy diagonalization — recommended for BOMD.\n")
            out.append("      ! Ref: Guidon et al., J. Chem. Theory Comput. 6, 2348 (2010).\n")
            out.append("      ADMM_PURIFICATION_METHOD MO_DIAG\n")
        out.append("    &END AUXILIARY_DENSITY_MATRIX_METHOD\n")

    out.append("  &END DFT\n\n")

    # Parse MM box edges from the already-validated cell_abc string so the
    # SPME α/GMAX accuracy diagnostic can be emitted in the &POISSON block.
    # The string format is 3 floats separated by spaces, produced by
    # _resolve_box_params() — failure here would be an upstream regression.
    try:
        _mm_box_edges = tuple(float(x) for x in str(cell_abc).split()[:3])
    except (TypeError, ValueError):
        _mm_box_edges = None
    _emit_mm_section(
        out,
        qmmm_topology.prmtop_file,
        ff_info_filename,
        gmax_a,
        gmax_b,
        gmax_c,
        s.mm_scale14_policy,
        box_edges=_mm_box_edges,
    )

    # &QMMM
    out.append("  &QMMM\n")
    out.append("    ECOUPL GAUSS\n")
    out.append(f"    USE_GEEP_LIB {d['qmmm_geep_lib']}\n")
    out.append("    &CELL\n")
    out.append(f"      ABC [angstrom] {qm_cell_abc}\n")
    out.append("      PERIODIC XYZ\n")
    out.append("    &END CELL\n")
    out.append("    &PERIODIC\n")
    out.append("      &MULTIPOLE\n")
    out.append(
        "        ! ── &PERIODIC/&MULTIPOLE/RCUT: periodic QM/MM electrostatics (V5 provenance)\n"
    )
    out.append(
        "        ! Real-space cutoff of the periodic multipole expansion used to couple the\n"
    )
    out.append(
        "        ! QM charge density to the infinite periodic MM image lattice.  Each MM image\n"
    )
    out.append(
        "        ! within |r - r_QM| <= RCUT contributes explicitly; the long-range tail is\n"
    )
    out.append(
        "        ! resummed via the multipole moments of the QM density (monopole/dipole/\n"
    )
    out.append(
        "        ! quadrupole) under an Ewald-style split governed by EWALD_PRECISION below.\n"
    )
    out.append(
        "        ! Refs: Laino, Mohamed, Curioni, VandeVondele, JCTC 2, 1370 (2006) — GEEP\n"
    )
    out.append(
        "        !       periodic QM/MM multipole decomposition, §2–3 (RCUT role and error\n"
    )
    out.append(
        "        !       scaling); CP2K manual, FORCE_EVAL/QMMM/PERIODIC/MULTIPOLE/RCUT\n"
    )
    out.append(
        "        !       (subkey stable since CP2K 6.1, see release notes).\n"
    )
    out.append(
        "        ! Constraint: RCUT must be <= half the shortest QM cell edge minus a small\n"
    )
    out.append(
        "        ! margin, otherwise an atom's own periodic image would fall inside the cutoff\n"
    )
    out.append(
        "        ! sphere and the multipole sum would double-count.  The generator therefore\n"
    )
    out.append(
        "        ! links QM-cell padding and target RCUT via make_qmmm_periodic_policy().\n"
    )
    out.append(
        f"        ! Target RCUT {qmmm_periodic['target_rcut']:.1f} A with requested half-cell buffer "
        f"{qmmm_periodic['requested_buffer']:.1f} A.\n"
    )
    if qmmm_periodic['rcut_relaxed']:
        out.append(
            f"        ! WARNING: QM cell limits RCUT to {qmmm_periodic['effective_rcut']:.1f} A; "
            "enlarge the QM cell/padding if longer-range multipole accuracy is required.\n"
        )
    if qmmm_periodic['buffer_relaxed']:
        out.append(
            "        ! WARNING: The requested half-cell safety buffer does not fit inside this QM cell; "
            "the generator fell back to the largest strictly valid RCUT below half the QM cell.\n"
        )
    out.append(f"        RCUT [angstrom] {qmmm_periodic['effective_rcut']:.1f}\n")
    out.append("        EWALD_PRECISION 1.0E-6\n")
    out.append("      &END MULTIPOLE\n")
    out.append("    &END PERIODIC\n")

    for elem, indices in sorted(s.qm_elements.items()):
        out.append(f"    &QM_KIND {elem}\n")
        for i in range(0, len(indices), 10):
            chunk = " ".join(indices[i:i+10])
            out.append(f"      MM_INDEX {chunk}\n")
        out.append(f"    &END QM_KIND\n")

    # ── &MM_KIND blocks: explicit GEEP Gaussian-embedding radii ───────────
    # CP2K's ECOUPL GAUSS replaces each MM point charge with a Gaussian of
    # width taken from &MM_KIND/RADIUS.  Without explicit radii, a single
    # default (~0.8 Å) is applied to every element, which is acceptable for
    # a narrow C/N/O set but over-smooths heavy halogens/ions and
    # under-smooths hydrogen (Laino, Mohamed, Curioni, VandeVondele, JCTC 2,
    # 1370 (2006), §2–3).  We emit one &MM_KIND per distinct MM element
    # that is *not* already a QM_KIND (CP2K rejects duplicate declarations).
    # Unlisted elements are capped at MM_KIND_RADIUS_FALLBACK so the
    # emission remains complete and the user is notified via a pipeline
    # warning handled upstream of this emitter.
    mm_element_symbols = extract_mm_element_symbols(s.qmmm_topology.mm_kinds_lines)
    qm_element_symbols = {str(e).upper() for e in s.qm_elements.keys()}
    # Hydrogen link-capping atoms are declared as QM_KIND H above; exclude H
    # from the MM_KIND set to avoid CP2K's duplicate-declaration rejection.
    mm_only_symbols = sorted(mm_element_symbols - qm_element_symbols)
    if mm_only_symbols:
        out.append("    ! --- MM_KIND Gaussian-embedding radii -------------\n")
        out.append("    ! Per-element RADIUS for GEEP (Laino et al. JCTC 2, 1370, 2006, Tbl I).\n")
        out.append("    ! Unlisted elements use the pipeline fallback (0.80 A, CP2K default).\n")
        for elem in mm_only_symbols:
            radius = MM_KIND_GEEP_RADII.get(elem, MM_KIND_RADIUS_FALLBACK)
            out.append(f"    &MM_KIND {elem}\n")
            out.append(f"      RADIUS [angstrom] {radius:.3f}\n")
            out.append(f"    &END MM_KIND\n")

    for link in s.link_bonds:
        out.append("    &LINK\n")
        out.append("      QM_KIND H\n")
        out.append(f"      QM_INDEX {link['QM_INDEX']}\n")
        out.append(f"      MM_INDEX {link['MM_INDEX']}\n")
        out.append("      LINK_TYPE IMOMM\n")
        out.append(f"      ALPHA_IMOMM {float(link.get('ALPHA_IMOMM', DEFAULT_ALPHA_IMOMM)):.3f}\n")
        charge_lines = generate_link_charge_directives(link, d['boundary_charge_scheme'])
        for cl in charge_lines:
            out.append(f"      {cl}")
        out.append("    &END LINK\n")

    # ── Optional QM/MM verbose diagnostics (S9) ──────────────────────────
    # When enabled (typically only for the 35_qmmm_warmup diagnostic stage),
    # request high-verbosity QM/MM reports so the user can verify the
    # effective multipole RCUT, the GEEP grid depth actually applied, and
    # the mapping between QM/MM Kinds and the Gaussian embedding charges
    # without re-parsing the emitted input.  Left off for production
    # stages to keep the log volume manageable.
    # Ref: CP2K manual §FORCE_EVAL/QMMM/PRINT/PROGRAM_RUN_INFO,
    #      §FORCE_EVAL/QMMM/PRINT/GRID_INFORMATION.
    if getattr(run_config, 'qmmm_verbose_diagnostics', False):
        out.append("    &PRINT\n")
        out.append("      ! Verbose QM/MM diagnostics requested via --qmmm-verbose-diagnostics.\n")
        out.append("      ! Intended for first-run verification of GEEP grid depth and\n")
        out.append("      ! effective multipole RCUT; disable for long production runs.\n")
        out.append("      &PROGRAM_RUN_INFO ON\n")
        out.append("        &EACH\n")
        out.append("          QS_SCF 0\n")
        out.append("          MD 1\n")
        out.append("        &END EACH\n")
        out.append("      &END PROGRAM_RUN_INFO\n")
        out.append("      &GRID_INFORMATION ON\n")
        out.append("      &END GRID_INFORMATION\n")
        out.append("    &END PRINT\n")
    out.append("  &END QMMM\n\n")

    qm_preamble = [
        "    ! ======================================\n",
        "    ! QM ELEMENT BASIS AND POTENTIAL MAPPING\n",
        "    ! ======================================\n",
        f"    ! QM basis set selection: {basis_set}\n",
        f"    ! MGRID NGRIDS: {d['mgrid_ngrids']}\n",
    ]
    if d['use_admm'] and d['admm_aux_basis']:
        qm_preamble.append(f"    ! ADMM auxiliary basis: {d['admm_aux_basis']}\n")
    if d['use_admm'] and d['admm_exch_correction_func']:
        qm_preamble.append(f"    ! ADMM exchange correction: {d['admm_exch_correction_func']}\n")
    _emit_subsys(out, cell_abc, cell_angles, qmmm_topology.prmtop_file, s.xyz_file,
                 qmmm_topology.mm_kinds_lines, qm_kinds_preamble=qm_preamble,
                 qm_kinds_lines=s.qm_kinds_lines,
                 sampling_config=r['sampling_config'])

    if run_type == 'MD':
        out.append("&MOTION\n")
        _append_fixed_atoms_constraint_lines(
            out,
            r['fixed_atom_indices'],
            indent="  ",
            sampling_config=r['sampling_config'],
        )
        _emit_md_block(out, md_ensemble, r['md_steps'], r['md_timestep'],
                       r['md_temperature'], md_energy_each,
                       md_dynamics_config=r['md_dynamics_config'])
        _emit_sampling_free_energy_lines(out, r['sampling_config'], indent="  ")
        _emit_md_motion_print(out, r['trajectory_format'])
        out.append("&END MOTION\n")
    elif run_type == 'GEO_OPT':
        out.append("&MOTION\n")
        _append_fixed_atoms_constraint_lines(out, r['fixed_atom_indices'], indent="  ")
        # Use the RunConfig-specified MAX_ITER, matching the MM-only assembler.
        # The default (200) is set in make_run_config(); callers can override
        # via geo_opt_max_iter=N.
        # Ref: CP2K Manual §MOTION/GEO_OPT — MAX_ITER controls the maximum
        # number of geometry optimization steps before convergence is abandoned.
        _emit_geo_opt_block(out, max_iter=r['geo_opt_max_iter'],
                            pre_relaxation=r['pre_relaxation'])
        out.append("&END MOTION\n")

    return ''.join(out)


def assemble_mm_only_input(system_model, run_config):
    """Assemble MM-only CP2K input from validated SystemModel and RunConfig."""
    if not isinstance(system_model, SystemModel):
        raise TypeError("assemble_mm_only_input() requires a SystemModel instance.")
    if not isinstance(run_config, RunConfig):
        raise TypeError("assemble_mm_only_input() requires a RunConfig instance.")
    validate_sampling_config_indices(run_config.sampling_config, system_model.natom)
    s = system_model
    r = run_config._asdict()
    run_type = validate_run_type(r['run_type'])
    if r['sampling_config'] and run_type != 'MD':
        raise ValueError("Advanced free-energy sampling is only supported for RUN_TYPE MD.")
    if run_type not in ('MD', 'GEO_OPT'):
        raise ValueError("MM-only staged inputs support run_type MD or GEO_OPT only.")
    trajectory_format = normalize_trajectory_format(r['trajectory_format'])
    md_ensemble = str(r['md_ensemble']).upper()
    mm_topology = s.mm_topology

    out = []
    _emit_global(out, r['project_name'], run_type, global_seed=r['md_dynamics_config'].global_seed)
    _append_ext_restart_lines(out, r['ext_restart_cfg'])

    out.append("&FORCE_EVAL\n")
    out.append("  METHOD FIST\n\n")
    if run_type == 'MD' and _md_ensemble_requires_stress_tensor(md_ensemble):
        out.append("  STRESS_TENSOR ANALYTICAL\n\n")

    # MM-only assembler: same SPME-diagnostic plumbing as the QM/MM path.
    try:
        _mm_only_box_edges = tuple(float(x) for x in str(s.cell_abc).split()[:3])
    except (TypeError, ValueError):
        _mm_only_box_edges = None
    _emit_mm_section(
        out,
        mm_topology.prmtop_file,
        r['ff_info_filename'],
        s.gmax_a,
        s.gmax_b,
        s.gmax_c,
        s.mm_scale14_policy,
        box_edges=_mm_only_box_edges,
    )
    _emit_subsys(
        out,
        s.cell_abc,
        s.cell_angles,
        mm_topology.prmtop_file,
        s.xyz_file,
        mm_topology.mm_kinds_lines,
        sampling_config=r['sampling_config'],
    )

    out.append("&MOTION\n")
    _append_fixed_atoms_constraint_lines(
        out,
        r['fixed_atom_indices'],
        indent="  ",
        sampling_config=r['sampling_config'],
    )
    if run_type == 'GEO_OPT':
        _emit_geo_opt_block(out, max_iter=r['geo_opt_max_iter'],
                            pre_relaxation=r['pre_relaxation'])
        _emit_geo_opt_motion_print(out, trajectory_format)
    else:
        _emit_md_block(out, md_ensemble, max(1, r['md_steps']), r['md_timestep'],
                       r['md_temperature'], md_energy_each=10,
                       md_dynamics_config=r['md_dynamics_config'])
        _emit_sampling_free_energy_lines(out, r['sampling_config'], indent="  ")
        _emit_md_motion_print(out, trajectory_format)
    out.append("&END MOTION\n")

    return ''.join(out)


def assemble_staged_cp2k_workflow(system_model, dft_config, workflow_config):
    """Build deterministic staged CP2K workflow inputs from validated config objects."""
    if not isinstance(system_model, SystemModel):
        raise TypeError("assemble_staged_cp2k_workflow() requires a SystemModel instance.")
    if not isinstance(dft_config, DFTConfig):
        raise TypeError("assemble_staged_cp2k_workflow() requires a DFTConfig instance.")
    if not isinstance(workflow_config, WorkflowConfig):
        raise TypeError("assemble_staged_cp2k_workflow() requires a WorkflowConfig instance.")
    validate_sampling_config_indices(workflow_config.sampling_config, system_model.natom)
    stage_inputs = OrderedDict()
    dependencies = []
    restrained = list(workflow_config.restraint_indices)
    stateful_restart = not bool(workflow_config.stateless_restart)
    qmmm_handoff_policy = workflow_config.qmmm_handoff_policy
    first_qmmm_stage_dynamics = make_first_qmmm_stage_dynamics(
        qmmm_handoff_policy,
        transition_thermostat_timecon_fs=workflow_config.qmmm_transition_thermostat_timecon_fs,
        transition_seed=workflow_config.qmmm_transition_seed,
    )
    md_state_flags = {
        'restart_counters': stateful_restart,
        'restart_thermostat': stateful_restart,
        'restart_barostat': stateful_restart,
        'restart_randomg': stateful_restart,
    }
    non_md_state_flags = {
        'restart_counters': False,
        'restart_thermostat': False,
        'restart_barostat': False,
        'restart_randomg': False,
    }

    # Stage 10: MM pre-relaxation energy minimization.
    # Purpose: remove bad contacts and steric clashes from the solvated box
    # before MD equilibration.  Marked as pre_relaxation=True so that:
    #   (a) the CP2K input receives relaxed convergence thresholds (~5x
    #       defaults) appropriate for large solvent-dominated systems, and
    #   (b) the wrapper gate accepts normal termination at MAX_ITER without
    #       requiring strict GEO_OPT convergence — downstream MD stages
    #       (NVT, NPT) provide the real structural equilibration.
    # Ref: CP2K QM/MM Tutorial (chorismate mutase): "1000 steps of energy
    #      minimization ... to eliminate bad contacts" before MD.
    stage_inputs[f'{STAGE_EM_MM.project_name}.inp'] = assemble_mm_only_input(
        system_model,
        make_run_config(
            project_name=STAGE_EM_MM.project_name,
            run_type='GEO_OPT',
            geo_opt_max_iter=workflow_config.em_max_iter,
            trajectory_format=workflow_config.trajectory_format,
            pre_relaxation=True,
        ),
    )
    dependencies.append({
        'stage': f'{STAGE_EM_MM.project_name}.inp',
        'restart_from': None,
        'restart_pos': False,
        'restart_vel': False,
        'restart_cell': False,
        'pre_relaxation': True,
    })

    stage_inputs[f'{STAGE_NVT_MM.project_name}.inp'] = assemble_mm_only_input(
        system_model,
        make_run_config(
            project_name=STAGE_NVT_MM.project_name,
            run_type='MD',
            preset='custom',
            md_steps=workflow_config.mm_nvt_steps,
            md_timestep=workflow_config.mm_timestep,
            md_temperature=workflow_config.production_temperature,
            md_ensemble='NVT',
            ext_restart_cfg=make_ext_restart_config(
                restart_file_name=STAGE_EM_MM.ext_restart,
                restart_pos=True,
                restart_vel=False,
                restart_cell=True,
                **non_md_state_flags,
            ),
            fixed_atom_indices=(restrained if workflow_config.mm_equil_restraints else None),
            trajectory_format=workflow_config.trajectory_format,
        ),
    )
    dependencies.append({
        'stage': f'{STAGE_NVT_MM.project_name}.inp',
        'restart_from': STAGE_EM_MM.ext_restart,
        'restart_pos': True,
        'restart_vel': False,
        'restart_cell': True,
        **non_md_state_flags,
    })

    stage_inputs[f'{STAGE_NPT_MM.project_name}.inp'] = assemble_mm_only_input(
        system_model,
        make_run_config(
            project_name=STAGE_NPT_MM.project_name,
            run_type='MD',
            preset='custom',
            md_steps=workflow_config.mm_npt_steps,
            md_timestep=workflow_config.mm_timestep,
            md_temperature=workflow_config.production_temperature,
            md_ensemble='NPT_I',
            ext_restart_cfg=make_ext_restart_config(
                restart_file_name=STAGE_NVT_MM.ext_restart,
                restart_pos=True,
                restart_vel=True,
                restart_cell=True,
                **md_state_flags,
            ),
            fixed_atom_indices=(restrained if workflow_config.mm_equil_restraints else None),
            trajectory_format=workflow_config.trajectory_format,
        ),
    )
    dependencies.append({
        'stage': f'{STAGE_NPT_MM.project_name}.inp',
        'restart_from': STAGE_NVT_MM.ext_restart,
        'restart_pos': True,
        'restart_vel': True,
        'restart_cell': True,
        **md_state_flags,
    })

    if workflow_config.enable_qmmm_warmup:
        stage_inputs[f'{STAGE_QMMM_WARMUP.project_name}.inp'] = assemble_cp2k_input(
            system_model,
            dft_config,
            make_run_config(
                project_name=STAGE_QMMM_WARMUP.project_name,
                run_type='MD',
                preset='custom',
                md_steps=workflow_config.warmup_steps,
                md_timestep=workflow_config.warmup_timestep,
                md_temperature=workflow_config.production_temperature,
                # NVT default: re-equilibrate at fixed volume after the MM→QM/MM
                # Hamiltonian switch before reintroducing pressure coupling.
                # Ref: Senn & Thiel, Angew. Chem. Int. Ed. 48, 1198 (2009).
                md_ensemble=workflow_config.warmup_ensemble,
                ext_restart_cfg=qmmm_handoff_ext_restart_config(
                    restart_file_name=STAGE_NPT_MM.ext_restart,
                    qmmm_handoff_policy=qmmm_handoff_policy,
                ),
                fixed_atom_indices=(restrained if workflow_config.warmup_restraints else None),
                md_dynamics_config=first_qmmm_stage_dynamics,
                trajectory_format=workflow_config.trajectory_format,
                # S9: opt-in verbose &QMMM/&PRINT diagnostics attach only
                # here — production stages (40_qmmm_md) stay at the default
                # False so long trajectories do not explode the log size.
                qmmm_verbose_diagnostics=bool(
                    getattr(workflow_config, 'qmmm_verbose_diagnostics', False)
                ),
            ),
        )
        dependencies.append({
            'stage': f'{STAGE_QMMM_WARMUP.project_name}.inp',
            'restart_from': STAGE_NPT_MM.ext_restart,
            'restart_pos': True,
            'restart_vel': bool(qmmm_handoff_policy.restart_velocities),
            'restart_cell': True,
            'restart_counters': bool(qmmm_handoff_policy.restart_counters),
            'restart_thermostat': bool(qmmm_handoff_policy.restart_thermostat),
            'restart_barostat': bool(qmmm_handoff_policy.restart_barostat),
            'restart_randomg': bool(qmmm_handoff_policy.restart_randomg),
            'wfn_restart_from': None,
            'transition_initialization_method': first_qmmm_stage_dynamics.initialization_method,
            'transition_global_seed': first_qmmm_stage_dynamics.global_seed,
            'transition_thermostat_timecon_fs': first_qmmm_stage_dynamics.thermostat_timecon_fs,
        })
        prod_restart = STAGE_QMMM_WARMUP.ext_restart
        prod_restart_vel = True
        prod_wfn_restart = STAGE_QMMM_WARMUP.wfn_restart
    else:
        prod_restart = STAGE_NPT_MM.ext_restart
        prod_restart_vel = bool(qmmm_handoff_policy.restart_velocities)
        prod_wfn_restart = None

    stage_inputs[f'{STAGE_QMMM_MD.project_name}.inp'] = assemble_cp2k_input(
        system_model,
        dft_config,
        make_run_config(
            project_name=STAGE_QMMM_MD.project_name,
            run_type='MD',
            preset='custom',
            md_steps=workflow_config.production_steps,
            md_timestep=workflow_config.production_timestep,
            md_temperature=workflow_config.production_temperature,
            md_ensemble=workflow_config.production_ensemble,
            ext_restart_cfg=(
                make_ext_restart_config(
                    restart_file_name=prod_restart,
                    restart_pos=True,
                    restart_vel=prod_restart_vel,
                    restart_cell=True,
                    **md_state_flags,
                )
                if workflow_config.enable_qmmm_warmup
                else qmmm_handoff_ext_restart_config(
                    restart_file_name=prod_restart,
                    qmmm_handoff_policy=qmmm_handoff_policy,
                )
            ),
            wfn_restart_file=prod_wfn_restart,
            md_dynamics_config=(
                make_md_dynamics_config()
                if workflow_config.enable_qmmm_warmup
                else first_qmmm_stage_dynamics
            ),
            trajectory_format=workflow_config.trajectory_format,
            sampling_config=workflow_config.sampling_config,
        ),
    )
    dependencies.append({
        'stage': f'{STAGE_QMMM_MD.project_name}.inp',
        'restart_from': prod_restart,
        'restart_pos': True,
        'restart_vel': bool(prod_restart_vel),
        'restart_cell': True,
        **(
            md_state_flags
            if workflow_config.enable_qmmm_warmup
            else {
                'restart_counters': bool(qmmm_handoff_policy.restart_counters),
                'restart_thermostat': bool(qmmm_handoff_policy.restart_thermostat),
                'restart_barostat': bool(qmmm_handoff_policy.restart_barostat),
                'restart_randomg': bool(qmmm_handoff_policy.restart_randomg),
            }
        ),
        'wfn_restart_from': prod_wfn_restart,
        'transition_initialization_method': (
            None
            if workflow_config.enable_qmmm_warmup
            else first_qmmm_stage_dynamics.initialization_method
        ),
        'transition_global_seed': (
            None
            if workflow_config.enable_qmmm_warmup
            else first_qmmm_stage_dynamics.global_seed
        ),
        'transition_thermostat_timecon_fs': (
            None
            if workflow_config.enable_qmmm_warmup
            else first_qmmm_stage_dynamics.thermostat_timecon_fs
        ),
    })

    meta = {
        'stage_order': list(stage_inputs.keys()),
        'dependencies': dependencies,
        'mm_prmtop_file': system_model.mm_topology.prmtop_file,
        'qmmm_prmtop_file': system_model.qmmm_topology.prmtop_file,
        'split_stage_topologies': bool(
            system_model.mm_topology.prmtop_file != system_model.qmmm_topology.prmtop_file
            or system_model.mm_topology.mm_kinds_lines != system_model.qmmm_topology.mm_kinds_lines
        ),
        'warmup_enabled': bool(workflow_config.enable_qmmm_warmup),
        'handoff_restart_velocities': bool(qmmm_handoff_policy.restart_velocities),
        'qmmm_handoff_policy_mode': qmmm_handoff_policy.mode,
        'qmmm_handoff_policy_label': qmmm_handoff_policy.label,
        'qmmm_handoff_policy_reason': qmmm_handoff_policy.reason,
        'qmmm_transition_initialization_method': first_qmmm_stage_dynamics.initialization_method,
        'qmmm_transition_global_seed': first_qmmm_stage_dynamics.global_seed,
        'qmmm_transition_thermostat_timecon_fs': first_qmmm_stage_dynamics.thermostat_timecon_fs,
        'qmmm_transition_label': first_qmmm_stage_dynamics.label,
        'qmmm_transition_reason': first_qmmm_stage_dynamics.reason,
        'mm_equil_restraints': bool(workflow_config.mm_equil_restraints),
        'warmup_restraints': bool(workflow_config.warmup_restraints),
        'stateless_restart': bool(workflow_config.stateless_restart),
        'restraint_atom_count': len(restrained),
        'sampling_method': (workflow_config.sampling_config.method if workflow_config.sampling_config else None),
    }
    return stage_inputs, meta


# ─── File Detection ──────────────────────────────────────────────────────────

def _score_mdin_candidate(mdin_path):
    """Prefer MDIN files that actually define a QM/MM region."""
    bname = os.path.basename(str(mdin_path)).lower()
    try:
        with open(mdin_path, 'r', errors='ignore') as f:
            preview = f.read(262144).lower()
    except OSError:
        preview = ''

    has_qmmm = '&qmmm' in preview
    has_qm_selection = 'iqmatoms' in preview or 'qmmask' in preview
    return (
        1 if has_qm_selection else 0,
        1 if has_qmmm else 0,
        1 if 'step5' in bname else 0,
        1 if 'production' in bname else 0,
        1 if 'qmmm' in bname else 0,
    )


def detect_files(directory):
    """Auto-detect CHARMM-GUI QM/MM Interfacer output files."""
    patterns = {
        'prmtop': ['*.parm7', '*.prmtop', '*.top'],
        'rst7':   ['*.rst7', '*.inpcrd', '*.crd'],
        'pdb':    ['*.pdb'],
        'psf':    ['*.psf'],
        'mdin':   ['*.mdin'],
        'sysinfo': ['sysinfo.dat'],
        'dihe':   ['dihe.restraint'],
    }
    found = {}
    for key, globs in patterns.items():
        matches = []
        for g in globs:
            matches.extend(glob.glob(os.path.join(directory, g)))
        if key == 'mdin':
            ranked_mdin = sorted(sorted(set(matches)), key=_score_mdin_candidate, reverse=True)
            if ranked_mdin:
                found['mdin_candidates'] = ranked_mdin
                found['mdin'] = ranked_mdin[0]
            continue
        # Prefer step3_input.* files
        best = None
        for m in matches:
            bname = os.path.basename(m)
            if 'step3_input' in bname or 'step5_production' in bname:
                best = m
                break
        if best is None and matches:
            best = matches[0]
        if best:
            found[key] = best
    return found


# ─── Textual TUI Layer ──────────────────────────────────────────────────────
#
# Everything below this marker through the closing ``# ─── End Textual TUI``
# is guarded by ``if HAS_TEXTUAL:`` and is never evaluated on Python < 3.9
# or when the `textual` package is absent.  The plain CLI wizard
# (``_main_cli_wizard()`` / ``main()``) remains the fallback.
#
# Architecture:
#   WizardState      — mutable dataclass accumulating all parameters.
#   _step_*()        — pure-logic step-functions callable from any frontend.
#   Screens          — one per workflow phase; screens read/write WizardState.
#   CharmmGui2Cp2kApp — App subclass dispatching between screens.
#
# Design principles:
#   • Keyboard-first: Tab/Enter/Escape/F1 navigate without a mouse.
#   • Restrained styling: operator console, not cyberpunk.
#   • Every scientifically meaningful default is *shown* and *confirmable*,
#     never silently applied.
#   • Workers wrap any blocking I/O so the event loop stays responsive.
#   • Non-interactive (--non-interactive) never enters the TUI path.
# ─────────────────────────────────────────────────────────────────────────────

if HAS_TEXTUAL:
    # ═════════════════════════════════════════════════════════════════════
    #  CHARMM-GUI → CP2K  ·  Textual "Workbench" TUI (v2)
    # ═════════════════════════════════════════════════════════════════════
    #
    #  Design intent
    #  ─────────────
    #  This block is the presentation layer only.  The scientific core
    #  (parsers, system builders, input writers, SCF profile logic, link
    #  atom construction, GEEP embedding, …) lives outside this block and
    #  is invoked through the same function signatures the CLI path uses
    #  in main().  The TUI therefore emits bit-identical artifacts to the
    #  batch path — it differs only in affordance and information density,
    #  never in numerical behavior.
    #
    #  Layout
    #  ──────
    #  A single WorkbenchScreen hosts a persistent frame:
    #
    #      ┌──────────────── TopBar ────────────────────────────────┐
    #      │ charmmgui2cp2k · <work_dir>            cp2k vX.Y.Z      │
    #      ├───── PhaseBreadcrumb ──────────────────────────────────┤
    #      │  ● System ▸ ◎ QM ▸ ○ Boundary ▸ ○ Method ▸ …          │
    #      ├───────────┬────────────────────────────────────────────┤
    #      │ System    │                                             │
    #      │ Summary   │         ContentSwitcher(phase host)         │
    #      │ (sticky)  │                                             │
    #      │           │                                             │
    #      ├───────────┴────────────────────────────────────────────┤
    #      │ ValidationTray                                          │
    #      ├───────────── FooterBar (keybinds / back / next) ────────┤
    #      └─────────────────────────────────────────────────────────┘
    #
    #  Phases (live inside the ContentSwitcher, not as separate Screens):
    #    1. SystemPhase       — detect files + CP2K probe + parse topology
    #    2. QMPhase           — review QM region, augment manually
    #    3. BoundaryPhase     — QM/MM link bonds + residual-charge scheme
    #    4. MethodPhase       — functional + basis + ADMM (Basic/Expert tabs)
    #    5. ElectronicPhase   — charge + multiplicity (with parity audit)
    #    6. WorkflowPhase     — MD stages, thermostats, warmup policy
    #    7. PreviewPhase      — dense operational summary prior to write
    #    8. GeneratePhase     — execute the scientific core + live progress
    #
    #  State model
    #  ───────────
    #  The App owns a set of plain-Python attributes whose names match the
    #  original CLI wizard (e.g. `topo`, `qm_indices`, `functional`, …).
    #  Phases mutate them through commit() and then call
    #  screen.refresh_state_ui() so the sticky sidebar, breadcrumb, and
    #  validation tray re-render against the new values.  Warnings are
    #  appended to `app.validation_records` (list[tuple[str, str]]).
    #
    #  References
    #  ──────────
    #    • Textual App        — https://textual.textualize.io/guide/app/
    #    • Textual CSS        — https://textual.textualize.io/guide/CSS/
    #    • ContentSwitcher    — https://textual.textualize.io/widgets/content_switcher/
    #    • Workers            — https://textual.textualize.io/guide/workers/
    #    • Messages           — https://textual.textualize.io/guide/events/
    # ═════════════════════════════════════════════════════════════════════

    # ── CSS ──────────────────────────────────────────────────────────────
    # Restrained, high-contrast operator-console theme.  Accent is a single
    # cyan-blue; warnings use amber, errors red, success green.  No
    # gratuitous colour; layout carries most of the visual work.
    _TUI_CSS = """
    Screen {
        layers: base overlay;
        background: $surface;
    }

    /* ── Top bar (identity + CP2K probe) ──────────────────────────── */
    #topbar {
        dock: top;
        height: 1;
        background: $boost;
        color: $text;
        padding: 0 2;
    }
    #topbar-title { color: $accent; text-style: bold; }
    #topbar-dir   { color: $text-muted; }
    #topbar-cp2k  { color: $secondary; }

    /* ── Phase breadcrumb ─────────────────────────────────────────── */
    #breadcrumb {
        dock: top;
        height: 1;
        background: $panel;
        color: $text-muted;
        padding: 0 2;
    }
    .chip-done    { color: $success; text-style: bold; }
    .chip-current { color: $accent;  text-style: bold reverse; }
    .chip-pending { color: $text-muted; }
    .chip-sep     { color: $text-disabled; }

    /* ── Left sticky sidebar ──────────────────────────────────────── */
    #sidebar {
        dock: left;
        width: 34;
        background: $panel;
        padding: 1 1;
        border-right: vkey $primary-background-lighten-2;
        overflow-y: auto;
    }
    .card {
        background: $boost;
        margin-bottom: 1;
        padding: 1 1;
        border: round $primary-background-lighten-2;
    }
    .card-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 0;
    }
    .card-row {
        color: $text;
    }
    .card-row-muted {
        color: $text-muted;
    }
    .card-row-warn {
        color: $warning;
    }

    /* ── Validation tray (above footer) ───────────────────────────── */
    #tray {
        dock: bottom;
        height: auto;
        max-height: 8;
        background: $panel;
        padding: 0 2;
        border-top: hkey $primary-background-lighten-2;
    }
    #tray-header { text-style: bold; }
    #tray-list   { color: $text-muted; padding: 0 1; }
    .tray-warn  { color: $warning; }
    .tray-error { color: $error; }
    .tray-ok    { color: $success; }

    /* ── Footer (keybinds + nav) ──────────────────────────────────── */
    #footbar {
        dock: bottom;
        height: 3;
        background: $boost;
        padding: 0 1;
        border-top: hkey $primary-background-lighten-2;
    }
    #footbar Button { margin: 0 1; min-width: 14; }
    #footbar-hint {
        color: $text-muted;
        content-align: center middle;
        width: 1fr;
    }

    /* ── Phase host ──────────────────────────────────────────────── */
    #host {
        padding: 1 2;
    }
    .phase-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    .phase-subtitle {
        color: $text-muted;
        margin-bottom: 1;
    }

    /* ── Didactic note — used beside scientifically-loaded controls ─ */
    .didactic {
        background: $primary-background-lighten-1;
        border-left: thick $accent;
        padding: 0 1;
        color: $text-muted;
        margin: 0 0 1 0;
    }
    .didactic-title {
        text-style: bold;
        color: $accent;
    }

    /* ── Generic control sections ─────────────────────────────────── */
    .section {
        margin: 1 0;
    }
    .section-title {
        text-style: bold underline;
        color: $accent;
        margin-bottom: 0;
    }

    /* ── Form rows (label | control | hint) ───────────────────────── */
    .row {
        height: auto;
        margin-bottom: 1;
    }
    .row-label {
        width: 22;
        padding: 1 1 0 0;
        text-style: bold;
    }
    .row-control {
        width: 26;
    }
    .row-hint {
        color: $text-muted;
        padding: 1 1 0 1;
        width: 1fr;
    }

    /* ── Tables ───────────────────────────────────────────────────── */
    DataTable {
        height: auto;
        max-height: 16;
        margin: 0 0 1 0;
    }

    /* ── Inputs ───────────────────────────────────────────────────── */
    Input {
        margin: 0 1 0 0;
    }
    Input:focus {
        border: tall $accent;
    }
    Select {
        margin: 0 1 0 0;
    }

    /* ── Preview phase (dense) ───────────────────────────────────── */
    #preview-grid {
        grid-size: 2 2;
        grid-columns: 1fr 1fr;
        grid-rows: 1fr 1fr;
        grid-gutter: 1 2;
        height: 1fr;
    }
    .preview-quadrant {
        background: $boost;
        border: round $primary-background-lighten-2;
        padding: 1;
    }
    .preview-quadrant-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }

    /* ── Generate phase ───────────────────────────────────────────── */
    #exec-log {
        height: 1fr;
        border: round $accent;
        margin: 1 0 0 0;
    }
    ProgressBar { margin: 0 0 1 0; }

    /* ── Misc ─────────────────────────────────────────────────────── */
    .muted { color: $text-muted; }
    .ok    { color: $success; }
    .warn  { color: $warning; }
    .err   { color: $error; }
    .kbd   { color: $accent; text-style: bold; }
    Collapsible { margin: 0 0 1 0; }
    TabbedContent { margin-bottom: 1; }
    """

    # ── Pure-logic step helpers ──────────────────────────────────────────
    # Same signatures as the v1 TUI so the scientific core does not move.

    def _step1_detect(work_dir):
        """Step 1: scan directory for CHARMM-GUI outputs.  Returns a dict of detected paths."""
        return detect_files(work_dir)

    def _step2_parse_topology(prmtop_path, rst7_path):
        """Step 2: parse AMBER topology and coordinates.

        Returns (topo, coords, box, element_map, unresolved, alias_plan) — same tuple
        as the CLI main() uses downstream.  Box preference is RST7 over
        PRMTOP (the RST7 carries the current simulation cell).
        """
        topo = AmberTopology(prmtop_path)
        coords, rst7_box = read_rst7(rst7_path)
        box = rst7_box or topo.box
        alias_plan = build_atom_type_alias_plan(topo)
        element_map = _resolved_alias_element_map(alias_plan)
        unresolved = sorted(alias_plan.unresolved_aliases)
        return topo, coords, box, element_map, unresolved, alias_plan

    def _step3_extract_qm_from_mdin(
        mdin_path, topo, element_map, atom_types, prmtop_path=None, crd_path=None
    ):
        """Attempt to infer a QM region from an AMBER-style MDIN selection."""
        try:
            elems, indices, meta = extract_qm_from_mdin(
                mdin_path,
                topo,
                element_map,
                atom_types,
                prmtop_path=prmtop_path,
                crd_path=crd_path,
            )
            if indices:
                meta = dict(meta or {})
                label = meta.get('selection_source', 'iqmatoms/qmmask')
                return elems, indices, meta, label
        except Exception:
            pass
        return None

    def _step4_detect_links(topo, qm_indices, element_map):
        """Step 4: detect QM/MM link bonds, enrich with M2 shell for GEEP."""
        adjacency = build_mm_adjacency(topo)
        alias_plan = build_atom_type_alias_plan(topo)
        atom_types = list(alias_plan.atom_aliases)
        atomic_numbers = topo.get_int_array('ATOMIC_NUMBER')
        links = detect_link_bonds(
            topo, set(qm_indices),
            atom_types=atom_types,
            element_map=element_map,
            atomic_numbers=atomic_numbers,
        )
        natom = int(topo.natom or 0)
        charges_raw = topo.get_float_array('CHARGE')
        charges_e = [float(c) / AMBER_CHARGE_SCALE for c in charges_raw[:natom]]
        enrich_link_with_m2(
            links, adjacency, set(qm_indices), charges_e,
            atom_types=atom_types,
            element_map=element_map,
            atomic_numbers=atomic_numbers,
        )
        return links, adjacency

    # ── Phase registry ────────────────────────────────────────────────
    # PHASE_ORDER drives the breadcrumb, Back/Next logic, and the switch
    # identifiers; keep it exactly synchronized with the phase widget
    # classes below (the strings are also the ContentSwitcher ids).
    PHASE_ORDER = [
        ('system',     'System'),
        ('qm',         'QM region'),
        ('boundary',   'Boundary'),
        ('method',     'Method'),
        ('electronic', 'Electronic'),
        ('workflow',   'Workflow'),
        ('preview',    'Preview'),
        ('generate',   'Generate'),
    ]

    # ── Shared utilities ────────────────────────────────────────────
    def _detect_tui_terminal_profile() -> dict:
        """Return conservative terminal traits used for TUI launch tuning."""
        term = os.environ.get('TERM', '')
        cols, rows = shutil.get_terminal_size(fallback=(80, 24))
        screen_like = bool(os.environ.get('STY')) or term.startswith('screen')
        android_like = any(
            os.environ.get(name)
            for name in ('ANDROID_ROOT', 'ANDROID_DATA', 'TERMUX_VERSION')
        ) or 'com.termux' in os.environ.get('PREFIX', '')
        small = cols < 100 or rows < 28
        return {
            'term': term,
            'cols': int(cols),
            'rows': int(rows),
            'screen_like': bool(screen_like),
            'android_like': bool(android_like),
            'small': bool(small),
            'compat_recommended': bool(screen_like or android_like or small),
        }

    def _fmt_path(p, max_len=28):
        """Compact a path for the sidebar while preserving the basename."""
        if not p:
            return '[dim]not set[/dim]'
        s = str(p)
        if len(s) <= max_len:
            return s
        base = os.path.basename(s)
        if len(base) + 3 >= max_len:
            return base
        return '...' + s[-(max_len - 3):]

    def _fmt_box(box):
        if not box:
            return '[dim]not parsed[/dim]'
        try:
            a, b, c = box[:3]
            return f"{float(a):.1f} x {float(b):.1f} x {float(c):.1f} A"
        except Exception:
            return str(box)

    # ── Persistent-frame widgets ──────────────────────────────────────
    class TopBar(Horizontal):
        """Always-visible identity strip."""

        def __init__(self, work_dir: str):
            super().__init__(id='topbar')
            self.work_dir = work_dir

        def compose(self) -> 'ComposeResult':
            yield Static("charmmgui2cp2k", id='topbar-title')
            yield Static(
                f"  -  {os.path.basename(self.work_dir) or self.work_dir}",
                id='topbar-dir',
            )
            yield Static("", id='topbar-cp2k')

        def set_cp2k_info(self, text: str) -> None:
            try:
                self.query_one('#topbar-cp2k', Static).update(text)
            except NoMatches:
                pass

    class PhaseBreadcrumb(Static):
        """Horizontal phase list."""

        def __init__(self):
            super().__init__("[dim]initializing...[/]", id='breadcrumb')

        def set_current(self, index: int) -> None:
            if getattr(self.app, 'compact_mode', False):
                _phase_id, label = PHASE_ORDER[index]
                total = len(PHASE_ORDER)
                next_label = (
                    PHASE_ORDER[index + 1][1]
                    if index + 1 < total else "finish"
                )
                self.update(
                    f"[cyan bold]{index + 1}/{total} {label}[/]  "
                    f"[dim]next: {next_label}[/]"
                )
                return
            parts = []
            for i, (_id, label) in enumerate(PHASE_ORDER):
                if i < index:
                    parts.append(f"[green bold]{i + 1}. {label}[/]")
                elif i == index:
                    parts.append(f"[cyan bold reverse] {i + 1}. {label} [/]")
                else:
                    parts.append(f"[dim]{i + 1}. {label}[/]")
            self.update("[dim] | [/]".join(parts))

    class SummaryCard(Static):
        """One sidebar card: title plus rows."""

        def __init__(self, title: str, classes: str = 'card'):
            super().__init__(f"[b]{title}[/b]", classes=classes)
            self._title = title
            self._rows: list[tuple[str, str]] = []

        def set_rows(self, rows: list) -> None:
            self._rows = list(rows)
            self._redraw()

        def _redraw(self) -> None:
            lines = [f"[b]{self._title}[/b]"]
            for row in self._rows:
                if len(row) == 3:
                    k, v, flag = row
                else:
                    k, v = row
                    flag = None
                if flag == 'warn':
                    lines.append(f"[yellow]{k}[/] [b]{v}[/b]")
                elif flag == 'ok':
                    lines.append(f"[green]{k}[/] [b]{v}[/b]")
                elif flag == 'muted':
                    lines.append(f"[dim]{k}[/] [dim]{v}[/dim]")
                else:
                    lines.append(f"[dim]{k}[/] {v}")
            self.update("\n".join(lines))

    class SystemSummary(VerticalScroll):
        """Sticky left sidebar summarizing wizard state."""

        def __init__(self):
            super().__init__(id='sidebar')

        def compose(self) -> 'ComposeResult':
            yield SummaryCard("Files", classes='card')
            yield SummaryCard("System", classes='card')
            yield SummaryCard("QM region", classes='card')
            yield SummaryCard("Method", classes='card')

        def refresh_from_app(self, app: 'CharmmGui2Cp2kApp') -> None:
            cards = list(self.query(SummaryCard))
            if len(cards) < 4:
                return
            det = app.detected_files or {}
            cards[0].set_rows([
                ('prmtop', _fmt_path(det.get('prmtop'))),
                ('rst7',   _fmt_path(det.get('rst7'))),
                ('pdb',    _fmt_path(det.get('pdb'))),
                ('mdin',   _fmt_path(det.get('mdin'))),
                ('work',   _fmt_path(app.work_dir)),
            ])
            if app.topo is not None:
                natom = int(app.topo.natom or 0)
                try:
                    nres = len(app.topo.get_string_array('RESIDUE_LABEL') or [])
                except Exception:
                    nres = 0
                cards[1].set_rows([
                    ('atoms',    f"{natom:,}"),
                    ('residues', f"{nres:,}"),
                    ('box',      _fmt_box(app.box)),
                    ('types',    f"{len(app.element_map)} resolved",
                                 'warn' if app.unresolved_types else 'ok'),
                ])
            else:
                cards[1].set_rows([('topology', '[dim]not parsed[/dim]')])
            if app.qm_indices:
                elems_summary = ", ".join(
                    f"{el}:{len(idxs)}" for el, idxs in sorted(app.qm_elements.items())
                )
                cards[2].set_rows([
                    ('atoms',   f"{len(app.qm_indices):,}"),
                    ('elems',   elems_summary[:24] + ('...' if len(elems_summary) > 24 else '')),
                    ('links',   f"{len(app.links or [])}"),
                    ('scheme',  str(app.boundary_charge_scheme)),
                ])
            else:
                cards[2].set_rows([('atoms', '[dim]not set[/dim]')])
            cards[3].set_rows([
                ('func',     str(app.functional)),
                ('basis',    str(app.basis_set)[:22]),
                ('admm',     'on' if app.use_admm else 'off'),
                ('cutoff',   f"{app.cutoff:.0f} Ry"),
                ('charge',   f"{int(app.qm_charge):+d}"),
                ('mult',     f"{int(app.multiplicity)}"),
            ])

    class ValidationTray(Static):
        """Running count and tail of validation records."""

        def __init__(self):
            super().__init__("[green]OK[/] No validation issues.", id='tray')

        def refresh_from_app(self, app: 'CharmmGui2Cp2kApp') -> None:
            recs = list(app.validation_records or [])
            n_warn = sum(1 for s, _ in recs if s == 'warn')
            n_err = sum(1 for s, _ in recs if s == 'error')
            n_ok = sum(1 for s, _ in recs if s == 'ok')
            if not recs:
                self.update("[green]OK[/] No validation issues.")
                return
            head = (
                f"[b]Validation[/b]  "
                f"[green]{n_ok} ok[/]  "
                f"[yellow]{n_warn} warn[/]  "
                f"[red]{n_err} error[/]"
            )
            tail = []
            for sev, msg in recs[-4:]:
                colour = {'ok': 'green', 'warn': 'yellow', 'error': 'red'}.get(sev, 'white')
                sym = {'ok': 'OK', 'warn': 'WARN', 'error': 'ERR'}.get(sev, '-')
                tail.append(f"  [{colour}]{sym}[/] {msg}")
            self.update(head + "\n" + "\n".join(tail))

    class FooterBar(Horizontal):
        """Bottom action bar."""

        def __init__(self):
            super().__init__(id='footbar')

        def compose(self) -> 'ComposeResult':
            yield Button("Back", id='btn-back', variant='default')
            yield Static("Ready", id='footbar-hint')
            yield Button("Next", id='btn-next', variant='primary')

    # ── Phase base class ──────────────────────────────────────────────
    class PhaseBase(VerticalScroll):
        """Common scaffolding for every phase widget."""

        title: str = ""
        subtitle: str = ""

        def phase_enter(self, app: 'CharmmGui2Cp2kApp') -> None:  # override
            pass

        def validate(self, app: 'CharmmGui2Cp2kApp') -> tuple:  # override
            return True, []

        def commit(self, app: 'CharmmGui2Cp2kApp') -> None:  # override
            pass

        def _header(self) -> 'ComposeResult':
            yield Static(f"[b]{self.title}[/b]", classes='phase-title')
            if self.subtitle:
                yield Static(self.subtitle, classes='phase-subtitle')

        def _didactic(self, title: str, body: str) -> Collapsible:
            return Collapsible(
                Static(body, classes='muted'),
                title=title,
                collapsed=True,
                classes='didactic',
            )


    # ── Phase 1: SystemPhase ─────────────────────────────────────────
    class SystemPhase(PhaseBase):
        """Detects CHARMM-GUI outputs, probes CP2K, parses the topology.

        The three long-running calls (detect_files, detect_cp2k_installation,
        AmberTopology) are off-loaded to Workers so the event loop stays
        responsive; a LoadingIndicator runs until each completes.
        """

        title = "Step 1 · System inspection"
        subtitle = ("The wizard has scanned the working directory.  Confirm the "
                    "detected CHARMM-GUI outputs or edit paths before parsing.")

        def compose(self) -> 'ComposeResult':
            yield from self._header()
            yield Static("[b]Detected CHARMM-GUI artifacts[/]", classes='section-title')
            yield DataTable(id='system-files-table', cursor_type='row')
            yield Static("[b]CP2K installation[/]", classes='section-title')
            yield Static("[dim]Probing…[/]", id='system-cp2k')
            yield Static("[b]Topology[/]", classes='section-title')
            yield Static("[dim]Waiting for user to confirm files.[/]", id='system-topo-status')
            yield self._didactic(
                "Why this step exists",
                "Every downstream decision (QM region, link bonds, SCF profile, "
                "charge redistribution) is conditioned on a correctly parsed AMBER "
                "topology.  Parsing is therefore gated and explicit — the wizard "
                "never silently recovers from a missing or stale file."
            )

        def phase_enter(self, app):
            self._run_probes(app)

        @work(thread=True, exclusive=True, group='system')
        def _run_probes(self, app):
            # 1. detect_files (fast, but still off-main)
            detected = _step1_detect(app.work_dir)
            app.detected_files = detected
            self.app.call_from_thread(self._render_detected, detected)
            # 2. CP2K probe (may exec a binary; must not block UI)
            try:
                info = detect_cp2k_installation(probe_version=True)
                v = info.get('version')
                bins = list((info.get('binaries') or {}).values())
                label = (f"[green]✓ cp2k {v}[/]  ·  "
                         f"{os.path.basename(str(bins[0])) if bins else '[dim]no binary[/]'}"
                         if v else "[yellow]⚠ CP2K not detected on PATH[/]")
            except Exception as exc:
                label = f"[red]✗ CP2K probe failed: {exc}[/]"
            self.app.call_from_thread(self._set_cp2k_label, label, info)
            # 3. Topology parse
            if detected.get('prmtop') and detected.get('rst7'):
                try:
                    topo, coords, box, element_map, unresolved, alias_plan = _step2_parse_topology(
                        detected['prmtop'], detected['rst7'],
                    )
                    app.topo = topo
                    app.coords = coords
                    app.box = box
                    app.element_map = element_map
                    app.unresolved_types = unresolved
                    app.alias_plan = alias_plan
                    app.atom_types = list(alias_plan.atom_aliases)
                    self.app.call_from_thread(
                        self._set_topo_status,
                        f"[green]✓[/] Parsed {int(topo.natom or 0):,} atoms · "
                        f"box {_fmt_box(box)} · "
                        f"{len(element_map)} atom types resolved"
                        + (f" · [yellow]{len(unresolved)} unresolved[/]"
                           if unresolved else ""),
                    )
                    if unresolved:
                        app.validation_records.append((
                            'warn',
                            f"{len(unresolved)} atom types have no element mapping"
                        ))
                except Exception as exc:
                    self.app.call_from_thread(
                        self._set_topo_status, f"[red]✗ parse failed: {exc}[/]",
                    )
                    app.validation_records.append(('error', f"topology parse failed: {exc}"))
            else:
                self.app.call_from_thread(
                    self._set_topo_status,
                    "[red]Required files (prmtop + rst7) not detected.[/]",
                )
                app.validation_records.append(('error', "Missing prmtop/rst7"))
            self.app.call_from_thread(self.screen.refresh_state_ui)

        def _render_detected(self, detected):
            try:
                table = self.query_one('#system-files-table', DataTable)
            except NoMatches:
                return
            table.clear(columns=True)
            table.add_columns("File", "Detected path", "Status")
            rows = [
                ('prmtop', 'AMBER topology'),
                ('rst7',   'AMBER coordinates'),
                ('pdb',    'PDB structure'),
                ('mdin',   'AMBER input (MDIN)'),
            ]
            for key, label in rows:
                val = detected.get(key)
                if val:
                    table.add_row(label, os.path.basename(val), "[green]✓[/]")
                else:
                    table.add_row(label, '—', "[yellow]missing[/]" if key in ('prmtop','rst7') else "[dim]opt.[/]")

        def _set_cp2k_label(self, label, info):
            try:
                self.query_one('#system-cp2k', Static).update(label)
            except NoMatches:
                pass
            # Push the CP2K version string into the TopBar strip.
            try:
                v = (info or {}).get('version')
                top = self.app.query_one(TopBar)
                top.set_cp2k_info(f"cp2k {v}" if v else "cp2k (not found)")
            except Exception:
                pass

        def _set_topo_status(self, text):
            try:
                self.query_one('#system-topo-status', Static).update(text)
            except NoMatches:
                pass

        def validate(self, app):
            issues = []
            if app.topo is None:
                issues.append("Topology not parsed — cannot continue.")
            if not app.detected_files.get('prmtop'):
                issues.append("No prmtop detected.")
            return (not issues), issues


    # ── Phase 2: QMPhase ─────────────────────────────────────────────
    class QMPhase(PhaseBase):
        """Review / augment the QM region.

        The MDIN+PDB auto-detection (Morokuma-style QM selection language
        inherited from AMBER's iqmatoms/qmmask) is attempted first; users
        can then augment by pasting comma-separated indices.  The per-
        element counts are the same figures the CLI shows at main()
        line ~18867.
        """

        title = "Step 2 · QM region"
        subtitle = ("The QM region is the quantum subsystem.  Inspect the auto-"
                    "detected atoms and add extras if required.")

        def compose(self) -> 'ComposeResult':
            yield from self._header()
            yield Static("[b]Auto-detected QM atoms[/]", classes='section-title')
            yield Static("[dim]Detecting…[/]", id='qm-source')
            yield DataTable(id='qm-elements-table', cursor_type='none')
            yield Static("", id='qm-summary')
            yield Rule()
            yield Static("[b]Augment the QM region[/]", classes='section-title')
            yield self._didactic(
                "When to add atoms",
                "Only include atoms that participate in bond-making/breaking or "
                "electronic polarisation relevant to your question.  Atoms far "
                "from the active site inflate HFX cost without improving the "
                "description.  See Senn & Thiel, ACIE 48, 1198 (2009)."
            )
            yield Horizontal(
                Input(placeholder="Comma-separated 1-based indices", id='qm-extra-input'),
                Button("Add", id='btn-add-qm', variant='primary'),
                classes='row',
            )

        def phase_enter(self, app):
            self._auto_detect(app)

        @work(thread=True, exclusive=True, group='qm')
        def _auto_detect(self, app):
            detected = app.detected_files or {}
            qm_elements, qm_indices, label = {}, [], ""
            mdin_meta = {}
            # Try MDIN selections first.
            mdin_candidates = list(dict.fromkeys(
                list(detected.get('mdin_candidates') or []) +
                ([detected.get('mdin')] if detected.get('mdin') else [])
            ))
            atom_types = list(app.atom_types or [])
            for mdin_path in mdin_candidates:
                result = _step3_extract_qm_from_mdin(
                    mdin_path,
                    app.topo,
                    app.element_map,
                    atom_types,
                    prmtop_path=detected.get('prmtop'),
                    crd_path=detected.get('rst7'),
                )
                if result:
                    qm_elements, qm_indices, mdin_meta, label = result
                    label = f"{label} in {os.path.basename(mdin_path)}"
                    break
            # Fallback to PDB HETB/HETD tags.
            if not qm_indices and detected.get('pdb'):
                try:
                    pdb_elems, pdb_indices = extract_qm_from_pdb(detected['pdb'])
                    if pdb_indices:
                        qm_elements = pdb_elems
                        qm_indices = pdb_indices
                        label = "PDB HETB/HETD segments"
                except Exception:
                    pass
            if qm_indices:
                app.qm_elements = qm_elements
                app.qm_indices = qm_indices
                app.mdin_meta = mdin_meta
                app.qm_source_label = label
                if mdin_meta.get('qmcharge') is not None:
                    app.qm_charge = int(mdin_meta['qmcharge'])
                spin_meta = parse_mdin_spin_metadata(mdin_meta)
                if spin_meta.get('mdin_multiplicity') is not None:
                    app.multiplicity = int(spin_meta['mdin_multiplicity'])
            self.app.call_from_thread(self._redraw, app, label)
            self.app.call_from_thread(self.screen.refresh_state_ui)

        def _redraw(self, app, label):
            src = self.query_one('#qm-source', Static)
            if app.qm_indices:
                src.update(f"[green]✓[/] From [b]{label or 'detection'}[/b]: "
                           f"{len(app.qm_indices):,} QM atoms")
            else:
                src.update("[yellow]⚠ No QM atoms detected — add them manually below.[/]")
            tbl = self.query_one('#qm-elements-table', DataTable)
            tbl.clear(columns=True)
            tbl.add_columns("Element", "Atoms", "Contribution")
            total = max(1, sum(len(v) for v in app.qm_elements.values()))
            for el, idxs in sorted(app.qm_elements.items()):
                share = 100.0 * len(idxs) / total
                tbl.add_row(el, f"{len(idxs):,}", f"{share:4.1f}%")
            self.query_one('#qm-summary', Static).update(
                f"[b]Total QM atoms:[/b] {len(app.qm_indices):,} · "
                f"[b]elements:[/b] {', '.join(sorted(app.qm_elements.keys())) or '—'}"
            )

        @on(Button.Pressed, '#btn-add-qm')
        def _add_qm(self, _ev):
            app = self.app
            inp = self.query_one('#qm-extra-input', Input)
            raw = (inp.value or '').strip()
            if not raw:
                self.app.notify("Enter comma-separated atom indices.",
                                severity='warning'); return
            try:
                new_elems, new_indices = extract_qm_from_indices(
                    raw,
                    app.topo,
                    app.element_map,
                    list(app.atom_types or []),
                )
                for el, idxs in new_elems.items():
                    if el in app.qm_elements:
                        s = set(app.qm_elements[el]); s.update(idxs)
                        app.qm_elements[el] = sorted(s)
                    else:
                        app.qm_elements[el] = sorted(idxs)
                s = set(app.qm_indices); s.update(new_indices)
                app.qm_indices = sorted(s)
                self.app.notify(f"Added {len(new_indices)} atoms. Total: {len(app.qm_indices)}")
                self._redraw(app, 'user addition')
                inp.value = ''
                self.screen.refresh_state_ui()
            except Exception as exc:
                self.app.notify(f"Parse error: {exc}", severity='error')

        def validate(self, app):
            if not app.qm_indices:
                return False, ["QM region is empty."]
            return True, []


    # ── Phase 3: BoundaryPhase ───────────────────────────────────────
    class BoundaryPhase(PhaseBase):
        """Link-atom detection and boundary-charge scheme selection.

        Link bonds are found automatically (same detect_link_bonds path
        the CLI uses).  The scheme choice drives how residual charge from
        removed MM atoms is redistributed — the single most important
        choice for artifact-free embedding; see Lin & Truhlar, Theor.
        Chem. Acc. 117, 185 (2007).
        """

        title = "Step 3 · Boundary treatment"
        subtitle = ("QM/MM link bonds need hydrogen caps and a residual-charge "
                    "redistribution rule.  The wizard detects link bonds and "
                    "recommends the scheme best suited to your system.")

        SCHEMES = [
            ('CHARGE_SHIFT', 'Shift the M1 charge onto its MM neighbours'),
            ('RC',           'Redistribute to remote MM atoms (Lin/Truhlar RC)'),
            ('RCD',          'RC + dipole correction (RCD)'),
            ('Z1',           'Zero only M1 charge (Z1, simplest, has dipole artefact)'),
            ('Z2',           'Zero M1 and M2 charges'),
            ('NONE',         'Leave all charges — use only for validation'),
        ]

        def compose(self) -> 'ComposeResult':
            yield from self._header()
            yield Static("[b]Detected QM/MM link bonds[/]", classes='section-title')
            yield DataTable(id='links-table', cursor_type='row')
            yield Static("", id='links-summary')
            yield Rule()
            yield Static("[b]Boundary-charge scheme[/]", classes='section-title')
            yield self._didactic(
                "Choosing a scheme",
                "CHARGE_SHIFT is a robust default for well-formed protein QM/MM "
                "boundaries.  RC/RCD are preferred when dipole artefacts are "
                "visible in the electron density near M1.  Z1/Z2 are kept for "
                "comparison only.  Each choice is written verbatim into "
                "&QMMM/&LINK and the MM topology — this is not cosmetic."
            )
            yield RadioSet(
                *[RadioButton(f"{k}  —  {desc}", id=f'sch-{k}')
                  for k, desc in self.SCHEMES],
                id='scheme-radio',
            )

        def phase_enter(self, app):
            self._detect(app)

        @work(thread=True, exclusive=True, group='boundary')
        def _detect(self, app):
            if app.topo is None or not app.qm_indices:
                return
            app.boundary_detection_done = False
            try:
                links, adjacency = _step4_detect_links(
                    app.topo, app.qm_indices, app.element_map,
                )
                app.links = links
                app.adjacency = adjacency
                app.boundary_detection_done = True
            except Exception as exc:
                app.validation_records.append(('error', f"link detection: {exc}"))
                return
            self.app.call_from_thread(self._redraw, app)
            self.app.call_from_thread(self.screen.refresh_state_ui)

        def _redraw(self, app):
            tbl = self.query_one('#links-table', DataTable)
            tbl.clear(columns=True)
            tbl.add_columns("#", "QM atom (Q1)", "MM atom (M1)", "M2 shell", "Cap")
            for i, link in enumerate(app.links or [], start=1):
                m2 = link.get('M2_ATOMS', []) or []
                tbl.add_row(
                    str(i),
                    f"{link.get('QM_ELEMENT','?')}{link.get('QM_ATOM_INDEX','?')}",
                    f"{link.get('MM_ELEMENT','?')}{link.get('MM_ATOM_INDEX','?')}",
                    f"{len(m2)}",
                    link.get('CAP_ELEMENT', 'H'),
                )
            summary = self.query_one('#links-summary', Static)
            if app.links:
                summary.update(f"[green]✓[/] {len(app.links)} link bond(s) detected")
            else:
                summary.update(
                    "[green]✓[/] No link bonds — QM region is chemically isolated.")
            # Pre-select the current scheme radio
            try:
                radio = self.query_one('#scheme-radio', RadioSet)
                for btn in radio.query(RadioButton):
                    btn.value = (btn.id == f'sch-{app.boundary_charge_scheme}')
            except NoMatches:
                pass

        def commit(self, app):
            try:
                radio = self.query_one('#scheme-radio', RadioSet)
                for btn in radio.query(RadioButton):
                    if btn.value and btn.id and btn.id.startswith('sch-'):
                        app.boundary_charge_scheme = btn.id[4:]
                        break
            except NoMatches:
                pass

        def validate(self, app):
            if app.topo is not None and app.qm_indices and not app.boundary_detection_done:
                return False, ["Boundary detection is still running."]
            return True, []


    # ── Phase 4: MethodPhase ─────────────────────────────────────────
    class MethodPhase(PhaseBase):
        """DFT method selection — Basic/Expert tabs.

        Basic:   functional (B3LYP / PBE0 / PBE), ADMM on/off, cutoff preset
        Expert:  basis set, MGRID cutoff/rel_cutoff/ngrids, GEEP lib count
        """

        title = "Step 4 · DFT method"
        subtitle = ("Choose the functional, basis, and density-cutoff grid.  "
                    "Recommendations come from the same heuristics the CLI uses.")

        FUNCTIONALS = [('B3LYP', 'Hybrid · general-purpose'),
                       ('PBE0',  'Hybrid · sharper for TM'),
                       ('PBE',   'GGA · fast, screening')]

        BASIS_SETS = ['DZVP-MOLOPT-GTH', 'TZVP-MOLOPT-GTH', 'TZV2P-MOLOPT-GTH']

        def compose(self) -> 'ComposeResult':
            yield from self._header()
            with TabbedContent(initial='basic'):
                with TabPane("Basic", id='basic'):
                    yield Static("[b]Functional[/]", classes='section-title')
                    yield RadioSet(
                        *[RadioButton(f"{n}  —  {desc}", id=f'func-{n}')
                          for n, desc in self.FUNCTIONALS],
                        id='func-radio',
                    )
                    yield self._didactic(
                        "Hybrid functional cost",
                        "B3LYP/PBE0 require HF-exchange; wall time grows with "
                        "the QM region faster than GGA.  ADMM (auxiliary density "
                        "matrix method, Guidon et al. JCTC 6, 2348, 2010) is ON "
                        "by default: expect ~5× speedup with negligible energy "
                        "difference."
                    )
                    yield Horizontal(
                        Static("[b]ADMM:[/b]", classes='row-label'),
                        Switch(value=True, id='admm-switch'),
                        Static("(auxiliary density matrix method)",
                               classes='row-hint'),
                        classes='row',
                    )
                with TabPane("Expert", id='expert'):
                    yield Static("[b]Orbital basis[/]", classes='section-title')
                    yield Select(
                        [(b, b) for b in self.BASIS_SETS],
                        value='DZVP-MOLOPT-GTH', id='basis-select', allow_blank=False,
                    )
                    yield Static("[b]Planewave grid[/]", classes='section-title')
                    yield self._didactic(
                        "CUTOFF & REL_CUTOFF",
                        "CUTOFF sets the planewave density grid finest scale; "
                        "REL_CUTOFF controls how basis functions are mapped "
                        "between the 5 (or 4) grids of the MGRID hierarchy.  "
                        "For MOLOPT-GTH defaults of 500/60/5 are a tested "
                        "compromise; raise both together if SCF total energy "
                        "is unstable under MGRID changes."
                    )
                    yield Horizontal(
                        Static("CUTOFF (Ry):", classes='row-label'),
                        Input(value="500", id='inp-cutoff'),
                        Static("typical 400–800", classes='row-hint'),
                        classes='row',
                    )
                    yield Horizontal(
                        Static("REL_CUTOFF (Ry):", classes='row-label'),
                        Input(value="60", id='inp-rel-cutoff'),
                        Static("typical 40–80", classes='row-hint'),
                        classes='row',
                    )
                    yield Horizontal(
                        Static("NGRIDS:", classes='row-label'),
                        Input(value="5", id='inp-ngrids'),
                        Static("5 for MOLOPT; 4 for GTH", classes='row-hint'),
                        classes='row',
                    )
                    yield Horizontal(
                        Static("USE_GEEP_LIB:", classes='row-label'),
                        Input(value=str(DEFAULT_QMMM_GEEP_LIB), id='inp-geep'),
                        Static("9 = published GEEP default", classes='row-hint'),
                        classes='row',
                    )

        def phase_enter(self, app):
            try:
                radio = self.query_one('#func-radio', RadioSet)
                for btn in radio.query(RadioButton):
                    btn.value = (btn.id == f'func-{app.functional}')
                self.query_one('#admm-switch', Switch).value = bool(app.use_admm)
                self.query_one('#basis-select', Select).value = app.basis_set
                self.query_one('#inp-cutoff', Input).value = str(int(app.cutoff))
                self.query_one('#inp-rel-cutoff', Input).value = str(int(app.rel_cutoff))
                self.query_one('#inp-ngrids', Input).value = str(int(app.mgrid_ngrids))
                self.query_one('#inp-geep', Input).value = str(int(app.geep_lib))
            except NoMatches:
                pass

        def commit(self, app):
            try:
                radio = self.query_one('#func-radio', RadioSet)
                for btn in radio.query(RadioButton):
                    if btn.value and btn.id and btn.id.startswith('func-'):
                        app.functional = btn.id[5:]
                        break
                app.use_admm  = bool(self.query_one('#admm-switch', Switch).value)
                app.basis_set = self.query_one('#basis-select', Select).value
                app.cutoff    = float(self.query_one('#inp-cutoff', Input).value or '500')
                app.rel_cutoff= float(self.query_one('#inp-rel-cutoff', Input).value or '60')
                app.mgrid_ngrids = int(self.query_one('#inp-ngrids', Input).value or '5')
                app.geep_lib  = int(self.query_one('#inp-geep', Input).value or str(DEFAULT_QMMM_GEEP_LIB))
            except (NoMatches, ValueError) as exc:
                app.validation_records.append(('warn', f"method input: {exc}"))


    # ── Phase 5: ElectronicPhase ─────────────────────────────────────
    class ElectronicPhase(PhaseBase):
        """Total QM charge, multiplicity, and a live parity audit.

        The parity check uses estimate_qm_electrons_for_spin to warn when
        the user-supplied multiplicity is incompatible with the electron
        count implied by the selected QM region.  This catches typos
        early (e.g. asking for multiplicity=2 on an even-electron count).
        """

        title = "Step 5 · Electronic state"
        subtitle = ("Set the net QM charge and spin multiplicity.  The wizard "
                    "verifies electron parity against the selected QM region "
                    "so a bad spin state cannot silently propagate.")

        def compose(self) -> 'ComposeResult':
            yield from self._header()
            yield Horizontal(
                Static("Net QM charge:", classes='row-label'),
                Input(value="0", id='inp-charge'),
                Static("integer, signed (e.g. -2, 0, +1)", classes='row-hint'),
                classes='row',
            )
            yield Horizontal(
                Static("Multiplicity:", classes='row-label'),
                Input(value="1", id='inp-mult'),
                Static("2S+1 (1=singlet, 2=doublet, 3=triplet)", classes='row-hint'),
                classes='row',
            )
            yield Rule()
            yield Static("[b]Parity audit[/]", classes='section-title')
            yield Static("[dim]Enter values above to run the parity check.[/]",
                         id='parity-status')
            yield self._didactic(
                "Electron parity",
                "An even-electron QM region cannot carry an even "
                "multiplicity; an odd-electron region cannot carry an odd "
                "multiplicity.  The check here uses the GTH valence q-tags "
                "(Krack, Theor. Chem. Acc. 114, 145, 2005) — the same "
                "partition CP2K uses for CHARGE/MULTIPLICITY."
            )
            yield Rule()
            yield Static("[b]Recommended SCF profile[/]", classes='section-title')
            yield Static("[dim]Will be computed from your QM region.[/]",
                         id='scf-status')

        def phase_enter(self, app):
            self._apply_spin_recommendation(app)
            try:
                self.query_one('#inp-charge', Input).value = str(int(app.qm_charge))
                self.query_one('#inp-mult', Input).value = str(int(app.multiplicity))
            except NoMatches:
                pass
            self._refresh_advisories(app)

        def _apply_spin_recommendation(self, app):
            try:
                decision = recommend_qm_spin_state(
                    qm_elements=app.qm_elements,
                    qm_charge=int(app.qm_charge),
                    link_bonds=list(app.links or []),
                    user_multiplicity=None,
                    mdin_meta=getattr(app, 'mdin_meta', {}),
                )
                app.spin_decision = decision
                recommended = decision.get('multiplicity')
                if (
                    recommended is not None
                    and not getattr(app, 'multiplicity_user_set', False)
                    and decision.get('decision_class') in ('AUTHORITATIVE', 'LOW_RISK_INFERRED')
                ):
                    app.multiplicity = int(recommended)
            except Exception:
                pass

        @on(Input.Changed, '#inp-charge')
        @on(Input.Changed, '#inp-mult')
        def _on_change(self, _ev):
            self._refresh_advisories(self.app)

        def _refresh_advisories(self, app):
            try:
                charge = int((self.query_one('#inp-charge', Input).value or '0').strip())
                mult = int((self.query_one('#inp-mult', Input).value or '1').strip())
            except ValueError:
                self.query_one('#parity-status', Static).update(
                    "[red]x charge or multiplicity is not an integer[/]")
                return
            try:
                _elec, meta = estimate_qm_electrons_for_spin(
                    qm_elements=app.qm_elements,
                    qm_charge=charge,
                    link_bonds=list(app.links or []),
                )
                final = meta.get('final_electron_count')
                if final is not None:
                    final_parity = 'even' if final % 2 == 0 else 'odd'
                    mult_parity = 'odd' if mult % 2 == 1 else 'even'
                    ok = ((final % 2) == ((mult - 1) % 2))
                    sym = "[green]OK[/]" if ok else "[red]ERR[/]"
                    self.query_one('#parity-status', Static).update(
                        f"{sym} valence electrons: [b]{final}[/b] "
                        f"({final_parity}); multiplicity {mult} implies "
                        f"{mult_parity} parity; "
                        f"{ '[green]consistent[/]' if ok else '[red]INCONSISTENT[/]' }"
                    )
                else:
                    self.query_one('#parity-status', Static).update(
                        "[yellow]could not estimate valence electrons.[/]")
                try:
                    app.spin_decision = recommend_qm_spin_state(
                        qm_elements=app.qm_elements,
                        qm_charge=charge,
                        link_bonds=list(app.links or []),
                        user_multiplicity=mult,
                        mdin_meta=getattr(app, 'mdin_meta', {}),
                    )
                except Exception:
                    pass
            except Exception as exc:
                self.query_one('#parity-status', Static).update(f"[red]{exc}[/]")
            try:
                qm_atom_count = sum(len(v) for v in app.qm_elements.values()) or 1
                prof, reason = recommended_scf_profile(
                    app.qm_elements.keys(), app.functional, qm_atom_count,
                    multiplicity=mult,
                )
                self.query_one('#scf-status', Static).update(
                    f"[$accent b]{prof}[/]  -  {reason}"
                )
            except Exception as exc:
                self.query_one('#scf-status', Static).update(f"[red]{exc}[/]")

        def commit(self, app):
            try:
                app.qm_charge = int((self.query_one('#inp-charge', Input).value or '0').strip())
                app.multiplicity = int((self.query_one('#inp-mult', Input).value or '1').strip())
                app.multiplicity_user_set = True
            except ValueError as exc:
                app.validation_records.append(('warn', f"electronic: {exc}"))

        def validate(self, app):
            try:
                charge = int((self.query_one('#inp-charge', Input).value or '0').strip())
                mult = int((self.query_one('#inp-mult', Input).value or '1').strip())
            except (NoMatches, ValueError):
                return False, ["Charge and multiplicity must be integers."]
            electrons, _meta = estimate_qm_electrons_for_spin(
                qm_elements=app.qm_elements,
                qm_charge=charge,
                link_bonds=list(app.links or []),
            )
            parity_ok, parity_msg = validate_multiplicity_parity(mult, electrons)
            if parity_ok is False:
                return False, [parity_msg]
            return True, []


    # ── Phase 6: WorkflowPhase ───────────────────────────────────────
    class WorkflowPhase(PhaseBase):
        """MD ladder: EM → MM-NVT → MM-NPT → QM/MM-warmup → QM/MM-MD.

        Each stage's step count / timestep / ensemble is editable; the
        QM/MM warmup can be disabled for tightly prepared systems.
        """

        title = "Step 6 · Workflow configuration"
        subtitle = ("Tune the MD staging ladder.  Defaults are the same ones "
                    "the CLI uses and have been validated on biomolecular "
                    "systems up to 200k atoms.")

        def compose(self) -> 'ComposeResult':
            yield from self._header()
            yield Static("[b]MM equilibration[/]", classes='section-title')
            yield Horizontal(
                Static("EM max-iter:", classes='row-label'),
                Input(value="2000", id='inp-em'),
                Static("conjugate-gradient minimisation", classes='row-hint'),
                classes='row',
            )
            yield Horizontal(
                Static("MM-NVT steps:", classes='row-label'),
                Input(value="5000", id='inp-nvt'),
                Static("1 fs step, thermostat equilibration", classes='row-hint'),
                classes='row',
            )
            yield Horizontal(
                Static("MM-NPT steps:", classes='row-label'),
                Input(value="10000", id='inp-npt'),
                Static("barostat relaxation", classes='row-hint'),
                classes='row',
            )
            yield Static("[b]QM/MM production[/]", classes='section-title')
            yield Horizontal(
                Static("Warmup:", classes='row-label'),
                Switch(value=True, id='sw-warmup'),
                Static("0.25 fs, short NVT handoff into QM forces",
                       classes='row-hint'),
                classes='row',
            )
            yield Horizontal(
                Static("Production steps:", classes='row-label'),
                Input(value="100000", id='inp-prod-steps'),
                Static("total QM/MM MD steps", classes='row-hint'),
                classes='row',
            )
            yield Horizontal(
                Static("Timestep (fs):", classes='row-label'),
                Input(value="0.5", id='inp-prod-dt'),
                Static("QM/MM typical 0.25–1.0", classes='row-hint'),
                classes='row',
            )
            yield Horizontal(
                Static("Temperature (K):", classes='row-label'),
                Input(value="300", id='inp-prod-T'),
                Static("target thermostat value", classes='row-hint'),
                classes='row',
            )
            yield Horizontal(
                Static("Ensemble:", classes='row-label'),
                Select([(e, e) for e in ('NVT','NPT','NVE')],
                       value='NVT', id='sel-ens', allow_blank=False),
                Static("NVT is the safest default", classes='row-hint'),
                classes='row',
            )
            yield self._didactic(
                "Handoff policy",
                "RESET_DYNAMICS (default) discards MM velocities at the "
                "QM/MM boundary so a short thermalisation re-seeds the "
                "warm start; CONTINUE passes them through verbatim.  "
                "Prefer RESET_DYNAMICS unless you have a specific reason."
            )
            yield Horizontal(
                Static("Handoff:", classes='row-label'),
                Select([('RESET_DYNAMICS','RESET_DYNAMICS'),
                        ('CONTINUE','CONTINUE')],
                        value='RESET_DYNAMICS', id='sel-handoff', allow_blank=False),
                classes='row',
            )

        def phase_enter(self, app):
            try:
                self.query_one('#inp-em', Input).value   = str(app.em_max_iter)
                self.query_one('#inp-nvt', Input).value  = str(app.mm_nvt_steps)
                self.query_one('#inp-npt', Input).value  = str(app.mm_npt_steps)
                self.query_one('#sw-warmup', Switch).value = bool(app.enable_warmup)
                self.query_one('#inp-prod-steps', Input).value = str(app.md_steps)
                self.query_one('#inp-prod-dt', Input).value = str(app.md_timestep)
                self.query_one('#inp-prod-T', Input).value = str(app.md_temperature)
                self.query_one('#sel-ens', Select).value = app.md_ensemble
                self.query_one('#sel-handoff', Select).value = app.handoff_policy_mode
            except NoMatches:
                pass

        def commit(self, app):
            try:
                app.em_max_iter    = int(self.query_one('#inp-em', Input).value or '2000')
                app.mm_nvt_steps   = int(self.query_one('#inp-nvt', Input).value or '5000')
                app.mm_npt_steps   = int(self.query_one('#inp-npt', Input).value or '10000')
                app.enable_warmup  = bool(self.query_one('#sw-warmup', Switch).value)
                app.md_steps       = int(self.query_one('#inp-prod-steps', Input).value or '100000')
                app.md_timestep    = float(self.query_one('#inp-prod-dt', Input).value or '0.5')
                app.md_temperature = float(self.query_one('#inp-prod-T', Input).value or '300')
                app.md_ensemble    = self.query_one('#sel-ens', Select).value
                app.handoff_policy_mode = self.query_one('#sel-handoff', Select).value
            except (NoMatches, ValueError) as exc:
                app.validation_records.append(('warn', f"workflow: {exc}"))


    # ── Phase 7: PreviewPhase ────────────────────────────────────────
    class PreviewPhase(PhaseBase):
        """Dense operational summary before any file is written.

        The preview runs assemble_staged_cp2k_workflow on the current
        wizard state (in-memory, no disk writes) so the operator sees
        the actual CP2K stage files that WILL be written.  The 4-
        quadrant grid surfaces:
          TL  Files to be written (with per-stage line count + headline
              FORCE_EVAL keys)
          TR  Scientific knobs summary (functional/basis/ADMM/CHARGE/
              MULTIPLICITY/SCF profile/GEEP lib/QM cell)
          BL  Validation records accumulated so far
          BR  Next actions once Generate completes
        """

        title = "Step 7 · Pre-generation review"
        subtitle = ("Nothing has been written yet.  The panels below summarise "
                    "exactly what the Generate step will emit — review each "
                    "before you authorise the write.")

        def compose(self) -> 'ComposeResult':
            yield from self._header()
            from textual.containers import Grid
            with Grid(id='preview-grid'):
                with Vertical(classes='preview-quadrant'):
                    yield Static("[b]Files to be written[/]", classes='preview-quadrant-title')
                    yield DataTable(id='preview-files', cursor_type='none')
                with Vertical(classes='preview-quadrant'):
                    yield Static("[b]Scientific configuration[/]", classes='preview-quadrant-title')
                    yield Static("[dim]Rendering…[/]", id='preview-knobs')
                with Vertical(classes='preview-quadrant'):
                    yield Static("[b]Validation records[/]", classes='preview-quadrant-title')
                    yield Static("[dim]—[/]", id='preview-val')
                with Vertical(classes='preview-quadrant'):
                    yield Static("[b]Next actions[/]", classes='preview-quadrant-title')
                    yield Static(
                        "• [b]Generate →[/b] writes all stage files to a "
                        "timestamped `cp2k_output_*` folder under the working "
                        "directory.\n"
                        "• A `run_qmmm_project.sh` wrapper is emitted that "
                        "auto-chains stages and includes a CP2K version check.\n"
                        "• `README_next_steps.txt` lists the recommended "
                        "cp2k.psmp / cp2k.ssmp invocation for this machine.\n"
                        "• `electronic_state.dat` records the CHARGE / "
                        "MULTIPLICITY reasoning for audit.\n"
                        "• You can abort at any time; nothing is written until "
                        "you press Generate.",
                    )

        def phase_enter(self, app):
            self._assemble(app)

        @work(thread=True, exclusive=True, group='preview')
        def _assemble(self, app):
            # Re-use the same build path as GeneratePhase but without disk writes.
            try:
                qm_elements = dict(app.qm_elements)
                multiplicity = int(app.multiplicity)
                qm_atom_count = sum(len(v) for v in qm_elements.values()) or 1
                rec_profile, rec_reason = recommended_scf_profile(
                    qm_elements.keys(), app.functional, qm_atom_count,
                    multiplicity=multiplicity,
                )
                scf_cfg = dict(SCF_PROFILES[rec_profile])
                qmmm_periodic_policy = make_qmmm_periodic_policy()
                qm_cell_abc, _ = compute_qm_cell(
                    list(app.qm_indices), app.coords,
                    padding=qmmm_periodic_policy.qm_cell_padding,
                    box_dims=app.box,
                    qmmm_periodic_policy=qmmm_periodic_policy,
                )
                qm_kinds_lines, _unres = generate_qm_kinds(
                    qm_elements, basis_set=app.basis_set, use_admm=app.use_admm,
                )
                m1_set = {
                    int(link.get('MM_INDEX'))
                    for link in (app.links or [])
                    if link.get('MM_INDEX') is not None
                }
                residual_charge_plan = build_residual_charge_plan(
                    app.qm_indices,
                    app.topo,
                    m1_set=m1_set,
                    redistribute_strategy='uniform',
                    coords=app.coords,
                )
                qmmm_charge_override = _apply_residual_charge_plan_to_raw_charges(
                    app.topo.get_float_array('CHARGE'),
                    residual_charge_plan,
                )
                mm_data = collect_topology_variant_data(
                    app.topo, list(qm_elements.keys()), alias_plan=app.alias_plan,
                )
                qmmm_data = collect_topology_variant_data(
                    app.topo, list(qm_elements.keys()),
                    charge_array_override=qmmm_charge_override, alias_plan=app.alias_plan,
                )
                system_model = make_system_spec(
                    prmtop_file='system_qmmm.prmtop',
                    xyz_file='system.xyz',
                    box_dims=app.box,
                    qm_elements=qm_elements,
                    link_bonds=list(app.links or []),
                    qm_kinds_lines=qm_kinds_lines,
                    mm_kinds_lines=mm_data['mm_kinds'],
                    mm_stage_kinds_lines=mm_data['mm_kinds'],
                    qmmm_stage_kinds_lines=qmmm_data['mm_kinds'],
                    mm_prmtop_file='system_mm.prmtop',
                    qmmm_prmtop_file='system_qmmm.prmtop',
                    qmmm_periodic_policy=qmmm_periodic_policy,
                    qm_cell_abc=qm_cell_abc,
                    qm_charge=int(app.qm_charge),
                    multiplicity=multiplicity,
                    natom=app.topo.natom,
                )
                dft_config = make_dft_config(
                    functional=app.functional,
                    basis_set=app.basis_set,
                    cutoff=app.cutoff,
                    rel_cutoff=app.rel_cutoff,
                    mgrid_ngrids=app.mgrid_ngrids,
                    use_admm=app.use_admm,
                    scf_profile=rec_profile,
                    scf_max_scf=scf_cfg['max_scf'],
                    scf_eps_scf=scf_cfg['eps_scf'],
                    scf_guess=scf_cfg['scf_guess'],
                    scf_cholesky=scf_cfg.get('cholesky'),
                    qs_eps_default=scf_cfg.get('qs_eps_default'),
                    scf_added_mos=scf_cfg['added_mos'],
                    scf_mixing_method=scf_cfg['mixing_method'],
                    scf_mixing_alpha=scf_cfg['mixing_alpha'],
                    scf_nbroyden=scf_cfg['nbroyden'],
                    outer_max_scf=scf_cfg['outer_max_scf'],
                    outer_eps_scf=scf_cfg['outer_eps_scf'],
                    qmmm_geep_lib=app.geep_lib,
                    boundary_charge_scheme=app.boundary_charge_scheme,
                    qm_elements_for_admm=qm_elements,
                    qm_kinds_lines_for_admm=qm_kinds_lines,
                )
                workflow_config = make_workflow_config(
                    production_steps=app.md_steps,
                    production_timestep=app.md_timestep,
                    production_temperature=app.md_temperature,
                    production_ensemble=app.md_ensemble,
                    em_max_iter=app.em_max_iter,
                    mm_nvt_steps=app.mm_nvt_steps,
                    mm_npt_steps=app.mm_npt_steps,
                    mm_timestep=1.0,
                    enable_qmmm_warmup=app.enable_warmup,
                    qmmm_handoff_policy=make_qmmm_handoff_policy(
                        mode=app.handoff_policy_mode),
                    restraint_indices=list(app.qm_indices),
                )
                stage_inputs, stage_meta = assemble_staged_cp2k_workflow(
                    system_model, dft_config, workflow_config,
                )
                qm_cell_str = ", ".join(f"{float(x):.2f}" for x in str(qm_cell_abc).split())
                self.app.call_from_thread(
                    self._render_summary, app, stage_inputs, stage_meta,
                    rec_profile, rec_reason, qm_cell_abc, residual_charge_plan,
                )
            except Exception as exc:
                self.app.call_from_thread(
                    self._render_error, exc,
                )

        def _render_summary(self, app, stage_inputs, stage_meta, rec_profile, rec_reason, qm_cell_abc, residual_charge_plan):
            # ── Files table ──────────────────────────────────────────
            try:
                tbl = self.query_one('#preview-files', DataTable)
                tbl.clear(columns=True)
                tbl.add_columns("#", "Stage", "Lines", "Headline")
                for i, (name, content) in enumerate(stage_inputs.items(), start=1):
                    lines = content.splitlines()
                    # Extract the first meaningful FORCE_EVAL / RUN_TYPE line.
                    headline = ''
                    for ln in lines[:40]:
                        s = ln.strip()
                        if s.startswith('RUN_TYPE') or s.startswith('METHOD'):
                            headline = s[:28]; break
                    tbl.add_row(str(i), name, f"{len(lines):,}", headline or "—")
                # Extra wrapper/README/PDB/prmtop rows (written by GeneratePhase)
                for extra in ('system_mm.prmtop', 'system_qmmm.prmtop',
                              'system.xyz', 'system_qmmm_flag.pdb',
                              'system_qm_only.pdb', 'run_qmmm_project.sh',
                              'README_next_steps.txt', 'electronic_state.dat'):
                    tbl.add_row("", f"[dim]{extra}[/]", "", "[dim]auxiliary[/]")
            except NoMatches:
                pass
            # ── Scientific knobs ────────────────────────────────────
            knobs = (
                f"[b]Functional:[/]   {app.functional}  "
                f"[b]Basis:[/] {app.basis_set}  "
                f"[b]ADMM:[/] {'on' if app.use_admm else 'off'}\n"
                f"[b]CUTOFF:[/]       {app.cutoff:g} Ry  "
                f"[b]REL_CUTOFF:[/] {app.rel_cutoff:g}  "
                f"[b]NGRIDS:[/] {app.mgrid_ngrids}\n"
                f"[b]CHARGE:[/]       {int(app.qm_charge):+d}  "
                f"[b]MULTIPLICITY:[/] {int(app.multiplicity)}  "
                f"[b]UKS:[/] {'yes' if int(app.multiplicity) > 1 else 'no'}\n"
                f"[b]SCF profile:[/]  {rec_profile}\n"
                f"[dim]reason:[/] {rec_reason}\n"
                f"[b]QM cell (Å):[/]  {qm_cell_abc}\n"
                f"[b]GEEP lib:[/]     {app.geep_lib}  "
                f"[b]Boundary scheme:[/] {app.boundary_charge_scheme}\n"
                f"[b]Residual charge:[/] {len(residual_charge_plan or [])} split residue(s)\n"
                f"[b]QM atoms:[/]     {len(app.qm_indices):,} "
                f"({', '.join(sorted(app.qm_elements.keys()))})\n"
                f"[b]Links:[/]        {len(app.links or [])}\n"
                f"[b]MD ladder:[/]    EM → NVT({app.mm_nvt_steps:,}) → "
                f"NPT({app.mm_npt_steps:,}) → warmup"
                f"{' ' if app.enable_warmup else '(off) '}→ "
                f"QMMM({app.md_steps:,}, {app.md_timestep:g} fs, "
                f"{app.md_ensemble})"
            )
            try:
                self.query_one('#preview-knobs', Static).update(knobs)
            except NoMatches:
                pass
            # ── Validation summary ──────────────────────────────────
            try:
                recs = list(app.validation_records or [])
                if not recs:
                    self.query_one('#preview-val', Static).update(
                        "[green]✓ No warnings captured during configuration.[/]")
                else:
                    by_sev = {'ok': [], 'warn': [], 'error': []}
                    for sev, msg in recs:
                        by_sev.setdefault(sev, []).append(msg)
                    bits = []
                    for sev, colour in (('error','error'), ('warn','warning'), ('ok','success')):
                        if by_sev[sev]:
                            bits.append(f"[${colour} b]{sev.upper()}[/] ({len(by_sev[sev])})")
                            for m in by_sev[sev][-6:]:
                                bits.append(f"  [${colour}]•[/] {m}")
                    self.query_one('#preview-val', Static).update("\n".join(bits))
            except NoMatches:
                pass

        def _render_error(self, exc):
            try:
                self.query_one('#preview-knobs', Static).update(
                    f"[red]Preview failed:[/] {exc}")
            except NoMatches:
                pass


    # ── Phase 8: GeneratePhase ───────────────────────────────────────
    class GeneratePhase(PhaseBase):
        """Run the full generation pipeline in a Worker with live log.

        The worker body is the scientifically-validated version from the
        earlier fix (signatures matched against the current core).  No
        numerical choices are made here — everything has been committed
        by earlier phases and is read via wizard-app attributes.
        """

        title = "Step 8 · Generation"
        subtitle = ("Running the CP2K input-generation pipeline in a "
                    "background thread.  Files appear below as they are "
                    "written.")

        def compose(self) -> 'ComposeResult':
            yield from self._header()
            yield Static("[b]Progress[/]", classes='section-title')
            yield ProgressBar(total=100, id='exec-progress', show_eta=False)
            yield Static("", id='exec-status')
            yield Static("[b]Activity log[/]", classes='section-title')
            yield RichLog(id='exec-log', highlight=True, markup=True, wrap=True)

        def phase_enter(self, app):
            if getattr(self, '_started', False):
                return
            self._started = True
            self._run_generation(app)

        @work(thread=True, exclusive=True, group='generate')
        def _run_generation(self, app):
            """Run the CP2K input-generation pipeline in a worker thread.

            The TUI is a presentation layer: every scientific decision is
            delegated to the same core routines the CLI uses (see main()
            around line 18847 in this file).  Keyword-argument names and
            positional order MUST match the core signatures bit-for-bit —
            otherwise the run fails at the first unrecognised kwarg.

            For a full-fidelity run with provenance records, CHARGE-drift
            verification, spin decision, and residual-charge redistribution,
            users should still invoke the CLI (charmmgui2cp2k.py --no-tui).
            The TUI intentionally omits those audit layers to keep the
            worker simple; the CP2K inputs it emits are identical up to
            those optional artifacts.
            """
            try:
                log = self.query_one('#exec-log', RichLog)
                progress = self.query_one('#exec-progress', ProgressBar)
            except NoMatches:
                return

            def log_msg(prefix, msg):
                self.app.call_from_thread(log.write, f"{prefix} {msg}")

            def set_progress(pct):
                self.app.call_from_thread(setattr, progress, 'progress', pct)

            w = app
            try:
                boundary_charge_scheme = getattr(
                    w, 'boundary_charge_scheme', DEFAULT_BOUNDARY_CHARGE_SCHEME
                )
                links = list(w.links or [])
                qm_indices = list(w.qm_indices)
                qm_elements = dict(w.qm_elements)
                qm_syms = list(qm_elements.keys())
                multiplicity = int(w.multiplicity)
                qm_charge = int(w.qm_charge)
                functional = w.functional
                detected = w.detected_files
                alias_plan = w.alias_plan or build_atom_type_alias_plan(w.topo)
                run_provenance = RunProvenance()

                log_msg("●", "Step 5: Preparing topology variants & exporting coordinates...")
                set_progress(10)

                verify_per_link_boundary_charge_overrides(
                    links,
                    global_scheme=boundary_charge_scheme,
                    interactive=False,
                    run_provenance=run_provenance,
                )
                for link in links:
                    generate_link_charge_directives(link, boundary_charge_scheme)

                m1_set = {
                    int(link.get('MM_INDEX'))
                    for link in links
                    if link.get('MM_INDEX') is not None
                }
                residual_charge_plan = build_residual_charge_plan(
                    qm_indices,
                    w.topo,
                    m1_set=m1_set,
                    redistribute_strategy='uniform',
                    coords=w.coords,
                )
                residual_severity = evaluate_residual_charge_plan_severity(
                    residual_charge_plan
                )
                run_provenance.record(
                    kind='tui_generation_path',
                    severity='info',
                    source='wizard',
                    from_value=None,
                    to_value='Textual TUI',
                    accepted=True,
                    reason='Generation launched from the Textual workbench using committed wizard state.',
                    context={
                        'qm_atoms': len(qm_indices),
                        'link_bonds': len(links),
                        'boundary_charge_scheme': boundary_charge_scheme,
                        'qm_source': getattr(w, 'qm_source_label', ''),
                    },
                )
                if residual_charge_plan:
                    run_provenance.record(
                        kind='residual_charge_redistribution',
                        severity=(
                            'recommendation'
                            if residual_severity['overall_severity'] == 'noticeable'
                            else (
                                'correction'
                                if residual_severity['overall_severity'] == 'severe'
                                else 'info'
                            )
                        ),
                        source='auto',
                        from_value=None,
                        to_value=f"{len(residual_charge_plan)} split residue(s)",
                        accepted=None,
                        reason='Uniform residual-charge redistribution for QM/MM topology generation.',
                        context={
                            'overall_severity': residual_severity['overall_severity'],
                            'max_abs_per_atom_e': residual_severity['max_abs_per_atom_e'],
                            'max_abs_per_residue_e': residual_severity['max_abs_per_residue_e'],
                        },
                    )
                log_msg(
                    "✓",
                    f"Residual charge plan: {len(residual_charge_plan)} split residue(s), "
                    f"severity={residual_severity['overall_severity']}",
                )

                out_dir = os.path.join(
                    w.work_dir,
                    f"cp2k_output_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                )
                os.makedirs(out_dir, exist_ok=True)
                log_msg("✓", f"Output directory: {out_dir}")
                set_progress(20)

                qmmm_charge_override = _apply_residual_charge_plan_to_raw_charges(
                    w.topo.get_float_array('CHARGE'),
                    residual_charge_plan,
                )
                mm_topology_data = collect_topology_variant_data(
                    w.topo, qm_syms, alias_plan=alias_plan,
                )
                qmmm_topology_data = collect_topology_variant_data(
                    w.topo,
                    qm_syms,
                    charge_array_override=qmmm_charge_override,
                    alias_plan=alias_plan,
                )
                log_msg("✓", f"MM topology: {len(mm_topology_data['mm_kinds']) // 3} KINDs")
                log_msg("✓", f"QM/MM topology: {len(qmmm_topology_data['mm_kinds']) // 3} KINDs")
                set_progress(30)

                mm_prmtop_out = os.path.join(out_dir, 'system_mm.prmtop')
                qmmm_prmtop_out = os.path.join(out_dir, 'system_qmmm.prmtop')
                try:
                    patch_lj_and_write(
                        w.topo, mm_prmtop_out,
                        prmtop_path=detected['prmtop'],
                        residual_charge_plan=None, alias_plan=alias_plan,
                    )
                    patch_lj_and_write(
                        w.topo, qmmm_prmtop_out,
                        prmtop_path=detected['prmtop'],
                        residual_charge_plan=residual_charge_plan, alias_plan=alias_plan,
                    )
                    verify_prmtop_charges_match_manifest(
                        qmmm_prmtop_out,
                        w.topo.get_float_array('CHARGE'),
                        residual_charge_plan,
                        label="QM/MM-stage topology",
                    )
                    verify_prmtop_charges_match_manifest(
                        mm_prmtop_out,
                        w.topo.get_float_array('CHARGE'),
                        None,
                        label="MM-stage topology",
                    )
                    write_atom_type_alias_manifest(
                        os.path.join(out_dir, ATOM_TYPE_ALIAS_MANIFEST_BASENAME),
                        detected['prmtop'],
                        [('mm', mm_prmtop_out), ('qmmm', qmmm_prmtop_out)],
                        alias_plan,
                    )
                    log_msg("✓", f"Wrote MM topology: {os.path.basename(mm_prmtop_out)}")
                    log_msg("✓", f"Wrote QM/MM topology: {os.path.basename(qmmm_prmtop_out)}")
                    log_msg("✓", "Verified PRMTOP charges and wrote atom-type alias manifest")
                except Exception as exc:
                    log_msg("✗", f"Topology write failed: {exc}")
                    return

                set_progress(45)
                atomic_numbers = w.topo.get_int_array('ATOMIC_NUMBER') or []
                atom_types = list(w.atom_types or [])
                elems_per_atom = []
                for i in range(len(w.coords)):
                    if i < len(atomic_numbers) and atomic_numbers[i] in ATOMIC_NUM_TO_SYMBOL:
                        elems_per_atom.append(ATOMIC_NUM_TO_SYMBOL[atomic_numbers[i]])
                    elif i < len(atom_types):
                        elems_per_atom.append(w.element_map.get(atom_types[i], 'X'))
                    else:
                        elems_per_atom.append('X')

                xyz_out = os.path.join(out_dir, 'system.xyz')
                n_written = write_xyz(w.coords, elems_per_atom, xyz_out)
                log_msg("✓", f"Wrote {n_written} atoms to {os.path.basename(xyz_out)}")

                try:
                    atom_names = w.topo.get_string_array('ATOM_NAME')
                    residue_labels = w.topo.get_string_array('RESIDUE_LABEL')
                    residue_pointers = w.topo.get_int_array('RESIDUE_POINTER')
                    write_qmmm_boundary_pdbs(
                        coords=w.coords,
                        qm_indices=qm_indices,
                        full_pdb_out_path=os.path.join(out_dir, 'system_qmmm_flag.pdb'),
                        qm_only_pdb_out_path=os.path.join(out_dir, 'system_qm_only.pdb'),
                        elements_per_atom=elems_per_atom,
                        atom_names=atom_names,
                        residue_labels=residue_labels,
                        residue_pointers=residue_pointers,
                    )
                    log_msg("✓", "Wrote QM/MM boundary PDB files")
                except Exception as exc:
                    log_msg("⚠", f"Boundary PDB skipped (non-critical): {exc}")

                set_progress(55)
                log_msg("●", "Step 6: Generating staged CP2K input files...")

                if ensure_link_cap_kind(qm_elements, links, cap_element='H'):
                    log_msg("✓", "Added H KIND for QM/MM link caps")
                qm_kinds_lines, unresolved_qm_gth = generate_qm_kinds(
                    qm_elements, basis_set=w.basis_set, use_admm=w.use_admm,
                )
                if unresolved_qm_gth:
                    log_msg("⚠", f"Unresolved GTH entries for: {sorted(unresolved_qm_gth)}")

                qmmm_periodic_policy = make_qmmm_periodic_policy()
                qm_cell_abc, _qm_cell_meta = compute_qm_cell(
                    qm_indices, w.coords,
                    padding=qmmm_periodic_policy.qm_cell_padding,
                    box_dims=w.box,
                    qmmm_periodic_policy=qmmm_periodic_policy,
                )
                evaluate_qmmm_periodic_electrostatics(
                    qm_cell_abc, qmmm_periodic_policy=qmmm_periodic_policy,
                )

                set_progress(65)

                qm_atom_count = sum(len(v) for v in qm_elements.values())
                rec_profile, _rec_reason = recommended_scf_profile(
                    qm_elements.keys(), functional, qm_atom_count,
                    multiplicity=multiplicity,
                )
                scf_profile_name = rec_profile
                scf_cfg = dict(SCF_PROFILES[rec_profile])
                _scf_diag = should_use_diagonalization_scf(
                    functional, multiplicity, qm_elements, scf_profile_name,
                )

                system_model = make_system_spec(
                    prmtop_file=os.path.basename(qmmm_prmtop_out),
                    xyz_file=os.path.basename(xyz_out),
                    box_dims=w.box,
                    qm_elements=qm_elements,
                    link_bonds=links,
                    qm_kinds_lines=qm_kinds_lines,
                    mm_kinds_lines=mm_topology_data['mm_kinds'],
                    mm_stage_kinds_lines=mm_topology_data['mm_kinds'],
                    qmmm_stage_kinds_lines=qmmm_topology_data['mm_kinds'],
                    mm_prmtop_file=os.path.basename(mm_prmtop_out),
                    qmmm_prmtop_file=os.path.basename(qmmm_prmtop_out),
                    qmmm_periodic_policy=qmmm_periodic_policy,
                    qm_cell_abc=qm_cell_abc,
                    qm_charge=qm_charge,
                    multiplicity=multiplicity,
                    natom=w.topo.natom,
                )
                dft_config = make_dft_config(
                    functional=functional,
                    basis_set=w.basis_set,
                    cutoff=w.cutoff,
                    rel_cutoff=w.rel_cutoff,
                    mgrid_ngrids=w.mgrid_ngrids,
                    use_admm=w.use_admm,
                    scf_profile=scf_profile_name,
                    scf_max_scf=scf_cfg['max_scf'],
                    scf_eps_scf=scf_cfg['eps_scf'],
                    scf_guess=scf_cfg['scf_guess'],
                    scf_cholesky=scf_cfg.get('cholesky'),
                    qs_eps_default=scf_cfg.get('qs_eps_default'),
                    scf_added_mos=scf_cfg['added_mos'],
                    scf_mixing_method=scf_cfg['mixing_method'],
                    scf_mixing_alpha=scf_cfg['mixing_alpha'],
                    scf_nbroyden=scf_cfg['nbroyden'],
                    outer_max_scf=scf_cfg['outer_max_scf'],
                    outer_eps_scf=scf_cfg['outer_eps_scf'],
                    qmmm_geep_lib=w.geep_lib,
                    boundary_charge_scheme=boundary_charge_scheme,
                    qm_elements_for_admm=qm_elements,
                    qm_kinds_lines_for_admm=qm_kinds_lines,
                )
                handoff_policy = make_qmmm_handoff_policy(
                    mode=getattr(w, 'handoff_policy_mode', None)
                )
                workflow_config = make_workflow_config(
                    production_steps=w.md_steps,
                    production_timestep=w.md_timestep,
                    production_temperature=w.md_temperature,
                    production_ensemble=w.md_ensemble,
                    em_max_iter=getattr(w, 'em_max_iter', 2000),
                    mm_nvt_steps=getattr(w, 'mm_nvt_steps', 5000),
                    mm_npt_steps=getattr(w, 'mm_npt_steps', 10000),
                    mm_timestep=1.0,
                    enable_qmmm_warmup=getattr(w, 'enable_warmup', True),
                    qmmm_handoff_policy=handoff_policy,
                    restraint_indices=list(qm_indices),
                )
                set_progress(75)
                stage_inputs, stage_meta = assemble_staged_cp2k_workflow(
                    system_model, dft_config, workflow_config,
                )
                stage_input_names = list(stage_inputs.keys())
                for stage_name, stage_content in stage_inputs.items():
                    with open(os.path.join(out_dir, stage_name), 'w') as f:
                        f.write(stage_content)
                    log_msg("✓", f"Wrote: {stage_name}")
                set_progress(85)

                log_msg("●", "Step 7: Preparing execution wrapper...")
                default_stage_input = (
                    stage_input_names[0] if stage_input_names else "10_em_mm.inp"
                )
                wrapper_log_default = (
                    f"{os.path.splitext(default_stage_input)[0]}.log"
                )
                try:
                    hardware_info = detect_local_hardware()
                    cp2k_install = detect_cp2k_installation(probe_version=True)
                    launch_cfg = recommend_cp2k_launch_settings(
                        hardware_info, cp2k_install,
                    )
                    wrapper_path = os.path.join(out_dir, 'run_qmmm_project.sh')
                    write_cp2k_execution_wrapper(
                        wrapper_path=wrapper_path,
                        input_filename=default_stage_input,
                        log_filename=wrapper_log_default,
                        launch_cfg=launch_cfg,
                        hardware_info=hardware_info,
                        cp2k_info=cp2k_install,
                        detection_enabled=True,
                        stage_inputs=stage_inputs,
                        stage_meta=stage_meta,
                    )
                    log_msg("✓", f"Wrote: {os.path.basename(wrapper_path)}")
                except Exception as exc:
                    log_msg("⚠", f"Wrapper generation warning: {exc}")
                    wrapper_path = os.path.join(out_dir, 'run_qmmm_project.sh')
                    launch_cfg = {'cp2k_binary': None}
                set_progress(90)

                try:
                    readme_path = os.path.join(out_dir, 'README_next_steps.txt')
                    write_readme_next_steps(
                        out_path=readme_path,
                        wrapper_filename=os.path.basename(wrapper_path),
                        stage_meta=stage_meta,
                        cp2k_binary=launch_cfg.get('cp2k_binary'),
                    )
                    log_msg("✓", f"Wrote: {os.path.basename(readme_path)}")
                except Exception as exc:
                    log_msg("⚠", f"README generation warning: {exc}")
                set_progress(95)

                try:
                    spin_decision = recommend_qm_spin_state(
                        qm_elements=qm_elements,
                        qm_charge=qm_charge,
                        link_bonds=links,
                        user_multiplicity=multiplicity,
                        mdin_meta=getattr(w, 'mdin_meta', {}),
                    )
                    _, qm_meta = estimate_qm_electrons_for_spin(
                        qm_elements=qm_elements, qm_charge=qm_charge,
                        link_bonds=links,
                    )
                    write_electronic_state_dat(
                        out_path=os.path.join(out_dir, 'electronic_state.dat'),
                        qm_meta=qm_meta,
                        qm_charge=qm_charge,
                        multiplicity=multiplicity,
                        spin_decision=spin_decision,
                    )
                    log_msg("✓", "Wrote: electronic_state.dat")
                except Exception as exc:
                    log_msg("⚠", f"Electronic state file warning: {exc}")
                try:
                    bc_meta = write_boundary_charges_audit(
                        out_dir=out_dir,
                        link_bonds=links,
                        residual_charge_plan=residual_charge_plan,
                        boundary_charge_scheme=boundary_charge_scheme,
                        topo=w.topo,
                    )
                    log_msg(
                        "✓",
                        "Wrote boundary charge audit: "
                        f"{os.path.basename(bc_meta['json_path'])} / "
                        f"{os.path.basename(bc_meta['dat_path'])}",
                    )
                except Exception as exc:
                    log_msg("⚠", f"Boundary charge audit warning: {exc}")
                try:
                    provenance_path = os.path.join(out_dir, 'run_provenance.txt')
                    run_provenance.write_file(
                        provenance_path,
                        header_lines=(
                            f"source=TUI",
                            f"work_dir={w.work_dir}",
                            f"qm_charge={qm_charge}",
                            f"multiplicity={multiplicity}",
                        ),
                    )
                    log_msg("✓", "Wrote: run_provenance.txt")
                except Exception as exc:
                    log_msg("⚠", f"Provenance warning: {exc}")
                set_progress(100)

                log_msg("━" * 60, "")
                log_msg("✓", f"All files written to: {out_dir}")
                log_msg("✓", "Run: ./run_qmmm_project.sh --auto-chain")

                try:
                    self.app.call_from_thread(
                        self.query_one('#exec-status', Static).update,
                        "[$success b]✓ Generation complete.[/]  "
                        "Press [b]Ctrl-Q[/] to exit.",
                    )
                except NoMatches:
                    pass

            except Exception as exc:
                log_msg("✗", f"FATAL: {exc}")
                import traceback
                for line in traceback.format_exc().splitlines():
                    log_msg("  ", line)


    # ── WorkbenchScreen (single full-screen host) ────────────────────
    class WorkbenchScreen(Screen):
        """The only Screen the App ever mounts.

        It owns the persistent frame (TopBar / Breadcrumb / Sidebar /
        Tray / FooterBar) and a ContentSwitcher that selects one of
        the eight PhaseBase subclasses.  Back/Next delegate to the
        currently-visible phase's commit() and then swap which phase
        the ContentSwitcher is showing.
        """

        BINDINGS = [
            Binding("ctrl+q", "quit", "Quit", show=True, priority=True),
            Binding("f1", "toggle_help", "Help", show=True),
            Binding("ctrl+n", "next", "Next", show=True),
            Binding("ctrl+p", "back", "Back", show=True),
            Binding("ctrl+right", "next", "Next", show=False),
            Binding("ctrl+left",  "back", "Back", show=False),
        ]

        def __init__(self, wizard_app):
            super().__init__()
            self.wizard_app = wizard_app
            self.current_index = 0

        def compose(self) -> 'ComposeResult':
            yield TopBar(self.wizard_app.work_dir)
            yield PhaseBreadcrumb()
            if not getattr(self.wizard_app, 'compact_mode', False):
                yield SystemSummary()
            with ContentSwitcher(initial='system', id='host'):
                yield SystemPhase(id='system')
                yield QMPhase(id='qm')
                yield BoundaryPhase(id='boundary')
                yield MethodPhase(id='method')
                yield ElectronicPhase(id='electronic')
                yield WorkflowPhase(id='workflow')
                yield PreviewPhase(id='preview')
                yield GeneratePhase(id='generate')
            yield ValidationTray()
            yield FooterBar()

        def on_mount(self):
            self._enter_phase(0)

        # ── Navigation ────────────────────────────────────────────
        def _enter_phase(self, index: int) -> None:
            index = max(0, min(index, len(PHASE_ORDER) - 1))
            self.current_index = index
            phase_id, _label = PHASE_ORDER[index]
            switcher = self.query_one(ContentSwitcher)
            switcher.current = phase_id
            # Tell the incoming phase to refresh itself.
            phase = self.query_one(f'#{phase_id}', PhaseBase)
            try:
                phase.phase_enter(self.wizard_app)
            except Exception as exc:
                self.wizard_app.validation_records.append(
                    ('error', f"phase '{phase_id}' phase_enter: {exc}")
                )
            # Update footer button label for preview → generate / last phase.
            self._set_next_button_label()
            self.refresh_state_ui()

        def _set_next_button_label(self) -> None:
            try:
                nxt = self.query_one('#btn-next', Button)
            except NoMatches:
                return
            phase_id, _ = PHASE_ORDER[self.current_index]
            if phase_id == 'preview':
                nxt.label = (
                    "Generate"
                    if getattr(self.wizard_app, 'compat_mode', False)
                    else "Generate ⚡"
                )
                nxt.variant = 'warning'
            elif phase_id == 'generate':
                nxt.label = "Quit"
                nxt.variant = 'default'
            else:
                nxt.label = (
                    "Next"
                    if getattr(self.wizard_app, 'compat_mode', False)
                    else "Next →"
                )
                nxt.variant = 'primary'

        def refresh_state_ui(self) -> None:
            """Re-render every frame widget that reads wizard state."""
            try:
                self.query_one(PhaseBreadcrumb).set_current(self.current_index)
            except NoMatches:
                pass
            try:
                self.query_one(SystemSummary).refresh_from_app(self.wizard_app)
            except NoMatches:
                pass
            try:
                self.query_one(ValidationTray).refresh_from_app(self.wizard_app)
            except NoMatches:
                pass
            try:
                hint = self.query_one('#footbar-hint', Static)
                if getattr(self.wizard_app, 'compat_mode', False):
                    hint.update(
                        "screen-safe: Tab/Enter buttons · Ctrl-N next · Ctrl-P back · Ctrl-Q quit"
                    )
                else:
                    hint.update(
                        "Tab/Enter buttons · Ctrl-N next · Ctrl-P back · Ctrl-Q quit"
                    )
            except NoMatches:
                pass

        # ── Button handlers ───────────────────────────────────────
        @on(Button.Pressed, '#btn-next')
        def action_next(self, _ev=None):
            phase_id, _ = PHASE_ORDER[self.current_index]
            # The last phase's Next is a quit-quit.
            if phase_id == 'generate':
                self.app.exit(); return
            # Run the outgoing phase's commit() + validate() before advancing.
            try:
                outgoing = self.query_one(f'#{phase_id}', PhaseBase)
                outgoing.commit(self.wizard_app)
                ok, issues = outgoing.validate(self.wizard_app)
            except NoMatches:
                ok, issues = True, []
            if not ok:
                for msg in issues:
                    self.app.notify(msg, severity='warning', timeout=6)
                    self.wizard_app.validation_records.append(('warn', msg))
                self.refresh_state_ui()
                return
            self._enter_phase(self.current_index + 1)

        @on(Button.Pressed, '#btn-back')
        def action_back(self, _ev=None):
            if self.current_index == 0:
                return
            self._enter_phase(self.current_index - 1)

        def action_toggle_help(self) -> None:
            self.app.notify(
                "Tab/Shift-Tab between controls · Enter to confirm · "
                "Ctrl-N/Ctrl-P to walk phases · Ctrl-Q to quit.",
                title="Keyboard", timeout=8,
            )


    # ── The Textual Application ──────────────────────────────────────
    class CharmmGui2Cp2kApp(App):
        """Textual TUI for the CHARMM-GUI → CP2K QM/MM pipeline.

        The App holds wizard state as plain attributes with names
        identical to the CLI wizard's locals, so the scientific core
        reads from a single source of truth whether invoked from the
        TUI or the batch path.

        Design references:
            • Textual App docs — https://textual.textualize.io/guide/app/
            • Workers          — https://textual.textualize.io/guide/workers/
        """

        CSS = _TUI_CSS
        TITLE = "charmmgui2cp2k"
        SUB_TITLE = "CHARMM-GUI → CP2K QM/MM workbench"

        BINDINGS = [
            Binding("ctrl+q", "quit", "Quit", show=True, priority=True),
            Binding("f1", "toggle_help", "Help", show=True),
        ]

        def __init__(
            self,
            work_dir='.',
            args=None,
            compact_mode=False,
            compat_mode=False,
            terminal_profile=None,
        ):
            super().__init__()
            # ── Wizard state (names match the CLI wizard verbatim) ───
            self.work_dir = os.path.abspath(work_dir)
            self.cli_args = args
            self.compact_mode = bool(compact_mode)
            self.compat_mode = bool(compat_mode)
            self.terminal_profile = dict(terminal_profile or {})
            self.detected_files = {}
            self.topo = None
            self.coords = None
            self.box = None
            self.element_map = {}
            self.unresolved_types = []
            self.alias_plan = None
            self.atom_types = []
            self.qm_elements = {}
            self.qm_indices = []
            self.mdin_meta = {}
            self.qm_source_label = ""
            self.links = []
            self.adjacency = {}
            self.boundary_detection_done = False
            self.boundary_charge_scheme = DEFAULT_BOUNDARY_CHARGE_SCHEME
            self.qm_charge = 0
            self.multiplicity = 1
            self.multiplicity_user_set = False
            self.spin_decision = {}
            self.functional = 'B3LYP'
            self.basis_set = 'DZVP-MOLOPT-GTH'
            self.use_admm = True
            self.cutoff = 500.0
            self.rel_cutoff = 60.0
            self.mgrid_ngrids = 5
            self.geep_lib = DEFAULT_QMMM_GEEP_LIB
            self.md_steps = 100000
            self.md_timestep = 0.5
            self.md_temperature = 300.0
            self.md_ensemble = 'NVT'
            self.handoff_policy_mode = 'RESET_DYNAMICS'
            self.enable_warmup = True
            self.em_max_iter = 2000
            self.mm_nvt_steps = 5000
            self.mm_npt_steps = 10000
            # ── Cross-phase validation tray ───────────────────────
            # Each entry is (severity, message) where severity ∈
            # {'ok','warn','error'}.  Every phase that surfaces a
            # concern appends here; ValidationTray renders the tail.
            self.validation_records = []

        def on_mount(self):
            self.push_screen(WorkbenchScreen(self))

        def action_toggle_help(self):
            self.notify(
                "Tab/Shift-Tab between controls · Enter to confirm · "
                "Ctrl-N/Ctrl-P to walk phases · Ctrl-Q to quit.",
                title="Keyboard", timeout=8,
            )

# ─── End Textual TUI ────────────────────────────────────────────────────────


# ─── Main CLI Wizard ─────────────────────────────────────────────────────────

def _main_cli_wizard():
    """Original interactive CLI wizard — the production-proven fallback.

    This function contains the complete 8-step wizard with ask_*/print-based
    I/O.  It is invoked when:
      - Textual is unavailable (Python <3.9 or textual not installed)
      - The user passes --no-tui
      - The terminal is not a TTY
      - --non-interactive is set (batch mode, no prompts at all)

    When the Textual TUI is requested instead, the dispatch function main()
    launches CharmmGui2Cp2kApp, which drives the same scientific core
    through Screens instead of sequential ask_* calls.
    """
    parser = argparse.ArgumentParser(
        description="CHARMM-GUI → CP2K QM/MM Input Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dir', default='.', help='Input directory containing CHARMM-GUI outputs')
    parser.add_argument('--dry-run', action='store_true', help='Validate only, do not write files')
    parser.add_argument('--non-interactive', action='store_true', help='Use all defaults without prompting')
    parser.add_argument(
        '--sampling-spec',
        default=None,
        help='External JSON/YAML specification for advanced free-energy sampling (metadynamics or umbrella)',
    )
    parser.add_argument(
        '--functional',
        default='B3LYP',
        help='QM DFT functional (B3LYP, PBE0, or PBE)',
    )
    parser.add_argument(
        '--cutoff',
        type=float,
        default=500.0,
        help='CP2K MGRID CUTOFF [Ry]',
    )
    parser.add_argument(
        '--rel-cutoff',
        type=float,
        default=60.0,
        help='CP2K MGRID REL_CUTOFF [Ry]',
    )
    parser.add_argument(
        '--ngrids',
        type=int,
        default=None,
        help='CP2K MGRID NGRIDS override (default: 5 for standard MOLOPT, else 4)',
    )
    parser.add_argument(
        '--basis-set',
        default='DZVP-MOLOPT-GTH',
        help='QM orbital basis set label for QM KIND blocks',
    )
    parser.add_argument(
        '--geep-lib',
        type=int,
        default=DEFAULT_QMMM_GEEP_LIB,
        help='CP2K USE_GEEP_LIB count for &QMMM ECOUPL GAUSS (default: 9)',
    )
    parser.add_argument(
        '--admm-aux-basis',
        default=None,
        help='ADMM auxiliary basis label for AUX_FIT (cpFIT3, cFIT3, admm-dzp)',
    )
    parser.add_argument(
        '--admm-exch-correction',
        default=None,
        help='ADMM EXCH_CORRECTION_FUNC override for hybrid ADMM runs (BECKE88X or PBEX)',
    )
    parser.add_argument(
        '--hf-max-memory',
        type=int,
        default=None,
        help=(
            'CP2K HF/MEMORY/MAX_MEMORY for hybrid-functional HFX, per MPI rank '
            f'(default: {DEFAULT_HF_MAX_MEMORY}; conservative, explicit, not whole-job memory)'
        ),
    )
    parser.add_argument(
        '--ot-stepsize-mode',
        default=None,
        help=(
            'OT STEPSIZE policy (AUTO or MANUAL). AUTO emits STEPSIZE -1.0 so CP2K '
            'chooses the preconditioner-dependent initial line-search step.'
        ),
    )
    parser.add_argument(
        '--ot-stepsize',
        type=float,
        default=None,
        help=(
            'Explicit OT STEPSIZE initial line-search step. '
            'Providing this without --ot-stepsize-mode implies MANUAL.'
        ),
    )
    parser.add_argument(
        '--qm-cell-padding',
        type=float,
        default=None,
        help=(
            'Target isotropic QM-cell padding [angstrom] for periodic QM/MM '
            f'(default: {DEFAULT_QMMM_QM_CELL_PADDING}; linked with MULTIPOLE RCUT policy)'
        ),
    )
    parser.add_argument(
        '--qmmm-multipole-rcut',
        type=float,
        default=None,
        help=(
            'Target &QMMM/&PERIODIC/&MULTIPOLE RCUT [angstrom] '
            f'(default: {DEFAULT_QMMM_TARGET_MULTIPOLE_RCUT}; effective RCUT may be reduced if the QM cell is box-limited)'
        ),
    )
    parser.add_argument(
        '--mm-scale14-policy',
        default=None,
        help=(
            'MM 1-4 scaling policy for CP2K FORCEFIELD '
            '(AMBER_RECOMMENDED, CP2K_EXPLICIT, MANUAL_OVERRIDE)'
        ),
    )
    parser.add_argument(
        '--mm-ei-scale14',
        type=float,
        default=None,
        help='Explicit CP2K EI_SCALE14 override for expert/manual MM 1-4 scaling',
    )
    parser.add_argument(
        '--mm-vdw-scale14',
        type=float,
        default=None,
        help='Explicit CP2K VDW_SCALE14 override for expert/manual MM 1-4 scaling',
    )
    parser.add_argument(
        '--use-admm',
        dest='use_admm',
        action='store_true',
        help='Enable ADMM acceleration and AUX_FIT basis lines',
    )
    parser.add_argument(
        '--no-admm',
        dest='use_admm',
        action='store_false',
        help='Disable ADMM acceleration',
    )
    # ── ADMM coverage-verification controls ─────────────────────────────────
    # ADMM requires an auxiliary basis that covers every element present in
    # the QM region (Guidon, Hutter, VandeVondele, JCTC 6, 2348 (2010)).  A
    # silently-missing Kind will only surface as a cryptic CP2K runtime error
    # after SCF initialisation.  The default coverage gate refuses to enable
    # ADMM when the curated pin (optionally widened by a scan of CP2K's
    # BASIS_ADMM* file) does not list every QM element.  --admm-allow-unverified
    # is an expert override for users who vouch for their local CP2K install
    # shipping the required ADMM fits; --cp2k-data-dir lets the scan read
    # the actual basis file on disk (optional — defaults to $CP2K_DATA_DIR or
    # the built-in curated pin only).
    parser.add_argument(
        '--admm-allow-unverified',
        dest='admm_allow_unverified',
        action='store_true',
        help=('Expert override: keep ADMM enabled even when the auxiliary '
              'basis coverage for one or more QM elements cannot be verified '
              'against the curated pin or the shipped CP2K basis file. '
              'Use only when you have confirmed locally that BASIS_ADMM* '
              'contains entries for every QM Kind.'),
    )
    parser.add_argument(
        '--cp2k-data-dir',
        dest='cp2k_data_dir',
        default=None,
        help=('Path to the CP2K data/ directory holding BASIS_ADMM / '
              'BASIS_ADMM_MOLOPT.  When provided, the ADMM coverage check '
              'opportunistically widens the curated element pin with any '
              'element symbols actually declared in the shipped basis file. '
              'Defaults to the $CP2K_DATA_DIR environment variable if set.'),
    )
    # ── QM/MM verbose diagnostics (S9) ──────────────────────────────────
    # Injects &PRINT/&PROGRAM_RUN_INFO HIGH and &PRINT/&GRID_INFORMATION into
    # the &QMMM block of the 35_qmmm_warmup stage only, so the user can
    # verify the effective multipole RCUT and GEEP grid depth without
    # re-reading the emitted input.  Disabled by default to keep the
    # log volume of production stages manageable.
    parser.add_argument(
        '--qmmm-verbose-diagnostics',
        dest='qmmm_verbose_diagnostics',
        action='store_true',
        help=('Enable &PROGRAM_RUN_INFO and &GRID_INFORMATION for the '
              '35_qmmm_warmup QM/MM warmup stage only.  Use on first runs '
              'to verify the effective &QMMM/&PERIODIC multipole RCUT and '
              'the GEEP library depth that CP2K actually applies.'),
    )
    parser.add_argument(
        '--qmmm-warmup',
        dest='enable_qmmm_warmup',
        action='store_true',
        help='Enable 35_qmmm_warmup.inp stage (default)',
    )
    parser.add_argument(
        '--no-qmmm-warmup',
        dest='enable_qmmm_warmup',
        action='store_false',
        help='Disable 35_qmmm_warmup.inp and hand off directly from 30_npt_mm to 40_qmmm_md',
    )
    parser.add_argument(
        '--qmmm-handoff-policy',
        default=None,
        help=(
            'MM->QM/MM handoff policy for the first QM/MM stage '
            '(RESET_DYNAMICS, REUSE_VELOCITIES, FULL_STATE_CONTINUITY). '
            'Recommended default is RESET_DYNAMICS.'
        ),
    )
    parser.add_argument(
        '--handoff-velocities',
        dest='handoff_velocities',
        action='store_true',
        help='Legacy alias for --qmmm-handoff-policy REUSE_VELOCITIES',
    )
    parser.add_argument(
        '--qmmm-transition-thermostat-timecon',
        type=float,
        default=DEFAULT_QMMM_TRANSITION_THERMOSTAT_TIMECON_FS,
        help=(
            'CSVR TIMECON [fs] for the first QM/MM stage when thermostat state is reset '
            f'(pipeline transition default: {DEFAULT_QMMM_TRANSITION_THERMOSTAT_TIMECON_FS:g} fs)'
        ),
    )
    parser.add_argument(
        '--qmmm-transition-seed',
        type=int,
        default=DEFAULT_QMMM_TRANSITION_SEED,
        help=(
            'Explicit GLOBAL SEED for the first QM/MM stage when RNG/velocity initialization is reset '
            f'(pipeline transition default: {DEFAULT_QMMM_TRANSITION_SEED})'
        ),
    )
    parser.add_argument(
        '--no-qmmm-transition-seed',
        dest='qmmm_transition_seed',
        action='store_const',
        const=None,
        help='Disable explicit GLOBAL SEED emission for the first QM/MM stage',
    )
    parser.add_argument(
        '--stateless-restart',
        dest='stateless_restart',
        action='store_true',
        help='EXPERT: disable restart of counters/thermostat/barostat/random generator state across stages',
    )
    parser.add_argument(
        '--mm-active-site-restraints',
        action='store_true',
        help='Fix QM-region atoms during 20_nvt_mm and 30_npt_mm stages',
    )
    parser.add_argument(
        '--qmmm-warmup-restraints',
        dest='qmmm_warmup_restraints',
        action='store_true',
        help='Fix QM-region atoms during 35_qmmm_warmup',
    )
    parser.add_argument(
        '--no-qmmm-warmup-restraints',
        dest='qmmm_warmup_restraints',
        action='store_false',
        help='Disable fixed-atom restraints in 35_qmmm_warmup',
    )
    parser.add_argument('--em-max-iter', type=int, default=2000, help='10_em_mm GEO_OPT MAX_ITER')
    parser.add_argument('--mm-nvt-steps', type=int, default=5000, help='20_nvt_mm MD steps')
    parser.add_argument('--mm-npt-steps', type=int, default=10000, help='30_npt_mm MD steps')
    parser.add_argument('--mm-timestep', type=float, default=1.0, help='MM equilibration timestep [fs]')
    parser.add_argument('--warmup-steps', type=int, default=2000, help='35_qmmm_warmup MD steps')
    parser.add_argument('--warmup-timestep', type=float, default=0.25, help='35_qmmm_warmup timestep [fs]')
    parser.add_argument('--warmup-ensemble', type=str, default='NVT',
                        choices=['NVT', 'NPT_F', 'NPT_I'],
                        help='35_qmmm_warmup ensemble (NVT recommended; NPT for expert use)')
    parser.add_argument(
        '--hardware-aware',
        dest='hardware_aware',
        action='store_true',
        help='Auto-detect local hardware/CP2K installation for execution wrapper tuning',
    )
    parser.add_argument(
        '--no-hardware-aware',
        dest='hardware_aware',
        action='store_false',
        help='Skip hardware/CP2K probing and use conservative wrapper defaults',
    )
    # ── V8: CP2K version-gate overrides ──────────────────────────────────
    # Two escape hatches for the two-tier gate emitted by the wrapper (V2):
    #
    #   --cp2k-min-version X.Y
    #       Tighten or loosen the *hard* floor baked into the wrapper.
    #       The default reflects CP2K_VERSION_FLOOR_HARD (currently 7.1)
    #       — every non-optional emitted keyword is documented stable at
    #       that version.  Downgrading below the default is an advanced,
    #       user-owned choice; the wrapper still prints the detected
    #       version so CI logs remain auditable.
    #
    #   --cp2k-skip-version-check
    #       Bypass the gate entirely.  Equivalent to setting the
    #       CP2K_SKIP_VERSION_CHECK=1 environment variable at runtime.
    #       Both forms are honored; the env var can always be unset to
    #       re-enable the check without regenerating the wrapper.
    #
    # These CLI overrides do NOT change the Python capability resolution
    # (that stays anchored in the probed version) so substitutions and
    # compat reporting remain accurate regardless of override state.
    parser.add_argument(
        '--cp2k-min-version',
        dest='cp2k_min_version',
        default=None,
        help=(
            'Override the CP2K hard-floor (default: '
            f'{CP2K_VERSION_FLOOR_HARD[0]}.{CP2K_VERSION_FLOOR_HARD[1]}). '
            'Accepts X.Y or X.Y.Z; affects both the wrapper gate and the '
            'Python capability floor used by compat reporting.'
        ),
    )
    parser.add_argument(
        '--cp2k-skip-version-check',
        dest='cp2k_skip_version_check',
        action='store_true',
        default=False,
        help=(
            'Bake CP2K_SKIP_VERSION_CHECK=1 into the generated wrapper so '
            'the runtime gate is bypassed.  Advanced; recorded in the compat '
            'report for auditability.'
        ),
    )
    # ── V7: opt-in generator-time parser validation ──────────────────────
    # After emitting stage inputs, invoke ``cp2k --input-check <file>`` on
    # each to confirm it parses under the resident CP2K build.  The option
    # has been stable since CP2K 6.1; see CP2K manual, §1.2 (Command-line
    # options).  Off by default because it requires CP2K on PATH at
    # generation time (which is not always the case in CI pipelines that
    # build inputs on a controller then ship them to compute nodes).
    parser.add_argument(
        '--cp2k-input-check',
        dest='cp2k_input_check',
        choices=['off', 'warn', 'strict'],
        default='off',
        help=(
            'Post-generation parser validation of each stage input using '
            '`cp2k --input-check` (CP2K >= 6.1). '
            '"off" skips the probe (default); "warn" runs the probe and '
            'reports failures as warnings; "strict" makes any failure abort '
            'generation with a nonzero exit.'
        ),
    )
    parser.add_argument(
        '--scf-profile',
        dest='scf_profile',
        default=None,
        help=(
            'Override the auto-selected SCF profile. Useful for non-interactive '
            'runs that should accept a documented recommendation such as '
            'ORGANIC_RADICAL_DIAG.'
        ),
    )
    parser.add_argument(
        '--scf-guess',
        dest='scf_guess',
        default=None,
        help=(
            'Override CP2K SCF_GUESS (ATOMIC, RESTART, MOPAC, CORE). '
            'Useful for open-shell or difficult QM/MM starts.'
        ),
    )
    parser.add_argument(
        '--dispersion-scheme',
        dest='dispersion_scheme',
        default=None,
        help='Override dispersion correction scheme (DFTD3_BJ, DFTD4, or NONE).',
    )
    parser.set_defaults(
        hardware_aware=None,
        use_admm=None,
        enable_qmmm_warmup=True,
        handoff_velocities=None,
        stateless_restart=False,
        qmmm_warmup_restraints=None,
    )
    parser.add_argument('--multiplicity', type=int, default=None, help='QM multiplicity (2S+1)')
    args = parser.parse_args()
    try:
        dft_cfg = resolve_dft_qm_settings(
            functional=args.functional,
            cutoff=args.cutoff,
            rel_cutoff=args.rel_cutoff,
            use_admm=(True if args.use_admm is None else bool(args.use_admm)),
            basis_set=args.basis_set,
            ngrids=args.ngrids,
        )
    except ValueError as exc:
        parser.error(str(exc))
    try:
        qmmm_geep_lib = validate_qmmm_geep_lib(args.geep_lib)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        admm_aux_basis = normalize_admm_aux_basis(args.admm_aux_basis)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        admm_exch_correction_func = normalize_admm_exch_correction_func(args.admm_exch_correction)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        hf_max_memory = validate_hf_max_memory(args.hf_max_memory)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        ot_stepsize_policy = make_ot_stepsize_policy(
            mode=args.ot_stepsize_mode,
            stepsize=args.ot_stepsize,
            ot_preconditioner=DEFAULT_OT_PRECONDITIONER,
        )
    except ValueError as exc:
        parser.error(str(exc))
    try:
        scf_profile_override = (
            _validate_scf_profile_key(args.scf_profile)
            if args.scf_profile is not None
            else None
        )
    except ValueError as exc:
        parser.error(str(exc))
    try:
        scf_guess_override = (
            validate_scf_guess(args.scf_guess)
            if args.scf_guess is not None
            else None
        )
    except ValueError as exc:
        parser.error(str(exc))
    try:
        dispersion_scheme_override = (
            _validate_dispersion_scheme(args.dispersion_scheme)
            if args.dispersion_scheme is not None
            else None
        )
    except ValueError as exc:
        parser.error(str(exc))
    try:
        requested_qmmm_handoff_policy = make_qmmm_handoff_policy(
            mode=args.qmmm_handoff_policy,
            handoff_restart_velocities=args.handoff_velocities,
        )
    except ValueError as exc:
        parser.error(str(exc))
    try:
        requested_qmmm_transition_timecon = validate_md_timecon(
            args.qmmm_transition_thermostat_timecon,
            "First QM/MM-stage thermostat TIMECON",
        )
    except ValueError as exc:
        parser.error(str(exc))
    try:
        requested_qmmm_transition_seed = validate_global_seed(
            args.qmmm_transition_seed,
            "First QM/MM-stage GLOBAL SEED",
        )
    except ValueError as exc:
        parser.error(str(exc))
    try:
        qmmm_periodic_policy = make_qmmm_periodic_policy(
            qm_cell_padding=(
                DEFAULT_QMMM_QM_CELL_PADDING
                if args.qm_cell_padding is None
                else args.qm_cell_padding
            ),
            target_multipole_rcut=(
                DEFAULT_QMMM_TARGET_MULTIPOLE_RCUT
                if args.qmmm_multipole_rcut is None
                else args.qmmm_multipole_rcut
            ),
        )
    except ValueError as exc:
        parser.error(str(exc))
    try:
        requested_mm_scale14_policy = resolve_mm_scale14_policy(
            args.mm_scale14_policy,
            ei_scale14=args.mm_ei_scale14,
            vdw_scale14=args.mm_vdw_scale14,
        )
    except ValueError as exc:
        parser.error(str(exc))
    if args.em_max_iter < 1:
        parser.error("--em-max-iter must be >= 1")
    if args.mm_nvt_steps < 1:
        parser.error("--mm-nvt-steps must be >= 1")
    if args.mm_npt_steps < 1:
        parser.error("--mm-npt-steps must be >= 1")
    if args.mm_timestep <= 0:
        parser.error("--mm-timestep must be > 0")
    if args.warmup_steps < 1:
        parser.error("--warmup-steps must be >= 1")
    if args.warmup_timestep <= 0:
        parser.error("--warmup-timestep must be > 0")

    interactive = not args.non_interactive
    dry_run = args.dry_run

    # ── V10: version-gate coherence self-check ───────────────────────────
    # Run before any emission so any drift between CP2K_KEYWORD_MIN_VERSION,
    # CP2K_VERSION_FLOOR_HARD, and CP2K_VERSION_FLOOR_SOFT aborts early with
    # a clear message.  Raises AssertionError on violation; we let it
    # propagate so CI/developer feedback is immediate.
    assert_version_gate_coherence()

    # ── V3/V6/V8: CP2K capability snapshot (authoritative, session-wide) ─
    # Probe the resident CP2K executable once, immediately after argument
    # validation, so every downstream emitter (ADMM resolver, input writer,
    # wrapper generator, compat-report writer) consumes the same frozen
    # ResolvedCP2KCapability view.  Probing here — before `banner()` and
    # before any heavy I/O — keeps the code path cheap when the binary is
    # absent (query_cp2k_version returns (None, "") and we simply fall
    # back to permissive capability flags), and guarantees that V4
    # admm-dzp→cpFIT3 substitution (JCTC 6, 2348, 2010; cpFIT3 stable
    # since CP2K 5.1) fires at the correct moment.  See CP2K_KEYWORD_
    # MIN_VERSION above for the per-keyword floor matrix.
    #
    # V8: when the user passed --cp2k-min-version X.Y, we parse it and
    # use the override as the hard floor for *both* the capability
    # snapshot and the bash wrapper, keeping the two in lock-step.  An
    # unparseable override is an early hard error (argparse-level) so
    # downstream code never has to defend against malformed input.
    _cli_min_version = getattr(args, 'cp2k_min_version', None)
    if _cli_min_version:
        _parsed_floor = parse_cp2k_version_string(str(_cli_min_version))
        if _parsed_floor is None:
            parser.error(
                f"--cp2k-min-version '{_cli_min_version}' is not a valid "
                "CP2K version string (expected X.Y or X.Y.Z)."
            )
        _effective_floor_hard = _parsed_floor[:2]
    else:
        _effective_floor_hard = CP2K_VERSION_FLOOR_HARD
    _early_cp2k_install = detect_cp2k_installation(probe_version=True)
    cp2k_capability = build_cp2k_capability(
        _early_cp2k_install.get('version'),
        _early_cp2k_install.get('version_line', ''),
        floor_hard=_effective_floor_hard,
    )
    # Accumulator for any V4-style feature substitutions.  Each entry is
    # a dict {'keyword': ..., 'requested': ..., 'substituted': ...,
    # 'reason': ...} that will be rendered by write_cp2k_compat_report().
    admm_substitutions_log = []
    # ── Unified run-provenance accumulator (F.1.a) ──────────────────────
    # Single sink for every non-default decision recorded across the
    # run.  Persisted to ``run_provenance.txt`` alongside the CP2K input
    # so reproducing or auditing this run does not require re-walking
    # the wizard interactively.
    run_provenance = RunProvenance()

    # ── F.2.a: Up-front non-interactive policy notice ────────────────────
    # When --non-interactive is in effect, the pipeline cannot prompt the
    # user to confirm decisions that would otherwise surface as
    # interactive recommendations.  Per project policy
    # (feedback_no_silent_modifications), the script *never* silently
    # rewrites a user-supplied configuration: recommendation-grade
    # findings are emitted as WARN and the original configuration is
    # preserved; correction-grade findings (settings CP2K will reject
    # outright, e.g. OT + UKS) WARN and then hard-exit so the user can
    # rerun interactively or pre-set the correct value.  We emit this
    # notice once, up-front, so users know exactly what to scan for in
    # the resulting run_provenance.txt and stderr stream.  Recording it
    # in the manifest makes it self-evident from the audit file alone
    # which policy regime governed the run.
    if not interactive:
        warn(
            "Non-interactive mode is active (--non-interactive). "
            "Per project policy, recommendation-grade prompts are NOT "
            "auto-applied — they are surfaced as WARN and the original "
            "configuration is preserved.  Correction-grade issues "
            "(settings CP2K will reject) WARN then hard-exit. "
            "Categories that may fire: SCF profile/engine, ADMM aux basis, "
            "boundary-charge scheme, link-bond cuts, residual-charge plan, "
            "PME tolerance, periodic QM/MM RCUT, electron parity. "
            "See run_provenance.txt after the run for the full audit "
            "trail; rerun without --non-interactive to be prompted."
        )
        run_provenance.record(
            kind='non_interactive_mode',
            severity='info',
            source='cli',
            from_value=None,
            to_value='enabled',
            reason=(
                'Non-interactive mode active: recommendation-grade prompts '
                'are skipped (config preserved); correction-grade issues '
                'hard-exit per feedback_no_silent_modifications policy.'
            ),
            citation='project policy (feedback_no_silent_modifications)',
        )

    banner()
    TOTAL_STEPS = 8

    # ── Step 1: Directory scan ────────────────────────────────────────────
    step(1, TOTAL_STEPS, "Scanning input directory")
    work_dir = os.path.abspath(args.dir)
    info(f"Working directory: {work_dir}")

    detected = detect_files(work_dir)
    if not detected.get('prmtop'):
        error("No AMBER topology file (.parm7/.prmtop) found!")
        sys.exit(1)

    for key, path in detected.items():
        if isinstance(path, (list, tuple)):
            shown = ", ".join(os.path.basename(p) for p in path[:3])
            if len(path) > 3:
                shown += ", ..."
            detail(f"{key:>10s}: {shown}")
        else:
            detail(f"{key:>10s}: {os.path.basename(path)}")

    if not detected.get('rst7'):
        error("No AMBER coordinate file (.rst7/.inpcrd) found!")
        sys.exit(1)

    if interactive:
        if not ask_yes("Accept detected files?"):
            detected['prmtop'] = ask("AMBER topology file path", detected.get('prmtop', ''))
            detected['rst7'] = ask("AMBER coordinate file path", detected.get('rst7', ''))
            pdb_path = ask("PDB file path (optional, press Enter to skip)",
                           detected.get('pdb', ''))
            if pdb_path:
                detected['pdb'] = pdb_path

    # ── Step 2: Parse topology ────────────────────────────────────────────
    step(2, TOTAL_STEPS, "Parsing AMBER topology")
    topo = AmberTopology(detected['prmtop'])
    info(f"NATOM = {topo.natom}, NTYPES = {topo.ntypes}")
    info(f"FLAG sections found: {len(topo.flags)}")
    validate_topology_format(topo, interactive=interactive)

    # ── Early ParmEd availability check ──────────────────────────────────
    # ParmEd is required for zero-LJ hydrogen patching (changeLJSingleType)
    # and derived PRMTOP export.  The actual import is deferred to
    # patch_lj_and_write(), which is gated by `if not dry_run:`.  Without
    # this check, dry-run mode silently succeeds even when ParmEd is absent,
    # giving a false green light for a run that will fail at execution time.
    # Ref: ParmEd docs — pip install parmed; AmberTools includes it.
    parmed_backend = _get_preferred_parmed_backend()
    if parmed_backend is None:
        _parmed_msg = (
            "ParmEd is required for topology preparation (zero-LJ hydrogen "
            "patching and derived PRMTOP export). The script searched "
            f"{_format_parmed_search_locations()}. Install ParmEd in the active "
            "Python, or point AMBERHOME to an AmberTools installation that includes it."
        )
        if dry_run:
            warn(f"[DRY RUN] {_parmed_msg}")
            warn(
                "[DRY RUN] The real (non-dry-run) execution will fail without ParmEd. "
                "All other dry-run checks will proceed."
            )
        else:
            error(_parmed_msg)
            sys.exit(1)
    else:
        detail(f"ParmEd backend selected: {parmed_backend.label}")

    coords_rst7, rst7_box = read_rst7(detected['rst7'])
    prmtop_box = topo.box
    box = rst7_box or prmtop_box

    if rst7_box and prmtop_box:
        # Prefer restart-file box (contains full current crystallographic cell).
        diff = max(abs(float(rst7_box[i]) - float(prmtop_box[i])) for i in range(6))
        if diff > 1.0e-6:
            warn(
                "PRMTOP and RST7 box values differ; using RST7 box for CP2K cell "
                "(more current and can include full alpha/beta/gamma)."
            )

    if box:
        info(f"Box lengths: {box[0]:.2f} x {box[1]:.2f} x {box[2]:.2f} Å")
        info(f"Box angles:  alpha={box[3]:.2f} beta={box[4]:.2f} gamma={box[5]:.2f} deg")
    else:
        warn("No box dimensions found in PRMTOP or RST7. Using default 100 Å orthorhombic box.")

    # AMBER File Formats make ATOM_TYPE_INDEX the force-field identity, so the
    # CP2K bridge is derived once from the source topology and reused everywhere.
    alias_plan = build_atom_type_alias_plan(topo)
    _validate_atom_type_alias_plan(topo, alias_plan)
    element_map = _resolved_alias_element_map(alias_plan)
    unresolved = list(alias_plan.unresolved_aliases)
    atom_types = list(alias_plan.atom_aliases)
    atom_charges = topo.get_float_array('CHARGE')
    info(f"Resolved {len(element_map)} unique atom-type identities to elements")
    if unresolved:
        unresolved_preview = []
        for alias in unresolved[:10]:
            ident = alias_plan.alias_to_identity.get(alias)
            if ident is None:
                unresolved_preview.append(alias)
            else:
                unresolved_preview.append(f"{alias}<-{ident.raw_label}/{ident.atom_type_index}")
        warn(f"Could not resolve {len(unresolved)} atom-type identities: {unresolved_preview}")
        if interactive:
            overrides = {}
            for alias in unresolved:
                ident = alias_plan.alias_to_identity[alias]
                elem = ask(
                    f"Element for atom type '{ident.raw_label}' (ATOM_TYPE_INDEX {ident.atom_type_index}, alias {alias})?",
                    'X',
                )
                overrides[alias] = elem.upper()
            alias_plan = _apply_alias_element_overrides(alias_plan, overrides)
            element_map = _resolved_alias_element_map(alias_plan)
            unresolved = list(alias_plan.unresolved_aliases)

    # ── Step 3: Extract QM region ─────────────────────────────────────────
    step(3, TOTAL_STEPS, "Extracting QM region")

    qm_elements = None
    qm_indices = None
    mdin_meta = {}

    # Strategy 1: Try .mdin files (most authoritative — contain CHARMM-GUI QM/MM region definitions)
    mdin_candidates = list(dict.fromkeys(detected.get('mdin_candidates') or ([detected['mdin']] if detected.get('mdin') else [])))
    if mdin_candidates:
        if len(mdin_candidates) > 1:
            detail(f"Found {len(mdin_candidates)} AMBER input candidates; trying QM/MM-aware files first.")
        for mdin_path in mdin_candidates:
            detail(f"Found AMBER input file: {os.path.basename(mdin_path)}")
            detail("Parsing &qmmm namelist for iqmatoms/qmmask...")
            mdin_result = extract_qm_from_mdin(
                mdin_path,
                topo,
                element_map,
                atom_types,
                prmtop_path=detected.get('prmtop'),
                crd_path=detected.get('rst7'),
            )
            if not mdin_result[1]:
                if len(mdin_candidates) > 1:
                    detail(f"  No QM region found in {os.path.basename(mdin_path)}; trying next .mdin candidate.")
                continue

            mdin_elements, mdin_indices, parsed_mdin_meta = mdin_result
            selection_label = parsed_mdin_meta.get('selection_source', 'iqmatoms')
            info(f"Found {len(mdin_indices)} QM atoms from {selection_label} in {os.path.basename(mdin_path)}")
            if parsed_mdin_meta.get('qmcharge') is not None:
                detail(f"  QM charge:  {parsed_mdin_meta['qmcharge']}")
            if parsed_mdin_meta.get('qm_theory'):
                detail(f"  QM theory:  {parsed_mdin_meta['qm_theory']} (AMBER setting — CP2K uses its own DFT config)")
            if parsed_mdin_meta.get('qmmask'):
                detail(f"  QM mask:    {parsed_mdin_meta['qmmask']}")
            for elem, idxs in sorted(mdin_elements.items()):
                detail(f"  {elem}: {len(idxs)} atoms")

            use_mdin = True
            if interactive:
                use_mdin = ask_yes("Use this MDIN-derived QM region?")

            if use_mdin:
                qm_elements = mdin_elements
                qm_indices = mdin_indices
                mdin_meta = dict(parsed_mdin_meta)
                break
            detail("Skipping this MDIN selection, will try the next source...")

    # Strategy 2: Try PDB-based extraction (HETB/HETD segments)
    if not qm_indices and detected.get('pdb'):
        detail("Attempting QM extraction from PDB file (HETB/HETD segments)...")
        qm_elements, qm_indices = extract_qm_from_pdb(detected['pdb'])
        if qm_indices:
            info(f"Auto-detected {len(qm_indices)} QM atoms from PDB HETB/HETD segments")
            warn("PDB-based detection captures ligand/cofactor atoms only.")
            warn("If your QM region includes protein residues (e.g., active site sidechains),")
            warn("you must add them manually below.")

            if interactive and ask_yes("Add additional QM atoms (protein residues, etc.)?", default=False):
                method = ask("Extension method: (1) comma-separated indices, (2) AMBER mask", "1")
                extra_elements = {}
                extra_indices = []
                if method == "2":
                    mask = ask("Enter AMBER mask for additional QM atoms")
                    extra_elements, extra_indices = extract_qm_from_mask(
                        mask, detected['prmtop'], detected['rst7'])
                    if extra_indices is None:
                        # ── Explicit mask-fallback UX (S7) ────────────────
                        # Previously we silently downgraded to manual indices,
                        # which is a hazard: the two selection semantics are
                        # not interchangeable (masks resolve through ParmEd's
                        # topology model, whereas comma-separated indices are
                        # literal 1-based atom IDs).  A silent downgrade can
                        # produce a wrong QM region without the user noticing.
                        # Force an explicit confirmation before proceeding.
                        warn(
                            "AMBER mask could not be resolved (ParmEd unavailable "
                            "or mask syntax rejected). The alternative — manual "
                            "index entry — does NOT share the same selection "
                            "semantics and may yield a different QM region."
                        )
                        if not ask_yes(
                            "Fall back to manual comma-separated indices?",
                            default=False,
                        ):
                            error(
                                "QM-region extension cancelled by user. Install "
                                "ParmEd (AmberTools) to use AMBER mask selection."
                            )
                            sys.exit(1)
                        idx_str = ask("Enter additional 1-based QM atom indices (comma-separated)")
                        extra_elements, extra_indices = extract_qm_from_indices(
                            idx_str, topo, element_map, atom_types)
                else:
                    idx_str = ask("Enter additional 1-based QM atom indices (comma-separated)")
                    extra_elements, extra_indices = extract_qm_from_indices(
                        idx_str, topo, element_map, atom_types)

                if extra_indices:
                    qm_indices.extend(extra_indices)
                    for elem, idxs in extra_elements.items():
                        qm_elements.setdefault(elem, []).extend(idxs)
                    info(f"Extended QM region to {len(qm_indices)} total atoms")

    # Strategy 3: Manual input (interactive only)
    if not qm_indices:
        detail("No QM atoms detected from MDIN or PDB. Please specify QM region.")
        if interactive:
            method = ask("QM selection method: (1) comma-separated indices, (2) AMBER mask", "1")
            if method == "2":
                mask = ask("Enter AMBER mask (e.g., ':90,223@CA')")
                qm_elements, qm_indices = extract_qm_from_mask(
                    mask, detected['prmtop'], detected['rst7'])
                if qm_indices is None:
                    # ── Explicit mask-fallback UX (S7) ────────────────────
                    # AMBER mask and manual-index selection have *different*
                    # semantics: the mask is parsed by ParmEd against the
                    # topology graph (`:90,223@CA` => atoms CA of residues
                    # 90 and 223), while index entry is literal 1-based
                    # atom IDs.  Silently degrading the user's selection
                    # can produce a subtly wrong QM region that only
                    # manifests as a bad chemistry result post-run.
                    # Require an explicit confirmation.
                    warn(
                        "AMBER mask resolution failed (ParmEd unavailable or mask "
                        "rejected). Manual comma-separated indices are NOT "
                        "equivalent — they are literal 1-based atom IDs, whereas "
                        "the mask would resolve against the topology graph."
                    )
                    if not ask_yes(
                        "Fall back to manual comma-separated indices?",
                        default=False,
                    ):
                        error(
                            "QM selection cancelled by user. Install ParmEd "
                            "(AmberTools) to use AMBER mask selection, or re-run "
                            "with a pre-resolved index list."
                        )
                        sys.exit(1)
                    idx_str = ask("Enter 1-based QM atom indices (comma-separated)")
                    qm_elements, qm_indices = extract_qm_from_indices(
                        idx_str, topo, element_map, atom_types)
            else:
                idx_str = ask("Enter 1-based QM atom indices (comma-separated)")
                qm_elements, qm_indices = extract_qm_from_indices(
                    idx_str, topo, element_map, atom_types)
        else:
            error("No QM atoms found and running in non-interactive mode.")
            error("Place a .mdin file with iqmatoms in the directory, or use interactive mode.")
            sys.exit(1)

    if not qm_indices:
        error("No QM atoms specified. Cannot proceed.")
        sys.exit(1)

    for elem, indices in sorted(qm_elements.items()):
        detail(f"  {elem}: {len(indices)} atoms")

    # ── Step 4: Detect link atoms ─────────────────────────────────────────
    step(4, TOTAL_STEPS, "Detecting QM/MM boundary bonds")
    qm_set = set(qm_indices)
    atomic_numbers = topo.get_int_array('ATOMIC_NUMBER')
    links = detect_link_bonds(
        topo,
        qm_set,
        atom_types=atom_types,
        element_map=element_map,
        atomic_numbers=atomic_numbers,
    )
    info(f"Found {len(links)} QM/MM link bonds")
    adjacency = build_mm_adjacency(topo)
    charges_e = [float(c) / AMBER_CHARGE_SCALE for c in atom_charges[:int(topo.natom)]]
    enrich_link_with_m2(
        links, adjacency, qm_set, charges_e,
        atom_types=atom_types, element_map=element_map,
        atomic_numbers=atomic_numbers,
    )
    # ── C.1.a: Forbidden-bond classifier via AMBER Kr proxy ───────────────
    # Flag any link whose QM- or MM-side element falls outside the AMBER
    # covalent subset (transition metals, heavy main-group, noble gases,
    # f-block).  For those "Kr-proxied" elements the IMOMM capping-atom
    # construction is categorically invalid: the MM side has no covalent
    # bond parameters, so the H_link direction has no restoring force.
    # Per feedback_no_silent_modifications we *always* surface the issue
    # (WARN + provenance) and, in interactive mode, ask the user for
    # explicit consent to proceed.
    _forbidden_link_records = []
    for _lnk in links:
        _verdict = classify_forbidden_link_bond(_lnk.get('QM_ELEM'), _lnk.get('MM_ELEM'))
        if _verdict['forbidden']:
            _lnk['FORBIDDEN_KR_PROXY'] = dict(_verdict)
            _forbidden_link_records.append((_lnk, _verdict))
    if _forbidden_link_records:
        for _lnk, _verdict in _forbidden_link_records:
            warn(
                f"FORBIDDEN link bond: QM atom {_lnk.get('QM_INDEX')} "
                f"({_lnk.get('QM_ELEM')}) — MM atom {_lnk.get('MM_INDEX')} "
                f"({_lnk.get('MM_ELEM')}): "
                f"{_verdict['reason']} [side={_verdict['side']}]"
            )
        _aggregate = {
            f"{l.get('QM_ELEM')}-{l.get('MM_ELEM')}": v['reason_key']
            for (l, v) in _forbidden_link_records
        }
        _user_confirmed_forbidden = False
        if interactive:
            warn(
                "Proceeding through a forbidden link bond produces an ill-"
                "defined QM/MM Hamiltonian (see Maseras & Morokuma 1995; "
                "Peters et al. JCTC 6, 2935 (2010)). The scientifically "
                "correct remedies are: (a) widen the QM region to absorb "
                "the full coordination sphere, or (b) supply a curated "
                "bonded force field (e.g. CHARMM-GUI Metal Protein)."
            )
            _user_confirmed_forbidden = ask_yes(
                "Do you understand the risk and want to proceed anyway?",
                default=False,
            )
        else:
            error(
                "Non-interactive run encountered forbidden Kr-proxy link "
                "bond(s); refusing to proceed silently. Re-run interactively "
                "to override, or widen the QM region to absorb the "
                "coordination sphere."
            )
        run_provenance.record(
            kind='forbidden_link_bond_kr_proxy',
            severity='error',
            source=('user' if interactive else 'auto'),
            from_value=None,
            to_value=_aggregate,
            accepted=(_user_confirmed_forbidden if interactive else False),
            reason=(
                f"{len(_forbidden_link_records)} QM/MM link bond(s) cross "
                "an AMBER Kr-proxied element where IMOMM H-capping is "
                "categorically undefined; user consent required to proceed."
            ),
            citation=(
                "Maseras & Morokuma, JCC 16, 1170 (1995); "
                "Peters et al., JCTC 6, 2935 (2010); "
                "Lin & Truhlar, Theor. Chem. Acc. 117, 185 (2007); "
                "AmberTools Manual — QM/MM chapter (Case et al.)"
            ),
            context={
                'link_count': len(_forbidden_link_records),
                'pairs': _aggregate,
            },
        )
        if not interactive or not _user_confirmed_forbidden:
            raise SystemExit(
                "Aborted: forbidden QM/MM link bond(s) detected — "
                "see WARN lines above and run_provenance.jsonl."
            )
    # ── C.1.d: Interactive ALPHA_IMOMM override for unsupported pairs ─────
    # detect_link_bonds() already emits a WARN naming every (QM_elem,
    # MM_elem) pair that falls back on DEFAULT_ALPHA_IMOMM because it is
    # not tabulated in LINK_ALPHA_IMOMM_BY_PAIR.  The default 1.38 is a
    # conventional C–H-scaled value that may be significantly off for
    # exotic cuts (e.g. metal–ligand, halogen–C, Se–Se, B–N).  In
    # interactive mode we offer the user a chance to supply a curated
    # ALPHA = r(QM–MM) / r(QM–H_link) per pair without ever modifying
    # the value silently.  Non-interactive invocations keep the default
    # (per feedback_no_silent_modifications policy) and always emit a
    # provenance entry so the fallback is visible in the audit trail.
    # Refs: Maseras & Morokuma, J. Comput. Chem. 16, 1170 (1995) — IMOMM
    #       capping-atom scheme; Senn & Thiel, Angew. Chem. Int. Ed.
    #       48, 1198 (2009), §3.1 — link-atom hygiene in QM/MM.
    _unsupported_pair_links = defaultdict(list)
    for _link in links:
        _pair = (str(_link.get('QM_ELEM', 'X')).upper(),
                 str(_link.get('MM_ELEM', 'X')).upper())
        if _pair not in LINK_ALPHA_IMOMM_BY_PAIR:
            _unsupported_pair_links[_pair].append(_link)
    if _unsupported_pair_links:
        _pair_override_record = {}
        if interactive:
            info(
                f"{len(_unsupported_pair_links)} boundary element pair(s) are "
                f"not tabulated in LINK_ALPHA_IMOMM_BY_PAIR and currently use "
                f"DEFAULT_ALPHA_IMOMM={DEFAULT_ALPHA_IMOMM:.2f}. "
                "You may override ALPHA = r(QM–MM) / r(QM–H_link) per pair, "
                "or keep the default."
            )
            for _pair, _lnks in sorted(_unsupported_pair_links.items()):
                _pair_label = f"{_pair[0]}–{_pair[1]}"
                if ask_yes(
                    f"  Override ALPHA_IMOMM for unsupported pair {_pair_label} "
                    f"({len(_lnks)} link bond(s))?",
                    default=False,
                ):
                    _new_alpha = ask_float(
                        f"    ALPHA_IMOMM for {_pair_label} (QM={_pair[0]}, MM={_pair[1]})",
                        default=DEFAULT_ALPHA_IMOMM,
                        minimum=0.1,
                    )
                    for _lnk in _lnks:
                        _lnk['ALPHA_IMOMM'] = float(_new_alpha)
                    _pair_override_record[_pair] = float(_new_alpha)
                    info(
                        f"    Using ALPHA_IMOMM={float(_new_alpha):.3f} for "
                        f"{_pair_label} ({len(_lnks)} link(s))."
                    )
        # Always record the fallback/override situation for post-hoc audit.
        run_provenance.record(
            kind='link_alpha_imomm_unsupported_pair',
            severity='recommendation',
            source='user' if _pair_override_record else 'auto',
            from_value=f"default={DEFAULT_ALPHA_IMOMM:.3f}",
            to_value=(
                "; ".join(
                    f"{a}-{b}={_pair_override_record[(a, b)]:.3f}"
                    for (a, b) in sorted(_pair_override_record)
                ) if _pair_override_record
                else f"default={DEFAULT_ALPHA_IMOMM:.3f} retained"
            ),
            accepted=(bool(_pair_override_record) if interactive else None),
            reason=(
                f"{len(_unsupported_pair_links)} unsupported QM–MM element "
                "pair(s) not tabulated in LINK_ALPHA_IMOMM_BY_PAIR; "
                + (
                    f"{len(_pair_override_record)} user-supplied override(s) applied."
                    if _pair_override_record else
                    f"default {DEFAULT_ALPHA_IMOMM:.2f} retained "
                    + ("(user declined override)." if interactive else
                       "(non-interactive mode — no auto-modification per policy).")
                )
            ),
            citation=(
                "Maseras & Morokuma, J. Comput. Chem. 16, 1170 (1995); "
                "Senn & Thiel, Angew. Chem. Int. Ed. 48, 1198 (2009)"
            ),
            context={
                'unsupported_pairs': [
                    f"{a}-{b}" for (a, b) in sorted(_unsupported_pair_links)
                ],
                'link_counts': {
                    f"{a}-{b}": len(_unsupported_pair_links[(a, b)])
                    for (a, b) in sorted(_unsupported_pair_links)
                },
                'overrides': {
                    f"{a}-{b}": float(_pair_override_record[(a, b)])
                    for (a, b) in sorted(_pair_override_record)
                },
            },
        )
    for link in links:
        m2_str = ", ".join(str(i) for i in link.get('M2_INDICES', []))
        detail(
            f"  QM atom {link['QM_INDEX']} ({link.get('QM_ELEM', 'X')}) — "
            f"MM atom {link['MM_INDEX']} ({link.get('MM_ELEM', 'X')}) "
            f"alpha={float(link.get('ALPHA_IMOMM', DEFAULT_ALPHA_IMOMM)):.3f}, "
            f"q(M1)={link.get('M1_CHARGE_E', 0.0):+.4f} e, M2 neighbors=[{m2_str}]"
        )
    # ── Duplicate-M1 frontier detection (C.1.b) ───────────────────────────
    # A single MM atom serving as M1 for two different &LINK blocks is
    # accepted by CP2K but produces a doubly-truncated embedding for that
    # M1: each link independently rescales QMMM_SCALE_FACTOR/FIST_SCALE
    # _FACTOR and runs its own ADD_MM_CHARGE redistribution, and the two
    # perturbations compose in a way that is difficult to audit post-hoc.
    # We surface the situation but never auto-modify the QM region —
    # widening the QM cut to absorb the M1 atom is the user's call (it
    # changes the science of the calculation).
    # Refs: Senn & Thiel, Angew. Chem. Int. Ed. 48, 1198 (2009), §3.1;
    #       Lin & Truhlar, Theor. Chem. Acc. 117, 185 (2007), §2.2.
    duplicate_m1 = detect_duplicate_m1_frontier_atoms(links)
    if duplicate_m1:
        warn(
            f"{len(duplicate_m1)} MM atom(s) serve as the M1 frontier for >1 link bond. "
            "Each such M1 will be doubly-perturbed by independent &LINK blocks "
            "(QMMM_SCALE/FIST_SCALE applied twice, ADD_MM_CHARGE redistributed to "
            "disjoint M2 sets).  Consider widening the QM region to include the "
            "M1 atom, or accept the composed perturbation knowingly."
        )
        for m1_idx, link_list in sorted(duplicate_m1.items()):
            qm_partners = ", ".join(str(int(l.get('QM_INDEX'))) for l in link_list)
            detail(f"    M1={m1_idx} appears in links to QM atoms: [{qm_partners}]")
        run_provenance.record(
            kind='duplicate_m1_frontier',
            severity='recommendation',
            source='auto',
            accepted=None,
            reason=(
                f"{len(duplicate_m1)} MM atom(s) serve as M1 for multiple links; "
                "doubly-truncated embedding will be emitted unless QM region is widened."
            ),
            citation=(
                "Senn & Thiel, Angew. Chem. Int. Ed. 48, 1198 (2009); "
                "Lin & Truhlar, Theor. Chem. Acc. 117, 185 (2007)"
            ),
            context={
                'm1_atoms': sorted(int(k) for k in duplicate_m1.keys()),
                'duplicate_count': len(duplicate_m1),
            },
        )
    m1_set = {int(link['MM_INDEX']) for link in links}
    # ── B.3.a: residual-charge redistribute_strategy selection ──────────
    # The operator picks between 'uniform' (classic CP2K-tutorial behaviour)
    # and 'distance_weighted' (concentrates Δq near the QM boundary).  In
    # interactive mode we always inquire (cf. no_silent_modifications
    # policy); in non-interactive mode we use the safe default 'uniform'
    # and surface the choice in the run provenance so the reviewer sees
    # what the pipeline actually did. Citation: Lin & Truhlar, Theor.
    # Chem. Acc. 117, 185 (2007) — review of boundary charge schemes.
    if interactive:
        _redistribute_strategy_choice = ask_choice(
            "Residual-charge redistribution strategy for split residues "
            "(uniform = equal Δq per target atom, reproducible default; "
            "distance_weighted = Δq ∝ 1/(d²+r0²) from nearest QM atom, "
            "localizes correction near the boundary)",
            list(RESIDUAL_CHARGE_REDISTRIBUTE_STRATEGIES),
            'uniform',
        )
    else:
        _redistribute_strategy_choice = 'uniform'
    _redistribute_strategy_choice = _validate_redistribute_strategy(
        _redistribute_strategy_choice
    )
    run_provenance.record(
        kind='residual_charge_redistribute_strategy',
        severity='recommendation',
        source=('user' if interactive else 'auto'),
        from_value='uniform',
        to_value=_redistribute_strategy_choice,
        accepted=True,
        reason=(
            "Uniform preserves integrated residue neutrality by equal "
            "split; distance_weighted also preserves it (Σw=1) but "
            "concentrates Δq on MM atoms nearest the excised QM region, "
            "which better matches the physical locality of the embedding "
            "scar at the cost of residue-specific weights."
        ),
        citation=(
            "Lin & Truhlar, Theor. Chem. Acc. 117, 185 (2007); "
            "Senn & Thiel, Angew. Chem. Int. Ed. 48, 1198 (2009)"
        ),
    )
    residual_charge_plan = warn_residual_charges(
        qm_indices, topo, m1_set=m1_set,
        redistribute_strategy=_redistribute_strategy_choice,
        coords=coords_rst7,
    )
    # ── B.3.b: record residual-charge severity in run provenance ────────
    # The redistribution itself is exact (charge neutrality preserved) but
    # large per-atom or per-residue shifts deserve durable audit so the
    # reviewer can correlate any observed force/energy artefacts back to
    # the embedding edit, not just the in-stream WARN lines.
    if residual_charge_plan:
        _residual_severity = evaluate_residual_charge_plan_severity(residual_charge_plan)
        if _residual_severity['overall_severity'] != 'ok':
            run_provenance.record(
                kind='residual_charge_redistribution',
                severity=(
                    'recommendation'
                    if _residual_severity['overall_severity'] == 'noticeable'
                    else 'correction'
                ),
                source='auto',
                from_value=None,
                to_value=(
                    f"{len(residual_charge_plan)} residue(s) "
                    f"redistributed; max |Δq/atom|="
                    f"{_residual_severity['max_abs_per_atom_e']:.3f} e, "
                    f"max |Σ/residue|="
                    f"{_residual_severity['max_abs_per_residue_e']:.3f} e"
                ),
                accepted=None,
                reason=(
                    "Uniform residual-charge redistribution after QM "
                    "excision; per-atom or per-residue shifts exceed the "
                    f"{_residual_severity['overall_severity']} threshold "
                    "(integral neutrality is preserved exactly, but the "
                    "MM Hamiltonian seen by the QM region is reshaped)."
                ),
                citation=(
                    'AMBER ff14SB (Maier et al., JCTC 11, 3696 (2015)); '
                    'RESP fitting (Bayly et al., JPC 97, 10269 (1993))'
                ),
                context={
                    'overall_severity': _residual_severity['overall_severity'],
                    'noticeable_residues': len(_residual_severity['noticeable_residues']),
                    'severe_residues': len(_residual_severity['severe_residues']),
                },
            )
    if interactive and links:
        detail(
            "Recommended QM/MM frontier policy: CHARGE_SHIFT "
            "(QMMM_SCALE_FACTOR 0.0, FIST_SCALE_FACTOR 1.0, redistribute q(M1) to M2)."
        )
        if ask_yes("Keep recommended boundary-charge policy?", default=True):
            boundary_charge_scheme = DEFAULT_BOUNDARY_CHARGE_SCHEME
            run_provenance.record(
                kind='boundary_charge_scheme',
                severity='info',
                source='wizard',
                from_value=None,
                to_value=DEFAULT_BOUNDARY_CHARGE_SCHEME,
                accepted=True,
                reason='User accepted recommended QM/MM frontier policy.',
                citation='Laino et al. JCTC 2, 1370 (2006); Senn & Thiel 2009',
            )
        else:
            for scheme, desc in BOUNDARY_CHARGE_SCHEMES.items():
                detail(f"  {scheme}: {desc}")
            boundary_charge_scheme = ask_choice(
                "Boundary charge scheme",
                list(BOUNDARY_CHARGE_SCHEMES.keys()),
                default=DEFAULT_BOUNDARY_CHARGE_SCHEME,
            ).upper()
            run_provenance.record(
                kind='boundary_charge_scheme',
                severity='info',
                source='wizard',
                from_value=DEFAULT_BOUNDARY_CHARGE_SCHEME,
                to_value=boundary_charge_scheme,
                accepted=True,
                reason='User selected non-default frontier policy.',
                citation='Laino et al. JCTC 2, 1370 (2006); Senn & Thiel 2009',
            )
    else:
        boundary_charge_scheme = DEFAULT_BOUNDARY_CHARGE_SCHEME
        if links:
            run_provenance.record(
                kind='boundary_charge_scheme',
                severity='info',
                source='auto',
                from_value=None,
                to_value=DEFAULT_BOUNDARY_CHARGE_SCHEME,
                accepted=None,
                reason='Non-interactive default applied (no link bonds → no impact).'
                       if not links else
                       'Non-interactive default applied to QM/MM frontier policy.',
                citation='Laino et al. JCTC 2, 1370 (2006)',
            )

    # ── C.2.a: verify any per-link boundary-charge overrides ──────────────
    # Individual &LINK blocks may carry an optional
    # ``BOUNDARY_CHARGE_SCHEME`` override (populated from CLI, a config
    # manifest, or a future per-link wizard step).  Before any CP2K
    # input is assembled we validate each override against the documented
    # BOUNDARY_CHARGE_SCHEMES enum and the link's own M2 availability.
    # Rejected/demoted overrides are reported to WARN and captured in
    # run_provenance so the audit trail explains exactly why the emitted
    # &LINK block differs from what was requested.
    if links:
        verify_per_link_boundary_charge_overrides(
            links,
            global_scheme=boundary_charge_scheme,
            interactive=interactive,
            run_provenance=run_provenance,
        )

    # ── Step 5: Prepare topology variants & export coordinates ────────────
    step(5, TOTAL_STEPS, "Preparing MM/QM/MM topologies and coordinates")

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_dir = os.path.join(work_dir, f"cp2k_output_{timestamp}")

    if not dry_run:
        os.makedirs(out_dir, exist_ok=True)
        info(f"Output directory: {out_dir}")

    mm_prmtop_out = os.path.join(out_dir, "system_mm.prmtop")
    qmmm_prmtop_out = os.path.join(out_dir, "system_qmmm.prmtop")
    atom_type_manifest_out = os.path.join(out_dir, ATOM_TYPE_ALIAS_MANIFEST_BASENAME)
    xyz_out = os.path.join(out_dir, "system.xyz")
    pdb_full_out = os.path.join(out_dir, "system_qmmm_flag.pdb")
    pdb_qm_only_out = os.path.join(out_dir, "qm_subsystem.pdb")
    electronic_state_out = os.path.join(out_dir, "electronic_state.dat")
    wrapper_out = None
    wrapper_log_default = None
    readme_out = None
    stage_meta = None
    stage_input_names = []
    hardware_probe_enabled = False
    hardware_info = None
    cp2k_install = None
    launch_cfg = None

    atomic_numbers_for_xyz = topo.get_int_array('ATOMIC_NUMBER')
    atom_names_for_export = topo.get_string_array('ATOM_NAME')
    residue_labels_for_export = topo.get_string_array('RESIDUE_LABEL')
    residue_pointers_for_export = topo.get_int_array('RESIDUE_POINTER')
    elems_per_atom = []

    if not dry_run:
        try:
            patch_lj_and_write(
                topo,
                mm_prmtop_out,
                prmtop_path=detected['prmtop'],
                residual_charge_plan=None,
                alias_plan=alias_plan,
            )
            patch_lj_and_write(
                topo,
                qmmm_prmtop_out,
                prmtop_path=detected['prmtop'],
                residual_charge_plan=residual_charge_plan,
                alias_plan=alias_plan,
            )
        except Exception as e:
            error(str(e))
            sys.exit(1)
        info(f"Wrote MM-stage topology: {os.path.basename(mm_prmtop_out)}")
        info(f"Wrote QM/MM-stage topology: {os.path.basename(qmmm_prmtop_out)}")

        # ── S11: PRMTOP-vs-manifest charge-drift cross-check ───────────
        # After ParmEd has round-tripped the QM/MM topology through its
        # PRMTOP writer, re-parse the emitted file and confirm its CHARGE
        # array matches the residual-charge plan bit-for-bit (modulo the
        # 1e-8 AMBER-units tolerance).  This catches the class of silent
        # failures where a ParmEd normalisation or a conversion-backend
        # fallback overwrote our QM-side charge redistribution.  Any
        # violation raises and blocks the run — the operator must fix
        # the drift before MD, since a systematic CHARGE mismatch
        # corrupts both the FIST electrostatics on the MM side and the
        # ADD_MM_CHARGE embedding on the QM side.
        # Ref: AmberTools Reference Manual §2.2 ("CHARGE"); Senn &
        #      Thiel ACIE 48, 1198 (2009) on the sensitivity of QM/MM
        #      embedding to boundary-charge accuracy.
        try:
            verify_prmtop_charges_match_manifest(
                qmmm_prmtop_out,
                topo.get_float_array('CHARGE'),
                residual_charge_plan,
                label="QM/MM-stage topology",
            )
            # MM-stage topology is authored with residual_charge_plan=None,
            # so its reference reduces to the raw CHARGE array of the
            # source.  Verifying it here catches the symmetric failure
            # mode where a round-trip inadvertently modifies MM charges.
            verify_prmtop_charges_match_manifest(
                mm_prmtop_out,
                topo.get_float_array('CHARGE'),
                None,
                label="MM-stage topology",
            )
            info("Verified emitted PRMTOP CHARGE arrays against residual-charge manifest.")
        except RuntimeError as _charge_err:
            error(str(_charge_err))
            sys.exit(1)

        write_atom_type_alias_manifest(
            atom_type_manifest_out,
            detected['prmtop'],
            [('mm', mm_prmtop_out), ('qmmm', qmmm_prmtop_out)],
            alias_plan,
        )
        info(f"Wrote atom-type alias manifest: {os.path.basename(atom_type_manifest_out)}")
        detail(
            "MM stages preserve original classical charges; QM/MM stages use the split-residue "
            "redistributed topology only where QM charge removal requires it."
        )
    else:
        info("[DRY RUN] Would write MM topology, QM/MM topology, XYZ, and QM/MM validation PDB files")
        info(f"[DRY RUN] Would write: {os.path.basename(atom_type_manifest_out)}")

    coords = coords_rst7
    for i in range(len(coords)):
        if i < len(atomic_numbers_for_xyz) and atomic_numbers_for_xyz[i] in ATOMIC_NUM_TO_SYMBOL:
            elems_per_atom.append(ATOMIC_NUM_TO_SYMBOL[atomic_numbers_for_xyz[i]])
        elif i < len(atom_types):
            elems_per_atom.append(element_map.get(atom_types[i], 'X'))
        else:
            elems_per_atom.append('X')

    if not dry_run:
        n_written = write_xyz(coords, elems_per_atom, xyz_out)
        info(f"Wrote {n_written} atoms to: {os.path.basename(xyz_out)}")

        pdb_counts = write_qmmm_boundary_pdbs(
            coords=coords,
            qm_indices=qm_indices,
            full_pdb_out_path=pdb_full_out,
            qm_only_pdb_out_path=pdb_qm_only_out,
            elements_per_atom=elems_per_atom,
            atom_names=atom_names_for_export,
            residue_labels=residue_labels_for_export,
            residue_pointers=residue_pointers_for_export,
        )
        info(
            f"Wrote QM/MM flag PDB: {os.path.basename(pdb_full_out)} "
            f"({pdb_counts['full_atoms']} atoms; B-factor 1.00=QM, 0.00=MM)"
        )
        info(
            f"Wrote QM-only PDB: {os.path.basename(pdb_qm_only_out)} "
            f"({pdb_counts['qm_atoms']} atoms)"
        )

    # ── Step 6: Generate staged CP2K input files ─────────────────────────
    step(6, TOTAL_STEPS, "Generating staged CP2K input files")
    run_type = 'MD'
    detail("Staged workflow: 10_em_mm -> 20_nvt_mm -> 30_npt_mm -> 35_qmmm_warmup -> 40_qmmm_md")

    # Production-stage MD setup (40_qmmm_md)
    preset = 'production'
    preset_cfg = dict(PRESETS[preset])
    md_steps = int(preset_cfg['steps'])
    md_timestep = float(preset_cfg['timestep'])
    md_temperature = float(preset_cfg['temperature'])
    md_ensemble = str(preset_cfg['ensemble']).upper()
    if interactive:
        print(f"\n  Available production presets:")
        for k, v in PRESETS.items():
            print(f"    {C.BOLD}{k:>15s}{C.R}: {v['desc']}")
        preset = ask_choice("Select production preset (40_qmmm_md)", list(PRESETS.keys()), "production").lower()
        preset_cfg = dict(PRESETS[preset])
        md_steps = int(preset_cfg['steps'])
        md_timestep = float(preset_cfg['timestep'])
        md_temperature = float(preset_cfg['temperature'])
        md_ensemble = str(preset_cfg['ensemble']).upper()
        if preset == 'custom':
            print(f"\n  {C.BOLD}Custom production MD setup{C.R}")
            md_steps = ask_int("Production MD steps (40_qmmm_md)", md_steps, minimum=1)
            md_timestep = ask_float("Production MD timestep [fs]", md_timestep, minimum=1.0e-8)
            md_temperature = ask_float("Production MD temperature [K]", md_temperature, minimum=0.0)
        md_ensemble = ask_choice(qmmm_md_ensemble_prompt(), MD_ENSEMBLES, md_ensemble).upper()

    # Stage controls (MM equilibration, handoff, warmup)
    em_max_iter = int(args.em_max_iter)
    mm_nvt_steps = int(args.mm_nvt_steps)
    mm_npt_steps = int(args.mm_npt_steps)
    mm_timestep = float(args.mm_timestep)
    warmup_steps = int(args.warmup_steps)
    # Honour the user-supplied warmup timestep verbatim here; any
    # reconciliation against the production timestep happens below,
    # after all interactive overrides, and follows the no-silent-
    # modifications policy (WARN non-interactively; explicit
    # ask_choice interactively).  Silently clamping ``args.warmup_timestep``
    # to ``md_timestep`` would destroy the operator's intent and is
    # therefore forbidden by this pipeline's audit contract.
    warmup_timestep = float(args.warmup_timestep)
    warmup_ensemble = str(args.warmup_ensemble).strip().upper()
    enable_qmmm_warmup = bool(args.enable_qmmm_warmup)
    qmmm_handoff_policy = requested_qmmm_handoff_policy
    qmmm_transition_thermostat_timecon_fs = float(requested_qmmm_transition_timecon)
    qmmm_transition_seed = requested_qmmm_transition_seed
    stateless_restart = bool(args.stateless_restart)
    mm_equil_restraints = bool(args.mm_active_site_restraints)
    warmup_restraints = (
        bool(args.qmmm_warmup_restraints)
        if args.qmmm_warmup_restraints is not None
        else bool(mm_equil_restraints)
    )
    if not enable_qmmm_warmup:
        warmup_restraints = False
    # NVT is the recommended warmup ensemble: the MM→QM/MM Hamiltonian switch
    # changes the potential energy surface, and the system must thermally
    # re-equilibrate at fixed volume before reintroducing pressure coupling.
    # NPT warmup risks unphysical cell fluctuations from transient QM forces.
    # Ref: Senn & Thiel, Angew. Chem. Int. Ed. 48, 1198 (2009), §4.2.
    if warmup_ensemble != 'NVT' and enable_qmmm_warmup:
        warn(
            f"Non-default warmup ensemble '{warmup_ensemble}' selected. "
            "NVT is recommended for QM/MM re-equilibration after the "
            "Hamiltonian switch. NPT risks transient cell instabilities "
            "driven by QM force artifacts."
        )

    if interactive:
        print(f"\n  {C.BOLD}Staged Workflow Controls{C.R}")
        detail("MM stages are always MM-only and use explicit EXT_RESTART semantics.")
        detail(
            "MM->QM/MM handoff policy controls only the first QM/MM stage after the Hamiltonian switch. "
            "Positions and cell are always restarted; velocities and thermostat/barostat/RNG state are optional."
        )
        detail(
            "If velocities are not restarted, CP2K can initialize fresh velocities from the QM/MM target temperature "
            "instead of inheriting MM velocities on the new Hamiltonian."
        )
        detail(
            "Recommended transition control is explicit: short CSVR coupling on the first QM/MM stage, "
            "and an explicit GLOBAL SEED when fresh stochastic initialization/state is used."
        )
        enable_qmmm_warmup = ask_yes("Enable 35_qmmm_warmup stage (recommended)?", default=enable_qmmm_warmup)
        if (args.qmmm_handoff_policy is not None) or (args.handoff_velocities is not None):
            detail(
                "Using CLI-selected MM->QM/MM handoff policy: "
                f"{qmmm_handoff_policy.mode} - {qmmm_handoff_policy.label}"
            )
        elif ask_yes(
            "Keep recommended QM/MM handoff policy (positions+cell only; fresh velocities/state on the first QM/MM stage)?",
            default=True,
        ):
            qmmm_handoff_policy = make_qmmm_handoff_policy()
        else:
            detail("Available MM->QM/MM handoff policies:")
            for mode, desc in QMMM_HANDOFF_POLICIES.items():
                detail(f"  {mode}: {desc}")
            qmmm_handoff_policy = make_qmmm_handoff_policy(
                mode=ask_choice(
                    "MM->QM/MM handoff policy",
                    tuple(QMMM_HANDOFF_POLICIES.keys()),
                    qmmm_handoff_policy.mode,
                ).upper()
            )
        if args.qmmm_transition_thermostat_timecon != DEFAULT_QMMM_TRANSITION_THERMOSTAT_TIMECON_FS:
            detail(
                "Using CLI-selected first-QM/MM-stage CSVR TIMECON: "
                f"{qmmm_transition_thermostat_timecon_fs:g} fs"
            )
        elif ask_yes(
            "Keep recommended first-QM/MM-stage CSVR TIMECON "
            f"({DEFAULT_QMMM_TRANSITION_THERMOSTAT_TIMECON_FS:g} fs for explicit re-equilibration)?",
            default=True,
        ):
            qmmm_transition_thermostat_timecon_fs = DEFAULT_QMMM_TRANSITION_THERMOSTAT_TIMECON_FS
        else:
            qmmm_transition_thermostat_timecon_fs = ask_float(
                "First QM/MM-stage CSVR TIMECON [fs]",
                qmmm_transition_thermostat_timecon_fs,
                minimum=1.0e-8,
            )
        if qmmm_handoff_policy.restart_randomg:
            qmmm_transition_seed = None
        elif args.qmmm_transition_seed != DEFAULT_QMMM_TRANSITION_SEED:
            detail(
                "Using CLI-selected first-QM/MM-stage GLOBAL SEED: "
                + ("disabled" if qmmm_transition_seed is None else str(int(qmmm_transition_seed)))
            )
        elif ask_yes(
            f"Keep explicit first-QM/MM-stage GLOBAL SEED {DEFAULT_QMMM_TRANSITION_SEED} for reproducible fresh stochastic initialization?",
            default=True,
        ):
            qmmm_transition_seed = DEFAULT_QMMM_TRANSITION_SEED
        else:
            qmmm_transition_seed = None
        stateless_restart = ask_yes(
            "stateless EXT_RESTART (disable thermostat/barostat/RNG/counters restart)?",
            default=stateless_restart,
        )
        mm_equil_restraints = ask_yes(
            "Apply active-site restraints (fixed QM atoms) during 20_nvt_mm and 30_npt_mm?",
            default=mm_equil_restraints,
        )
        if enable_qmmm_warmup:
            warmup_restraints = ask_yes(
                "Apply active-site restraints during 35_qmmm_warmup?",
                default=warmup_restraints,
            )
        else:
            warmup_restraints = False

        if ask_yes("Edit staged MM/warmup lengths and timesteps?", default=False):
            em_max_iter = ask_int("10_em_mm MAX_ITER", em_max_iter, minimum=1)
            mm_nvt_steps = ask_int("20_nvt_mm steps", mm_nvt_steps, minimum=1)
            mm_npt_steps = ask_int("30_npt_mm steps", mm_npt_steps, minimum=1)
            mm_timestep = ask_float("MM equilibration timestep [fs]", mm_timestep, minimum=1.0e-8)
            if enable_qmmm_warmup:
                warmup_steps = ask_int("35_qmmm_warmup steps", warmup_steps, minimum=1)
                warmup_timestep = ask_float("35_qmmm_warmup timestep [fs]", warmup_timestep, minimum=1.0e-8)
                warmup_ensemble = ask_choice(
                    "35_qmmm_warmup ensemble (NVT recommended)",
                    ['NVT', 'NPT_F', 'NPT_I'],
                    warmup_ensemble,
                ).upper()
                if warmup_ensemble != 'NVT':
                    warn(
                        f"Non-default warmup ensemble '{warmup_ensemble}' — NVT is "
                        "recommended for QM/MM re-equilibration."
                    )
    # ── Warmup Δt vs production Δt reconciliation ────────────────────
    # The 35_qmmm_warmup stage is the first integration under the
    # QM/MM Hamiltonian, following an MM-equilibrated configuration.
    # Its role is to absorb the transient energy impulse introduced
    # by the Hamiltonian switch — thermal re-equilibration at fixed
    # volume before coupling a barostat (Leimkuhler & Reich,
    # *Simulating Hamiltonian Dynamics*, CUP 2004, §5 on symplectic
    # integrator stability Δt·ω_max ≲ 2; Senn & Thiel, *Angew. Chem.
    # Int. Ed.* **48**, 1198 (2009), §4.2 on QM/MM re-equilibration).
    #
    # Convention is warmup Δt ≤ production Δt.  When the operator
    # asks for a larger warmup Δt we neither silently reduce it
    # (would violate the audit contract) nor forbid it (CP2K accepts
    # any positive Δt and the operator may have a reason).  Instead:
    #   • non-interactive → WARN and keep the value, recording
    #     provenance with accepted=False so the manifest flags the
    #     unusual choice for the reviewer;
    #   • interactive    → ask_choice {keep, reduce, custom}, then
    #     record provenance with the selected value and accepted=True
    #     (or accepted=False when the operator elects to keep).
    if warmup_timestep > md_timestep:
        _warmup_requested = float(warmup_timestep)
        _warmup_resolution_source = 'cli+args'
        _warmup_resolution_accepted = False
        if interactive:
            # Three-way prompt: default is 'reduce' because the
            # conservative handoff convention is warmup Δt ≤ md Δt.
            _choice = ask_choice(
                f"Warmup Δt ({_warmup_requested:g} fs) exceeds production Δt "
                f"({md_timestep:g} fs) — keep, reduce to production, or enter new value?",
                ['keep', 'reduce', 'custom'],
                'reduce',
            ).lower()
            if _choice == 'reduce':
                warmup_timestep = float(md_timestep)
                _warmup_resolution_source = 'user_prompt'
                _warmup_resolution_accepted = True
            elif _choice == 'custom':
                warmup_timestep = ask_float(
                    "New warmup Δt [fs]",
                    float(md_timestep),
                    minimum=1.0e-8,
                )
                _warmup_resolution_source = 'user_prompt'
                _warmup_resolution_accepted = True
            else:  # 'keep'
                warn(
                    f"Warmup Δt ({_warmup_requested:g} fs) retained above production Δt "
                    f"({md_timestep:g} fs) at operator request; this is unusual for "
                    "conservative QM/MM handoff."
                )
                _warmup_resolution_source = 'user_prompt'
                _warmup_resolution_accepted = False
        else:
            # Non-interactive: audit-contract forbids silent reduction.
            warn(
                f"Warmup Δt ({_warmup_requested:g} fs) exceeds production Δt "
                f"({md_timestep:g} fs) — retained verbatim (policy: no silent "
                "auto-reduce).  Pass ``--warmup-timestep`` ≤ ``--md-timestep`` "
                "or run interactively to resolve."
            )
        run_provenance.record(
            kind='md_warmup_timestep_clamp',
            severity='recommendation',
            source=_warmup_resolution_source,
            from_value=f"{_warmup_requested:g} fs",
            to_value=f"{float(warmup_timestep):g} fs",
            accepted=_warmup_resolution_accepted,
            reason=(
                'Warmup Δt exceeded production Δt; conservative QM/MM '
                'handoff uses warmup Δt ≤ production Δt. Policy forbids '
                'silent reduction; operator choice recorded.'
            ),
            citation=(
                'Leimkuhler & Reich 2004, §5; '
                'Senn & Thiel, Angew. Chem. Int. Ed. 48, 1198 (2009), §4.2'
            ),
            context={
                'md_timestep_fs': float(md_timestep),
                'requested_warmup_fs': _warmup_requested,
                'resolved_warmup_fs': float(warmup_timestep),
            },
        )
    first_qmmm_stage_dynamics = make_first_qmmm_stage_dynamics(
        qmmm_handoff_policy,
        transition_thermostat_timecon_fs=qmmm_transition_thermostat_timecon_fs,
        transition_seed=qmmm_transition_seed,
    )

    detail(
        "Stage controls: "
        f"warmup={'on' if enable_qmmm_warmup else 'off'}, "
        f"qmmm_handoff={qmmm_handoff_policy.mode}, "
        f"qmmm_transition_tau={first_qmmm_stage_dynamics.thermostat_timecon_fs:g} fs, "
        f"qmmm_transition_seed={('off' if first_qmmm_stage_dynamics.global_seed is None else int(first_qmmm_stage_dynamics.global_seed))}, "
        f"restart_mode={'stateless_expert' if stateless_restart else 'stateful_default'}, "
        f"mm_restraints={'on' if mm_equil_restraints else 'off'}, "
        f"warmup_restraints={'on' if warmup_restraints else 'off'}"
    )
    detail(
        "MM->QM/MM handoff semantics: "
        f"restart_velocities={'on' if qmmm_handoff_policy.restart_velocities else 'off'}, "
        f"restart_thermostat={'on' if qmmm_handoff_policy.restart_thermostat else 'off'}, "
        f"restart_barostat={'on' if qmmm_handoff_policy.restart_barostat else 'off'}, "
        f"restart_randomg={'on' if qmmm_handoff_policy.restart_randomg else 'off'}, "
        f"transition_init={(first_qmmm_stage_dynamics.initialization_method or 'restart_velocities')}, "
        f"transition_tau={first_qmmm_stage_dynamics.thermostat_timecon_fs:g} fs"
    )
    if not enable_qmmm_warmup:
        warn(
            "QM/MM warmup stage is disabled. The first QM/MM production stage will absorb the MM->QM/MM Hamiltonian switch directly."
        )
    if qmmm_handoff_policy.mode == 'REUSE_VELOCITIES':
        warn(
            "MM->QM/MM handoff policy reuses MM velocities on the new QM/MM Hamiltonian. "
            "This can be useful for continuity experiments, but the warmup stage should be treated as the re-equilibration stage."
        )
    if qmmm_handoff_policy.mode == 'FULL_STATE_CONTINUITY':
        warn(
            "MM->QM/MM handoff policy reuses full MM dynamical state, including thermostat/barostat/RNG state, across the Hamiltonian switch. "
            "This is an expert override and is not the conservative production default."
        )
    if first_qmmm_stage_dynamics.global_seed is None and not qmmm_handoff_policy.restart_randomg:
        warn(
            "First QM/MM stage will rely on CP2K's implicit default RNG seed because explicit GLOBAL SEED was disabled. "
            "Use an explicit seed if you need the handoff initialization policy to be fully visible in the input."
        )

    # Project name
    project_name = "QMMM_PROJECT"
    trajectory_format = DEFAULT_TRAJECTORY_FORMAT
    sampling_config = None
    mm_scale14_policy = requested_mm_scale14_policy
    mm_scale14_cli_specified = any(
        value is not None
        for value in (args.mm_scale14_policy, args.mm_ei_scale14, args.mm_vdw_scale14)
    )
    if interactive:
        project_name = ask("Project name", project_name)
        detail(
            "MM 1-4 scaling will be emitted explicitly in CP2K &FORCEFIELD. "
            "Preserved PRMTOP SCEE/SCNB blocks are kept for topology fidelity only."
        )
        if mm_scale14_cli_specified:
            detail(
                f"Using CLI-selected MM 1-4 scaling: {format_mm_scale14_policy(mm_scale14_policy)}"
            )
        elif ask_yes(
            "Keep recommended AMBER MM 1-4 scaling "
            f"(EI_SCALE14 {DEFAULT_EI_SCALE14:.10f}, VDW_SCALE14 {DEFAULT_VDW_SCALE14:.10f})?",
            default=True,
        ):
            mm_scale14_policy = make_mm_scale14_policy()
        else:
            detail("Available MM 1-4 scaling policies:")
            for mode, desc in MM_SCALE14_POLICIES.items():
                detail(f"  {mode}: {desc}")
            mm_scale14_mode = ask_choice(
                "MM 1-4 scaling policy",
                ('AMBER_RECOMMENDED', 'CP2K_EXPLICIT', 'MANUAL_OVERRIDE'),
                mm_scale14_policy.mode,
            ).upper()
            if mm_scale14_mode == 'AMBER_RECOMMENDED':
                mm_scale14_policy = make_mm_scale14_policy(mm_scale14_mode)
            else:
                mm_scale14_policy = make_mm_scale14_policy(
                    mm_scale14_mode,
                    ei_scale14=ask_float(
                        "MM EI_SCALE14",
                        mm_scale14_policy.ei_scale14,
                        minimum=0.0,
                    ),
                    vdw_scale14=ask_float(
                        "MM VDW_SCALE14",
                        mm_scale14_policy.vdw_scale14,
                        minimum=0.0,
                    ),
                )
        detail(
            "CP2K defaults TRAJECTORY FORMAT to XMOL, but this pipeline recommends "
            "DCD for large periodic biomolecular MD because CP2K documents it as the "
            "binary trajectory format with cell information."
        )
        if ask_yes("Keep recommended trajectory FORMAT DCD?", default=True):
            trajectory_format = DEFAULT_TRAJECTORY_FORMAT
        else:
            trajectory_format = ask_choice(
                "Trajectory FORMAT (DCD recommended; XMOL = text XYZ-style)",
                TRAJECTORY_FORMAT_CHOICES,
                trajectory_format,
            ).upper()
    detail(
        f"Trajectory format for pipeline trajectory stages: {trajectory_format} "
        f"({TRAJECTORY_FORMAT_SUMMARY[trajectory_format]})"
    )
    detail(
        "MM 1-4 scaling policy: "
        f"{format_mm_scale14_policy(mm_scale14_policy)} - {mm_scale14_policy.label}"
    )

    sampling_spec_path = resolve_sampling_spec_path(args.sampling_spec, work_dir) if args.sampling_spec else ''
    if sampling_spec_path:
        try:
            sampling_config = load_sampling_spec(sampling_spec_path)
            validate_sampling_config_indices(sampling_config, topo.natom)
        except Exception as exc:
            error(f"Could not load sampling spec: {exc}")
            sys.exit(1)
        detail(
            f"Advanced sampling spec: {os.path.basename(sampling_config.source_path)} "
            f"({sampling_config.method})"
        )
    elif interactive:
        detail(
            "Advanced free-energy workflows require an external JSON/YAML sampling spec. "
            "CV definitions and umbrella/window schedules are not inferred from topology."
        )
        if ask_yes("Configure advanced free-energy sampling (metadynamics or umbrella)?", default=False):
            requested_path = ask(
                "Sampling spec path (.json/.yaml), or press Enter to generate a boilerplate template",
                "",
            ).strip()
            if not requested_path:
                template_fmt = ask_choice("Sampling template format", ('YAML', 'JSON'), 'YAML').lower()
                template_default = os.path.join(
                    work_dir,
                    f"sampling_spec_template.{ 'json' if template_fmt == 'json' else 'yaml' }",
                )
                template_path = ask("Sampling template output path", template_default).strip() or template_default
                written_template = write_sampling_spec_template(template_path, template_fmt)
                info(f"Wrote sampling template: {written_template}")
                if not ask_yes("Continue this run without advanced sampling?", default=False):
                    info("Populate the sampling template and rerun with --sampling-spec <file>.")
                    sys.exit(0)
            else:
                try:
                    sampling_config = load_sampling_spec(resolve_sampling_spec_path(requested_path, work_dir))
                    validate_sampling_config_indices(sampling_config, topo.natom)
                except Exception as exc:
                    error(f"Could not load sampling spec: {exc}")
                    sys.exit(1)
                detail(
                    f"Advanced sampling spec: {os.path.basename(sampling_config.source_path)} "
                    f"({sampling_config.method})"
                )

    # DFT/QM setup (functional, cutoffs, ADMM, basis set)
    functional = dft_cfg['functional']
    cutoff = dft_cfg['cutoff']
    rel_cutoff = dft_cfg['rel_cutoff']
    mgrid_ngrids = dft_cfg['ngrids']
    hf_max_memory = dft_cfg['hf_max_memory']
    use_admm = dft_cfg['use_admm']
    basis_set = dft_cfg['basis_set']
    qm_cell_padding = qmmm_periodic_policy.qm_cell_padding
    target_multipole_rcut = qmmm_periodic_policy.target_multipole_rcut
    # V4: pass the capability snapshot so an admm-dzp request on CP2K < 8.1
    # (Guidon, Hutter, VandeVondele, JCTC 6, 2348, 2010) is silently but
    # auditably downgraded to cpFIT3 (stable since CP2K 5.1).  Every such
    # substitution is appended to admm_substitutions_log and surfaced in
    # cp2k_compat_report.txt so users retain full provenance.
    admm_aux_basis = resolve_admm_aux_basis(
        qm_elements.keys(), admm_aux_basis,
        use_admm=use_admm, basis_set=basis_set,
        cp2k_capability=cp2k_capability,
        substitutions_log=admm_substitutions_log,
    )
    admm_exch_correction_func = resolve_admm_exch_correction_func(
        functional,
        admm_exch_correction_func,
        use_admm=use_admm,
    )

    if interactive:
        print(f"\n  {C.BOLD}DFT/QM Setup{C.R}")
        print(f"  Available DFT functionals:")
        for key in DFT_FUNCTIONALS:
            print(f"    {C.BOLD}{key:>15s}{C.R}: {DFT_FUNCTIONAL_DESCRIPTIONS[key]}")
        functional = ask_choice("DFT functional", DFT_FUNCTIONALS, functional).upper()
        cutoff = ask_float("MGRID CUTOFF [Ry]", cutoff, minimum=1.0e-8)
        rel_cutoff = ask_float("MGRID REL_CUTOFF [Ry]", rel_cutoff, minimum=1.0e-8)
        use_admm = ask_yes("Enable ADMM acceleration?", default=use_admm)

        print(f"\n  Available QM basis-set presets:")
        for preset_basis in QM_BASIS_SET_PRESETS:
            print(f"    {C.BOLD}{preset_basis}{C.R}")
        basis_choice_default = basis_set if basis_set in QM_BASIS_SET_PRESETS else 'CUSTOM'
        basis_choice = ask_choice(
            "QM basis-set preset (or CUSTOM)",
            list(QM_BASIS_SET_PRESETS) + ['CUSTOM'],
            basis_choice_default,
        ).upper()
        if basis_choice == 'CUSTOM':
            basis_set = ask("Custom QM basis set label", basis_set).strip()
        else:
            basis_set = basis_choice
        mgrid_ngrids = resolve_mgrid_ngrids(basis_set, args.ngrids)
        detail(
            "Select the number of multi-grids (NGRIDS) for density mapping. "
            "Using 5 is highly recommended for standard MOLOPT basis sets as it efficiently "
            "captures diffuse functions (up to 2x speedup) when COMMENSURATE=T."
        )
        mgrid_ngrids = ask_int(
            "Number of multi-grids (NGRIDS)",
            mgrid_ngrids,
            minimum=1,
        )
        if use_admm:
            # ── D.2.b: TM-aware ADMM auxiliary basis recommendation ──
            # Transition-metal QM regions need polarization functions on
            # the auxiliary basis to faithfully represent the d-manifold
            # crystal-field splitting in the HFX correction; cFIT3
            # (no polarization) systematically biases ligand-field
            # excitation energies and metal-centred SOMOs.  cpFIT3 keeps
            # p/d polarization at modest cost (Guidon, Hutter,
            # VandeVondele, JCTC 6, 2348 (2010); Merlot et al., JCP 141,
            # 094104 (2014)).  We surface a recommendation, never modify
            # — admm_aux_basis remains the user's seeded value until the
            # ask_choice prompt records their explicit pick.
            _has_tm_for_admm = bool(
                {str(e).upper() for e in qm_elements.keys()} & TRANSITION_METALS
            )
            detail(
                "Select the ADMM auxiliary basis set for hybrid functional calculations. "
                "cFIT3 is fastest but lacks polarization. cpFIT3 adds polarization functions "
                "for much better biomolecular accuracy at a modest extra cost. "
                "admm-dzp is a newer alternative from BASIS_ADMM_MOLOPT."
            )
            if _has_tm_for_admm and str(admm_aux_basis).strip() == 'cFIT3':
                detail(
                    "Recommendation: QM region contains transition metal(s) "
                    f"({', '.join(sorted({str(e).upper() for e in qm_elements.keys()} & TRANSITION_METALS))}); "
                    "cpFIT3 (with polarization) better resolves the metal "
                    "d-manifold under HFX correction than cFIT3 — choose cpFIT3 "
                    "unless you have a deliberate reason to prefer cFIT3 "
                    "(Guidon et al., JCTC 6, 2348 (2010); Merlot et al., "
                    "JCP 141, 094104 (2014))."
                )
            admm_aux_basis_before = admm_aux_basis
            admm_aux_basis = ask_choice(
                "ADMM auxiliary basis set",
                ADMM_AUX_BASIS_CHOICES,
                admm_aux_basis,
            )
            if (
                _has_tm_for_admm
                and admm_aux_basis_before != admm_aux_basis
            ):
                run_provenance.record(
                    kind='admm_aux_basis_tm_recommendation',
                    severity='recommendation',
                    source='wizard',
                    from_value=admm_aux_basis_before,
                    to_value=admm_aux_basis,
                    accepted=True,
                    reason=(
                        "User chose ADMM aux basis after TM-aware "
                        "polarization recommendation."
                    ),
                    citation='Guidon et al., JCTC 6, 2348 (2010); Merlot et al., JCP 141, 094104 (2014)',
                    context={'has_tm': True},
                )
        if use_admm and str(functional).upper() in HYBRID_DFT_FUNCTIONALS:
            exch_prompt, exch_prompt_default = admm_exch_correction_prompt(functional)
            admm_exch_correction_func = ask_choice(
                exch_prompt,
                ADMM_EXCH_CORRECTION_CHOICES,
                exch_prompt_default,
            )
        if str(functional).upper() in HYBRID_DFT_FUNCTIONALS:
            detail(
                "HF MAX_MEMORY is a per-MPI-rank CP2K HFX limit, not a whole-job memory value. "
                "Only memory left after helper arrays is available for integral storage."
            )
            if args.hf_max_memory is not None:
                detail(f"Using CLI-selected HF MAX_MEMORY: {hf_max_memory} per MPI rank")
            elif ask_yes(
                f"Keep conservative HF MAX_MEMORY {hf_max_memory} per MPI rank?",
                default=True,
            ):
                hf_max_memory = validate_hf_max_memory(hf_max_memory)
            else:
                hf_max_memory = ask_int(
                    "HF MAX_MEMORY [per MPI rank]",
                    hf_max_memory,
                    minimum=1,
                )
        detail(
            "QM/MM electrostatic coupling uses ECOUPL GAUSS with a GEEP library. "
            "Higher USE_GEEP_LIB improves the MM electrostatic potential seen by the QM region "
            "but increases computational cost."
        )
        detail("Typical values: 7 fast/rough, 9-12 reliable biomolecular production, 15 high precision.")
        qmmm_geep_lib = ask_int(
            "Select the number of Gaussians for the QM/MM electrostatic coupling (GEEP library)",
            qmmm_geep_lib,
            minimum=1,
        )
        detail(
            "Periodic QM/MM MULTIPOLE RCUT is limited by half the QM cell. "
            "This pipeline sizes the QM cell from both padding and the target real-space cutoff."
        )
        if (args.qm_cell_padding is not None) or (args.qmmm_multipole_rcut is not None):
            detail(
                "Using CLI-selected periodic QM/MM settings: "
                f"padding {qm_cell_padding:.1f} A, target MULTIPOLE RCUT {target_multipole_rcut:.1f} A"
            )
        elif ask_yes(
            "Keep recommended periodic QM/MM defaults (padding 6.0 A, target MULTIPOLE RCUT 8.0 A)?",
            default=True,
        ):
            qmmm_periodic_policy = make_qmmm_periodic_policy()
            qm_cell_padding = qmmm_periodic_policy.qm_cell_padding
            target_multipole_rcut = qmmm_periodic_policy.target_multipole_rcut
        else:
            qm_cell_padding = ask_float(
                "QM-cell padding [angstrom]",
                qm_cell_padding,
                minimum=0.1,
            )
            target_multipole_rcut = ask_float(
                "Target QMMM MULTIPOLE RCUT [angstrom]",
                target_multipole_rcut,
                minimum=0.1,
            )
            qmmm_periodic_policy = make_qmmm_periodic_policy(
                qm_cell_padding=qm_cell_padding,
                target_multipole_rcut=target_multipole_rcut,
            )

    dft_cfg = resolve_dft_qm_settings(
        functional=functional,
        cutoff=cutoff,
        rel_cutoff=rel_cutoff,
        use_admm=use_admm,
        basis_set=basis_set,
        ngrids=mgrid_ngrids,
        hf_max_memory=hf_max_memory,
    )
    functional = dft_cfg['functional']
    cutoff = dft_cfg['cutoff']
    rel_cutoff = dft_cfg['rel_cutoff']
    mgrid_ngrids = dft_cfg['ngrids']
    hf_max_memory = dft_cfg['hf_max_memory']
    use_admm = dft_cfg['use_admm']
    basis_set = dft_cfg['basis_set']
    qmmm_geep_lib = validate_qmmm_geep_lib(qmmm_geep_lib)
    # V4: same capability-aware ADMM resolution as the non-interactive
    # branch above (see in-place comment at the earlier call site).  The
    # two call sites are structurally identical; both feed the single
    # shared admm_substitutions_log and cp2k_capability objects so that
    # cp2k_compat_report.txt is authoritative regardless of path.
    admm_aux_basis = resolve_admm_aux_basis(
        qm_elements.keys(), admm_aux_basis,
        use_admm=use_admm, basis_set=basis_set,
        cp2k_capability=cp2k_capability,
        substitutions_log=admm_substitutions_log,
    )
    admm_exch_correction_func = resolve_admm_exch_correction_func(
        functional,
        admm_exch_correction_func,
        use_admm=use_admm,
    )
    if rel_cutoff > cutoff:
        warn(
            f"REL_CUTOFF ({rel_cutoff:g} Ry) exceeds CUTOFF ({cutoff:g} Ry). "
            "This is unusual; verify that this is intentional."
        )
    # ── D.4.a: MGRID CUTOFF / REL_CUTOFF threshold advisory ────────────
    # Run after rel_cutoff/cutoff sanity but before downstream selection
    # so the user sees the under-convergence warnings exactly once,
    # whether the cutoffs arrived via CLI defaults or the wizard.  All
    # findings are advisories — the original values are preserved per
    # feedback_no_silent_modifications.
    _mgrid_balance = evaluate_mgrid_cutoff_balance(
        cutoff_ry=cutoff,
        rel_cutoff_ry=rel_cutoff,
        basis_set=basis_set,
        use_admm=use_admm,
        has_hybrid=(str(functional).upper() in HYBRID_DFT_FUNCTIONALS),
    )
    for _msg in _mgrid_balance['messages']:
        warn(_msg)
    if _mgrid_balance['messages']:
        run_provenance.record(
            kind='mgrid_cutoff_balance',
            severity='recommendation',
            source='audit',
            from_value=f"cutoff={cutoff:g} Ry, rel_cutoff={rel_cutoff:g} Ry",
            to_value=(
                f"cutoff≥{MGRID_CUTOFF_RECOMMENDED_FLOOR_RY:g}, "
                f"rel_cutoff≥{MGRID_REL_CUTOFF_PRODUCTION_DEFAULT_RY:g}"
            ),
            accepted=None,
            reason="MGRID CUTOFF/REL_CUTOFF below conservative MOLOPT/GTH convergence floor",
            citation='VandeVondele-Hutter, JCP 127, 114105 (2007); CP2K Manual §FORCE_EVAL/DFT/MGRID',
            context={
                'basis_set': basis_set,
                'use_admm': bool(use_admm),
                'is_hybrid': str(functional).upper() in HYBRID_DFT_FUNCTIONALS,
                'n_findings': len(_mgrid_balance['messages']),
            },
        )
    if qmmm_geep_lib < 9:
        warn(
            f"USE_GEEP_LIB={qmmm_geep_lib} is faster but relatively coarse for biomolecular QM/MM electrostatics. "
            "Use 9-12 for more reliable production runs."
        )
    if is_standard_molopt_basis_set(basis_set) and int(mgrid_ngrids) < MOLOPT_DIFFUSE_MGRID_NGRIDS:
        warn(
            f"NGRIDS={mgrid_ngrids} is lower than the recommended {MOLOPT_DIFFUSE_MGRID_NGRIDS} "
            f"for standard MOLOPT basis set {basis_set}. This can leave diffuse-grid speedups on the table."
        )
    recommended_admm_exch_correction = recommended_admm_exch_correction_func(functional)
    if (
        use_admm
        and recommended_admm_exch_correction
        and admm_exch_correction_func
        and admm_exch_correction_func != recommended_admm_exch_correction
    ):
        warn(
            f"EXCH_CORRECTION_FUNC={admm_exch_correction_func} does not match the recommended "
            f"{recommended_admm_exch_correction} exchange correction for {functional}. "
            "This can introduce systematic ADMM SCF errors."
        )
    # ── D.2.b: TM-aware ADMM aux-basis residual advisory ─────────────────
    # Even after the wizard prompt, the user may still be on cFIT3 (no
    # polarization) with a transition-metal QM region.  Emit a single
    # WARN here so non-interactive users (who never saw the wizard
    # detail) are told too — the value itself is preserved per
    # feedback_no_silent_modifications.
    _has_tm_for_admm_final = bool(
        {str(e).upper() for e in qm_elements.keys()} & TRANSITION_METALS
    )
    if (
        use_admm
        and admm_aux_basis is not None
        and str(admm_aux_basis).strip() == 'cFIT3'
        and _has_tm_for_admm_final
    ):
        _tm_present = sorted(
            {str(e).upper() for e in qm_elements.keys()} & TRANSITION_METALS
        )
        warn(
            f"ADMM aux basis cFIT3 lacks polarization; QM region contains "
            f"transition metal(s) ({', '.join(_tm_present)}). "
            "cpFIT3 better resolves the metal d-manifold under HFX "
            "correction. Override --admm-aux-basis cpFIT3 (or pick cpFIT3 "
            "interactively) unless the cost difference is critical "
            "(Guidon et al., JCTC 6, 2348 (2010); "
            "Merlot et al., JCP 141, 094104 (2014))."
        )
        run_provenance.record(
            kind='admm_aux_basis_tm_recommendation',
            severity='recommendation',
            source='audit',
            from_value='cFIT3',
            to_value='cpFIT3 (recommended)',
            accepted=False,
            reason=(
                "Transition metal in QM region with cFIT3 (no polarization); "
                "cpFIT3 recommended for HFX correction fidelity."
            ),
            citation='Guidon et al., JCTC 6, 2348 (2010); Merlot et al., JCP 141, 094104 (2014)',
            context={'transition_metals_present': ', '.join(_tm_present)},
        )
    detail(
        "DFT/QM settings: "
        f"functional={functional}, basis_set={basis_set}, "
        f"CUTOFF={cutoff:g} Ry, REL_CUTOFF={rel_cutoff:g} Ry, NGRIDS={int(mgrid_ngrids)}, "
        f"ADMM={'on' if use_admm else 'off'}, "
        f"{('ADMM_AUX=' + admm_aux_basis + ', ') if use_admm and admm_aux_basis else ''}"
        f"{('ADMM_EXCH_CORR=' + admm_exch_correction_func + ', ') if use_admm and admm_exch_correction_func else ''}"
        f"USE_GEEP_LIB={qmmm_geep_lib}"
    )
    detail(
        "Periodic QM electrostatics will be written explicitly as "
        "&DFT/&POISSON PERIODIC XYZ with PSOLVER PERIODIC."
    )
    detail(
        "Periodic QM/MM electrostatics policy: "
        f"padding {qmmm_periodic_policy.qm_cell_padding:.1f} A, "
        f"target MULTIPOLE RCUT {qmmm_periodic_policy.target_multipole_rcut:.1f} A."
    )
    detail(
        "QM/MM MD will write &QS EXTRAPOLATION PS / EXTRAPOLATION_ORDER 3 "
        "explicitly, following CP2K's MD-specific recommendation instead of "
        "inheriting the generic QS default ASPC/3."
    )

    # SCF setup (interactive, system-aware recommendations)
    rec_profile, rec_reason = recommended_scf_profile(qm_elements.keys(), functional, len(qm_indices))
    scf_profile_name = scf_profile_override or rec_profile
    scf_cfg = dict(SCF_PROFILES[rec_profile])
    if scf_profile_override:
        scf_cfg = dict(SCF_PROFILES[scf_profile_name])
    if scf_guess_override:
        scf_cfg['scf_guess'] = scf_guess_override
    # ── A.2.a: baseline snapshot for promotion-overwrite detection ──────
    # Capture the *unmodified* profile defaults so that when an SCF
    # profile promotion fires later, we can identify which scf_cfg keys
    # the user has explicitly tuned (in the wizard or via CLI) and prompt
    # for permission before the promotion overwrites them.  Tracking this
    # at the entry of the SCF setup stage gives the strongest baseline
    # — anything that diverges later is unambiguously a user edit.
    _scf_cfg_baseline = dict(scf_cfg)
    ot_minimizer = DEFAULT_OT_MINIMIZER
    ot_preconditioner = DEFAULT_OT_PRECONDITIONER
    # D.2.a: ADVANCED-mode operators may override the auto-selected ADMM
    # purification method.  Non-ADVANCED runs keep None → pipeline default
    # (MO_DIAG for OT SCF, NONE for DIAG SCF).
    admm_purification_override = None
    ot_energy_gap = DEFAULT_OT_ENERGY_GAP
    ot_stepsize_policy = make_ot_stepsize_policy(
        mode=ot_stepsize_policy.mode,
        stepsize=(None if ot_stepsize_policy.mode == 'AUTO' else ot_stepsize_policy.stepsize),
        ot_preconditioner=ot_preconditioner,
    )

    if interactive:
        print(f"\n  {C.BOLD}SCF Setup Wizard{C.R}")
        detail(f"Functional: {functional}")
        detail(f"QM atoms: {len(qm_indices)}")
        detail(f"Detected QM elements: {', '.join(sorted(qm_elements.keys()))}")
        info(f"Recommended: {rec_profile} — {SCF_PROFILES[rec_profile]['label']}")
        detail(f"Reason: {rec_reason}")
        print()
        detail("Available electronic-structure profiles:")
        for key in SCF_PROFILE_DISPLAY_ORDER:
            prof = SCF_PROFILES[key]
            marker = f"  {C.GREEN}[recommended]{C.R}" if key == rec_profile else ""
            detail(f"  {C.BOLD}{key}{C.R}: {prof['label']}{marker}")
            detail(f"      {prof['description']}")
        print()

        if scf_profile_override:
            detail(
                f"Using CLI-selected SCF profile {scf_profile_name} "
                f"({SCF_PROFILES[scf_profile_name]['label']})."
            )
        else:
            scf_profile_name = ask_choice(
                "Select SCF profile",
                list(SCF_PROFILE_DISPLAY_ORDER),
                rec_profile,
            ).upper()
            scf_profile_name = _validate_scf_profile_key(scf_profile_name)
            scf_cfg = dict(SCF_PROFILES[scf_profile_name])
            if scf_guess_override:
                scf_cfg['scf_guess'] = scf_guess_override
        # A.2.a: refresh the baseline whenever the user picks a different
        # profile interactively — wizard tail edits below should be
        # measured against the *new* profile's defaults, not the
        # recommender's preliminary choice.
        _scf_cfg_baseline = dict(scf_cfg)

        is_advanced = (scf_profile_name == 'ADVANCED')
        is_diag_profile = (scf_cfg.get('engine') == 'DIAG')

        if is_advanced or ask_yes("Edit SCF numeric parameters?", default=False):
            scf_cfg['max_scf'] = ask_int("SCF MAX_SCF", scf_cfg['max_scf'], minimum=1)
            scf_cfg['eps_scf'] = ask_float("SCF EPS_SCF", scf_cfg['eps_scf'], minimum=1.0e-12)
            # ── A.3.b: SCF_GUESS recommendations (MOPAC for hard cases) ──
            # CP2K supports several initial-guess flavours
            # (CP2K Manual §FORCE_EVAL/DFT/SCF/SCF_GUESS):
            #   * ATOMIC  — superposition of atomic densities; cheap,
            #               works for most closed-shell organic systems.
            #   * RESTART — re-use a wavefunction file; preferred when
            #               continuing from a converged calculation.
            #   * MOPAC   — semi-empirical (PM6/PM7) pre-SCF; provides a
            #               non-trivial initial wavefunction with
            #               appropriate spin distribution.  Recommended
            #               for transition-metal d-manifolds where
            #               ATOMIC oscillates between charge-transfer
            #               states.  Refs: Stewart, J. Mol. Mod. 13, 1173
            #               (2007) (PM6); J. Mol. Mod. 19, 1 (2013) (PM7).
            #   * CORE    — bare-Hamiltonian; rarely useful.
            # The multiplicity is not yet resolved at the SCF wizard
            # stage, so the recommendation here is keyed off transition-
            # metal presence only; an additional open-shell-driven WARN
            # fires after the spin-state stage when multiplicity>1 still
            # leaves SCF_GUESS=ATOMIC (see post-spin block below).
            _scf_guess_choices = ['ATOMIC', 'RESTART', 'MOPAC', 'CORE']
            _has_tm_for_guess_wizard = bool(
                {str(e).upper() for e in qm_elements.keys()} & TRANSITION_METALS
            )
            if _has_tm_for_guess_wizard:
                detail(
                    "Recommendation: SCF_GUESS=MOPAC starts from a PM6/PM7 "
                    "semi-empirical wavefunction (transition metal in QM "
                    "region); this typically converges faster than ATOMIC "
                    "and avoids the charge-transfer oscillations that "
                    "plague TM systems with the bare ATOMIC superposition. "
                    "Refs: Stewart, J. Mol. Mod. 13, 1173 (2007) (PM6); "
                    "J. Mol. Mod. 19, 1 (2013) (PM7)."
                )
            scf_guess_before = scf_cfg['scf_guess']
            scf_cfg['scf_guess'] = ask_choice("SCF_GUESS", _scf_guess_choices, scf_cfg['scf_guess']).upper()
            if (
                _has_tm_for_guess_wizard
                and scf_guess_before != scf_cfg['scf_guess']
            ):
                run_provenance.record(
                    kind='scf_guess_recommendation',
                    severity='recommendation',
                    source='wizard',
                    from_value=scf_guess_before,
                    to_value=scf_cfg['scf_guess'],
                    accepted=True,
                    reason='User changed SCF_GUESS after TM-aware MOPAC recommendation.',
                    citation='Stewart, J. Mol. Mod. 13, 1173 (2007); 19, 1 (2013)',
                )
            if is_advanced:
                cholesky_default = normalize_scf_cholesky(scf_cfg.get('cholesky')) or 'DEFAULT'
                scf_cfg['cholesky'] = ask_choice(
                    "SCF CHOLESKY mode (ADVANCED only)",
                    ['DEFAULT', 'RESTORE', 'INVERSE', 'OFF'],
                    cholesky_default,
                ).upper()
                qs_eps_mode_default = (
                    'TIGHTER'
                    if normalize_qs_eps_default(scf_cfg.get('qs_eps_default')) is not None
                    else 'DEFAULT'
                )
                qs_eps_mode = ask_choice(
                    "Quickstep EPS_DEFAULT mode (ADVANCED only)",
                    ['DEFAULT', 'TIGHTER'],
                    qs_eps_mode_default,
                ).upper()
                if qs_eps_mode == 'TIGHTER':
                    qs_eps_default = normalize_qs_eps_default(scf_cfg.get('qs_eps_default'))
                    if qs_eps_default is None or qs_eps_default > QUICKSTEP_EPS_DEFAULT:
                        qs_eps_default = 1.0e-12
                    scf_cfg['qs_eps_default'] = ask_float(
                        f"Quickstep EPS_DEFAULT (<= {QUICKSTEP_EPS_DEFAULT:.1E})",
                        qs_eps_default,
                        minimum=1.0e-16,
                    )
                    while float(scf_cfg['qs_eps_default']) > QUICKSTEP_EPS_DEFAULT:
                        warn(
                            f"Quickstep EPS_DEFAULT must be <= {QUICKSTEP_EPS_DEFAULT:.1E} "
                            "(tighter than CP2K default)."
                        )
                        scf_cfg['qs_eps_default'] = ask_float(
                            f"Quickstep EPS_DEFAULT (<= {QUICKSTEP_EPS_DEFAULT:.1E})",
                            float(scf_cfg['qs_eps_default']),
                            minimum=1.0e-16,
                        )
                else:
                    scf_cfg['qs_eps_default'] = None
                # ── D.2.a: ADMM purification override (ADVANCED only) ──
                # Only meaningful when ADMM is actually in use.  The default
                # entry keeps the engine-matched pick (MO_DIAG/OT,
                # NONE/DIAG); NON_PURIFICATION is the advanced-benchmarking
                # option documented by Merlot et al. JCP 141, 094104 (2014).
                if use_admm:
                    _admm_purif_choices = ('DEFAULT',) + ADMM_PURIFICATION_METHODS
                    _admm_purif_pick = ask_choice(
                        "ADMM_PURIFICATION_METHOD (ADVANCED only; DEFAULT keeps "
                        "pipeline's engine-matched choice — MO_DIAG for OT, "
                        "NONE for DIAG SCF)",
                        list(_admm_purif_choices),
                        'DEFAULT',
                    ).upper()
                    if _admm_purif_pick != 'DEFAULT':
                        admm_purification_override = validate_admm_purification_override(_admm_purif_pick)
                        run_provenance.record(
                            kind='admm_purification_override',
                            severity='recommendation',
                            source='wizard',
                            from_value='engine-matched (MO_DIAG/OT, NONE/DIAG)',
                            to_value=admm_purification_override,
                            accepted=True,
                            reason=(
                                "ADVANCED operator overrode auto-selected ADMM "
                                "purification method."
                            ),
                            citation=(
                                "Guidon, Hutter, VandeVondele, JCTC 6, 2348 "
                                "(2010); Merlot et al., JCP 141, 094104 (2014)"
                            ),
                        )
            # ADDED_MOS and MIXING are only relevant for DIAG-engine profiles.
            if is_diag_profile:
                scf_cfg['added_mos'] = ask_int("SCF ADDED_MOS", scf_cfg['added_mos'], minimum=0)
                scf_cfg['mixing_method'] = ask_choice(
                    "MIXING METHOD",
                    ['DIRECT_P_MIXING', 'BROYDEN_MIXING'],
                    scf_cfg['mixing_method'],
                ).upper()
                scf_cfg['mixing_alpha'] = ask_float("MIXING ALPHA (0-1)", scf_cfg['mixing_alpha'], minimum=0.0)
                while scf_cfg['mixing_alpha'] > 1.0:
                    warn("MIXING ALPHA should be <= 1.0")
                    scf_cfg['mixing_alpha'] = ask_float("MIXING ALPHA (0-1)", scf_cfg['mixing_alpha'], minimum=0.0)
                scf_cfg['nbroyden'] = ask_int("MIXING NBROYDEN", scf_cfg['nbroyden'], minimum=1)
            scf_cfg['outer_max_scf'] = ask_int("OUTER_SCF MAX_SCF", scf_cfg['outer_max_scf'], minimum=1)
            scf_cfg['outer_eps_scf'] = ask_float("OUTER_SCF EPS_SCF", scf_cfg['outer_eps_scf'], minimum=1.0e-12)

        if float(scf_cfg['outer_eps_scf']) > float(scf_cfg['eps_scf']):
            warn("OUTER_SCF EPS_SCF is looser than inner SCF EPS_SCF. Tightening OUTER_SCF EPS_SCF to match.")
            scf_cfg['outer_eps_scf'] = float(scf_cfg['eps_scf'])
    else:
        if scf_profile_override:
            detail(
                f"Using CLI-selected SCF profile {scf_profile_name} "
                f"({SCF_PROFILES[scf_profile_name]['label']})"
            )
        else:
            detail(
                f"Using auto-selected SCF profile {scf_profile_name} "
                f"({SCF_PROFILES[scf_profile_name]['label']}; reason: {rec_reason})"
            )
        if scf_guess_override:
            detail(f"Using CLI-selected SCF_GUESS {scf_guess_override}")
    # Enforce OUTER_SCF EPS_SCF <= inner EPS_SCF in all modes.
    if float(scf_cfg['outer_eps_scf']) > float(scf_cfg['eps_scf']):
        scf_cfg['outer_eps_scf'] = float(scf_cfg['eps_scf'])
    if scf_profile_name != 'ADVANCED':
        # Non-ADVANCED profiles rely on CP2K's default CHOLESKY mode.
        scf_cfg['cholesky'] = None
        # Non-ADVANCED profiles use CP2K Quickstep EPS_DEFAULT default.
        scf_cfg['qs_eps_default'] = None

    # ── Boundary validation of the resolved SCF cfg (A.2.b) ──────────────
    # Run once after every interactive/CLI adjustment is finalised and
    # before the SCF block is emitted.  Catches values that slipped past
    # individual ask_* prompts (e.g. CLI overrides) and surfaces them with
    # actionable error text rather than letting CP2K reject the input or
    # silently misconverge.  Engine selection drives which keys apply
    # (mixing/added_mos are DIAG-only; OT ignores them in the emitter).
    _final_engine_for_validation = SCF_PROFILES.get(scf_profile_name, {}).get('engine', 'OT')
    validate_scf_cfg(scf_cfg, engine=_final_engine_for_validation)

    detail(
        "SCF final settings: "
        f"MAX_SCF={scf_cfg['max_scf']}, EPS_SCF={float(scf_cfg['eps_scf']):.1E}, "
        f"MIXING={scf_cfg['mixing_method']}, ALPHA={float(scf_cfg['mixing_alpha']):.2f}, "
        f"OUTER_MAX_SCF={scf_cfg['outer_max_scf']}, OUTER_EPS_SCF={float(scf_cfg['outer_eps_scf']):.1E}, "
        f"CHOLESKY={normalize_scf_cholesky(scf_cfg.get('cholesky')) or 'CP2K default (RESTORE)'}, "
        f"QS_EPS_DEFAULT={float(normalize_qs_eps_default(scf_cfg.get('qs_eps_default')) or QUICKSTEP_EPS_DEFAULT):.1E}"
    )

    # If .mdin provided the charge, use it; otherwise ask interactively (defaulting to 0
    # in non-interactive mode). A wrong QM charge gives the wrong electron count in &DFT.
    if mdin_meta.get('qmcharge') is not None:
        qm_charge = int(mdin_meta['qmcharge'])
        detail(f"QM charge for CP2K &DFT: {qm_charge} (from mdin)")
    elif interactive:
        qm_charge = ask_int("QM region total charge [e]", 0)
        detail(f"QM charge for CP2K &DFT: {qm_charge} (user-supplied)")
    else:
        qm_charge = 0
        warn("No QM charge found in .mdin and running non-interactive; defaulting to 0")
    qm_cell_abc, qm_cell_meta = compute_qm_cell(
        qm_indices,
        coords_rst7,
        padding=qmmm_periodic_policy.qm_cell_padding,
        box_dims=box,
        qmmm_periodic_policy=qmmm_periodic_policy,
    )
    qmmm_periodic_meta = evaluate_qmmm_periodic_electrostatics(qm_cell_abc, qmmm_periodic_policy)
    # ── C.3.a: periodic QM/MM RCUT short-of-default advisory ────────────
    # Laino, Mohamed, Curioni & Hutter (JCTC 2, 1370 (2006)) document a
    # GEEP-periodic real-space cutoff of ~8 Å as the safe default for
    # condensed-phase QM/MM electrostatics; below that, dipole/quadrupole
    # truncation in the multipole sum starts to perturb the embedded QM
    # potential and observed forces.  The pre-existing ``rcut_relaxed``
    # warning (emitted later via the global warnings list) only fires
    # when the QM cell *forces* a reduction; here we additionally advise
    # whenever the *target* requested by the user (CLI or wizard) is
    # itself below 8 Å, which is otherwise silent.  The resolved
    # effective RCUT is reported alongside so reviewers see both numbers.
    _target_rcut_advisory = float(qmmm_periodic_meta.get('target_rcut', 0.0))
    _effective_rcut_advisory = float(qmmm_periodic_meta.get('effective_rcut', 0.0))
    if _target_rcut_advisory < 8.0 - 1.0e-6:
        warn(
            f"Periodic QM/MM target MULTIPOLE RCUT is {_target_rcut_advisory:.1f} Å, "
            "below the Laino 2006 documented default (8.0 Å). "
            "Reduced cutoffs increase dipole/quadrupole truncation error in "
            "the embedded QM potential. Verify this is intentional; otherwise "
            "rerun and accept the recommended periodic QM/MM defaults "
            "(JCTC 2, 1370 (2006))."
        )
        run_provenance.record(
            kind='qmmm_periodic_rcut',
            severity='recommendation',
            source='audit',
            from_value=f"target_rcut={_target_rcut_advisory:.2f} Å",
            to_value="recommended ≥8.0 Å",
            accepted=None,
            reason=(
                "Target periodic QM/MM MULTIPOLE RCUT is below the "
                "Laino 2006 documented default; multipole truncation "
                "error grows below ~8 Å."
            ),
            citation='Laino et al., JCTC 2, 1370 (2006)',
            context={
                'effective_rcut': f"{_effective_rcut_advisory:.2f}",
                'rcut_relaxed': bool(qmmm_periodic_meta.get('rcut_relaxed', False)),
            },
        )
    # ── E.1.b: SPME (classical MM-side) tolerance advisory + override ────
    # Kolafa & Perram (Mol. Simul. 9, 351, 1992) leading-order tail errors
    # for the split-Ewald sum: real-space ~ erfc(α·r_c)/r_c, reciprocal
    # ~ (2α/√π)·exp(-k²/4α²)/k where k_max = π·GMAX/L.  A well-balanced
    # PME keeps both tails ≲ target tolerance.  We re-run the estimator
    # here against the defaults (ALPHA, RCUT_NB, and the box-derived GMAX)
    # so the user sees the same numbers that will land as &POISSON
    # comments in the emitted input — but ahead of emission, where a
    # consent prompt can still change them (interactive mode only).
    # Policy (feedback_no_silent_modifications): non-interactive runs
    # WARN + record and proceed with defaults; interactive runs offer an
    # opt-in override that must be explicitly accepted.
    try:
        _, _, _pme_gmax_a, _pme_gmax_b, _pme_gmax_c = _resolve_box_params(box)
    except Exception:
        _pme_gmax_a = _pme_gmax_b = _pme_gmax_c = None
    try:
        _pme_box_edges = (
            None if not box else
            tuple(_normalize_box_dims(box)[:3]) if _normalize_box_dims(box) else None
        )
    except Exception:
        _pme_box_edges = None
    if (_pme_box_edges and _pme_gmax_a and _pme_gmax_b and _pme_gmax_c):
        _pme_balance = evaluate_pme_tolerance_balance(
            _MM_EMIT_PME_ALPHA,
            _MM_EMIT_PME_RCUT_NB,
            _pme_box_edges,
            (_pme_gmax_a, _pme_gmax_b, _pme_gmax_c),
        )
        _real_over = (
            _pme_balance['real_error'] is not None and
            _pme_balance['real_error'] > PME_WARN_THRESHOLD_TOLERANCE
        )
        _recip_over = bool(_pme_balance['under_density_axes'])
        if _real_over or _recip_over:
            warn(
                "SPME tolerance diagnostic flags an imbalance with the default "
                f"ALPHA={_MM_EMIT_PME_ALPHA:.2f} Å⁻¹ and RCUT_NB="
                f"{_MM_EMIT_PME_RCUT_NB:.1f} Å:"
            )
            for _msg in _pme_balance['messages']:
                warn(f"  {_msg}")
            _pme_override_alpha = None
            _pme_override_rcut = None
            if interactive:
                info(
                    "You may supply tightened ALPHA and/or RCUT_NB to rebalance "
                    "the real- and reciprocal-space errors.  Leave at default "
                    "to keep the current values (the diagnostic message will "
                    "still land as a comment in the emitted input)."
                )
                # Guard: aggressive α without commensurate GMAX growth makes
                # the reciprocal tail worse — the prompt is informative only;
                # the user retains full judgement over the numbers.
                if ask_yes(
                    "Override SPME ALPHA for improved tolerance?",
                    default=False,
                ):
                    _pme_override_alpha = float(ask_float(
                        f"  ALPHA [Å⁻¹] (default {_MM_EMIT_PME_ALPHA:.2f}; "
                        "raising α tightens the real-space tail but demands "
                        "larger GMAX for reciprocal-space accuracy)",
                        default=_MM_EMIT_PME_ALPHA,
                        minimum=1.0e-3,
                    ))
                if ask_yes(
                    "Override SPME RCUT_NB (and matching FORCEFIELD cutoff)?",
                    default=False,
                ):
                    _pme_override_rcut = float(ask_float(
                        f"  RCUT_NB [Å] (default {_MM_EMIT_PME_RCUT_NB:.1f}; "
                        "raising r_c tightens the real-space tail at the cost "
                        "of pair-list size)",
                        default=_MM_EMIT_PME_RCUT_NB,
                        minimum=1.0,
                    ))
                if _pme_override_alpha is not None or _pme_override_rcut is not None:
                    # Assign module-level overrides so _emit_mm_section()
                    # picks them up when it serializes &MM/&POISSON/&EWALD.
                    global _MM_EMIT_PME_ALPHA_OVERRIDE, _MM_EMIT_PME_RCUT_NB_OVERRIDE
                    if _pme_override_alpha is not None:
                        _MM_EMIT_PME_ALPHA_OVERRIDE = _pme_override_alpha
                    if _pme_override_rcut is not None:
                        _MM_EMIT_PME_RCUT_NB_OVERRIDE = _pme_override_rcut
                    _eff_alpha = _effective_pme_alpha()
                    _eff_rcut = _effective_pme_rcut_nb()
                    info(
                        f"Applied SPME overrides: ALPHA={_eff_alpha:.3f} Å⁻¹, "
                        f"RCUT_NB={_eff_rcut:.2f} Å (defaults "
                        f"{_MM_EMIT_PME_ALPHA:.2f}/{_MM_EMIT_PME_RCUT_NB:.1f})."
                    )
                    # Recompute diagnostic to report the post-override balance.
                    _post = evaluate_pme_tolerance_balance(
                        _eff_alpha, _eff_rcut, _pme_box_edges,
                        (_pme_gmax_a, _pme_gmax_b, _pme_gmax_c),
                    )
                    for _msg in _post['messages']:
                        detail(f"  post-override: {_msg}")
            run_provenance.record(
                kind='pme_tolerance_balance',
                severity='recommendation',
                source='user' if (
                    _pme_override_alpha is not None or _pme_override_rcut is not None
                ) else 'auto',
                from_value=(
                    f"alpha={_MM_EMIT_PME_ALPHA:.3f} Å⁻¹, "
                    f"rcut_nb={_MM_EMIT_PME_RCUT_NB:.2f} Å, "
                    f"real_err={_pme_balance['real_error']:.2e}, "
                    f"worst_recip_err={(_pme_balance['worst_recip_error'] or 0.0):.2e}"
                ),
                to_value=(
                    f"alpha={_effective_pme_alpha():.3f} Å⁻¹, "
                    f"rcut_nb={_effective_pme_rcut_nb():.2f} Å"
                ),
                accepted=(
                    True if (_pme_override_alpha is not None or _pme_override_rcut is not None)
                    else (False if interactive else None)
                ),
                reason=(
                    "Kolafa-Perram leading-order SPME tails flag an "
                    "imbalance against the default ALPHA/RCUT_NB; "
                    + (
                        "user-supplied overrides applied."
                        if (_pme_override_alpha is not None or _pme_override_rcut is not None)
                        else (
                            "user declined override; defaults retained."
                            if interactive
                            else "non-interactive mode — defaults retained per policy."
                        )
                    )
                ),
                citation=(
                    "Kolafa & Perram, Mol. Simul. 9, 351 (1992); "
                    "Essmann et al., J. Chem. Phys. 103, 8577 (1995)"
                ),
                context={
                    'box_edges_A': [f"{L:.2f}" for L in _pme_box_edges],
                    'gmax': [int(_pme_gmax_a), int(_pme_gmax_b), int(_pme_gmax_c)],
                    'warn_threshold': f"{PME_WARN_THRESHOLD_TOLERANCE:.1e}",
                    'target_tolerance': f"{PME_TARGET_ABSOLUTE_TOLERANCE:.1e}",
                    'real_over_threshold': bool(_real_over),
                    'recip_over_threshold': bool(_recip_over),
                },
            )
    if qm_cell_meta.get('fallback'):
        warn("Could not derive QM cell from coordinates; using fallback 25.0 25.0 25.0 Å")
    else:
        sx, sy, sz = qm_cell_meta['span']
        detail(
            "QM span before padding: "
            f"{sx:.2f} x {sy:.2f} x {sz:.2f} Å "
            f"(padding {qm_cell_meta['padding']:.1f} Å)"
        )
        if qm_cell_meta.get('expanded_for_target_rcut'):
            detail(
                "QM cell was enlarged beyond raw padding to support the periodic MULTIPOLE target "
                f"({qmmm_periodic_policy.target_multipole_rcut:.1f} A)."
            )
        if qm_cell_meta.get('box_limited_axes'):
            warn(
                "QM cell growth was limited by the MM box on axes "
                f"{', '.join(qm_cell_meta['box_limited_axes'])}. "
                "Padding alone cannot recover longer-range periodic QM/MM electrostatics once the box is the limiter."
            )
    if qm_cell_meta.get('imaging_suspect'):
        error(
            "QM atom bounding-box span exceeds half the simulation box in at "
            "least one dimension.  This almost certainly means the coordinates "
            "are wrapped and the QM region is split across a periodic boundary, "
            "which produces a grossly oversized (and wrong) QM cell."
        )
        error(
            "REMEDY: Image/recenter coordinates before running this script. "
            "For example, with cpptraj:\n"
            "    parm system.prmtop\n"
            "    trajin system.rst7\n"
            "    autoimage\n"
            "    trajout system_imaged.rst7 restart\n"
            "    run\n"
            "Then re-run charmmgui2cp2k.py with the imaged restart file."
        )
        if not interactive:
            raise SystemExit("Aborting: QM atoms appear split across PBC (see above).")
        if not ask_yes("Continue anyway with the current (likely wrong) QM cell?", default=False):
            raise SystemExit("Aborted by user — please image coordinates first.")
    detail(f"Computed QM cell ABC: {qm_cell_abc}")
    # Validate QM cell does not exceed MM cell (periodic QM/MM sanity).
    if box and not qm_cell_meta.get('fallback'):
        norm_box_check = _normalize_box_dims(box)
        if norm_box_check:
            qm_parts = [float(x) for x in qm_cell_abc.split()]
            if len(qm_parts) >= 3:
                for dim_i, (qm_l, mm_l, label) in enumerate(zip(
                    qm_parts[:3],
                    [norm_box_check[0], norm_box_check[1], norm_box_check[2]],
                    ['A', 'B', 'C'],
                )):
                    if qm_l > mm_l:
                        warn(
                            f"QM cell {label}={qm_l:.1f} Å exceeds MM cell "
                            f"{label}={mm_l:.1f} Å. The QM cell should not "
                            "extend beyond the simulation box in periodic QM/MM."
                        )
    if qmmm_periodic_meta['rcut_relaxed']:
        warn(
            "Periodic QM/MM MULTIPOLE RCUT had to be reduced to "
            f"{qmmm_periodic_meta['effective_rcut']:.1f} A from the target "
            f"{qmmm_periodic_meta['target_rcut']:.1f} A because of the available QM cell."
        )
    if qmmm_periodic_meta['buffer_relaxed']:
        warn(
            "The requested half-cell safety buffer for periodic QM/MM RCUT does not fit inside the QM cell. "
            "The generator used the largest strictly valid RCUT below half the QM cell instead."
        )
    qm_elements_upper = {str(e).upper() for e in qm_elements.keys()}
    has_tm_qm = bool(qm_elements_upper & TRANSITION_METALS)
    # ── A.1.b: spectator-vs-redox TM split ───────────────────────────────
    # Derive redox / spectator subsets of the QM TM complement so the
    # SCF-profile-promotion gate can distinguish "pure d¹⁰ cofactor"
    # from "redox-active centre".  The split is advisory by default
    # (non-interactive runs preserve the conservative "any TM → METAL
    # profile" behaviour per feedback_no_silent_modifications); in
    # interactive mode the user may opt to route spectator-only cases
    # through ORGANIC_RADICAL_DIAG (no smearing, level shift) when an
    # open-shell state on a ligand is expected and the metal is just a
    # structural Lewis-acid centre.  See classify_tm_presence() for the
    # taxonomy and authoritative references.
    _tm_classification = classify_tm_presence(qm_elements_upper)
    has_redox_tm_qm = bool(_tm_classification['has_redox_tm'])
    has_spectator_tm_qm = bool(_tm_classification['has_spectator_tm'])
    if has_tm_qm:
        _redox_label = ", ".join(sorted(_tm_classification['redox_tm_present'])) or "(none)"
        _spec_label = ", ".join(sorted(_tm_classification['spectator_tm_present'])) or "(none)"
        info(
            f"QM TM classification: redox-candidate={{{_redox_label}}}; "
            f"spectator(d¹⁰ Zn/Cd/Hg)={{{_spec_label}}}."
        )
        if has_spectator_tm_qm and not has_redox_tm_qm:
            detail(
                "Only spectator d¹⁰ TM(s) in QM.  METAL_RADICAL_DIAG "
                "promotion still applies by default — an opt-in prompt "
                "at the SCF-profile gate may route this through the "
                "ORGANIC_RADICAL_DIAG recipe when appropriate."
            )
    requested_admm_aux_basis = admm_aux_basis
    # ── ADMM coverage gate ────────────────────────────────────────────────
    # ADMM requires an auxiliary basis covering every QM element
    # (Guidon, Hutter, VandeVondele, JCTC 6, 2348 (2010)).  Coverage is
    # resolved from (i) a curated per-basis element pin and (ii) an
    # opportunistic scan of the CP2K-shipped BASIS_ADMM* file when
    # --cp2k-data-dir (or $CP2K_DATA_DIR) points at a real CP2K install.
    # The default policy is to *disable* ADMM when any QM element is not
    # covered — silent omission of an AUX_FIT Kind is the documented
    # failure mode that yields a cryptic CP2K runtime error during SCF
    # initialisation.  --admm-allow-unverified is the expert escape hatch.
    if use_admm:
        cp2k_data_dir = args.cp2k_data_dir or os.environ.get('CP2K_DATA_DIR')
        missing_admm = missing_admm_aux_basis_elements(
            qm_elements.keys(), admm_aux_basis, cp2k_data_dir=cp2k_data_dir,
        )
        if missing_admm and not args.admm_allow_unverified:
            warn(
                f"ADMM disabled: {admm_aux_basis} auxiliary basis does not cover "
                f"{', '.join(sorted(missing_admm))} in the curated pin"
                + (f" nor in {cp2k_data_dir}/BASIS_ADMM*" if cp2k_data_dir else "")
                + ". Remove these from the QM region, supply a custom AUX_FIT "
                  "basis, or pass --admm-allow-unverified to override. "
                  "See Guidon et al. JCTC 6, 2348 (2010)."
            )
            use_admm = False
            admm_aux_basis = None
        elif missing_admm and args.admm_allow_unverified:
            # Override accepted: keep ADMM on but loudly record the risk.
            warn(
                f"ADMM coverage for {admm_aux_basis} is not verified for "
                f"{', '.join(sorted(missing_admm))} (user override via "
                "--admm-allow-unverified). CP2K will error at SCF init if the "
                "ADMM basis file on PATH does not declare these Kinds."
            )
        elif admm_aux_basis == 'admm-dzp' and (qm_elements_upper - STANDARD_BIO_ADMM_ELEMENTS):
            # Curated pin / scan both accept these elements; emit a
            # lower-severity confirmation so the user sees that a non-bio
            # element got through the check and can cross-check locally.
            detail(
                "ADMM auxiliary basis admm-dzp validated against curated pin"
                + (f" and {cp2k_data_dir}/BASIS_ADMM_MOLOPT" if cp2k_data_dir else "")
                + f" for non-bio elements: "
                f"{', '.join(sorted(qm_elements_upper - STANDARD_BIO_ADMM_ELEMENTS))}."
            )
    # ── QM-region geometry packet for Tier-B risk probes ─────────────────
    # Build a self-contained geometry description (elements, coordinates,
    # QM-internal bond list) in 0-based local indexing.  The packet is
    # consumed by detect_pi_stacking_risk() via recommend_qm_spin_state()
    # to raise a face-to-face aromatic stacking warning when applicable.
    # The probe is advisory: it never changes the routing decision, it
    # only populates the risk-flag list shown to the user and audited.
    #
    # This block translates the pipeline's 1-based AMBER topology indexing
    # into the 0-based local indexing expected by the probe, using the
    # adjacency map already built at line 10167 (no extra graph walk).
    _qm_indices_sorted = sorted(int(i) for i in (qm_indices or []))
    _qm_1b_to_local = {g1: loc for loc, g1 in enumerate(_qm_indices_sorted)}
    _qm_geom_atoms = []
    for g1 in _qm_indices_sorted:
        idx0 = g1 - 1  # 0-based index into per-atom arrays
        if 0 <= idx0 < len(coords) and 0 <= idx0 < len(elems_per_atom):
            elem = str(elems_per_atom[idx0] or 'X').upper()
            cx, cy, cz = coords[idx0]
            _qm_geom_atoms.append((elem, (float(cx), float(cy), float(cz))))
        else:
            # Defensive: should never fire when qm_indices came from the
            # same topology as coords/elems_per_atom, but degrade
            # gracefully rather than raise during prep.
            _qm_geom_atoms.append(('X', (0.0, 0.0, 0.0)))
    _qm_geom_bonds = set()
    for g1 in _qm_indices_sorted:
        for nb in adjacency.get(g1, ()):
            nb = int(nb)
            if nb in _qm_1b_to_local and nb != g1:
                a = _qm_1b_to_local[g1]
                b = _qm_1b_to_local[nb]
                _qm_geom_bonds.add(frozenset((a, b)))
    qm_geometry = {'atoms': _qm_geom_atoms, 'bonds': _qm_geom_bonds}

    # ── B.1.a: QM-region residue label derivation ───────────────────────
    # Collect the set of distinct residue 3-letter codes present among
    # QM atoms.  The set is consumed by recommend_qm_spin_state and
    # classify_spin_risk_detectors so the KNOWN_REDOX_COFACTOR_RESIDUES
    # probe can fire for cofactors whose elements (C/H/N/O/P) are
    # invisible to the element-only hint set — most importantly FAD /
    # FMN in flavoenzymes.  RESIDUE_POINTER is the 1-based start-atom
    # pointer per residue and RESIDUE_LABEL is the parallel per-residue
    # name array (AMBER prmtop specification, AmberTools Reference
    # Manual §2.2 "%FLAG RESIDUE_LABEL/%FLAG RESIDUE_POINTER").
    _qm_atom_to_res = _atom_residue_index_map(
        topo.natom, residue_pointers_for_export or []
    )
    _qm_res_labels_set = set()
    for _g1 in _qm_indices_sorted:
        _idx0 = _g1 - 1
        if 0 <= _idx0 < len(_qm_atom_to_res):
            _res_1b = _qm_atom_to_res[_idx0]
            if 1 <= _res_1b <= len(residue_labels_for_export or ()):
                _rl = str(residue_labels_for_export[_res_1b - 1] or '').strip().upper()
                if _rl:
                    _qm_res_labels_set.add(_rl)
    qm_residue_labels = sorted(_qm_res_labels_set)

    # Informational advisory — if any named redox cofactor is present,
    # surface it early so the operator sees the evidence underlying the
    # risk flag before the recommender classifies the decision.
    _qm_redox_residue_hits = detect_known_redox_cofactor_residues(qm_residue_labels)
    if _qm_redox_residue_hits:
        _hit_summary = ", ".join(
            f"{_code} ({_cls})"
            for _code, (_name, _cls, _note) in _qm_redox_residue_hits
        )
        info(
            f"Named redox-active cofactor residue(s) in QM region: {_hit_summary}. "
            "Spin-state decision will route through the risk-flag path "
            "(see recommender output below)."
        )

    # ── Spin-state decision engine ───────────────────────────────────────
    # Electron parity is a necessary constraint, not proof of the
    # chemically correct spin state.  The recommender classifies every
    # decision so the user knows whether it was authoritative, inferred,
    # or ambiguous and requires explicit confirmation.
    user_mult_arg = args.multiplicity  # None when not supplied on CLI
    spin_decision = recommend_qm_spin_state(
        qm_elements=qm_elements,
        qm_charge=qm_charge,
        link_bonds=links,
        user_multiplicity=user_mult_arg,
        mdin_meta=mdin_meta,
        qm_geometry=qm_geometry,
        qm_residue_labels=qm_residue_labels,
    )
    qm_electrons = spin_decision['electron_count']
    qm_e_meta = estimate_qm_electrons_for_spin(
        qm_elements=qm_elements, qm_charge=qm_charge, link_bonds=links
    )[1]  # keep full metadata for the report file

    # ── Parity-estimate provenance exposure (B.2.a) ─────────────────────
    # estimate_qm_electrons_for_spin tags each element with the source of
    # its valence-electron count: 'gth' (curated GTH q-tag, exact) or
    # 'z-fallback' (raw atomic number used because the GTH q-tag table had
    # no entry).  Z-fallback is wrong for any element where the GTH PP
    # uses a smaller valence (e.g. Fe-q16 vs Z=26), which silently shifts
    # the parity check.  Surface this so the user can confirm or override
    # the multiplicity rather than trust a misleading estimate.
    # Ref: Krack, Theor. Chem. Acc. 114, 145 (2005) — GTH valence/core
    #      conventions per row; mismatch causes parity drift here.
    _z_fallback_count = int((qm_e_meta.get('source_counts') or {}).get('z-fallback', 0))
    if _z_fallback_count > 0:
        warn(
            f"Parity estimate uses Z-fallback for {_z_fallback_count} atom(s); "
            "the GTH q-tag table is incomplete for these elements and the "
            "parity check may mislead.  Confirm multiplicity manually."
        )
        run_provenance.record(
            kind='parity_z_fallback',
            severity='recommendation',
            source='auto',
            from_value='gth_qtag',
            to_value='atomic_number_fallback',
            accepted=None,
            reason=(
                f"{_z_fallback_count} QM atom(s) lack a GTH q-tag entry; "
                "parity estimate uses raw Z which can disagree with the "
                "GTH valence partition."
            ),
            citation="Krack, Theor. Chem. Acc. 114, 145 (2005)",
        )

    if interactive:
        print(f"\n  {C.BOLD}Spin-State Setup{C.R}")
        if qm_electrons is not None:
            detail(
                "Estimated QM electrons (GTH valence + link-H caps − charge): "
                f"{qm_electrons}"
            )
            detail(
                "Allowed multiplicity parity from electron count: "
                f"{'odd (1,3,5,…)' if qm_electrons % 2 == 0 else 'even (2,4,6,…)'}"
            )
        for rl in spin_decision.get('reason_lines', []):
            detail(f"  {rl}")
        if spin_decision['risk_flags']:
            for rf in spin_decision['risk_flags']:
                warn(f"Spin risk: {rf}")
            if has_tm_qm:
                detail("Common high-spin starting guesses: Fe²⁺=5, Cu²⁺=2, Mn²⁺=6, Co²⁺=4")

        if spin_decision['decision_class'] == 'AMBIGUOUS_REQUIRES_USER':
            # Must ask — we refuse to silently auto-accept.
            tentative = spin_decision.get('multiplicity')
            default_prompt = tentative if tentative is not None else 1
            warn("Spin state is ambiguous.  You must confirm or choose multiplicity.")
            # ── B.1.b: enumerate the firing detector categories so the
            # user can see the full taxonomy of risk that pushed this
            # decision into AMBIGUOUS, not just the per-flag messages
            # already echoed above.  This makes the underlying physics
            # assumption visible and helps the user choose between
            # overriding multiplicity, recovering missing element data,
            # or rerunning with explicit --multiplicity.
            _fired_detectors = classify_spin_risk_detectors(
                qm_elements=qm_elements,
                electron_count=qm_electrons,
                unresolved_elements=(qm_e_meta.get('unresolved_elements') or []),
                qm_geometry=qm_geometry,
                qm_residue_labels=qm_residue_labels,
            )
            if _fired_detectors:
                detail("Detector categories that fired (taxonomy):")
                for _det_key in _fired_detectors:
                    _det_label = SPIN_RISK_DETECTOR_LABELS.get(
                        _det_key, _det_key
                    )
                    detail(f"  • [{_det_key}] {_det_label}")
            if qm_electrons is not None:
                detail(
                    "Parity-compatible options: "
                    + (
                        "1, 3, 5, …" if (qm_electrons % 2) == 0
                        else "2, 4, 6, …"
                    )
                )
            while True:
                multiplicity = ask_int("QM region multiplicity (2S+1)", default_prompt, minimum=1)
                parity_ok, parity_msg = validate_multiplicity_parity(multiplicity, qm_electrons)
                if parity_ok is False:
                    # ── Electron-parity warning (interactive) ────────
                    # This is a quantum-mechanical constraint, not a
                    # soft preference.  Overriding requires expert
                    # justification (e.g. known topology charge error).
                    # Ref: Szabo & Ostlund, "Modern Quantum Chemistry"
                    #      (1996), §2.2 — spin eigenstate requirements.
                    warn(f"PHYSICS VIOLATION: {parity_msg}")
                    warn("This multiplicity is mathematically incompatible with the electron count.")
                    if ask_yes("Keep this parity-inconsistent multiplicity anyway?", default=False):
                        break
                    continue
                break
            # Re-derive decision as AUTHORITATIVE now that user confirmed.
            spin_decision = recommend_qm_spin_state(
                qm_elements=qm_elements, qm_charge=qm_charge,
                link_bonds=links, user_multiplicity=multiplicity,
                mdin_meta=mdin_meta,
                qm_geometry=qm_geometry,
                qm_residue_labels=qm_residue_labels,
            )
        elif spin_decision['decision_class'] in ('AUTHORITATIVE', 'LOW_RISK_INFERRED'):
            multiplicity = spin_decision['multiplicity']
            if user_mult_arg is not None:
                detail(f"CLI multiplicity provided: {user_mult_arg}")
            # Allow the user to override even an auto-accepted decision.
            while True:
                multiplicity = ask_int("QM region multiplicity (2S+1)", multiplicity, minimum=1)
                parity_ok, parity_msg = validate_multiplicity_parity(multiplicity, qm_electrons)
                if parity_ok is False:
                    # ── Electron-parity warning (interactive) ────────
                    # Same physics constraint as the AMBIGUOUS path.
                    # Ref: Szabo & Ostlund, "Modern Quantum Chemistry"
                    #      (1996), §2.2 — spin eigenstate requirements.
                    warn(f"PHYSICS VIOLATION: {parity_msg}")
                    warn("This multiplicity is mathematically incompatible with the electron count.")
                    if ask_yes("Keep this parity-inconsistent multiplicity anyway?", default=False):
                        break
                    continue
                break
            if multiplicity != spin_decision['multiplicity']:
                spin_decision = recommend_qm_spin_state(
                    qm_elements=qm_elements, qm_charge=qm_charge,
                    link_bonds=links, user_multiplicity=multiplicity,
                    mdin_meta=mdin_meta,
                    qm_geometry=qm_geometry,
                    qm_residue_labels=qm_residue_labels,
                )
        else:
            multiplicity = spin_decision.get('multiplicity') or 1
    else:
        # Non-interactive mode.
        if spin_decision['decision_class'] == 'AMBIGUOUS_REQUIRES_USER':
            if user_mult_arg is None:
                for rf in spin_decision['risk_flags']:
                    warn(f"Spin risk: {rf}")
                error(
                    "Spin state is ambiguous and --multiplicity was not provided.  "
                    "Provide --multiplicity explicitly for this system."
                )
                sys.exit(1)
            # user_mult_arg was set → already AUTHORITATIVE from the recommender.
            multiplicity = spin_decision['multiplicity']
        else:
            multiplicity = spin_decision['multiplicity']
            if multiplicity is None:
                error("Could not determine multiplicity.  Provide --multiplicity.")
                sys.exit(1)
        # ── Electron-parity enforcement (non-interactive) ────────────
        # Multiplicity M implies (M-1) unpaired electrons.  The parity
        # of (M-1) must match the parity of total electron count N:
        #   N even → M must be odd  (singlet, triplet, …)
        #   N odd  → M must be even (doublet, quartet, …)
        # Violating this constraint is physically impossible — it would
        # require a fractional electron.  CP2K will either crash in the
        # SCF solver or produce a meaningless wavefunction.
        # Ref: Szabo & Ostlund, "Modern Quantum Chemistry" (1996), §2.2.
        parity_ok, parity_msg = validate_multiplicity_parity(multiplicity, qm_electrons)
        if parity_ok is False:
            error(parity_msg)
            error(
                f"Multiplicity {multiplicity} is incompatible with "
                f"{qm_electrons} electrons.  Provide a parity-consistent "
                f"--multiplicity value."
            )
            sys.exit(1)

    detail(f"QM multiplicity for CP2K &DFT: {multiplicity}")
    detail(f"Spin treatment: {'UKS (open-shell)' if multiplicity != 1 else 'RKS (singlet)'}")
    detail(f"Decision class: {spin_decision['decision_class']} (source: {spin_decision['decision_source']})")
    use_diag_scf_final = should_use_diagonalization_scf(
        functional=functional,
        multiplicity=multiplicity,
        qm_elements=qm_elements,
        scf_profile=scf_profile_name,
    )
    # ── Promote SCF profile when open-shell/TM physics demands it ──
    # The SCF profile was chosen BEFORE multiplicity was known.  Now that
    # multiplicity is resolved, re-evaluate and promote if needed.
    #
    # Three promotion paths (the "open-shell" branch now splits on TM):
    #   (a) OT-engine profile + open-shell and has TM → METAL_RADICAL_DIAG
    #   (b) OT-engine profile + open-shell and no  TM → ORGANIC_RADICAL_DIAG
    #   (c) OT-engine profile + closed-shell (but diag forced elsewhere) → MECHANISM_DIAG
    #   (d) MECHANISM_DIAG + open-shell and has TM → METAL_RADICAL_DIAG
    #   (e) MECHANISM_DIAG + open-shell and no  TM → ORGANIC_RADICAL_DIAG
    #
    # The TM-vs-organic split is load-bearing: the two open-shell
    # populations need opposite mixing recipes (metallic-prior Fermi
    # smearing vs. level shift on discrete organic SOMOs).  Collapsing
    # them — as earlier revisions did — caused the LAAO flavoenzyme QM/MM
    # warmup to stall in charge-transfer sloshing because FAD/L-Phe π-π
    # near-degeneracy was fractionalised by smearing that had no physical
    # basis for an organic π-radical.
    #
    # Ref: CP2K Manual §CP2K_INPUT/FORCE_EVAL/DFT/SCF — OT is documented
    #      closed-shell only; &DIAGONALIZATION required for UKS.
    #      Kühne et al. J. Chem. Phys. 152, 194103 (2020) — SCF convergence.
    #      Pulay, Chem. Phys. Lett. 73, 393 (1980) — DIIS/mixing stability.
    #      Saunders & Hillier, Int. J. Quantum Chem. 7, 699 (1973) —
    #      level shift for near-degenerate frontier orbitals.
    #      Rabuck & Scuseria, J. Chem. Phys. 110, 695 (1999) — Fermi
    #      smearing as a convergence aid for transition-metal systems.
    _current_engine = SCF_PROFILES.get(scf_profile_name, {}).get('engine', 'OT')
    _needs_radical = (has_tm_qm or multiplicity > 1)

    # Helper: choose the right radical profile on the has_tm axis.
    # This encapsulates the single rule that the whole Tier-A fix hinges
    # on: "organic radical ≠ metal radical; route them separately."
    # A.1.b refinement: the decision is driven by the *redox* TM subset,
    # not by bare TM presence.  When only spectator d¹⁰ centres are in
    # the QM region, the open-shell character (if any) lives on an
    # organic ligand and ORGANIC_RADICAL_DIAG (no Fermi smearing, level
    # shift) is the correct recipe.  Callers that predate the split may
    # still pass a single boolean, which is interpreted as ``has_redox_tm``
    # (matching the previous semantics) via the second argument default.
    def _radical_profile_for_tm(has_tm_local, has_redox_tm_local=None):
        _has_redox = (has_tm_local if has_redox_tm_local is None
                      else bool(has_redox_tm_local))
        return 'METAL_RADICAL_DIAG' if _has_redox else 'ORGANIC_RADICAL_DIAG'

    # A.1.b: when the QM region holds only spectator d¹⁰ TM(s) (Zn/Cd/Hg)
    # and no redox-candidate metal, the default "METAL_RADICAL_DIAG for
    # any TM" rule is typically wrong — the radical, if any, is on an
    # organic ligand.  We surface a one-time recommendation here so any
    # downstream promotion uses the spectator-aware choice.  In
    # non-interactive mode the conservative default is preserved
    # (per feedback_no_silent_modifications) and only a WARN + provenance
    # entry fire.  In interactive mode the user opts in to the refined
    # ORGANIC_RADICAL_DIAG routing by confirming the prompt.
    _spectator_tm_override_organic = False
    if has_tm_qm and has_spectator_tm_qm and not has_redox_tm_qm:
        _advisory_msg = (
            "QM region contains only spectator d¹⁰ transition metal(s) "
            f"({', '.join(sorted(_tm_classification['spectator_tm_present']))}). "
            "ZnII/CdII/HgII are closed-shell Lewis-acid cofactors in biology "
            "— any open-shell character resides on the organic ligand, so "
            "ORGANIC_RADICAL_DIAG is the scientifically-grounded radical "
            "profile (no Fermi smearing, level-shift on). METAL_RADICAL_DIAG "
            "remains available as the conservative default."
        )
        warn(_advisory_msg)
        if interactive:
            if ask_yes(
                "Route any radical-profile promotion through "
                "ORGANIC_RADICAL_DIAG (spectator-aware)?",
                default=True,
            ):
                _spectator_tm_override_organic = True
                info(
                    "Spectator-aware routing accepted: open-shell promotions "
                    "(if any) will use ORGANIC_RADICAL_DIAG."
                )
        run_provenance.record(
            kind='tm_spectator_split',
            severity='recommendation',
            source='user' if (interactive and _spectator_tm_override_organic) else 'auto',
            from_value='METAL_RADICAL_DIAG (conservative default)',
            to_value=(
                'ORGANIC_RADICAL_DIAG (spectator-aware)'
                if _spectator_tm_override_organic
                else 'METAL_RADICAL_DIAG (default retained)'
            ),
            accepted=(_spectator_tm_override_organic if interactive else None),
            reason=(
                "QM region contains only spectator d¹⁰ TM(s); "
                + (
                    "user opted into spectator-aware ORGANIC_RADICAL_DIAG routing."
                    if _spectator_tm_override_organic else
                    ("user declined override; METAL default retained."
                     if interactive else
                     "non-interactive mode — METAL default retained per policy.")
                )
            ),
            citation=(
                "Holm, Kennepohl, Solomon, Chem. Rev. 96, 2239 (1996); "
                "Andreini et al., J. Biol. Inorg. Chem. 13, 1205 (2008)"
            ),
            context={
                'spectator_tm': sorted(_tm_classification['spectator_tm_present']),
                'redox_tm': sorted(_tm_classification['redox_tm_present']),
                'multiplicity': int(multiplicity),
            },
        )
    # ``_effective_has_redox_tm`` is the value that downstream
    # promotion-site calls should use.  Without a user opt-in it is the
    # conservative ``has_tm_qm`` (old behaviour preserved).  With opt-in
    # it is ``has_redox_tm_qm`` (pure spectator → ORGANIC profile).
    _effective_has_redox_tm = (
        has_redox_tm_qm if _spectator_tm_override_organic else has_tm_qm
    )

    # The set of keys copied during a promotion is the union of all
    # numeric parameters the emitter reads from scf_cfg.  We widen this
    # set to include the two new declarative fields so that emitter
    # behaviour (LEVEL_SHIFT emission, SMEAR gating) tracks the promoted
    # profile rather than the original preliminary one.
    _PROMOTABLE_SCF_KEYS = (
        'max_scf', 'eps_scf',
        'added_mos', 'mixing_method', 'mixing_alpha', 'nbroyden',
        'outer_max_scf', 'outer_eps_scf',
        'expects_smearing', 'level_shift',
    )

    # ── User-consent gate for SCF profile promotions ────────────────────
    # Per project policy: never modify SCF settings automatically.  Always
    # surface a strong, scientifically-grounded recommendation; the user
    # decides whether to apply it.
    #
    # Two severity levels:
    #   * 'correction'    — the originally-selected profile is physically
    #                       inconsistent with the resolved electronic
    #                       structure (e.g. OT engine + UKS).  Without
    #                       promotion the run will fail or produce
    #                       garbage.  In non-interactive mode we abort
    #                       with an actionable error (the user must
    #                       re-pick the profile and re-run) rather than
    #                       silently change settings.
    #   * 'recommendation'— the originally-selected profile may converge
    #                       but is suboptimal (e.g. MECHANISM_DIAG's
    #                       aggressive mixing on a UKS organic radical).
    #                       In non-interactive mode we WARN loudly and
    #                       leave the configuration untouched, honouring
    #                       the user's explicit choice.
    #
    # Refs (kept here so the prompt body can quote them concisely):
    #   * CP2K Manual §FORCE_EVAL/DFT/SCF — OT closed-shell only.
    #   * Pulay, Chem. Phys. Lett. 73, 393 (1980) — DIIS/mixing stability.
    #   * Saunders & Hillier, IJQC 7, 699 (1973) — level-shift for
    #     near-degenerate organic SOMOs.
    #   * Rabuck & Scuseria, JCP 110, 695 (1999) — Fermi smearing for TM
    #     near-degenerate d-manifolds.
    def _prompt_user_consent_for_scf_promotion(
        from_profile, to_profile, rationale, severity,
    ):
        """Strongly recommend a profile switch and return the user's choice.

        Returns True iff the caller should apply the promotion.  Never
        mutates scf_cfg / scf_profile_name itself — that stays the
        caller's responsibility so the diff is local and auditable.
        """
        msg_head = (
            f"SCF profile '{from_profile}' is "
            + ("INCOMPATIBLE" if severity == 'correction' else "SUBOPTIMAL")
            + f" for the resolved electronic structure.\n"
            f"      Strong recommendation: switch to '{to_profile}'.\n"
            f"      Rationale: {rationale}"
        )
        warn(msg_head)
        # Citation bundle for every SCF-promotion provenance entry — the
        # text is the same per severity, so factor it out once.
        _scf_promo_citation = (
            "CP2K Manual §FORCE_EVAL/DFT/SCF (OT closed-shell only); "
            "Saunders & Hillier, IJQC 7, 699 (1973); Rabuck & Scuseria, "
            "JCP 110, 695 (1999)"
        )
        if interactive:
            if ask_yes(
                f"Apply the recommended switch to '{to_profile}'?",
                default=True,
            ):
                info(
                    f"User accepted SCF profile switch: "
                    f"'{from_profile}' → '{to_profile}'."
                )
                run_provenance.record(
                    kind='scf_profile_promotion',
                    severity=severity,
                    source='wizard',
                    from_value=from_profile,
                    to_value=to_profile,
                    accepted=True,
                    reason=rationale,
                    citation=_scf_promo_citation,
                )
                return True
            info(
                f"User declined SCF profile switch; keeping '{from_profile}'. "
                "The pipeline will proceed with the original choice as requested."
            )
            run_provenance.record(
                kind='scf_profile_promotion',
                severity=severity,
                source='wizard',
                from_value=from_profile,
                to_value=to_profile,
                accepted=False,
                reason=rationale,
                citation=_scf_promo_citation,
            )
            return False
        # Non-interactive: never modify automatically.
        if severity == 'correction':
            error(
                f"--non-interactive: cannot apply the required SCF profile switch "
                f"without user consent.  Re-run interactively, or pre-select "
                f"'{to_profile}' before invoking the generator (e.g. by editing "
                f"the input wizard inputs upstream).  Refusing to silently modify "
                f"SCF settings (project policy: 'never modify anything automatically')."
            )
            run_provenance.record(
                kind='scf_profile_promotion',
                severity='correction',
                source='auto',
                from_value=from_profile,
                to_value=to_profile,
                accepted=False,
                reason=f"Non-interactive abort: {rationale}",
                citation=_scf_promo_citation,
            )
            sys.exit(1)
        warn(
            f"--non-interactive: leaving SCF profile as '{from_profile}'.  "
            f"If convergence is poor, re-run interactively and accept the "
            f"recommended switch to '{to_profile}'."
        )
        run_provenance.record(
            kind='scf_profile_promotion',
            severity='recommendation',
            source='auto',
            from_value=from_profile,
            to_value=to_profile,
            accepted=False,
            reason=f"Non-interactive: WARN-only; {rationale}",
            citation=_scf_promo_citation,
        )
        return False

    # ── A.2.a: helper to detect user-edited keys vs profile baseline ─────
    # Returns the keys that the user has tuned away from the profile's
    # original defaults and that the promotion would overwrite.  Floats
    # are compared with a tolerance so machine-rounding never creates a
    # spurious "edited" tag.
    def _detect_user_edited_promotable_keys(promoted_cfg):
        edited = []
        for _k in _PROMOTABLE_SCF_KEYS:
            if _k not in promoted_cfg:
                continue
            _baseline_v = _scf_cfg_baseline.get(_k)
            _current_v = scf_cfg.get(_k)
            _promoted_v = promoted_cfg.get(_k)
            if _baseline_v is None and _current_v is None:
                continue
            try:
                _diverged_from_baseline = (
                    abs(float(_current_v) - float(_baseline_v)) > 1.0e-12
                )
            except (TypeError, ValueError):
                _diverged_from_baseline = (_current_v != _baseline_v)
            if not _diverged_from_baseline:
                continue
            try:
                _would_overwrite = (
                    abs(float(_current_v) - float(_promoted_v)) > 1.0e-12
                )
            except (TypeError, ValueError):
                _would_overwrite = (_current_v != _promoted_v)
            if _would_overwrite:
                edited.append((_k, _current_v, _promoted_v))
        return edited

    def _prompt_user_for_overwrite_consent(promoted_profile, edited_keys):
        """A.2.a per-key sub-prompt before SCF promotion overwrites edits.

        Returns the set of keys the user permits the promotion to
        overwrite.  Keys not in the returned set are preserved at the
        user's edited value even though the rest of the promotion
        applies.  Non-interactive mode preserves all user edits (per
        feedback_no_silent_modifications) and returns an empty set.
        """
        if not edited_keys:
            return {k for (k, _o, _n) in []}  # empty set with stable type
        warn(
            f"SCF promotion to '{promoted_profile}' would overwrite "
            f"{len(edited_keys)} key(s) you explicitly tuned away from the "
            f"profile defaults:"
        )
        for (_k, _old, _new) in edited_keys:
            detail(f"  • {_k}: {_old} (your edit) → {_new} (promoted profile)")
        if not interactive:
            warn(
                "Non-interactive mode: keeping all user-edited values. "
                "Re-run interactively to authorise per-key overwrites."
            )
            run_provenance.record(
                kind='scf_promotion_user_edit_preserved',
                severity='recommendation',
                source='auto',
                from_value=None,
                to_value=None,
                accepted=False,
                reason=(
                    "Non-interactive: SCF promotion accepted but user-edited "
                    "keys preserved per feedback_no_silent_modifications."
                ),
                citation='project policy (feedback_no_silent_modifications)',
                context={
                    'promoted_profile': promoted_profile,
                    'preserved_keys': ', '.join(k for (k, _o, _n) in edited_keys),
                },
            )
            return set()
        if ask_yes(
            "Allow the promotion to overwrite ALL these user edits with "
            "the promoted profile's values?",
            default=True,
        ):
            run_provenance.record(
                kind='scf_promotion_user_edit_overwrite',
                severity='recommendation',
                source='wizard',
                from_value=None,
                to_value=None,
                accepted=True,
                reason='User authorised SCF promotion to overwrite tuned keys.',
                citation='project policy (feedback_no_silent_modifications)',
                context={
                    'promoted_profile': promoted_profile,
                    'overwritten_keys': ', '.join(k for (k, _o, _n) in edited_keys),
                },
            )
            return {k for (k, _o, _n) in edited_keys}
        # Per-key sub-prompts for the user who wants finer control.
        keep_user_edit_keys = set()
        for (_k, _old, _new) in edited_keys:
            if ask_yes(
                f"  Overwrite '{_k}' ({_old} → {_new})?",
                default=False,
            ):
                continue
            keep_user_edit_keys.add(_k)
        run_provenance.record(
            kind='scf_promotion_user_edit_partial',
            severity='recommendation',
            source='wizard',
            from_value=None,
            to_value=None,
            accepted=True,
            reason='User authorised SCF promotion with per-key overwrite control.',
            citation='project policy (feedback_no_silent_modifications)',
            context={
                'promoted_profile': promoted_profile,
                'preserved_keys': ', '.join(sorted(keep_user_edit_keys)) or '(none)',
                'overwritten_keys': ', '.join(
                    k for (k, _o, _n) in edited_keys if k not in keep_user_edit_keys
                ) or '(none)',
            },
        )
        return {k for (k, _o, _n) in edited_keys} - keep_user_edit_keys

    def _apply_promotion(promoted_profile):
        promoted_cfg = SCF_PROFILES[promoted_profile]
        edited_keys = _detect_user_edited_promotable_keys(promoted_cfg)
        keys_to_overwrite = (
            _prompt_user_for_overwrite_consent(promoted_profile, edited_keys)
        )
        edited_key_set = {k for (k, _o, _n) in edited_keys}
        for param in _PROMOTABLE_SCF_KEYS:
            if param not in promoted_cfg:
                continue
            if param in edited_key_set and param not in keys_to_overwrite:
                # Preserve the user's tuned value.
                continue
            scf_cfg[param] = promoted_cfg[param]
        return promoted_profile

    if use_diag_scf_final and _current_engine == 'OT':
        # Paths (a)/(b)/(c): OT → the DIAG profile that matches the
        # resolved physics (radical vs. closed-shell, TM vs. organic).
        # Severity = 'correction': OT engine does not support UKS, so
        # without the switch CP2K will reject the input.
        if _needs_radical:
            promoted_profile = _radical_profile_for_tm(
                has_tm_qm, has_redox_tm_local=_effective_has_redox_tm,
            )
        else:
            promoted_profile = 'MECHANISM_DIAG'
        _rationale = (
            f"OT engine is documented closed-shell only (CP2K Manual "
            f"§FORCE_EVAL/DFT/SCF); resolved multiplicity={multiplicity} "
            f"and TM-presence={has_tm_qm} require &DIAGONALIZATION."
        )
        if _prompt_user_consent_for_scf_promotion(
            scf_profile_name, promoted_profile, _rationale, severity='correction',
        ):
            scf_profile_name = _apply_promotion(promoted_profile)
    elif _needs_radical and scf_profile_name == 'MECHANISM_DIAG':
        # Paths (d)/(e): MECHANISM_DIAG was selected for a large QM region,
        # but the system turns out to be open-shell.  MECHANISM_DIAG's
        # mixing (alpha=0.18, NBROYDEN=8) is too aggressive for UKS;
        # the radical profile is recommended but the run can still
        # proceed (it may just converge slowly or oscillate).
        promoted_profile = _radical_profile_for_tm(
            has_tm_qm, has_redox_tm_local=_effective_has_redox_tm,
        )
        _radical_kind = (
            'transition-metal d-manifold' if _effective_has_redox_tm
            else 'organic π-radical'
        )
        _rationale = (
            f"MECHANISM_DIAG's aggressive mixing (alpha=0.18, NBROYDEN=8) is "
            f"tuned for closed-shell density relaxation; multiplicity={multiplicity} "
            f"indicates open-shell character and the {_radical_kind} recipe "
            f"({promoted_profile}) reduces SCF oscillation."
        )
        if _prompt_user_consent_for_scf_promotion(
            scf_profile_name, promoted_profile, _rationale, severity='recommendation',
        ):
            scf_profile_name = _apply_promotion(promoted_profile)
    if not use_diag_scf_final:
        detail(
            "OT routine path: FULL_ALL + ENERGY_GAP 1.0E-3 is the explicit "
            "CP2K-documented robust default; FULL_ALL expects an underestimated gap."
        )
        if interactive:
            detail("OT minimizer choice: CG is the recommended reliable default; DIIS is speed-first.")
            ot_minimizer = ask_choice(
                "OT minimizer (CG recommended: most reliable; DIIS faster but less robust)",
                OT_MINIMIZERS,
                ot_minimizer,
            ).upper()
            # ── A.4.a: OT PRECONDITIONER selector (ADVANCED profile only) ──
            # Non-ADVANCED users stay on FULL_ALL — the pipeline's conservative
            # robust default.  ADVANCED operators may pick a different
            # preconditioner (FULL_SINGLE_INVERSE for memory-constrained HFX,
            # FULL_KINETIC for cheap warmup, etc.); when they do, the
            # subsequent ENERGY_GAP step needs to be calibrated accordingly.
            # Refs: VandeVondele & Hutter, J. Chem. Phys. 118, 4365 (2003);
            # CP2K Manual §FORCE_EVAL/DFT/SCF/OT/PRECONDITIONER.
            if scf_profile_name == 'ADVANCED':
                _ot_precond_choices = list(OT_PRECONDITIONER_RECOMMENDED_ENERGY_GAP.keys())
                ot_preconditioner = ask_choice(
                    "OT PRECONDITIONER (FULL_ALL recommended; FULL_SINGLE_INVERSE for "
                    "large/HFX jobs; FULL_KINETIC for cheap warmup)",
                    _ot_precond_choices,
                    ot_preconditioner,
                ).upper()
            if ask_yes(
                f"Keep recommended OT ENERGY_GAP {DEFAULT_OT_ENERGY_GAP:.1E} "
                f"(CP2K robust default for PRECONDITIONER=FULL_ALL)?",
                default=True,
            ):
                ot_energy_gap = DEFAULT_OT_ENERGY_GAP
            else:
                ot_energy_gap = ask_float(
                    f"OT ENERGY_GAP for PRECONDITIONER={ot_preconditioner} "
                    "(use an underestimate of the HOMO-LUMO gap)",
                    ot_energy_gap,
                    minimum=1.0e-12,
                )
            # ── A.4.a: preconditioner-aware ENERGY_GAP advisory ──
            # When the operator leaves ENERGY_GAP at the FULL_ALL-tuned
            # default but selects a different preconditioner, surface the
            # CP2K/VandeVondele-Hutter guidance so they can consciously
            # opt in or adjust.  The helper never rewrites the value
            # silently (feedback_no_silent_modifications).
            ot_energy_gap = advise_ot_energy_gap_for_preconditioner(
                ot_preconditioner,
                ot_energy_gap,
                interactive=True,
                run_provenance=run_provenance,
            )
            detail(
                "OT STEPSIZE is only the initial line-search step. "
                "CP2K can choose it automatically from the preconditioner when STEPSIZE is negative."
            )
            if (args.ot_stepsize_mode is not None) or (args.ot_stepsize is not None):
                detail(
                    "Using CLI-selected OT STEPSIZE policy: "
                    + (
                        "AUTO (emit STEPSIZE -1.0 so CP2K chooses it)"
                        if ot_stepsize_policy.mode == 'AUTO'
                        else f"MANUAL ({ot_stepsize_policy.stepsize:g})"
                    )
                )
            elif ask_yes("Let CP2K choose OT STEPSIZE automatically?", default=True):
                ot_stepsize_policy = make_ot_stepsize_policy(
                    mode='AUTO',
                    ot_preconditioner=ot_preconditioner,
                )
            else:
                ot_stepsize_policy = make_ot_stepsize_policy(
                    mode='MANUAL',
                    stepsize=ask_float(
                        "OT STEPSIZE initial line-search step",
                        cp2k_default_ot_stepsize(ot_preconditioner),
                        minimum=1.0e-12,
                    ),
                    ot_preconditioner=ot_preconditioner,
                )
        else:
            ot_stepsize_policy = make_ot_stepsize_policy(
                mode=ot_stepsize_policy.mode,
                stepsize=(None if ot_stepsize_policy.mode == 'AUTO' else ot_stepsize_policy.stepsize),
                ot_preconditioner=ot_preconditioner,
            )
            # A.4.a: non-interactive path still surfaces the advisory as WARN
            # (not as a silent rewrite) when a non-FULL_ALL preconditioner is
            # in effect — typically coming from a CLI override or a future
            # programmatic caller — so the operator sees the guidance in the
            # log even without a prompt.
            ot_energy_gap = advise_ot_energy_gap_for_preconditioner(
                ot_preconditioner,
                ot_energy_gap,
                interactive=False,
                run_provenance=run_provenance,
            )
        detail(
            f"OT settings: MINIMIZER={ot_minimizer}, "
            f"PRECONDITIONER={ot_preconditioner}, ENERGY_GAP={float(ot_energy_gap):.1E}, "
            f"STEPSIZE={'AUTO(-1.0)' if ot_stepsize_policy.mode == 'AUTO' else format(ot_stepsize_policy.stepsize, 'g')}"
        )

    # ── SCF-routing audit payload ────────────────────────────────────────
    # Captures the final profile (post any promotion) and the two
    # declarative fields that control the most consequential emitter
    # decisions: Fermi smearing and LEVEL_SHIFT.  Written into
    # electronic_state.dat so the audit file alone is sufficient to
    # reproduce why a given CP2K input was generated.
    _final_profile_meta = SCF_PROFILES.get(scf_profile_name, {})
    scf_routing_audit = {
        'profile': scf_profile_name,
        'engine': _final_profile_meta.get('engine', 'OT'),
        'has_tm': bool(has_tm_qm),
        'expects_smearing': bool(_final_profile_meta.get('expects_smearing', False)),
        'level_shift': _final_profile_meta.get('level_shift'),
        'reason': (
            f"Selected after post-hoc promotion; multiplicity={int(multiplicity)}, "
            f"has_tm={'yes' if has_tm_qm else 'no'}, "
            f"spin_decision_class={spin_decision.get('decision_class', 'unknown')}, "
            f"spin_decision_source={spin_decision.get('decision_source', 'unknown')}."
        ),
        # ── Decision-class propagation (A.1.c) ───────────────────────────
        # Surface the spin-decision taxonomy in the audit so reviewers can
        # see whether the SCF profile rests on AUTHORITATIVE evidence
        # (user/mdin), LOW_RISK_INFERRED (parity), or AMBIGUOUS (risk
        # flags present and the user explicitly resolved them).
        'spin_decision_class': spin_decision.get('decision_class'),
        'spin_decision_source': spin_decision.get('decision_source'),
        'spin_decision_confidence': spin_decision.get('confidence'),
    }
    # ── OT stepsize provenance (A.4.b) ───────────────────────────────────
    # Capture the resolved OT line-search stepsize policy alongside the SCF
    # routing record so the audit file is sufficient to reproduce the SCF
    # numerics (CP2K Manual §FORCE_EVAL/DFT/SCF/OT/STEPSIZE; STEPSIZE -1.0
    # delegates the choice to CP2K's preconditioner-dependent default).
    if _final_profile_meta.get('engine', 'OT') == 'OT':
        scf_routing_audit['ot_stepsize_mode'] = ot_stepsize_policy.mode
        scf_routing_audit['ot_stepsize_value'] = float(ot_stepsize_policy.stepsize)
        scf_routing_audit['ot_stepsize_reason'] = ot_stepsize_policy.reason
        scf_routing_audit['ot_minimizer'] = ot_minimizer
        scf_routing_audit['ot_preconditioner'] = ot_preconditioner
        scf_routing_audit['ot_energy_gap'] = float(ot_energy_gap)

    # ── A.3.b: post-spin SCF_GUESS=ATOMIC + open-shell advisory ──────────
    # The SCF wizard ran before the spin state was resolved, so it could
    # only key its MOPAC recommendation off TM presence.  Now that
    # multiplicity is known, surface a parallel recommendation when the
    # system is open-shell (multiplicity > 1) and the user is still on
    # SCF_GUESS=ATOMIC — the bare atomic superposition has no spin
    # polarization, which is precisely where MOPAC PM6/PM7 helps most.
    # WARN-only per feedback_no_silent_modifications.
    _open_shell_after_spin = (int(multiplicity) > 1)
    if (
        _open_shell_after_spin
        and str(scf_cfg.get('scf_guess', '')).upper() == 'ATOMIC'
    ):
        warn(
            f"SCF_GUESS=ATOMIC with open-shell multiplicity={multiplicity}: "
            "bare atomic superposition has no spin polarization, so the "
            "first SCF iteration starts from a spin-restricted density. "
            "Consider rerunning with SCF_GUESS=MOPAC (PM6/PM7 pre-SCF) "
            "for faster, more reliable convergence on open-shell systems. "
            "Refs: Stewart, J. Mol. Mod. 13, 1173 (2007); 19, 1 (2013)."
        )
        run_provenance.record(
            kind='scf_guess_recommendation_post_spin',
            severity='recommendation',
            source='audit',
            from_value='ATOMIC',
            to_value='MOPAC (recommended)',
            accepted=False,
            reason=(
                f"Open-shell system (multiplicity={multiplicity}) with "
                "SCF_GUESS=ATOMIC; MOPAC initial guess avoids the "
                "spin-restricted starting density."
            ),
            citation='Stewart, J. Mol. Mod. 13, 1173 (2007); 19, 1 (2013)',
        )

    if not dry_run:
        es_meta = write_electronic_state_dat(
            out_path=electronic_state_out,
            qm_meta=qm_e_meta,
            qm_charge=qm_charge,
            multiplicity=multiplicity,
            spin_decision=spin_decision,
            scf_routing=scf_routing_audit,
        )
        info(f"Wrote electronic state breakdown: {os.path.basename(electronic_state_out)}")
        if es_meta.get('parity_consistent') is False:
            warn(
                "electronic_state.dat reports multiplicity/electron parity mismatch. "
                "Review CHARGE and MULTIPLICITY."
            )
        # ── Boundary-charges audit artifact ───────────────────────────────
        # Emit a structured record of the two channels that modify charge at
        # the QM/MM frontier (FIST residual redistribution + &QMMM/&LINK
        # ADD_MM_CHARGE).  These operate on disjoint Hamiltonians, so they
        # do not literally double-count, but the per-atom composition is
        # otherwise difficult to audit post-hoc.
        try:
            bc_meta = write_boundary_charges_audit(
                out_dir=out_dir,
                link_bonds=links,
                residual_charge_plan=residual_charge_plan,
                boundary_charge_scheme=boundary_charge_scheme,
                topo=topo,
            )
            info(
                "Wrote boundary-charges audit: "
                f"{os.path.basename(bc_meta['json_path'])} / "
                f"{os.path.basename(bc_meta['dat_path'])} "
                f"(links={bc_meta['n_links']}, residues={bc_meta['n_redistributed_residues']}, "
                f"atoms_touched={bc_meta['n_atoms_touched']})"
            )
        except Exception as exc:
            # Never fail the main emission path over an audit artifact.
            warn(f"Could not write boundary-charges audit artifact: {exc}")
    else:
        info(f"[DRY RUN] Would write: {os.path.basename(electronic_state_out)}")
        info("[DRY RUN] Would write: boundary_charges.json / boundary_charges.dat")

    if ensure_link_cap_kind(qm_elements, links, cap_element='H'):
        warn("Link atoms require element H in QM KINDs; adding H KIND block automatically.")

    # Generate KIND blocks.  Run the GTH-PP ↔ functional consistency
    # advisory once before building the KIND directives so the operator
    # sees the self-consistency status exactly at the point where the
    # POTENTIAL choice is committed to the input file.  See B.1.c for
    # the curated table and literature citations.
    qm_syms = list(qm_elements.keys())
    _gth_pp_prefix = validate_functional_pp_match(
        functional,
        interactive=interactive,
        run_provenance=run_provenance,
    )
    qm_kinds, unresolved_qm_gth = generate_qm_kinds(
        qm_elements,
        basis_set=basis_set,
        aux_basis=admm_aux_basis,
        potential_prefix=_gth_pp_prefix,
        use_admm=use_admm,
    )
    # ── Guard: reject unresolved QM GTH pseudopotentials ─────────────
    # generate_qm_kinds() flags elements without a GTH_CHARGE_MAP entry.
    # These produce 'POTENTIAL …-qX' lines that have no matching record
    # in any CP2K pseudopotential library file; the run will crash at
    # POTENTIAL parsing with a non-diagnostic error.
    #   Ref: CP2K Manual §4.3 — POTENTIAL keyword requires exact match.
    #   Ref: Goedecker, Teter & Hutter, Phys. Rev. B 54, 1703 (1996).
    # Hard-stop in ALL modes: an invalid potential is a guaranteed crash,
    # and proceeding produces a broken input file regardless of whether
    # the session is interactive.
    if unresolved_qm_gth:
        error(
            f"Cannot produce valid CP2K input: no GTH pseudopotential charge "
            f"mapping for element(s) {', '.join(sorted(unresolved_qm_gth))}. "
            f"Add entries to GTH_CHARGE_MAP or remove these elements from "
            f"the QM region."
        )
        sys.exit(1)
    mm_topology_data = collect_topology_variant_data(
        topo,
        qm_syms,
        alias_plan=alias_plan,
    )
    qmmm_topology_data = collect_topology_variant_data(
        topo,
        qm_syms,
        charge_array_override=_apply_residual_charge_plan_to_raw_charges(atom_charges, residual_charge_plan),
        alias_plan=alias_plan,
    )

    for label, topo_data in (("MM", mm_topology_data), ("QM/MM", qmmm_topology_data)):
        info(
            f"{label} topology atom types: {len(set(topo_data['atom_types']))} unique "
            f"({len(topo_data['atom_types'])} atoms)"
        )
        if topo_data['unresolved']:
            warn(f"Unresolved atom types in {label} topology: {topo_data['unresolved'][:10]}")

    info(f"Generated {len(qm_syms)} QM KIND blocks")
    info(f"Generated {len(mm_topology_data['mm_kinds']) // 3} MM KIND blocks for MM stages (with conformers)")
    info(f"Generated {len(qmmm_topology_data['mm_kinds']) // 3} MM KIND blocks for QM/MM stages (with conformers)")

    # Assemble staged workflow inputs
    mm_prmtop_ref = os.path.basename(mm_prmtop_out) if not dry_run else "system_mm.prmtop"
    qmmm_prmtop_ref = os.path.basename(qmmm_prmtop_out) if not dry_run else "system_qmmm.prmtop"
    xyz_ref = os.path.basename(xyz_out) if not dry_run else "system.xyz"
    restraint_indices = list(qm_indices)
    system_model = make_system_spec(
        prmtop_file=qmmm_prmtop_ref,
        mm_prmtop_file=mm_prmtop_ref,
        qmmm_prmtop_file=qmmm_prmtop_ref,
        xyz_file=xyz_ref,
        natom=topo.natom,
        box_dims=box,
        qm_elements=qm_elements,
        link_bonds=links,
        qm_kinds_lines=qm_kinds,
        mm_kinds_lines=mm_topology_data['mm_kinds'],
        mm_stage_kinds_lines=mm_topology_data['mm_kinds'],
        qmmm_stage_kinds_lines=qmmm_topology_data['mm_kinds'],
        mm_scale14_policy=mm_scale14_policy,
        qmmm_periodic_policy=qmmm_periodic_policy,
        qm_cell_abc=qm_cell_abc,
        qm_charge=qm_charge,
        multiplicity=multiplicity,
    )
    # D.1.b: offer DFTD4 upgrade when the CP2K build supports it and the
    # functional has published DFTD4 parameters.  Interactive consent only;
    # the default path preserves DFTD3(BJ) so behaviour is unchanged for
    # non-interactive runs and older CP2K builds.
    _dispersion_scheme_resolved = dispersion_scheme_override or 'DFTD3_BJ'
    if dispersion_scheme_override:
        detail(f"Using CLI-selected dispersion scheme {_dispersion_scheme_resolved}")
    elif recommend_dftd4_upgrade(
        functional=functional,
        cp2k_version_tuple=(cp2k_capability.version if cp2k_capability else None),
        interactive=interactive,
        run_provenance=run_provenance,
    ):
        _dispersion_scheme_resolved = 'DFTD4'
    dft_config = make_dft_config(
        functional=functional,
        basis_set=basis_set,
        cutoff=cutoff,
        rel_cutoff=rel_cutoff,
        use_admm=use_admm,
        admm_aux_basis=admm_aux_basis,
        admm_exch_correction_func=admm_exch_correction_func,
        mgrid_ngrids=mgrid_ngrids,
        scf_profile=scf_profile_name,
        scf_max_scf=scf_cfg['max_scf'],
        scf_eps_scf=scf_cfg['eps_scf'],
        scf_guess=scf_cfg['scf_guess'],
        scf_cholesky=scf_cfg.get('cholesky'),
        qs_eps_default=scf_cfg.get('qs_eps_default'),
        scf_added_mos=scf_cfg['added_mos'],
        scf_mixing_method=scf_cfg['mixing_method'],
        scf_mixing_alpha=scf_cfg['mixing_alpha'],
        scf_nbroyden=scf_cfg['nbroyden'],
        outer_max_scf=scf_cfg['outer_max_scf'],
        outer_eps_scf=scf_cfg['outer_eps_scf'],
        ot_minimizer=ot_minimizer,
        ot_preconditioner=ot_preconditioner,
        ot_energy_gap=ot_energy_gap,
        ot_stepsize=(None if ot_stepsize_policy.mode == 'AUTO' else ot_stepsize_policy.stepsize),
        ot_stepsize_mode=ot_stepsize_policy.mode,
        hf_max_memory=hf_max_memory,
        qmmm_geep_lib=qmmm_geep_lib,
        boundary_charge_scheme=boundary_charge_scheme,
        qm_elements_for_admm=qm_elements,
        qm_kinds_lines_for_admm=qm_kinds,
        dftd3_interactive=interactive,
        dftd3_run_provenance=run_provenance,
        dispersion_scheme=_dispersion_scheme_resolved,
        admm_purification_override=admm_purification_override,
    )
    workflow_config = make_workflow_config(
        production_steps=md_steps,
        production_timestep=md_timestep,
        production_temperature=md_temperature,
        production_ensemble=md_ensemble,
        em_max_iter=em_max_iter,
        mm_nvt_steps=mm_nvt_steps,
        mm_npt_steps=mm_npt_steps,
        mm_timestep=mm_timestep,
        enable_qmmm_warmup=enable_qmmm_warmup,
        qmmm_handoff_policy=qmmm_handoff_policy,
        qmmm_transition_thermostat_timecon_fs=qmmm_transition_thermostat_timecon_fs,
        qmmm_transition_seed=qmmm_transition_seed,
        warmup_steps=warmup_steps,
        warmup_timestep=warmup_timestep,
        warmup_ensemble=warmup_ensemble,
        warmup_restraints=warmup_restraints,
        mm_equil_restraints=mm_equil_restraints,
        stateless_restart=stateless_restart,
        restraint_indices=restraint_indices,
        trajectory_format=trajectory_format,
        sampling_config=sampling_config,
        # S9: forward the CLI flag so that only the 35_qmmm_warmup stage
        # gets the extra &QMMM/&PRINT diagnostics; all other stages keep
        # their default (silent) behaviour.
        qmmm_verbose_diagnostics=bool(getattr(args, 'qmmm_verbose_diagnostics', False)),
    )
    stage_inputs, stage_meta = assemble_staged_cp2k_workflow(
        system_model,
        dft_config,
        workflow_config,
    )
    stage_input_names = list(stage_inputs.keys())
    if not stage_input_names:
        error("No stage inputs were generated.")
        sys.exit(1)

    if not dry_run:
        for stage_name, stage_content in stage_inputs.items():
            stage_path = os.path.join(out_dir, stage_name)
            with open(stage_path, 'w') as f:
                f.write(stage_content)
            info(f"Wrote staged input: {stage_name}")
        detail("Staged workflow inputs written with deterministic filenames.")

        # ── V7: post-emission parser-only input validation ──────────────
        # Opt-in; --cp2k-input-check=off|warn|strict.  Runs the resident
        # CP2K's parser over each stage so structural errors surface
        # before the user queues an expensive job.  Uses the binary
        # already identified by the early probe (_early_cp2k_install) so
        # the check aligns with the machine that will actually run the
        # job in the common desktop case.
        input_check_mode = getattr(args, 'cp2k_input_check', 'off')
        if input_check_mode != 'off':
            _ic_binaries = (_early_cp2k_install.get('binaries') or {}) if _early_cp2k_install else {}
            _ic_binary = next(iter(_ic_binaries.values()), None)
            if not _ic_binary:
                warn(
                    "--cp2k-input-check requested but no CP2K binary was detected; "
                    "skipping parser validation."
                )
            else:
                failures = []
                for stage_name in stage_input_names:
                    stage_path = os.path.join(out_dir, stage_name)
                    result = run_cp2k_input_check(
                        _ic_binary, stage_path, working_dir=out_dir
                    )
                    if result['ok']:
                        if result.get('mode') == 'syntax_only_without_restart_dependencies':
                            detail(
                                f"--input-check syntax-only OK: {stage_name} "
                                "(direct check requires upstream restart files)"
                            )
                        else:
                            detail(f"--input-check OK: {stage_name}")
                    else:
                        failures.append((stage_name, result))
                        # Always show the diagnostic tail so the user has
                        # something actionable in either warn or strict mode.
                        warn(
                            f"--input-check FAILED: {stage_name} "
                            f"(rc={result['returncode']}, err={result['error'] or 'parser error'})"
                        )
                        if result['stderr_tail']:
                            for ln in result['stderr_tail'].splitlines():
                                detail(f"  {ln}")
                if failures and input_check_mode == 'strict':
                    error(
                        f"--cp2k-input-check=strict: {len(failures)} stage(s) failed "
                        "the parser-only validation.  Aborting generation."
                    )
                    sys.exit(1)
                elif not failures:
                    info(
                        "All stage inputs passed `cp2k --input-check` against "
                        f"{os.path.basename(str(_ic_binary))}."
                    )
    else:
        info("[DRY RUN] Would write staged CP2K inputs:")
        for stage_name in stage_input_names:
            detail(stage_name)

    # ── Step 7: Prepare execution wrapper ────────────────────────────────
    step(7, TOTAL_STEPS, "Preparing execution wrapper")

    if args.hardware_aware is None:
        if interactive:
            hardware_probe_enabled = ask_yes(
                "Evaluate local hardware and CP2K installation for wrapper auto-tuning?",
                default=True,
            )
        else:
            hardware_probe_enabled = True
    else:
        hardware_probe_enabled = bool(args.hardware_aware)

    if hardware_probe_enabled:
        hardware_info = detect_local_hardware()
        # V6: reuse the authoritative early probe so that cp2k_capability
        # and cp2k_install are guaranteed to describe the same binary.
        # (Previously this was a second detect_cp2k_installation() call —
        # wasteful, and it could in principle desync from the capability
        # snapshot if PATH mutated mid-run.)
        cp2k_install = _early_cp2k_install
        info(
            "Detected hardware: "
            f"{hardware_info['logical_cores']} logical cores, "
            f"{hardware_info['physical_cores']} physical cores, "
            f"{hardware_info['gpu_count']} GPU(s)"
        )
        if hardware_info.get('gpu_detection_method') and hardware_info.get('gpu_count', 0) > 0:
            detail(f"GPU detection method: {hardware_info['gpu_detection_method']}")
        elif hardware_info.get('nvidia_smi_path'):
            detail(
                f"GPU detection attempted via {hardware_info['nvidia_smi_path']} "
                "but no devices were reported."
            )
        if hardware_info.get('memory_gb') is not None:
            detail(f"Detected memory: {float(hardware_info['memory_gb']):.1f} GB")
        if cp2k_install.get('binaries'):
            detail(
                "Detected CP2K binaries: "
                + ", ".join(f"{k}={v}" for k, v in cp2k_install['binaries'].items())
            )
        else:
            warn("No CP2K binaries detected in PATH during probing.")
        if cp2k_install.get('mpi_launcher'):
            detail(f"Detected MPI launcher: {cp2k_install['mpi_launcher']}")
        else:
            warn("No MPI launcher (mpirun/mpiexec/srun) detected in PATH.")
    else:
        logical = max(int(os.cpu_count() or 1), 1)
        hardware_info = {
            'logical_cores': logical,
            'physical_cores': max(_detect_physical_cores(), 1),
            'memory_gb': None,
            'gpu_count': 0,
            'gpus': [],
            'gpu_devices': [],
            'gpu_detection_method': 'disabled',
            'nvidia_smi_path': None,
        }
        cp2k_install = {
            'binaries': OrderedDict(),
            'mpi_launchers': OrderedDict(),
            'mpi_launcher': None,
        }
        detail("Hardware/CP2K probing disabled; using conservative wrapper defaults.")

    launch_cfg = recommend_cp2k_launch_settings(hardware_info, cp2k_install)
    wrapper_out = os.path.join(out_dir, f"run_{project_name.lower()}.sh")
    default_stage_input = stage_input_names[0] if stage_input_names else "10_em_mm.inp"
    wrapper_log_default = f"{os.path.splitext(default_stage_input)[0]}.log"

    if not dry_run:
        write_cp2k_execution_wrapper(
            wrapper_path=wrapper_out,
            input_filename=default_stage_input,
            log_filename=wrapper_log_default,
            launch_cfg=launch_cfg,
            hardware_info=hardware_info,
            cp2k_info=cp2k_install,
            detection_enabled=hardware_probe_enabled,
            stage_inputs=stage_inputs,
            stage_meta=stage_meta,
            cp2k_min_version_override=getattr(args, 'cp2k_min_version', None),
            cp2k_skip_version_check_default=bool(
                getattr(args, 'cp2k_skip_version_check', False)
            ),
        )
        readme_out = os.path.join(out_dir, "README_next_steps.txt")
        write_readme_next_steps(
            out_path=readme_out,
            wrapper_filename=os.path.basename(wrapper_out),
            stage_meta=stage_meta,
            cp2k_binary=launch_cfg.get('cp2k_binary'),
        )
        # ── V6/V9: structured CP2K compatibility & provenance report ───
        # Emit a single audit-grade artifact that collapses the previous
        # scattered hardware-aware README chunks (S12) and the version/
        # capability snapshot (V2/V3/V4) into one place.  Produced only
        # on real runs; --dry-run deliberately skips filesystem emission.
        #
        # cutoff/rel_cutoff/ngrids provenance: these arrive via three
        # channels — CLI defaults, explicit CLI overrides, or the
        # interactive wizard.  We cannot distinguish default from explicit
        # CLI for cutoff/rel_cutoff (argparse defaults collapse them), so
        # we report the *channel* (interactive vs CLI) plus whether --ngrids
        # was user-provided (the only one with `default=None`).
        mgrid_provenance = {
            'cutoff_source':
                'interactive prompt' if interactive else 'CLI (--cutoff, default 500 Ry)',
            'rel_cutoff_source':
                'interactive prompt' if interactive else 'CLI (--rel-cutoff, default 60 Ry)',
            'ngrids_source': (
                ('interactive prompt' if interactive else 'CLI (--ngrids)')
                if getattr(args, 'ngrids', None) is not None
                else 'MOLOPT default (5 for MOLOPT, 4 otherwise) — JCP 127, 114105 (2007)'
            ),
        }
        compat_report_out = os.path.join(out_dir, "cp2k_compat_report.txt")
        try:
            write_cp2k_compat_report(
                out_path=compat_report_out,
                cp2k_capability=cp2k_capability,
                substitutions=admm_substitutions_log,
                hardware_info=hardware_info,
                launch_cfg=launch_cfg,
                dft_config=dft_cfg,
                mgrid_provenance=mgrid_provenance,
                cp2k_binary=launch_cfg.get('cp2k_binary'),
            )
            info(f"Wrote CP2K compat report: {os.path.basename(compat_report_out)}")
        except Exception as _exc:
            # Report emission must never abort the generation pipeline;
            # the wrapper, inputs, and README are already on disk.
            warn(f"Could not write cp2k_compat_report.txt: {_exc}")

        # ── F.1.a: Unified run-provenance manifest ───────────────────────
        # Mirror the per-subsystem ADMM substitutions into the manifest
        # *before* writing it so the file is the single artifact a reviewer
        # needs to reconstruct every non-default decision (auto-recommended,
        # version-driven substitution, accepted/declined SCF promotion,
        # boundary-charge scheme, validator outcome, etc.).  Wrapped in a
        # try/except for the same reason as compat_report: provenance is an
        # audit artifact and must never abort the main emission path.
        try:
            run_provenance.extend_from_substitutions(admm_substitutions_log)
            provenance_out = os.path.join(out_dir, "run_provenance.txt")
            run_provenance.write_file(
                provenance_out,
                header_lines=(
                    f"project: {project_name}",
                    f"interactive: {bool(interactive)}",
                    f"dry_run: {bool(dry_run)}",
                    (
                        f"cp2k_version: "
                        f"{format_cp2k_version(cp2k_capability.version) if cp2k_capability.version else 'unknown'}"
                    ),
                    f"functional: {functional}",
                    f"basis_set: {basis_set}",
                    f"qm_atoms: {len(qm_indices)}",
                    f"links: {len(links)}",
                    f"qm_charge: {qm_charge}",
                    f"multiplicity: {multiplicity}",
                ),
            )
            info(
                f"Wrote run-provenance manifest: "
                f"{os.path.basename(provenance_out)} "
                f"({len(run_provenance)} entries)"
            )
        except Exception as _exc:
            warn(f"Could not write run_provenance.txt: {_exc}")

        info(f"Wrote execution wrapper: {os.path.basename(wrapper_out)}")
        info(f"Wrote workflow guide: {os.path.basename(readme_out)}")
        detail(f"Default run command: ./{os.path.basename(wrapper_out)}")
        detail(f"Default stage input: {default_stage_input}")
        detail(f"Default log file:   {wrapper_log_default}")
        detail(
            f"Wrapper settings: binary={launch_cfg['cp2k_binary']}, "
            f"MPI={'on' if launch_cfg['use_mpi'] else 'off'}, "
            f"ranks={launch_cfg['mpi_ranks']}, OMP_NUM_THREADS={launch_cfg['omp_threads']}"
        )
        if launch_cfg.get('selected_gpu_index') is not None:
            detail(
                "Selected GPU:   "
                f"{launch_cfg.get('selected_gpu_index')}"
                + (f" ({launch_cfg.get('selected_gpu_name')})" if launch_cfg.get('selected_gpu_name') else "")
            )
    else:
        info(f"[DRY RUN] Would write wrapper: {os.path.basename(wrapper_out)}")
        info(f"[DRY RUN] Wrapper default log would be: {wrapper_log_default}")
        info("[DRY RUN] Would write workflow guide: README_next_steps.txt")

    # ── Step 8: Summary ──────────────────────────────────────────────────
    step(8, TOTAL_STEPS, "Summary")

    print(f"\n  {C.BOLD}Input Files{C.R}")
    detail(f"Topology:    {os.path.basename(detected['prmtop'])}")
    detail(f"Coordinates: {os.path.basename(detected['rst7'])}")
    if detected.get('pdb'):
        detail(f"PDB:         {os.path.basename(detected['pdb'])}")
    detail(f"MM topology:  {mm_prmtop_ref}")
    detail(f"QM/MM topo:   {qmmm_prmtop_ref}")

    print(f"\n  {C.BOLD}QM Region{C.R}")
    detail(f"Total QM atoms: {len(qm_indices)}")
    detail(f"QM elements:    {', '.join(sorted(qm_elements.keys()))}")
    detail(f"Link bonds:     {len(links)}")
    if links:
        detail(f"Boundary scheme: {boundary_charge_scheme}")
    if boundary_charge_scheme in BOUNDARY_CHARGE_REDISTRIBUTION_SCHEMES and links:
        total_redistributed = sum(abs(link.get('M1_CHARGE_E', 0.0)) for link in links)
        detail(f"Total |q(M1)| redistributed to M2: {total_redistributed:.4f} e across {len(links)} links")
    detail(f"QM charge:      {qm_charge}")
    detail(f"Multiplicity:   {multiplicity}")
    detail(f"Spin mode:      {'UKS' if multiplicity != 1 else 'RKS'}")
    detail(f"QM cell ABC:    {qm_cell_abc} Å")
    detail(
        "QM cell policy: "
        f"padding {qmmm_periodic_policy.qm_cell_padding:.1f} Å, "
        f"target RCUT {qmmm_periodic_policy.target_multipole_rcut:.1f} Å"
    )
    detail(
        "QMMM MULTIPOLE: "
        f"effective RCUT {qmmm_periodic_meta['effective_rcut']:.1f} Å"
        + (
            f" (target relaxed from {qmmm_periodic_meta['target_rcut']:.1f} Å)"
            if qmmm_periodic_meta['rcut_relaxed']
            else ""
        )
    )

    print(f"\n  {C.BOLD}DFT/QM Setup{C.R}")
    detail(f"Functional:     {functional}")
    detail(f"Basis set:      {basis_set}")
    detail(f"GEEP library:   USE_GEEP_LIB {qmmm_geep_lib}")
    detail("DFT Poisson:    PERIODIC XYZ / PSOLVER PERIODIC")
    detail(f"CUTOFF:         {cutoff:g} Ry")
    detail(f"REL_CUTOFF:     {rel_cutoff:g} Ry")
    detail(f"NGRIDS:         {int(mgrid_ngrids)}")
    detail(f"ADMM:           {'enabled' if use_admm else 'disabled'}")
    if use_admm and admm_aux_basis:
        detail(f"ADMM aux basis: {admm_aux_basis}")
    elif requested_admm_aux_basis:
        detail(f"ADMM aux basis: {requested_admm_aux_basis} (requested)")
    if use_admm and admm_exch_correction_func:
        detail(f"ADMM exch corr: {admm_exch_correction_func}")
    if functional in HYBRID_DFT_FUNCTIONALS:
        detail(f"HF memory:      MAX_MEMORY {int(hf_max_memory)} per MPI rank")
    if qm_cell_meta.get('box_limited_axes'):
        detail(
            "QM/MM periodic note: MM box limited QM-cell growth on "
            + ", ".join(qm_cell_meta['box_limited_axes'])
        )

    print(f"\n  {C.BOLD}MM Force Field{C.R}")
    detail(f"1-4 policy:     {mm_scale14_policy.mode}")
    detail(f"EI_SCALE14:     {mm_scale14_policy.ei_scale14:.10f}")
    detail(f"VDW_SCALE14:    {mm_scale14_policy.vdw_scale14:.10f}")
    detail(f"Rationale:      {mm_scale14_policy.label}")
    detail("Runtime source: explicit &MM/&FORCEFIELD; preserved PRMTOP SCEE/SCNB kept for topology fidelity")

    print(f"\n  {C.BOLD}SCF Setup{C.R}")
    scf_diag_mode = should_use_diagonalization_scf(
        functional=functional,
        multiplicity=multiplicity,
        qm_elements=qm_elements,
        scf_profile=scf_profile_name,
    )
    detail(f"Profile:        {scf_profile_name}")
    detail(f"SCF engine:     {'Diagonalization/Mixing' if scf_diag_mode else 'OT'}")
    detail(f"MAX_SCF:        {scf_cfg['max_scf']}")
    detail(f"EPS_SCF:        {float(scf_cfg['eps_scf']):.1E}")
    detail(f"CHOLESKY:       {normalize_scf_cholesky(scf_cfg.get('cholesky')) or 'CP2K default (RESTORE)'}")
    detail(
        "QS EPS_DEFAULT: "
        f"{float(normalize_qs_eps_default(scf_cfg.get('qs_eps_default')) or QUICKSTEP_EPS_DEFAULT):.1E}"
    )
    if not scf_diag_mode:
        detail(
            "OT settings:    "
            f"MINIMIZER {ot_minimizer} | PRECONDITIONER {ot_preconditioner} | "
            f"ENERGY_GAP {float(ot_energy_gap):.1E} | "
            f"STEPSIZE {'AUTO(-1.0)' if ot_stepsize_policy.mode == 'AUTO' else format(ot_stepsize_policy.stepsize, 'g')}"
        )
    detail(f"MIXING:         {scf_cfg['mixing_method']} (ALPHA {float(scf_cfg['mixing_alpha']):.2f})")
    detail(f"OUTER_SCF:      MAX_SCF {scf_cfg['outer_max_scf']} | EPS_SCF {float(scf_cfg['outer_eps_scf']):.1E}")

    print(f"\n  {C.BOLD}Run Setup{C.R}")
    detail("Workflow:       staged MM->QM/MM")
    detail("Stage files:    " + ", ".join(stage_input_names))
    detail(f"Production:     ensemble={md_ensemble}, steps={md_steps}, timestep={md_timestep:g} fs")
    detail(f"Trajectory:     FORMAT {trajectory_format}")
    if sampling_config:
        detail(
            f"Sampling:       {sampling_config.method} "
            f"({os.path.basename(sampling_config.source_path)})"
        )
    if md_ensemble != 'NVE':
        detail(f"Temperature:    {md_temperature:g} K")
    detail(
        "Handoff:        "
        f"{qmmm_handoff_policy.mode} | "
        f"velocities={'on' if qmmm_handoff_policy.restart_velocities else 'off'} | "
        f"warmup={'on' if enable_qmmm_warmup else 'off'}"
    )
    detail(f"Handoff note:   {qmmm_handoff_policy.label}")
    detail(
        "Transition MD:  "
        f"CSVR TIMECON {first_qmmm_stage_dynamics.thermostat_timecon_fs:g} fs | "
        f"GLOBAL SEED {('off' if first_qmmm_stage_dynamics.global_seed is None else int(first_qmmm_stage_dynamics.global_seed))} | "
        f"INIT {(first_qmmm_stage_dynamics.initialization_method or 'restart_velocities')}"
    )
    detail(
        "Restart mode:   "
        + ("stateless (EXPERT override)" if stateless_restart else "stateful (conservative default)")
    )
    detail(
        "Restraints:     "
        f"MM equil={'on' if mm_equil_restraints else 'off'}, "
        f"QM/MM warmup={'on' if warmup_restraints else 'off'}"
    )
    detail(
        "MM stages:      "
        f"EM_MAX_ITER={em_max_iter}, NVT_steps={mm_nvt_steps}, NPT_steps={mm_npt_steps}, "
        f"dt={mm_timestep:g} fs"
    )
    if enable_qmmm_warmup:
        detail(f"Warmup stage:   ensemble={warmup_ensemble}, steps={warmup_steps}, timestep={warmup_timestep:g} fs")

    print(f"\n  {C.BOLD}Execution Wrapper{C.R}")
    detail(f"Hardware probe: {'enabled' if hardware_probe_enabled else 'disabled'}")
    if launch_cfg is not None:
        detail(f"CP2K binary:    {launch_cfg['cp2k_binary']}")
        if launch_cfg.get('use_mpi'):
            detail(
                "MPI launch:     "
                f"{launch_cfg.get('mpi_launcher')} "
                f"{launch_cfg.get('mpi_np_flag', '-np')} {launch_cfg.get('mpi_ranks')}"
            )
        else:
            detail("MPI launch:     disabled")
        detail(f"OMP threads:    {launch_cfg.get('omp_threads')}")
        if launch_cfg.get('selected_gpu_index') is not None:
            detail(
                "Selected GPU:   "
                f"{launch_cfg.get('selected_gpu_index')}"
                + (f" ({launch_cfg.get('selected_gpu_name')})" if launch_cfg.get('selected_gpu_name') else "")
            )
    if wrapper_out:
        detail(f"Wrapper file:   {os.path.basename(wrapper_out)}")
    if wrapper_log_default:
        detail(f"Default log:    {wrapper_log_default}")
    if readme_out:
        detail(f"Workflow guide: {os.path.basename(readme_out)}")

    print(f"\n  {C.BOLD}Output Files{C.R}")
    if not dry_run:
        for f in sorted(os.listdir(out_dir)):
            fpath = os.path.join(out_dir, f)
            size = os.path.getsize(fpath)
            detail(f"{f:>30s}  ({size:,} bytes)")
    else:
        detail("[DRY RUN] No files written")

    # Warnings
    warnings = []
    unresolved_all = sorted(
        set(
            list(unresolved)
            + list(mm_topology_data.get('unresolved', []))
            + list(qmmm_topology_data.get('unresolved', []))
        )
    )
    if unresolved_all:
        warnings.append(f"Unresolved atom types: {unresolved_all}")
    if any(GTH_CHARGE_MAP.get(e.upper()) is None for e in qm_elements):
        warnings.append("Some QM elements lack default GTH charge mappings — review &KIND POTENTIAL lines")
    if not box:
        warnings.append("No box dimensions — using default 100 Å cube. Verify &CELL ABC values.")
    if has_tm_qm and multiplicity == 1:
        warnings.append("Transition-metal QM region with multiplicity 1. Verify spin state before production runs.")
    if qm_electrons is not None and (qm_electrons % 2) != ((multiplicity - 1) % 2):
        warnings.append(
            f"Multiplicity/electron parity mismatch ({qm_electrons} electrons, multiplicity {multiplicity}). "
            "Review spin state."
        )
    if boundary_charge_scheme == 'NONE' and links:
        warnings.append(
            "Boundary charge scheme is NONE - M1 atoms retain full charges in QM embedding. "
            "This causes frontier-atom overpolarization. Not recommended for production."
        )
    if not enable_qmmm_warmup:
        warnings.append(
            "QM/MM warmup stage is disabled, so the first QM/MM production stage will absorb the MM->QM/MM Hamiltonian switch directly."
        )
    if qmmm_handoff_policy.mode == 'REUSE_VELOCITIES':
        warnings.append(
            "MM->QM/MM handoff reuses MM velocities on the first QM/MM stage. Review this choice if conservative re-equilibration is the priority."
        )
    if qmmm_handoff_policy.mode == 'FULL_STATE_CONTINUITY':
        warnings.append(
            "MM->QM/MM handoff reuses full MM dynamical state, including thermostat/barostat/RNG state, across the Hamiltonian change. This is an expert override."
        )
    if first_qmmm_stage_dynamics.global_seed is None and not qmmm_handoff_policy.restart_randomg:
        warnings.append(
            "First QM/MM stage resets stochastic state without emitting an explicit GLOBAL SEED. "
            "The run remains valid, but the handoff initialization policy is less explicit and less portable for reproducibility review."
        )
    if (
        first_qmmm_stage_dynamics.thermostat_timecon_fs >= DEFAULT_MD_THERMOSTAT_TIMECON_FS
        and not qmmm_handoff_policy.restart_thermostat
    ):
        warnings.append(
            "First QM/MM stage resets thermostat state but uses production-strength CSVR coupling. "
            "A shorter transition TIMECON is usually safer for deliberate MM->QM/MM re-equilibration."
        )
    if qmmm_periodic_meta['rcut_relaxed']:
        warnings.append(
            "Periodic QM/MM MULTIPOLE RCUT was reduced to "
            f"{qmmm_periodic_meta['effective_rcut']:.1f} Å from the target "
            f"{qmmm_periodic_meta['target_rcut']:.1f} Å because the available QM cell is too small. "
            "Review QM-cell padding and the periodic cell before production."
        )
    if qm_cell_meta.get('box_limited_axes'):
        warnings.append(
            "Periodic QM/MM QM-cell growth was limited by the MM box on axes "
            f"{', '.join(qm_cell_meta['box_limited_axes'])}. "
            "If you need a longer MULTIPOLE RCUT, enlarging padding alone will not help."
        )

    if warnings:
        print(f"\n  {C.YELLOW}{C.BOLD}Warnings requiring review:{C.R}")
        for w in warnings:
            warn(w)

    print(f"\n  {C.GREEN}{C.BOLD}Done!{C.R}\n")


# ─── Entry Point Dispatch ────────────────────────────────────────────────────
#
# Three execution modes:
#   1. --non-interactive (or --no-tui)  →  _main_cli_wizard()  [plain CLI]
#   2. Textual available + TTY + --tui  →  CharmmGui2Cp2kApp   [TUI screens]
#   3. Fallback                         →  _main_cli_wizard()  [plain CLI]
#
# The TUI is opt-in via --tui because it is a new frontend; the proven
# CLI wizard remains the production default until the TUI is validated
# through full regression testing.  When --tui is omitted and Textual is
# available, the script prints a one-line hint.
# ─────────────────────────────────────────────────────────────────────────────

def main():
    """Top-level entry point: dispatch to TUI or CLI wizard."""
    # Lightweight pre-parse: only need --tui, --no-tui, --non-interactive,
    # and --dir to decide which frontend to launch.  Full argparse runs
    # inside _main_cli_wizard() or inside the TUI screens.
    import sys as _sys

    _argv = _sys.argv[1:]
    _use_tui = False
    _forced_no_tui = False
    _non_interactive = False
    _tui_compat = False
    _tui_compact = False
    _tui_inline = False
    _tui_mouse = None
    _work_dir = '.'
    _program_name = os.path.basename(_sys.argv[0])
    _tui_command_names = {'charmmgui2cp2k-tui'}
    _help_requested = any(a in ('-h', '--help') for a in _argv)

    # Simple flag scan — avoids importing argparse twice for dispatch
    i = 0
    while i < len(_argv):
        arg = _argv[i]
        if arg == '--tui':
            _use_tui = True
        elif arg == '--no-tui':
            _forced_no_tui = True
        elif arg in ('--tui-compat', '--tui-screen-safe'):
            _tui_compat = True
            _tui_compact = True
            _tui_inline = True
            if _tui_mouse is None:
                _tui_mouse = False
        elif arg == '--tui-compact':
            _tui_compact = True
        elif arg == '--tui-inline':
            _tui_inline = True
        elif arg == '--tui-no-mouse':
            _tui_mouse = False
        elif arg == '--tui-mouse':
            _tui_mouse = True
        elif arg == '--non-interactive':
            _non_interactive = True
        elif arg == '--dir' and i + 1 < len(_argv):
            _work_dir = _argv[i + 1]
            i += 1
        elif arg.startswith('--dir='):
            _work_dir = arg.split('=', 1)[1]
        i += 1

    if (
        _program_name in _tui_command_names
        and not _forced_no_tui
        and not _non_interactive
        and not _help_requested
    ):
        _use_tui = True

    if HAS_TEXTUAL:
        _profile = _detect_tui_terminal_profile()
    else:
        _profile = {}
    if _use_tui and _profile.get('compat_recommended') and not _tui_compat:
        _tui_compat = True
        _tui_compact = True
        _tui_inline = True
        if _tui_mouse is None:
            _tui_mouse = False
    if _tui_mouse is None:
        _tui_mouse = True

    # Strip TUI dispatch/control flags from sys.argv before they reach argparse
    # in _main_cli_wizard(), which has no knowledge of these dispatch flags.
    _dispatch_flags = {
        '--tui',
        '--no-tui',
        '--tui-compat',
        '--tui-screen-safe',
        '--tui-compact',
        '--tui-inline',
        '--tui-no-mouse',
        '--tui-mouse',
    }
    _sys.argv = [_sys.argv[0]] + [
        a for a in _sys.argv[1:] if a not in _dispatch_flags
    ]

    # Dispatch logic
    if _non_interactive or _forced_no_tui:
        # Batch mode or explicit --no-tui → plain CLI wizard
        _main_cli_wizard()
    elif _use_tui and HAS_TEXTUAL and _sys.stdin.isatty():
        # Explicit --tui request with Textual available
        if _tui_compat:
            reasons = []
            if _profile.get('screen_like'):
                reasons.append("screen")
            if _profile.get('android_like'):
                reasons.append("Android/Termux")
            if _profile.get('small'):
                reasons.append(
                    f"{_profile.get('cols')}x{_profile.get('rows')}"
                )
            reason = ", ".join(reasons) or "requested"
            print(
                f"  {C.DIM}TUI compatibility mode active ({reason}): "
                f"compact layout, inline rendering, mouse disabled.{C.R}"
            )
        app = CharmmGui2Cp2kApp(
            work_dir=_work_dir,
            compact_mode=_tui_compact,
            compat_mode=_tui_compat,
            terminal_profile=_profile,
        )
        app.run(
            inline=bool(_tui_inline),
            inline_no_clear=bool(_tui_inline),
            mouse=bool(_tui_mouse),
        )
    elif _use_tui and not HAS_TEXTUAL:
        # User asked for TUI but Textual is not installed
        print(
            f"  {C.YELLOW}{C.BOLD}⚠{C.R} {C.YELLOW}"
            f"--tui requested but Textual is not available "
            f"(Python {_sys.version_info.major}.{_sys.version_info.minor}; "
            f"error: {_textual_import_error}).{C.R}\n"
            f"  {C.DIM}Falling back to plain CLI wizard. "
            f"Install Textual with: python3.11 -m pip install textual{C.R}"
        )
        _main_cli_wizard()
    elif _use_tui and not _sys.stdin.isatty():
        # TUI requested but not on a TTY (piped/scripted)
        print(
            f"  {C.YELLOW}{C.BOLD}⚠{C.R} {C.YELLOW}"
            f"--tui requested but stdin is not a TTY.{C.R}\n"
            f"  {C.DIM}Falling back to plain CLI wizard.{C.R}"
        )
        _main_cli_wizard()
    else:
        # Default: plain CLI wizard (proven production path)
        if HAS_TEXTUAL and _sys.stdin.isatty() and not _non_interactive:
            # Hint that TUI is available
            print(
                f"  {C.DIM}Tip: run with --tui for an interactive "
                f"full-screen interface (Textual {__import__('textual').__version__}).{C.R}"
            )
        _main_cli_wizard()


if __name__ == "__main__":
    main()
