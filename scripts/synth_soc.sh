#!/usr/bin/env bash
# =============================================================================
# scripts/synth_soc.sh  -  RTL-SOC: synthesis + place & route + bitstream of
#                          soc_top (Tang Nano 9K, GW1NR-LV9QN88PC6/I5)
#
# Flows (both from the SAME RTL, init files and constraints):
#   nwl : yosys synth_gowin -nowidelut  (CHOSEN flow: smaller and faster for
#         the CPU and the TPU in RTL-CPU / RTL-TPU)
#   def : yosys synth_gowin             (default wide-LUT mapping, comparison)
# For each flow: nextpnr-himbaechel-gowin, device GW1NR-LV9QN88PC6/I5, family
# GW1N-9C, CST design/constraints/tangnano9k.cst, --freq 27, seeds 1/2/3,
# single thread (shared 4-core machine), WITHOUT --timing-allow-fail.
# Utilisation from the nextpnr "Device utilisation" block, Fmax from the LAST
# "Max frequency" line (post-route), critical path from the LAST "Critical
# path report" block. Acceptance (ARCHITECTURE.md 10): every resource
# <= 85 % of the device, worst-seed Fmax >= 29.7 MHz.
# Then, for the chosen flow (nwl) and its worst seed: pin report
# (scripts/pnr_pin_report.py), BSRAM-init check, and gowin_pack -> .fs
# (route proof only: NEVER programmed into hardware).
# Yosys `check` (latches, combinational loops, multiple drivers) is run in
# both flows (REQ-TIM-002).
#
# Usage   : bash scripts/synth_soc.sh              (both flows, ~? min)
#           FLOWS=nwl bash scripts/synth_soc.sh    (chosen flow only)
#           REPORT_ONLY=1 bash scripts/synth_soc.sh (rebuild the report from logs)
# Logs    : logs/soc/synth_<flow>.log, logs/soc/pnr_<flow>_s<seed>.log,
#           logs/soc/pins.log, logs/soc/pack.log, logs/soc/bsram_init.log
# Report  : reports/fpga/soc/soc_impl.md (+ pnr_report_<flow>_s<seed>.json,
#           critical_path_<flow>.txt)
# Products: sim/soc/build/ (gitignored), incl. soc_top.fs (sha256 in
#           logs/soc/pack.log and the report; not committed, 2 MB)
# Exit    : 0 only if every step succeeded and the acceptance holds for nwl.
# =============================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"

T=design/rtl/tpu; C=design/rtl/cpu; S=design/rtl/soc
RTL="$C/rv32i_core.v $C/rv32i_decode.v $C/rv32i_alu.v $C/rv32i_regfile.v $T/sc_lfsr8.v $T/sc_rng.v $T/sc_lane_array.v $T/sc_postproc.v $T/sc_tpu_ctrl.v $T/sc_tpu.v $S/soc_bus.v $S/soc_ram.v $S/soc_periph.v $S/soc_top.v"
TOP=soc_top
CST=design/constraints/tangnano9k.cst
DEVICE="GW1NR-LV9QN88PC6/I5"
FAMILY="GW1N-9C"
LOG=logs/soc
B=sim/soc/build
REP=reports/fpga/soc
FLOWS=${FLOWS:-"nwl def"}
SEEDS=${SEEDS:-"1 2 3"}
REPORT_ONLY=${REPORT_ONLY:-0}
mkdir -p "$LOG" "$B" "$REP"

REV="$(git rev-parse --short HEAD 2>/dev/null || echo no-commit)"
if [ -n "$(git status --porcelain -- design/rtl design/constraints sim/data scripts/synth_soc.sh 2>/dev/null)" ]; then REV="${REV}-dirty"; fi
echo "# RTL-SOC synth/P&R  $(date -Is)  input revision: $REV" | tee "$LOG/synth_versions.log"
{
    echo "yosys   : $(yowasp-yosys -V)"
    echo "nextpnr : $(yowasp-nextpnr-himbaechel-gowin --version 2>&1 | sed -n 1p)"
    echo "apycula : $(pip show apycula 2>/dev/null | sed -n 's/^Version: //p')"
} | tee -a "$LOG/synth_versions.log"

