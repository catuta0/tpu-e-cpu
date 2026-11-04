"""Bit-exact golden model of one SC-TPU inference (task SW-01a).

Normative source: ``design/architecture/ARCHITECTURE.md`` section 5 (rev A,
FROZEN, git ece09f0) and its machine-readable twin ``management/INTERFACES.json``
(key ``tpu``). Sections 5.2, 5.3 and 5.5 are marked [BIT-EXACT]: the RTL must
reproduce every HIDDEN, SCORE and RESULT value produced by this module.

What is modelled
----------------
Inputs of one inference (exactly what the CPU writes into the TPU before START):

* 64 input codes (INPUT buffer, 5.4), each 0..255;
* the 2048-byte weight RAM laid out per 5.5 (only bytes 0..1279 are read);
* 32 signed 16-bit biases (BIAS[b], b = 16*(l-1) + j, 5.4);
* K = CONFIG.LOG2_L (clamped by hardware to 4..10), s = CONFIG.ACT_SHIFT (0..7);
* RNG_MODE (synthesis parameter, 0 SHARED / 1 ROTATE / 2 INDEPENDENT).

Outputs: HIDDEN[16] codes, SCORE[16] signed 32-bit words, RESULT (argmax over
lanes 0..9, ties to the lowest index).

Implementations (all integer-only in the hardware-equivalent path)
-----------------------------------------------------------------
``sc_inference_reference``
    Slow, literal transcription of 5.3: Python loops over layers, tiles,
    stream cycles, neurons and lanes; LFSRs advanced by 8 *single* steps
    (``lfsr.step``) per stream cycle. Written to be obviously correct.
``SCEngine`` / ``sc_inference_batch``
    Fast numpy implementation for batches of images. It is exact (not an
    approximation): for a given (K, RNG_MODE) the random numbers r of every
    stream cycle are the same for every inference (LFSRs are reloaded with
    fixed seeds on START), so the XNOR count of one lane over one tile depends
    only on the pair (input code, weight code). It is pre-computed as a table
    ``T[tile, lane, cx, cw]`` from a 2-D histogram of (r_x, r_w) pairs; one
    inference is then a table gather + sum. The unit tests check that it agrees
    with the reference bit for bit.
``ev_inference``
    "Expected-value" deterministic model: every stochastic XNOR product is
    replaced by its exact expectation. With ``K=None`` it is the limit
    L -> infinity (what Dp/L converges to); with an integer K it is E[Dp] at
    that finite L (the bias quantisation B = floor(bias*2^K/128) is kept).
``int8_inference``
    Non-stochastic binary baseline (ADR-001 option B): signed int8 x int8
    multiply, int32 accumulate, same bias and requantisation. By construction
    it equals ``ev_inference(K=None)`` (the SC expectation is exactly the
    bilinear form); it is kept as an independently written code path.
``float_inference``
    Floating-point reference of the same network (no quantisation).

Ambiguities of the spec and the reading chosen here (all escalated in
``management/handoffs/software-engineer/SW-01a.md``):

A1  In mode 1 the rotation amount "i" is the *lane* index i mod IL (0..7), not
    the global input index 8t+i (5.3 says "i = 0..IL-1").
A2  The first stream cycle after START uses r = low byte of the state AFTER the
    first 8 steps (the seed itself is never used as r).
A3  Internal widths of acc/D/B/Dp are not specified; the model uses unbounded
    integers. Ranges needed by the RTL are documented in ``value_ranges()``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np

from . import lfsr

# ---------------------------------------------------------------------------
# Constants (ARCHITECTURE.md 5.1, 5.3, 5.4, 5.5; INTERFACES.json "tpu")
# ---------------------------------------------------------------------------

NL = 16  #: neuron lanes (5.1)
IL = 8  #: input lanes (5.1)
N_IN = (64, 16)  #: inputs per layer, layer 1 and layer 2 (5.3)
N_OUT = (16, 10)  #: real neurons per layer (layer-2 lanes 10..15 are padding, 5.5)
TILES = (N_IN[0] // IL, N_IN[1] // IL)  #: (8, 2) tiles per layer (5.3)
N_TILES_TOTAL = TILES[0] + TILES[1]  #: 10 tiles per inference
WEIGHT_BASE = (0, 1024)  #: base_1, base_2 (5.5)
WEIGHT_RAM_BYTES = 2048  #: weight RAM size (5.4)
N_BIAS = 32  #: BIAS[0..31] (5.4)
N_CLASSES = 10  #: argmax over lanes 0..9 (5.3 step 2)
CODE_ZERO = 128  #: code of value 0.0, v(c) = (c-128)/128 (5.2)

K_MIN, K_MAX = 4, 10  #: hardware clamp of CONFIG.LOG2_L (5.3)
S_MIN, S_MAX = 0, 7  #: CONFIG.ACT_SHIFT range (3 bits, 5.4)
RNG_MODES = (0, 1, 2)  #: 0 SHARED, 1 ROTATE, 2 INDEPENDENT (5.3)

SEED_X = 0xACE1  #: LFSR_X seed (5.3)
SEED_W = 0x7A5C  #: LFSR_W seed (5.3)
SEED_X_STEP = 0x3C5A  #: mode-2 seed increment for LFSR_X_i (5.3)
SEED_W_STEP = 0x2B67  #: mode-2 seed increment for LFSR_W_i (5.3)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def clamp_log2l(raw: int) -> int:
    """Return the effective K for a CONFIG.LOG2_L field value (5.3, 5.4).

    CONFIG[3:0] can hold 0..15; the hardware clamps it to 4..10.
    """
    if not 0 <= raw <= 15:
        raise ValueError("CONFIG.LOG2_L is a 4-bit field")
    return min(max(raw, K_MIN), K_MAX)


def check_k_s_mode(K: int, s: int, mode: int) -> None:
    """Validate (K, s, RNG_MODE) against the ranges of 5.3/5.4 (raises ValueError)."""
    if not K_MIN <= K <= K_MAX:
        raise ValueError(f"K={K} outside {K_MIN}..{K_MAX} (apply clamp_log2l first)")
    if not S_MIN <= s <= S_MAX:
        raise ValueError(f"s={s} outside {S_MIN}..{S_MAX}")
    if mode not in RNG_MODES:
        raise ValueError(f"RNG_MODE={mode} not in {RNG_MODES}")


def rotl8(v: int, n: int) -> int:
    """8-bit rotate left of ``v`` by ``n`` (mode 1 lane decorrelation, 5.3)."""
    n %= 8
    return ((v << n) | (v >> (8 - n))) & 0xFF if n else v & 0xFF


def code_value(c):
    """Bipolar value of a code, v(c) = (c - 128)/128 (5.2). Float, for analysis only."""
    return (np.asarray(c, dtype=np.float64) - 128.0) / 128.0


def lane_seeds(mode: int) -> tuple[list[int], list[int]]:
    """Return the (X, W) LFSR seeds as lists (5.3).

    Modes 0 and 1 have one LFSR_X and one LFSR_W (lists of length 1); mode 2
    has IL of each, seed_x_i = (0xACE1 + 0x3C5A*i) mod 2^16 and
    seed_w_i = (0x7A5C + 0x2B67*i) mod 2^16. A zero seed would lock the LFSR;
    ``lfsr.LFSR16`` rejects it and the unit tests check none occurs.
    """
    if mode in (0, 1):
        return [SEED_X], [SEED_W]
    if mode == 2:
        return ([(SEED_X + SEED_X_STEP * i) & 0xFFFF for i in range(IL)],
                [(SEED_W + SEED_W_STEP * i) & 0xFFFF for i in range(IL)])
    raise ValueError(f"RNG_MODE={mode}")


def floor_bias_term(bias: int, K: int) -> int:
    """B = floor(bias * 2^K / 128) with Python floor division (5.3 step 1c).

    Python ``//`` rounds towards minus infinity, which is the "floor" of the
    spec (an arithmetic right shift in RTL, NOT a truncating division).
    """
    return (bias * (1 << K)) // 128


def hidden_u(dp: int, K: int, s: int) -> int:
    """u = floor(Dp * 2^(s+7) / 2^K) with Python floor division (5.3 step 1c, l=1)."""
    return (dp * (1 << (s + 7))) // (1 << K)


def argmax_lowest(scores: Sequence[int]) -> int:
    """RESULT = argmax over lanes 0..9, ties -> lowest index (5.3 step 2).

    Lanes 10..15 (padding) are never considered even if they are larger.
    """
    best = 0
    for j in range(1, N_CLASSES):
        if scores[j] > scores[best]:  # strict ">" keeps the lowest index on ties
            best = j
    return best


# ---------------------------------------------------------------------------
# Weight RAM layout (5.5) and register packing (5.4, 5.6)
# ---------------------------------------------------------------------------

def weight_addr(layer: int, j: int, i: int) -> int:
    """Byte address of W[layer][j][i] in the weight RAM (5.5, [BIT-EXACT]).

    addr = base_l + (floor(i/IL)*NL + j)*IL + (i mod IL), base_1=0, base_2=1024.
    ``layer`` is 1 or 2, ``j`` 0..15, ``i`` 0..N_in-1.
    """
    if layer not in (1, 2):
        raise ValueError("layer must be 1 or 2")
    n_in = N_IN[layer - 1]
    if not (0 <= j < NL and 0 <= i < n_in):
        raise ValueError(f"index out of range: layer {layer}, j {j}, i {i}")
    return WEIGHT_BASE[layer - 1] + ((i // IL) * NL + j) * IL + (i % IL)


def pack_weight_ram(w1: np.ndarray, w2: np.ndarray, pad_code: int = CODE_ZERO,
                    fill_code: int = 0) -> np.ndarray:
    """Build the 2048-byte weight RAM image from weight codes (5.5).

    Parameters
    ----------
    w1 : (16, 64) codes of layer 1, w1[j, i].
    w2 : (10, 16) or (16, 16) codes of layer 2. If only 10 rows are given the
         padding neurons 10..15 get ``pad_code`` (128 = weight 0; 5.5 allows
         any code since argmax ignores them).
    fill_code : value of the unused bytes 1280..2047 (never read by the TPU).
    """
    w1 = np.asarray(w1, dtype=np.int64)
    w2 = np.asarray(w2, dtype=np.int64)
    if w1.shape != (NL, N_IN[0]):
        raise ValueError(f"w1 shape {w1.shape}")
    if w2.shape == (N_CLASSES, N_IN[1]):
        w2 = np.vstack([w2, np.full((NL - N_CLASSES, N_IN[1]), pad_code, np.int64)])
    if w2.shape != (NL, N_IN[1]):
        raise ValueError(f"w2 shape {w2.shape}")
    for w in (w1, w2):
        if w.min() < 0 or w.max() > 255:
            raise ValueError("weight codes must be 0..255")
    ram = np.full(WEIGHT_RAM_BYTES, fill_code, dtype=np.uint8)
    for layer, w in ((1, w1), (2, w2)):
        for j in range(NL):
            for i in range(N_IN[layer - 1]):
                ram[weight_addr(layer, j, i)] = w[j, i]
    return ram


def unpack_weight_ram(ram: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Inverse of :func:`pack_weight_ram`: return w1 (16,64) and w2 (16,16) codes (5.5)."""
    ram = np.asarray(ram, dtype=np.int64)
    if ram.shape != (WEIGHT_RAM_BYTES,):
        raise ValueError("weight RAM must have 2048 bytes")
    w1 = np.empty((NL, N_IN[0]), np.int64)
    w2 = np.empty((NL, N_IN[1]), np.int64)
    for layer, w in ((1, w1), (2, w2)):
        for j in range(NL):
            for i in range(N_IN[layer - 1]):
                w[j, i] = ram[weight_addr(layer, j, i)]
    return w1, w2


