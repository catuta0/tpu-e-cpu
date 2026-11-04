"""Unit tests of the rev A vs rev B comparison helpers (task SW-02).

Covered:
* exact McNemar p-value against scipy's exact binomial test and hand values;
* Newcombe paired-difference CI: contains the point estimate, symmetric
  limiting cases, agrees with a brute-force Wald interval for large n;
* the structural rev B finding: with equal X/W lane spacing every lane's
  (r_x, r_w) pair stream is the neighbour's stream delayed by 512 cycles, so
  count tables repeat across (tile, lane) slots (K = 9: slot (t, i+1) equals
  slot (t+1, i)); rev A and the analysis-only candidate C1 have none.
Run: ``.venv/bin/python -m pytest -q code/python/tests``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sctpu import compare_revs as C  # noqa: E402
from sctpu import lfsr  # noqa: E402
from sctpu import model as M  # noqa: E402


def test_mcnemar_exact_matches_scipy_binomtest() -> None:
    """p = two-sided exact binomial(b+c, 1/2) on the discordant counts."""
    for b, c in ((22, 5), (8, 6), (0, 0), (0, 7), (84, 47), (12, 156), (3, 3)):
        p = C.mcnemar_exact(b, c)
        ref = 1.0 if b + c == 0 else stats.binomtest(min(b, c), b + c, 0.5).pvalue
        assert abs(p - ref) < 1e-12, (b, c, p, ref)
    assert C.mcnemar_exact(0, 7) == 2 / 2 ** 7  # all 7 discordant one way: 2 * (1/2)^7
    assert C.mcnemar_exact(3, 3) == 1.0


def test_newcombe_ci_properties() -> None:
    """CI contains the estimate; swapping A/B mirrors it; close to Wald for large n."""
    lo, hi = C.newcombe_paired_ci(318, 22, 5, 15)
    d = (5 - 22) / 360
    assert lo < d < hi and hi < 0  # significant drop, consistent with McNemar p = 0.0015
    lo2, hi2 = C.newcombe_paired_ci(318, 5, 22, 15)
    assert abs(lo2 + hi) < 1e-12 and abs(hi2 + lo) < 1e-12
    # large-n sanity: Wald interval of the paired difference
    a, b, c, d_ = 60000, 3000, 2000, 35000
    n = a + b + c + d_
    diff = (c - b) / n
    se = np.sqrt((b + c) / n - diff ** 2) / np.sqrt(n)
    lo, hi = C.newcombe_paired_ci(a, b, c, d_)
    assert abs(lo - (diff - 1.96 * se)) < 2e-4 and abs(hi - (diff + 1.96 * se)) < 2e-4


def test_paired_cells_counts() -> None:
    """2x2 bookkeeping of paired_cells."""
    ok_a = np.array([1, 1, 0, 0, 1], bool)
    ok_b = np.array([1, 0, 1, 0, 1], bool)
    r = C.paired_cells(ok_a, ok_b)
    assert (r["both_correct"], r["A_only_correct"], r["B_only_correct"], r["both_wrong"]) == (2, 1, 1, 1)
    assert r["acc_A"] == r["acc_B"] == 0.6 and r["diff_B_minus_A"] == 0.0


def test_revB_pair_streams_are_delayed_copies() -> None:
    """Rev B: (r_x,i+1(k), r_w,i+1(k)) = (r_x,i(k+512), r_w,i(k+512)) for every lane."""
    rx, rw = M.rng_streams(2, 512 + 64, spec_rev="B")
    for i in range(7):
        assert np.array_equal(rx[i + 1, :64], rx[i, 512:576])
        assert np.array_equal(rw[i + 1, :64], rw[i, 512:576])
    info = C.seed_info(*M.lane_seeds(2, "B"))
    assert info["n_distinct_pair_offsets"] == 1
    assert C.seed_info(*M.lane_seeds(2, "A"))["n_distinct_pair_offsets"] == 8


def test_revB_count_tables_repeat_at_K9_only_in_revB() -> None:
    """K = 9 (L = 512 = the lane delay): table of slot (t, i+1) == table of slot (t+1, i)."""
    eB = M.SCEngine(9, 2, spec_rev="B")
    for t in range(9):
        for i in range(7):
            assert np.array_equal(eB.table[t, i + 1], eB.table[t + 1, i])
    assert C.identical_table_pairs(eB) == 196
    assert C.identical_table_pairs(M.SCEngine(9, 2, spec_rev="A")) == 0
    assert C.identical_table_pairs(M.SCEngine(9, 2, seeds=C.candidate_c1_seeds())) == 0


def test_candidate_c1_seeds() -> None:
    """C1 = rev B seed values with the W lanes reversed; analysis-only, not a spec revision."""
    sx, sw = C.candidate_c1_seeds()
    bx, bw = M.lane_seeds(2, "B")
    assert sx == bx and sw == bw[::-1]
    info = C.seed_info(sx, sw)
    assert info["min_pairwise_distance_cycles"] == 512 and info["n_distinct_pair_offsets"] == 8
    # the override really reaches the streams
    rx, rw = M.rng_streams(2, 8, seeds=(sx, sw))
    assert list(rw[0]) == lfsr.stream_r_sequence(bw[7], 8)
