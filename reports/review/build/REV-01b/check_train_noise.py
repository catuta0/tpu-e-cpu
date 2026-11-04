"""REV-01b: compare the training-noise variance used in code/python/sctpu/train.py
(_forward: var1 = (1 - (x^2) @ (W^2).T) / L) with eq. (3) of reports/sw/error_model.md
(Var(Dp/L) = (1/L) * sum_i (1 - v_x,i^2 v_w,i^2)). Uses the deployed codes of
sim/data/model_params.json and the 1437 training images (pixel->code rule of train.py,
re-implemented here). Reads only; writes nothing."""
import json, sys
import numpy as np
from sklearn.datasets import load_digits
p = json.load(open(sys.argv[1]))
w1 = (np.array(p["w1_codes"]) - 128) / 128.0          # (16, 64)
w2 = (np.array(p["w2_codes"]) - 128) / 128.0          # (10, 16)
X = load_digits().data.astype(np.int64)
test = set(p["test_indices"]) if "test_indices" in p else set()
idx = [i for i in range(len(X)) if i not in test]
codes = 128 + (X[idx] * 127 + 8) // 16
xv = (codes - 128) / 128.0
L = 256
s_code = (xv ** 2) @ (w1 ** 2).T                        # sum_i x^2 w^2, (n, 16)
var_train = np.maximum(1.0 - s_code, 0.0) / L           # train.py
var_eq3 = (64.0 - s_code) / L                           # error_model.md eq. (3)
print(f"n_images={len(idx)} L={L}")
print(f"layer1 sum_i x^2 w^2: mean={s_code.mean():.3f} min={s_code.min():.3f} max={s_code.max():.3f}; fraction with 1-sum<=0 (train noise = 0): {(1.0 - s_code <= 0).mean():.3f}")
print(f"layer1 RMS noise std: train.py={np.sqrt(var_train.mean()):.4f}  eq.(3)={np.sqrt(var_eq3.mean()):.4f}  ratio={np.sqrt(var_eq3.mean()/max(var_train.mean(),1e-30)):.1f}x")
