"""Unit tests of the SC-TPU golden model (task SW-01a, deliverable 5).

Spec: design/architecture/ARCHITECTURE.md rev A, sections 5.2-5.6 ([BIT-EXACT]).
Run: ``.venv/bin/python -m pytest -q code/python/tests``.

Covered:
* leap-forward LFSR = 8 single steps, for every one of the 65536 states (5.3);
* slow literal reference vs fast vectorised model on random cases, all
  RNG modes, K = 4..10 (5.3);
* weight-RAM layout formula and its round trip (5.5), word packing (5.4);
* floor semantics for negative values (B and u, 5.3 step 1c);
* argmax tie rule and padding lanes (5.3 step 2);
* deterministic models (EV vs int8 vs exact rational arithmetic);
* generated files (line counts and widths of 5.6; vector files re-checked).
"""

from __future__ import annotations

import json
import sys
from fractions import Fraction
from math import floor
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sctpu import lfsr  # noqa: E402
from sctpu import model as M  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "sim" / "data"
TEST_SEED = 12345  #: seed of all random test cases


# ---------------------------------------------------------------------------
# LFSR (5.3, ADR-005)
# ---------------------------------------------------------------------------

def test_leap8_equals_8_single_steps_for_all_states() -> None:
    """leap8(s) == step^8(s) for all 65536 16-bit states (linear map, exhaustive)."""
    bad = [s for s in range(1 << 16) if lfsr.leap8(s) != lfsr.step_n(s, 8)]
    assert bad == [], f"{len(bad)} mismatching states, first {bad[:5]}"


def test_leap8_masks_shift_structure() -> None:
    """New bits 8..15 are old bits 0..7 (8 shifts towards the MSB)."""
    for b in range(8, 16):
        assert lfsr.LEAP8_MASKS[b] == 1 << (b - 8)


def test_stream_r_uses_state_after_8_steps() -> None:
    """First r = low byte of step^8(seed); the seed itself is not used (ambiguity A2)."""
    seq = lfsr.stream_r_sequence(M.SEED_X, 3)
    s = M.SEED_X
    for k in range(3):
        s = lfsr.step_n(s, 8)
        assert seq[k] == s & 0xFF


def test_mode2_seeds() -> None:
    """Mode-2 seeds follow (base + step*i) mod 2^16 and none is the lock-up state 0."""
    sx, sw = M.lane_seeds(2)
    assert sx[0] == 0xACE1 and sw[0] == 0x7A5C
    assert sx[1] == (0xACE1 + 0x3C5A) & 0xFFFF and sw[7] == (0x7A5C + 7 * 0x2B67) & 0xFFFF
    assert 0 not in sx + sw
    assert M.lane_seeds(0) == M.lane_seeds(1) == ([0xACE1], [0x7A5C])


def test_rng_streams_modes() -> None:
    """Lane r values: mode 0 identical, mode 1 rotl8(r, lane), mode 2 own LFSR (5.3)."""
    rx0, rw0 = M.rng_streams(0, 20)
    rx1, rw1 = M.rng_streams(1, 20)
    rx2, _ = M.rng_streams(2, 20)
    assert (rx0 == rx0[0]).all() and (rw0 == rw0[0]).all()
    for i in range(8):
        assert [int(v) for v in rx1[i]] == [M.rotl8(int(v), i) for v in rx0[0]]
        assert [int(v) for v in rw1[i]] == [M.rotl8(int(v), i) for v in rw0[0]]
    assert list(rx2[0]) == list(rx0[0])  # lane 0 seed equals the shared seed
    assert list(rx2[3]) == lfsr.stream_r_sequence((0xACE1 + 3 * 0x3C5A) & 0xFFFF, 20)


def test_rotl8() -> None:
    """8-bit rotate left."""
    assert M.rotl8(0x81, 1) == 0x03
    assert M.rotl8(0x12, 4) == 0x21
    assert M.rotl8(0xA5, 0) == 0xA5
    assert all(M.rotl8(v, 8) == v for v in range(256))


