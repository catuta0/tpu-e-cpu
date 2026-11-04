#!/usr/bin/env bash
# REV-01a: independent re-run of the chosen SoC flow (synth_gowin -nowidelut +
# nextpnr seeds 1..3) at the reviewed revision; outputs only in reports/review/build/REV-01a/pnr.
set -uo pipefail
cd /home/user/tpu-e-cpu; source .venv/bin/activate
O=reports/review/build/REV-01a/pnr; mkdir -p $O
T=design/rtl/tpu; C=design/rtl/cpu; S=design/rtl/soc
RTL="$C/rv32i_core.v $C/rv32i_decode.v $C/rv32i_alu.v $C/rv32i_regfile.v $T/sc_lfsr8.v $T/sc_rng.v $T/sc_lane_array.v $T/sc_postproc.v $T/sc_tpu_ctrl.v $T/sc_tpu.v $S/soc_bus.v $S/soc_ram.v $S/soc_periph.v $S/soc_top.v"
{ echo "rev $(git rev-parse --short HEAD) dirty-paths: $(git status --porcelain -- design sim/data | wc -l)"; yowasp-yosys -V; yowasp-nextpnr-himbaechel-gowin --version 2>&1 | head -1; } > $O/versions.log
yowasp-yosys -l $O/synth_nwl.log -p "read_verilog $RTL; synth_gowin -nowidelut -top soc_top -json $O/soc_top_nwl.json; check; stat" > /dev/null 2>&1
echo "SYNTH done $(date -Is)" >> $O/versions.log
for s in 1 2 3; do
  yowasp-nextpnr-himbaechel-gowin --json $O/soc_top_nwl.json --write $O/pnr_s$s.json --device GW1NR-LV9QN88PC6/I5 --vopt family=GW1N-9C --vopt cst=design/constraints/tangnano9k.cst --freq 27 --report $O/report_s$s.json --seed $s --threads 1 > $O/pnr_nwl_s$s.log 2>&1
  echo "PNR_EXIT=$?" >> $O/pnr_nwl_s$s.log
  echo "PNR s$s done $(date -Is)" >> $O/versions.log
done
