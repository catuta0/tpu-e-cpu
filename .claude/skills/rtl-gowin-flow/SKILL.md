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
- (ST-FPGA-01, fpga-engineer) Reference flow that works end to end in ~3 s for a
  small design: `bash scripts/smoke_fpga.sh` (lint -> sim -> synth -> P&R -> pin
  report -> pack). Copy its command lines, they are verified.
- **yowasp-yosys + file redirect loses the log tail.** With `yowasp-yosys ... > f.log`
  the log stops at "Running ABC command" (everything after ABC9, incl. `stat` and
  "End of script", is lost) although yosys exits 0 and writes the JSON. Use yosys'
  own log instead:
  `yowasp-yosys -l logs/<area>/x_synth.log -p "read_verilog <f.v>; synth_gowin -top <top> -json sim/<area>/build/<top>.json; stat" > sim/<area>/build/x_stdout.log 2>&1`
- **YoWASP tools only see the working directory tree** (WebAssembly sandbox): a
  `-l /tmp/...` or any path outside the project fails ("Can't open log file").
  Run from the project root with relative paths.
- Avoid `// synthesis translate_off`: Yosys 0.70 warns. Use `` `ifndef SYNTHESIS ``
  (read_verilog predefines SYNTHESIS). The only remaining synth warning is
  Yosys-internal: "Lexer warning: ... `bit' (at /share/abc9_map.v:35)" - benign.
- Working P&R line (single thread, no `--timing-allow-fail`, so a timing FAIL aborts):
  `yowasp-nextpnr-himbaechel-gowin --json B/<top>.json --write B/<top>_pnr.json --device GW1NR-LV9QN88PC6/I5 --vopt family=GW1N-9C --vopt cst=design/constraints/tangnano9k.cst --freq 27 --report B/<top>_report.json --seed 1 --threads 1 > logs/<area>/x_pnr.log 2>&1`
  nextpnr prints "Max frequency" TWICE (after placement = estimate, after routing =
  final): quote the LAST one. A design with only IO->FF->IO paths prints
  "No Fmax available; no interior timing paths" instead (not a failure).
- **CST ports missing from the netlist are only `Info: Cell <name> not found`**, not
  an error, so one shared `design/constraints/tangnano9k.cst` serves every top. The
  flip side: a typo in a port name is silent too. Always run
  `python scripts/pnr_pin_report.py B/<top>_pnr.json GW1N-9C QFN88P` and grep the
  expected pins (maps placed bel X?Y?/IOB? -> IO name -> package pin via Apicula chipdb).
  Also always present: 26 `Info: Cell O_psram_*/IO_psram_* not found` (GW1NR in-package PSRAM) - ignore.
- Trailing `// comments` after a CST statement are accepted by nextpnr's CST reader.
- Bitstream: `gowin_pack -d GW1N-9C -o B/<top>.fs B/<top>_pnr.json` -> ASCII .fs,
  ~2.07 MB uncompressed for GW1N-9C (Apicula's Makefile adds `-c` to compress). The
  .fs is deterministic for a fixed seed (same sha256 across runs and port renames).
- Gowin mapping: sync-reset flops -> DFFR; a `reg x = 1'b1` init -> DFFS with SET tied
  to GND (INIT=1); `+1` counters -> ALU carry chain (nextpnr counts ALU in LUT4 too).
- Tang Nano 9K pins: pin 4 (S2 button) is dual-purpose JTAGSEL_N; clk pin 52 is GCLKT_3.
- Bash: with `set -o pipefail`, `cmd | head -n N` can kill the script with SIGPIPE
  (exit 141) once head closes early. Don't pipe log extraction into head; use
  `awk '... {exit}' file` or `sed -n 1,Np file` on the file directly.
- `iverilog -g2005` accepts `$fatal(1, ...)` (Icarus 12) and returns exit 1 - proven by
  the INJECT_FAULT negative run. Verilator TB lint needs `--timing`; it flags
  blocking clock generators (use `always #(T) clk <= ~clk;`) and 32-bit
  integer localparams passed to narrower task args (declare `localparam [W-1:0]`).
