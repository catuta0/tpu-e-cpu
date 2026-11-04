# SC-TPU accuracy: rev A vs rev B LFSR seeds (SW-02)

Command: `cd code/python && ../../.venv/bin/python -m sctpu.compare_revs` · git `9f91914-dirty` · log `logs/sw/compare_revs.log`  
All numbers: **SIMULATION** of the bit-exact Python golden model (`code/python/sctpu/model.py`), test split of sklearn digits (stratified, seed 0), **n = 360** images, weights `qat_noise` (s = 0) from SW-01a, **not retrained** (only the hardware seeds differ). Expected-value model (K→∞) accuracy: 95.0 %.  
Ensemble: 20 analysis-only LFSR start offsets (numpy `default_rng(0)`, identical for both revisions): 55745, 41743, 33497, 17681, 20174, 2686, 4931, 1084, 11486, 53297, 42559, 59817, 33005, 39756, 63617, 47807, 41436, 35626, 36694, 61280.  
Statistics: accuracy_ci: 95 % Wilson score interval; paired_hardware: exact McNemar (two-sided binomial on discordant images); 95 % CI of the paired difference: Newcombe 1998 method 10; paired_ensemble: paired over the 20 offsets: mean difference, Student-t 95 % CI, paired t-test; multiplicity: pre-specified: mode 2 at K=8 and K=9; other cells exploratory, uncorrected.

## 1. Pre-specified tests (mode 2 INDEPENDENT, hardware seeds)

| K | rev A acc % [95 % CI] (k/n) | rev B acc % [95 % CI] (k/n) | B − A pp [95 % CI] | discordant A-only / B-only | McNemar exact p |
|---|---|---|---|---|---|
| 8 | 94.4 [91.6, 96.4] (340/360) | 93.9 [90.9, 95.9] (338/360) | -0.6 [-2.8, 1.6] | 8 / 6 | 0.791 |
| 9 | 94.4 [91.6, 96.4] (340/360) | 89.7 [86.2, 92.5] (323/360) | -4.7 [-7.8, -2.0] | 22 / 5 | 0.00151 |

## 2. All modes and K, hardware seeds (exploratory except the two rows above)

| mode | K | rev A % [CI] | rev B % [CI] | B − A pp [Newcombe CI] | b / c | McNemar p |
|---|---|---|---|---|---|---|
| 0 | 4 | 58.6 [53.5, 63.6] | 48.3 [43.2, 53.5] | -10.3 [-16.3, -4.1] | 84 / 47 | 0.00156 |
| 0 | 5 | 41.4 [36.4, 46.5] | 40.8 [35.9, 46.0] | -0.6 [-6.9, 5.8] | 69 / 67 | 0.932 |
| 0 | 6 | 65.3 [60.2, 70.0] | 61.7 [56.5, 66.5] | -3.6 [-9.5, 2.3] | 66 / 53 | 0.271 |
| 0 | 7 | 49.7 [44.6, 54.9] | 89.7 [86.2, 92.5] | +40.0 [34.1, 45.5] | 12 / 156 | 4.1e-33 |
| 0 | 8 | 65.6 [60.5, 70.3] | 81.9 [77.6, 85.6] | +16.4 [11.0, 21.7] | 23 / 82 | 6.0e-09 |
| 0 | 9 | 88.6 [84.9, 91.5] | 90.0 [86.5, 92.7] | +1.4 [-0.7, 3.6] | 4 / 9 | 0.267 |
| 0 | 10 | 94.4 [91.6, 96.4] | 94.2 [91.2, 96.2] | -0.3 [-2.3, 1.7] | 6 / 5 | 1 |
| 1 | 4 | 63.6 [58.5, 68.4] | 60.8 [55.7, 65.7] | -2.8 [-9.3, 3.7] | 77 / 67 | 0.453 |
| 1 | 5 | 66.4 [61.4, 71.1] | 77.2 [72.6, 81.3] | +10.8 [4.9, 16.7] | 41 / 80 | 0.000499 |
| 1 | 6 | 84.2 [80.0, 87.6] | 81.7 [77.3, 85.3] | -2.5 [-7.3, 2.3] | 43 / 34 | 0.362 |
| 1 | 7 | 92.2 [89.0, 94.6] | 90.0 [86.5, 92.7] | -2.2 [-5.9, 1.3] | 25 / 17 | 0.28 |
| 1 | 8 | 91.1 [87.7, 93.6] | 89.2 [85.5, 92.0] | -1.9 [-4.9, 0.9] | 17 / 10 | 0.248 |
| 1 | 9 | 94.7 [91.9, 96.6] | 94.4 [91.6, 96.4] | -0.3 [-2.0, 1.4] | 4 / 3 | 1 |
| 1 | 10 | 94.7 [91.9, 96.6] | 95.0 [92.2, 96.8] | +0.3 [-1.6, 2.2] | 4 / 5 | 1 |
| 2 | 4 | 45.3 [40.2, 50.4] | 52.8 [47.6, 57.9] | +7.5 [0.7, 14.1] | 64 / 91 | 0.0364 |
| 2 | 5 | 75.3 [70.6, 79.5] | 70.0 [65.1, 74.5] | -5.3 [-11.3, 0.7] | 71 / 52 | 0.104 |
| 2 | 6 | 89.2 [85.5, 92.0] | 83.1 [78.8, 86.6] | -6.1 [-10.4, -1.9] | 42 / 20 | 0.00715 |
| 2 | 7 | 88.9 [85.2, 91.7] | 88.6 [84.9, 91.5] | -0.3 [-4.4, 3.9] | 29 / 28 | 1 |
| 2 | 8 | 94.4 [91.6, 96.4] | 93.9 [90.9, 95.9] | -0.6 [-2.8, 1.6] | 8 / 6 | 0.791 |
| 2 | 9 | 94.4 [91.6, 96.4] | 89.7 [86.2, 92.5] | -4.7 [-7.8, -2.0] | 22 / 5 | 0.00151 |
| 2 | 10 | 95.3 [92.6, 97.0] | 94.7 [91.9, 96.6] | -0.6 [-2.6, 1.4] | 6 / 4 | 0.754 |

