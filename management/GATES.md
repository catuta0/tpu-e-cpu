# Gate log
The user is asleep and instructed the manager not to stop (2026-11-04). Each gate
is therefore recorded here instead of waiting; decisions the user must take are
listed per gate and the manager proceeds with the stated default.

## G1 — Requirements and architecture — recorded 2026-11-04 (not waited, user asleep)
Done: 82 requirements (requirements/REQUIREMENTS.md, all NOT RUN at G1), budgets
(requirements/BUDGETS.md, CALCULATION + P&R calibration), risks, sources;
architecture rev A frozen + clarifications A.1/A.2; ADR-000..007.
Numbers: device 8640 LUT4 / 6480 FF / 26 BSRAM / 20 MULT18 (SOURCE: nextpnr/Apicula DB);
SoC LUT budget 66 % nominal, 78 % worst (CALCULATION); latency N(K)=10*2^K+409
cycles -> 110 us at K=8 (CALCULATION).
Open risks: datasheets unreachable (network); S1/S2 pin mapping ASSUMPTION; SC accuracy
depends strongly on RNG mode.
Decisions for the user (manager defaults applied):
- Allow cdn.gowinsemi.com.cn, www.gowinsemi.com, dl.sipeed.com, wiki.sipeed.com in the
  environment network policy to turn ASSUMPTION datasheet values into SOURCE (optional).
- Margins = 85 % per resource, Fmax >= 29.7 MHz (default applied).

## G2 — Smoke tests and toolchain — recorded 2026-11-04
All routes PASS except systems sources PARTIAL (see management/SMOKE_TESTS.md).

## G3 — Preliminary design with first analyses — recorded 2026-11-04
Done: RV32I core (44 tests x 4 bus configs, 176/176 PASS, re-run by manager), SC-TPU
rev A (1454 inferences bit-exact), Python golden model + QAT (EV 95.0 %), variant
studies (RNG modes 0/1/2, IL 4/8/16; L sweep K=4..10).
Cross-discipline iteration: SW accuracy + SYS correlation + FPGA cost -> rev B (mode 2,
phase-spaced seeds) -> SW found rev B defect (K=9 89.7 %, p=0.0015) -> rev C selected
on validation data -> FPGA re-ran TPU + SoC on rev C.
## G3b — Integrated design (rev C) — recorded 2026-11-04
SoC: LUT4 5628/8640 (65 %), DFF 2803 (43 %), BSRAM 5/26, worst Fmax 47.46 MHz vs 29.7
required (SIMULATION of P&R, 3 seeds); demo inference RESULT 7 correct, UART "7\n";
bitstream built, NOT programmed.
Decisions for the user (defaults applied): ADR-011 relaxes first-fetch bound to 40 cycles;
REQ-TIM-005 PARTIAL accepted for V1.
