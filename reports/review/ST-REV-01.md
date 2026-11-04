# ST-REV-01 - Independent review of the FPGA smoke test (ST-FPGA-01)

| Item | Value |
|---|---|
| Reviewer | independent-reviewer |
| Reviewed revision | 199a3dc. The in-scope files are byte-identical in HEAD 8431008 and in the working tree (`git diff --stat 199a3dc HEAD -- <files>` is empty; `git status --porcelain -- <files>` is empty) |
| Scope (only these inputs) | `design/rtl/common/smoke_counter.v`, `tests/smoke/tb_smoke_counter.v`, `design/constraints/tangnano9k.cst`, `scripts/smoke_fpga.sh`, `logs/smoke/fpga_*.log` |
| External reference | https://raw.githubusercontent.com/YosysHQ/apicula/master/examples/tangnano9k.cst (HTTP 200, 5497 bytes, sha256 df882541...6f00dc, apicula HEAD 993faec, which is the same HEAD the CST header cites) |
| Tools used | Icarus Verilog 12.0, Verilator 5.020 (lint only). Synthesis and P&R were **not** re-run, because the task did not ask for it |
| Evidence | `reports/review/build/ST-REV-01/` holds the re-run sim log, 11 mutant diffs and 11 mutant logs |

## Verdict

**The smoke-test claim is CONFIRMED.** The known answer of 998 is correct by hand derivation. The simulation reproduces it, and its output matches `logs/smoke/fpga_sim.log` exactly. The testbench catches 9 of 11 RTL mutants. All 11 CST pins, I/O standards and pull modes match the Apicula reference. Nothing is CRITICAL or MAJOR. There are 2 MINOR findings about testbench strength and 4 OBSERVATIONS.

## 1. Hand derivation of the known answer

RTL (`smoke_counter.v:95-121`): `sync_ff1 <= ~btn_rst_n; sync_ff2 <= sync_ff1; rst = sync_ff2;` and the counter has a synchronous reset on `rst`. The button is held pressed beforehand, so `ff1 = ff2 = 1`. The release happens at a negedge, half a period before rising edge 1.

| Rising edge after release | ff1 after | ff2 after | rst the counter sampled (old ff2) | count after |
|---|---|---|---|---|
| 1 | 0 | 1 | 1 | 0 |
| 2 | 0 | 0 | 1 | 0 |
| 3 | 0 | 0 | 0 | 1 |
| k (k >= 2) | | | | k - 2 |

Result: **N = 1000 gives count = 998 = 24'h0003E6** (CALCULATION). Bits 23..18 are 0, so led_n = 6'b111111. The TB expectation is `EXP_KNOWN = N_KNOWN[23:0] - SYNC_LAT[23:0] = 1000 - 2 = 998` (`tb_smoke_counter.v:63`). It is checked after `tick(1)` x3 plus `tick(N_KNOWN-3)`, which is 1000 rising edges in total (`:161-169`). **The two agree.**

Other TB constants I re-derived, all correct:
- TC2: `(1<<18)+2-1-1000 = 261145` further edges, so 262145 edges in total and count = 2^18 - 1 = 0x03FFFF. One more edge gives 0x040000, so led_n = 6'b111110.
- TC3 (press): edge 1 gives c+1 (counter sees old ff2 = 0), edge 2 gives c+2 (counter sees old ff2 = 0, while ff2 becomes 1), edge 3 gives 0.
- TC4 (4-bit): 17 edges give 15, 18 give 0 (wrap), 19 give 1.
- Simulated end time: 9 700 438 000 ps / 37 000 ps = 262 174 edges (CALCULATION). The TB has 5 + 3 + 997 + 261145 + 1 + 4 + 17 + 1 + 1 = 262 174 ticks, so the two match.

## 2. Simulation re-run and mutation test

Re-run command: `iverilog -g2005 -Wall -o <scratch>/tb.vvp design/rtl/common/smoke_counter.v tests/smoke/tb_smoke_counter.v && vvp -n <scratch>/tb.vvp`
Result: 21 checks, 0 errors, `TEST PASSED`, exit status 0. Except for the command line and the exit-code line, the output is identical to `logs/smoke/fpga_sim.log` (checked with `diff`). Verilator `--lint-only -Wall` on both the RTL and RTL+TB exits 0 with no warnings.

