# ST-FPGA-01 — FPGA toolchain smoke test (known answer), Tang Nano 9K
Status: PASS
Agent: fpga-engineer   Date: 2026-11-04T03:06Z   Input revision: be4b802-dirty
(The task was issued against the uncommitted workspace; the manager committed be4b802 while
this task was running. All files below are new and uncommitted; the manager commits.)

Scope note: PASS means lint + simulation + synthesis + P&R + bitstream generation succeeded and
the logs were read. It is NOT hardware validation. Nothing was flashed.

## Requirements addressed
- ST-FPGA-01 items 1–6 (smoke test only; no product requirement IDs).
- Conforms to management/INTERFACES.json rev A `top_ports` (`clk`, `btn_rst_n`, `led_n[5:0]`,
  `uart_tx`, `uart_rx`) and `reset` (S1 active-low, 2-FF synchroniser, internal sync active-high
  `rst`). INTERFACES.json appeared mid-task; I first used `btn_s1_n`, then renamed to the frozen
  name `btn_rst_n` everywhere and re-ran the full flow. No interface was changed.

## Inputs
- Task brief ST-FPGA-01; .claude/agents/fpga-engineer.md; skills engineering-evidence,
  rtl-gowin-flow, engineering-reporting; management/INTERFACES.json rev A.
- Pin sources (fetched 2026-11-04, see "Numerical findings" / "Sources"):
  - [A] https://raw.githubusercontent.com/YosysHQ/apicula/master/examples/tangnano9k.cst
    (apicula HEAD 993faec69ebca98838185298a834c46c670a11f1 via `git ls-remote`). Lines used:
    `IO_LOC "clk" 52; IO_PORT "clk" IO_TYPE=LVCMOS33 PULL_MODE=UP;`
    `IO_LOC "led[0]" 10;` … `"led[5]" 16;` (10,11,13,14,15,16) each `IO_TYPE=LVCMOS18 PULL_MODE=NONE;`
    `IO_LOC "key_i" 3; IO_PORT "key_i" IO_TYPE=LVCMOS18 PULL_MODE=UP;`
    `IO_LOC "rst_i" 4; IO_PORT "rst_i" IO_TYPE=LVCMOS18 PULL_MODE=UP;`
    `// Use buildin USB-serial` / `IO_LOC "TXD" 17; IO_PORT "TXD" IO_TYPE=LVCMOS33 PULL_MODE=UP;`
    `IO_LOC "RXD" 18; IO_PORT "RXD" IO_TYPE=LVCMOS33 PULL_MODE=UP;`
  - [B] https://github.com/sipeed/TangNano-9K-example (HEAD c3b795799f23de91982be52db4273a8eea100cdb),
    cross-check: `led/src/9K_LED_project.cst` (led[0..5]=10,11,13,14,15,16; sys_rst_n=4; sys_clk=52),
    `uart/src/top.cst` lines 9–15 (`uart_tx` 17, `uart_rx` 18 LVCMOS33 PULL_MODE=UP; `rst_n` 3; `clk` 52),
    `uart/src/uart_top.v` (uart_tx output, uart_rx input).
  - [C] Sipeed wiki https://raw.githubusercontent.com/sipeed/sipeed_wiki/main/docs/hardware/en/tang/Tang-Nano-9K/examples/led.md
    → image `.../zh/tang/Tang-Nano-9K/nano_9k/LED_Pins.png`: LED anodes on VCCO3_1V8, cathodes
    on PIN10_IOL15A … PIN16_IOL26B → LEDs active-low.
  - [D] Apicula 0.32 chip database (installed), GW1NR-9C / QFN88P pinout: pin 3=IOT2A,
    4=IOL5A (JTAGSEL_N, LPLL_T_IN), 10=IOL15A (GCLKT_6), 11=IOL16B, 13=IOL21B, 14=IOL22B,
    15=IOL25B, 16=IOL26B, 17=IOB2A, 18=IOB2B, 52=IOR17A (GCLKT_3). IO names agree with [C].
  - Not reachable: wiki.sipeed.com, dl.sipeed.com (proxy 403), GitHub REST API (403).