b = images correct only with rev A, c = correct only with rev B.

## 3. Ensemble over 20 LFSR start offsets (paired by offset)

| mode | K | rev A mean ± sd % | rev B mean ± sd % | B − A mean pp [95 % t-CI] | paired t p |
|---|---|---|---|---|---|
| 0 | 4 | 39.9 ± 16.6 | 40.2 ± 17.5 | +0.28 [-10.1, 10.7] | 0.956 |
| 0 | 5 | 54.5 ± 18.8 | 52.1 ± 20.4 | -2.37 [-13.4, 8.6] | 0.656 |
| 0 | 6 | 66.3 ± 17.5 | 71.2 ± 16.0 | +4.94 [-5.3, 15.2] | 0.323 |
| 0 | 7 | 81.5 ± 13.4 | 87.5 ± 4.9 | +6.01 [-1.5, 13.6] | 0.112 |
| 0 | 8 | 90.1 ± 5.7 | 90.7 ± 4.4 | +0.58 [-3.0, 4.1] | 0.736 |
| 0 | 9 | 93.6 ± 1.2 | 93.5 ± 1.1 | -0.06 [-0.8, 0.7] | 0.885 |
| 0 | 10 | 94.5 ± 0.8 | 94.5 ± 0.7 | -0.03 [-0.5, 0.5] | 0.907 |
| 1 | 4 | 57.5 ± 10.8 | 55.6 ± 13.4 | -1.89 [-9.6, 5.8] | 0.613 |
| 1 | 5 | 69.4 ± 9.8 | 71.8 ± 10.7 | +2.40 [-3.7, 8.5] | 0.417 |
| 1 | 6 | 85.9 ± 5.3 | 83.7 ± 4.2 | -2.24 [-5.1, 0.6] | 0.118 |
| 1 | 7 | 89.8 ± 2.4 | 89.8 ± 2.3 | +0.01 [-1.3, 1.3] | 0.982 |
| 1 | 8 | 93.5 ± 1.8 | 92.8 ± 1.3 | -0.65 [-1.6, 0.3] | 0.152 |
| 1 | 9 | 94.5 ± 0.9 | 94.3 ± 0.8 | -0.18 [-0.7, 0.3] | 0.457 |
| 1 | 10 | 95.1 ± 0.7 | 95.3 ± 0.5 | +0.21 [-0.1, 0.5] | 0.148 |
| 2 | 4 | 60.3 ± 13.1 | 59.3 ± 10.5 | -0.99 [-8.5, 6.5] | 0.786 |
| 2 | 5 | 71.0 ± 10.2 | 73.4 ± 8.6 | +2.40 [-3.5, 8.3] | 0.401 |
| 2 | 6 | 83.0 ± 5.2 | 84.5 ± 5.7 | +1.49 [-2.2, 5.2] | 0.407 |
| 2 | 7 | 90.7 ± 1.7 | 91.7 ± 2.3 | +0.99 [-0.2, 2.2] | 0.103 |
| 2 | 8 | 92.8 ± 1.4 | 93.3 ± 1.5 | +0.46 [-0.6, 1.5] | 0.367 |
| 2 | 9 | 94.4 ± 0.5 | 94.0 ± 1.2 | -0.44 [-1.1, 0.2] | 0.142 |
| 2 | 10 | 94.8 ± 0.5 | 94.2 ± 1.1 | -0.60 [-1.2, 0.1] | 0.0695 |

