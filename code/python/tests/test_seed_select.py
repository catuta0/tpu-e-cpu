"""Unit tests of the rev C seed-selection module (task SW-03, ``sctpu.seed_select``).

Covered:
* the bit-window overlap model behind rule R2, verified against the literal
  LFSR states (r = low byte of the state = 8-bit window of one bit sequence);
* the manager rule R1 ("no translated pair streams") and the stricter R2 per
  candidate, with rev B (C1) and the reversed-W variant (C2) as negative tests;
* the C3/C4 progression-family scan reproduces the chosen alphas;
* the protocol's selection function (worst-case count, tie-break);
* the validation set: 288 images, stratified sub-split of train, disjoint from test;
* the written selection report names C0 and rev C = the selected seed set.
Run: ``.venv/bin/python -m pytest -q code/python/tests``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sctpu import lfsr  # noqa: E402
from sctpu import model as M  # noqa: E402
from sctpu import seed_select as S  # noqa: E402
from sctpu import train as T  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]


def _bitseq(n_bits: int) -> list[int]:
    """b[n] = bit 0 of S(n) (newest bit); bit j of S(n) is b[n - j] for the shift-left LFSR."""
    st, out = 0xACE1, []
    for _ in range(n_bits):
        out.append(st & 1)
        st = lfsr.step(st)
    return out


def test_shared_bits_window_model_matches_lfsr_states() -> None:
    """r_b(k+lag) really shares shared_bits(n_a, n_b, lag) bits with r_a(k) (positions shifted)."""
    rng = np.random.default_rng(7)
    for _ in range(200):
        n_a = int(rng.integers(0, 60000))
        e = int(rng.integers(-7, 8))
        lag = int(rng.integers(-50, 50))
        n_b = (n_a + e - 8 * lag) % 65535  # chosen so that |n_b - n_a + 8 lag| = |e|
        assert S.shared_bits(n_a, n_b, lag) == 8 - abs(e)
        k = 60
        sa = lfsr.step_n(M.phase_state(n_a), 8 * (k + 1))  # state after stream cycle k
        sb = lfsr.step_n(M.phase_state(n_b), 8 * (k + lag + 1))
        # sb low byte = bit window shifted by e relative to sa's low byte
        ra, rb = sa & 0xFF, sb & 0xFF
        if e >= 0:   # b is e steps ahead: rb bits [7:e] = ra bits [7-e:0]
            assert (rb >> e) == (ra & (0xFF >> e))
        else:
            assert (ra >> -e) == (rb & (0xFF >> -e))
    assert S.shared_bits(0, 100, 0) == 0


def test_candidate_rules_and_negative_tests() -> None:
    """R1/R2 per candidate: C0, C3, C4 satisfy both; C1 (rev B) violates R1; C2 violates only R2."""
    c = S.candidates()
    st = {k: S.structure(v["x"], v["w"]) for k, v in c.items()}
    assert st["C0"]["R1_translate_rule"]["satisfied"] and st["C0"]["R2_simultaneous_sharing_rule"]["satisfied"]
    assert not st["C1"]["R1_translate_rule"]["satisfied"]
    assert len(st["C1"]["R1_translate_rule"]["violating_lane_pairs"]) == 28
    assert st["C1"]["n_distinct_pair_offsets"] == 1 and st["C1"]["pair_offset_cycles"] == [4096] * 8
    assert st["C2"]["R1_translate_rule"]["satisfied"] and not st["C2"]["R2_simultaneous_sharing_rule"]["satisfied"]
    v2 = st["C2"]["R2_simultaneous_sharing_rule"]["violations"]
    assert sorted((v["i"], v["j"]) for v in v2) == [(0, 7), (1, 6), (2, 5), (3, 4)]
    assert all(v["kind"] == "swapped" and abs(v["lag"]) == 4096 and v["shared_bits"] == [8, 7] for v in v2)
    for k in ("C3", "C4"):
        assert st[k]["R1_translate_rule"]["satisfied"] and st[k]["R2_simultaneous_sharing_rule"]["satisfied"]
    assert st["C0"]["lambda8_min_pairwise_lag_cycles"] == 321
    assert st["C1"]["lambda8_min_pairwise_lag_cycles"] == 512
    assert st["C3"]["lambda8_min_pairwise_lag_cycles"] == 4095  # = floor(65535 / 16), the maximum
    assert (st["C4"]["lambda8_min_pairwise_lag_cycles"], st["C4"]["lambda1_min_lag_any_shared_bit_cycles"]) == (3585, 511)
    # C2 swapped coupling is real: X_0 stream at k+4096 equals W_7 stream at k (exact copy)
    rx, rw = M.rng_streams(2, 4096 + 32, seeds=(c["C2"]["x"], c["C2"]["w"]))
    assert np.array_equal(rx[0, 4096:4096 + 32], rw[7, :32]) or np.array_equal(rw[7, 4096:4096 + 32], rx[0, :32])


def test_c3_c4_seeds_are_the_stated_progressions() -> None:
    """C3: X_i = S(32760 i), W_i = S(32760 (15 - i)); C4 with 4095; all seeds non-zero and distinct."""
    c = S.candidates()
    for name, alpha in (("C3", 32760), ("C4", 4095)):
        assert c[name]["x"] == [lfsr.step_n(0xACE1, alpha * i % 65535) for i in range(8)]
        assert c[name]["w"] == [lfsr.step_n(0xACE1, alpha * (15 - i) % 65535) for i in range(8)]
        assert 0 not in c[name]["x"] + c[name]["w"] and len(set(c[name]["x"] + c[name]["w"])) == 16
    assert (c["C0"]["x"], c["C0"]["w"]) == tuple(M.lane_seeds(2, "A"))
    assert (c["C1"]["x"], c["C1"]["w"]) == tuple(M.lane_seeds(2, "B"))


def test_progression_scan_reproduces_alphas() -> None:
    """Exhaustive alpha scan (CALCULATION) selects C3 = 32760 and C4 = 4095."""
    sc = S.scan_progression_family()
    assert sc["best_lambda8_then_lambda1"] == [32760, 4095, 1]
    assert sc["best_lambda1_then_lambda8"] == [4095, 3585, 511]
    # vectorised scan agrees with the scalar metrics for both
    for alpha, (l8, l1) in ((32760, (4095, 1)), (4095, (3585, 511))):
        nx, nw = S.progression_phases(alpha)
        m = S.lag_metrics([M.phase_state(n) for n in nx], [M.phase_state(n) for n in nw])
        assert (m["lambda8_min_pairwise_lag_cycles"], m["lambda1_min_lag_any_shared_bit_cycles"]) == (l8, l1)


def test_selection_rule() -> None:
    """Worst-case correct count decides; equal worst case -> higher ensemble mean."""
    r = {"P": {"deployed_worst_n_correct": 280, "ensemble_mean_K8_10": 0.99},
         "Q": {"deployed_worst_n_correct": 281, "ensemble_mean_K8_10": 0.90},
         "R": {"deployed_worst_n_correct": 281, "ensemble_mean_K8_10": 0.95}}
    assert S.select(r) == ("R", ["R", "Q", "P"])


def test_validation_set_definition() -> None:
    """288 stratified validation images, a subset of train, disjoint from the 360 test images."""
    d = T.load_split()
    val, tr, te = set(d["val_idx"].tolist()), set(d["train_idx"].tolist()), set(d["test_idx"].tolist())
    assert len(val) == 288 and val <= tr and not val & te and len(te) == 360
    counts = np.bincount(d["y"][d["val_idx"]], minlength=10)
    assert counts.min() >= 28 and counts.max() <= 30  # stratified
    v = S.load_validation()
    assert np.array_equal(v["idx"], d["val_idx"])


@pytest.mark.skipif(not (ROOT / "reports" / "sw" / "seed_selection_revC.json").exists(),
                    reason="run sctpu.seed_select first")
def test_selection_report_and_revC_table() -> None:
    """The report was made on validation data only, selected C0, and rev C implements C0."""
    r = json.loads((ROOT / "reports" / "sw" / "seed_selection_revC.json").read_text())
    assert r["test_split_used"] is False and r["validation_set"]["n"] == 288
    assert r["selected"] == "C0" and r["ranking"][0] == "C0"
    sel = r["candidates"]["C0"]["structure"]
    sx, sw = M.lane_seeds(2, "C")
    assert sel["seeds_x"] == [f"0x{v:04X}" for v in sx] and sel["seeds_w"] == [f"0x{v:04X}" for v in sw]
    worst = {k: c["validation"]["deployed_worst_n_correct"] for k, c in r["candidates"].items()}
    assert worst["C0"] == max(worst.values())
