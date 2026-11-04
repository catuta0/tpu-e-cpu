# DOC-01 — Scientific article, first full draft (IEEEtran conference)
Status: PARTIAL (draft complete and builds cleanly; all SC-TPU hardware numbers are placeholders by design, 18 printed placeholders open)
Agent: documentation-engineer   Date: 2026-11-04T03:50Z   Input revision: eee3352 (HEAD moved to 9144278 during the task; `git diff --stat eee3352 HEAD` = management/GATES.md only, so no input changed). Working tree dirty only from other agents' TPU WIP (not used). Not committed (as instructed).

## Requirements addressed
- REQ-DOC-005 (scientific article: architecture, SC method, accuracy vs K and RNG mode, resources, timing, latency, limitations, references) — partially: TPU resources/timing are TBD.
- REQ-AI-007 (every accuracy with n, k and 95 % Wilson CI) — Table II and Fig. 4 satisfy it for the article.
- REQ-DOC-003 (English), REQ-DOC-004 (labels SIMULATION / CALCULATION / SOURCE / ASSUMPTION in text; no MEASUREMENT claimed).

## Inputs
design/architecture/ARCHITECTURE.md (rev A + A.1 + A.2), management/INTERFACES.json, management/DECISIONS.md (ADR-000..007), requirements/REQUIREMENTS.md, requirements/BUDGETS.md, reports/sw/accuracy.json (git_rev field d2ed476-dirty), reports/sw/error_model.md, reports/sw/cpu_tests_summary.json, management/metrics.json, management/SOURCES.md, management/TOOLCHAIN.md, management/handoffs/fpga-engineer/RTL-CPU.md, management/handoffs/software-engineer/SW-01a.md and SW-01b.md, reports/fpga/cpu/cpu_synth_pnr.txt, logs/cpu/sim_cpu_summary.log, logs/cpu/pnr_s{1,2,3}.log, logs/sw/gen_hex.log, logs/sw/pytest_model.log, scripts/budgets/logs/{latency_budget,lfsr_check}.log, reports/article/smoke/refs.bib.

## Outputs
| Path | Content |
|---|---|
| reports/article/main.tex | 7-page IEEEtran conference draft: Abstract, I–VII, 5 figures (3 TikZ: SoC block diagram, MAC lane/APC datapath, tile timing diagram; 2 matplotlib), 4 tables (memory map, accuracy vs K x mode with k and CI and ensemble, latency vs K, resources/Fmax). 63 `% evidence:` comments. `\TBD{name}` macro (red bold [TBD:name]) in preamble. |
| reports/article/refs.bib | 15 entries (Gaines 1969; Alaghi & Hayes 2013; Brown & Card 2001; Kim et al. DAC 2016; Ren et al. ASPLOS 2017; Waterman & Asanović RISC-V vol. I 20191213; Wolf PicoRV32; Shah et al. FCCM 2019 Yosys+nextpnr; Yosys; Apicula; Icarus; Verilator; Pedregosa et al. JMLR 2011; Alpaydin & Kaynak UCI digits 1998; Sipeed Tang Nano 9K wiki). Uncertain fields omitted (page numbers of Alaghi 2013 and Brown & Card 2001; full author lists of Kim 2016, Ren 2017, Shah 2019, Pedregosa 2011 abbreviated to "et al."). |
| reports/article/main.pdf | built PDF, sha256 1be3085d…58ac |
| reports/article/PLACEHOLDERS.md | list of all 19 placeholders (18 printed + 1 in a comment), where they are, evidence expected; plus list of rev-A numbers that rev B will change |
| reports/figures/article_figures.py | generator for both data figures; reads only reports/sw/accuracy.json and prints every plotted value |
| reports/figures/article_acc_vs_k.pdf, article_rms_vs_k.pdf | vector figures (accuracy vs K per mode with Wilson CI + 16-offset ensemble; RMS error measured vs eq. (2) vs hardware seeds) |
| logs/doc/article_figures.log | figure-script output (all plotted values) |
| logs/doc/article_latex.log | clean latexmk build + log checks + pdfinfo + sha256 |

