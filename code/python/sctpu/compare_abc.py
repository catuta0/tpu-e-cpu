"""Rev A / rev B / rev C comparison of the SC-TPU accuracy on the TEST split (task SW-03, step 3).

Run only after the rev C seeds were fixed on validation data
(``sctpu.seed_select``, ``reports/sw/seed_selection_revC.md``). All numbers are
SIMULATION results of the bit-exact Python golden model on the 360 test images
of the stratified digits split (seed 0) with the SAME trained weights
(``qat_noise``, s = 0, SW-01a; not retrained). Only the LFSR seeds differ:

* rev A: ARCHITECTURE.md 5.3 (modes 0/1 X 0xACE1 / W 0x7A5C; mode 2 per-lane rule);
* rev B: ARCHITECTURE.md 11 (phase-spaced; superseded, ADR-009 defect);
* rev C: ADR-009 / SW-03 = rev A mode-2 seeds + rev B modes 0/1 pair.
  Consequently rev C is bit-identical to rev A in mode 2 and to rev B in modes
  0/1; the code asserts this on the per-image correctness vectors.

Pre-specified tests (assignment SW-03): mode 2, K = 8, 9, 10, hardware seeds,
exact McNemar rev C vs rev A and rev C vs rev B, with the 95 % Newcombe CI of
the paired difference. All other cells are exploratory (no multiplicity
correction). Ensemble: 20 analysis-only start offsets (numpy default_rng(0),
the SW-02 offsets), paired by offset (Student-t CI).

Outputs: ``reports/sw/revABC_comparison.json``, ``reports/sw/revABC_comparison.md``,
``reports/sw/fig_revABC_accuracy_vs_K.pdf`` (vector PDF). Log:
``logs/sw/compare_abc.log``.
Run: ``cd code/python && ../../.venv/bin/python -m sctpu.compare_abc``.
"""

from __future__ import annotations

import json
import sys
import time

import numpy as np
from scipy import stats

from . import accuracy as A
from . import compare_revs as CR
from . import model as M
from . import train as T

REPORT_DIR = T.REPORT_DIR
K_RANGE = A.K_RANGE
MODES = A.MODES
REVS = ("A", "B", "C")
N_ENS = 20
PRESPECIFIED_K = (8, 9, 10)  #: mode 2, rev C vs rev A and rev C vs rev B
DESIGN_TOLS = (0.01, 0.02)


