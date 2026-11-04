"""Accuracy and stochastic-error study of the SC-TPU (tasks SW-01a, SW-02, SW-03).

SW-03: default ``--spec-rev C`` (ADR-009) writes ``accuracy_revC.json`` and
the un-suffixed figures; the rev B figures of SW-02 were kept as
``fig_*_revB.pdf``. Re-runs of A/B write ``*_rev<X>_rerun.*``.
SW-02: the study is parametrised by the LFSR seed rule (``--spec-rev``,
then default ``B`` = ARCHITECTURE.md section 11) and the ensemble size
(``--ensemble-size``, default 20 >= REQ-AI-006). The network is NOT retrained:
the weights are those of ``sim/data/model_params.json`` / ``trained_models.json``.
Rev B output: ``reports/sw/accuracy_revB.json`` and the figures
``fig_accuracy_vs_K.pdf`` / ``fig_rms_error_vs_K.pdf`` (rev A copies carry the
suffix ``_revA``). ``--spec-rev A`` writes ``accuracy_revA_rerun.json`` and
``*_revA_rerun.pdf`` (never overwrites the original rev A results).

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
* Design rule: smallest K whose SC accuracy is within 1 (and 2) percentage
  points of the expected-value model (K -> infinity), per mode.

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

import argparse
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

def lfsr_lags(spec_rev: str = M.DEFAULT_SPEC_REV) -> dict:
    """Stream-cycle lags between all LFSRs (CALCULATION).

    All LFSRs share one m-sequence of period 65535. If seed b lies d single
    steps after seed a, then r_b(k) = r_a(k + m) with m = d * 8^-1 mod 65535
    (8 is invertible mod 65535), i.e. every LFSR is a lagged copy of every
    other one. A lag shorter than the cycles of one layer can create
    correlations that the error model (A2) ignores.
    """
    lag = M.stream_distance_cycles  # min(m, 65535 - m), m = d * inv(8) mod 65535
    sx, sw = M.lane_seeds(2, spec_rev)
    (x01,), (w01,) = M.lane_seeds(0, spec_rev)
    names = [f"X{i}" for i in range(M.IL)] + [f"W{i}" for i in range(M.IL)]
    seeds = sx + sw
    pairs = sorted((lag(seeds[a], seeds[b]), names[a], names[b])
                   for a in range(16) for b in range(a + 1, 16))
    return {"spec_rev": spec_rev,
            "modes01_X_W_lag_cycles": lag(x01, w01),
            "mode2_smallest_lags": [{"lag_cycles": p[0], "pair": [p[1], p[2]]} for p in pairs[:8]],
            "mode2_min_pairwise_lag_cycles": pairs[0][0],
            "mode2_Xi_Wi_lag_cycles": [lag(sx[i], sw[i]) for i in range(M.IL)],
            "cycles_per_layer1_by_K": {K: M.TILES[0] << K for K in K_RANGE},
            "cycles_per_inference_by_K": {K: M.N_TILES_TOTAL << K for K in K_RANGE},
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


def design_rule(sc: dict, ev_acc: float, tols=(0.01, 0.02)) -> dict:
    """Smallest K with acc_SC(K) >= acc_EV - tol (literal) and the monotone variant.

    For every tolerance in ``tols`` (fractions; 0.01 = 1 pp) two keys are
    returned: ``smallest_K_within_<n>pp`` (first K that meets the bound) and
    ``smallest_K_within_<n>pp_for_all_larger_K`` (K_op of REQ-AI-005: the
    bound holds for this K and every larger K up to 10). None = never met.
    """
    ks = sorted(int(k) for k in sc)
    out = {}
    for tol in tols:
        tag = f"{round(tol * 100)}pp"
        first = next((k for k in ks if sc[k]["acc"] >= ev_acc - tol - 1e-12), None)
        mono = None
        for k in ks:
            if all(sc[k2]["acc"] >= ev_acc - tol - 1e-12 for k2 in ks if k2 >= k):
                mono = k
                break
        out[f"smallest_K_within_{tag}"] = first
        out[f"smallest_K_within_{tag}_for_all_larger_K"] = mono
    return out


ENSEMBLE_SIZE = 20  #: number of analysis-only random LFSR start offsets (REQ-AI-006: >= 20)
ENSEMBLE_SEED = 0  #: numpy seed of the start offsets (first 16 = the SW-01a rev A offsets)


def ensemble_offsets(n: int = ENSEMBLE_SIZE, seed: int = ENSEMBLE_SEED) -> np.ndarray:
    """Analysis-only LFSR start offsets (single steps, 1..65534), default_rng(seed)."""
    return np.random.default_rng(seed).integers(1, lfsr.MAX_PERIOD, n)


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


def main(argv=None) -> int:
    """Run the full study, write reports/sw/accuracy_rev<X>.json and the PDF figures."""
    ap = argparse.ArgumentParser(description="SC-TPU accuracy / error study (SIMULATION)")
    ap.add_argument("--spec-rev", choices=M.SPEC_REVS, default=M.DEFAULT_SPEC_REV)
    ap.add_argument("--ensemble-size", type=int, default=ENSEMBLE_SIZE)
    args = ap.parse_args(argv)
    spec_rev, n_ens = args.spec_rev, args.ensemble_size
    # Output names never overwrite an earlier revision's results: the current
    # default (rev C) owns the un-suffixed figure names and accuracy_revC.json;
    # re-runs of superseded revisions get a "_rerun" suffix (SW-02 rev B and
    # SW-01a rev A originals: accuracy_revB.json, accuracy_revA.json, *_revB.pdf, *_revA.pdf).
    suffix = "" if spec_rev == M.DEFAULT_SPEC_REV else f"_rev{spec_rev}_rerun"
    out_json = REPORT_DIR / (f"accuracy_rev{spec_rev}.json" if spec_rev == M.DEFAULT_SPEC_REV
                             else f"accuracy_rev{spec_rev}_rerun.json")
    t0 = time.time()
    rev = T.git_rev()
    print(f"# accuracy.py rev={rev} numpy={np.__version__} spec_rev={spec_rev} ensemble_size={n_ens} "
          f"ensemble_seed={ENSEMBLE_SEED}")
    print("# weights NOT retrained: sim/data/model_params.json + reports/sw/trained_models.json (SW-01a)")
    sel, allm = load_models()
    d = T.load_split()
    te = np.array(sel["test_indices"])
    assert np.array_equal(te, d["test_idx"]), "test split differs from model_params.json"
    xc, y = d["codes"][te], d["y"][te]
    print(f"# test images: {len(te)}, seeds {sel['seeds']}, selected variant {sel['variant']} "
          f"s={sel['act_shift_s']}")

    variants = ["qat", "qat_noise", "float"]
    hws = {v: hw_from_json(allm["models"][v]) for v in variants}
    res = {"label": "SIMULATION (Python golden model sctpu.model, bit-exact per ARCHITECTURE.md 5 + 11)",
           "command": f"cd code/python && ../../.venv/bin/python -m sctpu.accuracy --spec-rev {spec_rev} "
                      f"--ensemble-size {n_ens}",
           "git_rev": rev,
           "spec_rev": spec_rev,
           "spec": {"C": "ARCHITECTURE.md section 5 with the rev C seeds of ADR-009 (SW-03: mode 2 = rev A "
                         "per-lane seeds, modes 0/1 = rev B pair, selected on validation data)",
                    "B": "ARCHITECTURE.md section 5 with the rev B phase-spaced seeds of section 11 (ADR-008), "
                         "INTERFACES.json revision B (git 4e5c35a); superseded by rev C",
                    "A": "ARCHITECTURE.md section 5 rev A seeds (superseded; re-run for comparison)"}[spec_rev],
           "seeds": {"modes01_x": f"0x{M.lane_seeds(0, spec_rev)[0][0]:04x}",
                     "modes01_w": f"0x{M.lane_seeds(0, spec_rev)[1][0]:04x}",
                     "mode2_x": [f"0x{v:04x}" for v in M.lane_seeds(2, spec_rev)[0]],
                     "mode2_w": [f"0x{v:04x}" for v in M.lane_seeds(2, spec_rev)[1]]},
           "retrained": False,
           "weights_source": "sim/data/model_params.json (selected) and reports/sw/trained_models.json "
                             "(all variants), trained in SW-01a; unchanged in SW-02 and SW-03",
           "rng_seeds_of_study": None,
           "dataset": sel["dataset"], "split": sel["split"], "training_seeds": sel["seeds"],
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
    ens_offsets = ensemble_offsets(n_ens, ENSEMBLE_SEED)
    res["rng_seeds_of_study"] = {"ensemble_numpy_seed": ENSEMBLE_SEED, "ensemble_size": int(n_ens),
                                 "ensemble_start_offsets_single_steps": [int(o) for o in ens_offsets]}
    ens_acc = {str(mo): {} for mo in MODES}
    for mode in MODES:
        S = spin_table(mode) if mode != 2 else None
        for K in K_RANGE:
            eng = M.SCEngine(K, mode, spec_rev=spec_rev)  # not cached: ~10 MB per engine
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
                ee = M.SCEngine(K, mode, start_offset=int(off), spec_rev=spec_rev).run(
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
                          "ensemble": f"{n_ens} analysis-only LFSR start offsets, rng seed {ENSEMBLE_SEED}: "
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
    res["lfsr_lags"] = lfsr_lags(spec_rev)
    res["value_ranges"] = M.value_ranges()
    res["requirement_checks"] = requirement_checks(res)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(res, indent=1) + "\n")
    print_table(res)
    make_figures(res, suffix)
    print(f"# wrote {out_json} and figures (suffix '{suffix}') ({time.time()-t0:.1f} s)")
    return 0


def requirement_checks(res: dict, mode: int = M.DEFAULT_RNG_MODE, K_req: int = 8) -> dict:
    """Evaluate REQ-AI-004/005/006/009 for the selected model and ``mode`` (SIMULATION).

    The pass/fail words are computed mechanically from the numbers of this
    run; they are evidence for the manager, not a verdict on the requirement
    (the requirement status is owned by the systems engineer).
    """
    selv = res["selected_variant"]
    mr = res["models"][selv]
    sc = mr["sc"][str(mode)]
    ev = mr["expected_value_Kinf"]["acc"]
    ens = mr["sc_ensemble_accuracy"][str(mode)][K_req]
    dr = mr["design_rule"][str(mode)]
    k_op = dr["smallest_K_within_2pp_for_all_larger_K"]
    ratios = {K: res["error_study"]["per_mode_K"][str(mode)][K][lay]["ensemble_ratio"]
              for K in K_RANGE if K >= 7 for lay in ("layer1",)}
    ratios_hw = {K: res["error_study"]["per_mode_K"][str(mode)][K]["layer1"]["ratio_measured_over_eq2"]
                 for K in K_RANGE if K >= 7}
    dev = abs(sc[K_req]["acc"] - ens["mean"])
    return {
        "mode": mode, "variant": selv, "label": "SIMULATION (n = 360 test images)",
        "REQ-AI-004": {"value": sc[K_req], "threshold": 0.90,
                       "result": "PASS" if sc[K_req]["acc"] >= 0.90 else "FAIL"},
        "REQ-AI-005": {"K_op": k_op, "ev_acc": ev,
                       "gap_pp_by_K": {K: round((ev - sc[K]["acc"]) * 100, 3) for K in K_RANGE},
                       "result": "PASS" if (k_op is not None and k_op <= 9) else "FAIL"},
        "REQ-AI-006": {"n_realisations": ens["n_realisations"], "mean": ens["mean"], "std": ens["std"],
                       "deployed": sc[K_req]["acc"], "abs_deviation_over_std": dev / ens["std"],
                       "result": "PASS" if (ens["n_realisations"] >= 20 and ens["mean"] >= 0.90
                                            and dev <= 2 * ens["std"]) else "FAIL"},
        "REQ-AI-009": {"layer1_ensemble_ratio_measured_over_eq2_K_ge_7": ratios,
                       "layer1_hardware_seed_ratio_K_ge_7": ratios_hw,
                       "result": "PASS" if all(0.5 <= r <= 2.0 for r in list(ratios.values())
                                               + list(ratios_hw.values())) else "FAIL"},
    }


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
        print("design rule (smallest K within 1 pp of EV; monotone | within 2 pp; monotone):",
              {mo: (dr["smallest_K_within_1pp"], dr["smallest_K_within_1pp_for_all_larger_K"],
                    dr["smallest_K_within_2pp"], dr["smallest_K_within_2pp_for_all_larger_K"])
               for mo, dr in mr["design_rule"].items()})
        if "sc_ensemble_accuracy" in mr:
            print("ensemble (mean +- sd over offsets):")
            for K in K_RANGE:
                print(f"{K:<3d} " + "  ".join(
                    f"m{mo} {mr['sc_ensemble_accuracy'][str(mo)][K]['mean']:.4f}+-"
                    f"{mr['sc_ensemble_accuracy'][str(mo)][K]['std']:.4f}" for mo in MODES))
            print("design rule on ensemble mean:", {mo: (d["smallest_K_within_1pp_for_all_larger_K"],
                                                         d["smallest_K_within_2pp_for_all_larger_K"])
                                                    for mo, d in mr["design_rule_ensemble_mean"].items()})
    if "requirement_checks" in res:
        rc = res["requirement_checks"]
        print(f"\nrequirement evidence (mode {rc['mode']}): " + ", ".join(
            f"{k}={v['result']}" for k, v in rc.items() if k.startswith("REQ")))


def make_figures(res: dict, suffix: str = "") -> None:
    """PDF figures: accuracy vs K, RMS error vs K (measured vs predicted), s sweep.

    ``suffix`` is appended to the file names (empty for the current rev B).
    The s-sweep figure depends only on the rev A model-selection data
    (s_sweep.json) and is redrawn only for a rev A run.
    """
    rev = res["spec_rev"]
    n_ens = res["rng_seeds_of_study"]["ensemble_size"]
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
                        label=f"mode {mo} mean of {n_ens} random LFSR offsets")
        ax.set_title(f"weights: {v} (s={mr['s']})")
        ax.set_xlabel("K = log2 L")
        ax.set_xticks(K_RANGE)
    axs[0].set_ylabel("test accuracy [%] (n=360)")
    axs[0].set_ylim(0, 100)
    handles, labels = axs[0].get_legend_handles_labels()
    labels = [lb.split(" (")[0] if lb.startswith(("expected", "float")) else lb for lb in labels]
    fig.legend(handles, labels, loc="lower center", ncol=5, fontsize=7, frameon=False)
    fig.suptitle(f"SC-TPU accuracy vs stream length, spec rev {rev} seeds — SIMULATION (bit-exact golden "
                 "model, digits test split seed 0, n=360); bands = 95 % Wilson CI", fontsize=9)
    fig.tight_layout(rect=(0, 0.13, 1, 1))
    fig.savefig(REPORT_DIR / f"fig_accuracy_vs_K{suffix}.pdf")
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
                    label=f"mode {mo} measured, {n_ens} random offsets")
        ax.set_yscale("log", base=2)
        ax.set_title(title)
        ax.set_xlabel("K = log2 L")
        ax.set_xticks(K_RANGE)
    axs[0].set_ylabel("RMS of Dp/L − E[Dp]/L")
    axs[1].legend(fontsize=6, frameon=False, loc="upper right", ncol=1)
    fig.suptitle(f"Stochastic error, weights {res['error_study']['variant']}, spec rev {rev} seeds — "
                 "SIMULATION vs analytical model", fontsize=9)
    fig.tight_layout()
    fig.savefig(REPORT_DIR / f"fig_rms_error_vs_K{suffix}.pdf")
    plt.close(fig)
    if rev != "A":
        return

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
    fig.savefig(REPORT_DIR / f"fig_s_sweep{suffix}.pdf")
    plt.close(fig)


if __name__ == "__main__":
    sys.exit(main())