Mutants were made from scratch-dir copies of the RTL; the design file was not touched. The TB is unchanged.

| Mutant | Change | TB result | First failing check |
|---|---|---|---|
| M1 | increment by 2 | **FAIL** (exit 1, 11 FAILs) | TC1 edge 3: got 2, exp 1 |
| M2 | 1-FF synchroniser (`rst = sync_ff1`) | **FAIL** (13) | TC1 edge 2: got 1, exp 0 |
| M3 | 3-FF synchroniser | **FAIL** (13) | TC1 edge 3: got 0, exp 1 |
| M4 | LEDs not inverted | **FAIL** (6) | TC0 LEDs: got 0x00, exp 0x3f |
| M5 | LED bit order reversed | **FAIL** (1) | TC2 LEDs at 0x040000 |
| M6 | swap led_n[5] and led_n[4] | **PASS (survived)** | none, see R-001 |
| M7 | LEDs shifted down by one bit | **FAIL** (1) | TC2 LEDs at 0x040000 |
| M8 | asynchronous counter reset | **FAIL** (1) | TC3 edge 2: got 0, exp 0x040002 |
| M9 | synchroniser INIT 2'b00 instead of 2'b11 | **PASS (survived)** | none, see R-002 |
| M10 | button not inverted | **FAIL** (16) | TC0: got 3, exp 0 |
| M11 | saturate instead of wrap | **FAIL** (3) | TC4 wrap: got 15, exp 0 |

The script's own negative check (`-DINJECT_FAULT`, `logs/smoke/fpga_sim_inject_fault.log`) only changes the *expected* value. M1 to M11 change the *design*, which is stronger evidence that the TB checks behaviour.

## 3. Pins and LED polarity

| CST port (project) | Pin | IO_TYPE / PULL | Apicula reference line | Match |
|---|---|---|---|---|
| clk | 52 | LVCMOS33 / UP | `clk` 52 LVCMOS33 UP | yes |
| btn_rst_n | 3 | LVCMOS18 / UP | `key_i` 3 LVCMOS18 UP | yes (pin); see R-005 for the name |
| btn_s2_n | 4 | LVCMOS18 / UP | `rst_i` 4 LVCMOS18 UP | yes (pin) |
| led_n[0..5] | 10, 11, 13, 14, 15, 16 | LVCMOS18 / NONE | `led[0..5]` 10, 11, 13, 14, 15, 16 LVCMOS18 NONE | yes |
| uart_tx | 17 | LVCMOS33 / UP | `TXD` 17 LVCMOS33 UP | yes |
| uart_rx | 18 | LVCMOS33 / UP | `RXD` 18 LVCMOS33 UP | yes |

The placed pins in `logs/smoke/fpga_pins.log` (smoke_counter, 8 IOs) and in `logs/smoke/fpga_cst_check_pnr.log:139-149` (all 11 ports) match the table. The synthesis stat (`fpga_synth.log`) shows 24 DFFR + 2 DFFS + 24 ALU + 8 LUT1, which fits 24 counter bits, 2 synchroniser flops, and 6 LED inverters plus 2 more. P&R reports post-route Fmax 245.52 MHz, PASS at 27 MHz (`fpga_summary.log:5`).

LED polarity in the RTL is `assign led_n = ~count[WIDTH-1 -: NUM_LEDS]` (`smoke_counter.v:130`). Pin 0 means LED on, so in reset (count 0) all LEDs are off. The TB checks inversion in TC0, TC2 and TC4, and mutant M4 is caught. The RTL is consistent with the stated active-low board wiring. That wiring itself could not be verified from the permitted sources (R-006).

## Findings

