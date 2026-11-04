#!/usr/bin/env bash
# =============================================================================
# tests/smoke/dsp/run_dsp_smoke.sh - ST-FPGA-02: smoke test of the Gowin DSP
#                                    route (fpga-engineer, CR-001 plan step 1)
#
# Steps (each logged under logs/tpu_det/dsp_smoke_*.log):
#   1 lint    verilator --lint-only -Wall on the smoke RTL
#   2 rtl     iverilog RTL simulation of tb_dsp_smoke (+ INJECT_FAULT negative run)
#   3 synth   yowasp-yosys synth_gowin of dsp_smoke_top (board wrapper), stat:
#             is the multiplier mapped to MULT9X9 / MULT18X18 / MULTALU*?
#   4 gate    synth_gowin -noiopads -json (same flow as P&R) of dsp_smoke_mac,
#             write_verilog -noattr -> netlist ->
#             iverilog with Yosys cells_sim.v + MULT9X9 model -> same TB
#   5 pnr     nextpnr-himbaechel-gowin, GW1NR-LV9QN88PC6/I5, 27 MHz, seed 1
#   6 pack    gowin_pack -> bitstream (route proof only; never flashed)
#   7 probe   dsp_timing_probe built with and without DSPs: is the timer
#             analysing paths through MULT9X9?
# Usage : bash tests/smoke/dsp/run_dsp_smoke.sh      (from anywhere)
# NOTE  : YoWASP tools only see the project tree -> relative paths from ROOT.
# =============================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source .venv/bin/activate

L=logs/tpu_det
B=sim/tpu_det/build/dsp_smoke
D=tests/smoke/dsp
mkdir -p "$L" "$B"
REV="$(git rev-parse --short HEAD)"
[ -n "$(git status --porcelain -- $D 2>/dev/null)" ] && REV="${REV}-dirty"
YSHARE="$(python -c 'import yowasp_yosys,os;print(os.path.join(os.path.dirname(yowasp_yosys.__file__),"share"))')"
DEV="--device GW1NR-LV9QN88PC6/I5 --vopt family=GW1N-9C --vopt cst=design/constraints/tangnano9k.cst --freq 27 --threads 1"
fail() { echo "DSP_SMOKE FAIL: $*"; exit 1; }
echo "# ST-FPGA-02 DSP smoke, revision $REV, $(date -Is)"

# 1 ---- lint
{
  echo "# cmd: verilator --lint-only -Wall $D/dsp_smoke_mac.v --top-module dsp_smoke_mac ($(verilator --version), rev $REV)"
  verilator --lint-only -Wall $D/dsp_smoke_mac.v --top-module dsp_smoke_mac && echo "LINT_OK dsp_smoke_mac"
  verilator --lint-only -Wall $D/dsp_smoke_mac.v $D/dsp_smoke_top.v --top-module dsp_smoke_top && echo "LINT_OK dsp_smoke_top"
  verilator --lint-only -Wall $D/dsp_timing_probe.v --top-module dsp_timing_probe && echo "LINT_OK dsp_timing_probe"
} > $L/dsp_smoke_lint.log 2>&1 || fail "lint (see $L/dsp_smoke_lint.log)"
grep -c LINT_OK $L/dsp_smoke_lint.log | grep -qx 3 || fail "lint"
grep -q '%Warning' $L/dsp_smoke_lint.log && fail "lint warnings"
echo "1 lint     : $(grep -c LINT_OK $L/dsp_smoke_lint.log) x LINT_OK"