def main() -> int:
    """Run every (rev, mode, K) configuration and write the JSON / Markdown / PDF outputs."""
    t0 = time.time()
    rev = T.git_rev()
    print(f"# compare_abc.py rev={rev} numpy={np.__version__} (SW-03 step 3, TEST split)")
    sel, allm = A.load_models()
    d = T.load_split()
    te = np.array(sel["test_indices"])
    assert np.array_equal(te, d["test_idx"])
    xc, y = d["codes"][te], d["y"][te]
    hw = A.hw_from_json(allm["models"][sel["variant"]])
    w1, w2 = M.unpack_weight_ram(hw["weight_ram"])
    offsets = A.ensemble_offsets(N_ENS, A.ENSEMBLE_SEED)
    print(f"# variant {sel['variant']} s={hw['s']} n_test={len(te)}; NOT retrained; offsets {[int(o) for o in offsets]}")
    raw = {r: {} for r in REVS}
    for r in REVS:
        for mode in MODES:
            for K in K_RANGE:
                raw[r][(mode, K)] = CR.run_config(xc, y, hw, K, mode, r, None, offsets, w1, w2, hw["biases"])
                rr = raw[r][(mode, K)]
                print(f"rev {r} mode {mode} K={K:2d} hw={rr['ok'].mean():.4f} ens={rr['ens_acc'].mean():.4f}"
                      f"+-{rr['ens_acc'].std(ddof=1):.4f} ident={rr['identical_table_pairs']} "
                      f"rms1 ens/eq2={rr['layer1_ens_rms'] / rr['layer1_eq2_rms']:.3f}", flush=True)
    # Structural identities of rev C (must hold exactly, bit for bit)
    for K in K_RANGE:
        assert np.array_equal(raw["C"][(2, K)]["ok"], raw["A"][(2, K)]["ok"])
        assert np.array_equal(raw["C"][(2, K)]["ens_acc"], raw["A"][(2, K)]["ens_acc"])
        for mode in (0, 1):
            assert np.array_equal(raw["C"][(mode, K)]["ok"], raw["B"][(mode, K)]["ok"])
            assert np.array_equal(raw["C"][(mode, K)]["ens_acc"], raw["B"][(mode, K)]["ens_acc"])
    ev = M.ev_inference(xc, hw["weight_ram"], hw["biases"], hw["s"])
    ev_acc = float(np.mean(ev["result"] == y))

    def compare(na: str, nb: str, mode: int, K: int) -> dict:
        ra, rb = raw[na][(mode, K)], raw[nb][(mode, K)]
        dif = rb["ens_acc"] - ra["ens_acc"]
        return {"A_rev": na, "B_rev": nb, "mode": mode, "K": K,
                "prespecified": mode == 2 and K in PRESPECIFIED_K and na in ("A", "B") and nb == "C",
                "hardware_seeds": CR.paired_cells(ra["ok"], rb["ok"]),
                "ensemble": {"paired_diff_mean": float(dif.mean()), "paired_diff_sd": float(dif.std(ddof=1)),
                             "paired_diff_ci95_t": CR.t_ci(dif) if np.any(dif != 0) else [0.0, 0.0],
                             "paired_t_p": float(stats.ttest_rel(rb["ens_acc"], ra["ens_acc"]).pvalue)
                             if np.any(dif != 0) else 1.0}}

    per = {r: {str(mo): {} for mo in MODES} for r in REVS}
    for r in REVS:
        for mo in MODES:
            for K in K_RANGE:
                rr = raw[r][(mo, K)]
                k = int(rr["ok"].sum())
                per[r][str(mo)][K] = {"deployed": {"acc": k / len(y), "n_correct": k, "n": int(len(y)),
                                                   "ci95": A.wilson_ci(k, len(y))},
                                      "ensemble_mean": float(rr["ens_acc"].mean()),
                                      "ensemble_sd": float(rr["ens_acc"].std(ddof=1)),
                                      "ensemble_min": float(rr["ens_acc"].min()),
                                      "ensemble_max": float(rr["ens_acc"].max()),
                                      "identical_table_pairs": rr["identical_table_pairs"],
                                      "layer1_rms_ensemble_over_eq2": rr["layer1_ens_rms"] / rr["layer1_eq2_rms"]}
    design = {r: {str(mo): {"deployed": A.design_rule({K: {"acc": per[r][str(mo)][K]["deployed"]["acc"]}
                                                       for K in K_RANGE}, ev_acc, DESIGN_TOLS),
                            "ensemble_mean": A.design_rule({K: {"acc": per[r][str(mo)][K]["ensemble_mean"]}
                                                            for K in K_RANGE}, ev_acc, DESIGN_TOLS)}
                  for mo in MODES} for r in REVS}
    res = {"label": "SIMULATION (Python golden model sctpu.model, bit-exact)",
           "command": "cd code/python && ../../.venv/bin/python -m sctpu.compare_abc",
           "git_rev": rev, "task": "SW-03 step 3 (test split, after the validation-only seed selection)",
           "seed_selection": "reports/sw/seed_selection_revC.json (selected C0 = rev A mode-2 seeds; validation only)",
           "retrained": False, "variant": sel["variant"], "s": hw["s"], "n_test": int(len(te)),
           "dataset": sel["dataset"], "split": sel["split"], "ev_Kinf_acc": ev_acc,
           "ensemble": {"numpy_seed": A.ENSEMBLE_SEED, "size": N_ENS, "offsets": [int(o) for o in offsets]},
           "seeds": {r: {"modes01_x": f"0x{M.lane_seeds(0, r)[0][0]:04X}", "modes01_w": f"0x{M.lane_seeds(0, r)[1][0]:04X}",
                         "mode2_x": [f"0x{v:04X}" for v in M.lane_seeds(2, r)[0]],
                         "mode2_w": [f"0x{v:04X}" for v in M.lane_seeds(2, r)[1]]} for r in REVS},
           "identities_asserted": "rev C == rev A in mode 2 and rev C == rev B in modes 0/1, per image and per "
                                  "ensemble offset (bit-exact, asserted in code)",
           "statistics": {"accuracy_ci": "95 % Wilson score interval",
                          "paired_hardware": "exact McNemar (two-sided) + 95 % Newcombe (1998, method 10) CI",
                          "paired_ensemble": "paired over the 20 offsets, Student-t 95 % CI",
                          "multiplicity": "pre-specified: mode 2 K=8,9,10, rev C vs A and rev C vs B; "
                                          "others exploratory, uncorrected"},
           "per_rev": per, "design_rule": design,
           "C_vs_A": [compare("A", "C", mo, K) for mo in MODES for K in K_RANGE],
           "C_vs_B": [compare("B", "C", mo, K) for mo in MODES for K in K_RANGE]}
    (REPORT_DIR / "revABC_comparison.json").write_text(json.dumps(res, indent=1) + "\n")
    write_markdown(res)
    make_figure(res)
    print(f"# wrote reports/sw/revABC_comparison.json/.md and fig_revABC_accuracy_vs_K.pdf ({time.time() - t0:.1f} s)")
    return 0


