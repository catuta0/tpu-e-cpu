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
