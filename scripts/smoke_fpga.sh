#!/usr/bin/env bash
# =============================================================================
# scripts/smoke_fpga.sh  -  ST-FPGA-01 toolchain smoke test (known answer)
#
# Runs the complete open-source FPGA route for the Sipeed Tang Nano 9K
# (Gowin GW1NR-LV9QN88PC6/I5, nextpnr family GW1N-9C) on smoke_counter:
#   1. verilator --lint-only -Wall          (RTL, and testbench with --timing)
#   2. iverilog/vvp simulation              (must print TEST PASSED)
#   2b. negative check: same TB with -DINJECT_FAULT must FAIL (proves the
#       checker and the $fatal exit status really work)
#   3. yowasp-yosys synth_gowin             -> netlist JSON
#   4. yowasp-nextpnr-himbaechel-gowin P&R  at 27 MHz, single thread, seed 1,
#      WITHOUT --timing-allow-fail (a timing failure aborts the script)
#   5. gowin_pack                           -> .fs bitstream
#      (ONLY to prove the route; this script never programs any hardware)
#   6. shared-CST check: tests/smoke/cst_all_ports_top.v (uses every CST port)
#      through synth + P&R + pin report + pack
#
# Logs    : logs/smoke/fpga_*.log           (kept, versioned)
# Products: sim/smoke/build/                (gitignored by "sim/**/build/")
#
# Usage   : bash scripts/smoke_fpga.sh       (from anywhere)
# Exit    : 0 only if every step succeeded AND its decisive log line was found.
# =============================================================================
set -euo pipefail

# --- Paths -------------------------------------------------------------------
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TOP=smoke_counter
RTL="design/rtl/common/smoke_counter.v"
TB="tests/smoke/tb_smoke_counter.v"
CST="design/constraints/tangnano9k.cst"
DEVICE="GW1NR-LV9QN88PC6/I5"
FAMILY="GW1N-9C"
FREQ_MHZ=27
SEED=1

LOG=logs/smoke
BUILD=sim/smoke/build
mkdir -p "$LOG" "$BUILD"

# --- Tools (project venv provides the YoWASP tools and gowin_pack) -----------
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"

# Helper: print a step banner to stdout.
step() { printf '\n==== %s ====\n' "$*"; }

# Helper: require that a regex is present in a log (exit code 0 is not a pass).
require() {  # require <log> <regex> <description>
    if ! grep -E -q "$2" "$1"; then
        echo "SMOKE FAIL: '$3' not found in $1" >&2
        exit 1
    fi
}

REV="$(git rev-parse --short HEAD 2>/dev/null || echo 'no-commit')"
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then REV="${REV}-dirty"; fi

# --- 0. Tool versions ----------------------------------------------------------
step "0. tool versions"
{
    echo "# ST-FPGA-01 tool versions  $(date -Is)  input revision: $REV"
    echo "verilator : $(verilator --version)"
    echo "iverilog  : $(iverilog -V 2>&1 | head -n1)"
    echo "yosys     : $(yowasp-yosys -V)"
    echo "nextpnr   : $(yowasp-nextpnr-himbaechel-gowin --version 2>&1 | head -n1)"
    echo "apycula   : $(pip show apycula 2>/dev/null | grep '^Version')"
} 2>&1 | tee "$LOG/fpga_versions.log"

# --- 1. Lint -------------------------------------------------------------------
step "1. verilator lint"
{
    echo "# cmd: verilator --lint-only -Wall $RTL --top-module $TOP"
    verilator --lint-only -Wall "$RTL" --top-module "$TOP"
    echo "LINT_RTL_EXIT=$?"
    echo "# cmd: verilator --lint-only -Wall --timing $RTL $TB --top-module tb_smoke_counter"
    verilator --lint-only -Wall --timing "$RTL" "$TB" --top-module tb_smoke_counter
    echo "LINT_TB_EXIT=$?"
} 2>&1 | tee "$LOG/fpga_lint.log"
require "$LOG/fpga_lint.log" '^LINT_RTL_EXIT=0$' "RTL lint clean"
require "$LOG/fpga_lint.log" '^LINT_TB_EXIT=0$'  "TB lint clean"
if grep -q '%Warning\|%Error' "$LOG/fpga_lint.log"; then
    echo "SMOKE FAIL: verilator reported warnings/errors" >&2; exit 1
fi

