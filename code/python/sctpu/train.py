"""Training of the 64-16-10 MLP for the SC-TPU (task SW-01a, deliverable 2).

Workload: ARCHITECTURE.md 5.1 (MLP 64-16-10, clipped-ReLU hidden layer, argmax
output). Number format: 5.2 (8-bit codes, v(c) = (c-128)/128). Activation and
bias semantics: 5.3 step 1c. Everything is plain numpy (no deep-learning
framework); all random choices use ``numpy.random.default_rng(seed)`` with the
seed recorded in the outputs.

Dataset and split
-----------------
scikit-learn ``load_digits`` (1797 images 8x8, pixels 0..16, 10 classes).
Stratified split train/test = 1437/360 with ``train_test_split(...,
test_size=360, stratify=y, random_state=0)``. For the choice of the activation
shift s (and of the training variant) the 1437 training images are split again
(stratified, 288 validation images, random_state=0); the test images are never
used for any choice. The final models are retrained on all 1437 images.

Pixel -> code mapping (assignment SW-01a): c = 128 + (p*127 + 8)//16, i.e.
v = round-half-up(p*127/16)/128 in [0, 127/128].

Network as trained (quantisation-aware, straight-through estimator)
-------------------------------------------------------------------
    W1q = q(W1), W2q = q(W2)      q(w) = clip(round(128 w), -128, 127)/128 (code - 128)/128
    b1q = round(128 b1)/128, b2q = round(128 b2)/128 (int16 in units of 1/128)
    z1  = x W1q^T + b1q                       (what Dp_j / L estimates, 5.3)
    h   = floor(128 clip(2^s z1, 0, 127/128)) / 128   (HIDDEN = 128 + 128 h)
    z2  = h W2q^T + b2q                       (SCORE / L)
    loss = cross-entropy(softmax(z2))
The straight-through estimator passes gradients unchanged through round()
and floor(); the clip of the activation has gradient 2^s inside (0, 127/128)
and 0 outside. Master weights are clipped to the representable range
[-1, 127/128] after every update.

Variants
--------
``float``     : no quantisation (q = identity, no floor) — float baseline.
``qat``       : quantisation-aware training as above.
``qat_noise`` : as ``qat`` plus Gaussian noise added to z1 and z2 during
                training with the variance predicted for SC at K_train
                (independent-stream model, see accuracy.py / error_model.md):
                Var(z) = (1/L) * sum_i (1 - v_x,i^2 v_w,i^2), L = 2^K_train.
                The noise std is treated as a constant (no gradient).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from . import model as M

ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "sim" / "data"
REPORT_DIR = ROOT / "reports" / "sw"

SPLIT_SEED = 0  #: random_state of the train/test split (assignment)
VAL_SEED = 0  #: random_state of the train/validation split
TRAIN_SEED = 0  #: seed of weight init + minibatch order + noise
N_TEST = 360
N_VAL = 288
K_TRAIN_NOISE = 8  #: L = 256, the CONFIG.LOG2_L reset value (5.4)

HPARAMS = {"epochs": 200, "batch": 32, "lr": 0.01, "lr_final": 0.0005,
           "beta1": 0.9, "beta2": 0.999, "eps": 1e-8}


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def pixel_to_code(p) -> np.ndarray:
    """Input pixel (0..16) -> 8-bit code c = 128 + (p*127 + 8)//16 (assignment, 5.2)."""
    p = np.asarray(p, dtype=np.int64)
    if p.min() < 0 or p.max() > 16:
        raise ValueError("pixels must be 0..16")
    return 128 + (p * 127 + 8) // 16