def test_advance_seed_matches_step_n() -> None:
    """Analysis helper advance_seed == step_n (used only for ensemble studies)."""
    for seed, n in ((0xACE1, 0), (0xACE1, 1), (0x7A5C, 1000), (0x1234, 65535)):
        assert M.advance_seed(seed, n) == lfsr.step_n(seed, n)


# ---------------------------------------------------------------------------
# Layout and packing (5.4, 5.5)
# ---------------------------------------------------------------------------

def test_weight_addr_examples() -> None:
    """Hand-computed addresses of the 5.5 formula."""
    assert M.weight_addr(1, 0, 0) == 0
    assert M.weight_addr(1, 0, 7) == 7
    assert M.weight_addr(1, 1, 0) == 8          # next neuron: +IL
    assert M.weight_addr(1, 0, 8) == 128        # next tile: +NL*IL
    assert M.weight_addr(1, 15, 63) == 1023
    assert M.weight_addr(2, 0, 0) == 1024
    assert M.weight_addr(2, 15, 15) == 1024 + (16 + 15) * 8 + 7 == 1279


def test_weight_addr_is_bijection() -> None:
    """Layer 1 covers 0..1023 and layer 2 1024..1279 exactly once."""
    a1 = sorted(M.weight_addr(1, j, i) for j in range(16) for i in range(64))
    a2 = sorted(M.weight_addr(2, j, i) for j in range(16) for i in range(16))
    assert a1 == list(range(1024)) and a2 == list(range(1024, 1280))


def test_tile_is_128_contiguous_bytes() -> None:
    """A tile (16 neurons x 8 inputs) is 128 contiguous bytes = 32 words (5.5)."""
    for t in range(8):
        addrs = sorted(M.weight_addr(1, j, 8 * t + i) for j in range(16) for i in range(8))
        assert addrs == list(range(128 * t, 128 * t + 128))


def test_pack_unpack_roundtrip() -> None:
    """pack_weight_ram / unpack_weight_ram are inverse; padding/fill as documented."""
    rng = np.random.default_rng(TEST_SEED)
    w1 = rng.integers(0, 256, (16, 64))
    w2 = rng.integers(0, 256, (10, 16))
    ram = M.pack_weight_ram(w1, w2, fill_code=0x5A)
    u1, u2 = M.unpack_weight_ram(ram)
    assert np.array_equal(u1, w1) and np.array_equal(u2[:10], w2)
    assert (u2[10:] == 128).all() and (ram[1280:] == 0x5A).all()
    words = M.bytes_to_words(ram)
    assert len(words) == 512 and M.words_to_bytes(words) == [int(v) for v in ram]


def test_little_endian_words() -> None:
    """Word w holds bytes 4w..4w+3 little-endian (5.4/5.5)."""
    assert M.bytes_to_words([1, 2, 3, 4, 0xFF, 0, 0, 0x80]) == [0x04030201, 0x800000FF]
    assert M.to_u32(-1) == 0xFFFFFFFF and M.to_u16(-32768) == 0x8000
    with pytest.raises(OverflowError):
        M.to_u16(32768)


def test_clamp_log2l() -> None:
    """CONFIG.LOG2_L is clamped to 4..10 (5.3)."""
    assert [M.clamp_log2l(v) for v in range(16)] == [4] * 5 + [5, 6, 7, 8, 9] + [10] * 6


# ---------------------------------------------------------------------------
# Floor semantics (5.3 step 1c)
# ---------------------------------------------------------------------------

def test_floor_bias_negative_examples() -> None:
    """B = floor(bias*2^K/128): floor, not truncation, for negative bias."""
    assert M.floor_bias_term(-1, 4) == -1        # -16/128 = -0.125 -> -1 (trunc would be 0)
    assert M.floor_bias_term(-128, 4) == -16
    assert M.floor_bias_term(-129, 4) == -17     # -16.125 -> -17
    assert M.floor_bias_term(1, 4) == 0
    assert M.floor_bias_term(-32768, 10) == -262144
    assert M.floor_bias_term(32767, 10) == 262136


