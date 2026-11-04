# Rev C LFSR seed selection on validation data (SW-03, step 1)

Command: `cd code/python && ../../.venv/bin/python -m sctpu.seed_select` · git `ba9dfb9-dirty` · log `logs/sw/seed_selection_revC.log`  
Accuracies: **SIMULATION** of the bit-exact Python golden model; seed structure: **CALCULATION** (exhaustive over the 65535-state m-sequence).  
**Validation set only — the 360 test images were not used in this step.** n = 288 images: sklearn load_digits; train_idx, test_idx = train_test_split(arange(1797), test_size=360, stratify=y, random_state=0); fit_idx, val_idx = train_test_split(train_idx, test_size=288, stratify=y[train_idx], random_state=0); validation = val_idx (same subset as the SW-01a s/variant selection). Class counts [29, 29, 28, 29, 29, 29, 29, 29, 28, 29].  
Caveat: the deployed weights were re-trained on all 1437 training images (SW-01a), so these images were seen in training: absolute accuracies are optimistic; the seed comparison is test-independent.  
Weights `qat_noise` (s = 0), not retrained. RNG_MODE 2. Ensemble: 20 analysis-only start offsets, numpy `default_rng(0)`: 55745, 41743, 33497, 17681, 20174, 2686, 4931, 1084, 11486, 53297, 42559, 59817, 33005, 39756, 63617, 47807, 41436, 35626, 36694, 61280.  
Selection rule (fixed in advance, ADR-009): highest worst-case deployed validation accuracy over K in {8,9,10} (compared as exact correct counts); tie-break: higher mean over K=8,9,10 of the 20-offset ensemble mean accuracy.

## 1. Candidates and seed-structure checks

| cand. | rule | R1 no translated pair streams | R2 no simultaneous sharing (stricter, info) | distinct pair offsets | λ8 min pairwise lag [cycles] | λ1 min lag with ≥1 shared bit [cycles] |
|---|---|---|---|---|---|---|
| C0 | rev A: X_i = 0xACE1 + 0x3C5A*i, W_i = 0x7A5C + 0x2B67*i (mod 2^16) | satisfied | satisfied | 8 of 8 | 321 | 69 |
| C1 | rev B: X_i = S(4096 i), W_i = S(32768 + 4096 i) | VIOLATED (28 of 28 lane pairs) | VIOLATED (64) | 1 of 8 | 512 | 511 |
| C2 | rev B X, W lanes reversed: X_i = S(4096 i), W_i = S(32768 + 4096 (7 - i)) | satisfied | VIOLATED (4) | 8 of 8 | 512 | 511 |
| C3 | X_i = S(32760 i), W_i = S(32760 (15 - i)) (mod 65535): equal spacing 4095 in stream cycles (max lambda8) | satisfied | satisfied | 8 of 8 | 4095 | 1 |
| C4 | X_i = S(4095 i), W_i = S(4095 (15 - i)) (mod 65535): equal spacing 4095 in single steps (max lambda1) | satisfied | satisfied | 8 of 8 | 3585 | 511 |

R2 violations (lag = stream-cycle lag of the coupling; shared bits of the two operand pairs):

- C1: swapped ×36: (0,0) lag -4096 bits [8, 7], (0,1) lag -4608 bits [8, 7], (0,2) lag -5120 bits [8, 7], (0,3) lag -5632 bits [8, 7] …; direct ×28: (0,1) lag -512 bits [8, 8], (0,2) lag -1024 bits [8, 8], (0,3) lag -1536 bits [8, 8], (0,4) lag -2048 bits [8, 8] …
- C2: swapped ×4: (0,7) lag -4096 bits [8, 7], (1,6) lag -4096 bits [8, 7], (2,5) lag -4096 bits [8, 7], (3,4) lag -4096 bits [8, 7]

C3/C4 family scan (X_i = S(α i), W_i = S(α (15 − i)), α = 1..65534, feasible = R1 ∧ R2 ∧ no same-instant sharing): 65288 feasible α; best (λ8, λ1): α = 32760 → (4095, 1); best (λ1, λ8): α = 4095 → (511, 3585). C3/C4 were fixed from this calculation before any accuracy was computed.

## 2. Validation accuracy, mode 2 (SIMULATION, n = 288)

| cand. | K=8 deployed | K=9 deployed | K=10 deployed | deployed mean | **deployed worst** | ens. K=8 mean ± sd | ens. K=9 | ens. K=10 | ens. mean K8–10 | identical table pairs K8/9/10 | layer-1 RMS ens./eq.(2) K8/9/10 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| C0 | 98.96 (285/288) | 98.96 (285/288) | 99.31 (286/288) | 99.07 | **98.96** | 97.38 ± 1.07 | 99.05 ± 0.37 | 99.22 ± 0.53 | 98.55 | 0/0/0 | 1.01/0.89/0.98 |
| C1 | 96.88 (279/288) | 95.14 (274/288) | 97.92 (282/288) | 96.64 | **95.14** | 97.15 ± 1.85 | 98.30 ± 1.43 | 98.42 ± 1.24 | 97.96 | 120/196/100 | 1.07/1.29/1.55 |
| C2 | 95.83 (276/288) | 97.92 (282/288) | 98.26 (283/288) | 97.34 | **95.83** | 97.40 ± 1.29 | 98.84 ± 0.61 | 99.06 ± 0.54 | 98.43 | 0/0/0 | 0.99/0.95/1.07 |
| C3 | 98.26 (283/288) | 98.61 (284/288) | 99.65 (287/288) | 98.84 | **98.26** | 97.69 ± 1.00 | 98.49 ± 0.83 | 99.20 ± 0.45 | 98.46 | 0/0/0 | 0.98/1.01/0.96 |
| C4 | 97.22 (280/288) | 98.61 (284/288) | 98.96 (285/288) | 98.26 | **97.22** | 97.05 ± 1.82 | 98.68 ± 0.58 | 99.01 ± 0.64 | 98.25 | 0/0/0 | 1.02/1.09/1.13 |

Ranking by the protocol: C0 > C3 > C4 > C2 > C1. **Selected: C0** (rev A: X_i = 0xACE1 + 0x3C5A*i, W_i = 0x7A5C + 0x2B67*i (mod 2^16)).

How decisive (information only, not part of the protocol): the winner's worst case is 285/288 = 98.96 % (95 % Wilson CI 97.0–99.6 %; one image = 0.35 pp). Paired exact McNemar of C0 vs each other candidate on the same 288 images (discordant C0-only / other-only, p):

| other | K=8 | K=9 | K=10 |
|---|---|---|---|
| C1 | 8/2, p = 0.109 | 11/0, p = 0.000977 | 4/0, p = 0.125 |
| C2 | 10/1, p = 0.0117 | 3/0, p = 0.25 | 3/0, p = 0.25 |
| C3 | 3/1, p = 0.625 | 2/1, p = 1 | 1/2, p = 1 |
| C4 | 6/1, p = 0.125 | 3/2, p = 1 | 1/0, p = 1 |

The validation images were part of the final training set, so all candidates are near the ceiling (97–99 %) and the margins are a few images; among the rule-compliant candidates (C0, C3, C4) no difference is statistically significant, and the ranking among candidates with similar ensemble means is dominated by the realisation noise of a single seed set (ensemble sd 0.4–1.8 pp). The protocol was nevertheless applied as fixed in advance.
