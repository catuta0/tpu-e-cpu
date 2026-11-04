# SC-TPU stochastic error model (task SW-01a)

Command: `cd code/python && ../../.venv/bin/python -m sctpu.accuracy` (log `logs/sw/accuracy.log`,
results `reports/sw/accuracy.json` key `error_study`, figure `reports/sw/fig_rms_error_vs_K.pdf`).
Spec: `design/architecture/ARCHITECTURE.md` rev A, 5.2–5.3. Implementation: `code/python/sctpu/accuracy.py`
(`predicted_variance`, `lane_correlations`).

## Quantity

For neuron j of a layer, the TPU computes Dp = 2·acc − N_in·L + B (5.3). The bipolar interpretation is
Dp/L ≈ Σ_i v(x_i)·v(W_ji) + bias/128. The stochastic error studied is

  e = (Dp − B)/L − P/2^14,   P = Σ_i (x_i − 128)(W_ji − 128)

i.e. Dp/L minus its exact expectation at the same K (the deterministic bias term B is removed; the
separate bias-quantisation error |B/L − bias/128| < 1/L is reported as `rms_total_vs_Kinf` for layer 1).

## Derivation (CALCULATION)

Write every stream bit as a spin s = 2b − 1. The XNOR product of lane i is p_i = (1 + s_x,i·s_w,i)/2.

Assumptions:

* **A1** r is uniform on {0..255} in each stream cycle. (The LFSR never produces state 0; over a full
  period the low byte 0 occurs 255 times and the others 256 times: 0.4 % deviation, neglected.)
  Then P(b = 1) = P(r < c) = c/256 and E[s] = 2c/256 − 1 = (c − 128)/128 = v(c) **exactly**.
* **A2** r values of different stream cycles are independent (leap-forward of 8 steps, ADR-005).
* **A3** the X and W generators are independent of each other.
* **A4** mode 2: generators of different lanes are independent.

With lane-pair spin correlations C^x_ik = E[s_x,i s_x,k] and C^w_ik = E[s_w,i s_w,k] (C_ii = 1) and A3:

  Cov(p_i, p_k) = ( C^x_ik·C^w_ik − v_x,i v_w,i v_x,k v_w,k ) / 4                       (1)

Summing over IL lanes, L independent cycles per tile and independent tiles (A2), with Dp = 2·acc + const:

  **Var(Dp/L) = (1/L) · Σ_tiles [ Σ_{i,k} C^x_ik·C^w_ik − (Σ_i v_x,i v_w,i)^2 ]**        (2)

Lane correlations for codes a (lane i), b (lane k):

| Mode | C_ik (i ≠ k) | Note |
|---|---|---|
| 0 SHARED | 1 − 2·\|a − b\|/256 | same r: the two bits differ iff r lies between a and b |
| 1 ROTATE | (1/256)·Σ_r s(rotl8(r,i) < a)·s(rotl8(r,k) < b) | exact enumeration of 256 r values |
| 2 INDEPENDENT | v_a·v_b | A4 → Cov = 0 for i ≠ k |

For mode 2, (2) reduces to the familiar independent-stream form

  **Var(Dp/L) = (1/L) · Σ_i (1 − v_x,i^2 · v_w,i^2)**                                    (3)

Consequences: the variance falls as 1/L (RMS halves every +2 in K); it is **largest for zero products**
(v_x·v_w = 0 gives the maximal per-lane variance 1/L) — in the digits workload most pixels are 0
(code 128), so layer 1 carries close to the worst-case 64/L variance (RMS ≈ 8/√L); sharing random
numbers (mode 0) makes lanes with similar codes almost perfectly correlated, which multiplies the
variance by up to IL = 8 for a tile of equal codes. The prediction reported is
RMS = sqrt(mean over images and neurons of (2)); layer 2 uses the SC hidden codes of the same run.

## Measurement (SIMULATION)

Two measurements per (K, mode), selected model `qat_noise`, 360 test images:

1. **hardware seeds** — the fixed seeds of 5.3 (one deterministic realisation of the random sequence);
2. **ensemble** — 16 analysis-only random LFSR start offsets (all seeds advanced by the same random
   number of steps, numpy seed 0; NOT hardware behaviour), RMS over all realisations.

The ensemble estimates the expectation that (2) predicts; the hardware-seed value is one draw.
Selected rows (full table in `accuracy.json`; values are RMS of e in bipolar units):

