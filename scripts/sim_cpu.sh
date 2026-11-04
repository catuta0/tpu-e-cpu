#!/usr/bin/env bash
# =============================================================================
# scripts/sim_cpu.sh  -  RTL-CPU: lint + simulation regression of rv32i_core
#
# Steps
#   1. verilator --lint-only -Wall on the CPU RTL (top rv32i_core) and on the
#      testbench (--timing) -> logs/cpu/lint.log; any %Warning/%Error fails.
#   2. Companion expectation files: scripts/cpu_meta_to_tb.py converts every
#      <test>.meta.json listed in <TEST_DIR>/index.txt into
#      sim/cpu/build/meta/<test>.tbmeta.hex (also re-checks the sha256 of the
#      .hex/.sig recorded by the generator).
#   3. iverilog compile of tests/cpu/tb_rv32i_core.v + the CPU RTL.
#   4. For every test and every bus configuration below, one vvp run
#      (log: logs/cpu/runs/<test>__<cfg>.log). A run passes only if it prints
#      "TEST PASSED", exits 0 and its RESULT line says status=PASS viol=0.
#        ws0   : 0 wait states (mem_ready in the first mem_valid cycle) -> CPI
#        ws1   : 1 wait state  (behaviour of a registered BSRAM slave)
#        ws3   : 3 wait states
#        rand  : 0 wait states + random 0..7 stall cycles per transaction
#                (seed = 1 + test index, deterministic)
#   5. Negative checks (must FAIL): signature fault injection and protocol-
#      checker fault injection on dir_alu_reg.
#   6. Summary -> logs/cpu/sim_cpu_summary.log (per-test PASS/FAIL per
#      config, totals, CPI per test at ws0 and aggregate CPI).
#
# Usage   : bash scripts/sim_cpu.sh [TEST_DIR]     (default sim/data/cpu_tests)
# Exit    : 0 only if lint is clean, every run passed and both negative
#           checks failed as they must.
# Runs simulations one at a time (shared 4-core machine).
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"

TEST_DIR="${1:-sim/data/cpu_tests}"
RTL="design/rtl/cpu/rv32i_core.v design/rtl/cpu/rv32i_decode.v design/rtl/cpu/rv32i_alu.v design/rtl/cpu/rv32i_regfile.v"
TB="tests/cpu/tb_rv32i_core.v"
LOG=logs/cpu
BUILD=sim/cpu/build
mkdir -p "$LOG/runs" "$BUILD/meta"
rm -f "$LOG"/runs/*.log

REV="$(git rev-parse --short HEAD 2>/dev/null || echo 'no-commit')"
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then REV="${REV}-dirty"; fi
SUM="$LOG/sim_cpu_summary.log"
fail=0

step() { printf '\n==== %s ====\n' "$*"; }

# ---- 1. Lint ---------------------------------------------------------------------
step "1. verilator lint"
set +e
{
    echo "# $(date -Is) revision $REV"
    echo "# $(verilator --version)"
    echo "# cmd: verilator --lint-only -Wall $RTL --top-module rv32i_core"
    # shellcheck disable=SC2086
    verilator --lint-only -Wall $RTL --top-module rv32i_core
    echo "LINT_RTL_EXIT=$?"
    echo "# cmd: verilator --lint-only -Wall --timing $RTL $TB --top-module tb_rv32i_core"
    # shellcheck disable=SC2086
    verilator --lint-only -Wall --timing $RTL $TB --top-module tb_rv32i_core
    echo "LINT_TB_EXIT=$?"
} > "$LOG/lint.log" 2>&1
set -e
cat "$LOG/lint.log"
if ! grep -q '^LINT_RTL_EXIT=0$' "$LOG/lint.log" || ! grep -q '^LINT_TB_EXIT=0$' "$LOG/lint.log" \
   || grep -q '%Warning\|%Error' "$LOG/lint.log"; then
    echo "LINT FAILED" >&2; fail=1
fi

# ---- 2. Companion meta files -----------------------------------------------------------
step "2. meta -> TB companion files ($TEST_DIR)"
if [ ! -f "$TEST_DIR/index.txt" ]; then
    echo "OFFICIAL SUITE NOT RUN: $TEST_DIR/index.txt does not exist" | tee "$SUM"
    exit 2
fi
python scripts/cpu_meta_to_tb.py "$TEST_DIR" "$BUILD/meta" > "$LOG/meta_convert.log" 2>&1 || fail=1
tail -n 1 "$LOG/meta_convert.log"

# ---- 3. Compile ------------------------------------------------------------------------
step "3. iverilog compile"
# shellcheck disable=SC2086
iverilog -g2005 -Wall -o "$BUILD/tb_rv32i_core.vvp" $RTL $TB > "$LOG/compile.log" 2>&1
# shellcheck disable=SC2086
iverilog -g2005 -Wall -DINJECT_SIG_FAULT   -o "$BUILD/tb_rv32i_core_sigfault.vvp"   $RTL $TB >> "$LOG/compile.log" 2>&1
# shellcheck disable=SC2086
iverilog -g2005 -Wall -DINJECT_PROTO_FAULT -o "$BUILD/tb_rv32i_core_protofault.vvp" $RTL $TB >> "$LOG/compile.log" 2>&1
if [ -s "$LOG/compile.log" ]; then echo "compiler messages:"; cat "$LOG/compile.log"; fi

# ---- 4. Regression ---------------------------------------------------------------------
step "4. regression"
CFGS="ws0 ws1 ws3 rand"
run_one() {  # run_one <vvp> <test> <cfg> <idx> <logfile>
    local vvp="$1" t="$2" cfg="$3" idx="$4" lf="$5" args
    case "$cfg" in
        ws0)  args="+ws=0" ;;
        ws1)  args="+ws=1" ;;
        ws3)  args="+ws=3" ;;
        rand) args="+ws=0 +rand_stall=1 +seed=$((idx + 1))" ;;
    esac
    set +e
    # shellcheck disable=SC2086
    vvp -n "$vvp" +prog="$TEST_DIR/$t.hex" +sig="$TEST_DIR/$t.sig" \
        +meta="$BUILD/meta/$t.tbmeta.hex" +name="$t" $args > "$lf" 2>&1
    local rc=$?
    set -e
    echo "VVP_EXIT=$rc" >> "$lf"
    if [ $rc -eq 0 ] && grep -q '^TEST PASSED$' "$lf" && grep -q 'status=PASS .*viol=0$' "$lf"; then
        return 0
    fi
    return 1
}

{
    echo "# RTL-CPU simulation regression  $(date -Is)  revision $REV"
    echo "# tests: $TEST_DIR/index.txt ($(wc -l < "$TEST_DIR/index.txt") tests)  configs: $CFGS"
    echo "# tool: $(iverilog -V 2>&1 | head -n1)"
    echo "# columns: test, status per config, ws0 cycles, instret, CPI(ws0)"
} > "$SUM"

n_runs=0; n_pass=0; idx=0
tot_cyc=0; tot_ins=0
while read -r t; do
    [ -z "$t" ] && continue
    line="$(printf '%-26s' "$t")"
    test_ok=1
    for cfg in $CFGS; do
        lf="$LOG/runs/${t}__${cfg}.log"
        n_runs=$((n_runs + 1))
        if run_one "$BUILD/tb_rv32i_core.vvp" "$t" "$cfg" "$idx" "$lf"; then
            n_pass=$((n_pass + 1)); line="$line $cfg=PASS"
        else
            line="$line $cfg=FAIL"; test_ok=0; fail=1
        fi
    done
    r0="$(grep '^RESULT' "$LOG/runs/${t}__ws0.log" || true)"
    cyc="$(sed -n 's/.* cycles=\([0-9]*\) .*/\1/p' <<< "$r0")"
    ins="$(sed -n 's/.* instret=\([0-9]*\) .*/\1/p' <<< "$r0")"
    cpi="$(sed -n 's/.* cpi=\([0-9.]*\) .*/\1/p' <<< "$r0")"
    tot_cyc=$((tot_cyc + ${cyc:-0})); tot_ins=$((tot_ins + ${ins:-0}))
    if [ $test_ok -eq 1 ]; then st=PASS; else st=FAIL; fi
    echo "$st $line cycles=${cyc:-?} instret=${ins:-?} cpi_ws0=${cpi:-?}" | tee -a "$SUM"
    idx=$((idx + 1))