# --- 2. Simulation (known answer) -------------------------------------------------
step "2. iverilog simulation"
{
    echo "# cmd: iverilog -g2005 -Wall -o $BUILD/tb_smoke_counter.vvp $RTL $TB && vvp -n $BUILD/tb_smoke_counter.vvp"
    iverilog -g2005 -Wall -o "$BUILD/tb_smoke_counter.vvp" "$RTL" "$TB"
    vvp -n "$BUILD/tb_smoke_counter.vvp"
    echo "SIM_EXIT=$?"
} 2>&1 | tee "$LOG/fpga_sim.log"
require "$LOG/fpga_sim.log" '^TEST PASSED$' "TEST PASSED"
require "$LOG/fpga_sim.log" '^PASS: TC1 KNOWN ANSWER: count after 1000 edges : got 0x0003e6 \(998\)' "known answer 998"
if grep -q '^FAIL' "$LOG/fpga_sim.log"; then echo "SMOKE FAIL: FAIL lines in sim log" >&2; exit 1; fi

# --- 2b. Negative check: an injected wrong expectation must be detected --------
step "2b. negative check (INJECT_FAULT must fail)"
set +e
{
    echo "# cmd: iverilog -g2005 -Wall -DINJECT_FAULT -o $BUILD/tb_smoke_counter_fault.vvp $RTL $TB && vvp -n $BUILD/tb_smoke_counter_fault.vvp"
    iverilog -g2005 -Wall -DINJECT_FAULT -o "$BUILD/tb_smoke_counter_fault.vvp" "$RTL" "$TB"
    vvp -n "$BUILD/tb_smoke_counter_fault.vvp"
    echo "SIM_FAULT_EXIT=$?"
} > "$LOG/fpga_sim_inject_fault.log" 2>&1
set -e
cat "$LOG/fpga_sim_inject_fault.log" | grep -E 'FAIL|TEST|EXIT' || true
require "$LOG/fpga_sim_inject_fault.log" '^TEST FAILED$' "TEST FAILED under injected fault"
require "$LOG/fpga_sim_inject_fault.log" '^SIM_FAULT_EXIT=[1-9]' "non-zero exit under injected fault"

# --- 3. Synthesis ----------------------------------------------------------------
step "3. yosys synth_gowin"
# GOTCHA (found in ST-FPGA-01): when yowasp-yosys stdout is redirected to a
# FILE, everything printed after the ABC9 step is lost (log stops at
# "Running ABC command"), although yosys completes and exits 0. Use yosys' own
# -l <logfile> instead. The log path must be RELATIVE to (inside) the working
# directory: the YoWASP WebAssembly sandbox cannot open files under /tmp.
YS="read_verilog $RTL; synth_gowin -top $TOP -json $BUILD/$TOP.json; stat"
echo "# cmd: yowasp-yosys -l $LOG/fpga_synth.log -p \"$YS\"" > "$BUILD/synth_cmd.txt"
yowasp-yosys -l "$LOG/fpga_synth.log" -p "$YS" > "$BUILD/synth_stdout.log" 2>&1
# Prepend the command line to the log (reports keep the exact command at the top).
cat "$BUILD/synth_cmd.txt" "$LOG/fpga_synth.log" > "$BUILD/synth_tmp.log" && mv "$BUILD/synth_tmp.log" "$LOG/fpga_synth.log"
require "$LOG/fpga_synth.log" 'End of script' "yosys End of script"
# Show only the final 'stat' section (synth_gowin prints intermediate stats too).
sed -n '/^3\. Printing statistics/,/^End of script/p' "$LOG/fpga_synth.log"