# 2 ---- RTL simulation (+ negative run)
iverilog -g2005 -Wall -o $B/tb_rtl.vvp $D/tb_dsp_smoke.v $D/dsp_smoke_mac.v
{ echo "# cmd: iverilog -g2005 -Wall tb_dsp_smoke.v dsp_smoke_mac.v; vvp -n ($(iverilog -V 2>&1 | sed -n 1p), rev $REV)"; vvp -n $B/tb_rtl.vvp; } > $L/dsp_smoke_tb_rtl.log 2>&1 || fail "RTL sim (see $L/dsp_smoke_tb_rtl.log)"
grep -q '^TEST PASSED' $L/dsp_smoke_tb_rtl.log || fail "RTL sim: no TEST PASSED"
iverilog -g2005 -Wall -DINJECT_FAULT -o $B/tb_rtl_neg.vvp $D/tb_dsp_smoke.v $D/dsp_smoke_mac.v
rc=0; { echo "# negative run: -DINJECT_FAULT (must FAIL)"; vvp -n $B/tb_rtl_neg.vvp; } > $L/dsp_smoke_tb_inject_fault.log 2>&1 || rc=$?
echo "VVP_EXIT=$rc" >> $L/dsp_smoke_tb_inject_fault.log
{ [ $rc -ne 0 ] && grep -q '^TEST FAILED' $L/dsp_smoke_tb_inject_fault.log; } || fail "negative run did not fail"
echo "2 rtl sim  : $(grep -c '^PASS' $L/dsp_smoke_tb_rtl.log) PASS lines, TEST PASSED; inject-fault run exit $rc, TEST FAILED (expected)"

# 3 ---- synthesis of the board wrapper
yowasp-yosys -l $L/dsp_smoke_synth.log -p "read_verilog $D/dsp_smoke_mac.v $D/dsp_smoke_top.v; synth_gowin -top dsp_smoke_top -json $B/dsp_smoke_top.json; stat" > $B/synth_stdout.log 2>&1 || fail "yosys"
grep -q 'End of script' $L/dsp_smoke_synth.log || fail "no End of script"
NM9=$(awk '/=== dsp_smoke_top ===/{f=1} f && $2=="MULT9X9"{print $1; exit}' $L/dsp_smoke_synth.log)
echo "3 synth    : MULT9X9 cells in dsp_smoke_top = ${NM9:-0}"

# 4 ---- post-synthesis (gate-level) simulation of the DSP-mapped core
yowasp-yosys -l $L/dsp_smoke_synth_core.log -p "read_verilog $D/dsp_smoke_mac.v; synth_gowin -noiopads -top dsp_smoke_mac -json $B/dsp_smoke_mac_core.json; write_verilog -noattr $B/dsp_smoke_mac_syn.v; stat" > $B/synth_core_stdout.log 2>&1 || fail "yosys core"
grep -q 'MULT9X9' $B/dsp_smoke_mac_syn.v || fail "core netlist has no MULT9X9"
iverilog -g2005 -o $B/tb_gate.vvp -DNO_SPECIFY $D/tb_dsp_smoke.v $B/dsp_smoke_mac_syn.v $D/gowin_mult_models.v "$YSHARE/gowin/cells_sim.v" > $B/gate_compile.log 2>&1 || { cat $B/gate_compile.log; fail "gate compile"; }
{ echo "# cmd: iverilog tb_dsp_smoke.v + synth_gowin netlist dsp_smoke_mac_syn.v + gowin_mult_models.v + yowasp share/gowin/cells_sim.v (rev $REV)"; vvp -n $B/tb_gate.vvp; } > $L/dsp_smoke_tb_gate.log 2>&1 || fail "gate sim (see $L/dsp_smoke_tb_gate.log)"
grep -q '^TEST PASSED' $L/dsp_smoke_tb_gate.log || fail "gate sim: no TEST PASSED"
echo "4 gate sim : netlist MULT9X9 x $(grep -c 'MULT9X9 ' $B/dsp_smoke_mac_syn.v), $(grep -c '^PASS' $L/dsp_smoke_tb_gate.log) PASS lines, TEST PASSED"

