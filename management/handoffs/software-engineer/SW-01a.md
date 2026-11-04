# SW-01a — SC-TPU golden model, training, accuracy study, init/test-vector files
Status: PASS
Agent: software-engineer   Date: 2026-11-04   Input revision: ece09f0 (spec); working tree at run time 8431008…d05477e-dirty (manager WIP commits; `git diff ece09f0 HEAD -- design/architecture/ARCHITECTURE.md management/INTERFACES.json` empty → spec unchanged). Not committed (as instructed).

## Requirements addressed
Assignment SW-01a deliverables 1–5 (no REQUIREMENTS.md IDs exist yet). Spec: ARCHITECTURE.md 5.1–5.6 ([BIT-EXACT] 5.2, 5.3, 5.5), INTERFACES.json `tpu`.

## Inputs
- `design/architecture/ARCHITECTURE.md` rev A, `management/INTERFACES.json` (rev ece09f0)
- `code/python/sctpu/lfsr.py` (ST-SW-01, extended here)
- venv: Python 3.13.18, numpy 2.5.4, scikit-learn 1.9.1, matplotlib 3.11.2, pytest 9.2.0

## Outputs
Code (all functions docstringed with spec section):
- `code/python/sctpu/lfsr.py` — added `step_n`, `LEAP8_MASKS` (GF(2) 8-step XOR network; new bit b = parity(state & mask[b]); bits 8..15 = old 0..7, bits 0..7 masks 0x168,0x2d0,0x5a0,0xb40,0x1680,0x2d00,0x5a00,0xb400), `leap8`, `stream_r_sequence`.
- `code/python/sctpu/model.py` — `sc_inference_reference` (literal loops, 8×`lfsr.step`), `SCEngine`/`sc_inference_batch` (exact count-table model: T[tile,lane,cx,cw] = L − n_x − n_w + 2A from the (r_x,r_w) histogram; gather+sum), `ev_inference` (K→∞ and finite K), `int8_inference`, `float_inference`, layout `weight_addr`/`pack_weight_ram`/`unpack_weight_ram`, register packing, `value_ranges`.
- `code/python/sctpu/train.py` — numpy QAT (STE) of 64-16-10, variants float / qat / qat_noise, s sweep, export.
- `code/python/sctpu/accuracy.py` — accuracy study + analytical variance model + figures.
- `code/python/sctpu/gen_hex.py` — init files, vectors, corner sets, RNG traces, reference cross-check.
- `code/python/tests/test_model.py` — 28 tests.
Data (`sim/data/`, format in `sim/data/README.md`):
- `model_params.json` (codes, s=0, split indices, seeds), `weights.hex` (512×8 hex), `bias.hex` (32×4 hex), `input.hex` (16×8 hex, test position 0 = load_digits row 1496, label 7)
- `tpu_vectors_mode{0,1,2}.txt` (K=8, s=0, 360 vectors each), `tpu_vectors_K4_mode1.txt`, `tpu_vectors_K10_mode1.txt` (16 each), `tpu_vectors_corner_mode{0,1,2}.txt` (K=4, 51 each) + `corner/pset{1..8}_{weights,bias}.hex`, `tpu_rng_trace_mode{0,1,2}.txt` (64 cycles)
- sha256: weights.hex b743fe71…51c8, bias.hex 1d1e138f…da83, input.hex 4eeb1ae6…1c9a, model_params.json d7a15da2…f348
Reports (`reports/sw/`): `accuracy.json`, `s_sweep.json`, `trained_models.json`, `error_model.md`, `fig_accuracy_vs_K.pdf`, `fig_rms_error_vs_K.pdf`, `fig_s_sweep.pdf`.
Logs (`logs/sw/`): `pytest_model.log`, `train.log`, `accuracy.log`, `gen_hex.log`, `train_reproducibility.log`.