# --- 4. Place & route --------------------------------------------------------------
step "4. nextpnr-himbaechel-gowin P&R @ ${FREQ_MHZ} MHz"
{
    echo "# cmd: yowasp-nextpnr-himbaechel-gowin --json $BUILD/$TOP.json --write $BUILD/${TOP}_pnr.json --device $DEVICE --vopt family=$FAMILY --vopt cst=$CST --freq $FREQ_MHZ --report $BUILD/${TOP}_report.json --seed $SEED --threads 1"
    yowasp-nextpnr-himbaechel-gowin \
        --json "$BUILD/$TOP.json" \
        --write "$BUILD/${TOP}_pnr.json" \
        --device "$DEVICE" \
        --vopt family="$FAMILY" \
        --vopt cst="$CST" \
        --freq "$FREQ_MHZ" \
        --report "$BUILD/${TOP}_report.json" \
        --seed "$SEED" \
        --threads 1
} > "$LOG/fpga_pnr.log" 2>&1
cp "$BUILD/${TOP}_report.json" "$LOG/fpga_pnr_report.json"
require "$LOG/fpga_pnr.log" "Max frequency for clock .*PASS at ${FREQ_MHZ}\.00 MHz" "timing PASS at ${FREQ_MHZ} MHz"
# nextpnr prints "Max frequency" twice: after placement (estimate) and after
# routing (final). The LAST one is the routed result and is the one that counts.
grep -E 'Max frequency for clock' "$LOG/fpga_pnr.log" | tail -n 1
grep -E -i 'warning|error' "$LOG/fpga_pnr.log" || echo "(no warnings/errors in P&R log)"
# Constraints for ports that do not exist in this top level (btn_s2_n,
# uart_tx, uart_rx) are reported only as "Info: Cell <name> not found".
grep -E 'Cell .* not found' "$LOG/fpga_pnr.log" | grep -v psram || true

# --- 4b. Independent pin check -------------------------------------------------
step "4b. placed pins vs. CST (Apicula chipdb lookup)"
{
    echo "# cmd: python scripts/pnr_pin_report.py $BUILD/${TOP}_pnr.json GW1N-9C QFN88P"
    python scripts/pnr_pin_report.py "$BUILD/${TOP}_pnr.json" GW1N-9C QFN88P
} 2>&1 | tee "$LOG/fpga_pins.log"
for exp in 'clk\[0\] .* pin  52' 'btn_rst_n\[0\] .* pin   3' \
           'led_n\[0\] .* pin  10' 'led_n\[1\] .* pin  11' 'led_n\[2\] .* pin  13' \
           'led_n\[3\] .* pin  14' 'led_n\[4\] .* pin  15' 'led_n\[5\] .* pin  16'; do
    require "$LOG/fpga_pins.log" "$exp" "placement $exp"
done

# --- 5. Bitstream ------------------------------------------------------------------
step "5. gowin_pack (bitstream generation only, NO programming)"
{
    echo "# cmd: gowin_pack -d $FAMILY -o $BUILD/$TOP.fs $BUILD/${TOP}_pnr.json"
    gowin_pack -d "$FAMILY" -o "$BUILD/$TOP.fs" "$BUILD/${TOP}_pnr.json"
    echo "PACK_EXIT=$?"
    echo "# bitstream file:"
    ls -l "$BUILD/$TOP.fs"
    echo "size_bytes=$(stat -c %s "$BUILD/$TOP.fs")"
    sha256sum "$BUILD/$TOP.fs"
    echo "# first 3 lines of the .fs (ASCII '0'/'1' bitstream text), cut to 80 chars:"
    cut -c1-80 "$BUILD/$TOP.fs" | sed -n '1,3p'
    echo "lines=$(wc -l < "$BUILD/$TOP.fs")"
} > "$LOG/fpga_pack.log" 2>&1
cat "$LOG/fpga_pack.log"
require "$LOG/fpga_pack.log" '^PACK_EXIT=0$' "gowin_pack exit 0"
[ -s "$BUILD/$TOP.fs" ] || { echo "SMOKE FAIL: empty .fs" >&2; exit 1; }

# --- 6. Shared-CST check: every port of tangnano9k.cst used at once ---------------
# smoke_counter leaves uart_tx/uart_rx/btn_s2_n unconstrained-in-practice, so a
# tiny throw-away top that uses ALL CST ports is pushed through synth + P&R +
# pack to prove the shared constraint file is legal for the SoC (pins, IO
# standards, bank voltages). It has only IO->FF->IO paths, so nextpnr reports
# "No Fmax available" for it - that is expected and not a timing result.
step "6. shared CST check (all ports: clk, btn_rst_n, btn_s2_n, led_n, uart_tx, uart_rx)"
CTOP=cst_all_ports_top
CSRC=tests/smoke/cst_all_ports_top.v
{
    echo "# cmd: verilator --lint-only -Wall $CSRC --top-module $CTOP"
    verilator --lint-only -Wall "$CSRC" --top-module "$CTOP"
    echo "LINT_CST_TOP_EXIT=$?"
} > "$LOG/fpga_cst_check_lint.log" 2>&1
yowasp-yosys -l "$LOG/fpga_cst_check_synth.log" \
    -p "read_verilog $CSRC; synth_gowin -top $CTOP -json $BUILD/$CTOP.json" > "$BUILD/cst_synth_stdout.log" 2>&1
