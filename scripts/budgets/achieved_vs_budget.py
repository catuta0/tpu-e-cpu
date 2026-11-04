#!/usr/bin/env python3
# =============================================================================
# File    : scripts/budgets/achieved_vs_budget.py
# Task    : REQ-02 (systems-engineer) - compare the issue-1 budget CALCULATIONs
#           of requirements/BUDGETS.md with the achieved numbers that now exist
#           (SIMULATION = synthesis / P&R tool reports and RTL / golden-model
#           simulations of other specialists). Read-only on all inputs.
# Inputs  : (paths relative to the repository root; each value is parsed from
#           the decisive log line, never typed in by hand)
#   logs/soc/pnr_nwl_s{1,2,3}.log      SoC P&R, release flow synth_gowin -nowidelut
#   logs/cpu/pnr_s{1,2,3}.log          CPU in-context P&R (RTL-CPU)
#   logs/cpu/sim_cpu_summary.log       CPU CPI (RTL-CPU)
#   logs/tpu/pnr_il8_m{1,2}_nwl_s{1,2,3}.log, pnr_il4_m1_nwl_s1.log,
#   logs/tpu/pnr_il16_m1_nwl_s1.log    TPU stand-alone P&R variants (RTL-TPU)
#   logs/tpu/tb_sc_tpu_mode2.log       CYCLES (D8 line, rev C run)
#   logs/soc/tb_soc_demo.log           SoC demo timing (RTL-SOC, rev C)
#   reports/sw/accuracy_revC.json      accuracy (SW-03, rev C)
#   reports/sw/accuracy_revA.json      accuracy used as preliminary input in issue 1
# Budget  : the issue-1 values are constants below, each with its BUDGETS.md
#           section (CALCULATION, issue 1, input revision 494448a).
# Output  : table "name | budget | achieved | deviation %" ; deviation =
#           (achieved - budget) / budget (CALCULATION). Rows with |dev| > 10 %
#           are flagged ">10%" and explained in BUDGETS.md.
# Usage   : python3 scripts/budgets/achieved_vs_budget.py \
#               > scripts/budgets/logs/achieved_vs_budget.log
# =============================================================================
import json
import os
import re
import subprocess
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def rd(rel):
    """Read a repository file as text."""
    with open(os.path.join(REPO, rel)) as f:
        return f.read()


def util(rel, res):
    """Used count of resource `res` from a nextpnr 'Device utilisation' block."""
    m = re.search(rf"^Info:\s+{res}:\s+(\d+)/\s*(\d+)", rd(rel), re.M)
    return int(m.group(1))


def fmax(rel):
    """LAST 'Max frequency' value of a nextpnr log (post-route), in MHz."""
    v = re.findall(r"Max frequency for clock '[^']+': ([\d.]+) MHz", rd(rel))
    return float(v[-1])


ROWS = []


def row(name, budget, achieved, unit, note=""):
    """Record one comparison row; deviation in % of the budget value."""
    dev = (achieved - budget) / budget * 100.0
    ROWS.append((name, budget, achieved, unit, dev, note))