def test_floor_u_negative_examples() -> None:
    """u = floor(Dp*2^(s+7)/2^K) for negative Dp."""
    assert M.hidden_u(-1, 8, 0) == -1            # -0.5 -> -1
    assert M.hidden_u(-3, 10, 2) == -2           # -1.5 -> -2
    assert M.hidden_u(5, 10, 0) == 0             # 0.625 -> 0
    assert M.hidden_u(-5, 4, 7) == -5 * 1024


def test_floor_semantics_vectorised_vs_fraction() -> None:
    """Shift-based vectorised B, Dp, u equal exact rational floors (random, all K, s)."""
    rng = np.random.default_rng(TEST_SEED)
    for K in range(4, 11):
        bias = rng.integers(-32768, 32768, 200)
        acc = rng.integers(0, 64 * (1 << K) + 1, 200)
        dp = M._post_dp(acc, 64, bias, K)
        for a, b, d in zip(acc, bias, dp):
            B = floor(Fraction(int(b) * 2 ** K, 128))
            assert d == 2 * int(a) - 64 * (1 << K) + B
            assert M.floor_bias_term(int(b), K) == B
        for s in range(8):
            h = M._post_hidden(dp, K, s)
            for d, hh in zip(dp, h):
                u = floor(Fraction(int(d) * 2 ** (s + 7), 2 ** K))
                assert hh == 128 + min(max(u, 0), 127)
                assert M.hidden_u(int(d), K, s) == u


# ---------------------------------------------------------------------------
# Argmax (5.3 step 2)
# ---------------------------------------------------------------------------

def test_argmax_ties_lowest_index() -> None:
    """Ties go to the lowest index; lanes 10..15 are ignored."""
    assert M.argmax_lowest([5] * 16) == 0
    assert M.argmax_lowest([1, 7, 3, 7] + [0] * 12) == 1
    assert M.argmax_lowest([0] * 9 + [2] + [99] * 6) == 9
    assert M.argmax_lowest([-5, -3, -3, -9, -100, -3, -4, -6, -7, -8] + [0] * 6) == 1
    sc = np.array([[3, 9, 9, 0, 0, 0, 0, 0, 0, 9] + [50] * 6, [-1] * 16])
    assert list(M._argmax_lowest_batch(sc)) == [1, 0]


# ---------------------------------------------------------------------------
# Reference vs vectorised (5.3)
# ---------------------------------------------------------------------------

def _random_case(rng, extreme: bool = False):
    """Random inputs, weight RAM and biases; ``extreme`` uses only codes 0/128/255."""
    if extreme:
        pool = np.array([0, 1, 127, 128, 254, 255])
        x = rng.choice(pool, 64)
        ram = rng.choice(pool, 2048).astype(np.uint8)
        b = rng.choice(np.array([-32768, -129, -1, 0, 1, 127, 32767]), 32)
    else:
        x = rng.integers(0, 256, 64)
        ram = rng.integers(0, 256, 2048).astype(np.uint8)
        b = rng.integers(-4000, 4000, 32)
    return x, ram, b


@pytest.mark.parametrize("mode", [0, 1, 2])
def test_reference_vs_vectorised_random(mode: int) -> None:
    """Bit-exact agreement (HIDDEN, SCORE, RESULT, acc, Dp) on random cases, K=4..10."""
    rng = np.random.default_rng(TEST_SEED + mode)
    mismatches = 0
    cases = 0
    for K in (4, 5, 6, 7, 8, 9, 10, 4, 6):
        for extreme in (False, True):
            if K >= 9 and extreme:
                continue  # keep runtime low; K>=9 covered by the random case
            x, ram, b = _random_case(rng, extreme)
            s = int(rng.integers(0, 8))
            ref = M.sc_inference_reference(x, ram, b, K, s, mode)
            fast = M.sc_inference(x, ram, b, K, s, mode)
            cases += 1
            mismatches += sum(int(a != c) for a, c in zip(ref.hidden, fast.hidden))
            mismatches += sum(int(a != c) for a, c in zip(ref.score, fast.score))
            mismatches += int(ref.result != fast.result)
            mismatches += sum(int(a != c) for a, c in zip(ref.acc[0] + ref.acc[1], fast.acc[0] + fast.acc[1]))
            mismatches += sum(int(a != c) for a, c in zip(ref.dp[0] + ref.dp[1], fast.dp[0] + fast.dp[1]))
    assert mismatches == 0, f"{mismatches} mismatching fields over {cases} cases"
    assert cases == 16  # 7 K values x 2 kinds + K=9,10 random only