def bytes_to_words(b: Sequence[int]) -> list[int]:
    """Pack bytes into 32-bit little-endian words: word w = bytes 4w..4w+3 (5.4, 5.5)."""
    b = [int(v) for v in b]
    if len(b) % 4:
        raise ValueError("byte count must be a multiple of 4")
    return [b[4 * w] | (b[4 * w + 1] << 8) | (b[4 * w + 2] << 16) | (b[4 * w + 3] << 24)
            for w in range(len(b) // 4)]


def words_to_bytes(words: Sequence[int]) -> list[int]:
    """Inverse of :func:`bytes_to_words` (little-endian, 5.4)."""
    out = []
    for w in words:
        out += [(int(w) >> (8 * k)) & 0xFF for k in range(4)]
    return out


def to_u32(v: int) -> int:
    """Two's-complement 32-bit image of a signed value (SCORE sign extension, 5.3)."""
    if not -(1 << 31) <= v < (1 << 31):
        raise OverflowError(f"{v} does not fit in int32")
    return v & 0xFFFFFFFF


def to_u16(v: int) -> int:
    """Two's-complement 16-bit image of a signed bias (BIAS[15:0], 5.4)."""
    if not -(1 << 15) <= v < (1 << 15):
        raise OverflowError(f"bias {v} does not fit in int16")
    return v & 0xFFFF


def pack_biases(b1: Sequence[int], b2: Sequence[int]) -> np.ndarray:
    """Return the 32 BIAS words as signed ints, index b = 16*(l-1)+j (5.4).

    ``b2`` may have 10 entries; padding lanes 10..15 get bias 0.
    """
    b1 = [int(v) for v in b1]
    b2 = [int(v) for v in b2] + [0] * (NL - len(b2))
    if len(b1) != NL or len(b2) != NL:
        raise ValueError("need 16 layer-1 and <=16 layer-2 biases")
    out = np.array(b1 + b2, dtype=np.int64)
    for v in out:
        to_u16(int(v))  # range check
    return out


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class InferenceResult:
    """Outputs (and debug internals) of one inference.

    hidden : 16 HIDDEN codes (128 + h_j, 5.3 step 1c).
    score  : 16 SCORE values (signed Dp_j of layer 2).
    result : argmax class 0..9.
    acc    : (acc of layer 1 [16], acc of layer 2 [16]) — debug only.
    dp     : (Dp of layer 1 [16], Dp of layer 2 [16]) — debug only.
    """

    hidden: list
    score: list
    result: int
    acc: tuple = field(default=())
    dp: tuple = field(default=())


# ---------------------------------------------------------------------------
# Slow literal reference (5.3)
# ---------------------------------------------------------------------------

def sc_inference_reference(inputs: Sequence[int], weight_ram: Sequence[int],
                           biases: Sequence[int], K: int, s: int, mode: int) -> InferenceResult:
    """Literal, loop-based model of one SC-TPU inference (ARCHITECTURE.md 5.3).

    Every statement maps to a line of 5.3. LFSRs are advanced with 8 calls of
    the single-step function ``lfsr.step`` per stream cycle (not with the
    leap-forward masks) so that this path is independent of the fast path.
    """
    check_k_s_mode(K, s, mode)
    inputs = [int(v) for v in inputs]
    ram = [int(v) for v in weight_ram]
    biases = [int(v) for v in biases]
    assert len(inputs) == N_IN[0] and len(ram) == WEIGHT_RAM_BYTES and len(biases) == N_BIAS
    L = 1 << K

    # LFSRs are loaded with their seeds when START is accepted (5.3).
    sx, sw = lane_seeds(mode)
    sx, sw = list(sx), list(sw)

    def stream_cycle_r() -> tuple[list[int], list[int]]:
        """Advance every LFSR by 8 single steps; return r_x, r_w per input lane."""
        for n in range(len(sx)):
            for _ in range(8):
                sx[n] = lfsr.step(sx[n])
                sw[n] = lfsr.step(sw[n])
        if mode == 0:  # SHARED: every lane uses the same r
            rx = [sx[0] & 0xFF] * IL
            rw = [sw[0] & 0xFF] * IL
        elif mode == 1:  # ROTATE: lane i uses rotl8(r, i)   (ambiguity A1: lane index)
            rx = [rotl8(sx[0] & 0xFF, i) for i in range(IL)]
            rw = [rotl8(sw[0] & 0xFF, i) for i in range(IL)]
        else:  # INDEPENDENT: lane i has its own LFSR pair
            rx = [sx[i] & 0xFF for i in range(IL)]
            rw = [sw[i] & 0xFF for i in range(IL)]
        return rx, rw

    hidden = [CODE_ZERO] * NL
    score = [0] * NL
    accs, dps = [], []
    for layer in (1, 2):
        n_in = N_IN[layer - 1]
        n_tiles = n_in // IL
        layer_inputs = inputs if layer == 1 else hidden  # l=2 reads the HIDDEN buffer
        acc = [0] * NL  # step 1a
        for t in range(n_tiles):  # step 1b
            w_tile = [[ram[weight_addr(layer, j, IL * t + i)] for i in range(IL)] for j in range(NL)]
            x_tile = [layer_inputs[IL * t + i] for i in range(IL)]
            for _k in range(L):
                rx, rw = stream_cycle_r()
                for j in range(NL):
                    for i in range(IL):
                        bx = 1 if rx[i] < x_tile[i] else 0   # SNG, 5.2
                        bw = 1 if rw[i] < w_tile[j][i] else 0
                        acc[j] += 1 if bx == bw else 0       # XNOR + APC
        dp = []
        for j in range(NL):  # step 1c
            D = 2 * acc[j] - n_in * L
            B = floor_bias_term(biases[16 * (layer - 1) + j], K)
            dp.append(D + B)
        if layer == 1:
            new_hidden = []
            for j in range(NL):
                u = hidden_u(dp[j], K, s)
                h = min(max(u, 0), 127)
                new_hidden.append(128 + h)
            hidden = new_hidden
        else:
            score = dp
        accs.append(acc)
        dps.append(dp)
    return InferenceResult(hidden=hidden, score=score, result=argmax_lowest(score),
                           acc=tuple(accs), dp=tuple(dps))


# ---------------------------------------------------------------------------
# Random-number streams for the fast path (5.3)
# ---------------------------------------------------------------------------

_MSEQ: list = []
_MSEQ_POS: dict = {}


def advance_seed(seed: int, n_steps: int) -> int:
    """Return the LFSR state ``n_steps`` single steps after ``seed`` (analysis helper).

    Uses a cached walk of the full 65535-state m-sequence, so large offsets
    are O(1). Equivalent to ``lfsr.step_n(seed, n_steps)``.
    """
    if not _MSEQ:
        st = SEED_X
        for n in range(lfsr.MAX_PERIOD):
            _MSEQ.append(st)
            _MSEQ_POS[st] = n
            st = lfsr.step(st)
    return _MSEQ[(_MSEQ_POS[seed] + n_steps) % lfsr.MAX_PERIOD]


def rng_streams(mode: int, n_cycles: int, start_offset: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Return r_x and r_w per input lane for ``n_cycles`` stream cycles (5.3).

    Shapes (IL, n_cycles), dtype uint8. Column k is the r used in stream cycle
    k counted from START (k continues across tiles and layers because the
    LFSRs are never reset between them). Uses the leap-forward function
    ``lfsr.leap8`` (checked against 8 single steps by the unit tests).

    ``start_offset`` is an ANALYSIS-ONLY option (not hardware behaviour): every
    seed is first advanced by that many single steps, which keeps all relative
    phases between the LFSRs and emulates a different, equally valid random
    realisation. The hardware model always uses ``start_offset = 0``.
    """
    sx, sw = lane_seeds(mode)
    if start_offset:
        sx = [advance_seed(v, start_offset) for v in sx]
        sw = [advance_seed(v, start_offset) for v in sw]
    seq_x = [lfsr.stream_r_sequence(s0, n_cycles) for s0 in sx]
    seq_w = [lfsr.stream_r_sequence(s0, n_cycles) for s0 in sw]
    rx = np.empty((IL, n_cycles), np.uint8)
    rw = np.empty((IL, n_cycles), np.uint8)
    for i in range(IL):
        if mode == 0:
            rx[i] = seq_x[0]
            rw[i] = seq_w[0]
        elif mode == 1:
            rx[i] = [rotl8(v, i) for v in seq_x[0]]
            rw[i] = [rotl8(v, i) for v in seq_w[0]]
        else:
            rx[i] = seq_x[i]
            rw[i] = seq_w[i]
    return rx, rw


# ---------------------------------------------------------------------------
# Fast exact batch implementation
# ---------------------------------------------------------------------------

def _post_dp(acc: np.ndarray, n_in: int, bias: np.ndarray, K: int) -> np.ndarray:
    """Vectorised D = 2*acc - N_in*L, B = floor(bias*2^K/128), Dp = D + B (5.3 1c).

    ``(bias << K) >> 7`` on int64 is an arithmetic shift, i.e. floor division
    by 128 also for negative biases (same as the RTL must do).
    """
    L = 1 << K
    B = (bias.astype(np.int64) << K) >> 7
    return 2 * acc.astype(np.int64) - n_in * L + B


def _post_hidden(dp: np.ndarray, K: int, s: int) -> np.ndarray:
    """Vectorised HIDDEN = 128 + clip(floor(Dp * 2^(s+7) / 2^K), 0, 127) (5.3 1c, l=1)."""
    sh = s + 7 - K
    u = (dp << sh) if sh >= 0 else (dp >> (-sh))  # >> on int64 = floor
    return CODE_ZERO + np.clip(u, 0, 127)


def _argmax_lowest_batch(score: np.ndarray) -> np.ndarray:
    """Vectorised argmax over lanes 0..9; numpy returns the FIRST maximum = lowest index."""
    return np.argmax(score[:, :N_CLASSES], axis=1)


class SCEngine:
    """Pre-computed exact XNOR-count tables for one (K, RNG_MODE) pair.

    ``table[g, i, cx, cw]`` = number of stream cycles k of tile g (g = 0..7
    layer-1 tiles, g = 8..9 layer-2 tiles, in execution order) for which lane
    i produces XNOR(r_x < cx, r_w < cw) = 1. Derivation: with
    n_x(cx) = #{k : r_x < cx}, n_w(cw) = #{k : r_w < cw} and
    A(cx, cw) = #{k : r_x < cx and r_w < cw}, the XNOR is 1 when both bits are
    1 (A cycles) or both are 0 (L - n_x - n_w + A cycles), so
    count = L - n_x - n_w + 2A. A is an exclusive 2-D prefix sum of the
    histogram of (r_x, r_w) pairs. The table is exact because the r sequence
    after START does not depend on the data (5.3).
    """

    def __init__(self, K: int, mode: int, start_offset: int = 0) -> None:
        """Build the tables; ``start_offset`` != 0 is analysis-only (see rng_streams)."""
        check_k_s_mode(K, 0, mode)
        self.K, self.mode, self.L = K, mode, 1 << K
        L = self.L
        n_cycles = N_TILES_TOTAL * L
        self.rx, self.rw = rng_streams(mode, n_cycles, start_offset)
        table = np.empty((N_TILES_TOTAL, IL, 256, 256), np.int16)  # counts <= L <= 1024
        for g in range(N_TILES_TOTAL):
            for i in range(IL):
                a = self.rx[i, g * L:(g + 1) * L].astype(np.int64)
                b = self.rw[i, g * L:(g + 1) * L].astype(np.int64)
                hist = np.bincount(a * 256 + b, minlength=65536).reshape(256, 256)
                pref = np.zeros((257, 257), np.int64)
                pref[1:, 1:] = hist.cumsum(0).cumsum(1)
                A = pref[:256, :256]
                nx = pref[:256, 256][:, None]
                nw = pref[256, :256][None, :]
                table[g, i] = L - nx - nw + 2 * A
        self.table = table
        # Lane-indexed views: layer-1 input q = 8t+i uses tile g=t, lane i;
        # layer-2 input q = 8t+i uses tile g = 8+t, lane i.
        self.t1 = table[:TILES[0]].reshape(N_IN[0], 256, 256)
        self.t2 = table[TILES[0]:].reshape(N_IN[1], 256, 256)

    def acc(self, layer: int, x: np.ndarray, w: np.ndarray) -> np.ndarray:
        """acc_j for a batch: x (N, n_in) codes, w (16, n_in) codes -> (N, 16) (5.3 1b)."""
        tab = self.t1 if layer == 1 else self.t2
        n_in = N_IN[layer - 1]
        q = np.arange(n_in)[None, None, :]
        return tab[q, x[:, None, :], w[None, :, :]].sum(axis=2, dtype=np.int64)

    def run(self, inputs: np.ndarray, weight_ram: np.ndarray, biases: np.ndarray,
            s: int) -> dict:
        """Run a batch of inferences (5.3). Returns a dict of numpy arrays.

        Keys: ``hidden`` (N,16), ``score`` (N,16), ``result`` (N,),
        ``acc1``/``acc2`` (N,16), ``dp1``/``dp2`` (N,16).
        """
        check_k_s_mode(self.K, s, self.mode)
        x = np.atleast_2d(np.asarray(inputs, dtype=np.int64))
        biases = np.asarray(biases, dtype=np.int64)
        w1, w2 = unpack_weight_ram(weight_ram)
        acc1 = self.acc(1, x, w1)
        dp1 = _post_dp(acc1, N_IN[0], biases[None, :NL], self.K)
        hidden = _post_hidden(dp1, self.K, s)
        acc2 = self.acc(2, hidden, w2)
        dp2 = _post_dp(acc2, N_IN[1], biases[None, NL:], self.K)
        return {"hidden": hidden, "score": dp2, "result": _argmax_lowest_batch(dp2),
                "acc1": acc1, "acc2": acc2, "dp1": dp1, "dp2": dp2}


_ENGINE_CACHE: dict = {}


def get_engine(K: int, mode: int) -> SCEngine:
    """Return a cached :class:`SCEngine` for (K, mode) (tables cost ~0.1-1 s to build)."""
    key = (K, mode)
    if key not in _ENGINE_CACHE:
        _ENGINE_CACHE[key] = SCEngine(K, mode)
    return _ENGINE_CACHE[key]


def sc_inference_batch(inputs, weight_ram, biases, K: int, s: int, mode: int) -> dict:
    """Fast exact SC inference of a batch (5.3); see :class:`SCEngine`."""
    return get_engine(K, mode).run(inputs, weight_ram, biases, s)


def sc_inference(inputs, weight_ram, biases, K: int, s: int, mode: int) -> InferenceResult:
    """Fast exact SC inference of ONE image, returned like the reference (5.3)."""
    r = sc_inference_batch(np.asarray(inputs)[None, :], weight_ram, biases, K, s, mode)
    return InferenceResult(hidden=[int(v) for v in r["hidden"][0]],
                           score=[int(v) for v in r["score"][0]],
                           result=int(r["result"][0]),
                           acc=([int(v) for v in r["acc1"][0]], [int(v) for v in r["acc2"][0]]),
                           dp=([int(v) for v in r["dp1"][0]], [int(v) for v in r["dp2"][0]]))


# ---------------------------------------------------------------------------
# Deterministic models
# ---------------------------------------------------------------------------

def _bilinear(x: np.ndarray, w: np.ndarray) -> np.ndarray:
    """P_j = sum_i (x_i - 128)(W_ji - 128), the exact product sum in units of 2^-14."""
    return (x.astype(np.int64) - CODE_ZERO) @ (w.astype(np.int64) - CODE_ZERO).T


def ev_inference(inputs, weight_ram, biases, s: int, K: Optional[int] = None) -> dict:
    """Expected-value model: stochastic products replaced by their expectation (5.2, 5.3).

    Derivation. With r uniform on 0..255, P(r < c) = c/256, so for one XNOR
    E[p] = px*pw + (1-px)(1-pw) = (1 + v_x v_w)/2 exactly (v = (c-128)/128).
    Summed over N_in lanes and L cycles: E[D] = E[2 acc - N_in L]
    = L * sum_i v_x,i v_w,ji = L * P_j / 2^14 with the integer
    P_j = sum_i (x_i-128)(W_ji-128).

    * ``K is None`` (limit L -> infinity): Dp/L -> P/2^14 + bias/128, so
      layer 1: h = clip(floor((P + 128 bias) * 2^s / 2^7), 0, 127);
      layer 2: score = P + 128 bias (in units of 2^-14; argmax is scale-free).
    * integer ``K``: E[Dp] = L P / 2^14 + B with B = floor(bias 2^K/128), and
      u = floor(E[Dp] 2^(s+7) / L) = floor(((P << K) + (B << 14)) 2^(s+7) / 2^(14+K)).
      Scores are returned as 2^14 * E[Dp] (exact integers).

    The hidden activation of layer 2 inputs is the (deterministic) layer-1
    output, i.e. this is E applied layer by layer, not E of the whole chain.
    Returns a dict with ``hidden``, ``score``, ``result`` (numpy arrays).
    """
    x = np.atleast_2d(np.asarray(inputs, dtype=np.int64))
    b = np.asarray(biases, dtype=np.int64)
    w1, w2 = unpack_weight_ram(weight_ram)

    def layer_num(xx, w, bb):
        P = _bilinear(xx, w)
        if K is None:
            return P + 128 * bb[None, :], 0  # scale 2^-14
        B = (bb << K) >> 7
        return (P << K) + (B[None, :] << 14), K  # scale 2^-(14+K)

    n1, k1 = layer_num(x, w1, b[:NL])
    u = (n1 << s) >> 7 if K is None else (n1 << (s + 7)) >> (14 + k1)
    hidden = CODE_ZERO + np.clip(u, 0, 127)
    n2, _ = layer_num(hidden, w2, b[NL:])
    return {"hidden": hidden, "score": n2, "result": _argmax_lowest_batch(n2), "pre1": n1}


def int8_inference(inputs, weight_ram, biases, s: int) -> dict:
    """Binary int8 (non-stochastic) baseline datapath (ADR-001 option B).

    Operands are the same codes reinterpreted as signed int8 (c - 128), the
    accumulator is int32: acc = sum x_q w_q + 128*bias (bias in units of 1/128,
    products in units of 1/2^14). Hidden requantisation: h = clip((acc << s) >> 7,
    0, 127) (the integer form of the clipped ReLU of 5.3). Mathematically equal
    to ``ev_inference(K=None)``; the equality is checked in the accuracy study.
    """
    x = np.atleast_2d(np.asarray(inputs, dtype=np.int64))
    b = np.asarray(biases, dtype=np.int64)
    w1, w2 = unpack_weight_ram(weight_ram)
    xq = (x - 128).astype(np.int8).astype(np.int32)
    w1q = (w1 - 128).astype(np.int8).astype(np.int32)
    w2q = (w2 - 128).astype(np.int8).astype(np.int32)
    acc1 = xq @ w1q.T + (b[:NL] * 128).astype(np.int32)[None, :]
    h = np.clip((acc1.astype(np.int64) << s) >> 7, 0, 127)
    acc2 = h.astype(np.int32) @ w2q.T + (b[NL:] * 128).astype(np.int32)[None, :]
    return {"hidden": CODE_ZERO + h, "score": acc2.astype(np.int64),
            "result": _argmax_lowest_batch(acc2)}


def float_inference(xv: np.ndarray, W1: np.ndarray, b1: np.ndarray, W2: np.ndarray,
                    b2: np.ndarray, s: int) -> dict:
    """Floating-point model of the network (interpretation paragraph of 5.3).

    xv : (N, 64) input values in [-1, 1); W1 (16,64), b1 (16,), W2 (10,16), b2 (10,).
    Hidden value = clip(2^s (W1 x + b1), 0, 127/128) (no floor), score = W2 h + b2.
    """
    z1 = np.atleast_2d(xv) @ W1.T + b1[None, :]
    h = np.clip((2.0 ** s) * z1, 0.0, 127.0 / 128.0)
    z2 = h @ W2.T + b2[None, :]
    return {"hidden": h, "score": z2, "result": np.argmax(z2, axis=1)}


# ---------------------------------------------------------------------------
# Register-level views (5.4)
# ---------------------------------------------------------------------------

def input_words(inputs: Sequence[int]) -> list[int]:
    """INPUT[0..63] packed 4 codes per 32-bit word, little-endian (5.4): 16 words."""
    return bytes_to_words(inputs)


def hidden_words(hidden: Sequence[int]) -> list[int]:
    """HIDDEN[0..15] packed 4 codes per word (5.4): 4 words."""
    return bytes_to_words(hidden)


def score_words(score: Sequence[int]) -> list[int]:
    """SCORE[0..15] as 32-bit two's-complement words (5.3, 5.4): 16 words."""
    return [to_u32(int(v)) for v in score]


def value_ranges() -> dict:
    """Worst-case ranges of internal quantities over K=4..10, s=0..7 (CALCULATION).

    Provided for the RTL designer (ambiguity A3: widths are not specified in 5.3).
    For each K: acc in [0, N_in L]; D in [-N_in L, N_in L];
    B in [floor(-32768 2^K/128), floor(32767 2^K/128)]; Dp = D + B.
    The layer-1 value u = Dp 2^(s+7-K) only matters up to the clip at 0..127,
    but an RTL that shifts before clipping needs the full width; the bound is
    reported for the worst (K, s).
    """
    out = {"per_K": {}}
    worst_dp, worst_u = 0, 0
    for K in range(K_MIN, K_MAX + 1):
        L = 1 << K
        b_lo, b_hi = (-32768 << K) >> 7, (32767 << K) >> 7
        dp1_lo, dp1_hi = -N_IN[0] * L + b_lo, N_IN[0] * L + b_hi
        dp2_lo, dp2_hi = -N_IN[1] * L + b_lo, N_IN[1] * L + b_hi
        u_hi = max(abs(dp1_lo), dp1_hi) << max(0, S_MAX + 7 - K)
        out["per_K"][K] = {"acc1_max": N_IN[0] * L, "B_range": [b_lo, b_hi],
                           "Dp1_range": [dp1_lo, dp1_hi], "Dp2_range": [dp2_lo, dp2_hi],
                           "u_abs_max_s7": u_hi}
        worst_dp = max(worst_dp, abs(dp1_lo), dp1_hi)
        worst_u = max(worst_u, u_hi)
    out["acc1_bits_unsigned"] = (N_IN[0] << K_MAX).bit_length()
    out["Dp_bits_signed"] = worst_dp.bit_length() + 1
    out["u_bits_signed_if_shift_before_clip"] = worst_u.bit_length() + 1
    return out
