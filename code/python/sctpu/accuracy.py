"""Accuracy and stochastic-error study of the SC-TPU (task SW-01a, deliverable 3).

All numbers produced here are SIMULATION results of the Python golden model
(``sctpu.model``), which is bit-exact with ARCHITECTURE.md section 5 by
construction and by the unit tests in ``code/python/tests/test_model.py``.

Study
-----
* Dataset: the 360 test images of the stratified split (seed 0, see train.py).
* Accuracy for every trained variant (``qat``, ``qat_noise``, ``float``-trained
  weights quantised post-training): float, expected value (K -> infinity),
  expected value at finite K, int8 binary baseline, bit-exact SC for
  K = 4..10 x RNG_MODE 0, 1, 2 (identical inputs for all configurations).
* Error of the stochastic estimate Dp/L versus its expectation, per K and
  mode, measured and predicted by the analytical model below.
* Design rule: smallest K whose SC accuracy is within 1 percentage point of
  the expected-value model (K -> infinity), per mode.

Analytical error model (also in reports/sw/error_model.md)
---------------------------------------------------------
Notation: spin s = 2b - 1 in {-1, +1} for a stream bit b; the XNOR product of
lane i is p_i = (1 + s_x,i s_w,i)/2. For a neuron j and one tile t:

Assumptions
  (A1) r is uniform on {0..255} in every stream cycle (the 16-bit LFSR never
       outputs state 0, so over a full period the low byte 0 occurs 255 times
       and every other value 256 times — a 0.4 % deviation, neglected);
  (A2) r values of different stream cycles are independent (leap-forward by
       8 steps, ADR-005), including lagged copies between different LFSRs;
  (A3) the X and W generators are independent of each other;
  (A4) mode 2: the generators of different lanes are independent.
Then E[s_x,i] = v_x,i and E[s_w,i] = v_w,i exactly (P(r < c) = c/256), and
with the lane-pair spin correlations C^x_ik = E[s_x,i s_x,k],
C^w_ik = E[s_w,i s_w,k] (C_ii = 1):

    Cov(p_i, p_k) = (C^x_ik C^w_ik - v_x,i v_w,i v_x,k v_w,k) / 4            (1)

    Var(Dp / L) = (1/L) * sum_t [ sum_{i,k} C^x_ik C^w_ik - (sum_i v_x,i v_w,i)^2 ]   (2)

(Dp = 2 acc - N_in L + B, B deterministic; acc is the sum of L independent
cycles per tile; tiles are independent under A2.) The correlations are, for
codes a (lane i) and b (lane k):
  mode 0 (shared r):      C = 1 - 2|a - b|/256  (P(bits differ) = |a-b|/256);
  mode 1 (rotated r):     C = (1/256) sum_r s(rotl8(r,i) < a) s(rotl8(r,k) < b), exact enumeration;
  mode 2 (independent):   C = v_a v_b for i != k, so (2) reduces to
    Var(Dp / L) = (1/L) * sum_i (1 - v_x,i^2 v_w,i^2)                         (3)
Equation (3) is also reported for modes 0/1 as the "independent-stream"
reference, to show the cost of sharing random numbers.
The predicted RMS error is sqrt(mean over images and neurons of (2)).
For layer 2 the inputs are the hidden codes produced by the SC layer 1 of the
same run (conditional error of layer 2 alone).
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import numpy as np

from . import lfsr
from . import model as M
from . import train as T

ROOT = T.ROOT
REPORT_DIR = T.REPORT_DIR
DATA_DIR = T.DATA_DIR
K_RANGE = list(range(M.K_MIN, M.K_MAX + 1))
MODES = list(M.RNG_MODES)
MODE_NAMES = {0: "SHARED", 1: "ROTATE", 2: "INDEPENDENT"}


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------

def wilson_ci(k: int, n: int, z: float = 1.959964) -> list:
    """95 % Wilson score interval of a binomial proportion k/n (CALCULATION)."""
    if n == 0:
        return [float("nan"), float("nan")]
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [c - h, c + h]


def acc_entry(pred: np.ndarray, y: np.ndarray) -> dict:
    """Accuracy, correct count, sample count and 95 % Wilson CI."""
    k = int(np.sum(pred == y))
    return {"acc": k / len(y), "n_correct": k, "n": int(len(y)), "ci95": wilson_ci(k, len(y))}


# ---------------------------------------------------------------------------
# Analytical variance model, equations (1)-(3)
# ---------------------------------------------------------------------------

def spin_table(mode: int) -> np.ndarray:
    """S[i, r, c] = 2*[R_i(r) < c] - 1 for lane i, r in 0..255, code c in 0..255.

    R_i(r) is the lane transform of the shared random number: identity for
    mode 0, rotl8(r, i) for mode 1 (ARCHITECTURE.md 5.3). Not used for mode 2.
    """
    r = np.arange(256)
    c = np.arange(256)
    S = np.empty((M.IL, 256, 256), np.float64)
    for i in range(M.IL):
        ri = r if mode == 0 else np.array([M.rotl8(int(v), i) for v in r])
        S[i] = np.where(ri[:, None] < c[None, :], 1.0, -1.0)
    return S


def lane_correlations(codes: np.ndarray, mode: int, S: np.ndarray | None) -> np.ndarray:
    """Spin correlation matrices C[n, t, i, k] for codes (n, 8*T) under ``mode``.

    Mode 0/1: C = (1/256) sum_r S[i, r, a] S[k, r, b] (exact under A1).
    Mode 2  : C_ik = v_a v_b for i != k, 1 on the diagonal (A4).
    """
    n, n_in = codes.shape
    T_ = n_in // M.IL
    c = codes.reshape(n, T_, M.IL)
    if mode == 2:
        v = M.code_value(c)
        C = v[:, :, :, None] * v[:, :, None, :]
        idx = np.arange(M.IL)
        C[:, :, idx, idx] = 1.0
        return C
    lanes = np.arange(M.IL)[None, None, :]
    Mx = S[lanes, :, c]                     # (n, T, IL, 256): S[i, r, c[n,t,i]]
    return np.einsum("ntir,ntkr->ntik", Mx, Mx) / 256.0


def predicted_variance(x: np.ndarray, w: np.ndarray, K: int, mode: int,
                       S: np.ndarray | None) -> tuple[np.ndarray, np.ndarray]:
    """Predicted Var(Dp/L) per (image, neuron): (general eq. (2), independent eq. (3)).

    x : (N, n_in) input codes of the layer; w : (J, n_in) weight codes.
    """
    L = 1 << K
    n, n_in = x.shape
    T_ = n_in // M.IL
    Cx = lane_correlations(x, mode, S)
    Cw = lane_correlations(w, mode, S)
    vx = M.code_value(x).reshape(n, T_, M.IL)
    vw = M.code_value(w).reshape(len(w), T_, M.IL)
    cross = np.einsum("ntik,jtik->nj", Cx, Cw)
    mean_t = np.einsum("nti,jti->njt", vx, vw)            # sum_i v_x v_w per tile
    var_gen = (cross - (mean_t ** 2).sum(axis=2)) / L
    var_ind = (n_in - (vx.reshape(n, n_in) ** 2) @ (vw.reshape(len(w), n_in) ** 2).T) / L
    return var_gen, var_ind


# ---------------------------------------------------------------------------
# LFSR phase relations (supports assumption A2/A3)
# ---------------------------------------------------------------------------

def lfsr_lags() -> dict:
    """Stream-cycle lags between all LFSRs (CALCULATION).

    All LFSRs share one m-sequence of period 65535. If seed b lies d single
    steps after seed a, then r_b(k) = r_a(k + m) with m = d * 8^-1 mod 65535
    (8 is invertible mod 65535), i.e. every LFSR is a lagged copy of every
    other one. A lag shorter than the cycles of one layer can create
    correlations that the error model (A2) ignores.
    """
    pos, st = {}, M.SEED_X
    for n in range(lfsr.MAX_PERIOD):
        pos[st] = n
        st = lfsr.step(st)
    inv8 = pow(8, -1, lfsr.MAX_PERIOD)

    def lag(a, b):
        m = ((pos[b] - pos[a]) % lfsr.MAX_PERIOD) * inv8 % lfsr.MAX_PERIOD
        return int(min(m, lfsr.MAX_PERIOD - m))

    sx, sw = M.lane_seeds(2)
    names = [f"X{i}" for i in range(M.IL)] + [f"W{i}" for i in range(M.IL)]
    seeds = sx + sw
    pairs = sorted((lag(seeds[a], seeds[b]), names[a], names[b])
                   for a in range(16) for b in range(a + 1, 16))
    return {"modes01_X_W_lag_cycles": lag(M.SEED_X, M.SEED_W),
            "mode2_smallest_lags": [{"lag_cycles": p[0], "pair": [p[1], p[2]]} for p in pairs[:8]],
            "max_cycles_per_inference_K10": M.N_TILES_TOTAL << M.K_MAX,
            "label": "CALCULATION (exhaustive walk of the 65535-state m-sequence)"}


# ---------------------------------------------------------------------------
# Main study
# ---------------------------------------------------------------------------

def load_models() -> tuple[dict, dict]:
    """Return (model_params.json content, trained_models.json content)."""
    sel = json.loads((DATA_DIR / "model_params.json").read_text())
    allm = json.loads((REPORT_DIR / "trained_models.json").read_text())
    return sel, allm


def hw_from_json(m: dict) -> dict:
    """Weight RAM and BIAS images from a stored parameter set (5.4, 5.5)."""
    return {"weight_ram": M.pack_weight_ram(np.array(m["w1_codes"]), np.array(m["w2_codes"])),
            "biases": M.pack_biases(m["b1_int16"], m["b2_int16"]), "s": int(m["s"])}


def design_rule(sc: dict, ev_acc: float, tol: float = 0.01) -> dict:
    """Smallest K with acc_SC(K) >= acc_EV - tol (literal) and the monotone variant."""
    ks = sorted(int(k) for k in sc)
    first = next((k for k in ks if sc[k]["acc"] >= ev_acc - tol - 1e-12), None)
    mono = None
    for k in ks:
        if all(sc[k2]["acc"] >= ev_acc - tol - 1e-12 for k2 in ks if k2 >= k):
            mono = k
            break
    return {"smallest_K_within_1pp": first, "smallest_K_within_1pp_for_all_larger_K": mono}


ENSEMBLE_SIZE = 16  #: number of analysis-only random LFSR start offsets
ENSEMBLE_SEED = 0  #: numpy seed of the start offsets


def error_arrays(r: dict, xc, w1, w2, b, K: int, mode: int, S) -> dict:
    """Per (image, neuron) errors of Dp/L and predicted variances, both layers.

    e = (Dp - B)/L - P/2^14, i.e. Dp/L minus its expectation E[Dp]/L at this K
    (the deterministic bias term B is removed). Layer 2 uses the hidden codes
    of the same SC run as inputs (conditional error of layer 2 alone).
    """
    L = 1 << K
    P1 = (xc - 128) @ (w1 - 128).T
    B1 = (b[None, :16] << K) >> 7
    e1 = (r["dp1"] - B1) / L - P1 / 16384.0
    e1_tot = r["dp1"] / L - (P1 / 16384.0 + b[None, :16] / 128.0)
    h = r["hidden"]
    P2 = (h - 128) @ (w2 - 128).T
    B2 = (b[None, 16:] << K) >> 7
    e2 = (r["dp2"] - B2) / L - P2 / 16384.0
    vg1, vi1 = predicted_variance(xc, w1, K, mode, S)
    vg2, vi2 = predicted_variance(h, w2, K, mode, S)
    return {"layer1": {"e": e1, "vg": vg1, "vi": vi1, "e_tot": e1_tot},
            "layer2": {"e": e2, "vg": vg2, "vi": vi2}}


def error_entry(r: dict, xc, w1, w2, b, K: int, mode: int, S) -> dict:
    """Summary statistics (RMS, mean, predictions) for one SC run."""
    raw = error_arrays(r, xc, w1, w2, b, K, mode, S)
    ent = {}
    for name, lay, sl in (("layer1", "layer1", slice(0, 16)),
                          ("layer2_real", "layer2", slice(0, 10)),
                          ("layer2_padding", "layer2", slice(10, 16))):
        ee = raw[lay]["e"][:, sl]
        ent[name] = {"n_samples": int(ee.size),
                     "rms_measured": float(np.sqrt(np.mean(ee ** 2))),
                     "mean_measured": float(np.mean(ee)),
                     "rms_predicted_eq2": float(np.sqrt(np.mean(raw[lay]["vg"][:, sl]))),
                     "rms_predicted_eq3_independent": float(np.sqrt(np.mean(raw[lay]["vi"][:, sl])))}
        ent[name]["ratio_measured_over_eq2"] = ent[name]["rms_measured"] / ent[name]["rms_predicted_eq2"]
    ent["layer1"]["rms_total_vs_Kinf"] = float(np.sqrt(np.mean(raw["layer1"]["e_tot"] ** 2)))
    return ent


def main() -> int:
    """Run the full study, write reports/sw/accuracy.json and the PDF figures."""
    t0 = time.time()
    rev = T.git_rev()
    print(f"# accuracy.py rev={rev} numpy={np.__version__}")
    sel, allm = load_models()
    d = T.load_split()
    te = np.array(sel["test_indices"])
    assert np.array_equal(te, d["test_idx"]), "test split differs from model_params.json"
    xc, y = d["codes"][te], d["y"][te]
    print(f"# test images: {len(te)}, seeds {sel['seeds']}, selected variant {sel['variant']} "
          f"s={sel['act_shift_s']}")

    variants = ["qat", "qat_noise", "float"]
    hws = {v: hw_from_json(allm["models"][v]) for v in variants}
    res = {"label": "SIMULATION (Python golden model sctpu.model, bit-exact per ARCHITECTURE.md 5)",
           "command": "cd code/python && ../../.venv/bin/python -m sctpu.accuracy",
           "git_rev": rev, "spec_rev": "ece09f0 (ARCHITECTURE.md rev A, unchanged at run time)",
           "dataset": sel["dataset"], "split": sel["split"], "seeds": sel["seeds"],
           "n_test": int(len(te)), "selected_variant": sel["variant"],
           "selected_s": sel["act_shift_s"], "K_range": K_RANGE, "modes": MODE_NAMES,
           "models": {}}

    # ---- deterministic models ---------------------------------------------
    xv = T.code_values(xc)
    for v in variants:
        m = allm["models"][v]
        hw = hws[v]
        fl = M.float_inference(xv, np.array(m["W1"]), np.array(m["b1"]), np.array(m["W2"]),
                               np.array(m["b2"]), hw["s"])
        ev = M.ev_inference(xc, hw["weight_ram"], hw["biases"], hw["s"])
        i8 = M.int8_inference(xc, hw["weight_ram"], hw["biases"], hw["s"])
        mism = int(np.sum(i8["result"] != ev["result"]) + np.sum(i8["hidden"] != ev["hidden"])
                   + np.sum(i8["score"] != ev["score"]))
        res["models"][v] = {
            "s": hw["s"],
            "description": {"qat": "quantisation-aware training (STE)",
                            "qat_noise": "QAT + SC-like Gaussian noise (K_train=8) in training",
                            "float": "float training, codes by post-training rounding"}[v],
            "float_master_weights": acc_entry(fl["result"], y),
            "expected_value_Kinf": acc_entry(ev["result"], y),
            "int8_binary": acc_entry(i8["result"], y),
            "int8_vs_ev_mismatches_hidden_score_result": mism,
            "expected_value_finite_K": {}, "sc": {str(mo): {} for mo in MODES}}
        for K in K_RANGE:
            evk = M.ev_inference(xc, hw["weight_ram"], hw["biases"], hw["s"], K=K)
            res["models"][v]["expected_value_finite_K"][K] = acc_entry(evk["result"], y)
    m = allm["models"]["float_at_hw_s"]
    fl = M.float_inference(xv, np.array(m["W1"]), np.array(m["b1"]), np.array(m["W2"]),
                           np.array(m["b2"]), int(m["s"]))
    res["float_trained_at_hw_s"] = dict(acc_entry(fl["result"], y), s=int(m["s"]))
    m = allm["models"]["float"]
    fl = M.float_inference(xv, np.array(m["W1"]), np.array(m["b1"]), np.array(m["W2"]),
                           np.array(m["b2"]), int(m["s"]))
    res["float_trained_best_val_s"] = dict(acc_entry(fl["result"], y), s=int(m["s"]))

    # ---- SC sweep + error study ---------------------------------------------
    err = {str(mo): {} for mo in MODES}
    selv = sel["variant"]
    hw_sel = hws[selv]
    w1, w2 = M.unpack_weight_ram(hw_sel["weight_ram"])
    b = hw_sel["biases"]
    ens_rng = np.random.default_rng(ENSEMBLE_SEED)
    ens_offsets = ens_rng.integers(1, lfsr.MAX_PERIOD, ENSEMBLE_SIZE)
    ens_acc = {str(mo): {} for mo in MODES}
    for mode in MODES:
        S = spin_table(mode) if mode != 2 else None
        for K in K_RANGE:
            eng = M.SCEngine(K, mode)  # not cached: ~10 MB per engine
            for v in variants:
                hw = hws[v]
                r = eng.run(xc, hw["weight_ram"], hw["biases"], hw["s"])
                res["models"][v]["sc"][str(mode)][K] = acc_entry(r["result"], y)
                if v == selv:
                    rsel = r
            ent = error_entry(rsel, xc, w1, w2, b, K, mode, S)
            # Ensemble over analysis-only LFSR start offsets (not hardware
            # behaviour): validates eq. (2) as an expectation over random
            # realisations, and shows the realisation-to-realisation spread
            # of the accuracy that a single fixed seed set hides.
            sq = {k: [] for k in ("layer1", "layer2_real")}
            pr = {k: [] for k in ("layer1", "layer2_real")}
            accs = []
            for off in ens_offsets:
                ee = M.SCEngine(K, mode, start_offset=int(off)).run(
                    xc, hw_sel["weight_ram"], hw_sel["biases"], hw_sel["s"])
                accs.append(float(np.mean(ee["result"] == y)))
                raw = error_arrays(ee, xc, w1, w2, b, K, mode, S)
                for name, sl in (("layer1", slice(0, 16)), ("layer2_real", slice(0, 10))):
                    lay = "layer1" if name == "layer1" else "layer2"
                    sq[name].append(np.mean(raw[lay]["e"][:, sl] ** 2))
                    pr[name].append(np.mean(raw[lay]["vg"][:, sl]))
            for name in sq:
                ent[name]["ensemble_rms_measured"] = float(np.sqrt(np.mean(sq[name])))
                ent[name]["ensemble_rms_predicted_eq2"] = float(np.sqrt(np.mean(pr[name])))
                ent[name]["ensemble_ratio"] = ent[name]["ensemble_rms_measured"] / ent[name]["ensemble_rms_predicted_eq2"]
                ent[name]["single_realisation_rms_min_max"] = [float(np.sqrt(min(sq[name]))),
                                                               float(np.sqrt(max(sq[name])))]
            ens_acc[str(mode)][K] = {"mean": float(np.mean(accs)), "std": float(np.std(accs, ddof=1)),
                                     "min": float(min(accs)), "max": float(max(accs)),
                                     "n_realisations": len(accs)}
            err[str(mode)][K] = ent
            print(f"mode {mode} K={K:2d} acc[{selv}]={res['models'][selv]['sc'][str(mode)][K]['acc']:.4f} "
                  f"ens acc={ens_acc[str(mode)][K]['mean']:.4f}+-{ens_acc[str(mode)][K]['std']:.4f} | "
                  f"rms1 hw={ent['layer1']['rms_measured']:.4f} ens={ent['layer1']['ensemble_rms_measured']:.4f} "
                  f"pred={ent['layer1']['rms_predicted_eq2']:.4f} | "
                  f"rms2 hw={ent['layer2_real']['rms_measured']:.4f} ens={ent['layer2_real']['ensemble_rms_measured']:.4f} "
                  f"pred={ent['layer2_real']['rms_predicted_eq2']:.4f}", flush=True)
            del eng
    res["error_study"] = {"variant": selv, "quantity": "Dp/L - E[Dp]/L (B removed); units of the bipolar value",
                          "hardware_seeds": "rms_measured / mean_measured: the fixed seeds of 5.3 (one realisation)",
                          "ensemble": f"{ENSEMBLE_SIZE} analysis-only LFSR start offsets, rng seed {ENSEMBLE_SEED}: "
                                      + ", ".join(str(int(o)) for o in ens_offsets),
                          "per_mode_K": err}
    res["models"][selv]["sc_ensemble_accuracy"] = ens_acc
    ev_sel = res["models"][selv]["expected_value_Kinf"]["acc"]
    res["models"][selv]["design_rule_ensemble_mean"] = {
        mo: design_rule({K: {"acc": ens_acc[mo][K]["mean"]} for K in K_RANGE}, ev_sel) for mo in ens_acc}
    for v in variants:
        ev_acc = res["models"][v]["expected_value_Kinf"]["acc"]
        res["models"][v]["design_rule"] = {str(mo): design_rule(res["models"][v]["sc"][str(mo)], ev_acc)
                                           for mo in MODES}
    res["lfsr_lags"] = lfsr_lags()
    res["value_ranges"] = M.value_ranges()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "accuracy.json").write_text(json.dumps(res, indent=1) + "\n")
    print_table(res)
    make_figures(res)
    print(f"# wrote {REPORT_DIR/'accuracy.json'} and figures ({time.time()-t0:.1f} s)")
    return 0


def print_table(res: dict) -> None:
    """Human-readable accuracy table on stdout (copied into the log)."""
    for v, mr in res["models"].items():
        print(f"\n## variant {v} (s={mr['s']}), test n={res['n_test']}  [SIMULATION]")
        print(f"float(master)={mr['float_master_weights']['acc']:.4f}  EV(K->inf)={mr['expected_value_Kinf']['acc']:.4f}"
              f"  int8={mr['int8_binary']['acc']:.4f}  int8-vs-EV mismatches={mr['int8_vs_ev_mismatches_hidden_score_result']}")
        print("K   EV(K)   SC m0   SC m1   SC m2")
        for K in K_RANGE:
            row = [mr["expected_value_finite_K"][K]["acc"]] + [mr["sc"][str(mo)][K]["acc"] for mo in MODES]
            print(f"{K:<3d} " + "  ".join(f"{a:.4f}" for a in row))
        print("design rule (smallest K within 1 pp of EV; monotone):",
              {mo: (dr["smallest_K_within_1pp"], dr["smallest_K_within_1pp_for_all_larger_K"])
               for mo, dr in mr["design_rule"].items()})


def make_figures(res: dict) -> None:
    """PDF figures: accuracy vs K, RMS error vs K (measured vs predicted), s sweep."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Reference categorical palette (dataviz skill, slots 1-3) for the 3 modes.
    col = {0: "#2a78d6", 1: "#eb6834", 2: "#1baf7a"}
    mk = {0: "o", 1: "s", 2: "^"}
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.grid": True, "grid.color": "#dddddd", "grid.linewidth": 0.6})

    # 1. accuracy vs K, one panel per variant
    vs = ["qat_noise", "qat", "float"]
    fig, axs = plt.subplots(1, 3, figsize=(11, 3.8), sharey=True)
    for ax, v in zip(axs, vs):
        mr = res["models"][v]
        ev = mr["expected_value_Kinf"]["acc"] * 100
        ax.axhline(ev, color="#52514e", lw=1.2, label=f"expected value K→∞ ({ev:.1f} %)")
        ax.axhspan(ev - 1, ev, color="#52514e", alpha=0.10, lw=0, label="within 1 pp of EV")
        fl = mr["float_master_weights"]["acc"] * 100
        ax.axhline(fl, color="#52514e", lw=1.0, ls=":", label=f"float ({fl:.1f} %)")
        for mo in MODES:
            a = [mr["sc"][str(mo)][K]["acc"] * 100 for K in K_RANGE]
            lo = [mr["sc"][str(mo)][K]["ci95"][0] * 100 for K in K_RANGE]
            hi = [mr["sc"][str(mo)][K]["ci95"][1] * 100 for K in K_RANGE]
            ax.plot(K_RANGE, a, color=col[mo], marker=mk[mo], ms=5, lw=2,
                    label=f"SC mode {mo} {MODE_NAMES[mo]}")
            ax.fill_between(K_RANGE, lo, hi, color=col[mo], alpha=0.12, lw=0)
            if "sc_ensemble_accuracy" in mr:  # selected model: ensemble mean (analysis-only)
                ea = [mr["sc_ensemble_accuracy"][str(mo)][K]["mean"] * 100 for K in K_RANGE]
                ax.plot(K_RANGE, ea, color=col[mo], lw=1.2, ls="--",
                        label=f"mode {mo} mean of 16 random LFSR offsets")
        ax.set_title(f"weights: {v} (s={mr['s']})")
        ax.set_xlabel("K = log2 L")
        ax.set_xticks(K_RANGE)
    axs[0].set_ylabel("test accuracy [%] (n=360)")
    axs[0].set_ylim(0, 100)
    handles, labels = axs[0].get_legend_handles_labels()
    labels = [lb.split(" (")[0] if lb.startswith(("expected", "float")) else lb for lb in labels]
    fig.legend(handles, labels, loc="lower center", ncol=5, fontsize=7, frameon=False)
    fig.suptitle("SC-TPU accuracy vs stream length — SIMULATION (bit-exact golden model, "
                 "digits test split seed 0, n=360); bands = 95 % Wilson CI", fontsize=9)
    fig.tight_layout(rect=(0, 0.13, 1, 1))
    fig.savefig(REPORT_DIR / "fig_accuracy_vs_K.pdf")
    plt.close(fig)

    # 2. RMS error vs K, measured (markers) vs predicted (lines)
    es = res["error_study"]["per_mode_K"]
    fig, axs = plt.subplots(1, 2, figsize=(9, 3.6), sharey=True)
    for ax, layer, title in ((axs[0], "layer1", "layer 1 (64 inputs)"),
                             (axs[1], "layer2_real", "layer 2 (16 inputs, lanes 0..9)")):
        for mo in MODES:
            meas = [es[str(mo)][K][layer]["rms_measured"] for K in K_RANGE]
            pred = [es[str(mo)][K][layer]["rms_predicted_eq2"] for K in K_RANGE]
            ax.plot(K_RANGE, pred, color=col[mo], lw=2, label=f"mode {mo} predicted, eq. (2)")
            ax.plot(K_RANGE, meas, color=col[mo], marker=mk[mo], ms=6, lw=0,
                    label=f"mode {mo} measured, hardware seeds")
            ens = [es[str(mo)][K][layer]["ensemble_rms_measured"] for K in K_RANGE]
            ax.plot(K_RANGE, ens, color=col[mo], marker=mk[mo], ms=8, lw=0, mfc="none", mew=1.5,
                    label=f"mode {mo} measured, 16 random offsets")
        ax.set_yscale("log", base=2)
        ax.set_title(title)
        ax.set_xlabel("K = log2 L")
        ax.set_xticks(K_RANGE)
    axs[0].set_ylabel("RMS of Dp/L − E[Dp]/L")
    axs[1].legend(fontsize=6, frameon=False, loc="upper right", ncol=1)
    fig.suptitle(f"Stochastic error, weights {res['error_study']['variant']} — SIMULATION vs analytical model",
                 fontsize=9)
    fig.tight_layout()
    fig.savefig(REPORT_DIR / "fig_rms_error_vs_K.pdf")
    plt.close(fig)

    # 3. s sweep (validation)
    sw = json.loads((REPORT_DIR / "s_sweep.json").read_text())
    fig, axs = plt.subplots(1, 2, figsize=(8, 3.1), sharey=True)
    vcol = {"float": "#2a78d6", "qat": "#eb6834", "qat_noise": "#1baf7a"}
    for ax, metric, title in ((axs[0], "ev", "expected value (K→∞)"),
                              (axs[1], "sc_K8_m1", "bit-exact SC, K=8, mode 1")):
        for v in ("float", "qat", "qat_noise"):
            rows = sorted((r for r in sw["sweep"] if r["variant"] == v), key=lambda r: r["s"])
            ax.plot([r["s"] for r in rows], [r["val"][metric] * 100 for r in rows], marker="o",
                    ms=5, lw=2, color=vcol[v], label=v)
        ax.set_title(title)
        ax.set_xlabel("ACT_SHIFT s")
    axs[0].set_ylabel("validation accuracy [%] (n=288)")
    axs[0].legend(fontsize=7, frameon=False)
    fig.suptitle("Activation-shift sweep — SIMULATION (validation split of the 1437 training images)",
                 fontsize=9)
    fig.tight_layout()
    fig.savefig(REPORT_DIR / "fig_s_sweep.pdf")
    plt.close(fig)


if __name__ == "__main__":
    sys.exit(main())
