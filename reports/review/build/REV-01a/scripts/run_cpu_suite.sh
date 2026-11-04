#!/usr/bin/env bash
# REV-01a reviewer copy of scripts/sim_cpu.sh steps 2-4 (no lint), outputs only
# under reports/review/build/REV-01a/.  Usage:
#   run_cpu_suite.sh <outdir> <cfgs> <rtl files...>
# Runs every test of sim/data/cpu_tests/index.txt with the given bus configs on
# tests/cpu/tb_rv32i_core.v compiled against the given RTL files.
set -uo pipefail
ROOT=/home/user/tpu-e-cpu
cd "$ROOT"
source .venv/bin/activate
OUT="$1"; shift; CFGS="$1"; shift; RTL="$*"
mkdir -p "$OUT/runs" "$OUT/meta"
python scripts/cpu_meta_to_tb.py sim/data/cpu_tests "$OUT/meta" > "$OUT/meta_convert.log" 2>&1 || { echo META_FAIL; exit 3; }
iverilog -g2005 -Wall -o "$OUT/tb.vvp" $RTL tests/cpu/tb_rv32i_core.v > "$OUT/compile.log" 2>&1 || { echo COMPILE_FAIL; cat "$OUT/compile.log"; exit 4; }
npass=0; nrun=0; idx=0; failed=""
while read -r t; do
  [ -z "$t" ] && continue
  for cfg in $CFGS; do
    case "$cfg" in ws0) a="+ws=0";; ws1) a="+ws=1";; ws3) a="+ws=3";; rand) a="+ws=0 +rand_stall=1 +seed=$((idx+1))";; esac
    lf="$OUT/runs/${t}__${cfg}.log"
    vvp -n "$OUT/tb.vvp" +prog=sim/data/cpu_tests/$t.hex +sig=sim/data/cpu_tests/$t.sig +meta=$OUT/meta/$t.tbmeta.hex +name=$t $a > "$lf" 2>&1
    rc=$?; echo "VVP_EXIT=$rc" >> "$lf"; nrun=$((nrun+1))
    if [ $rc -eq 0 ] && grep -q '^TEST PASSED$' "$lf" && grep -q 'status=PASS .*viol=0$' "$lf"; then npass=$((npass+1)); else failed="$failed $t:$cfg"; fi
  done
  idx=$((idx+1))
done < sim/data/cpu_tests/index.txt
echo "RUNS $npass/$nrun PASS"
echo "FAILED:$failed"