require "$LOG/fpga_cst_check_synth.log" 'End of script' "cst check: yosys End of script"
{
    echo "# cmd: yowasp-nextpnr-himbaechel-gowin --json $BUILD/$CTOP.json --write $BUILD/${CTOP}_pnr.json --device $DEVICE --vopt family=$FAMILY --vopt cst=$CST --freq $FREQ_MHZ --seed $SEED --threads 1"
    yowasp-nextpnr-himbaechel-gowin --json "$BUILD/$CTOP.json" --write "$BUILD/${CTOP}_pnr.json" \
        --device "$DEVICE" --vopt family="$FAMILY" --vopt cst="$CST" \
        --freq "$FREQ_MHZ" --seed "$SEED" --threads 1
    echo "# cmd: python scripts/pnr_pin_report.py $BUILD/${CTOP}_pnr.json GW1N-9C QFN88P"
    python scripts/pnr_pin_report.py "$BUILD/${CTOP}_pnr.json" GW1N-9C QFN88P
    echo "# cmd: gowin_pack -d $FAMILY -o $BUILD/$CTOP.fs $BUILD/${CTOP}_pnr.json"
    gowin_pack -d "$FAMILY" -o "$BUILD/$CTOP.fs" "$BUILD/${CTOP}_pnr.json"
    echo "PACK_CST_TOP_EXIT=$?"
} > "$LOG/fpga_cst_check_pnr.log" 2>&1
grep -E ' pin |IOB:|Fmax|PACK_CST' "$LOG/fpga_cst_check_pnr.log"
require "$LOG/fpga_cst_check_lint.log" '^LINT_CST_TOP_EXIT=0$' "cst check lint"
require "$LOG/fpga_cst_check_pnr.log" 'Program finished normally' "cst check P&R finished"
require "$LOG/fpga_cst_check_pnr.log" '^PACK_CST_TOP_EXIT=0$' "cst check pack"
for exp in 'clk\[0\] .* pin  52' 'btn_rst_n\[0\] .* pin   3' 'btn_s2_n\[0\] .* pin   4' \
           'uart_tx\[0\] .* pin  17' 'uart_rx\[0\] .* pin  18' \
           'led_n\[0\] .* pin  10' 'led_n\[5\] .* pin  16'; do
    require "$LOG/fpga_cst_check_pnr.log" "$exp" "cst check placement $exp"
done

# --- Summary ---------------------------------------------------------------------
step "summary"
{
    echo "# ST-FPGA-01 summary  $(date -Is)  input revision: $REV"
    grep -E '^TEST (PASSED|FAILED)$|KNOWN ANSWER' "$LOG/fpga_sim.log"
    echo "negative check: $(grep -E '^TEST FAILED$' "$LOG/fpga_sim_inject_fault.log") ($(grep -E '^SIM_FAULT_EXIT=' "$LOG/fpga_sim_inject_fault.log"))"
    echo "post-route: $(grep -E 'Max frequency for clock' "$LOG/fpga_pnr.log" | tail -n 1)"
    # (no "| head" here: with pipefail an early-closing head kills the script
    #  with SIGPIPE, exit 141 - a gotcha hit in ST-FPGA-01)
    # Print the utilisation table only (header line + following lines with '%').
    awk '/Device utilisation/{f=1; print; next} f && /%/ {print; next} f {exit}' "$LOG/fpga_pnr.log"
    grep -E '^size_bytes=' "$LOG/fpga_pack.log"
    grep -E 'smoke_counter.fs$' "$LOG/fpga_pack.log" | grep -v '^-' || true
    echo "pins: $(grep -c ' pin ' "$LOG/fpga_pins.log") placed IOs match the CST (see fpga_pins.log)"
    echo "shared CST check: $(grep -c ' pin ' "$LOG/fpga_cst_check_pnr.log") IOs placed as constrained, pack $(grep -E '^PACK_CST_TOP_EXIT=' "$LOG/fpga_cst_check_pnr.log") (see fpga_cst_check_pnr.log)"
    echo "SMOKE_FPGA: ALL STEPS PASSED"
} 2>&1 | tee "$LOG/fpga_summary.log"