ys() {  # ys <log> <script>  (yosys' own log, see rtl-gowin-flow lessons)
    yowasp-yosys -l "$1" -p "$2" > "$B/ys_stdout.log" 2>&1 || true
    grep -q 'End of script' "$1" || { echo "yosys failed: $1" >&2; exit 1; }
}

if [ "$REPORT_ONLY" != 1 ]; then
    for fl in $FLOWS; do
        opt=""; [ "$fl" = nwl ] && opt="-nowidelut"
        echo "== synth $fl (synth_gowin $opt)"
        # `check` after synthesis: latches / loops / multiple drivers (REQ-TIM-002).
        ys "$LOG/synth_$fl.log" "read_verilog $RTL; synth_gowin $opt -top $TOP -json $B/${TOP}_$fl.json; check; stat"
        for s in $SEEDS; do
            PL="$LOG/pnr_${fl}_s$s.log"
            echo "== P&R $fl seed $s"
            {
                echo "# input revision: $REV"
                echo "# cmd: yowasp-nextpnr-himbaechel-gowin --json $B/${TOP}_$fl.json --write $B/${TOP}_${fl}_pnr_s$s.json --device $DEVICE --vopt family=$FAMILY --vopt cst=$CST --freq 27 --report $B/${TOP}_${fl}_report_s$s.json --seed $s --threads 1"
                set +e
                yowasp-nextpnr-himbaechel-gowin --json "$B/${TOP}_$fl.json" --write "$B/${TOP}_${fl}_pnr_s$s.json" \
                    --device "$DEVICE" --vopt family="$FAMILY" --vopt cst="$CST" --freq 27 \
                    --report "$B/${TOP}_${fl}_report_s$s.json" --seed "$s" --threads 1
                echo "PNR_EXIT=$?"
                set -e
            } > "$PL" 2>&1
            grep -E 'Max frequency for clock' "$PL" | tail -n 1 || true
            grep -E '^PNR_EXIT' "$PL"
            [ -f "$B/${TOP}_${fl}_report_s$s.json" ] && cp "$B/${TOP}_${fl}_report_s$s.json" "$REP/pnr_report_${fl}_s$s.json"
        done
    done
fi

# ---------------------------------------------------------------- report tables
python3 -I - "$LOG" "$REP" "$REV" "$FLOWS" "$SEEDS" > "$LOG/report_parse.log" 2>&1 <<'PY' || { cat "$LOG/report_parse.log"; exit 1; }
"""Parse the synth / P&R logs -> reports/fpga/soc/soc_impl_tables.md and
critical_path_<flow>.txt; print SOC_<KEY>_<flow>=<value> lines for the shell."""
import re, sys
from pathlib import Path
log, rep, rev, flows, seeds = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4].split(), sys.argv[5].split()
# Resources reported (always shown: the first 6 + MUX2_LUT5 + MULT18X18; others if used).
RES = ["LUT4", "ALU", "DFF", "BSRAM", "RAM16SDP4", "IOB", "MUX2_LUT5", "MUX2_LUT6", "MUX2_LUT7",
       "MUX2_LUT8", "MULT9X9", "MULT18X18", "MULT36X36", "MULTALU18X18", "MULTALU36X18",
       "MULTADDALU18X18", "ALU54D", "PADD9", "PADD18"]