def _pc(v: float) -> str:
    return f"{100 * v:.1f}"


def write_markdown(res: dict) -> None:
    """reports/sw/revABC_comparison.md."""
    per, ev = res["per_rev"], res["ev_Kinf_acc"]
    L = ["# SC-TPU accuracy: rev A vs rev B vs rev C LFSR seeds (SW-03, test split)", "",
         f"Command: `{res['command']}` · git `{res['git_rev']}` · log `logs/sw/compare_abc.log`  ",
         f"All numbers: **SIMULATION** of the bit-exact Python golden model, test split of sklearn digits "
         f"(stratified, seed 0), **n = {res['n_test']}** images, weights `{res['variant']}` (s = {res['s']}), "
         f"not retrained. EV (K→∞) = {_pc(ev)} %.  ",
         f"Rev C seeds were selected beforehand on the 288 VALIDATION images only "
         f"(`reports/sw/seed_selection_revC.md`); the test split was first used in this step.  ",
         f"Ensemble: {res['ensemble']['size']} analysis-only start offsets (numpy `default_rng("
         f"{res['ensemble']['numpy_seed']})`, the SW-02 offsets).  ",
         f"Identity (asserted bit-exactly): {res['identities_asserted']}.", "",
         "## 1. Seeds", "", "| rev | modes 0/1 X / W | mode 2 X_0..7 | mode 2 W_0..7 |", "|---|---|---|---|"]
    for r, s in res["seeds"].items():
        L.append(f"| {r} | {s['modes01_x']} / {s['modes01_w']} | {' '.join(s['mode2_x'])} | {' '.join(s['mode2_w'])} |")
    L += ["", "## 2. Pre-specified tests: mode 2, hardware seeds, rev C vs rev A and rev C vs rev B", "",
          "| comparison | K | acc first % (k/n) | rev C % (k/n) [95 % CI] | C − first pp [Newcombe 95 % CI] | "
          "discordant first-only / C-only | McNemar exact p |", "|---|---|---|---|---|---|---|"]
    for key, nm in (("C_vs_A", "C vs A"), ("C_vs_B", "C vs B")):
        for c in res[key]:
            if not c["prespecified"]:
                continue
            h = c["hardware_seeds"]
            L.append(f"| {nm} | {c['K']} | {_pc(h['acc_A'])} ({h['n_correct_A']}/{h['n']}) | {_pc(h['acc_B'])} "
                     f"({h['n_correct_B']}/{h['n']}) [{_pc(h['ci95_B'][0])}, {_pc(h['ci95_B'][1])}] | "
                     f"{100 * h['diff_B_minus_A']:+.1f} [{100 * h['diff_ci95_newcombe'][0]:+.1f}, "
                     f"{100 * h['diff_ci95_newcombe'][1]:+.1f}] | {h['A_only_correct']} / {h['B_only_correct']} | "
                     f"{h['mcnemar_exact_p']:.3g} |")
    L += ["", "Rev C vs rev A in mode 2 is degenerate by construction (identical seeds, 0 discordant images); "
              "the Newcombe interval with b = c = 0 only reflects n. Rev C vs rev B in mode 2 repeats the SW-02 "
              "rev A vs rev B result with the sign reversed.",
          "", "## 3. Accuracy, all modes and K (deployed hardware seeds | ensemble mean ± sd) [%]", "",
          "| mode | K | rev A hw | rev B hw | rev C hw | rev A ens | rev B ens | rev C ens |", "|---|---|---|---|---|---|---|---|"]
    for mo in MODES:
        for K in K_RANGE:
            row = [per[r][str(mo)][K] for r in REVS]
            L.append(f"| {mo} | {K} | " + " | ".join(_pc(x["deployed"]["acc"]) for x in row) + " | "
                     + " | ".join(f"{_pc(x['ensemble_mean'])} ± {_pc(x['ensemble_sd'])}" for x in row) + " |")
    L += ["", "## 4. Design rule: smallest K within 1 pp | 2 pp of EV, holding for all larger K (first K in brackets if different)", "",
          "| rev | basis | mode 0 | mode 1 | mode 2 |", "|---|---|---|---|---|"]
    for r in REVS:
        for basis in ("deployed", "ensemble_mean"):
            cells = []
            for mo in MODES:
                dr = res["design_rule"][r][str(mo)][basis]
                parts = []
                for t in ("1pp", "2pp"):
                    a, b = dr[f"smallest_K_within_{t}_for_all_larger_K"], dr[f"smallest_K_within_{t}"]
                    parts.append(f"{a if a is not None else 'none'}" + (f" ({b})" if b != a else ""))
                cells.append(" \\| ".join(parts))
            L.append(f"| {r} | {basis.replace('_', ' ')} | " + " | ".join(cells) + " |")
    L += ["", "## 5. Structure and error model (mode 2)", "",
          "| K | identical table pairs A / B / C | layer-1 RMS ensemble / eq. (2): A / B / C |", "|---|---|---|"]
    for K in K_RANGE:
        x = [per[r]["2"][K] for r in REVS]
        ratios = " / ".join(f"{v['layer1_rms_ensemble_over_eq2']:.2f}" for v in x)
        idents = " / ".join(str(v["identical_table_pairs"]) for v in x)
        L.append(f"| {K} | {idents} | {ratios} |")
    L += ["", "## 6. Exploratory paired comparisons (all cells)", "",
          "| comparison | mode | K | hw diff pp | McNemar p | ens diff pp [t-CI] |", "|---|---|---|---|---|---|"]
    for key, nm in (("C_vs_A", "C − A"), ("C_vs_B", "C − B")):
        for c in res[key]:
            h, e = c["hardware_seeds"], c["ensemble"]
            L.append(f"| {nm} | {c['mode']} | {c['K']} | {100 * h['diff_B_minus_A']:+.1f} | {h['mcnemar_exact_p']:.3g} | "
                     f"{100 * e['paired_diff_mean']:+.2f} [{100 * e['paired_diff_ci95_t'][0]:+.2f}, "
                     f"{100 * e['paired_diff_ci95_t'][1]:+.2f}] |")
    (REPORT_DIR / "revABC_comparison.md").write_text("\n".join(L) + "\n")


