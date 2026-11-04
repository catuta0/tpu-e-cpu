#!/usr/bin/env bash
# REV-01a reviewer copy of scripts/sim_soc.sh steps 3, 4, 5 (subset), 6; outputs
# only under the given out dir.  Usage: run_soc.sh <outdir> <soc_rtl_dir> <cpu_rtl_dir> [cpu tests...]
set -uo pipefail
cd /home/user/tpu-e-cpu; source .venv/bin/activate
OUT=$1; S=$2; C=$3; shift 3; TESTS="${*:-dir_mmio}"
T=design/rtl/tpu; DATA=sim/data; B=reports/review/build/REV-01a
mkdir -p "$OUT/meta"
CPU_RTL="$C/rv32i_core.v $C/rv32i_decode.v $C/rv32i_alu.v $C/rv32i_regfile.v"
TPU_RTL="$T/sc_lfsr8.v $T/sc_rng.v $T/sc_lane_array.v $T/sc_postproc.v $T/sc_tpu_ctrl.v $T/sc_tpu.v"
SOC_RTL="$CPU_RTL $TPU_RTL $S/soc_bus.v $S/soc_ram.v $S/soc_periph.v $S/soc_top.v"
python3 -I $B/scripts/soc_expected_gen.py "$DATA" "$OUT/soc_expected.hex" C > "$OUT/expected.log" 2>&1
PEXP="$(sed -n 's/^PARAMS_EXPECTED=//p' "$OUT/expected.log")"
python scripts/cpu_meta_to_tb.py "$DATA/cpu_tests" "$OUT/meta" > "$OUT/cpu_meta.log" 2>&1
res() { if grep -q '^TEST PASSED$' "$1" && ! grep -q '^FAIL' "$1"; then echo PASS; else echo FAIL; fi; }
iverilog -g2005 -Wall -o $OUT/demo.vvp $SOC_RTL tests/soc/tb_soc.v > $OUT/demo.log 2>&1 && vvp -n $OUT/demo.vvp +MODE=demo +EXP=$OUT/soc_expected.hex >> $OUT/demo.log 2>&1
echo "demo=$(res $OUT/demo.log)"
iverilog -g2005 -Wall -P "tb_soc_bfm.EXP_PARAMS=32'h$PEXP" -o $OUT/bfm.vvp $SOC_RTL tests/soc/tb_soc_bfm.v > $OUT/bfm.log 2>&1 && vvp -n $OUT/bfm.vvp >> $OUT/bfm.log 2>&1
echo "bfm=$(res $OUT/bfm.log)"
for t in $TESTS; do
  iverilog -g2005 -Wall -P "tb_soc.PROG_HEX=\"$DATA/cpu_tests/$t.hex\"" -o $OUT/cpu_$t.vvp $SOC_RTL tests/soc/tb_soc.v > $OUT/cpu_$t.log 2>&1 && \
    vvp -n $OUT/cpu_$t.vvp +MODE=cpu +META=$OUT/meta/$t.tbmeta.hex +SIG=$DATA/cpu_tests/$t.sig >> $OUT/cpu_$t.log 2>&1
  echo "cpu_$t=$(res $OUT/cpu_$t.log)"
done
