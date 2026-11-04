#!/usr/bin/env bash
# =============================================================================
# scripts/sim_soc.sh  -  RTL-SOC lint + simulation regression (fpga-engineer)
#
# Steps (each writes a log under logs/soc/ and is checked for its decisive
# line - an exit code 0 alone is never taken as a pass):
#   1. RTL lint: verilator --lint-only -Wall on soc_top (whole SoC: CPU + TPU +
#      SoC blocks) and on soc_bus / soc_ram / soc_periph alone   -> lint_rtl.log
#   2. TB lint : verilator --lint-only --timing (default warning set) on
#      tests/soc/tb_soc.v and tests/soc/tb_soc_bfm.v              -> lint_tb.log
#   3. Expectation file for the demo: sim/data/soc_expected.json (SW-02,
#      golden model) -> sim/soc/build/soc_expected.hex. Cross-checks: spec_rev
#      B; sha256 of input/weights/bias.hex equal to the ones recorded in the
#      JSON; HIDDEN/SCORE/RESULT equal to the test-position-0 line of
#      sim/data/tpu_vectors_mode2.txt (K=8, s=0, mode 2). If the JSON is
#      missing, the expectation is taken from that vector line instead
#      (documented in the log).                                 -> expected.log
#   4. tb_soc demo run (soc_demo_prog.hex on the real CPU + TPU)  -> tb_soc_demo.log
#   5. tb_soc on the SW-01b CPU suite: dir_mmio (required) and, unless
#      CPU_ALL=0, all 44 tests (each test compiled with its .hex as the RAM
#      INIT_FILE)                                                 -> cpu/<test>.log
#   6. tb_soc_bfm directed fabric tests (registers, map, unmapped, UART bytes,
#      LED values)                                                -> tb_soc_bfm.log
#   7. Negative runs, all MUST end in TEST FAILED with a non-zero exit:
#      tb_soc -DINJECT_FAULT (expected SCORE[0] corrupted), tb_soc with the DUT
#      UART divider 240 (bit-timing checker), tb_soc -DINJECT_PROTO_FAULT
#      (protocol checker), tb_soc_bfm -DINJECT_FAULT (LED polarity)
#                                                                 -> neg_*.log
# Usage   : bash scripts/sim_soc.sh        (~2 min; CPU_ALL=0 for ~20 s)
# Products: sim/soc/build/ (gitignored)
# Exit    : 0 only if every step passed.
# =============================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"

LOG=logs/soc
B=sim/soc/build
mkdir -p "$LOG/cpu" "$B/meta"
CPU_ALL=${CPU_ALL:-1}
T=design/rtl/tpu; C=design/rtl/cpu; S=design/rtl/soc
CPU_RTL="$C/rv32i_core.v $C/rv32i_decode.v $C/rv32i_alu.v $C/rv32i_regfile.v"
TPU_RTL="$T/sc_lfsr8.v $T/sc_rng.v $T/sc_lane_array.v $T/sc_postproc.v $T/sc_tpu_ctrl.v $T/sc_tpu.v"
SOC_RTL="$CPU_RTL $TPU_RTL $S/soc_bus.v $S/soc_ram.v $S/soc_periph.v $S/soc_top.v"
DATA=sim/data

REV="$(git rev-parse --short HEAD 2>/dev/null || echo no-commit)"
if [ -n "$(git status --porcelain -- design/rtl tests/soc sim/data scripts/sim_soc.sh 2>/dev/null)" ]; then REV="${REV}-dirty"; fi

fail() { echo "SIM_SOC FAIL: $*" >&2; exit 1; }
require() { grep -E -q "$2" "$1" || fail "'$3' not found in $1"; }
step() { printf '\n==== %s ====\n' "$*"; }

