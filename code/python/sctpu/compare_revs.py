"""Rev A vs rev B seed comparison of the SC-TPU accuracy (task SW-02, deliverable 4).

All numbers are SIMULATION results of the bit-exact Python golden model
(``sctpu.model``) on the 360 test images of the stratified digits split
(seed 0), with the SAME trained weights for both revisions (the network is not
retrained in SW-02; only the hardware LFSR seeds differ, ARCHITECTURE.md 11,
ADR-008).

What is compared (selected model ``qat_noise``, s = 0)
------------------------------------------------------
1. Hardware seeds (the single deployed realisation of each revision), for
   every RNG_MODE 0/1/2 and K = 4..10: accuracy with 95 % Wilson CI, the paired
   difference rev B - rev A with a 95 % Newcombe (1998, method 10) CI, and the
   exact McNemar test on the discordant images (same 360 images in both runs).
   The pre-specified tests of the assignment are mode 2 at K = 8 and K = 9; all
   other cells are exploratory (no multiple-comparison correction).
2. Ensemble: 20 analysis-only LFSR start offsets (numpy default_rng(0), the
   same offsets for both revisions, which keeps each revision's relative seed
   phases). Paired over offsets: mean difference with a 95 % Student-t CI.
3. Structure check (CALCULATION from the model's count tables): number of
   (tile, lane) slot pairs of one inference whose XNOR count tables are
   identical. In rev B the X and W lane seeds are spaced by the same 4096
   single steps (= 512 stream cycles), so the joint (r_x, r_w) stream of lane
   i+1 is the stream of lane i delayed by 512 cycles; whenever 512 cycles are
   a whole number of tiles (K <= 9) or a tile is a whole number of 512-cycle
   blocks (K = 10) the count tables repeat across slots and the SC errors of
   those slots are no longer independent.
4. Analysis-only candidate ``C1`` (NOT a spec revision): rev B seeds with the
   W lanes in reverse order, W_i = S(32768 + 4096 (7 - i)). Same 16 seed
   values (min pairwise lag still 512 cycles) but b_i - a_i = 4096 + 512 (7 - 2i)
   cycles differ for every lane, so no two pair streams are shifted copies.

Outputs: ``reports/sw/revA_vs_revB.json``, ``reports/sw/revA_vs_revB.md``,
``reports/sw/fig_revA_vs_revB.pdf``. Log: ``logs/sw/compare_revs.log``.
Run: ``cd code/python && ../../.venv/bin/python -m sctpu.compare_revs``.
"""

from __future__ import annotations

import json
import math
import sys
import time
from fractions import Fraction

import numpy as np
from scipy import stats

from . import accuracy as A
from . import model as M
from . import train as T

