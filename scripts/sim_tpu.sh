#!/usr/bin/env bash
# =============================================================================
# scripts/sim_tpu.sh  -  RTL-TPU lint + simulation regression (fpga-engineer)
#
# Steps (each writes a log under logs/tpu/ and is checked for its decisive
# line - an exit code 0 alone is never taken as a pass):
#   1. verilator --lint-only -Wall on every RTL module of design/rtl/tpu/
#      (each module as top, sc_tpu for RNG_MODE 0/1/2 and IL 4/8/16, and the
#      synthesis wrapper)                                    -> lint_rtl.log
#   2. verilator --lint-only --timing on the testbenches (default warning
#      set; -Wno-INITIALDLY because the BFMs intentionally use non-blocking
#      assignments in initial-block tasks, which are standard Verilog
#      semantics for Icarus - the TBs are not meant for Verilator)
#                                                            -> lint_tb.log
#   3. unit TBs (Icarus): tb_sc_lfsr8 (+ rev B seed tables of sc_rng, TC7), tb_sc_postproc, tb_sc_lane_array, plus their
#      -DINJECT_FAULT negative runs, which MUST fail          -> tb_*.log
#   4. tb_sc_tpu for RNG_MODE 0, 1, 2 (one compile per mode): directed tests
#      D1..D11, RNG trace R1/R2, all golden vector files of sim/data/ for
#      that mode (SW-01a) and the K/s sweep sim/tpu/vectors/tpu_vectors_sweep_mode<m>.txt
#      (tests/tpu/gen_tpu_sweep_vectors.py), with LOG2_L clamp re-runs
#                                                            -> tb_sc_tpu_mode<m>.log
#   4b. tb_sc_tpu D12 with INIT_FILES=1 (init files read back, inference
#      without bus loading)                                  -> tb_sc_tpu_init_mode<m>.log
#   5. tb_sc_tpu negative run (-DINJECT_FAULT, mode 1, K=4 set) MUST fail
#                                                            -> tb_sc_tpu_inject_fault.log
#
# Usage   : bash scripts/sim_tpu.sh            (from anywhere; ~20-30 min,
#           dominated by the 3 x 360 K=8 inferences in Icarus)
#           QUICK=1 bash scripts/sim_tpu.sh    (skip the 360-vector files)
# Products: sim/tpu/build/ (gitignored)
# Exit    : 0 only if every step passed.
# =============================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LOG=logs/tpu
B=sim/tpu/build
mkdir -p "$LOG" "$B"
D=design/rtl/tpu
RTL="$D/sc_lfsr8.v $D/sc_rng.v $D/sc_lane_array.v $D/sc_postproc.v $D/sc_tpu_ctrl.v $D/sc_tpu.v"
DATA=sim/data
QUICK=${QUICK:-0}

REV="$(git rev-parse --short HEAD 2>/dev/null || echo no-commit)"
if [ -n "$(git status --porcelain -- design/rtl/tpu tests/tpu 2>/dev/null)" ]; then REV="${REV}-dirty"; fi

fail() { echo "SIM_TPU FAIL: $*" >&2; exit 1; }
require() {  # require <log> <regex> <what>
    grep -E -q "$2" "$1" || fail "'$3' not found in $1"
}
step() { printf '\n==== %s ====\n' "$*"; }

{
    echo "# RTL-TPU simulation regression  $(date -Is)  input revision: $REV"
    echo "verilator : $(verilator --version)"
    echo "iverilog  : $(iverilog -V 2>&1 | sed -n 1p)"
} | tee "$LOG/versions.log"

# ---------------------------------------------------------------- 1. RTL lint
step "1. RTL lint (verilator -Wall)"
{
    echo "# input revision: $REV"
    lint() {  # lint <top> <files> [-G...]
        local top=$1; shift; local files=$1; shift
        echo "# cmd: verilator --lint-only -Wall $files --top-module $top $*"
        if verilator --lint-only -Wall $files --top-module "$top" "$@"; then
            echo "LINT_OK $top $*"
        else
            echo "LINT_FAIL $top $*"
        fi
    }
    lint sc_lfsr8      "$D/sc_lfsr8.v"
    for m in 0 1 2; do lint sc_rng "$D/sc_lfsr8.v $D/sc_rng.v" -GRNG_MODE=$m; done
    lint sc_lane_array "$D/sc_lane_array.v"
    lint sc_postproc   "$D/sc_postproc.v"
    lint sc_tpu_ctrl   "$D/sc_tpu_ctrl.v"
    for m in 0 1 2; do lint sc_tpu "$RTL" -GRNG_MODE=$m; done
    for il in 4 16; do lint sc_tpu "$RTL" -GIL=$il -GRNG_MODE=1; done
    lint sc_tpu_synth_top "$RTL $D/sc_tpu_synth_top.v"
} > "$LOG/lint_rtl.log" 2>&1
grep -E '^LINT_' "$LOG/lint_rtl.log"
if grep -q -E '^LINT_FAIL|%Warning|%Error' "$LOG/lint_rtl.log"; then fail "RTL lint not clean"; fi
[ "$(grep -c '^LINT_OK' "$LOG/lint_rtl.log")" -eq 13 ] || fail "expected 13 LINT_OK lines"

