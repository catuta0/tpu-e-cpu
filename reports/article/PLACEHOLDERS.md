# Article placeholders (DOC-01 draft)

File: `reports/article/main.tex`. Macro `\TBD{name}` prints a red bold
`[TBD:name]` (defined in the preamble). No placeholder may be filled with a
number that lacks an evidence file; when filling one, add a
`% evidence: <path>` comment next to it and remove the row below.

Input revision of the draft: git `eee3352` (HEAD later moved to `9144278`,
which changes only `management/GATES.md`).

## A. Placeholders printed in the PDF

| # | Name | Where (section / float) | What is needed | Expected evidence (owner) |
|---|---|---|---|---|
| 1 | `authors` | title block | author names | manager / user |
| 2 | `affiliation` | title block | affiliation | manager / user |
| 3 | `tpu-lut` | abstract; Table IV; conclusion | SC-TPU LUT4 count (nextpnr "LUT4" line, incl. ALU + LUT-RAM), final rev B RTL | `reports/fpga/tpu/*` + P&R log (fpga-engineer, RTL-TPU) |
| 4 | `tpu-ff` | Table IV | SC-TPU DFF count | same |
| 5 | `tpu-bsram` | Table IV | SC-TPU BSRAM blocks | same |
| 6 | `tpu-fmax` | Table IV | SC-TPU Fmax, worst of 3 seeds (stand-alone or in SoC — state which) | same |
| 7 | `soc-lut` | Table IV | integrated SoC LUT4 count (and %) | `reports/fpga/soc/*` (RTL-SOC) |
| 8 | `soc-ff` | Table IV | integrated SoC DFF | same |
| 9 | `soc-bsram` | Table IV | integrated SoC BSRAM | same |
| 10 | `soc-fmax-worst` | abstract; Table IV; conclusion | SoC post-route Fmax, worst of 3 seeds | same |
| 11 | `tpu-bitexact-mismatches` | Sec. IV-A; conclusion | RTL vs golden-model mismatch count | TPU testbench summary log (RTL-TPU) |
| 12 | `tpu-vectors-total` | Sec. IV-A | number of vectors compared (SW-01a exported 360x3 + 32 + 153 for rev A; rev B vectors will differ) | same |
| 13 | `tpu-tb-faultinj` | Sec. IV-E | TPU TB fault-injection result (`TEST FAILED`, non-zero exit) | TPU neg-check log (RTL-TPU) |
| 14 | `tpu-tile-schedule` | Sec. III-F; Fig. 3 caption | cycle-accurate RTL tile schedule (load, stream, post-proc cycles) — replace or confirm the budget ASSUMPTION O_tile = 36, P_post = 16, C_layer = 2 | RTL header of `design/rtl/tpu/sc_tpu_ctrl.v` + TB CYCLES |
| 15 | `tpu-cycles-K8` | Sec. V-C; Table III | measured CYCLES register at K = 8 (simulation); ideally also K = 4, 10 | TPU / SoC TB log |
| 16 | `soc-cpu-overhead-cycles` | Sec. V-C | CPU-side cycles per inference (input writes, START, poll, RESULT) — REQ-TIM-005 | SoC demo TB log (RTL-SOC) |
| 17 | `revB-seeds` | Sec. III-D | rev B mode-2 seed definition (and new default RNG mode) | ARCHITECTURE.md rev B / ADR (manager) |
| 18 | `acc-revB-mode2-K8` | Sec. V-A; Sec. VI | bit-exact accuracy, mode 2, K = 8, rev B seeds, with k/360 and Wilson CI | `reports/sw/accuracy.json` re-run on rev B (software-engineer) |
| 19 | `ensemble-20-seeds` | Sec. VI | seed-ensemble result with >= 20 seed sets (REQ-AI-006 asks >= 20; current study has 16) | `reports/sw/accuracy.json` re-run (software-engineer) |

(`\TBD{name}` on main.tex line 17 is inside a comment and does not print.)

## B. Numbers present in the draft that will change with rev B (not placeholders)

These are correct for rev A (evidence `reports/sw/accuracy.json`, git_rev field
`d2ed476-dirty`, spec rev A) and are labelled "rev A seeds" in the text, but
must be regenerated once rev B (mode 2 default, phase-spaced seeds) is frozen:

- Table II, mode-2 "HW" and "CI" columns (all K); Fig. 4(a) mode-2 curve.
- Fig. 5 open markers (hardware-seed RMS) for mode 2.
- Abstract / Sec. V-A / conclusion: "94.4 % (CI 91.6-96.4 %) at L = 256",
  "smallest K within 1 pp of EV: mode 2 = 8".
- Sec. V-B: smallest mode-2 LFSR lag "321 cycles (X0/W3)" and "ensemble
  agreement 0.89-1.06" for mode 2.
- Table III column "acc. m1 / m2" (mode-2 values).
- Sec. III-D: rev A default mode 1 statement and the mode-2 seed formula
  (keep as rev A history or replace by rev B).
- Table IV row "SC tile bench, m2" is a pre-RTL calibration bench and stays
  valid as such.
- If the default becomes mode 2, the "SoC budget (m1)" row should be
  re-based (+112 LUT4, +224 FF per BUDGETS.md 1.5) or kept with its label.