def load_split() -> dict:
    """Load sklearn digits and make the stratified 1437/360 split (seed 0).

    Returns a dict with ``pixels`` (1797,64) int, ``y`` (1797,), ``codes``
    (1797,64), ``train_idx`` (1437,), ``test_idx`` (360,), ``fit_idx`` and
    ``val_idx`` (sub-split of train for model selection). Index arrays refer to
    rows of ``load_digits().data``; their order is the order returned by
    ``train_test_split`` and is preserved in all generated files.
    """
    from sklearn.datasets import load_digits
    from sklearn.model_selection import train_test_split

    d = load_digits()
    pixels = d.data.astype(np.int64)
    y = d.target.astype(np.int64)
    idx = np.arange(len(y))
    train_idx, test_idx = train_test_split(idx, test_size=N_TEST, stratify=y,
                                           random_state=SPLIT_SEED)
    fit_idx, val_idx = train_test_split(train_idx, test_size=N_VAL, stratify=y[train_idx],
                                        random_state=VAL_SEED)
    return {"pixels": pixels, "y": y, "codes": pixel_to_code(pixels),
            "train_idx": train_idx, "test_idx": test_idx,
            "fit_idx": fit_idx, "val_idx": val_idx}


# ---------------------------------------------------------------------------
# Quantisers (5.2 codes, 5.4 int16 biases)
# ---------------------------------------------------------------------------

W_MIN, W_MAX = -1.0, 127.0 / 128.0  #: representable weight range v(0)..v(255)
B_MIN, B_MAX = -32768 / 128.0, 32767 / 128.0  #: int16 bias in units of 1/128


def weight_codes(W: np.ndarray) -> np.ndarray:
    """Float weights -> codes: c = clip(round(128 w), -128, 127) + 128 (5.2).

    ``np.round`` rounds half to even; any fixed rule is fine because the
    resulting codes ARE the model (they are what the hardware sees).
    """
    return (np.clip(np.round(W * 128.0), -128, 127) + 128).astype(np.int64)


def bias_ints(b: np.ndarray) -> np.ndarray:
    """Float biases -> int16 in units of 1/128 (5.3: B = floor(bias 2^K / 128))."""
    return np.clip(np.round(b * 128.0), -32768, 32767).astype(np.int64)


def code_values(c) -> np.ndarray:
    """v(c) = (c - 128)/128 (5.2)."""
    return (np.asarray(c, dtype=np.float64) - 128.0) / 128.0


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def _forward(params, xv, s, quant, noise_L=None, rng=None):
    """Training forward pass; returns intermediates for the backward pass."""
    W1, b1, W2, b2 = params
    if quant:
        W1q, W2q = code_values(weight_codes(W1)), code_values(weight_codes(W2))
        b1q, b2q = bias_ints(b1) / 128.0, bias_ints(b2) / 128.0
    else:
        W1q, W2q, b1q, b2q = W1, W2, b1, b2
    z1 = xv @ W1q.T + b1q
    if noise_L:
        # Independent-stream SC variance of Dp/L (error_model.md, eq. (3)).
        var1 = (1.0 - (xv ** 2) @ (W1q ** 2).T) / noise_L
        z1 = z1 + rng.standard_normal(z1.shape) * np.sqrt(np.maximum(var1, 0.0))
    a = (2.0 ** s) * z1
    mask = (a > 0.0) & (a < W_MAX)
    hc = np.clip(a, 0.0, W_MAX)
    h = np.floor(hc * 128.0) / 128.0 if quant else hc
    z2 = h @ W2q.T + b2q
    if noise_L:
        var2 = (1.0 - (h ** 2) @ (W2q ** 2).T) / noise_L
        z2 = z2 + rng.standard_normal(z2.shape) * np.sqrt(np.maximum(var2, 0.0))
    return {"W1q": W1q, "W2q": W2q, "mask": mask, "h": h, "z2": z2}


def _softmax(z):
    """Row-wise numerically stable softmax."""
    e = np.exp(z - z.max(axis=1, keepdims=True))
    return e / e.sum(axis=1, keepdims=True)


