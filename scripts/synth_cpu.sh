#!/usr/bin/env bash
# =============================================================================
# scripts/synth_cpu.sh  -  RTL-CPU: synthesis + P&R of rv32i_core (area, Fmax)
#
# Method (documented in management/handoffs/fpga-engineer/RTL-CPU.md)
#   A. In-context, routed: tests/cpu/cpu_synth_top.v wraps the core with a
#      4 KiB BSRAM RAM (1 wait state, initialised with the official test
#      rand_00), a 6-bit LED register and XOR reductions of every bus/debug
#      output onto the 6 board LEDs (the core's ~140 bus pins do not fit the
#      QN88 package and unconnected outputs would be optimised away).
#      yosys synth_gowin -nowidelut -> nextpnr-himbaechel-gowin P&R for
#      GW1NR-LV9QN88PC6/I5 (family GW1N-9C) at 27 MHz, seeds 1..3, single
#      thread, WITHOUT --timing-allow-fail -> Fmax = worst routed seed.
#      Pin check with scripts/pnr_pin_report.py, gowin_pack to prove the route
#      (bitstream is never programmed into hardware).
#   B. Out-of-context, core only: synth_gowin -noiopads -top rv32i_core
#      (cell counts of the core without wrapper; not placed/routed).
#   C. For reference, A's wrapper and B's core are also synthesised with the
#      default synth_gowin (wide-LUT MUX2_LUTx mapping); -nowidelut is the
#      chosen flow because it is smaller for this design (see handoff).
#
# Logs    : logs/cpu/synth_*.log, logs/cpu/pnr_s<seed>.log, logs/cpu/pins.log,
#           logs/cpu/pack.log; summary reports/fpga/cpu/cpu_synth_pnr.txt
# Products: sim/cpu/build/ (gitignored)
# Exit    : 0 only if every step succeeded and every seed met 29.7 MHz
#           (27 MHz + 10 %, RTL-CPU acceptance).
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"

RTL="design/rtl/cpu/rv32i_core.v design/rtl/cpu/rv32i_decode.v design/rtl/cpu/rv32i_alu.v design/rtl/cpu/rv32i_regfile.v"
TOPV="tests/cpu/cpu_synth_top.v"
TOP=cpu_synth_top
CST="design/constraints/tangnano9k.cst"
DEVICE="GW1NR-LV9QN88PC6/I5"
FAMILY="GW1N-9C"
FMIN=29.7
LOG=logs/cpu
B=sim/cpu/build
REP=reports/fpga/cpu
mkdir -p "$LOG" "$B" "$REP"

REV="$(git rev-parse --short HEAD 2>/dev/null || echo 'no-commit')"
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then REV="${REV}-dirty"; fi
OUT="$REP/cpu_synth_pnr.txt"
fail=0

# Print the final yosys 'stat' cell table of a log (only "N CELL" lines).
cells() { sed -n '/^[0-9]*\. Printing statistics/,/End of script/p' "$1" | grep -E '^ +[0-9]+ +[A-Z]' ; }

# Run yosys with its own log (see rtl-gowin-flow lessons: no stdout redirect
# of the log, relative paths only).
ys() {  # ys <log> <script>
    yowasp-yosys -l "$1" -p "$2" > "$B/ys_stdout.log" 2>&1
    grep -q 'End of script' "$1" || { echo "yosys failed: $1" >&2; exit 1; }
}

# ---- 0. lint of the wrapper (core lint is in sim_cpu.sh) ---------------------------
{
    echo "# cmd: verilator --lint-only -Wall $RTL $TOPV --top-module $TOP"
    # shellcheck disable=SC2086
    verilator --lint-only -Wall $RTL $TOPV --top-module $TOP
    echo "LINT_TOP_EXIT=$?"
} > "$LOG/synth_top_lint.log" 2>&1 || true
grep -q '^LINT_TOP_EXIT=0$' "$LOG/synth_top_lint.log" && ! grep -q '%Warning\|%Error' "$LOG/synth_top_lint.log" \
    || { echo "wrapper lint FAILED"; fail=1; }

# ---- A. in-context synthesis (chosen flow) -------------------------------------------
ys "$LOG/synth_top.log" "read_verilog $RTL $TOPV; synth_gowin -nowidelut -top $TOP -json $B/$TOP.json; stat"
# ---- B. out-of-context core -----------------------------------------------------------
ys "$LOG/synth_core_ooc.log" "read_verilog $RTL; synth_gowin -nowidelut -noiopads -top rv32i_core -json $B/rv32i_core_ooc.json; stat"
# ---- C. reference: default (wide-LUT) mapping -------------------------------------------
ys "$LOG/synth_top_widelut.log" "read_verilog $RTL $TOPV; synth_gowin -top $TOP -json $B/${TOP}_widelut.json; stat"
ys "$LOG/synth_core_ooc_widelut.log" "read_verilog $RTL; synth_gowin -noiopads -top rv32i_core -json $B/rv32i_core_ooc_widelut.json; stat"