## Checks actually performed
| Command | Tool | Log | Result (quoted) |
|---|---|---|---|
| `.venv/bin/python -m pytest -v code/python/tests/test_model.py code/python/tests/test_smoke.py` | pytest 9.2.0 | logs/sw/pytest_model.log | "33 passed in 7.74s", exit=0 |
| leap8 vs 8 single steps, all 65536 states | test_leap8_equals_8_single_steps_for_all_states | same | PASSED (0 mismatching states) |
| reference vs vectorised, 16 random cases/mode (K=4..10, random + extreme codes/biases), all fields incl. acc/Dp | test_reference_vs_vectorised_random[0,1,2] | same | PASSED, mismatches = 0 |
| `cd code/python && ../../.venv/bin/python -m sctpu.gen_hex` | gen_hex.py | logs/sw/gen_hex.log | "CROSSCHECK TOTAL: 257 vectors x 33 fields, mismatches = 0"; "corner-case sanity assertions: PASS" |
| `… -m sctpu.train` | train.py | logs/sw/train.log | "# selected: variant=qat_noise s=0 (val sc_K8_m1=0.9236)" |
| retrain selected model, compare codes | train_mlp | logs/sw/train_reproducibility.log | "reproducible: True" |
| `… -m sctpu.accuracy` | accuracy.py | logs/sw/accuracy.log | tables below; int8-vs-EV mismatches=0 (all 3 variants) |
| Figures rendered to PNG and inspected visually | pdftoppm | — | layout OK |

## Numerical findings (all SIMULATION of the Python golden model unless labelled; test split = 360 images, stratified, seed 0; 95 % Wilson CI ≈ ±2.3 pp at 95 %)
Selected model: `qat_noise`, s = 0 (chosen on the 288-image validation split; test untouched).

| Name | Value | Label |
|---|---|---|
| Float, float-trained, s=0 / s=1 (best val s) | 96.11 % / 95.28 % | SIMULATION |
| Expected value K→∞ (selected) = int8 binary baseline | 95.00 % (342/360), int8-vs-EV mismatches 0 | SIMULATION |
| EV K→∞, `qat` variant (no noise) | 95.83 % | SIMULATION |

Bit-exact SC accuracy [%], selected model, hardware seeds | ensemble mean ± sd over 16 analysis-only LFSR start offsets:
| K | mode 0 | mode 1 | mode 2 | ens m0 | ens m1 | ens m2 |
|---|---|---|---|---|---|---|
| 4 | 58.6 | 63.6 | 45.3 | 41.9±17.6 | 56.3±11.7 | 59.6±13.9 |
| 5 | 41.4 | 66.4 | 75.3 | 54.4±20.1 | 68.7±10.7 | 70.8±10.2 |
| 6 | 65.3 | 84.2 | 89.2 | 65.2±18.3 | 86.5±4.6 | 84.5±4.5 |
| 7 | 49.7 | 92.2 | 88.9 | 81.6±13.4 | 90.1±2.6 | 90.5±1.6 |
| 8 | 65.6 | 91.1 | 94.4 | 89.7±6.2 | 93.3±1.9 | 92.7±1.5 |
| 9 | 88.6 | 94.7 | 94.4 | 93.7±1.2 | 94.4±1.0 | 94.4±0.6 |
| 10 | 94.4 | 94.7 | 95.3 | 94.5±0.8 | 95.1±0.6 | 94.8±0.5 |

Design rule (smallest K with SC accuracy ≥ EV − 1 pp; identical with "for all larger K"):
| | mode 0 | mode 1 | mode 2 |
|---|---|---|---|
| selected model, hardware seeds | K=10 | K=9 | K=8 |
| `qat` model, hardware seeds | K=10 | K=9 | K=8 |
| selected model, ensemble mean | K=10 | K=9 | K=9 |
| float-trained weights rounded post-training (PTQ) | none ≤ 10 (K=10: 93.3/94.2/94.2 vs EV 95.3) | | |
Caveat: 1 pp = 3.6 images, smaller than the CI half-width; K=8 vs K=9 for mode 2 is not statistically resolved.

Noise-aware training (test, s=0): `qat` vs `qat_noise`: EV 95.8 vs 95.0; SC K=8 m0 68.6 vs 65.6, m1 90.6 vs 91.1, m2 95.3 vs 94.4 → no significant difference (all within CI). It mainly helps at large s (val EV at s=6: 88.2 % vs 17.7 %).

s sweep (validation, n=288, `qat_noise`, EV / SC K8 m1 [%]): s0 96.5/92.4, s1 95.8/89.9, s2 94.1/88.9, s3 94.1/84.4, s4 91.7/78.1, s5 92.4/68.1, s6 88.2/76.7, s7 10.1/8.7. s amplifies the SC error by 2^s → s=0 best for every variant. s≥6 (float/qat) and s=7 (all) fail to train (10 % = chance) — partly an optimisation artefact of the clipped ReLU (linear region only 2^-s wide).