def train_mlp(xv: np.ndarray, y: np.ndarray, s: int, variant: str, seed: int = TRAIN_SEED,
              hp: dict = HPARAMS) -> dict:
    """Train the 64-16-10 MLP (plain numpy, Adam, STE) and return float master params.

    Parameters: ``xv`` (N,64) input values v(c); ``y`` labels; ``s`` ACT_SHIFT;
    ``variant`` in {"float", "qat", "qat_noise"} (see module docstring).
    Initialisation: uniform Glorot limits, W1 divided by 2^s so that the
    pre-activation 2^s z1 starts in the same range for every s.
    """
    if variant not in ("float", "qat", "qat_noise"):
        raise ValueError(variant)
    quant = variant != "float"
    noise_L = (1 << K_TRAIN_NOISE) if variant == "qat_noise" else None
    rng = np.random.default_rng(seed)
    a1, a2 = np.sqrt(6.0 / (64 + 16)), np.sqrt(6.0 / (16 + 10))
    W1 = rng.uniform(-a1, a1, (16, 64)) / (2.0 ** s)
    W2 = rng.uniform(-a2, a2, (10, 16))
    params = [W1, np.zeros(16), W2, np.zeros(10)]
    m = [np.zeros_like(p) for p in params]
    v = [np.zeros_like(p) for p in params]
    n = len(y)
    Y = np.eye(10)[y]
    steps_per_epoch = int(np.ceil(n / hp["batch"]))
    total = hp["epochs"] * steps_per_epoch
    t = 0
    for _epoch in range(hp["epochs"]):
        order = rng.permutation(n)
        for b0 in range(0, n, hp["batch"]):
            bi = order[b0:b0 + hp["batch"]]
            xb, Yb = xv[bi], Y[bi]
            f = _forward(params, xb, s, quant, noise_L, rng)
            dz2 = (_softmax(f["z2"]) - Yb) / len(bi)
            gW2 = dz2.T @ f["h"]
            gb2 = dz2.sum(0)
            dh = dz2 @ f["W2q"]                 # STE through floor()
            dz1 = dh * f["mask"] * (2.0 ** s)  # clip derivative
            gW1 = dz1.T @ xb                    # STE through round()
            gb1 = dz1.sum(0)
            grads = [gW1, gb1, gW2, gb2]
            t += 1
            # cosine learning-rate decay from lr to lr_final
            lr = hp["lr_final"] + 0.5 * (hp["lr"] - hp["lr_final"]) * (1 + np.cos(np.pi * t / total))
            for k in range(4):
                m[k] = hp["beta1"] * m[k] + (1 - hp["beta1"]) * grads[k]
                v[k] = hp["beta2"] * v[k] + (1 - hp["beta2"]) * grads[k] ** 2
                mh = m[k] / (1 - hp["beta1"] ** t)
                vh = v[k] / (1 - hp["beta2"] ** t)
                params[k] = params[k] - lr * mh / (np.sqrt(vh) + hp["eps"])
            # keep master values inside the representable ranges (5.2, 5.4)
            params[0] = np.clip(params[0], W_MIN, W_MAX)
            params[2] = np.clip(params[2], W_MIN, W_MAX)
            params[1] = np.clip(params[1], B_MIN, B_MAX)
            params[3] = np.clip(params[3], B_MIN, B_MAX)
    W1, b1, W2, b2 = params
    return {"W1": W1, "b1": b1, "W2": W2, "b2": b2, "s": s, "variant": variant, "seed": seed}


def to_hw(p: dict) -> dict:
    """Quantise float params to hardware codes/ints and build the TPU images (5.4, 5.5)."""
    w1c, w2c = weight_codes(p["W1"]), weight_codes(p["W2"])
    b1i, b2i = bias_ints(p["b1"]), bias_ints(p["b2"])
    return {"w1_codes": w1c, "w2_codes": w2c, "b1": b1i, "b2": b2i,
            "weight_ram": M.pack_weight_ram(w1c, w2c),
            "biases": M.pack_biases(b1i, b2i), "s": p["s"]}


