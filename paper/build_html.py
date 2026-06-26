#!/usr/bin/env python3
"""Build the self-contained, publication-grade HTML edition of the manuscript.

    python paper/build_html.py   ->  paper/manuscript.html

All figures are embedded (PNG/SVG as data URIs; the architecture diagram is an
inline hand-authored SVG) so the output is a single portable file. Content is
kept in sync with paper/manuscript.md by hand.
"""

import base64
import datetime
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIG = os.path.join(ROOT, "figures")


def data_uri(path, mime):
    with open(path, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def build():
    # All three figures are embedded as isolated SVG data-URIs (vector; the TUI
    # screenshot is a raster embedded inside its SVG). Isolation via <img>
    # avoids any id/style collisions between the matplotlib and hand-authored SVGs.
    fig1 = data_uri(os.path.join(FIG, "fig1_architecture.svg"), "image/svg+xml")
    fig2 = data_uri(os.path.join(FIG, "fig2_tui.svg"), "image/svg+xml")
    fig3 = data_uri(os.path.join(FIG, "fig3_validation.svg"), "image/svg+xml")
    today = datetime.date.today().isoformat()

    # Plain replacement (not str.format) because the CSS contains literal braces.
    html = TEMPLATE
    for key, val in (("{fig1}", fig1), ("{fig2}", fig2),
                     ("{fig3}", fig3), ("{today}", today)):
        html = html.replace(key, val)
    out = os.path.join(HERE, "manuscript.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    print("wrote", os.path.relpath(out, ROOT), f"({len(html)//1024} KB)")


CSS = r"""
:root{
  --ink:#16202c; --muted:#5b6b7d; --faint:#8a98a8;
  --rule:#e3e8ef; --rule-strong:#c2ccd9;
  --accent:#1f6feb; --accent-deep:#14507a; --accent-soft:#eaf1fb;
  --ok:#0f7b4f; --ok-soft:#ecfdf5;
  --maxw:830px;
  --serif:"Iowan Old Style","Charter","Palatino Linotype","Georgia",serif;
  --sans:"Inter",ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  --mono:"SFMono-Regular",ui-monospace,"JetBrains Mono","Cascadia Code",Menlo,Consolas,monospace;
}
*{box-sizing:border-box;}
html{-webkit-text-size-adjust:100%;}
body{
  margin:0; color:var(--ink); background:#eef1f5;
  font-family:var(--serif); font-size:18px; line-height:1.62;
}
.page{
  max-width:var(--maxw); margin:34px auto 60px; background:#fff;
  padding:56px 64px 64px; border-radius:6px;
  box-shadow:0 1px 2px rgba(16,32,48,.06),0 12px 40px rgba(16,32,48,.10);
}
/* ── Masthead ── */
.kicker{font-family:var(--sans); font-weight:700; font-size:12.5px; letter-spacing:.16em;
  text-transform:uppercase; color:var(--accent); margin:0 0 14px;}
.kicker .dot{color:var(--faint); margin:0 8px;}
h1.title{font-family:var(--sans); font-weight:800; font-size:30px; line-height:1.2;
  letter-spacing:-.015em; margin:0 0 18px; color:#0f1924;}
.authors{font-family:var(--sans); font-size:16.5px; font-weight:600; color:#21303f; margin:0 0 4px;}
.authors .corr{color:var(--accent); font-weight:700;}
.affil{font-family:var(--sans); font-size:13px; color:var(--muted); line-height:1.5; margin:6px 0 0;}
.affil sup{color:var(--accent-deep); font-weight:700;}
.meta{display:flex; flex-wrap:wrap; gap:8px; margin:20px 0 4px;}
.chip{font-family:var(--sans); font-size:11.5px; font-weight:600; letter-spacing:.02em;
  color:#33475b; background:#f1f5fa; border:1px solid var(--rule);
  padding:4px 10px; border-radius:999px;}
.chip.ok{color:var(--ok); background:var(--ok-soft); border-color:#bce6d2;}
.chip a{color:inherit; text-decoration:none;}
.rule{height:3px; background:linear-gradient(90deg,var(--accent),#7fb0f5 60%,transparent);
  border:0; margin:22px 0 6px; border-radius:2px;}
/* ── Abstract ── */
.abstract{background:linear-gradient(180deg,#fbfcfe,#f6f9fe); border:1px solid var(--rule);
  border-left:4px solid var(--accent); border-radius:8px; padding:20px 24px; margin:26px 0 8px;}
.abstract h2{font-family:var(--sans); font-size:12.5px; letter-spacing:.14em; text-transform:uppercase;
  color:var(--accent-deep); margin:0 0 8px;}
.abstract p{margin:0; font-size:16.5px; line-height:1.6;}
.struct{margin:14px 0 0; font-family:var(--sans); font-size:13.5px; color:#2a3a4a; line-height:1.55;}
.struct b{color:var(--accent-deep);}
/* ── Body ── */
.body{margin-top:14px;}
.body h2{font-family:var(--sans); font-weight:750; font-size:20px; color:#10202e;
  margin:38px 0 6px; padding-bottom:7px; border-bottom:1px solid var(--rule);}
.body h2 .n{color:var(--accent); margin-right:.5em; font-weight:800;}
.body h3{font-family:var(--sans); font-weight:700; font-size:15.5px; color:#1c2c3a; margin:24px 0 4px;}
.body h3 .tag{font-family:var(--sans); font-size:10.5px; font-weight:700; letter-spacing:.06em;
  text-transform:uppercase; color:#9a6700; background:#fff5e0; border:1px solid #f3e0ad;
  padding:2px 8px; border-radius:999px; margin-left:10px; vertical-align:middle;}
.body p{margin:10px 0; text-align:justify; hyphens:auto;}
.body ul{margin:10px 0; padding-left:0; list-style:none;}
.body ul li{position:relative; padding-left:22px; margin:8px 0; text-align:justify; hyphens:auto;}
.body ul li::before{content:""; position:absolute; left:4px; top:.62em; width:7px; height:7px;
  background:var(--accent); border-radius:2px; transform:rotate(45deg);}
code{font-family:var(--mono); font-size:.82em; background:#f3f5f8; color:#2a3140;
  padding:.12em .38em; border-radius:4px; border:1px solid #e7ebf1;}
strong{font-weight:700; color:#10202e;}
a{color:var(--accent-deep); text-decoration:none; border-bottom:1px solid #c9d8ef;}
/* ── Table ── */
.tbl-wrap{margin:16px 0 6px; overflow-x:auto;}
table.bt{border-collapse:collapse; width:100%; font-family:var(--sans); font-size:13.5px;}
table.bt caption{caption-side:top; text-align:left; font-size:13.5px; color:var(--muted);
  margin-bottom:8px;}
table.bt caption b{color:var(--ink);}
table.bt thead th{font-weight:700; color:#10202e; text-align:left; padding:9px 12px;
  border-top:2px solid var(--ink); border-bottom:1.5px solid var(--rule-strong);}
table.bt td{padding:8px 12px; border-bottom:1px solid var(--rule); vertical-align:top; color:#2c3a48;}
table.bt tbody tr:last-child td{border-bottom:2px solid var(--ink);}
table.bt tr.hi td{background:var(--accent-soft); font-weight:600; color:#13314f;}
.yes{color:var(--ok); font-weight:700;} .no{color:#9aa6b2;}
/* ── Figures ── */
figure{margin:26px 0; text-align:center;}
figure .frame{display:inline-block; max-width:100%; padding:14px; background:#fff;
  border:1px solid var(--rule); border-radius:10px; box-shadow:0 6px 22px rgba(16,32,48,.07);}
figure img, figure svg{display:block; max-width:100%; height:auto; margin:0 auto; border-radius:4px;}
figure.arch .frame{background:#fff;}
figure.arch svg{width:600px;}
figcaption{font-family:var(--sans); font-size:13px; color:var(--muted); line-height:1.5;
  margin:12px auto 0; max-width:640px; text-align:left;}
figcaption .lab{font-weight:700; color:var(--accent-deep);}
/* ── References ── */
.refs{counter-reset:r; list-style:none; padding:0; margin:8px 0;
  font-family:var(--sans); font-size:13.5px; line-height:1.5; color:#28323d;}
.refs li{position:relative; padding-left:34px; margin:9px 0;}
.refs li::before{counter-increment:r; content:counter(r); position:absolute; left:0; top:1px;
  width:22px; height:22px; line-height:22px; text-align:center; font-weight:700; font-size:11.5px;
  color:var(--accent-deep); background:var(--accent-soft); border-radius:6px;}
.refs em{color:#1c2c3a;}
/* ── Notes / footer ── */
.note{font-family:var(--sans); font-size:12.5px; color:var(--muted); font-style:italic; margin:8px 0;}
.editorial{background:#fffaf0; border:1px solid #f0e2c0; border-radius:8px; padding:10px 14px;
  font-family:var(--sans); font-size:12.5px; color:#7a5b12; margin:18px 0;}
footer{margin-top:46px; padding-top:18px; border-top:1px solid var(--rule);
  font-family:var(--sans); font-size:12px; color:var(--faint); line-height:1.6;}
footer .badges{display:flex; gap:8px; flex-wrap:wrap; margin-bottom:10px;}
/* ── Responsive / print ── */
@media (max-width:680px){
  body{font-size:16.5px;} .page{padding:30px 20px; margin:0; border-radius:0;}
  h1.title{font-size:24px;} figure.arch svg{width:100%;}
}
@media print{
  body{background:#fff; font-size:10.5pt;}
  .page{box-shadow:none; margin:0; max-width:none; padding:0;}
  figure,table,.abstract{break-inside:avoid;} h2,h3{break-after:avoid;}
  a{color:var(--ink); border:0;}
  @page{margin:18mm 16mm;}
}
"""

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>charmmgui2cp2k — automated CP2K QM/MM input generation</title>
<meta name="description" content="charmmgui2cp2k: the first automated CHARMM-GUI/AMBER to CP2K QM/MM input generator."/>
<style>{css}</style>
</head>
<body>
<article class="page">

  <p class="kicker">Application Note<span class="dot">&middot;</span>Structural &amp; Computational Bioinformatics<span class="dot">&middot;</span>Preprint</p>

  <h1 class="title">charmmgui2cp2k: automated generation of CP2K QM/MM input from CHARMM-GUI/AMBER biomolecular setups</h1>

  <p class="authors">[ Author One ]<sup>1</sup>, [ Author Two ]<sup>1,2</sup>, <span class="corr">[ Corresponding Author ]<sup>1,&#42;</sup></span></p>
  <p class="affil">
    <sup>1</sup>&nbsp;[ Department / Institute, University, City, Country ]&nbsp;&nbsp;
    <sup>2</sup>&nbsp;[ Second affiliation ]<br/>
    <sup>&#42;</sup>&nbsp;Correspondence:&nbsp;[ email ]
  </p>

  <div class="meta">
    <span class="chip ok">Open source &middot; MIT</span>
    <span class="chip">v0.1.0</span>
    <span class="chip">Python 3.10&ndash;3.12</span>
    <span class="chip">CP2K &ge; 7.1</span>
    <span class="chip">DOI: 10.xxxx/zenodo &middot; on release</span>
    <span class="chip"><a href="#avail">Availability &darr;</a></span>
  </div>
  <hr class="rule"/>

  <section class="abstract">
    <h2>Abstract</h2>
    <p>Setting up a biomolecular quantum-mechanics/molecular-mechanics (QM/MM) simulation in
    CP2K from an existing AMBER&nbsp;/&nbsp;CHARMM-GUI system is a manual, error-prone expert task:
    the QM region must be enumerated, every boundary link atom defined, boundary charges
    redistributed, and the AMBER topology pre-edited. We present <strong>charmmgui2cp2k</strong>,
    a terminal-native wizard (a plain CLI and a full-screen Textual TUI sharing one validated
    core) that automates this end to end and emits immediately runnable CP2K QM/MM input,
    embedding the scientific safeguards a careful setup requires &mdash; topology validation,
    hydrogen link atoms with forbidden-cut rejection, charge-conserving boundary schemes,
    spin-state risk analysis, and CP2K version/data-file capability gating. To our knowledge it
    is the first automated CHARMM-GUI/AMBER&nbsp;&rarr;&nbsp;CP2K QM/MM input generator. We
    validate correctness by NVE energy conservation, real-CP2K parser acceptance, and an
    independent ParmEd cross-check, and show the generated boundary is energy-conserving.</p>
    <p class="struct"><b>Availability and implementation:</b> open source under the MIT license;
    source, tests, and the reproducible validation harness at
    <a href="#avail">the repository</a> (archived on Zenodo at release).
    &nbsp;<b>Contact:</b> [ email ].</p>
  </section>

  <div class="body">

    <h2><span class="n">1</span>Statement of need</h2>
    <p>CP2K is a widely used engine for biomolecular QM/MM, able to read AMBER <code>prmtop</code>
    and CHARMM PSF topologies directly, but it ships no setup GUI or wizard: users hand-author
    the <code>&amp;QMMM</code> region (<code>QM_KIND</code>/<code>MM_INDEX</code>), every
    <code>&amp;LINK</code> atom, the boundary charge handling, and Lennard-Jones/charge pre-edits
    of the topology. Mistakes in any of these silently produce physically wrong simulations.</p>
    <p>No existing tool closes this gap end to end (Table&nbsp;1). CHARMM-GUI&rsquo;s QM/MM
    Interfacer is web-based, semiempirical-only, and targets the CHARMM/AMBER engines, not CP2K;
    ASH is a scripting library rather than a guided wizard; MiMiCPy targets CPMD+GROMACS.
    <strong>charmmgui2cp2k</strong> fills this gap and is delivered as an offline, terminal-native
    wizard aimed at enzyme active sites, flavoenzymes, metalloproteins, and other redox-cofactor systems
    &mdash; where boundary and charge correctness matter most.</p>

    <div class="tbl-wrap">
    <table class="bt">
      <caption><b>Table 1.</b> Landscape of QM/MM setup tools and the unmet gap.</caption>
      <thead><tr><th>Tool</th><th>Form</th><th>Engine target</th><th>Closes CHARMM-GUI/AMBER&rarr;CP2K gap?</th></tr></thead>
      <tbody>
        <tr><td>CHARMM-GUI QM/MM Interfacer</td><td>web GUI</td><td>CHARMM/AMBER, semiempirical</td><td><span class="no">No</span> &mdash; no CP2K, no DFT</td></tr>
        <tr><td>CP2K (native)</td><td>input language</td><td>CP2K</td><td><span class="no">No</span> &mdash; no setup wizard</td></tr>
        <tr><td>ASH</td><td>Python library</td><td>many (CP2K as a backend)</td><td><span class="no">No</span> &mdash; library, no CHARMM-GUI ingest</td></tr>
        <tr><td>MiMiCPy</td><td>wizard</td><td>CPMD + GROMACS</td><td><span class="no">No</span> &mdash; different stack</td></tr>
        <tr><td>gmx2qmmm</td><td>script</td><td>GROMACS&harr;Gaussian/ORCA/&hellip;</td><td><span class="no">No</span> &mdash; no CP2K</td></tr>
        <tr><td>QwikMD</td><td>VMD GUI</td><td>NAMD</td><td><span class="no">No</span> &mdash; no CP2K</td></tr>
        <tr class="hi"><td>charmmgui2cp2k</td><td>CLI + TUI wizard</td><td>CP2K</td><td><span class="yes">Yes</span></td></tr>
      </tbody>
    </table>
    </div>

    <h2><span class="n">2</span>Implementation</h2>
    <p>The pipeline is a single Python module exposing three frontends over one shared scientific
    core (Figure&nbsp;1): a plain CLI wizard, a Textual TUI workbench (Figure&nbsp;2; eight phases:
    System&nbsp;&rarr;&nbsp;QM&nbsp;region&nbsp;&rarr;&nbsp;Boundary&nbsp;&rarr;&nbsp;Method&nbsp;&rarr;&nbsp;Electronic&nbsp;&rarr;&nbsp;Workflow&nbsp;&rarr;&nbsp;Preview&nbsp;&rarr;&nbsp;Generate),
    and a non-interactive batch mode. The core performs:</p>
    <ul>
      <li><strong>Topology validation</strong> &mdash; AMBER <code>POINTERS</code>/array
        cross-checks, CHAMBER rejection, mixed-SCEE detection.</li>
      <li><strong>QM/MM boundary</strong> &mdash; automatic detection of bonds crossing the
        boundary, hydrogen link-atom capping (IMOMM), classification and rejection of chemically
        impossible cuts, M1/M2 neighbour enrichment, GEEP embedding radii, and generation-time
        link-geometry sanity checks.</li>
      <li><strong>Charge conservation</strong> &mdash; residual-charge redistribution across
        split-residue MM atoms with PRMTOP round-trip verification, plus a combined cross-channel
        audit (FIST residual + ADD_MM_CHARGE embedding).</li>
      <li><strong>Electronic structure</strong> &mdash; GTH-valence electron counting,
        multiplicity-parity enforcement, and a multi-detector spin-risk taxonomy (transition
        metals, redox cofactors, &pi;-stacking geometry, unresolved elements) that refuses to
        auto-assign spin when the choice is unreliable.</li>
      <li><strong>CP2K capability gating</strong> &mdash; keyword/basis/dispersion emission gated
        against the detected CP2K version <em>and</em> against the presence of the corresponding
        data files (GTH potentials, ADMM basis, dftd3.dat) in the install.</li>
      <li><strong>Provenance</strong> &mdash; every generated input embeds a deterministic
        parameter header; a full decision log, boundary-charge audit, and electronic-state report
        are written alongside.</li>
    </ul>
    <p>A <code>--strict</code> mode turns unresolved scientific concerns into a non-zero exit for
    reproducible pipelines.</p>

    <figure class="arch">
      <div class="frame"><img src="{fig1}" alt="charmmgui2cp2k architecture and data flow"/></div>
      <figcaption><span class="lab">Figure 1.</span> Architecture and data flow. Three frontends
      share one validated scientific core that ingests CHARMM-GUI/AMBER inputs, applies six
      sequential stages under cross-cutting safeguards, and emits runnable CP2K QM/MM input plus
      machine- and human-readable audit artifacts.</figcaption>
    </figure>

    <figure>
      <div class="frame"><img src="{fig2}" alt="Annotated Textual TUI workbench screenshot"/></div>
      <figcaption><span class="lab">Figure 2.</span> The Textual TUI workbench (rendered live,
      headlessly) on the System phase. Callouts: <strong>(1)</strong> the phase rail showing current
      and remaining steps; <strong>(2)</strong> the sticky system summary; <strong>(3)</strong>
      auto-detected inputs, each with its provenance; <strong>(4)</strong> progressive disclosure of
      expert detail. Keyboard-first navigation makes the next safe action obvious without a manual.</figcaption>
    </figure>

    <h2><span class="n">3</span>Validation</h2>
    <p>All validation is reproducible from the <code>validation/</code> harness on a committed
    alanine-dipeptide demo system (build script included); production-scale agreement is the
    flavoenzyme case study (&sect;3.4).</p>

    <h3>3.1&nbsp;&nbsp;Real-CP2K acceptance</h3>
    <p>Every generated staged input passes a real CP2K binary&rsquo;s parser-only
    <code>--input-check</code> (CP2K&nbsp;2025.2); see
    <code>tests/regression/test_cp2k_input_check.py</code>.</p>

    <h3>3.2&nbsp;&nbsp;NVE energy conservation</h3>
    <p>A self-contained NVE QM/MM trajectory of the generated setup (PBE, 50&nbsp;fs) gives a
    conserved-quantity range of 0.104&nbsp;kcal/mol and a drift of
    <strong>2.6&times;10<sup>&minus;4</sup>&nbsp;kT/dof/ps</strong> with no systematic trend
    (Figure&nbsp;3a), demonstrating the link atoms, deleted boundary terms, and boundary charges
    are mutually consistent. A longer trajectory with tighter SCF tolerance reduces this toward
    the literature reference (10<sup>&minus;5</sup>&ndash;10<sup>&minus;6</sup>&nbsp;kT/dof/ps;
    G&ouml;tz <em>et al.</em>, 2014 [6]).</p>

    <h3>3.3&nbsp;&nbsp;Boundary handling and reproducibility</h3>
    <p>Single-point energies under the NONE&nbsp;/&nbsp;Z1&nbsp;/&nbsp;CHARGE_SHIFT boundary
    schemes differ measurably: NONE (the full M1 frontier charge retained in the embedding) lies
    2.61&nbsp;kcal/mol from CHARGE_SHIFT, while Z1 and CHARGE_SHIFT (both remove M1 from the
    embedding) agree to 0.26&nbsp;kcal/mol (Figure&nbsp;3b). This confirms the boundary charge
    treatment is physically active and that the redistribution schemes control the frontier
    over-polarization NONE exhibits. Repeated runs are bitwise reproducible
    (|&Delta;E|&nbsp;=&nbsp;5&times;10<sup>&minus;15</sup>&nbsp;Ha). Element identities and charges
    agree with an independent ParmEd parse (<code>tests/unit/test_parmed_crosscheck.py</code>).</p>

    <figure>
      <div class="frame"><img src="{fig3}" alt="Validation: NVE energy conservation and boundary-scheme over-polarization"/></div>
      <figcaption><span class="lab">Figure 3.</span> Validation on the alanine-dipeptide demo
      (PBE; CP2K&nbsp;2025.2). <strong>(a)</strong> NVE energy conservation &mdash; the conserved
      quantity oscillates within ~0.1&nbsp;kcal/mol and the transient decays; bounded, with no
      systematic drift (2.6&times;10<sup>&minus;4</sup>&nbsp;kT/dof/ps). <strong>(b)</strong>
      Boundary-scheme over-polarization &mdash; single-point QM/MM energy relative to CHARGE_SHIFT:
      NONE (full M1 charge in the embedding) is an outlier by +2.61&nbsp;kcal/mol, while Z1 and
      CHARGE_SHIFT (both remove M1 from the embedding) agree to within 0.26&nbsp;kcal/mol.</figcaption>
    </figure>

    <h3>3.4&nbsp;&nbsp;Flavoenzyme case study <span class="tag">data pending</span></h3>
    <p>Headline validation on a flavoenzyme active site (L-amino-acid oxidase, LAAO; a redox-active FAD
    cofactor), where the QM region spans the flavin and substrate and both boundary/charge handling
    and spin-state assignment are most scrutinized: single-point and short-MD agreement against a
    reference, plus a boundary over-polarization probe. The harness runs unchanged via
    <code>--dir</code>; results will be inserted here.</p>

    <h3>3.5&nbsp;&nbsp;Benchmark suite <span class="tag">data pending</span></h3>
    <p>Agreement with the BioExcel GROMACS+CP2K QM/MM benchmark systems (MQAE, ClC, CBD_PHY, GFP)
    to show tool-generated CP2K input matches standalone references.</p>

    <h2><span class="n">4</span>Usability and reproducibility (FAIR)</h2>
    <p>The primary workflow is designed to need no external manual: defaults trace to source
    evidence, expert controls use progressive disclosure, validation failures state the corrective
    action, and the generation phase shows progress and final artifacts. Each generated input
    embeds its full parameter set as a comment header (FAIR&nbsp;R1.2 [15]); a one-command
    <code>--demo</code> reproduces a complete run from bundled data. The software ships an OSI
    license, a <code>CITATION.cff</code>, and continuous-integration tests; releases will be
    archived on Zenodo for a versioned DOI.</p>

    <h2 id="avail"><span class="n">5</span>Availability</h2>
    <p>Source code, tests, and the validation harness are available under the MIT license at
    <a href="https://github.com/aleff-ferreira/charmmgui2cp2k">https://github.com/aleff-ferreira/charmmgui2cp2k</a>, archived on Zenodo for a versioned DOI. Tested on
    Linux with Python&nbsp;3.10&ndash;3.12 and CP2K&nbsp;&ge;&nbsp;7.1.</p>

    <h2>References</h2>
    <ol class="refs">
      <li>Senn HM, Thiel W. QM/MM methods for biomolecular systems. <em>Angew Chem Int Ed.</em> 2009;48(7):1198&ndash;1229.</li>
      <li>Lin H, Truhlar DG. QM/MM: what have we learned, where are we, and where do we go from here? <em>Theor Chem Acc.</em> 2007;117:185&ndash;199.</li>
      <li>Laino T, Mohamed F, Curioni A, VandeVondele J. An efficient real space multigrid QM/MM electrostatic coupling. <em>J Chem Theory Comput.</em> 2005;1(6):1176&ndash;1184.</li>
      <li>Laino T, Mohamed F, Curioni A, VandeVondele J. An efficient linear-scaling electrostatic coupling for treating periodic boundary conditions in QM/MM simulations. <em>J Chem Theory Comput.</em> 2006;2(5):1370&ndash;1378.</li>
      <li>K&uuml;hne TD, Iannuzzi M, Del Ben M, <em>et al.</em> CP2K: An electronic structure and molecular dynamics software package &mdash; Quickstep. <em>J Chem Phys.</em> 2020;152:194103.</li>
      <li>G&ouml;tz AW, Clark MA, Walker RC. An extensible interface for QM/MM molecular dynamics simulations with AMBER. <em>J Comput Chem.</em> 2014;35(2):95&ndash;108.</li>
      <li>Maier JA, Martinez C, Kasavajhala K, Wickstrom L, Hauser KE, Simmerling C. ff14SB: improving the accuracy of protein side chain and backbone parameters. <em>J Chem Theory Comput.</em> 2015;11(8):3696&ndash;3713.</li>
      <li>Grimme S, Ehrlich S, Goerigk L. Effect of the damping function in dispersion corrected density functional theory. <em>J Comput Chem.</em> 2011;32(7):1456&ndash;1465.</li>
      <li>Guidon M, Hutter J, VandeVondele J. Auxiliary density matrix methods for Hartree&ndash;Fock exchange calculations. <em>J Chem Theory Comput.</em> 2010;6(8):2348&ndash;2364.</li>
      <li>VandeVondele J, Hutter J. Gaussian basis sets for accurate calculations on molecular systems in gas and condensed phases. <em>J Chem Phys.</em> 2007;127:114105.</li>
      <li>Cordero B, G&oacute;mez V, Platero-Prats AE, <em>et al.</em> Covalent radii revisited. <em>Dalton Trans.</em> 2008;(21):2832&ndash;2838.</li>
      <li>Jo S, Kim T, Iyer VG, Im W. CHARMM-GUI: a web-based graphical user interface for CHARMM. <em>J Comput Chem.</em> 2008;29(11):1859&ndash;1865.</li>
      <li>Lee J, Cheng X, Swails JM, <em>et al.</em> CHARMM-GUI Input Generator for NAMD, GROMACS, AMBER, OpenMM, and CHARMM/OpenMM simulations. <em>J Chem Theory Comput.</em> 2016;12(1):405&ndash;413.</li>
      <li>List M, Ebert P, Albrecht F. Ten Simple Rules for Developing Usable Software in Computational Biology. <em>PLoS Comput Biol.</em> 2017;13(1):e1005265.</li>
      <li>Barker M, Chue Hong NP, Katz DS, <em>et al.</em> Introducing the FAIR Principles for research software. <em>Sci Data.</em> 2022;9:622.</li>
    </ol>

    <p class="editorial"><strong>Editorial note (preprint).</strong> Author names/affiliations and
    the repository DOI are placeholders pending submission; &sect;3.4&ndash;3.5 await the production
    metalloprotein system and the external benchmark suite. Reference details should be verified
    against the publishers&rsquo; records before submission.</p>

  </div>

  <footer>
    <div class="badges">
      <span class="chip ok">MIT license</span>
      <span class="chip">Reproducible: <code>figures/make_figures.py</code></span>
      <span class="chip">Figures embedded</span>
    </div>
    charmmgui2cp2k &mdash; automated CHARMM-GUI/AMBER&rarr;CP2K QM/MM input generation.
    Self-contained manuscript compiled {today}. Figures 3&ndash;4 are generated directly from the
    committed validation output; Figure&nbsp;2 is a live headless render of the TUI.
  </footer>

</article>
</body>
</html>
"""

# CSS is injected via str.replace to avoid brace-escaping the whole stylesheet.
TEMPLATE = TEMPLATE.replace("{css}", CSS)

if __name__ == "__main__":
    build()