Error model (CALCULATION + SIMULATION, details `reports/sw/error_model.md`): Var(Dp/L) = (1/L)·Σ_tiles[Σ_ik C^x_ik C^w_ik − (Σ_i v_x v_w)^2]; mode 2 → (1/L)Σ_i(1 − v_x²v_w²). Ensemble-measured / predicted RMS ratio 0.82–1.13 over 41 of 42 layer×K×mode points (exception mode 0, layer 1, K=10: 0.74). Example layer-1 RMS at K=8: mode 0 0.82 (pred 0.79), mode 1 0.47 (0.51), mode 2 0.50 (0.48). Hardware-seed single realisation deviates more (mode 0, K=8: 1.55 vs 0.79).

Internal ranges for RTL (CALCULATION, `model.value_ranges()`): acc1 ≤ 65536 (17 bits unsigned); Dp signed 20 bits (|Dp| ≤ 327680 at K=10 with bias ±32768); u needs 24 bits signed if shifted before clipping (K=4, s=7, shift left 10).

LFSR lags (CALCULATION): modes 0/1 X→W lag 26829 stream cycles (> 10240, no overlap in an inference); mode 2 smallest lags X0–W3 321, X4–X6 541, W0–W2 1467 cycles (inside one layer from K≥6). All mode-2 seeds non-zero.

## Assumptions
- Validation split 288 of the 1437 training images (stratified, random_state=0) for s/variant selection; final models retrained on all 1437. Hyper-parameters: Adam, 300 epochs, batch 32, lr 0.005→0.0002 cosine, train seed 0, noise model K_train=8.
- Weight code rounding: round-half-even of 128·w, clipped to codes 0..255; biases round(128·b) clipped to int16.
- Layer-2 padding neurons 10..15: weight code 0x80, bias 0; unused weight-RAM bytes 1280..2047: 0x00.
- The int8 binary baseline is the exact-integer datapath on the SAME codes (identical to EV by construction); a conventional int8 PTQ of an unconstrained float model was not done.
- Init .hex files have no header comment (5.6 says exactly 512/32/16 lines).

## Errors / deviations
- None blocking. The first pytest run failed 3 tests because of a wrong case-count constant in the test itself (16, not 15); fixed, rerun 33/33 PASS.
- `model.py` received a docstring-only edit (ambiguity A4 text) after gen_hex.py ran; the vector re-check test passed afterwards.

## Open decisions (for the manager) — spec ambiguities, most literal reading used
- A1: mode 1 rotation amount "i" = lane index (i mod IL, 0..7), not global input index 8t+i.
- A2: the first stream cycle uses r = low byte of the state after the first 8 steps; the seed is never used as r (`sim/data/tpu_rng_trace_mode*.txt` shows the exact values).
- A3: internal widths of acc/D/B/Dp/u not specified; model uses unbounded integers — RTL must provide ≥ 20-bit signed Dp (see ranges) or the spec should fix widths.
- A4: SCORE is computed for all 16 lanes incl. padding 10..15; vectors expect those values too (TB may mask them if the manager decides otherwise).
- D1 (ADR-003 input): with the frozen seeds, mode 0 is unusable below K=10 (49.7 % at K=7, 65.6 % at K=8 — an unlucky realisation; ensemble mean 81.6/89.7 %). Mode 2 reaches EV−1 pp at K=8 with these seeds, mode 1 at K=9. With the CONFIG reset value K=8, mode 1 loses 3.9 pp vs EV.
- D2: mode-2 seeds X0/W3 are only 321 stream cycles apart on the shared m-sequence (lagged copies inside one layer for K≥6). Measured effect looks small (ensemble agreement 0.89–1.06) but different seed increments could remove it.

## Next actions
- fpga-engineer: use `sim/data/tpu_vectors_*.txt` + `tpu_rng_trace_*.txt` in the TPU testbench (mismatch count over 360×3 + 32 + 153 vectors).
- Manager: decide A1–A4 (confirm or amend spec), and the default RNG_MODE/K (D1) for the SoC demo program.
- Optional: conventional int8 PTQ baseline; seed-sensitivity study as an article figure (data already in accuracy.json `sc_ensemble_accuracy`).