def evaluate(p: dict, codes: np.ndarray, y: np.ndarray, sc_cfgs=((8, 0), (8, 1), (8, 2))) -> dict:
    """Accuracy of one trained model: float, expected-value (K->inf) and bit-exact SC."""
    out = {}
    fl = M.float_inference(code_values(codes), p["W1"], p["b1"], p["W2"], p["b2"], p["s"])
    out["float"] = float(np.mean(fl["result"] == y))
    hw = to_hw(p)
    ev = M.ev_inference(codes, hw["weight_ram"], hw["biases"], hw["s"])
    out["ev"] = float(np.mean(ev["result"] == y))
    for K, mode in sc_cfgs:
        r = M.sc_inference_batch(codes, hw["weight_ram"], hw["biases"], K, hw["s"], mode)
        out[f"sc_K{K}_m{mode}"] = float(np.mean(r["result"] == y))
    return out


def params_to_json(p: dict) -> dict:
    """Serialisable copy of a trained parameter set (floats + codes)."""
    hw = to_hw(p)
    return {"variant": p["variant"], "s": int(p["s"]), "seed": int(p["seed"]),
            "W1": p["W1"].tolist(), "b1": p["b1"].tolist(),
            "W2": p["W2"].tolist(), "b2": p["b2"].tolist(),
            "w1_codes": hw["w1_codes"].tolist(), "w2_codes": hw["w2_codes"].tolist(),
            "b1_int16": hw["b1"].tolist(), "b2_int16": hw["b2"].tolist()}


def git_rev() -> str:
    """git short revision of the working tree (+'-dirty'), for provenance."""
    try:
        rev = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"],
                               capture_output=True, text=True).stdout.strip()
        return rev + ("-dirty" if dirty else "")
    except Exception:  # pragma: no cover - provenance only
        return "unknown"


