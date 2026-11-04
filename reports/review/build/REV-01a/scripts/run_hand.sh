#!/usr/bin/env bash
# REV-01a: run the reviewer hand programs on tests/cpu/tb_rv32i_core.v with RTL dir $2.
# Usage: run_hand.sh <outdir> <rtl_dir>
set -uo pipefail
cd /home/user/tpu-e-cpu
OUT=$1; R=$2; D=reports/review/build/REV-01a/hand/data
mkdir -p "$OUT"
iverilog -g2005 -Wall -o "$OUT/tb.vvp" $R/rv32i_core.v $R/rv32i_decode.v $R/rv32i_alu.v $R/rv32i_regfile.v tests/cpu/tb_rv32i_core.v > "$OUT/compile.log" 2>&1 || exit 4
n=0; p=0; failed=""
for s in $D/*.sig; do t=$(basename $s .sig); h=$D/$t.hex
  for cfg in "+ws=0" "+ws=1" "+ws=3" "+ws=0 +rand_stall=1 +seed=7"; do
    lf="$OUT/${t}__$(echo $cfg | tr -d '+= ').log"
    vvp -n "$OUT/tb.vvp" +prog=$h +sig=$D/$t.sig +meta=$D/$t.tbmeta.hex +name=$t $cfg > "$lf" 2>&1; rc=$?
    n=$((n+1)); if [ $rc -eq 0 ] && grep -q '^TEST PASSED$' "$lf"; then p=$((p+1)); else failed="$failed $t"; fi
  done
done
echo "HAND RUNS $p/$n PASS; failed:$(echo $failed | tr ' ' '\n' | sort -u | tr '\n' ' ')"