def make_figure(res: dict) -> None:
    """fig_revABC_accuracy_vs_K.pdf: accuracy vs K per mode, revs A/B/C, hardware seeds + ensemble mean."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.grid": True, "grid.color": "#dddddd", "grid.linewidth": 0.6,
                         "pdf.fonttype": 42})
    col = {"A": "#2a78d6", "B": "#eb6834", "C": "#1baf7a"}
    mk = {"A": "o", "B": "s", "C": "^"}
    per = res["per_rev"]
    fig, axs = plt.subplots(1, 3, figsize=(11, 3.9), sharey=True)
    for ax, mo in zip(axs, MODES):
        ax.axhline(100 * res["ev_Kinf_acc"], color="#52514e", lw=1.0, label="expected value K→∞")
        for r in REVS:
            hwv = [100 * per[r][str(mo)][K]["deployed"]["acc"] for K in K_RANGE]
            m = np.array([100 * per[r][str(mo)][K]["ensemble_mean"] for K in K_RANGE])
            s = np.array([100 * per[r][str(mo)][K]["ensemble_sd"] for K in K_RANGE])
            # rev C overlays A (mode 2) or B (modes 0/1) exactly: drawn last, hollow, larger markers
            kw = dict(mfc="none", ms=9, mew=1.6, lw=1.4) if r == "C" else dict(ms=5, lw=2)
            ax.plot(K_RANGE, hwv, color=col[r], marker=mk[r], label=f"rev {r} deployed seeds", **kw)
            ax.plot(K_RANGE, m, color=col[r], lw=1.1, ls="--" if r != "C" else ":", label=f"rev {r} ensemble mean")
            if r != "C":
                ax.fill_between(K_RANGE, m - s, m + s, color=col[r], alpha=0.10, lw=0)
        ax.set_title(f"RNG_MODE {mo} {A.MODE_NAMES[mo]}" + (" (rev C = rev A)" if mo == 2 else " (rev C = rev B)"))
        ax.set_xlabel("K = log2 L")
        ax.set_xticks(K_RANGE)
        ax.set_ylim(30, 100)
    axs[0].set_ylabel(f"test accuracy [%] (n={res['n_test']})")
    h, lb = axs[2].get_legend_handles_labels()
    fig.legend(h, lb, loc="lower center", ncol=4, fontsize=7, frameon=False)
    fig.suptitle(f"Rev A / B / C LFSR seeds — SIMULATION, same weights ({res['variant']}), "
                 f"{res['ensemble']['size']} start offsets (±1 sd bands for A, B)", fontsize=9)
    fig.tight_layout(rect=(0, 0.12, 1, 1))
    fig.savefig(REPORT_DIR / "fig_revABC_accuracy_vs_K.pdf")
    plt.close(fig)


if __name__ == "__main__":
    sys.exit(main())