| K | mode | L1 hw seeds | L1 ensemble | L1 eq. (2) | L1 eq. (3) | L2 hw seeds | L2 ensemble | L2 eq. (2) |
|---|---|---|---|---|---|---|---|---|
| 4 | 0 | 1.794 | 3.212 | 3.158 | 1.932 | 0.482 | 0.703 | 0.757 |
| 8 | 0 | 1.551 | 0.821 | 0.789 | 0.483 | 0.301 | 0.157 | 0.161 |
| 10 | 0 | 0.270 | 0.290 | 0.395 | 0.241 | 0.177 | 0.080 | 0.098 |
| 4 | 1 | 1.781 | 1.943 | 2.051 | 1.932 | 0.665 | 0.788 | 0.717 |
| 8 | 1 | 0.541 | 0.466 | 0.513 | 0.483 | 0.268 | 0.186 | 0.191 |
| 10 | 1 | 0.206 | 0.218 | 0.256 | 0.241 | 0.104 | 0.091 | 0.099 |
| 4 | 2 | 2.110 | 1.823 | 1.932 | 1.932 | 0.918 | 0.719 | 0.839 |
| 8 | 2 | 0.353 | 0.499 | 0.483 | 0.483 | 0.198 | 0.195 | 0.199 |
| 10 | 2 | 0.209 | 0.242 | 0.241 | 0.241 | 0.094 | 0.094 | 0.097 |

Agreement (ensemble / eq. (2)), all 42 layer-K-mode combinations: ratio within 0.82–1.13 except
mode 0, layer 1, K = 10 (0.74) (`ensemble_ratio` in the JSON).
Equation (2) therefore predicts the expected error well; the measured error tends to fall
*below* the prediction at the largest K in modes 0/1. Hypothesis (not verified): a layer uses up to
8·L = 8192 consecutive states of a 65535-state m-sequence, i.e. sampling without replacement, which
violates A2 slightly and reduces variance (finite-population factor ≈ 1 − 8192/65535).

The **hardware-seed realisation** deviates much more from the prediction than the ensemble
(e.g. mode 0, K = 8, layer 1: 1.55 vs 0.79 predicted, ratio 1.96): with shared random numbers the
error of all images is driven by the same few empirical (r_x, r_w) histograms, so one realisation has
few degrees of freedom. This explains the non-monotonic mode-0 accuracy versus K (49.7 % at K = 7,
65.6 % at K = 8, whereas the ensemble mean is 81.6 % and 89.7 %).

## Known limitations of the model

* A2 ignores lagged copies between LFSRs: all LFSRs run on the same m-sequence, so
  r_b(k) = r_a(k + m) with m = d·8^(−1) mod 65535 (d = seed distance in steps). For the modes 0/1 pair
  X/W the lag is 26829 cycles (> 10240 = cycles of a K = 10 inference: no overlap). In mode 2 the
  smallest lags are 321 (X0–W3), 541 (X4–X6), 1467 (W0–W2) cycles, i.e. inside one layer from K = 6
  on; such pairs re-use the same random number at two different cycles of the same accumulation
  (CALCULATION, `accuracy.json` key `lfsr_lags`). The ensemble agreement for mode 2 (0.89–1.06)
  suggests the effect is small for this workload.
* The model is per layer; it does not propagate layer-1 errors through the clipped ReLU.

## Rev B addendum (task SW-02, 2026-11-04)

Spec rev B (ARCHITECTURE.md 11, ADR-008) changes only the LFSR seeds. Same model, same
weights (not retrained). Rev B results: `reports/sw/accuracy_revB.json` key `error_study`,
figure `fig_rms_error_vs_K.pdf` (rev A copy: `fig_rms_error_vs_K_revA.pdf`), comparison
`reports/sw/revA_vs_revB.md` section 4. Log: `logs/sw/accuracy_revB.log`, `logs/sw/compare_revs.log`.

**Assumption A4 (independent lanes in mode 2) is violated by the rev B seeds for K >= 6.**
X_i and W_i are both advanced by the same 4096 single steps per lane, so the joint random
pair of lane i+1 is the pair of lane i delayed by 512 stream cycles. When 512 cycles are a
whole number of tiles (K <= 9) or a tile is a whole number of 512-cycle blocks (K = 10),
whole XNOR count tables repeat across (tile, lane) slots (CALCULATION from the model's
tables: 14 / 54 / 120 / 196 / 100 identical slot pairs of 3160 at K = 6 / 7 / 8 / 9 / 10;
rev A: 0). The errors of those slots are then identical functions of the codes and add
coherently. Measured (SIMULATION, 360 test images, 20 start offsets, `qat_noise`), mode 2,
layer 1, ensemble RMS / eq. (2):

| K | 7 | 8 | 9 | 10 |
|---|---|---|---|---|
| rev A | 0.98 | 1.01 | 0.90 | 0.98 |
| rev B | 0.91 | 1.06 | 1.30 | 1.55 |
| C1 (analysis-only: rev B with W lanes reversed) | 0.96 | 0.99 | 0.94 | 1.06 |

With the rev B hardware seeds the layer-1 RMS at K = 9 is 0.741 vs 0.342 predicted (ratio
2.17) and at K = 10 0.442 vs 0.242 (1.83); the error no longer falls as 1/sqrt(L) above K = 8.
Eq. (2) therefore remains adequate for rev B modes 0/1 (ensemble ratios 0.77–1.01 for K >= 7) and for mode 2 at K <= 8, but
under-predicts mode 2 at K = 9, 10.