## 4. Structural cause of the rev B K = 9/10 degradation (mode 2)

CALCULATION (`seed_info`, `identical_table_pairs` in `code/python/sctpu/compare_revs.py`):

| seed set | min pairwise distance [stream cycles] | X_i–W_i distance [cycles] | distinct pair offsets b_i − a_i |
|---|---|---|---|
| rev A | 321 | 26829, 28145, 3406, 12607, 13583, 11304, 24748, 22808 | 8 of 8 |
| rev B | 512 | 4096, 4096, 4096, 4096, 4096, 4096, 4096, 4096 | 1 of 8 |
| C1 (analysis only) | 512 | 7680, 6656, 5632, 4608, 3584, 2560, 1536, 512 | 8 of 8 |

In rev B every X_i and W_i seed is advanced by the same 4096 single steps per lane, so the joint random pair (r_x,i+1(k), r_w,i+1(k)) = (r_x,i(k+512), r_w,i(k+512)): all 8 lanes carry ONE pair stream with 512-cycle delays (1 distinct pair offset of 8). When 512 cycles are a whole number of tiles (K ≤ 9) or a tile is a whole number of 512-cycle blocks (K = 10), whole XNOR count tables repeat across (tile, lane) slots, so the stochastic errors of those slots are identical functions of the codes and add coherently instead of averaging out (violates assumption A4 of the error model).

| K | identical (tile, lane) table pairs per inference: rev A | rev B | C1 | layer-1 RMS ensemble / eq. (2): rev A | rev B | C1 |
|---|---|---|---|---|---|---|
| 4 | 0 | 0 | 0 | 0.93 | 0.94 | 1.05 |
| 5 | 0 | 0 | 0 | 1.02 | 0.91 | 0.96 |
| 6 | 0 | 14 | 0 | 1.01 | 0.91 | 0.92 |
| 7 | 0 | 54 | 0 | 0.98 | 0.91 | 0.96 |
| 8 | 0 | 120 | 0 | 1.01 | 1.06 | 0.99 |
| 9 | 0 | 196 | 0 | 0.90 | 1.30 | 0.94 |
| 10 | 0 | 100 | 0 | 0.98 | 1.55 | 1.06 |

(3160 slot pairs exist per inference: 80 slots = 10 tiles × 8 lanes.)

## 5. Analysis-only candidate C1 (NOT a spec revision): rev B with W lanes reversed

W_i = S(32768 + 4096·(7 − i)); same 16 seed values as rev B, so the minimum pairwise distance stays 512 cycles, but every lane has a different X–W offset. Mode 2:

| K | rev B hw % [CI] | C1 hw % [CI] | C1 − B pp [Newcombe CI] | McNemar p | rev B ens mean ± sd % | C1 ens mean ± sd % | C1 − B ens pp [t-CI] |
|---|---|---|---|---|---|---|---|
| 4 | 52.8 [47.6, 57.9] | 53.6 [48.4, 58.7] | +0.8 [-5.0, 6.7] | 0.853 | 59.3 ± 10.5 | 56.1 ± 9.8 | -3.21 [-9.4, 3.0] |
| 5 | 70.0 [65.1, 74.5] | 85.6 [81.5, 88.8] | +15.6 [10.3, 20.8] | 2.3e-08 | 73.4 ± 8.6 | 75.1 ± 10.0 | +1.78 [-2.8, 6.3] |
| 6 | 83.1 [78.8, 86.6] | 73.1 [68.2, 77.4] | -10.0 [-14.5, -5.5] | 2.6e-05 | 84.5 ± 5.7 | 85.7 ± 3.6 | +1.18 [-1.1, 3.5] |
| 7 | 88.6 [84.9, 91.5] | 88.3 [84.6, 91.3] | -0.3 [-3.8, 3.3] | 1 | 91.7 ± 2.3 | 90.8 ± 2.3 | -0.89 [-2.2, 0.4] |
| 8 | 93.9 [90.9, 95.9] | 90.8 [87.4, 93.4] | -3.1 [-5.8, -0.6] | 0.0266 | 93.3 ± 1.5 | 93.3 ± 1.4 | +0.04 [-0.7, 0.7] |
| 9 | 89.7 [86.2, 92.5] | 93.6 [90.6, 95.7] | +3.9 [1.5, 6.6] | 0.00258 | 94.0 ± 1.2 | 94.2 ± 0.9 | +0.21 [-0.3, 0.8] |
| 10 | 94.7 [91.9, 96.6] | 94.4 [91.6, 96.4] | -0.3 [-2.0, 1.4] | 1 | 94.2 ± 1.1 | 94.5 ± 0.8 | +0.32 [-0.1, 0.8] |

(In this table column 'A' of the JSON entry is rev B and column 'B' is C1.)