| ID | Severity | Location | Finding | Evidence | Recommendation | Disposition |
|---|---|---|---|---|---|---|
| R-001 | MINOR | tests/smoke/tb_smoke_counter.v:170-184 | The LED-to-count bit mapping is only partly checked. Only led_n[0] at count bit 18 is discriminated. Any permutation of led_n[5:1] passes. At 1000 edges the LED check gives all-ones, the same as the reset state, so it would also pass with a stuck counter. | Mutant M6 (led_n[5] and led_n[4] swapped) gives TEST PASSED, exit 0 (`reports/review/build/ST-REV-01/mut_M6_led_swap45.log`). | Add a continuous check `led_n === ~count[WIDTH-1 -: NUM_LEDS]` on every negedge, or add a small WIDTH=6/NUM_LEDS=6 instance where each LED bit is seen to toggle on its own. | |
| R-002 | MINOR | tests/smoke/tb_smoke_counter.v:70-71, 150; smoke_counter.v:95-96 | The power-up INIT of the synchroniser (2'b11, the documented "held in reset after configuration" behaviour) is not tested. The TB starts with the button pressed, so the synchroniser fills with 1s whatever its INIT is. | Mutant M9 (INIT 2'b00) gives TEST PASSED, exit 0 (`mut_M9_syncinit0.log`). | Add a case with the button released from t=0. With INIT 11 the count must be N-2 after N edges; INIT 00 would give N. The hardware impact is only 2 cycles, hence MINOR. | |
| R-003 | OBSERVATION | logs/smoke/fpga_versions.log:1, fpga_summary.log:1 | The committed logs are stamped `input revision: be4b802-dirty`, not 199a3dc. In-scope RTL, TB and CST changed between be4b802 and 199a3dc, so the logs cannot be traced to a clean revision. | `git diff --stat be4b802 199a3dc` shows changes to all 4 source files. My re-run at 199a3dc reproduces fpga_sim.log exactly. Synthesis, P&R and pack logs were not reproduced by me. | Re-run `scripts/smoke_fpga.sh` on a clean checkout of the released revision so that every log carries a non-dirty stamp. | |
| R-004 | OBSERVATION | scripts/smoke_fpga.sh:78, 81, 95 | Under `set -e`, the `LINT_*_EXIT=$?` and `SIM_EXIT=$?` lines can only ever print 0, because a non-zero status aborts first. So they are not independent evidence. Pass and fail is in fact decided by `TEST PASSED` / `FAIL` greps and pipefail, which work correctly. | Script logic. The negative path (`set +e`, :103-113) correctly records `SIM_FAULT_EXIT=1`. | Optional: capture the exit code explicitly (`cmd; rc=$?` under `set +e`) so the logged value means something. | |
| R-005 | OBSERVATION | design/constraints/tangnano9k.cst:33-39, 65-68 | The S1/S2 to pin 3/4 mapping is a labelled ASSUMPTION. Apicula names pin 3 `key_i` and pin 4 `rst_i`. The CST header itself reports that Sipeed examples disagree (led example `sys_rst_n` = 4, uart example `rst_n` = 3). Choosing pin 3 also avoids JTAGSEL_N on pin 4. There is no electrical risk because both inputs are LVCMOS18 with pull-up and active-low. | Apicula CST lines 17-20; `fpga_cst_check_pnr.log:140` (pin 4 is dual-purpose JTAGSEL_N). | Confirm against the official schematic before any hardware bring-up. Until then, keep the ASSUMPTION label. | |
| R-006 | OBSERVATION | smoke_counter.v:25-30, 130 | The RTL inverts the LEDs correctly for active-low wiring, and the TB checks this. The active-low claim itself (anode on VCCO3 1.8 V) rests on a Sipeed wiki excerpt that is not among the permitted sources. The Apicula CST gives IO_TYPE only, not polarity. | Mutant M4 is caught. The polarity source was not checked independently. | Cross-check the polarity with the board schematic at hardware bring-up. If it is wrong, the only effect is an inverted display. | |

## 4. MCP tool visibility

`ToolSearch("github", max_results=3)` returned three MCP tools, which I did not call: `mcp__github__actions_get`, `mcp__github__actions_list`, `mcp__github__actions_run_trigger`. The session's deferred-tool list also contains many other `mcp__github__*` tools (for example get_file_contents and create_pull_request). Separately, the session reported that the plugin server `plugin:engineering:github` failed to connect (proxy 403). I used neither of them.