# ---- A. place & route, 3 seeds ---------------------------------------------------------
worst=""
for s in 1 2 3; do
    PL="$LOG/pnr_s$s.log"
    {
        echo "# cmd: yowasp-nextpnr-himbaechel-gowin --json $B/$TOP.json --write $B/${TOP}_pnr_s$s.json --device $DEVICE --vopt family=$FAMILY --vopt cst=$CST --freq 27 --report $B/${TOP}_report_s$s.json --seed $s --threads 1"
        yowasp-nextpnr-himbaechel-gowin --json "$B/$TOP.json" --write "$B/${TOP}_pnr_s$s.json" \
            --device "$DEVICE" --vopt family="$FAMILY" --vopt cst="$CST" --freq 27 \
            --report "$B/${TOP}_report_s$s.json" --seed "$s" --threads 1
        echo "PNR_EXIT=$?"
    } > "$PL" 2>&1 || true
    grep -q '^PNR_EXIT=0$' "$PL" || { echo "P&R seed $s FAILED"; fail=1; continue; }
    f="$(grep -E 'Max frequency for clock' "$PL" | tail -n 1 | sed -n 's/.*: \([0-9.]*\) MHz.*/\1/p')"
    echo "seed $s: $f MHz"
    if [ -z "$worst" ] || python -c "import sys; sys.exit(0 if $f < $worst else 1)"; then worst="$f"; fi
    cp "$B/${TOP}_report_s$s.json" "$REP/pnr_report_s$s.json"
done
if [ -z "$worst" ] || ! python -c "import sys; sys.exit(0 if $worst >= $FMIN else 1)"; then
    echo "Fmax below $FMIN MHz"; fail=1
fi

# ---- pins + bitstream (route proof only, never programmed) ---------------------------------
python scripts/pnr_pin_report.py "$B/${TOP}_pnr_s1.json" GW1N-9C QFN88P > "$LOG/pins.log" 2>&1 || fail=1
for exp in 'clk\[0\] .* pin  52' 'btn_rst_n\[0\] .* pin   3' 'led_n\[0\] .* pin  10' 'led_n\[5\] .* pin  16'; do
    grep -E -q "$exp" "$LOG/pins.log" || { echo "pin check failed: $exp"; fail=1; }
done
{
    echo "# cmd: gowin_pack -d $FAMILY -o $B/$TOP.fs $B/${TOP}_pnr_s1.json"
    gowin_pack -d "$FAMILY" -o "$B/$TOP.fs" "$B/${TOP}_pnr_s1.json"
    echo "PACK_EXIT=$?"
    sha256sum "$B/$TOP.fs"
} > "$LOG/pack.log" 2>&1 || true
grep -q '^PACK_EXIT=0$' "$LOG/pack.log" || { echo "pack FAILED"; fail=1; }

# ---- summary report ---------------------------------------------------------------------------
{
    echo "# RTL-CPU synthesis / P&R report   $(date -Is)   input revision $REV"
    echo "# generated by: bash scripts/synth_cpu.sh"
    echo "# tools: $(yowasp-yosys -V) | $(yowasp-nextpnr-himbaechel-gowin --version 2>&1 | head -n1) | apycula $(pip show apycula 2>/dev/null | sed -n 's/^Version: //p')"
    echo "# device $DEVICE (family $FAMILY), clock constraint 27 MHz, acceptance Fmax >= $FMIN MHz"
    echo
    echo "== A. in-context: $TOP (core + 4 KiB BSRAM RAM + LED/XOR wrapper), synth_gowin -nowidelut"
    echo "-- yosys cells (logs/cpu/synth_top.log):"
    cells "$LOG/synth_top.log"
    echo "-- nextpnr utilisation, seed 1 (logs/cpu/pnr_s1.log; nextpnr's LUT4 count includes ALU cells):"
    awk '/Device utilisation/{f=1; next} f && /%/ {print; next} f {exit}' "$LOG/pnr_s1.log" \
        | grep -E 'IOB|LUT4|MUX2_LUT5|ALU:|DFF|BSRAM|RAM16|MULT9' | sed 's/^Info: *//'
    echo "-- routed Fmax per seed (last 'Max frequency' line of each log):"
    for s in 1 2 3; do echo "seed $s: $(grep -E 'Max frequency for clock' "$LOG/pnr_s$s.log" | tail -n 1 | sed 's/^Info: //')"; done
    echo "worst seed Fmax: $worst MHz (margin vs 27 MHz: $(python -c "print(f'{($worst/27-1)*100:.0f}')") %)"
    echo
    echo "== B. out-of-context core only: rv32i_core, synth_gowin -nowidelut -noiopads (not placed)"
    cells "$LOG/synth_core_ooc.log"
    echo
    echo "== C. reference, default wide-LUT mapping (NOT the chosen flow)"
    echo "-- $TOP:"
    cells "$LOG/synth_top_widelut.log" | grep -E 'LUT|MUX|ALU'
    echo "-- rv32i_core OOC:"
    cells "$LOG/synth_core_ooc_widelut.log" | grep -E 'LUT|MUX|ALU'
    echo
    echo "pins: $(grep -c ' pin ' "$LOG/pins.log") IOs placed (logs/cpu/pins.log); bitstream: $(grep -E 'PACK_EXIT' "$LOG/pack.log") (route proof only, never programmed)"
    if [ $fail -eq 0 ]; then echo "SYNTH_CPU: PASS"; else echo "SYNTH_CPU: FAIL"; fi
} > "$OUT"
cat "$OUT"
exit $fail