{
    echo "# RTL-SOC simulation regression  $(date -Is)  input revision: $REV"
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
        # shellcheck disable=SC2086
        if verilator --lint-only -Wall $files --top-module "$top" "$@"; then echo "LINT_OK $top $*"; else echo "LINT_FAIL $top $*"; fi
    }
    lint soc_top    "$SOC_RTL"
    lint soc_bus    "$S/soc_bus.v"
    lint soc_ram    "$S/soc_ram.v"
    lint soc_periph "$S/soc_periph.v"
    lint soc_periph "$S/soc_periph.v" -GUART_DIV=240
} > "$LOG/lint_rtl.log" 2>&1
grep -E '^LINT_' "$LOG/lint_rtl.log"
if grep -q -E '^LINT_FAIL|%Warning|%Error' "$LOG/lint_rtl.log"; then fail "RTL lint not clean"; fi
[ "$(grep -c '^LINT_OK' "$LOG/lint_rtl.log")" -eq 5 ] || fail "expected 5 LINT_OK lines"

# ---------------------------------------------------------------- 2. TB lint
step "2. TB lint (verilator --timing, default warnings)"
{
    echo "# input revision: $REV"
    for top in tb_soc tb_soc_bfm; do
        echo "# cmd: verilator --lint-only --timing $SOC_RTL tests/soc/$top.v --top-module $top"
        # shellcheck disable=SC2086
        if verilator --lint-only --timing $SOC_RTL tests/soc/$top.v --top-module $top; then echo "LINT_TB_OK $top"; else echo "LINT_TB_FAIL $top"; fi
    done
} > "$LOG/lint_tb.log" 2>&1
grep -E '^LINT_TB' "$LOG/lint_tb.log"
if grep -q -E '^LINT_TB_FAIL|%Warning|%Error' "$LOG/lint_tb.log"; then fail "TB lint not clean"; fi

# ---------------------------------------------------------------- 3. expectation
step "3. demo expectation (sim/data/soc_expected.json, SW-02)"
python3 -I - "$DATA" "$B/soc_expected.hex" > "$LOG/expected.log" 2>&1 <<'PY' || { cat "$LOG/expected.log"; fail "expectation generation"; }
"""Build sim/soc/build/soc_expected.hex for tests/soc/tb_soc.v.
Layout (one 32-bit hex word per line): 0 RESULT, 1 TOHOST, 2 LED, 3 K,
4..7 HIDDEN words, 8..23 SCORE words, 24 number of UART bytes, 25.. bytes,
zero padding to 32 words."""
import hashlib, json, sys
from pathlib import Path
data, out = Path(sys.argv[1]), Path(sys.argv[2])
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()

# Golden line of the vector file: pset 0, test position 0, K=8, s=0, mode 2.
vf = data / "tpu_vectors_mode2.txt"
lines = vf.read_text().splitlines()
print(f"vector file {vf} sha256 {sha(vf)}")
print("vector file spec_rev header:", "present" if any(l.strip() == "# spec_rev B" for l in lines[:5]) else "MISSING")
if not any(l.strip() == "# spec_rev B" for l in lines[:5]):
    sys.exit("vector file is not spec_rev B")
vec = None
for l in lines:
    if not l.strip() or l.startswith("#"):
        continue
    f = [int(x, 16) for x in l.split()]
    if f[0] == 0 and f[4] == 0:
        vec = f
        break
assert vec is not None and vec[1] == 8 and vec[2] == 0 and vec[3] == 2, "vector line idx 0 not K=8 s=0 mode 2"
v_in, v_hid, v_sc, v_res = vec[6:22], vec[22:26], vec[26:42], vec[42]
inp = [int(l.split("//")[0], 16) for l in (data / "input.hex").read_text().splitlines() if l.split("//")[0].strip()]
assert inp == v_in, "input.hex != INPUT words of vector idx 0"
print("input.hex == INPUT words of the idx-0 vector: yes")

j = data / "soc_expected.json"
if j.exists():
    e = json.loads(j.read_text())
    print(f"source: {j} (sha256 {sha(j)}), generator {e.get('generator')}, git_rev {e.get('git_rev')}")
    assert e["spec_rev"] == "B", "soc_expected.json is not spec_rev B"
    assert e["K"] == 8 and e["act_shift_s"] == 0 and e["rng_mode"] == 2
    for k, fname in (("input_sha256", "input.hex"), ("weights_sha256", "weights.hex"), ("bias_sha256", "bias.hex")):
        assert e[k] == sha(data / fname), f"{fname} sha256 differs from soc_expected.json"
        print(f"{fname} sha256 matches soc_expected.json")
    res, tohost, led, K = e["result"], e["expected_tohost"], e["expected_led"], e["K"]
    hid = [int(x, 16) for x in e["hidden_words"]]
    sc = [int(x, 16) & 0xFFFFFFFF for x in e["score_words"]]
    uart = [int(x, 16) for x in e["expected_uart_bytes"]]
    assert hid == v_hid and sc == v_sc and res == v_res, "soc_expected.json != vector file line idx 0"
    print("cross-check soc_expected.json == tpu_vectors_mode2.txt idx 0 (HIDDEN, SCORE, RESULT): OK")