## Outputs
- design/rtl/common/smoke_counter.v — 24-bit counter, top 6 bits → active-low LEDs, S1 via 2-FF
  synchroniser → synchronous reset. Params WIDTH, NUM_LEDS. Fully commented header with cycle-exact latency.
- tests/smoke/tb_smoke_counter.v — self-checking TB, 21 checks, 24-bit and 4-bit instances,
  watchdog, `$fatal(1)` on failure, `-DINJECT_FAULT` negative mode.
- tests/smoke/cst_all_ports_top.v — throw-away top using every CST port (shared-CST check).
- design/constraints/tangnano9k.cst — clk, btn_rst_n (S1), btn_s2_n (spare), led_n[0..5], uart_tx, uart_rx;
  header cites sources/lines.
- scripts/smoke_fpga.sh — whole route; exits non-zero unless every decisive log line is found.
- scripts/pnr_pin_report.py — reusable: placed bel → IO name → package pin (Apicula chipdb).
- Logs: logs/smoke/fpga_{versions,lint,sim,sim_inject_fault,synth,pnr,pins,pack,cst_check_lint,
  cst_check_synth,cst_check_pnr,summary,smoke_console}.log, logs/smoke/fpga_pnr_report.json.
- Build products (gitignored by `sim/**/build/`, verified with `git check-ignore`):
  sim/smoke/build/smoke_counter.{json,_pnr.json,_report.json,fs}, cst_all_ports_top.*, *.vvp.
- .claude/skills/rtl-gowin-flow/SKILL.md — "Lessons learned" filled in (lock taken and released).
- sha256: smoke_counter.v 0df81296…, tb_smoke_counter.v e2d9be7c…, tangnano9k.cst 4c6222df…,
  smoke_fpga.sh 2efa611e…, pnr_pin_report.py 4459363e…, cst_all_ports_top.v 8f7828b2….