def test_reference_vs_vectorised_batch_with_digits_like_inputs() -> None:
    """Batch path == single-image reference on 6 inputs sharing one parameter set."""
    rng = np.random.default_rng(TEST_SEED)
    ram = rng.integers(0, 256, 2048).astype(np.uint8)
    b = rng.integers(-500, 500, 32)
    X = 128 + rng.integers(0, 128, (6, 64))
    for mode in (0, 1, 2):
        r = M.sc_inference_batch(X, ram, b, 5, 1, mode)
        for n in range(len(X)):
            ref = M.sc_inference_reference(X[n], ram, b, 5, 1, mode)
            assert list(r["hidden"][n]) == ref.hidden and list(r["score"][n]) == ref.score
            assert int(r["result"][n]) == ref.result


def test_all_zero_codes_deterministic() -> None:
    """Codes 0: both SNG bits always 0 -> XNOR always 1 -> acc1 = 64 L exactly."""
    for mode in (0, 1, 2):
        r = M.sc_inference_reference([0] * 64, [0] * 2048, [0] * 32, 4, 0, mode)
        assert r.acc[0] == [64 * 16] * 16 and r.hidden == [255] * 16


def test_lfsr_not_reset_between_layers() -> None:
    """Layer-2 tiles use stream cycles 8L..10L-1 (no reload between tiles/layers)."""
    eng = M.SCEngine(4, 1)
    rx, rw = M.rng_streams(1, 10 * 16)
    assert np.array_equal(eng.rx, rx) and np.array_equal(eng.rw, rw)
    # count table of layer-2 tile 0, lane 2, recomputed from cycles 128..143
    a, bb = rx[2, 128:144].astype(int), rw[2, 128:144].astype(int)
    for cx, cw in ((0, 0), (77, 200), (255, 128)):
        expect = sum(int((ai < cx) == (bi < cw)) for ai, bi in zip(a, bb))
        assert eng.table[8, 2, cx, cw] == expect


# ---------------------------------------------------------------------------
# Deterministic models
# ---------------------------------------------------------------------------

def test_ev_equals_int8_and_rational() -> None:
    """EV (K->inf) == int8 baseline == exact rational evaluation of the formulas."""
    rng = np.random.default_rng(TEST_SEED)
    X = rng.integers(0, 256, (20, 64))
    ram = rng.integers(0, 256, 2048).astype(np.uint8)
    b = rng.integers(-3000, 3000, 32)
    w1, w2 = M.unpack_weight_ram(ram)
    for s in (0, 3):
        ev = M.ev_inference(X, ram, b, s)
        i8 = M.int8_inference(X, ram, b, s)
        assert np.array_equal(ev["hidden"], i8["hidden"]) and np.array_equal(ev["score"], i8["score"])
        for n in range(3):
            v = lambda c: Fraction(int(c) - 128, 128)  # noqa: E731
            for j in range(16):
                z = sum(v(X[n, i]) * v(w1[j, i]) for i in range(64)) + Fraction(int(b[j]), 128)
                h = min(max(floor(z * 2 ** (s + 7)), 0), 127)
                assert ev["hidden"][n, j] == 128 + h


