#!/usr/bin/env bash
# =============================================================================
# File    : scripts/budgets/run_ubench.sh
# Purpose : REQ-01 budget micro-benchmarks (systems-engineer). Synthesises and
#           places & routes small calibration designs for GW1NR-LV9QN88PC6/I5
#           (family GW1N-9C) with the project open-source flow and extracts
#           the nextpnr "Device utilisation" lines and "Max frequency" lines.
#           Results are TOOL ESTIMATES used as budget inputs; they are not
#           project RTL results and not hardware measurements.
# Usage   : bash scripts/budgets/run_ubench.sh  > scripts/budgets/logs/ubench.log 2>&1
# Outputs : build products only under scripts/budgets/build/ (git-ignorable).
# =============================================================================
set -u
ROOT=/home/user/tpu-e-cpu
B=$ROOT/scripts/budgets/build
U=$ROOT/scripts/budgets/ubench
source $ROOT/.venv/bin/activate
mkdir -p $B/ext
cd $B

echo "# command: bash scripts/budgets/run_ubench.sh"
echo "# date: $(date -u +%FT%TZ)  revision: $(cd $ROOT && git rev-parse --short HEAD)$(cd $ROOT && git diff --quiet HEAD -- 2>/dev/null || echo -dirty)"
echo "# yosys: $(yowasp-yosys -V 2>&1 | head -1)"
echo "# nextpnr: $(yowasp-nextpnr-himbaechel-gowin --version 2>&1 | head -1)"
echo "# apycula: $(pip show apycula 2>/dev/null | grep ^Version)"

# PicoRV32 reference core (CPU proxy). Downloaded into its own directory; only
# read by Yosys as data.
PICO_URL=https://raw.githubusercontent.com/YosysHQ/picorv32/main/picorv32.v
if [ ! -s $B/ext/picorv32.v ]; then curl -sS -o $B/ext/picorv32.v $PICO_URL; fi
echo "# picorv32.v: $PICO_URL sha256=$(sha256sum $B/ext/picorv32.v | cut -d' ' -f1)"

# Constraints: nextpnr-himbaechel-gowin refuses unconstrained I/Os, so the
# benches only use board pins taken from design/constraints/tangnano9k.cst
# (clk 52, buttons 3/4, LEDs 10..16, UART 17/18). Electrical I/O standards are
# irrelevant for these resource/timing estimates.
cat > $B/ubench.cst <<'CST'
IO_LOC  "clk" 52;
IO_PORT "clk" IO_TYPE=LVCMOS33 PULL_MODE=UP;
IO_LOC  "btn_s1_n" 3;
IO_LOC  "we" 4;
IO_LOC  "xwe" 18;
IO_LOC  "start" 10;
IO_LOC  "run" 11;
IO_LOC  "clr" 13;
IO_LOC  "dout_x" 17;
IO_LOC  "led_n[0]" 10;
IO_LOC  "led_n[1]" 11;
IO_LOC  "led_n[2]" 13;
IO_LOC  "led_n[3]" 14;
IO_LOC  "led_n[4]" 15;
IO_LOC  "led_n[5]" 16;
CST

run() {   # run <name> <top> <yosys-read-cmds> [chparams]
    local name=$1 top=$2 reads=$3 chp=${4:-}
    echo
    echo "================ $name (top=$top ${chp}) ================"
    yowasp-yosys -q -l $B/$name.yosys.log -p "$reads; ${chp:+chparam $chp $top;} synth_gowin -top $top -json $B/$name.json" >/dev/null 2>&1
    echo "yosys exit=$?"
    for seed in 1 2 3; do
        yowasp-nextpnr-himbaechel-gowin --json $B/$name.json --write $B/${name}_pnr.json \
            --device GW1NR-LV9QN88PC6/I5 --vopt family=GW1N-9C --vopt cst=$B/ubench.cst \
            --freq 27 --seed $seed > $B/${name}_s$seed.pnr.log 2>&1
        local rc=$?
        if [ $seed = 1 ]; then
            grep -E "^Info:[[:space:]]+(LUT4|ALU|DFF|RAM16SDP4|BSRAM|MUX2_LUT5|MUX2_LUT6|MUX2_LUT7|MUX2_LUT8|IOB|MULT18X18|MULT9X9):" $B/${name}_s1.pnr.log | sed 's/^Info:[[:space:]]*/  /'
        fi
        echo "  seed $seed nextpnr exit=$rc :: $(grep 'Max frequency for clock' $B/${name}_s$seed.pnr.log | tail -1 | sed 's/^Info: //')"
    done
}

RD_SC="read_verilog $U/sc_array_ubench.v"
run sc_nl16_il8_m0 sc_ubench_top "$RD_SC" "-set RNG_MODE 0"
run sc_nl16_il8_m1 sc_ubench_top "$RD_SC" "-set RNG_MODE 1"
run sc_nl16_il8_m2 sc_ubench_top "$RD_SC" "-set RNG_MODE 2"
run sc_nl16_il4_m1 sc_ubench_top "$RD_SC" "-set IL 4 -set AW 6 -set RNG_MODE 1"
run sc_nl16_il16_m1 sc_ubench_top "$RD_SC" "-set IL 16 -set AW 8 -set RNG_MODE 1"
run cpu_proxy       cpu_proxy_top   "read_verilog $B/ext/picorv32.v; read_verilog $U/cpu_proxy_top.v"
echo
echo "# done"
