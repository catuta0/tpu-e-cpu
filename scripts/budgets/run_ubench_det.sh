#!/usr/bin/env bash
# =============================================================================
# File    : scripts/budgets/run_ubench_det.sh
# Purpose : REQ-03 (CR-001) budget micro-benchmarks for the deterministic int8
#           TPU (rev D, ARCHITECTURE.md 14). Synthesises and places & routes the
#           calibration bench scripts/budgets/ubench/dt_mac_ubench.v for
#           GW1NR-LV9QN88PC6/I5 (family GW1N-9C) with the project open-source
#           flow, once with DSP inference (default synth_gowin) and once with
#           -nodsp (multipliers in LUT/ALU logic), for NL = 16 and NL = 8 lanes,
#           and prints the nextpnr "Device utilisation" and "Max frequency"
#           lines. Results are TOOL ESTIMATES used as budget inputs; they are
#           not project RTL results, not a DSP smoke test of the bitstream flow
#           (gowin_pack is not run; that is task ST-FPGA-02) and not hardware
#           measurements.
# Usage   : bash scripts/budgets/run_ubench_det.sh [bench ...] \
#             > scripts/budgets/logs/ubench_det_run1.log 2>&1
#           (no argument = all benches; PNR_TIMEOUT seconds per nextpnr run,
#           default 900; SEEDS default "1 2 3")
# Outputs : build products only under scripts/budgets/build/ (git-ignored).
# =============================================================================
set -u
ONLY="$*"                      # optional list of bench names to run
PNR_TIMEOUT=${PNR_TIMEOUT:-900}
SEEDS=${SEEDS:-"1 2 3"}
ROOT=/home/user/tpu-e-cpu
B=$ROOT/scripts/budgets/build
U=$ROOT/scripts/budgets/ubench
source $ROOT/.venv/bin/activate
mkdir -p $B
cd $B

echo "# command: PNR_TIMEOUT=$PNR_TIMEOUT SEEDS=\"$SEEDS\" bash scripts/budgets/run_ubench_det.sh $ONLY"
echo "# date: $(date -u +%FT%TZ)  revision: $(cd $ROOT && git rev-parse --short HEAD)$(cd $ROOT && git diff --quiet HEAD -- 2>/dev/null || echo -dirty)"
echo "# bench sha256: $(sha256sum $U/dt_mac_ubench.v | cut -d' ' -f1)"
echo "# yosys: $(yowasp-yosys -V 2>&1 | head -1)"
echo "# nextpnr: $(yowasp-nextpnr-himbaechel-gowin --version 2>&1 | head -1)"

# Same board-pin constraint file as run_ubench.sh (pins from tangnano9k.cst).
cat > $B/ubench_det.cst <<'CST'
IO_LOC  "clk" 52;
IO_PORT "clk" IO_TYPE=LVCMOS33 PULL_MODE=UP;
IO_LOC  "btn_s1_n" 3;
IO_LOC  "we" 4;
IO_LOC  "xwe" 18;
IO_LOC  "start" 10;
IO_LOC  "run" 11;
IO_LOC  "clr" 13;
IO_LOC  "dout_x" 17;
CST

run() {   # run <name> <synth_gowin extra flags> <chparam list>
    local name=$1 sflags=$2 chp=$3 rc=0
    echo
    echo "================ $name (synth_gowin -nowidelut $sflags; chparam $chp) ================"
    if [ -n "$ONLY" ] && ! echo " $ONLY " | grep -q " $name "; then echo "(skipped)"; return; fi
    yowasp-yosys -l $B/$name.yosys.log -p "read_verilog $U/dt_mac_ubench.v; chparam $chp dt_ubench_top; synth_gowin -nowidelut $sflags -top dt_ubench_top -json $B/$name.json" >/dev/null 2>&1 || rc=$?
    echo "yosys exit=$rc"
    # Yosys cell statistics of interest (multipliers, memories, LUTs, ALUs)
    grep -E "^[[:space:]]+[0-9]+[[:space:]]+(MULT9X9|MULT18X18|MULT36X36|SDPB|SDPX9B|DPB|DPX9B|SP|SPX9|RAM16SDP4|ALU|LUT1|LUT2|LUT3|LUT4|DFF[A-Z]*)$" $B/$name.yosys.log | tail -40 | sed 's/^/  yosys: /'
    for seed in $SEEDS; do
        rc=0
        timeout ${PNR_TIMEOUT} yowasp-nextpnr-himbaechel-gowin --json $B/$name.json --write $B/${name}_pnr.json \
            --device GW1NR-LV9QN88PC6/I5 --vopt family=GW1N-9C --vopt cst=$B/ubench_det.cst \
            --freq 27 --seed $seed > $B/${name}_s$seed.pnr.log 2>&1 || rc=$?
        [ $rc = 124 ] && echo "  seed $seed: nextpnr TIMEOUT after ${PNR_TIMEOUT} s (no result)"
        if [ $seed = 1 ]; then
            grep -E "^Info:[[:space:]]+(LUT4|ALU|DFF|RAM16SDP4|BSRAM|IOB|MULT18X18|MULT9X9|MULT36X36):" $B/${name}_s1.pnr.log | sed 's/^Info:[[:space:]]*/  /'
            grep -E "^ERROR" $B/${name}_s1.pnr.log | head -3 | sed 's/^/  /'
        fi
        echo "  seed $seed nextpnr exit=$rc :: $(grep 'Max frequency for clock' $B/${name}_s$seed.pnr.log | tail -1 | sed 's/^Info: //')"
    done
}

run dt_nl16_dsp  ""       "-set NL 16 -set PIPE 1"
run dt_nl8_dsp   ""       "-set NL 8 -set PIPE 1"
run dt_nl16_lut  "-nodsp" "-set NL 16 -set PIPE 1"
run dt_nl8_lut   "-nodsp" "-set NL 8 -set PIPE 1"
echo
echo "# done"
