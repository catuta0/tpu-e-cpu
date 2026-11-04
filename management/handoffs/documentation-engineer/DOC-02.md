# DOC-02 — Article rev C, engineering report, user manual
Status: PARTIAL. All three deliverables are complete and build cleanly. Two hooks stay open by design: the status matrix is pending G4, and the review findings are pending REV-01. Nothing was committed by me.
Agent: documentation-engineer   Date: 2026-11-04   Input revision: fab802e (assigned HEAD of claude/awesome-lovelace-hu02o8)

HEAD moved during the task: 99ee941, 7e978be, then 54ad7b4.
- 99ee941 touches only management/EXECUTION_METRICS.md and scripts/make_release.sh.
- 7e978be and 54ad7b4 are manager WIP commits. They contain my DOC-02 outputs and the reviewer's build tree.
- `git diff --stat fab802e HEAD` (reviewer build tree excluded) shows no change to any evidence file.
- Work was interrupted once by a usage-limit stop and resumed. Files written before the stop were intact.

## Requirements addressed
- REQ-DOC-005 (article): architecture, SC method, accuracy vs K and RNG mode, resources, timing, latency, limitations, references. The headline REQ-AI/RES/TIM numbers are present with labels. Wilson CIs and k/n are given for every accuracy table (REQ-AI-007).
- REQ-DOC-006 (engineering report): requirements and status-matrix hook, budgets vs results, risks, verification evidence, physical validation plan.
- REQ-VER-009: the plan is present, with 14 items PV-01..PV-14. Each item has a pass criterion and requirement IDs. Every item is NOT RUN.
- REQ-SYS-017: the power estimate is stated as an ASSUMPTION only.
- REQ-DOC-003 and REQ-DOC-004: everything is in English, every number is labelled, and no MEASUREMENT is claimed.

## Inputs
- Spec and decisions:
  - design/architecture/ARCHITECTURE.md, sections 1-12 (rev C)
  - management/INTERFACES.json, revision C
  - management/DECISIONS.md, ADR-000..012 plus the addendum
- Metrics: management/metrics.json
- Software evidence (reports/sw/):
  - accuracy_revC.json
  - revABC_comparison.md and revABC_comparison.json
  - seed_selection_revC.md
  - error_model.md
- FPGA evidence:
  - reports/fpga/soc/soc_impl.md, critical_path_nwl.txt
  - reports/fpga/tpu/variants.md
  - reports/fpga/cpu/cpu_synth_pnr.txt
- Requirements and risks: requirements/REQUIREMENTS.md (issue 2), requirements/BUDGETS.md (issue 2), management/RISKS.md (issue 2)
- Logs:
  - logs/tpu/ (sim_tpu_console, tb_*, *_inject_fault)
  - logs/soc/ (tb_soc_demo, sim_soc_console, synth_soc_console, pack, pins)
  - logs/cpu/sim_cpu_summary.log
  - logs/sw/ (gen_hex, pytest_revC, accuracy_revC, seed_selection_revC, compare_abc)
- Handoffs:
  - fpga-engineer: RTL-CPU, RTL-TPU, RTL-SOC
  - software-engineer: SW-01a, SW-01b, SW-02, SW-03
  - systems-engineer: REQ-01, REQ-02
  - documentation-engineer: DOC-01
