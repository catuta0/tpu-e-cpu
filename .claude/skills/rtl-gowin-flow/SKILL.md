---
name: rtl-gowin-flow
description: Workflow for RTL simulation, lint, synthesis and place-and-route of Verilog designs for the Gowin GW1NR-9 (Tang Nano 9K) with the open-source flow installed in this project.
---

# RTL / Gowin flow (Tang Nano 9K)

## Tools (installed; check versions with the commands)
- `source /home/user/tpu-e-cpu/.venv/bin/activate` first.
- Simulation: `iverilog -g2005 -Wall -o build/x.vvp ...; vvp -n build/x.vvp`
  (Icarus 12.0). Lint: `verilator --lint-only -Wall <files> --top-module <top>` (5.020).
- Synthesis: `yowasp-yosys -p "read_verilog <files>; synth_gowin -top <top> -json build/<top>.json"`
  (Yosys 0.70, YoWASP build). First run of a YoWASP tool takes ~20 s to warm up.
- P&R: `yowasp-nextpnr-himbaechel-gowin --json build/<top>.json --write build/<top>_pnr.json
  --device GW1NR-LV9QN88PC6/I5 --vopt family=GW1N-9C --vopt cst=<file.cst>
  --freq 27 --report build/<top>_report.json --seed 1` (nextpnr-0.11.1).
- Bitstream (only to prove the route; never flash hardware):
  `gowin_pack -d GW1N-9C -o build/<top>.fs build/<top>_pnr.json` (Apicula 0.32).

## Rules
- Verilog-2005, `default_nettype none` at the top of every file and
  `default_nettype wire` at the bottom.
- Synchronous active-high internal reset `rst`, generated from the board button
  by a synchroniser in the top level.
- Single clock domain `clk` (27 MHz board oscillator) unless a spec says otherwise.
- Inferred BSRAM: use a clocked read (`always @(posedge clk) rdata <= mem[addr]`)
  so Yosys maps it to BSRAM; check the utilisation report shows BSRAM, not LUTs.
- Read timing from the nextpnr log line `Max frequency for clock '...': X MHz (PASS|FAIL at 27.00 MHz)`.
  Report the worst of several seeds if close to the limit.
- Testbenches: self-checking, deterministic, print `TEST PASSED`/`TEST FAILED`,
  call `$fatal(1)` on failure so the script exit code is meaningful, and have a
  timeout watchdog.

## Lessons learned
- (none yet)