done < "$TEST_DIR/index.txt"

# ---- 5. Negative checks ------------------------------------------------------------------
step "5. negative checks (must FAIL)"
NEG_T=dir_alu_reg
neg_ok=1
if run_one "$BUILD/tb_rv32i_core_sigfault.vvp" "$NEG_T" ws0 0 "$LOG/neg_sigfault.log"; then
    echo "NEGATIVE CHECK BROKEN: INJECT_SIG_FAULT run passed" | tee -a "$SUM"; neg_ok=0; fail=1
fi
if run_one "$BUILD/tb_rv32i_core_protofault.vvp" "$NEG_T" ws1 0 "$LOG/neg_protofault.log"; then
    echo "NEGATIVE CHECK BROKEN: INJECT_PROTO_FAULT run passed" | tee -a "$SUM"; neg_ok=0; fail=1
fi
grep -q '^TEST FAILED' "$LOG/neg_sigfault.log"   || { neg_ok=0; fail=1; }
grep -q '^TEST FAILED' "$LOG/neg_protofault.log" || { neg_ok=0; fail=1; }
grep -q 'PROTOCOL VIOLATION' "$LOG/neg_protofault.log" || { neg_ok=0; fail=1; }

# ---- 6. Summary --------------------------------------------------------------------------
{
    echo "# negative checks: sig fault -> $(grep -E '^TEST (PASSED|FAILED)' "$LOG/neg_sigfault.log" | tr '\n' ' ')$(grep VVP_EXIT "$LOG/neg_sigfault.log");" \
         "proto fault -> $(grep -E '^TEST (PASSED|FAILED)' "$LOG/neg_protofault.log" | tr '\n' ' ')$(grep VVP_EXIT "$LOG/neg_protofault.log")" \
         "$( [ $neg_ok -eq 1 ] && echo '(both failed as required: OK)' || echo '(NOT OK)')"
    echo "# runs: $n_pass / $n_runs PASS"
    if [ "$tot_ins" -gt 0 ]; then
        echo "# aggregate CPI at 0 wait states: $tot_cyc cycles / $tot_ins instructions = $(python -c "print(f'{$tot_cyc/$tot_ins:.3f}')")"
    fi
    if [ $fail -eq 0 ]; then echo "SIM_CPU: ALL PASSED"; else echo "SIM_CPU: FAILURES"; fi
} | tee -a "$SUM"
exit $fail