# 5 ---- P&R
PL=$L/dsp_smoke_pnr.log
echo "# cmd: yowasp-nextpnr-himbaechel-gowin --json $B/dsp_smoke_top.json --write $B/dsp_smoke_top_pnr.json $DEV --report $B/dsp_smoke_report.json --seed 1 (rev $REV)" > $PL
rc=0; yowasp-nextpnr-himbaechel-gowin --json $B/dsp_smoke_top.json --write $B/dsp_smoke_top_pnr.json $DEV --report $B/dsp_smoke_report.json --seed 1 >> $PL 2>&1 || rc=$?
echo "PNR_EXIT=$rc" >> $PL
[ $rc -eq 0 ] || fail "nextpnr exit $rc"
echo "5 pnr      : $(grep -E 'MULT9X9:' $PL | sed -n 1p | sed 's/Info://;s/\t/ /g') ; $(grep 'Max frequency' $PL | tail -n 1 | sed 's/Info: //')"

# 6 ---- bitstream
rc=0; gowin_pack -d GW1N-9C -o $B/dsp_smoke_top.fs $B/dsp_smoke_top_pnr.json > $L/dsp_smoke_pack.log 2>&1 || rc=$?
echo "PACK_EXIT=$rc" >> $L/dsp_smoke_pack.log
[ $rc -eq 0 ] || fail "gowin_pack exit $rc"
FS_SHA=$(sha256sum $B/dsp_smoke_top.fs | cut -d' ' -f1)
echo "bitstream $B/dsp_smoke_top.fs $(stat -c %s $B/dsp_smoke_top.fs) bytes sha256 $FS_SHA" >> $L/dsp_smoke_pack.log
echo "6 pack     : exit 0, $(stat -c %s $B/dsp_smoke_top.fs) bytes, sha256 ${FS_SHA:0:16}..."

# 7 ---- timing probe: DSP vs LUT build of two multipliers in series
for opt in dsp nodsp; do
  o=""; [ $opt = nodsp ] && o="-nodsp"
  yowasp-yosys -l $L/dsp_probe_${opt}_synth.log -p "read_verilog $D/dsp_timing_probe.v; synth_gowin $o -top dsp_timing_probe -json $B/probe_$opt.json; stat" > $B/probe_${opt}_stdout.log 2>&1 || fail "probe synth $opt"
  PL=$L/dsp_probe_${opt}_pnr.log
  echo "# cmd: yowasp-nextpnr-himbaechel-gowin --json $B/probe_$opt.json $DEV --seed 1 (synth_gowin $o, rev $REV)" > $PL
  rc=0; yowasp-nextpnr-himbaechel-gowin --json $B/probe_$opt.json --write $B/probe_${opt}_pnr.json $DEV --report $B/probe_${opt}_report.json --seed 1 >> $PL 2>&1 || rc=$?
  echo "PNR_EXIT=$rc" >> $PL
  m=$(awk '/=== dsp_timing_probe ===/{f=1} f && $2=="MULT9X9"{print $1; exit}' $L/dsp_probe_${opt}_synth.log)
  # Start and end cell of the routed critical path (last report in the log):
  # with DSPs the a/b/c -> q path should appear here if it were timed.
  awk '/Critical path report for clock/{f=1;buf=""} f{buf=buf $0 "\n"} /Max frequency/{if(f){last=buf}; f=0} END{printf "%s", last}' $PL > $B/probe_${opt}_critical_path.txt
  cps=$(grep -m1 'clk-to-q' $B/probe_${opt}_critical_path.txt | awk '{print $NF}' | cut -c1-40)
  cpe=$(grep 'setup' $B/probe_${opt}_critical_path.txt | tail -n 1 | awk '{print $NF}' | cut -c1-40)
  cpt=$(grep -E '^Info: [0-9.]+ ns logic' $B/probe_${opt}_critical_path.txt | sed 's/Info: //')
  echo "7 probe $opt: MULT9X9=${m:-0}, $(grep 'Max frequency' $PL | tail -n 1 | sed 's/Info: //'); critical path $cps -> $cpe ($cpt)"
  { echo "# critical path (routed) of probe_$opt:"; cat $B/probe_${opt}_critical_path.txt; } >> $PL
done
echo "DSP_SMOKE DONE (revision $REV)"