ALWAYS = {"LUT4", "ALU", "DFF", "BSRAM", "RAM16SDP4", "IOB", "MUX2_LUT5", "MULT18X18"}
out = [f"<!-- generated by scripts/synth_soc.sh from logs/soc/, input revision {rev} -->", ""]
for fl in flows:
    rows = {}
    for s in seeds:
        p = log / f"pnr_{fl}_s{s}.log"
        if not p.exists():
            continue
        t = p.read_text()
        util = {}
        if "Device utilisation:" in t:
            blk = t.split("Device utilisation:")[1].split("\n\n")[0]
            for m in re.finditer(r"Info:\s+(\w+):\s+(\d+)/\s*(\d+)\s+(\d+)%", blk):
                util[m.group(1)] = (int(m.group(2)), int(m.group(3)), int(m.group(4)))
        fm = re.findall(r"Max frequency for clock '([^']+)': ([0-9.]+) MHz \((PASS|FAIL)", t)
        crit = []
        cp = t.rfind("Critical path report for clock")
        if cp >= 0:
            for l in t[cp:].splitlines():
                if not l.startswith("Info:"):
                    break
                crit.append(l)
                if re.search(r"[0-9.]+ ns logic, [0-9.]+ ns routing", l):
                    break
        rows[s] = dict(util=util, fmax=float(fm[-1][1]) if fm else None,
                       ok=("PNR_EXIT=0" in t), crit="\n".join(crit), clock=fm[-1][0] if fm else "-")
    if not rows:
        continue
    name = "synth_gowin -nowidelut (chosen)" if fl == "nwl" else "synth_gowin default wide-LUT (comparison)"
    out += [f"### Flow `{fl}`: {name}", "",
            "| Resource | device total | 85 % limit | " + " | ".join(f"seed {s}" for s in rows) + " | worst % | <= 85 % |",
            "|" + "---|" * (len(rows) + 5)]
    maxpct = 0
    res_ok = True
    for r in RES:
        vals = [rows[s]["util"].get(r) for s in rows]
        if all(v is None for v in vals):
            continue
        if r not in ALWAYS and all(v is None or v[0] == 0 for v in vals):
            continue
        tot = next(v[1] for v in vals if v)
        lim = int(tot * 0.85)
        used = max(v[0] for v in vals if v)
        pct = max(v[2] for v in vals if v)
        maxpct = max(maxpct, pct)
        ok = used <= lim
        res_ok &= ok
        out.append(f"| {r} | {tot} | {lim} | " + " | ".join(f"{v[0]} ({v[2]} %)" if v else "-" for v in vals)
                   + f" | {pct} % | {'PASS' if ok else 'FAIL'} |")
    out += ["", "(nextpnr counts every ALU cell inside LUT4 as well; LUT4 is the total of logic positions used.)", "",
            "| Seed | P&R exit | post-route Fmax (MHz) | margin vs 27 MHz | >= 29.7 MHz |", "|---|---|---|---|---|"]
    fms = {s: rows[s]["fmax"] for s in rows}
    for s in rows:
        f = fms[s]
        out.append(f"| {s} | {'0' if rows[s]['ok'] else 'FAIL'} | {f if f else '-'} | "
                   + (f"{(f / 27 - 1) * 100:+.1f} %" if f else "-") + " | "
                   + (("PASS" if f >= 29.7 else "FAIL") if f else "-") + " |")
    valid = [s for s in fms if fms[s] is not None]
    if valid:
        w = min(valid, key=lambda s: fms[s])
        out += ["", f"Worst seed {w}: {fms[w]} MHz (clock `{rows[w]['clock']}`); worst utilisation of any resource {maxpct} %.", ""]
        (rep / f"critical_path_{fl}.txt").write_text(
            f"# flow {fl}, worst seed {w} ({fms[w]} MHz), source logs/soc/pnr_{fl}_s{w}.log (last report = post-route)\n"
            + rows[w]["crit"] + "\n")
        print(f"SOC_WORSTSEED_{fl}={w}")
        print(f"SOC_WORSTFMAX_{fl}={fms[w]}")
        print(f"SOC_MAXPCT_{fl}={maxpct}")
        print(f"SOC_RESOK_{fl}={1 if res_ok else 0}")
        print(f"SOC_ALLPNR_{fl}={1 if (all(rows[s]['ok'] for s in rows) and len(rows) == len(seeds)) else 0}")
(rep / "soc_impl_tables.md").write_text("\n".join(out) + "\n")
print("\n".join(out))
PY
cat "$LOG/report_parse.log"
val() { sed -n "s/^SOC_$1=//p" "$LOG/report_parse.log"; }

