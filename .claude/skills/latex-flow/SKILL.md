---
name: latex-flow
description: Workflow for LaTeX documents in this project (IEEEtran article, engineering report) - build commands, figure conventions and number traceability.
---

# LaTeX flow

- Build: `cd <dir> && latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex`
  (TeX Live 2023, IEEEtran.cls available). Clean aux with `latexmk -c`.
- Check the log: `grep -E "Warning|Error|undefined" main.log`; zero undefined
  references or citations is mandatory.
- Figures: vector PDF from matplotlib (`savefig(..., bbox_inches="tight")`) or TikZ.
- Every number: from `management/metrics.json` or an evidence file, with a
  `% evidence: <path>` comment.
- Bibliography: BibTeX `refs.bib`, only real references you are confident exist.

## Lessons learned
- (none yet)