else:
    print("SOURCE: soc_expected.json ABSENT -> expectation from tpu_vectors_mode2.txt idx 0 (documented fallback)")
    res, tohost, led, K = v_res, 1, v_res, 8
    hid, sc, uart = v_hid, v_sc, [0x30 + v_res, 0x0A]
assert uart == [0x30 + res, 0x0A] and led == res and tohost == 1
w = [res, tohost, led, K] + hid + sc + [len(uart)] + uart
w += [0] * (32 - len(w))
out.write_text("".join(f"{x & 0xFFFFFFFF:08x}\n" for x in w))
print(f"EXPECTED RESULT={res} LED={led} TOHOST={tohost} K={K} UART={[hex(u) for u in uart]}")
print(f"EXPECTED HIDDEN={[hex(x) for x in hid]}")
print(f"EXPECTED SCORE={[x - (1 << 32) if x >> 31 else x for x in sc]}")
params = e.get("params_expected", "0x02020810") if j.exists() else "0x02020810"
print(f"PARAMS_EXPECTED={int(params, 16):08x}")
print(f"wrote {out}")
print("EXPECTATION_OK")
PY
cat "$LOG/expected.log"
require "$LOG/expected.log" '^EXPECTATION_OK$' "expectation file"

# ---------------------------------------------------------------- helpers
run_sim() {  # run_sim <log> <iverilog args...> -- <vvp plusargs...>
    local log=$1; shift
    local iargs=() pargs=()
    while [ $# -gt 0 ] && [ "$1" != "--" ]; do iargs+=("$1"); shift; done
    [ $# -gt 0 ] && shift
    pargs=("$@")
    local vvp="$B/$(basename "$log" .log).vvp"
    {
        echo "# input revision: $REV"
        echo "# cmd: iverilog -g2005 -Wall ${iargs[*]} -o $vvp && vvp -n $vvp ${pargs[*]}"
        set +e
        iverilog -g2005 -Wall "${iargs[@]}" -o "$vvp" && vvp -n "$vvp" "${pargs[@]}"
        echo "SIM_EXIT=$?"
        set -e
    } > "$log" 2>&1
}
must_pass() {  # must_pass <log> <what>
    require "$1" '^TEST PASSED$' "$2 TEST PASSED"
    require "$1" '^SIM_EXIT=0$' "$2 exit 0"
    if grep -q '^FAIL' "$1"; then fail "FAIL lines in $1"; fi
}
must_fail() {  # must_fail <log> <what>
    require "$1" '^TEST FAILED$' "$2 TEST FAILED"
    require "$1" '^SIM_EXIT=[1-9]' "$2 non-zero exit"
    echo "negative run $2: TEST FAILED as required"
}

# ---------------------------------------------------------------- 4. demo
step "4. tb_soc: SoC demo program on the real CPU + TPU (rev B, RNG_MODE 2)"
L="$LOG/tb_soc_demo.log"
run_sim "$L" $SOC_RTL tests/soc/tb_soc.v -- +MODE=demo +EXP=$B/soc_expected.hex
sha256sum "$DATA/soc_demo_prog.hex" "$DATA/weights.hex" "$DATA/bias.hex" "$DATA/input.hex" "$DATA/soc_expected.json" >> "$L" 2>/dev/null || true
grep -E '^(PASS|FAIL|INFO: end|INFO: instr|INFO: bus|TEST)' "$L"
must_pass "$L" "tb_soc demo"

# ---------------------------------------------------------------- 5. CPU suite
step "5. tb_soc: SW-01b CPU tests on the SoC"
python scripts/cpu_meta_to_tb.py "$DATA/cpu_tests" "$B/meta" > "$LOG/cpu_meta.log" 2>&1 || { cat "$LOG/cpu_meta.log"; fail "cpu_meta_to_tb"; }
if [ "$CPU_ALL" = 1 ]; then TESTS=$(cat "$DATA/cpu_tests/index.txt"); else TESTS=dir_mmio; fi
npass=0; ntot=0
: > "$LOG/cpu_suite_summary.log"
for t in $TESTS; do
    L="$LOG/cpu/$t.log"
    run_sim "$L" -P "tb_soc.PROG_HEX=\"$DATA/cpu_tests/$t.hex\"" $SOC_RTL tests/soc/tb_soc.v -- \
        +MODE=cpu +META=$B/meta/$t.tbmeta.hex +SIG=$DATA/cpu_tests/$t.sig
    ntot=$((ntot + 1))
    if grep -q '^TEST PASSED$' "$L" && grep -q '^SIM_EXIT=0$' "$L" && ! grep -q '^FAIL' "$L"; then
        npass=$((npass + 1)); echo "PASS $t" >> "$LOG/cpu_suite_summary.log"
    else
        echo "FAIL $t" >> "$LOG/cpu_suite_summary.log"
    fi
done
echo "# CPU tests on the SoC: $npass / $ntot PASS" | tee -a "$LOG/cpu_suite_summary.log"
grep -E '^(PASS|FAIL|INFO)' "$LOG/cpu/dir_mmio.log"
must_pass "$LOG/cpu/dir_mmio.log" "tb_soc dir_mmio"
[ "$npass" -eq "$ntot" ] || fail "CPU suite on the SoC: $npass / $ntot"

# ---------------------------------------------------------------- 6. BFM
step "6. tb_soc_bfm: directed fabric tests inside soc_top"
L="$LOG/tb_soc_bfm.log"
PEXP="$(sed -n 's/^PARAMS_EXPECTED=//p' "$LOG/expected.log")"
run_sim "$L" -P "tb_soc_bfm.EXP_PARAMS=32'h$PEXP" $SOC_RTL tests/soc/tb_soc_bfm.v --
grep -E '^(PASS|FAIL|TEST)' "$L"
must_pass "$L" "tb_soc_bfm"

# ---------------------------------------------------------------- 7. negative
step "7. negative runs (must fail)"
run_sim "$LOG/neg_tb_soc_inject_fault.log" -DINJECT_FAULT $SOC_RTL tests/soc/tb_soc.v -- +MODE=demo +EXP=$B/soc_expected.hex
grep -E '^(FAIL|NOTE)' "$LOG/neg_tb_soc_inject_fault.log" || true
must_fail "$LOG/neg_tb_soc_inject_fault.log" "tb_soc -DINJECT_FAULT"
run_sim "$LOG/neg_tb_soc_uart_div240.log" -P tb_soc.UART_DIV=240 $SOC_RTL tests/soc/tb_soc.v -- +MODE=demo +EXP=$B/soc_expected.hex
grep -E '^FAIL: (U1|tx_busy)' "$LOG/neg_tb_soc_uart_div240.log" || true
must_fail "$LOG/neg_tb_soc_uart_div240.log" "tb_soc UART_DIV=240"
run_sim "$LOG/neg_tb_soc_proto_fault.log" -DINJECT_PROTO_FAULT $SOC_RTL tests/soc/tb_soc.v -- +MODE=demo +EXP=$B/soc_expected.hex
grep -E '^PROTOCOL VIOLATION' "$LOG/neg_tb_soc_proto_fault.log" || true
must_fail "$LOG/neg_tb_soc_proto_fault.log" "tb_soc -DINJECT_PROTO_FAULT"
run_sim "$LOG/neg_tb_soc_bfm_inject_fault.log" -DINJECT_FAULT $SOC_RTL tests/soc/tb_soc_bfm.v --
must_fail "$LOG/neg_tb_soc_bfm_inject_fault.log" "tb_soc_bfm -DINJECT_FAULT"

echo
echo "SIM_SOC ALL PASSED (revision $REV)"