# ---------------------------------------------------------------- acceptance (nwl)
fail=0
WS="$(val WORSTSEED_nwl)"; WF="$(val WORSTFMAX_nwl)"
[ -n "$WS" ] || { echo "no nwl P&R result"; exit 1; }
[ "$(val ALLPNR_nwl)" = 1 ] || { echo "a nwl P&R seed failed"; fail=1; }
[ "$(val RESOK_nwl)" = 1 ]  || { echo "a resource exceeds 85 %"; fail=1; }
python3 -c "import sys; sys.exit(0 if $WF >= 29.7 else 1)" || { echo "worst Fmax $WF < 29.7 MHz"; fail=1; }

# ---------------------------------------------------------------- latch / loop check
for fl in $FLOWS; do
    { grep -E -i 'latch|combinational loop|logic loop|multiple conflicting drivers|found and reported [0-9]+ problems' "$LOG/synth_$fl.log" || true; } > "$LOG/check_$fl.log"
    grep -E -i -q 'found and reported 0 problems' "$LOG/synth_$fl.log" && ! grep -E -i -q 'found and reported [1-9][0-9]* problems' "$LOG/synth_$fl.log" || { echo "yosys check reported problems ($fl)"; fail=1; }
done

# ---------------------------------------------------------------- pins (worst nwl seed)
PNR="$B/${TOP}_nwl_pnr_s$WS.json"
python scripts/pnr_pin_report.py "$PNR" GW1N-9C QFN88P > "$LOG/pins.log" 2>&1 || fail=1
for exp in 'clk\[0\] .* pin  52 ' 'btn_rst_n\[0\] .* pin   3 ' 'led_n\[0\] .* pin  10 ' 'led_n\[1\] .* pin  11 ' \
           'led_n\[2\] .* pin  13 ' 'led_n\[3\] .* pin  14 ' 'led_n\[4\] .* pin  15 ' 'led_n\[5\] .* pin  16 ' \
           'uart_tx\[0\] .* pin  17 ' 'uart_rx\[0\] .* pin  18 '; do
    grep -E -q "$exp" "$LOG/pins.log" || { echo "pin check failed: $exp"; fail=1; }
done
NIO="$(grep -c ' pin ' "$LOG/pins.log" || true)"
[ "$NIO" -eq 10 ] || { echo "expected 10 placed IOs, got $NIO"; fail=1; }

# ---------------------------------------------------------------- BSRAM init check
# The RAM program and the TPU weights must be in the BSRAM INIT parameters of
# the routed netlist (otherwise the bitstream would start with an empty RAM).
python3 -I - "$PNR" > "$LOG/bsram_init.log" 2>&1 <<'PY' || fail=1
import json, sys
d = json.load(open(sys.argv[1]))
mod = next(iter(d["modules"].values()))
n_bsram = n_init = 0
for name, c in mod["cells"].items():
    if c["type"] in ("SP", "SPX9", "SDP", "SDPB", "SDPX9B", "DP", "DPB", "DPX9B", "ROM", "pROM"):
        n_bsram += 1
        nz = sum(1 for k, v in c["parameters"].items() if k.startswith("INIT_RAM_") and set(str(v)) - {"0"})
        n_init += nz > 0
        print(f"{c['type']:7s} {name[:90]:90s} non-zero INIT_RAM_xx params: {nz}")
print(f"BSRAM cells {n_bsram}, with non-zero init {n_init}")
sys.exit(0 if n_bsram >= 3 and n_init >= 1 else 1)
PY
tail -n 1 "$LOG/bsram_init.log"

# ---------------------------------------------------------------- bitstream
{
    echo "# cmd: gowin_pack -d $FAMILY -o $B/$TOP.fs $PNR   (route proof only, never programmed)"
    set +e
    gowin_pack -d "$FAMILY" -o "$B/$TOP.fs" "$PNR"
    echo "PACK_EXIT=$?"
    set -e
    ls -l "$B/$TOP.fs" && sha256sum "$B/$TOP.fs"
} > "$LOG/pack.log" 2>&1 || true
grep -q '^PACK_EXIT=0$' "$LOG/pack.log" && [ -s "$B/$TOP.fs" ] || { echo "gowin_pack FAILED"; fail=1; }
cat "$LOG/pack.log"

if [ $fail -eq 0 ]; then echo "SYNTH_SOC: PASS (worst nwl seed $WS, $WF MHz)"; else echo "SYNTH_SOC: FAIL"; fi
exit $fail