def main():
    rev = subprocess.run(["git", "-C", REPO, "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", REPO, "status", "--porcelain"],
                           capture_output=True, text=True).stdout.strip()
    print("# command: python3 scripts/budgets/achieved_vs_budget.py")
    print(f"# input revision: {rev}{'-dirty' if dirty else ''}; python {sys.version.split()[0]}")
    print("# budget = CALCULATION (BUDGETS.md issue 1); achieved = SIMULATION (tool / simulation logs); deviation = CALCULATION")

    # ---------------- 1. resources (SoC, release flow nwl) ----------------
    soc = {r: util("logs/soc/pnr_nwl_s1.log", r) for r in ("LUT4", "ALU", "DFF", "RAM16SDP4", "BSRAM")}
    for s in (2, 3):  # placement does not change cell counts: verify
        assert all(util(f"logs/soc/pnr_nwl_s{s}.log", r) == v for r, v in soc.items())
    print("SoC nwl utilisation (seeds 1..3 identical): " + ", ".join(f"{k} {v}" for k, v in soc.items()))
    # issue-1 budget, baseline (mode 1, regfile in LUT-RAM) - BUDGETS 1.4
    row("SoC LUT4 vs issue-1 baseline (mode 1, LUT-RAM regfile)", 5735, soc["LUT4"], "LUT4")
    row("SoC DFF vs issue-1 baseline", 2489, soc["DFF"], "FF")
    # budget re-evaluated for the configuration actually built (CALCULATION from
    # the issue-1 variant deltas of BUDGETS 1.5): mode 2 (+112 LUT, +224 FF) and
    # CPU regfile in BSRAM (-256 LUT, -32 RAM16, +2 BSRAM)
    row("SoC LUT4 vs as-built-config budget (5735+112-256)", 5591, soc["LUT4"], "LUT4")
    row("SoC DFF vs as-built-config budget (2489+224)", 2713, soc["DFF"], "FF")
    row("SoC RAM16SDP4 vs as-built-config budget (56-32)", 24, soc["RAM16SDP4"], "cell",
        "SCORE (8 cells) implemented in FFs instead of LUT-RAM")
    row("SoC BSRAM vs issue-1 baseline", 3, soc["BSRAM"], "block", "regfile option taken (+2)")
    row("SoC BSRAM vs as-built-config budget (3+2)", 5, soc["BSRAM"], "block")
    row("SoC LUT4 vs issue-1 worst case", 6703, soc["LUT4"], "LUT4", "below worst case")

    # ---------------- TPU stand-alone (RTL-TPU, rev A seeds, nwl) ----------------
    tl = util("logs/tpu/pnr_il8_m2_nwl_s1.log", "LUT4")
    tf = util("logs/tpu/pnr_il8_m2_nwl_s1.log", "DFF")
    t1l = util("logs/tpu/pnr_il8_m1_nwl_s1.log", "LUT4")
    t1f = util("logs/tpu/pnr_il8_m1_nwl_s1.log", "DFF")
    t4l = util("logs/tpu/pnr_il4_m1_nwl_s1.log", "LUT4")
    t16l = util("logs/tpu/pnr_il16_m1_nwl_s1.log", "LUT4")
    wrap = 100  # ASSUMPTION: synthesis wrapper ~100 LUT / ~100 FF (reports/fpga/tpu/variants.md)
    print(f"TPU stand-alone nwl: IL8 m2 {tl} LUT4 / {tf} DFF; IL8 m1 {t1l} / {t1f}; IL4 m1 {t4l}; IL16 m1 {t16l} LUT4 "
          f"(wrapper ~{wrap} LUT / ~{wrap} FF, ASSUMPTION)")
    row("TPU LUT4 (mode 2) minus wrapper vs budget 2830+790+112", 3732, tl - wrap, "LUT4")
    row("TPU DFF (mode 2) minus wrapper vs budget 1409+347+224", 1980, tf - wrap, "FF")
    row("TPU-other LUT4 (TPU - array 2830 - mode-2 112 - wrapper) vs 790", 790, tl - wrap - 2830 - 112, "LUT4",
        "array share taken from the bench: attribution ASSUMPTION")
    row("RNG mode 1->2 delta LUT4 (nwl)", 112, tl - t1l, "LUT4")
    row("RNG mode 1->2 delta DFF (nwl)", 224, tf - t1f, "FF")
    row("IL 8->4 delta LUT4 (nwl, mode 1)", -1408, t4l - t1l, "LUT4")
    row("IL 8->16 delta LUT4 (nwl, mode 1)", 2426, t16l - t1l, "LUT4", "IL16: no legal placement")

    # ---------------- CPU (RTL-CPU in-context: core + 4 KiB RAM + wrapper) ----------------
    cl = util("logs/cpu/pnr_s1.log", "LUT4")
    cf = util("logs/cpu/pnr_s1.log", "DFF")
    print(f"CPU in-context (core + RAM wrapper): {cl} LUT4 / {cf} DFF")
    row("CPU LUT4 in-context vs proxy budget 1940", 1940, cl, "LUT4")
    row("CPU DFF in-context vs proxy budget 600", 600, cf, "FF")

    # ---------------- 5. timing ----------------
    sf = [fmax(f"logs/soc/pnr_nwl_s{s}.log") for s in (1, 2, 3)]
    cfm = [fmax(f"logs/cpu/pnr_s{s}.log") for s in (1, 2, 3)]
    tfm = [fmax(f"logs/tpu/pnr_il8_m2_nwl_s{s}.log") for s in (1, 2, 3)]
    print(f"Fmax SoC nwl seeds {sf}; CPU {cfm}; TPU IL8 m2 nwl {tfm} MHz")
    row("SoC worst-seed Fmax vs budget min over paths (P1 52.12)", 52.12, min(sf), "MHz",
        "critical path moved from P1 (SC MAC) to P3 (CPU)")
    row("P1 SC MAC path delay (TPU alone, worst seed) vs 19.19 ns", 19.19, 1000 / min(tfm), "ns")
    row("P3 CPU path delay (CPU alone, worst seed) vs 10.95 ns", 10.95, 1000 / min(cfm), "ns")
    row("P3 CPU path delay (in SoC, worst seed) vs 10.95 ns", 10.95, 1000 / min(sf), "ns")

    # ---------------- 3. latency ----------------
    d8 = re.search(r"D8 CYCLES = (\d+) = measured BUSY cycles (\d+) = formula 10\*2\^8\+(\d+)",
                   rd("logs/tpu/tb_sc_tpu_mode2.log"))
    cyc8, const = int(d8.group(1)), int(d8.group(3))
    assert cyc8 == int(d8.group(2)) == 10 * 256 + const
    print(f"CYCLES(K=8) = {cyc8} = 10*2^8 + {const} (SIMULATION, tb_sc_tpu_mode2 D8; all K in RTL-TPU)")
    for k in (4, 8, 10):
        row(f"CYCLES K={k} (10*2^K+{const} vs 10*2^K+409)", 10 * 2 ** k + 409, 10 * 2 ** k + const, "cycles")
    row("fixed overhead per inference (const term)", 409, const, "cycles",
        "argmax/start/done folded into post-processing; tile load 33 not 36")
    row("throughput K=8", 27e6 / 2969, 27e6 / cyc8, "inf/s")
    demo = rd("logs/soc/tb_soc_demo.log")
    m = re.search(r"START->RESULT read (\d+) cycles\), TPU BUSY (\d+) cycles", demo)
    s2r, busy = int(m.group(1)), int(m.group(2))
    f = re.search(r"first bus request after reset release is a fetch of 0x00000000 \(at cycle (\d+)", demo)
    print(f"SoC demo: START->RESULT read {s2r} cycles, BUSY {busy}, CPU-side overhead {s2r - busy} cycles "
          f"(no input loading in the demo); first fetch at cycle {f.group(1)}")

    # ---------------- CPI ----------------
    # aggregate CPI at 0 wait states = sum(cycles) / sum(instret) over the 44 tests
    cs = re.findall(r"^PASS \S+\s.*cycles=(\d+) instret=(\d+)", rd("logs/cpu/sim_cpu_summary.log"), re.M)
    cyc, ins = sum(int(a) for a, _ in cs), sum(int(b) for _, b in cs)
    print(f"CPU aggregate CPI (0 wait states, {len(cs)} tests): {cyc} / {ins} = {cyc / ins:.3f} "
          f"(budget ASSUMPTION 'CPI ~4-6', BUDGETS 3: inside the range)")
    # SoC-level CPI of the demo program (includes the 2-wait-state TPU and the
    # 1-wait-state RAM; CALCULATION from SIMULATION counts)
    m2 = re.search(r"instructions retired up to TOHOST (\d+)", demo)
    m3 = re.search(r"reset release -> TOHOST write = (\d+) cycles", demo)
    n_i, n_c = int(m2.group(1)), int(m3.group(1))
    print(f"SoC demo CPI = ({n_c} - {f.group(1)} CLEAR) / {n_i} = {(n_c - int(f.group(1))) / n_i:.2f}")

    # ---------------- 8. accuracy ----------------
    c = json.load(open(os.path.join(REPO, "reports/sw/accuracy_revC.json")))["models"]["qat_noise"]
    a = json.load(open(os.path.join(REPO, "reports/sw/accuracy_revA.json")))["models"]["qat_noise"]
    for mo in ("0", "1", "2"):
        row(f"accuracy K=8 mode {mo} (prelim rev A -> rev C)", a["sc"][mo]["8"]["acc"] * 100,
            c["sc"][mo]["8"]["acc"] * 100, "%")
    row("EV accuracy", a["expected_value_Kinf"]["acc"] * 100, c["expected_value_Kinf"]["acc"] * 100, "%")
    e = json.load(open(os.path.join(REPO, "reports/sw/accuracy_revC.json")))["error_study"]["per_mode_K"]["2"]["8"]
    row("layer-1 SC noise K=8 mode 2, ensemble RMS vs bound sqrt(64/256)", 0.5, e["layer1"]["ensemble_rms_measured"], "v")
    row("layer-1 SC noise K=8 mode 2, deployed seeds vs bound", 0.5, e["layer1"]["rms_measured"], "v")
    row("layer-2 SC noise K=8 mode 2 (lanes 0..9), ensemble vs bound sqrt(16/256)", 0.25,
        e["layer2_real"]["ensemble_rms_measured"], "v")
    row("layer-2 SC noise K=8 mode 2 (lanes 0..9), deployed vs bound", 0.25, e["layer2_real"]["rms_measured"], "v")

    # ---------------- print ----------------
    print()
    print("| name | budget (CALC) | achieved (SIM) | unit | deviation % | flag | note |")
    print("|---|---|---|---|---|---|---|")
    for name, b, x, u, d, note in ROWS:
        fb = f"{b:.4g}" if isinstance(b, float) else str(b)
        fx = f"{x:.4g}" if isinstance(x, float) else str(x)
        print(f"| {name} | {fb} | {fx} | {u} | {d:+.1f} | {'>10%' if abs(d) > 10 else ''} | {note} |")


if __name__ == "__main__":
    main()