## Checks actually performed
| Check | Command · tool | Log | Result (quoted) |
|---|---|---|---|
| Figures | `.venv/bin/python reports/figures/article_figures.py` · matplotlib 3.11.2 | logs/doc/article_figures.log | `wrote .../article_rms_vs_k.pdf`, rc=0; PNG renders inspected visually (no overlaps after two fixes) |
| Build (clean) | `latexmk -C; latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex` · TeX Live 2023, Latexmk 4.83, BibTeX | logs/doc/article_latex.log | `LATEXMK_EXIT=0`; `Output written on main.pdf (7 pages, 383496 bytes).` |
| Undefined refs/cites, overfull boxes, warnings | `grep -nE "undefined\|Overfull\|Error\|Warning" main.log` | same | `no undefined/overfull/error/warning lines` (0 undefined references, 0 undefined citations, 0 overfull boxes) |
| BibTeX | main.blg | same | `warning$ -- 0`; 15 bibitems |
| Remaining layout notes | main.log | — | 3 Underfull \hbox (badness 10000) in the bibliography (long Sipeed URL) + 1 Underfull \vbox; harmless |
| Page count | `pdfinfo main.pdf` | same | `Pages: 7`, letter |
| Visual inspection | pdftoppm → PNG of all pages | — | figures/tables readable; red TBD markers visible |
| Number traceability | manual: each number in main.tex compared with its evidence file (values printed by the figure script vs Table II; BUDGETS.md tables; RTL-CPU handoff; logs) | — | no discrepancy found in the numbers used |

## Numerical findings (all reused from evidence; none newly produced except the figures, which re-plot accuracy.json)
| Name | Value | Label | Evidence |
|---|---|---|---|
| Article page count | 7 | tool output | logs/doc/article_latex.log |
| Overfull boxes > 10 pt (and any) | 0 | tool output | same |
| Undefined references/citations | 0 / 0 | tool output | same |
| Printed placeholders | 18 distinct names (24 occurrences) | inspection | reports/article/PLACEHOLDERS.md |
| Headline: EV accuracy / SC mode 0,1,2 at K=8 (rev A seeds) | 95.0 % (342/360) / 65.6 / 91.1 / 94.4 % | SIMULATION | reports/sw/accuracy.json |
| CPU 176/176 runs, worst-seed Fmax 53.26 MHz, CPI 4.231 | — | SIMULATION | logs/cpu/sim_cpu_summary.log, logs/cpu/pnr_s2.log |
| Latency N(K) = 10·2^K + 409, N(8) = 2969 cycles = 109.96 µs | — | CALCULATION | requirements/BUDGETS.md sec. 3 |

## Assumptions
- Authors/affiliation unknown → placeholders.
- The CPU "mutation checks" requested in the task are described as what was actually done: two injected-fault negative runs of the CPU TB (signature fault, protocol fault) plus the generator's wrong-expected-value test; no RTL mutation campaign exists, and the text does not claim one.
- The tile timing diagram (Fig. 3) shows the latency-budget model (ASSUMPTION durations), not the RTL; labelled so in the caption.
- The int8-DSP throughput comparison (1.08e9 vs 1.08e7 MAC/s) is the BUDGETS.md CALCULATION; the text states no int8 design was built.

## Errors / deviations
- None in the build. Two figure-layout iterations (legend/label overlap) and three TikZ/align iterations to remove overfull boxes.
- Evidence-revision note: accuracy.json carries git_rev `d2ed476-dirty` while metrics.json lists those metrics at revision `d05477e`; the article cites the file, not the revision.

## Open decisions (for the manager)
1. **Seed-spacing metric for rev B (technical finding):** BUDGETS.md sec. 9 measures mode-2 seed separation in single LFSR steps (smallest 553 steps = "69 stream cycles", X5/W3), whereas the relevant reuse lag after the 8-step leap is d·8^-1 mod 65535 stream cycles (error_model.md: smallest 321 cycles, X0/W3). The two metrics rank pairs differently; rev B "phase-spaced seeds" should be designed and checked with the stream-cycle lag (the article uses the error-model metric).
2. REQ-AI-006 asks for >= 20 seed sets; the ensemble has 16 → placeholder `ensemble-20-seeds`; needs a software-engineer re-run (can be combined with the rev B accuracy re-run).
3. Title kept as given; author list/affiliation needed.
4. Whether Table IV should keep the pre-RTL calibration-bench rows once RTL numbers exist (recommended: keep, labelled, as a budget-vs-result comparison).

## Next actions
- software-engineer: re-run accuracy study for rev B seeds (and >= 20 seed sets); then `reports/figures/article_figures.py` regenerates both figures automatically; update Table II mode-2 columns and the rev-A-dependent numbers listed in PLACEHOLDERS.md section B.
- fpga-engineer: RTL-TPU / RTL-SOC utilisation, worst-seed Fmax, bit-exact mismatch count, fault-injection log, CYCLES at K=8, tile schedule → fill placeholders 3–16.
- documentation-engineer (DOC-02): fill placeholders with evidence comments, rebuild, re-check 0 undefined / 0 overfull, keep <= 8 pages.
