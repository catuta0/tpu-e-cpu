# Article placeholders — status after DOC-02 (rev C)

File: `reports/article/main.tex`. Input revision of DOC-02: git `fab802e`
(HEAD moved to `99ee941` during the task; that commit changes only
`management/EXECUTION_METRICS.md` and `scripts/make_release.sh`).

All 19 DOC-01 placeholders are closed. `\TBD{}` is still defined in the
preamble but no longer used; `pdftotext main.pdf | grep -c TBD` = 0
(logs/doc/article_latex_revC.log).

| # | Name (DOC-01) | Filled with (rev C) | Evidence |
|---|---|---|---|
| 1 | `authors` | "Author Name" (plain placeholder, user has not given names) | manager instruction DOC-02 |
| 2 | `affiliation` | "Affiliation (placeholder)" | same |
| 3 | `tpu-lut` | 4572 LUT4 (IL8, mode 2, -nowidelut, stand-alone wrapper) | reports/fpga/tpu/variants.md |
| 4 | `tpu-ff` | 2669 | same |
| 5 | `tpu-bsram` | 1 | same |
| 6 | `tpu-fmax` | 60.43 MHz worst of 3 seeds, stand-alone | same |
| 7 | `soc-lut` | 5628 (65 %) | reports/fpga/soc/soc_impl.md |
| 8 | `soc-ff` | 2803 (43 %) | same |
| 9 | `soc-bsram` | 5 | same |
| 10 | `soc-fmax-worst` | 47.46 MHz (seeds 51.98 / 47.46 / 51.21) | same |
| 11 | `tpu-bitexact-mismatches` | 0 mismatching fields | logs/tpu/sim_tpu_console.log (rev C) |
| 12 | `tpu-vectors-total` | 1454 inferences + 239 clamp re-runs (3 modes) | same; RTL-SOC handoff |
| 13 | `tpu-tb-faultinj` | all negative runs TEST FAILED (10 over TPU/CPU/SoC) | logs/tpu/*_inject_fault.log, logs/cpu/sim_cpu_summary.log, logs/soc/sim_soc_console.log |
| 14 | `tpu-tile-schedule` | LOAD 33, STREAM 2^K, POST 19 per layer; Fig. 3 redrawn | design/rtl/tpu/sc_tpu_ctrl.v header |
| 15 | `tpu-cycles-K8` | 2928 (= 10*2^K + 368) | logs/tpu/tb_sc_tpu_mode2.log D8; logs/soc/tb_soc_demo.log D6 |
| 16 | `soc-cpu-overhead-cycles` | START->RESULT read 2948 (CYCLES + 20); reset->TOHOST 5441; input-write time not simulated (REQ-TIM-005 PARTIAL) | logs/soc/tb_soc_demo.log; ADR-011 |
| 17 | `revB-seeds` | replaced by rev C seeds + new Sec. V-C (A -> B -> C) | ARCHITECTURE.md 11, 12; ADR-008..010 |
| 18 | `acc-revB-mode2-K8` | rev C mode 2 K8 94.4 % (340/360, CI 91.6-96.4); rev B K8 93.9 %, K9 89.7 % | reports/sw/accuracy_revC.json, revABC_comparison.md |
| 19 | `ensemble-20-seeds` | 20 offsets: mode 2 K8 92.8 +/- 1.4 % | reports/sw/accuracy_revC.json |

## Rev-A numbers replaced (section B of the DOC-01 list)
- Table II, Fig. 4, Fig. 5: now rev C (`accuracy_revC.json`, 20 offsets);
  modes 0/1 changed (W seed 0x7A5C -> 0xF9DE), mode 2 unchanged by construction.
- Error-model agreement: 0.82-1.13 (+0.74 exception, rev A, 16 offsets) ->
  0.77-1.05 over all 42 combinations (rev C, 20 offsets).
- Latency: budget N(K) = 10*2^K + 409 kept only as the budget column;
  RTL CYCLES = 10*2^K + 368.
- K = 10 "wrap" statement corrected (bit-sequence wrap after 8192 stream
  cycles, not a state wrap), per requirements/BUDGETS.md 9.1 issue 2.

## Open hook
- `REVIEW-FINDINGS-HOOK` (Discussion, "Independent review" paragraph): to be
  filled when the manager forwards REV-01 findings
  (reports/review/REVIEW_A_cpu_soc.md, REVIEW_B_tpu_model_article.md).