REPORT_DIR = T.REPORT_DIR
K_RANGE = A.K_RANGE
MODES = A.MODES
N_ENS = 20  #: ensemble size (REQ-AI-006: >= 20)
PRESPECIFIED = [(2, 8), (2, 9)]  #: (mode, K) cells named in the SW-02 assignment


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value for discordant counts b, c (CALCULATION).

    Under H0 (equal accuracy) the b discordant images of one kind out of
    n = b + c are Binomial(n, 1/2); p = min(1, 2 P(X <= min(b, c))). Exact
    rational arithmetic, converted to float at the end.
    """
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(Fraction(math.comb(n, k), 2 ** n) for k in range(min(b, c) + 1))
    return float(min(Fraction(1), 2 * tail))


def newcombe_paired_ci(a: int, b: int, c: int, d: int, z: float = 1.959964) -> list:
    """95 % CI of p_B - p_A for paired proportions, Newcombe (1998) method 10.

    2x2 table: a = both correct, b = A correct / B wrong, c = A wrong / B correct,
    d = both wrong. p_A = (a+b)/n, p_B = (a+c)/n. Uses the Wilson limits of both
    marginals and the phi correlation of the table.
    """
    n = a + b + c + d
    pA, pB = (a + b) / n, (a + c) / n
    lA, uA = A.wilson_ci(a + b, n, z)
    lB, uB = A.wilson_ci(a + c, n, z)
    den = math.sqrt((a + b) * (c + d) * (a + c) * (b + d))
    phi = (a * d - b * c) / den if den > 0 else 0.0
    delta = math.sqrt(max(0.0, (pB - lB) ** 2 - 2 * phi * (pB - lB) * (uA - pA) + (uA - pA) ** 2))
    eps = math.sqrt(max(0.0, (uB - pB) ** 2 - 2 * phi * (uB - pB) * (pA - lA) + (pA - lA) ** 2))
    diff = pB - pA
    return [diff - delta, diff + eps]


def paired_cells(ok_a: np.ndarray, ok_b: np.ndarray) -> dict:
    """2x2 paired counts, accuracies with Wilson CIs, Newcombe CI and McNemar p."""
    a = int(np.sum(ok_a & ok_b))
    b = int(np.sum(ok_a & ~ok_b))
    c = int(np.sum(~ok_a & ok_b))
    d = int(np.sum(~ok_a & ~ok_b))
    n = a + b + c + d
    return {"n": n, "both_correct": a, "A_only_correct": b, "B_only_correct": c, "both_wrong": d,
            "acc_A": (a + b) / n, "ci95_A": A.wilson_ci(a + b, n), "n_correct_A": a + b,
            "acc_B": (a + c) / n, "ci95_B": A.wilson_ci(a + c, n), "n_correct_B": a + c,
            "diff_B_minus_A": (c - b) / n, "diff_ci95_newcombe": newcombe_paired_ci(a, b, c, d),
            "mcnemar_exact_p": mcnemar_exact(b, c)}


def t_ci(x: np.ndarray, conf: float = 0.95) -> list:
    """Student-t confidence interval of the mean of ``x`` (CALCULATION)."""
    n = len(x)
    m = float(np.mean(x))
    h = float(stats.t.ppf(0.5 + conf / 2, n - 1) * np.std(x, ddof=1) / math.sqrt(n))
    return [m - h, m + h]


# ---------------------------------------------------------------------------
# Seed sets
# ---------------------------------------------------------------------------

def candidate_c1_seeds() -> tuple[list, list]:
    """Analysis-only candidate C1: rev B X seeds, rev B W seeds in reverse lane order."""
    sx = [M.phase_state(M.PHASE_LANE * i) for i in range(M.IL)]
    sw = [M.phase_state(M.PHASE_W + M.PHASE_LANE * (M.IL - 1 - i)) for i in range(M.IL)]
    return sx, sw


def identical_table_pairs(eng: M.SCEngine) -> int:
    """Number of (tile, lane) slot pairs of one inference with identical count tables."""
    flat = eng.table.reshape(M.N_TILES_TOTAL * M.IL, -1)
    # hash rows to find duplicates quickly, then confirm with array_equal
    groups: dict = {}
    for s in range(flat.shape[0]):
        groups.setdefault(hash(flat[s].tobytes()), []).append(s)
    n = 0
    for members in groups.values():
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                n += int(np.array_equal(flat[members[i]], flat[members[j]]))
    return n


def seed_info(sx: list, sw: list) -> dict:
    """Seeds and their stream-cycle distances (CALCULATION)."""
    seeds = list(sx) + list(sw)
    d = [M.stream_distance_cycles(seeds[a], seeds[b]) for a in range(len(seeds))
         for b in range(a + 1, len(seeds))]
    pair_shift = [(M.stream_lag_cycles(sx[0], sw[i]) - M.stream_lag_cycles(sx[0], sx[i]))
                  % 65535 for i in range(len(sx))]
    return {"x": [f"0x{v:04x}" for v in sx], "w": [f"0x{v:04x}" for v in sw],
            "min_pairwise_distance_cycles": min(d) if d else None,
            "Xi_Wi_distance_cycles": [M.stream_distance_cycles(sx[i], sw[i]) for i in range(len(sx))],
            "pair_offset_b_minus_a_cycles": pair_shift,
            "n_distinct_pair_offsets": len(set(pair_shift))}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_config(xc, y, hw, K, mode, spec_rev, seeds, offsets, w1, w2, b) -> dict:
    """Hardware-seed correctness vector + ensemble accuracies and layer-1 RMS ratio."""
    eng = M.SCEngine(K, mode, spec_rev=spec_rev, seeds=seeds)
    r = eng.run(xc, hw["weight_ram"], hw["biases"], hw["s"])
    ok = r["result"] == y
    ident = identical_table_pairs(eng) if mode == 2 else None
    del eng
    accs, sq, pr = [], [], []
    S = None if mode == 2 else A.spin_table(mode)
    for off in offsets:
        ee = M.SCEngine(K, mode, start_offset=int(off), spec_rev=spec_rev, seeds=seeds).run(
            xc, hw["weight_ram"], hw["biases"], hw["s"])
        accs.append(float(np.mean(ee["result"] == y)))
        raw = A.error_arrays(ee, xc, w1, w2, b, K, mode, S)
        sq.append(float(np.mean(raw["layer1"]["e"] ** 2)))
        pr.append(float(np.mean(raw["layer1"]["vg"])))
    return {"ok": ok, "ens_acc": np.array(accs), "identical_table_pairs": ident,
            "layer1_ens_rms": math.sqrt(np.mean(sq)), "layer1_eq2_rms": math.sqrt(np.mean(pr))}


def main() -> int:
    """Run the comparison and write the JSON, Markdown and PDF outputs."""
    t0 = time.time()
    rev = T.git_rev()
    print(f"# compare_revs.py rev={rev} numpy={np.__version__} scipy={stats.__name__}")
    sel, allm = A.load_models()
    d = T.load_split()
    te = np.array(sel["test_indices"])
    assert np.array_equal(te, d["test_idx"])
    xc, y = d["codes"][te], d["y"][te]
    selv = sel["variant"]
    hw = A.hw_from_json(allm["models"][selv])
    w1, w2 = M.unpack_weight_ram(hw["weight_ram"])
    b = hw["biases"]
    offsets = A.ensemble_offsets(N_ENS, A.ENSEMBLE_SEED)
    print(f"# variant {selv} s={hw['s']} n_test={len(te)}; NOT retrained; ensemble offsets (seed "
          f"{A.ENSEMBLE_SEED}): {[int(o) for o in offsets]}")
    c1 = candidate_c1_seeds()

    configs = {"A": ("A", None), "B": ("B", None), "C1": ("B", c1)}
    raw: dict = {k: {} for k in configs}
    for name, (srev, seeds) in configs.items():
        for mode in MODES:
            if name == "C1" and mode != 2:
                continue
            for K in K_RANGE:
                raw[name][(mode, K)] = run_config(xc, y, hw, K, mode, srev, seeds, offsets, w1, w2, b)
                rr = raw[name][(mode, K)]
                print(f"{name:2s} mode {mode} K={K:2d} hw acc={rr['ok'].mean():.4f} ens={rr['ens_acc'].mean():.4f}"
                      f"+-{rr['ens_acc'].std(ddof=1):.4f} ident_pairs={rr['identical_table_pairs']} "
                      f"rms1 ens/eq2={rr['layer1_ens_rms'] / rr['layer1_eq2_rms']:.3f}", flush=True)

    ev = M.ev_inference(xc, hw["weight_ram"], hw["biases"], hw["s"])
    ev_acc = float(np.mean(ev["result"] == y))

    def compare(na: str, nb: str, mode: int, K: int) -> dict:
        ra, rb = raw[na][(mode, K)], raw[nb][(mode, K)]
        hwc = paired_cells(ra["ok"], rb["ok"])
        dif = rb["ens_acc"] - ra["ens_acc"]
        return {"mode": mode, "K": K, "prespecified": (mode, K) in PRESPECIFIED and (na, nb) == ("A", "B"),
                "hardware_seeds": hwc,
                "ensemble": {"n_realisations": len(dif),
                             f"mean_{na}": float(ra["ens_acc"].mean()), f"sd_{na}": float(ra["ens_acc"].std(ddof=1)),
                             f"mean_{nb}": float(rb["ens_acc"].mean()), f"sd_{nb}": float(rb["ens_acc"].std(ddof=1)),
                             f"ci95_mean_{na}": t_ci(ra["ens_acc"]), f"ci95_mean_{nb}": t_ci(rb["ens_acc"]),
                             "paired_diff_mean": float(dif.mean()), "paired_diff_sd": float(dif.std(ddof=1)),
                             "paired_diff_ci95_t": t_ci(dif),
                             "paired_t_p": float(stats.ttest_rel(rb["ens_acc"], ra["ens_acc"]).pvalue)
                             if np.any(dif != 0) else 1.0},
                "identical_table_pairs": {na: ra["identical_table_pairs"], nb: rb["identical_table_pairs"]},
                "layer1_rms_ensemble_over_eq2": {na: ra["layer1_ens_rms"] / ra["layer1_eq2_rms"],
                                                 nb: rb["layer1_ens_rms"] / rb["layer1_eq2_rms"]}}

    res = {"label": "SIMULATION (Python golden model sctpu.model, bit-exact per ARCHITECTURE.md 5 / 11)",
           "command": "cd code/python && ../../.venv/bin/python -m sctpu.compare_revs",
           "git_rev": rev, "spec": "ARCHITECTURE.md 5.3 (rev A seeds) vs section 11 (rev B seeds), ADR-008",
           "retrained": False, "variant": selv, "s": hw["s"], "n_test": int(len(te)),
           "dataset": sel["dataset"], "split": sel["split"], "training_seeds": sel["seeds"],
           "ev_Kinf_acc": ev_acc,
           "ensemble": {"numpy_seed": A.ENSEMBLE_SEED, "size": N_ENS, "offsets": [int(o) for o in offsets],
                        "note": "analysis-only start offsets applied to every LFSR of a revision "
                                "(keeps that revision's relative phases)"},
           "seeds": {"A": seed_info(*M.lane_seeds(2, "A")), "B": seed_info(*M.lane_seeds(2, "B")),
                     "C1": seed_info(*c1),
                     "modes01_X_W_distance_cycles": {"A": M.stream_distance_cycles(*[v[0] for v in M.lane_seeds(0, "A")]),
                                                     "B": M.stream_distance_cycles(*[v[0] for v in M.lane_seeds(0, "B")])}},
           "statistics": {"accuracy_ci": "95 % Wilson score interval",
                          "paired_hardware": "exact McNemar (two-sided binomial on discordant images); "
                                             "95 % CI of the paired difference: Newcombe 1998 method 10",
                          "paired_ensemble": "paired over the 20 offsets: mean difference, Student-t 95 % CI, paired t-test",
                          "multiplicity": "pre-specified: mode 2 at K=8 and K=9; other cells exploratory, uncorrected"},
           "A_vs_B": [compare("A", "B", mo, K) for mo in MODES for K in K_RANGE],
           "B_vs_C1_mode2": [compare("B", "C1", 2, K) for K in K_RANGE]}
    (REPORT_DIR / "revA_vs_revB.json").write_text(json.dumps(res, indent=1) + "\n")
    write_markdown(res)
    make_figure(res)
    print(f"# wrote reports/sw/revA_vs_revB.json/.md and fig_revA_vs_revB.pdf ({time.time() - t0:.1f} s)")
    return 0


# ---------------------------------------------------------------------------
# Report writers
# ---------------------------------------------------------------------------

def _pc(v: float) -> str:
    return f"{100 * v:.1f}"


def _ci(c: list) -> str:
    return f"[{100 * c[0]:.1f}, {100 * c[1]:.1f}]"


def _p(p: float) -> str:
    return f"{p:.3g}" if p >= 1e-4 else f"{p:.1e}"


def write_markdown(res: dict) -> None:
    """Human-readable comparison report (reports/sw/revA_vs_revB.md)."""
    L = []
    L.append("# SC-TPU accuracy: rev A vs rev B LFSR seeds (SW-02)")
    L.append("")
    L.append(f"Command: `{res['command']}` · git `{res['git_rev']}` · log `logs/sw/compare_revs.log`  ")
    L.append(f"All numbers: **SIMULATION** of the bit-exact Python golden model (`code/python/sctpu/model.py`), "
             f"test split of sklearn digits (stratified, seed 0), **n = {res['n_test']}** images, weights "
             f"`{res['variant']}` (s = {res['s']}) from SW-01a, **not retrained** (only the hardware seeds differ). "
             f"Expected-value model (K→∞) accuracy: {_pc(res['ev_Kinf_acc'])} %.  ")
    L.append(f"Ensemble: {res['ensemble']['size']} analysis-only LFSR start offsets (numpy `default_rng("
             f"{res['ensemble']['numpy_seed']})`, identical for both revisions): "
             + ", ".join(str(o) for o in res["ensemble"]["offsets"]) + ".  ")
    L.append("Statistics: " + "; ".join(f"{k}: {v}" for k, v in res["statistics"].items()) + ".")
    L.append("")
    L.append("## 1. Pre-specified tests (mode 2 INDEPENDENT, hardware seeds)")
    L.append("")
    L.append("| K | rev A acc % [95 % CI] (k/n) | rev B acc % [95 % CI] (k/n) | B − A pp [95 % CI] | discordant A-only / B-only | McNemar exact p |")
    L.append("|---|---|---|---|---|---|")
    for c in res["A_vs_B"]:
        if not c["prespecified"]:
            continue
        h = c["hardware_seeds"]
        L.append(f"| {c['K']} | {_pc(h['acc_A'])} {_ci(h['ci95_A'])} ({h['n_correct_A']}/{h['n']}) | "
                 f"{_pc(h['acc_B'])} {_ci(h['ci95_B'])} ({h['n_correct_B']}/{h['n']}) | "
                 f"{100 * h['diff_B_minus_A']:+.1f} {_ci(h['diff_ci95_newcombe'])} | "
                 f"{h['A_only_correct']} / {h['B_only_correct']} | {_p(h['mcnemar_exact_p'])} |")
    L.append("")
    L.append("## 2. All modes and K, hardware seeds (exploratory except the two rows above)")
    L.append("")
    L.append("| mode | K | rev A % [CI] | rev B % [CI] | B − A pp [Newcombe CI] | b / c | McNemar p |")
    L.append("|---|---|---|---|---|---|---|")
    for c in res["A_vs_B"]:
        h = c["hardware_seeds"]
        L.append(f"| {c['mode']} | {c['K']} | {_pc(h['acc_A'])} {_ci(h['ci95_A'])} | {_pc(h['acc_B'])} "
                 f"{_ci(h['ci95_B'])} | {100 * h['diff_B_minus_A']:+.1f} {_ci(h['diff_ci95_newcombe'])} | "
                 f"{h['A_only_correct']} / {h['B_only_correct']} | {_p(h['mcnemar_exact_p'])} |")
    L.append("")
    L.append("b = images correct only with rev A, c = correct only with rev B.")
    L.append("")
    L.append(f"## 3. Ensemble over {res['ensemble']['size']} LFSR start offsets (paired by offset)")
    L.append("")
    L.append("| mode | K | rev A mean ± sd % | rev B mean ± sd % | B − A mean pp [95 % t-CI] | paired t p |")
    L.append("|---|---|---|---|---|---|")
    for c in res["A_vs_B"]:
        e = c["ensemble"]
        L.append(f"| {c['mode']} | {c['K']} | {_pc(e['mean_A'])} ± {_pc(e['sd_A'])} | {_pc(e['mean_B'])} ± "
                 f"{_pc(e['sd_B'])} | {100 * e['paired_diff_mean']:+.2f} {_ci(e['paired_diff_ci95_t'])} | "
                 f"{_p(e['paired_t_p'])} |")
    L.append("")
    L.append("## 4. Structural cause of the rev B K = 9/10 degradation (mode 2)")
    L.append("")
    sA, sB, sC = res["seeds"]["A"], res["seeds"]["B"], res["seeds"]["C1"]
    L.append("CALCULATION (`seed_info`, `identical_table_pairs` in `code/python/sctpu/compare_revs.py`):")
    L.append("")
    L.append("| seed set | min pairwise distance [stream cycles] | X_i–W_i distance [cycles] | distinct pair offsets b_i − a_i |")
    L.append("|---|---|---|---|")
    for nm, s in (("rev A", sA), ("rev B", sB), ("C1 (analysis only)", sC)):
        L.append(f"| {nm} | {s['min_pairwise_distance_cycles']} | {', '.join(map(str, s['Xi_Wi_distance_cycles']))} | "
                 f"{s['n_distinct_pair_offsets']} of 8 |")
    L.append("")
    L.append("In rev B every X_i and W_i seed is advanced by the same 4096 single steps per lane, so the joint "
             "random pair (r_x,i+1(k), r_w,i+1(k)) = (r_x,i(k+512), r_w,i(k+512)): all 8 lanes carry ONE pair "
             "stream with 512-cycle delays (1 distinct pair offset of 8). When 512 cycles are a whole number of "
             "tiles (K ≤ 9) or a tile is a whole number of 512-cycle blocks (K = 10), whole XNOR count tables "
             "repeat across (tile, lane) slots, so the stochastic errors of those slots are identical functions "
             "of the codes and add coherently instead of averaging out (violates assumption A4 of the error model).")
    L.append("")
    L.append("| K | identical (tile, lane) table pairs per inference: rev A | rev B | C1 | layer-1 RMS ensemble / eq. (2): rev A | rev B | C1 |")
    L.append("|---|---|---|---|---|---|---|")
    ab = {c["K"]: c for c in res["A_vs_B"] if c["mode"] == 2}
    bc = {c["K"]: c for c in res["B_vs_C1_mode2"]}
    for K in K_RANGE:
        L.append(f"| {K} | {ab[K]['identical_table_pairs']['A']} | {ab[K]['identical_table_pairs']['B']} | "
                 f"{bc[K]['identical_table_pairs']['C1']} | {ab[K]['layer1_rms_ensemble_over_eq2']['A']:.2f} | "
                 f"{ab[K]['layer1_rms_ensemble_over_eq2']['B']:.2f} | {bc[K]['layer1_rms_ensemble_over_eq2']['C1']:.2f} |")
    L.append("")
    L.append("(3160 slot pairs exist per inference: 80 slots = 10 tiles × 8 lanes.)")
    L.append("")
    L.append("## 5. Analysis-only candidate C1 (NOT a spec revision): rev B with W lanes reversed")
    L.append("")
    L.append("W_i = S(32768 + 4096·(7 − i)); same 16 seed values as rev B, so the minimum pairwise distance "
             "stays 512 cycles, but every lane has a different X–W offset. Mode 2:")
    L.append("")
    L.append("| K | rev B hw % [CI] | C1 hw % [CI] | C1 − B pp [Newcombe CI] | McNemar p | rev B ens mean ± sd % | C1 ens mean ± sd % | C1 − B ens pp [t-CI] |")
    L.append("|---|---|---|---|---|---|---|---|")
    for c in res["B_vs_C1_mode2"]:
        h, e = c["hardware_seeds"], c["ensemble"]
        L.append(f"| {c['K']} | {_pc(h['acc_A'])} {_ci(h['ci95_A'])} | {_pc(h['acc_B'])} {_ci(h['ci95_B'])} | "
                 f"{100 * h['diff_B_minus_A']:+.1f} {_ci(h['diff_ci95_newcombe'])} | {_p(h['mcnemar_exact_p'])} | "
                 f"{_pc(e['mean_B'])} ± {_pc(e['sd_B'])} | {_pc(e['mean_C1'])} ± {_pc(e['sd_C1'])} | "
                 f"{100 * e['paired_diff_mean']:+.2f} {_ci(e['paired_diff_ci95_t'])} |")
    L.append("")
    L.append("(In this table column 'A' of the JSON entry is rev B and column 'B' is C1.)")
    L.append("")
    (REPORT_DIR / "revA_vs_revB.md").write_text("\n".join(L) + "\n")


def make_figure(res: dict) -> None:
    """fig_revA_vs_revB.pdf: accuracy vs K per mode, rev A vs rev B (hardware seeds + ensemble)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.grid": True, "grid.color": "#dddddd", "grid.linewidth": 0.6})
    col = {"A": "#2a78d6", "B": "#eb6834", "C1": "#1baf7a"}
    fig, axs = plt.subplots(1, 3, figsize=(11, 3.8), sharey=True)
    for ax, mode in zip(axs, MODES):
        rows = [c for c in res["A_vs_B"] if c["mode"] == mode]
        ks = [c["K"] for c in rows]
        ax.axhline(100 * res["ev_Kinf_acc"], color="#52514e", lw=1.0, label="expected value K→∞")
        for nm, key in (("A", "acc_A"), ("B", "acc_B")):
            ax.plot(ks, [100 * c["hardware_seeds"][key] for c in rows], color=col[nm], marker="o", ms=5, lw=2,
                    label=f"rev {nm} hardware seeds")
            m = np.array([100 * c["ensemble"][f"mean_{nm}"] for c in rows])
            s = np.array([100 * c["ensemble"][f"sd_{nm}"] for c in rows])
            ax.plot(ks, m, color=col[nm], lw=1.2, ls="--", label=f"rev {nm} ensemble mean (±1 sd band)")
            ax.fill_between(ks, m - s, m + s, color=col[nm], alpha=0.12, lw=0)
        if mode == 2:
            rows_c = res["B_vs_C1_mode2"]
            ax.plot(ks, [100 * c["hardware_seeds"]["acc_B"] for c in rows_c], color=col["C1"], marker="^",
                    ms=5, lw=1.5, label="C1 (analysis only) hardware seeds")
            ax.plot(ks, [100 * c["ensemble"]["mean_C1"] for c in rows_c], color=col["C1"], lw=1.2, ls=":",
                    label="C1 ensemble mean")
        ax.set_title(f"RNG_MODE {mode} {A.MODE_NAMES[mode]}")
        ax.set_xlabel("K = log2 L")
        ax.set_xticks(ks)
        ax.set_ylim(30, 100)
    axs[0].set_ylabel(f"test accuracy [%] (n={res['n_test']})")
    h, lb = axs[2].get_legend_handles_labels()
    fig.legend(h, lb, loc="lower center", ncol=4, fontsize=7, frameon=False)
    fig.suptitle(f"Rev A vs rev B LFSR seeds — SIMULATION, same weights ({res['variant']}), "
                 f"{res['ensemble']['size']} start offsets", fontsize=9)
    fig.tight_layout(rect=(0, 0.12, 1, 1))
    fig.savefig(REPORT_DIR / "fig_revA_vs_revB.pdf")
    plt.close(fig)


if __name__ == "__main__":
    sys.exit(main())