def test_ev_finite_K_formula() -> None:
    """EV at finite K: u = floor((L P/2^14 + B) 2^(s+7)/L), checked with Fractions."""
    rng = np.random.default_rng(TEST_SEED + 7)
    X = rng.integers(0, 256, (4, 64))
    ram = rng.integers(0, 256, 2048).astype(np.uint8)
    b = rng.integers(-3000, 3000, 32)
    w1, _ = M.unpack_weight_ram(ram)
    K, s = 5, 2
    ev = M.ev_inference(X, ram, b, s, K=K)
    L = 1 << K
    for n in range(4):
        for j in range(16):
            P = sum((int(X[n, i]) - 128) * (int(w1[j, i]) - 128) for i in range(64))
            edp = Fraction(L * P, 2 ** 14) + M.floor_bias_term(int(b[j]), K)
            assert ev["hidden"][n, j] == 128 + min(max(floor(edp * 2 ** (s + 7) / L), 0), 127)


def test_pixel_to_code() -> None:
    """c = 128 + (p*127 + 8)//16: 0->128, 8->192, 16->255."""
    from sctpu.train import pixel_to_code
    assert list(pixel_to_code([0, 1, 8, 15, 16])) == [128, 136, 192, 247, 255]


# ---------------------------------------------------------------------------
# Generated files (5.6) — skipped if gen_hex.py has not been run
# ---------------------------------------------------------------------------

def _hexlines(p: Path) -> list[str]:
    return p.read_text().split()


@pytest.mark.skipif(not (DATA / "weights.hex").exists(), reason="run sctpu.gen_hex first")
def test_init_files_format_and_content() -> None:
    """weights.hex 512x8, bias.hex 32x4, input.hex 16x8 hex digits; content = model_params.json."""
    w = _hexlines(DATA / "weights.hex")
    bh = _hexlines(DATA / "bias.hex")
    ih = _hexlines(DATA / "input.hex")
    assert len(w) == 512 and all(len(t) == 8 and t == t.lower() for t in w)
    assert len(bh) == 32 and all(len(t) == 4 for t in bh)
    assert len(ih) == 16 and all(len(t) == 8 for t in ih)
    mp = json.loads((DATA / "model_params.json").read_text())
    ram = M.pack_weight_ram(np.array(mp["w1_codes"]), np.array(mp["w2_codes"]))
    assert M.words_to_bytes([int(t, 16) for t in w]) == [int(v) for v in ram]
    b = M.pack_biases(mp["b1_int16"], mp["b2_int16"])
    assert [int(t, 16) for t in bh] == [M.to_u16(int(v)) for v in b]


@pytest.mark.skipif(not (DATA / "tpu_vectors_mode1.txt").exists(), reason="run sctpu.gen_hex first")
def test_vector_files_recheck_with_reference() -> None:
    """Every vector file: 43 fields per line; 3 vectors per file recomputed by the reference."""
    from sctpu import gen_hex as G
    mp = json.loads((DATA / "model_params.json").read_text())
    psets = {0: (M.pack_weight_ram(np.array(mp["w1_codes"]), np.array(mp["w2_codes"])),
                 M.pack_biases(mp["b1_int16"], mp["b2_int16"]))}
    for n in range(1, 9):
        psets[n] = (np.array(M.words_to_bytes([int(t, 16) for t in _hexlines(DATA / "corner" / f"pset{n}_weights.hex")])),
                    [int(t, 16) - (65536 if int(t, 16) & 0x8000 else 0)
                     for t in _hexlines(DATA / "corner" / f"pset{n}_bias.hex")])
    files = sorted(DATA.glob("tpu_vectors_*.txt"))
    assert len(files) == 8
    for p in files:
        vecs = G.read_vectors(p)
        assert len(vecs) in (360, 16, 51)
        for v in (vecs[0], vecs[len(vecs) // 2], vecs[-1]):
            ram, b = psets[v["pset"]]
            r = M.sc_inference_reference(v["inputs"], ram, b, v["K"], v["s"], v["mode"])
            assert (r.hidden, r.score, r.result) == (v["hidden"], v["score"], v["result"]), p.name