# ---------------------------------------------------------------- 2. TB lint
step "2. TB lint (verilator --timing, default warnings, -Wno-INITIALDLY)"
{
    echo "# input revision: $REV"
    for t in "tb_sc_lfsr8:$D/sc_lfsr8.v $D/sc_rng.v" "tb_sc_postproc:$D/sc_postproc.v" "tb_sc_lane_array:$D/sc_lane_array.v" "tb_sc_tpu:$RTL"; do
        top=${t%%:*}; files=${t#*:}
        echo "# cmd: verilator --lint-only --timing -Wno-INITIALDLY $files tests/tpu/$top.v --top-module $top"
        if verilator --lint-only --timing -Wno-INITIALDLY $files tests/tpu/$top.v --top-module $top; then
            echo "LINT_TB_OK $top"
        else
            echo "LINT_TB_FAIL $top"
        fi
    done
} > "$LOG/lint_tb.log" 2>&1
grep -E '^LINT_TB' "$LOG/lint_tb.log"
if grep -q -E '^LINT_TB_FAIL|%Warning|%Error' "$LOG/lint_tb.log"; then fail "TB lint not clean"; fi

# ---------------------------------------------------------------- 3. unit TBs
run_tb() {  # run_tb <name> <log> <iverilog args...> -- <vvp plusargs...>
    local name=$1 log=$2; shift 2
    local iargs=() pargs=()
    while [ $# -gt 0 ] && [ "$1" != "--" ]; do iargs+=("$1"); shift; done
    [ $# -gt 0 ] && shift
    pargs=("$@")
    {
        echo "# input revision: $REV"
        echo "# cmd: iverilog -g2005 -Wall ${iargs[*]} -o $B/$name.vvp && vvp -n $B/$name.vvp ${pargs[*]}"
        set +e
        iverilog -g2005 -Wall "${iargs[@]}" -o "$B/$name.vvp" && vvp -n "$B/$name.vvp" "${pargs[@]}"
        echo "SIM_EXIT=$?"
        set -e
    } > "$log" 2>&1
}

step "3. unit testbenches"
run_tb tb_sc_lfsr8 "$LOG/tb_sc_lfsr8.log" "$D/sc_lfsr8.v" "$D/sc_rng.v" tests/tpu/tb_sc_lfsr8.v --
require "$LOG/tb_sc_lfsr8.log" '^TEST PASSED$' "tb_sc_lfsr8 TEST PASSED"
require "$LOG/tb_sc_lfsr8.log" '^SIM_EXIT=0$' "tb_sc_lfsr8 exit 0"
require "$LOG/tb_sc_lfsr8.log" '^PASS: TC7 SEEDS rev B' "tb_sc_lfsr8 TC7 rev B seed tables"
grep -E '^(PASS|FAIL)' "$LOG/tb_sc_lfsr8.log"
run_tb tb_sc_lfsr8_fault "$LOG/tb_sc_lfsr8_inject_fault.log" -DINJECT_FAULT "$D/sc_lfsr8.v" "$D/sc_rng.v" tests/tpu/tb_sc_lfsr8.v --
require "$LOG/tb_sc_lfsr8_inject_fault.log" '^TEST FAILED$' "tb_sc_lfsr8 negative run TEST FAILED"
require "$LOG/tb_sc_lfsr8_inject_fault.log" '^SIM_EXIT=[1-9]' "tb_sc_lfsr8 negative run non-zero exit"
echo "negative run tb_sc_lfsr8 -DINJECT_FAULT: TEST FAILED as required"

run_tb tb_sc_postproc "$LOG/tb_sc_postproc.log" "$D/sc_postproc.v" tests/tpu/tb_sc_postproc.v --
require "$LOG/tb_sc_postproc.log" '^TEST PASSED$' "tb_sc_postproc TEST PASSED"
require "$LOG/tb_sc_postproc.log" '^SIM_EXIT=0$' "tb_sc_postproc exit 0"
grep -E '^(PASS|FAIL|INFO)' "$LOG/tb_sc_postproc.log"
run_tb tb_sc_postproc_fault "$LOG/tb_sc_postproc_inject_fault.log" -DINJECT_FAULT "$D/sc_postproc.v" tests/tpu/tb_sc_postproc.v --
require "$LOG/tb_sc_postproc_inject_fault.log" '^TEST FAILED$' "tb_sc_postproc negative run TEST FAILED"
require "$LOG/tb_sc_postproc_inject_fault.log" '^SIM_EXIT=[1-9]' "tb_sc_postproc negative run non-zero exit"
echo "negative run tb_sc_postproc -DINJECT_FAULT: TEST FAILED as required"

run_tb tb_sc_lane_array "$LOG/tb_sc_lane_array.log" "$D/sc_lane_array.v" tests/tpu/tb_sc_lane_array.v --
require "$LOG/tb_sc_lane_array.log" '^TEST PASSED$' "tb_sc_lane_array TEST PASSED"
require "$LOG/tb_sc_lane_array.log" '^SIM_EXIT=0$' "tb_sc_lane_array exit 0"
grep -E '^(PASS|FAIL)' "$LOG/tb_sc_lane_array.log"
run_tb tb_sc_lane_array_fault "$LOG/tb_sc_lane_array_inject_fault.log" -DINJECT_FAULT "$D/sc_lane_array.v" tests/tpu/tb_sc_lane_array.v --
require "$LOG/tb_sc_lane_array_inject_fault.log" '^TEST FAILED$' "tb_sc_lane_array negative run TEST FAILED"
require "$LOG/tb_sc_lane_array_inject_fault.log" '^SIM_EXIT=[1-9]' "tb_sc_lane_array negative run non-zero exit"
echo "negative run tb_sc_lane_array -DINJECT_FAULT: TEST FAILED as required"

# ---------------------------------------------------------------- 4. system TB
step "4. tb_sc_tpu: directed tests + golden vectors (SW-01a), RNG_MODE 0/1/2"
for m in 0 1 2; do
    VECS=()
    n=1
    if [ "$QUICK" != 1 ]; then VECS+=("+VEC$n=$DATA/tpu_vectors_mode$m.txt"); n=$((n+1)); fi
    if [ "$m" = 1 ]; then
        VECS+=("+VEC$n=$DATA/tpu_vectors_K4_mode1.txt");  n=$((n+1))
        VECS+=("+VEC$n=$DATA/tpu_vectors_K10_mode1.txt"); n=$((n+1))
    fi
    VECS+=("+VEC$n=$DATA/tpu_vectors_corner_mode$m.txt"); n=$((n+1))
    VECS+=("+VEC$n=sim/tpu/vectors/tpu_vectors_sweep_mode$m.txt")
    for f in "${VECS[@]}"; do [ -s "${f#*=}" ] || fail "vector file ${f#*=} missing"; done
    # Rev B guard (RTL-SOC): every golden file must carry the "# spec_rev B"
    # header of SW-02 (sim/data/README.md), so stale rev-A vectors cannot pass.
    for f in "${VECS[@]}" "+TRACE=$DATA/tpu_rng_trace_mode$m.txt"; do
        grep -q -x '# spec_rev B' "${f#*=}" || fail "${f#*=} has no '# spec_rev B' header (rev A vectors?)"
    done
    L="$LOG/tb_sc_tpu_mode$m.log"
    run_tb tb_sc_tpu_m$m "$L" -P tb_sc_tpu.RNG_MODE=$m $RTL tests/tpu/tb_sc_tpu.v -- \
        +DATA=$DATA +DIRECTED +CLAMP "${VECS[@]}"
    # Record the vector files' checksums next to the result.
    for f in "${VECS[@]}"; do sha256sum "${f#*=}" >> "$L"; done
    grep -E '^(PASS|FAIL|INFO|TEST)' "$L"
    require "$L" '^TEST PASSED$' "tb_sc_tpu mode $m TEST PASSED"
    require "$L" '^SIM_EXIT=0$' "tb_sc_tpu mode $m exit 0"
    require "$L" 'mismatching inferences 0, mismatching fields 0$' "tb_sc_tpu mode $m zero mismatches"
    if grep -q '^FAIL' "$L"; then fail "FAIL lines in $L"; fi
done

# ---------------------------------------------------------------- 4b. init files
step "4b. tb_sc_tpu D12: \$readmemh init files (INIT_FILES=1), RNG_MODE 0/1/2"
for m in 0 1 2; do
    L="$LOG/tb_sc_tpu_init_mode$m.log"
    run_tb tb_sc_tpu_init_m$m "$L" -P tb_sc_tpu.RNG_MODE=$m -P tb_sc_tpu.INIT_FILES=1 $RTL tests/tpu/tb_sc_tpu.v -- \
        +DATA=$DATA +INITVEC=$DATA/tpu_vectors_mode$m.txt
    grep -E '^(PASS|FAIL|TEST)' "$L"
    require "$L" '^PASS: D12 ' "D12 PASS mode $m"
    require "$L" '^TEST PASSED$' "tb_sc_tpu init mode $m TEST PASSED"
    require "$L" '^SIM_EXIT=0$' "tb_sc_tpu init mode $m exit 0"
done

# ---------------------------------------------------------------- 5. negative
step "5. tb_sc_tpu negative run (-DINJECT_FAULT must fail)"
L="$LOG/tb_sc_tpu_inject_fault.log"
run_tb tb_sc_tpu_fault "$L" -DINJECT_FAULT -P tb_sc_tpu.RNG_MODE=1 $RTL tests/tpu/tb_sc_tpu.v -- \
    +DATA=$DATA +VEC1=$DATA/tpu_vectors_K4_mode1.txt
grep -E '^(INFO|TEST)|VECFILE' "$L"
require "$L" '^TEST FAILED$' "negative run TEST FAILED"
require "$L" '^SIM_EXIT=[1-9]' "negative run non-zero exit"

echo
echo "SIM_TPU ALL PASSED (revision $REV)"