# ---------------------------------------------------------------------------
# Main: s sweep on validation, final training, export
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    """Run the s sweep (validation), select (variant, s), retrain, save JSON files."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--epochs", type=int, default=HPARAMS["epochs"])
    args = ap.parse_args(argv)
    hp = dict(HPARAMS, epochs=args.epochs)
    import sklearn
    t0 = time.time()
    print(f"# train.py  split_seed={SPLIT_SEED} val_seed={VAL_SEED} train_seed={TRAIN_SEED} "
          f"numpy={np.__version__} sklearn={sklearn.__version__} rev={git_rev()}")
    print(f"# hyper-parameters: {hp}")
    d = load_split()
    codes, y = d["codes"], d["y"]
    xv_all = code_values(codes)
    fit, val, tr, te = d["fit_idx"], d["val_idx"], d["train_idx"], d["test_idx"]
    print(f"# samples: train={len(tr)} (fit={len(fit)}, val={len(val)}) test={len(te)}")

    # --- s sweep on the validation split (test split untouched) -------------
    sweep = []
    for variant in ("float", "qat", "qat_noise"):
        for s in range(8):
            p = train_mlp(xv_all[fit], y[fit], s, variant, hp=hp)
            ev = evaluate(p, codes[val], y[val])
            ev_fit = evaluate(p, codes[fit], y[fit], sc_cfgs=())
            row = {"variant": variant, "s": s, "val": ev, "fit_ev": ev_fit["ev"],
                   "fit_float": ev_fit["float"]}
            sweep.append(row)
            print(f"sweep variant={variant:9s} s={s} val={json.dumps(ev)}", flush=True)

    # Selection rule (validation only): maximise validation SC accuracy at
    # K=8, RNG_MODE=1 (CONFIG reset value, ADR-003 default mode); ties ->
    # higher validation EV accuracy -> smaller s -> "qat" before "qat_noise".
    def key(r):
        return (r["val"]["sc_K8_m1"], r["val"]["ev"], -r["s"], r["variant"] == "qat")
    best_per_variant = {}
    for variant in ("qat", "qat_noise"):
        rows = [r for r in sweep if r["variant"] == variant]
        best_per_variant[variant] = max(rows, key=key)
    chosen = max(best_per_variant.values(), key=key)
    s_star, var_star = chosen["s"], chosen["variant"]
    # Float baseline: s chosen by validation float accuracy (ties -> smaller s).
    frows = [r for r in sweep if r["variant"] == "float"]
    s_float = max(frows, key=lambda r: (r["val"]["float"], -r["s"]))["s"]
    print(f"# selected: variant={var_star} s={s_star} (val sc_K8_m1={chosen['val']['sc_K8_m1']:.4f}); "
          f"per-variant s: { {k: v['s'] for k, v in best_per_variant.items()} }; float s={s_float}")

    # --- final training on all 1437 training images ---------------------------
    finals = {}
    for variant in ("qat", "qat_noise"):
        finals[variant] = train_mlp(xv_all[tr], y[tr], best_per_variant[variant]["s"], variant, hp=hp)
    finals["float"] = train_mlp(xv_all[tr], y[tr], s_float, "float", hp=hp)
    # Also a float model at the hardware s, for a like-for-like float reference.
    finals["float_at_hw_s"] = train_mlp(xv_all[tr], y[tr], s_star, "float", hp=hp)
    for k, p in finals.items():
        tr_acc = evaluate(p, codes[tr], y[tr], sc_cfgs=())
        print(f"final {k:14s} s={p['s']} train float={tr_acc['float']:.4f} ev={tr_acc['ev']:.4f}")

    sel = finals[var_star]
    hw = to_hw(sel)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    meta = {
        "description": "Trained SC-TPU MLP 64-16-10 parameters as hardware codes (SIMULATION/training output)",
        "spec": "design/architecture/ARCHITECTURE.md rev A sections 5.2-5.5",
        "task": "SW-01a", "git_rev": git_rev(),
        "dataset": "sklearn.datasets.load_digits (1797 x 64, pixels 0..16)",
        "sklearn_version": sklearn.__version__, "numpy_version": np.__version__,
        "split": {"method": "train_test_split(test_size=360, stratify=y, random_state=0)",
                  "n_train": int(len(tr)), "n_test": int(len(te)),
                  "validation": "train_test_split(train, test_size=288, stratify, random_state=0)",
                  "n_fit": int(len(fit)), "n_val": int(len(val))},
        "seeds": {"split": SPLIT_SEED, "val_split": VAL_SEED, "train": TRAIN_SEED},
        "pixel_to_code": "c = 128 + (p*127 + 8)//16",
        "hyper_parameters": hp, "variant": var_star, "k_train_noise": K_TRAIN_NOISE,
        "selection_rule": "max validation SC accuracy at K=8 RNG_MODE=1; ties: val EV acc, smaller s, qat first",
    }
    out = dict(meta)
    out.update({
        "act_shift_s": int(s_star),
        "w1_codes": hw["w1_codes"].tolist(), "b1_int16": hw["b1"].tolist(),
        "w2_codes": hw["w2_codes"].tolist(), "b2_int16": hw["b2"].tolist(),
        "layer2_padding": "neurons 10..15: weight code 128, bias 0",
        "weight_ram_fill_unused": "bytes 1280..2047 = 0x00",
        "test_indices": [int(i) for i in te], "test_labels": [int(v) for v in y[te]],
        "train_indices": [int(i) for i in tr],
    })
    (DATA_DIR / "model_params.json").write_text(json.dumps(out, indent=1) + "\n")
    allm = dict(meta)
    allm["models"] = {k: params_to_json(p) for k, p in finals.items()}
    (REPORT_DIR / "trained_models.json").write_text(json.dumps(allm) + "\n")
    sweep_out = dict(meta)
    sweep_out.update({"label": "SIMULATION (validation split, 288 images)", "sweep": sweep,
                      "selected": {"variant": var_star, "s": s_star,
                                   "per_variant_s": {k: v["s"] for k, v in best_per_variant.items()},
                                   "float_s": s_float}})
    (REPORT_DIR / "s_sweep.json").write_text(json.dumps(sweep_out, indent=1) + "\n")
    print(f"# wrote {DATA_DIR/'model_params.json'}, {REPORT_DIR/'trained_models.json'}, "
          f"{REPORT_DIR/'s_sweep.json'}  ({time.time()-t0:.1f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