## Checks actually performed
All via `bash scripts/smoke_fpga.sh` (final run 2026-11-04T03:05:52Z, `SCRIPT_EXIT=0`,
console in logs/smoke/fpga_smoke_console.log). Tools: Verilator 5.020, Icarus 12.0,
Yosys 0.70 (YoWASP), nextpnr-0.11.1 himbaechel-gowin (YoWASP), Apicula 0.32.
| # | Command | Log | Result (quoted) |
|---|---|---|---|
| 1 | `verilator --lint-only -Wall design/rtl/common/smoke_counter.v --top-module smoke_counter` | fpga_lint.log | `LINT_RTL_EXIT=0`, no %Warning |
| 1 | `verilator --lint-only -Wall --timing <rtl> <tb> --top-module tb_smoke_counter` | fpga_lint.log | `LINT_TB_EXIT=0`, no %Warning |
| 2 | `iverilog -g2005 -Wall -o sim/smoke/build/tb_smoke_counter.vvp <rtl> <tb>; vvp -n …` | fpga_sim.log | `PASS: TC1 KNOWN ANSWER: count after 1000 edges : got 0x0003e6 (998), expected 0x0003e6 (998)`; `tb_smoke_counter: 21 checks, 0 errors`; `TEST PASSED` |
| 2b | same with `-DINJECT_FAULT` (expects 999) | fpga_sim_inject_fault.log | `FAIL: TC1 KNOWN ANSWER … got 0x0003e6 (998), expected 0x0003e7 (999)`, `TEST FAILED`, `SIM_FAULT_EXIT=1` → checker and exit code proven |
| 3 | `yowasp-yosys -l logs/smoke/fpga_synth.log -p "read_verilog …; synth_gowin -top smoke_counter -json …; stat"` | fpga_synth.log | `End of script`; cells: 24 ALU, 24 DFFR, 2 DFFS, 8 LUT1, 2 IBUF, 6 OBUF; no "Warnings:" summary (only Yosys-internal abc9_map.v lexer warning) |
| 4 | `yowasp-nextpnr-himbaechel-gowin --json … --device GW1NR-LV9QN88PC6/I5 --vopt family=GW1N-9C --vopt cst=design/constraints/tangnano9k.cst --freq 27 --report … --seed 1 --threads 1` (no --timing-allow-fail) | fpga_pnr.log | `Info: Max frequency for clock 'clk_IBUF_I_O': 245.52 MHz (PASS at 27.00 MHz)` (post-route); `Program finished normally.`; no Warning/ERROR lines |
| 4b | `python scripts/pnr_pin_report.py sim/smoke/build/smoke_counter_pnr.json GW1N-9C QFN88P` | fpga_pins.log | clk→pin 52, btn_rst_n→pin 3, led_n[0..5]→pins 10,11,13,14,15,16, IO_TYPE/PULL_MODE as in CST |
| 5 | `gowin_pack -d GW1N-9C -o sim/smoke/build/smoke_counter.fs sim/smoke/build/smoke_counter_pnr.json` | fpga_pack.log | `PACK_EXIT=0`, `size_bytes=2069320`, sha256 3c7d62eab9464094898d2a475b9c7c7f505eac6856b50c00d566869e218e5e71 |
| 6 | shared-CST check: lint + synth + P&R + pin report + pack of cst_all_ports_top | fpga_cst_check_*.log | 11 IOBs placed: uart_tx→17, uart_rx→18 (LVCMOS33), btn_s2_n→4, plus the 8 above; `PACK_CST_TOP_EXIT=0`; "No Fmax available" (no internal FF→FF paths, expected) |
| — | nextpnr behaviour for CST entries without a port | fpga_pnr.log | `Info: Cell btn_s2_n not found`, `Info: Cell uart_tx not found`, `Info: Cell uart_rx not found` — Info only, no error |
| — | `git check-ignore -v sim/smoke/build/smoke_counter.fs` | console | `.gitignore:4:sim/**/build/` |

## Numerical findings
| Name | Value | Unit | Label | Evidence |
|---|---|---|---|---|
| Synchroniser latency (release → first increment sees rst=0) | 2 | clock edges | CALCULATION (2 FFs, counter samples old sync_ff2) + SIMULATION (TC1 edges 1,2 → 0; edge 3 → 1) | fpga_sim.log |
| Known answer: count after N=1000 edges post-release | 998 = N−2 (0x0003E6) | — | CALCULATION; SIMULATION matched | fpga_sim.log |
| LED mapping: count 0x040000 at 2^18+2 edges → led_n | 6'b111110 | — | CALCULATION; SIMULATION matched | fpga_sim.log TC2 |
| 4-bit wrap 15→0 | at 17→18 edges post-release | edges | CALCULATION; SIMULATION matched | fpga_sim.log TC4 |
| Reset assertion latency | counter cleared on 3rd edge after press | edges | SIMULATION | fpga_sim.log TC3 |
| LUT4 | 34 / 8640 (0 %) | cells | SIMULATION (P&R tool report, nextpnr-0.11.1) | fpga_pnr.log |
| DFF | 26 / 6480 (0 %) | cells | SIMULATION (P&R tool report) | fpga_pnr.log |
| ALU | 26 / 6480 | cells | SIMULATION (P&R tool report) | fpga_pnr.log |
| IOB | 8 / 276 (2 %) | cells | SIMULATION (P&R tool report) | fpga_pnr.log |
| BSRAM / DSP (MULT*) / rPLL | 0 / 26, 0, 0 / 2 | cells | SIMULATION (P&R tool report) | fpga_pnr.log |
| Fmax clk (post-route, seed 1) | 245.52 | MHz | SIMULATION (nextpnr static timing analysis) | fpga_pnr.log |
| Fmax clk (post-placement estimate) | 211.95 | MHz | SIMULATION (nextpnr estimate) | fpga_pnr.log |
| Critical path (24-bit carry chain) | 4.07 (3.66 logic + 0.41 routing) | ns | SIMULATION (nextpnr STA) | fpga_pnr.log |
| Slack at 27 MHz | 37.04 − 4.07 = 32.97 | ns | CALCULATION (period 1/27 MHz = 37.037 ns) | — |
| Fmax margin vs 27 MHz | 245.52 / 27 = 9.09× | — | CALCULATION | — |
| Bitstream size (.fs, ASCII, uncompressed) | 2 069 320 | bytes | SIMULATION (tool output, `stat -c %s`) | fpga_pack.log |
| Counter MSB blink period | 2^24 / 27e6 = 0.621 | s | CALCULATION | — |
| Full flow run time | ≈ 3 | s wall | SIMULATION (observed `time`, container) | — |
| Pin numbers clk 52, S1 3, S2 4, LED 10/11/13/14/15/16, uart_tx 17, uart_rx 18 | — | pin | SOURCE [A], cross-checked [B], [D] | CST header |
| S1 ↔ pin 3, S2 ↔ pin 4 (silkscreen label mapping) | — | — | ASSUMPTION | see Assumptions |

