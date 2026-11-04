# ST-DOC-01 — Smoke test: one-page IEEEtran paper (TikZ + matplotlib + BibTeX)
Status: PASS
Agent: documentation-engineer   Date: 2026-11-04T02:57:48Z   Input revision: none (unborn HEAD — repository has no commits; all files untracked)

## Requirements addressed
- Smoke test of the documentation toolchain (task ST-DOC-01). No project requirement IDs.

## Inputs
- Task statement from the engineering manager (citation fields for Gaines 1969 and Alaghi & Hayes 2013).
- Toolchain: TeX Live 2023/Debian (pdfTeX 3.141592653-2.6-1.40.25), Latexmk 4.83, BibTeX 0.99d,
  IEEEtran.cls/IEEEtran.bst from texlive, matplotlib 3.11.2 in /home/user/tpu-e-cpu/.venv.

## Outputs
- reports/article/smoke/main.tex — IEEEtran conference paper: title, author "Author Name", abstract,
  one section, one equation (eq:sc_mult), TikZ block diagram CPU <-> Bus <-> SC-TPU (Fig. 1),
  matplotlib figure (Fig. 2), two citations.
- reports/article/smoke/refs.bib — 2 entries (gaines1969, alaghi2013survey).
- reports/article/smoke/main.pdf — sha256 5db63127f4083c5f2d5ce52ca851f7fcb2ce672e35c7c5464cbdf6f879c5f19b
- reports/figures/smoke_plot.py — generator for y = x^2, x in [0, 10].
- reports/figures/smoke_plot.pdf — vector PDF (Matplotlib pdf backend v3.11.2),
  sha256 2558066339453f6c835905057a92580456d46cc5cebb2ec94ca9372428cb5aee
- logs/smoke/doc_latex.log — latexmk console output + final main.log + main.blg.

## Checks actually performed
- `/home/user/tpu-e-cpu/.venv/bin/python reports/figures/smoke_plot.py` -> "wrote .../smoke_plot.pdf";
  `pdfinfo` Producer "Matplotlib pdf backend v3.11.2", Pages 1.
- `cd reports/article/smoke && latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex` -> exit 0;
  latexmk ran pdflatex x3 + bibtex; log: "Latexmk: All targets (main.pdf) are up-to-date".
- `grep -nE "undefined|Error|Overfull|Underfull|Warning" main.log` (final pass) -> no matches.
  (Passes 1-2 in logs/smoke/doc_latex.log show the expected transient "Citation ... undefined"
  warnings before bibtex/rerun; the final pass has none.)
- main.blg: "warning$ -- 0".
- `pdfinfo main.pdf` -> "Pages: 1", "Page size: 612 x 792 pts (letter)";
  main.log: "Output written on main.pdf (1 page, 135415 bytes)."
- `grep -c '\bibitem' main.bbl` -> 2.
- `pdffonts main.pdf` -> all fonts Type 1, embedded.
- `pdftotext main.pdf -` -> title, author, abstract, Fig. 1, Fig. 2 and reference [2] text present.

## Numerical findings
- PDF page count · 1 · pages · tool output (pdfinfo) · logs/smoke/doc_latex.log
- Undefined references/citations (final pass) · 0 · count · tool output · logs/smoke/doc_latex.log
- LaTeX errors · 0 · count · tool output · logs/smoke/doc_latex.log
- Overfull/underfull boxes · 0 · count · tool output · logs/smoke/doc_latex.log
- Bibliography entries · 2 · count · main.bbl
- Plot data y = x^2 · CALCULATION (synthetic, not a project result) · reports/figures/smoke_plot.py
All match the manager's known answer (1 page, 0 undefined refs, 2 bib entries).

## Assumptions
- Gaines 1969 entry adds editor J. T. Tou, vol. 2, Plenum Press (the commonly cited edition);
  pages and the Alaghi & Hayes article number were deliberately omitted (not given in the task).
- Bus drawn bidirectional (CPU <-> Bus <-> TPU); task said "CPU box -> bus -> TPU box".

## Errors / deviations
- None. Aux files (main.aux/.bbl/.blg/.fls/.fdb_latexmk/.log) left in reports/article/smoke/;
  remove with `latexmk -c` if not wanted. No git commit made (as instructed).

## MCP tool visibility
- ToolSearch query "github" (max_results 3) returned: mcp__github__actions_get,
  mcp__github__actions_list, mcp__github__actions_run_trigger. Not called.
- Session notice: plugin server "plugin:engineering:github" failed to connect (proxy 403);
  the mcp__github__* tools above come from a separate, connected github server.

## Open decisions (for the manager)
- None.

## Next actions
- Reuse main.tex preamble/figure conventions for reports/article/ proper once metrics.json exists.