- Code and data read for facts: design/rtl/tpu/sc_tpu_ctrl.v (header), tests/*/tb_*.v (INJECT_FAULT blocks), sim/data/soc_demo_prog.lst and .meta.json, design/constraints/tangnano9k.cst (header), management/SOURCES.md S-022, scripts/*.sh (headers).

## Outputs
| Path | Content |
|---|---|
| reports/article/main.tex, main.pdf | Rev C article: 8 pages, IEEEtran conference, 72 `% evidence:` comments. All 19 DOC-01 placeholders are filled. A new subsection V-C covers the seed iteration A -> B -> C with a new Fig. 6. Table IV has new RTL/SoC rows. Table III shows budget vs RTL. The tile-schedule figure is redrawn to the RTL. The `REVIEW-FINDINGS-HOOK` comment and an "Independent review" paragraph are in place. Author: "Author Name", "Affiliation (placeholder)". |
| reports/article/refs.bib | 18 entries. Added: Wilson 1927 (JASA 22(158):209-212), McNemar 1947 (Psychometrika 12(2):153-157), Newcombe 1998 (Stat. Med. 17(22):2635-2650). |
| reports/article/PLACEHOLDERS.md | Placeholder closure table (all closed) plus the list of rev A numbers that were replaced. |
| reports/engineering/main.tex, main.pdf | Engineering report: 16 pages, A4, article class, 67 `% evidence:` comments. It has sections 1-12 as requested, including the physical validation plan (sec. 11) and the review-findings hook (sec. 8). |
| reports/engineering/status_matrix.tex | Stub that prints "Requirement status matrix: pending G4." |
| reports/engineering/MANUAL.md | User manual: what the system is, repository map, 16 reproduction commands with their expected decisive lines, register quick reference, a self-programming section (openFPGALoader, command form only, explicitly NOT done in the project), troubleshooting. Written here because docs/ is outside my write paths. |
| reports/figures/article_figures.py | Now reads accuracy_revC.json (20 offsets). Adds `fig_rev_bc()`, which reads revABC_comparison.json. |
| reports/figures/article_acc_vs_k.pdf, article_rms_vs_k.pdf, article_revBC.pdf | Vector figures (rev C; rev B vs rev C). |
| logs/doc/article_figures_revC.log, article_latex_revC.log, report_latex.log | Figure values printed; build checks; sha256 of the outputs. |

## Checks actually performed
| Check | Command / tool | Log | Result (quoted) |
|---|---|---|---|
| Figures | `.venv/bin/python reports/figures/article_figures.py` (matplotlib 3.11.2) | logs/doc/article_figures_revC.log | `FIG_EXIT=0`. Printed values match Table II (e.g. `2  8  94.4 340  91.6  96.4  92.8  1.4 20`). PNG renders were inspected and the label overlaps fixed in 2 iterations. |
| Article build (clean) | `latexmk -C; latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex` (Latexmk 4.83, TeX Live 2023) | logs/doc/article_latex_revC.log | `LATEXMK_EXIT=0`; `Output written on main.pdf (8 pages, 420211 bytes)`; grep undefined/Overfull/Error/Warning: `none`; BibTeX warnings 0; 18 bibitems; `TBD markers printed: 0` |
| Report build (clean) | same, in reports/engineering | logs/doc/report_latex.log | `LATEXMK_EXIT=0`; `Output written on main.pdf (16 pages, 604532 bytes)`; grep undefined/Overfull/Error/Warning: `none` |
| Overfull boxes > 10 pt | main.log of both documents | same logs | Article 0. Report 0: 30+ table overflows were fixed with ragged columns and breakable paths. |
| Visual inspection | pdftoppm montage of all pages | — | Article: 8 full pages, figures and tables readable. Report: 16 pages, tables fit. |
| Number traceability | Each new number compared by hand with its evidence file while writing | — | No discrepancy left. One wording overstatement was corrected ("doubles the latency" became 1.9x = 5498/2928). The fault-injection description was corrected after reading the TB `INJECT_FAULT` blocks: the unit TBs use wrong reference models, not flipped expectations. |

## Numerical findings (all reused from evidence; nothing new except calculations noted)
| Name | Value | Label | Evidence |
|---|---|---|---|
| Mode-2 K8 accuracy, rev C deployed seeds | 94.4 % (340/360), CI 91.6-96.4 | SIMULATION | reports/sw/accuracy_revC.json |
| Ensemble mode 0/1/2 at K8 (20 offsets) | 90.7±4.4 / 92.8±1.3 / 92.8±1.4 % | SIMULATION | same |
| Error-model ensemble ratio, all 42 combinations | 0.77-1.05 (mode 2: 0.90-1.05) | SIMULATION | accuracy_revC.json error_study |
| Rev B vs C at K9 | 89.7 vs 94.4 %, discordant 5/22, McNemar p = 0.0015 | SIMULATION | revABC_comparison.md |
| SoC LUT4 / DFF / BSRAM; worst Fmax | 5628 (65 %) / 2803 / 5; 47.46 MHz | SIMULATION | soc_impl.md |
| TPU CYCLES | 10·2^K + 368; 2928 at K8 | CALCULATION + SIMULATION | sc_tpu_ctrl.v; tb_sc_tpu_mode2.log |
| Margins: default-flow SoC vs 29.7 MHz; TPU alone vs 29.7 MHz | +44.1 %; +103 % | CALCULATION | 42.80/29.7-1; 60.43/29.7-1 |
| UART bit time / frame / ±2 % window | 8.667 µs / 86.67 µs / 8.51-8.86 µs | CALCULATION | 234/27e6; 2340/27e6 |
| Article / report pages | 8 / 16 | tool output | logs/doc/*.log |

## Assumptions
- The TPU stand-alone numbers in the article (Table IV) and in the report come from the rev A RTL variant study. The mode-2 seeds are identical to rev C; only the PARAMS version constant and the modes 0/1 W seed differ. This is stated in a table footnote.
- The report's "evidence overview" table lists specialist-reported results and is explicitly *not* a status. The formal status is left to the G4 matrix.
- Validation-plan pass bounds that have no requirement behind them are labelled ASSUMPTION or "informative". Examples: PV-01 supply current has no bound; PV-14 thermal is informative.
- PV-09 (CYCLES over the UART) and PV-10 (≥ 20 images) need a future test program, not firmware: the demo stores CYCLES at 0x0E00 but never transmits it. PV-11 (full test-set accuracy) needs a UART RX path in the RTL plus a host script. PV-13 (PLL sweep) needs a separate build. All of these are marked as future work.
- The openFPGALoader board name `tangnano9k` and the `-f` flash option are given as command forms only. openFPGALoader is not in the project tool set and has not been run.

## Errors / deviations
- docs/MANUAL.md was not possible because docs/ is outside my write paths. The manual is at reports/engineering/MANUAL.md, which the task allowed as an alternative.
- The article grew from 7 to 8 pages, the upper limit. Adding anything more requires cutting text elsewhere.
- I corrected a factual statement from DOC-01. The old article said the LFSR "wraps within one inference at K = 10 (1.25 periods)". Following BUDGETS.md 9.1 (issue 2), it now says no state repeats, but the bit sequence wraps after 8192 stream cycles.
- I corrected the K=8 claims. Rev A-only claims ("65.6 % with shared numbers", "decorrelation matters more than stream length") were replaced by rev C data: modes 1 and 2 have equal ensemble means at K=8, and the deployed-seed spread is largely realisation noise.

## Open decisions (for the manager)
1. Author names and affiliation are still placeholders, pending the user.
2. Review findings: replace the article paragraph and report sec. 8 at `REVIEW-FINDINGS-HOOK` once REV-01 reports (REVIEW_A_cpu_soc.md, REVIEW_B_tpu_model_article.md) arrive.
3. status_matrix.tex: render requirements/STATUS_MATRIX.md into it after G4. This belongs to the systems-engineer or to me in a follow-up.
4. Should the manual move to docs/ (manager-owned path)? It is currently at reports/engineering/MANUAL.md.

## Next actions
- documentation-engineer (follow-up from the manager): integrate the REV-01 findings, insert the status matrix, rebuild both PDFs, re-check 0 undefined and 0 overfull > 10 pt, and keep the article at 8 pages or fewer.
- manager: commit the DOC-02 outputs (MANUAL.md is still untracked), then run REL-V1.