## Assumptions
- **S1 = pin 3, S2 = pin 4** (which pin carries which silkscreen label). The fetched sources give
  the pin numbers (3 and 4, both active-low with pull-up) but no fetched text names S1/S2 per pin;
  the Sipeed pinmap image shows S1/S2 without pin numbers. Impact if swapped: the other button
  resets the design; no electrical risk. To be checked against the Sipeed schematic PDF
  (dl.sipeed.com unreachable from this container).
- GW1NR registers power up to INIT; synchroniser INIT=1 → design held in reset after configuration
  until the released button has been seen for 2 edges (netlist check: DFFS, SET tied to GND, INIT=1).
- 27 MHz clock modelled as 37.000 ns in simulation (cycle-based check, exact period irrelevant).

## Errors / deviations
- Port renamed `btn_s1_n` → `btn_rst_n` to match frozen INTERFACES.json (found mid-task); full flow re-run.
- Yosys log truncation when stdout redirected to a file (YoWASP + ABC9) — worked around with `-l`;
  documented in the skill. Early runs' logs were overwritten by the final run.
- Script failed once with exit 141 (SIGPIPE from `| head` under pipefail) — fixed.
- Lint waivers: none. No `lint_off` used.
- Extra (not requested) deliverables: tests/smoke/cst_all_ports_top.v and scripts/pnr_pin_report.py,
  added because the CST's UART/S2 pins were otherwise untested and nextpnr is silent on port-name typos.

## Open decisions (for the manager)
1. Confirm S1/S2 ↔ pin 3/4 from the official Sipeed schematic, or accept the ASSUMPTION.
2. `btn_s2_n` is constrained in the shared CST but is not in INTERFACES.json. Harmless (Info only);
   keep as documented spare or delete. Note pin 4 is dual-purpose JTAGSEL_N [D] — if the SoC ever
   uses S2, check whether gowin_pack needs `--jtag_as_gpio`/similar (not investigated).
3. Suggested additions for management/SOURCES.md (I may not write it): sources [A]–[D] above.
4. Suggested metrics.json entries: fmax_smoke_counter 245.52 MHz (seed 1, rev be4b802-dirty,
   logs/smoke/fpga_pnr.log); bitstream_size_gw1n9c 2069320 bytes.

## Next actions
- Reuse design/constraints/tangnano9k.cst and scripts/smoke_fpga.sh step structure for the SoC flow
  (add the pin-report grep for uart_tx/uart_rx).
- For larger designs, run several seeds and report the worst Fmax (not needed here: 9× margin).

## Tooling note (task item 6)
ToolSearch query "github" (max_results 3) returned: `mcp__github__actions_get`,
`mcp__github__actions_list`, `mcp__github__actions_run_trigger`. None were called. (Separately,
the session reported the plugin `engineering:github` MCP server failed to connect; the
`mcp__github__*` tools are a different, deferred server.)
