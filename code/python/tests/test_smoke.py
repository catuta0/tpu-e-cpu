"""Smoke tests for the Python environment (task ST-SW-01).

Every test checks a KNOWN answer that is independent of this project's design
decisions, so a failure points to a broken environment or a broken basic
model, not to a design choice:

(a) a 16-bit maximal-length LFSR has period 2^16 - 1 = 65535 and never reaches
    the zero state;
(b) scikit-learn's ``load_digits`` dataset has 1797 samples, 64 features,
    10 classes and pixel values in 0..16 (SOURCE: scikit-learn documentation,
    "Optical recognition of handwritten digits dataset");
(c) the total number of set bits over all bytes 0..255 is 8 * 128 = 1024
    (CALCULATION: each of the 8 bit positions is set in half of the 256 values).

Run with: ``.venv/bin/python -m pytest -q code/python/tests``
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

# Make the ``sctpu`` package (in code/python/) importable without installing it.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sctpu import lfsr  # noqa: E402  (import after sys.path set-up)


def test_lfsr_period_from_seed_ace1() -> None:
    """(a) From seed 0xACE1 the LFSR returns to the seed after exactly 65535
    steps, never visits 0, and visits 65535 distinct states (all non-zero
    16-bit values)."""
    seed = 0xACE1
    reg = lfsr.LFSR16(seed)
    seen = set()
    steps = 0
    while True:
        state = reg.next()
        steps += 1
        assert state != 0, f"LFSR hit the lock-up state 0 at step {steps}"
        assert 0 < state <= 0xFFFF
        seen.add(state)
        if state == seed:
            break
        # Guard: a non-maximal tap set would cycle earlier or (with a bug)
        # never come back; stop well before running forever.
        assert steps <= lfsr.MAX_PERIOD, "seed did not recur within 65535 steps"
    assert steps == 65535
    assert len(seen) == 65535
    assert lfsr.period(seed) == 65535


def test_lfsr_first_steps_match_formula() -> None:
    """Hand-computed first step from 0xACE1 (CALCULATION).

    0xACE1 = 1010 1100 1110 0001b: bit15=1, bit13=1, bit12=0, bit10=1
    -> feedback = 1^1^0^1 = 1; next = (0xACE1 << 1 | 1) & 0xFFFF = 0x59C3.
    """
    assert lfsr.feedback(0xACE1) == 1
    assert lfsr.step(0xACE1) == 0x59C3


def test_lfsr_rejects_zero_seed() -> None:
    """Zero is the lock-up state and must be refused as a seed."""
    try:
        lfsr.LFSR16(0)
    except ValueError:
        return
    raise AssertionError("seed 0 was accepted")


def test_digits_dataset_shape() -> None:
    """(b) load_digits: 1797 samples x 64 features, 10 classes, pixels 0..16."""
    from sklearn.datasets import load_digits

    digits = load_digits()
    x, y = digits.data, digits.target
    assert x.shape == (1797, 64)
    assert y.shape == (1797,)
    assert sorted(np.unique(y).tolist()) == list(range(10))
    assert x.min() == 0
    assert x.max() == 16
    # Pixel values are integer counts (0..16) even though stored as float64.
    assert np.array_equal(x, np.round(x))


def test_popcount_bytes_sum() -> None:
    """(c) Sum of popcount(n) for n in 0..255 equals 1024."""
    total = sum(bin(n).count("1") for n in range(256))
    assert total == 1024
    # Cross-check with an independent method (int.bit_count, Python >= 3.10).
    assert sum(n.bit_count() for n in range(256)) == 1024
