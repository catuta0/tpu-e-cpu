"""Exact integer golden model of the deterministic tensor unit DT-TPU (task SW-05, CR-001).

Normative source: ``design/architecture/ARCHITECTURE.md`` section 14 (rev D),
sections 14.1 (arithmetic) and 14.3 (weight memory layout) are [BIT-EXACT];
machine-readable twin ``management/INTERFACES.json`` revision D, key ``tpu``
(the old stochastic design is key ``tpu_sc`` and is modelled by
``sctpu.model``). The RTL must reproduce every HIDDEN, SCORE and RESULT value
produced by this module, bit for bit.

What is modelled (one inference, exactly what the CPU writes before START)
-------------------------------------------------------------------------
* 64 input codes x_i in 0..255 (INPUT buffer, 5.4 / 14);
* the 2048-byte weight RAM in the NEW input-major layout of 14.3:
  ``addr = base_l + 16*i + j`` (base_1 = 0, base_2 = 1024);
* 32 signed 16-bit biases, index b = 16*(l-1) + j (5.4, unchanged);
* s = CONFIG.ACT_SHIFT in 0..7 (14.4: CONFIG[3:0] is reserved in rev D).

Arithmetic (14.1), for layer l and neuron lane j = 0..15:

    q(c)  = c - 128                                    (int8 value of a code)
    acc_j = sum_{i < N_in} q(x_i) * q(W_ji)            (exact)
    Dp_j  = acc_j + 128 * bias_j
    layer 1: u_j = floor(Dp_j * 2^s / 128); h_j = clip(u_j, 0, 127);
             HIDDEN[j] = 128 + h_j  (= input code of layer 2, q(HIDDEN[j]) = h_j)
    layer 2: SCORE[j] = Dp_j (sign-extended to 32 bits)
    RESULT  = argmax_{j = 0..9} SCORE[j], ties -> lowest index.

Layer-2 lanes 10..15 are computed exactly like the others (14.2: "computed but
ignored by argmax"); the vectors therefore expect their SCORE values too.

Implementations (integer-only; no floats anywhere in this module)
-----------------------------------------------------------------
``det_inference_reference``
    Slow, literal, cycle-by-cycle transcription of 14.1/14.2: in "cycle" i the
    16 weights of input row i are fetched as the four 32-bit RAM words
    ``base_l/4 + 4i .. +3`` (the 4-bank organisation hinted in 14.3), unpacked
    little-endian and multiplied lane by lane with q(x_i); Python ints; floor
    division ``//`` for u; explicit compare-and-select for clip and argmax.
``det_inference_batch``
    Vectorised numpy (int64) model for batches of images: the weight RAM is
    reshaped to (N_in, 16) matrices, one matrix product per layer, u computed
    with an arithmetic right shift ``Dp >> (7 - s)``, ``np.clip`` and
    ``np.argmax`` (first maximum = lowest index). Independent code path; the
    unit tests check that both agree bit for bit.

Relation to the earlier models (SW-01a)
---------------------------------------
``sctpu.model.int8_inference`` (the "int8 binary baseline", SC weight layout
5.5) and ``sctpu.model.ev_inference(K=None)`` (expected value of the SC-TPU,
K -> infinity) compute h = clip((acc + 128 b) << s >> 7, 0, 127) and
score = acc + 128 b with the same codes; they are therefore mathematically
identical to 14.1. ``tests/test_det_model.py`` checks the identity on all
1797 images of the dataset for s = 0..7 and on random/extreme parameter sets.

Width analysis (``value_ranges``, CALCULATION, exact and attained)
-----------------------------------------------------------------
Because every term of acc is a product of independent operands, the bounds of
the sum are the sums of the per-product bounds, which are attained at the
vertex codes 0 (q = -128) and 255 (q = 127). ``value_ranges`` returns them
together with witnesses (operand values that reach each bound); the corner
vectors of ``sim/data/det/`` contain those witnesses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

# ---------------------------------------------------------------------------
# Constants (ARCHITECTURE.md 14.1-14.4; INTERFACES.json rev D "tpu")
# ---------------------------------------------------------------------------

SPEC_REV = "D"  #: spec revision implemented by this module (CR-001)
NL = 16  #: neuron lanes (14.2)
INPUTS_PER_CYCLE = 1  #: one input row per MAC cycle (14.2, PARAMS[15:8])
N_IN = (64, 16)  #: inputs per layer (layer 1, layer 2)
N_CLASSES = 10  #: argmax over lanes 0..9 (14.1)
WEIGHT_BASE = (0, 1024)  #: base_1, base_2 of the weight layout (14.3)
WEIGHT_RAM_BYTES = 2048  #: weight RAM size (5.4, unchanged)
WEIGHT_RAM_WORDS = WEIGHT_RAM_BYTES // 4  #: 512 words -> weights.hex lines
N_BIAS = 32  #: BIAS[0..31] (5.4)
CODE_ZERO = 128  #: code of value 0: q(c) = c - 128
Q_MIN, Q_MAX = -128, 127  #: int8 range of q(c)
H_MAX = 127  #: hidden clip upper bound (14.1)
S_MIN, S_MAX = 0, 7  #: CONFIG.ACT_SHIFT range (3-bit field [6:4])
BIAS_MIN, BIAS_MAX = -32768, 32767  #: int16 (5.4)
BIAS_SCALE = 128  #: Dp = acc + 128*bias (14.1): bias in units of 1/128, acc in 1/2^14
HIDDEN_DIV_LOG2 = 7  #: u = floor(Dp * 2^s / 2^7) (14.1)
TPU_KIND_DET = 1  #: PARAMS[23:20] (14.4)
PARAMS_VERSION_D = 0x10  #: PARAMS[31:24] (14.4)


def params_word() -> int:
    """PARAMS register of the DT-TPU, assembled from the bit fields of 14.4.

    [7:0] NL = 16, [15:8] inputs per cycle = 1, [19:16] reserved 0,
    [23:20] TPU_KIND = 1, [31:24] version = 0x10  ->  0x1010_0110.
    """
    return (PARAMS_VERSION_D << 24) | (TPU_KIND_DET << 20) | (0 << 16) | (INPUTS_PER_CYCLE << 8) | NL


def config_word(s: int) -> int:
    """CONFIG value that selects ACT_SHIFT = s (14.4: [6:4] ACT_SHIFT, [3:0] reserved)."""
    check_s(s)
    return s << 4


def config_effective_s(raw: int) -> int:
    """ACT_SHIFT actually used after a CPU write of ``raw`` to CONFIG (14.4).

    Only bits [6:4] are stored; [3:0] are reserved (writes ignored, read 0).
    Example: the rev C demo program writes 0x08 (LOG2_L = 8) -> s = 0.
    """
    return (raw >> 4) & 0x7


def config_readback(raw: int) -> int:
    """Value read back from CONFIG after writing ``raw`` (14.4: only [6:4] kept)."""
    return raw & 0x70


def check_s(s: int) -> None:
    """Raise ValueError unless 0 <= s <= 7 (3-bit ACT_SHIFT field)."""
    if not (S_MIN <= int(s) <= S_MAX):
        raise ValueError(f"ACT_SHIFT s must be 0..7, got {s}")


def q(c: int) -> int:
    """Signed int8 value of a code: q(c) = c - 128 (14.1)."""
    c = int(c)
    if not 0 <= c <= 255:
        raise ValueError(f"code {c} out of 0..255")
    return c - CODE_ZERO


# ---------------------------------------------------------------------------
# Weight RAM layout (14.3, [BIT-EXACT]) and init-file packing
# ---------------------------------------------------------------------------

def weight_addr(layer: int, j: int, i: int) -> int:
    """Byte address of W[layer][j][i] in the rev D weight RAM (14.3).

    addr = base_l + 16*i + j with base_1 = 0, base_2 = 1024: the 16 weights of
    input row i (one per neuron lane j) are contiguous = 4 words, read in one
    cycle (14.2).
    """
    if layer not in (1, 2):
        raise ValueError("layer must be 1 or 2")
    n_in = N_IN[layer - 1]
    if not (0 <= j < NL and 0 <= i < n_in):
        raise ValueError(f"index out of range: layer {layer}, j {j}, i {i}")
    return WEIGHT_BASE[layer - 1] + NL * i + j


def pack_weight_ram(w1, w2, pad_code: int = CODE_ZERO, fill_code: int = 0) -> np.ndarray:
    """Build the 2048-byte rev D weight-RAM image from weight codes (14.3).

    Parameters
    ----------
    w1 : (16, 64) codes of layer 1, ``w1[j, i]`` (neuron j, input i) - the
         same orientation as ``model_params.json`` ``w1_codes``.
    w2 : (10, 16) or (16, 16) codes of layer 2. With 10 rows the padding
         neurons 10..15 get ``pad_code`` (128 = weight 0; any code is legal).
    fill_code : unused bytes 1280..2047 (never read by the TPU).
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
    # Literal per-element placement through weight_addr (no reshape trick here:
    # the vectorised model uses a reshape, so the two must agree).
    for layer, w in ((1, w1), (2, w2)):
        for j in range(NL):
            for i in range(N_IN[layer - 1]):
                ram[weight_addr(layer, j, i)] = w[j, i]
    return ram


def unpack_weight_ram(ram) -> tuple[np.ndarray, np.ndarray]:
    """Inverse of :func:`pack_weight_ram`: w1 (16, 64) and w2 (16, 16) codes, [j, i]."""
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
    """Pack bytes into 32-bit little-endian words: word w = bytes 4w..4w+3 (14.3)."""
    b = [int(v) for v in b]
    if len(b) % 4:
        raise ValueError("byte count must be a multiple of 4")
    return [b[4 * w] | (b[4 * w + 1] << 8) | (b[4 * w + 2] << 16) | (b[4 * w + 3] << 24)
            for w in range(len(b) // 4)]


def words_to_bytes(words: Sequence[int]) -> list[int]:
    """Inverse of :func:`bytes_to_words` (little-endian)."""
    out = []
    for w in words:
        out += [(int(w) >> (8 * k)) & 0xFF for k in range(4)]
    return out


def to_u32(v: int) -> int:
    """32-bit two's-complement image of SCORE (sign extension of Dp, 14.1)."""
    if not -(1 << 31) <= v < (1 << 31):
        raise OverflowError(f"{v} does not fit in int32")
    return v & 0xFFFFFFFF


def to_u16(v: int) -> int:
    """16-bit two's-complement image of a bias (BIAS[15:0], 5.4)."""
    if not BIAS_MIN <= v <= BIAS_MAX:
        raise OverflowError(f"bias {v} does not fit in int16")
    return v & 0xFFFF


def pack_biases(b1: Sequence[int], b2: Sequence[int]) -> np.ndarray:
    """32 BIAS values (signed), index b = 16*(l-1) + j; layer-2 padding lanes get 0."""
    b1 = [int(v) for v in b1]
    b2 = [int(v) for v in b2] + [0] * (NL - len(b2))
    if len(b1) != NL or len(b2) != NL:
        raise ValueError("need 16 layer-1 and <= 16 layer-2 biases")
    for v in b1 + b2:
        to_u16(v)  # range check
    return np.array(b1 + b2, dtype=np.int64)


def input_words(inputs: Sequence[int]) -> list[int]:
    """INPUT[0..63] as 16 words, 4 codes per word little-endian (5.4)."""
    return bytes_to_words(inputs)


def hidden_words(hidden: Sequence[int]) -> list[int]:
    """HIDDEN[0..15] as 4 words, 4 codes per word little-endian (5.4)."""
    return bytes_to_words(hidden)


def score_words(score: Sequence[int]) -> list[int]:
    """SCORE[0..15] as 16 two's-complement 32-bit words (14.1)."""
    return [to_u32(int(v)) for v in score]


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class DetResult:
    """Outputs (and debug internals) of one DT-TPU inference.

    hidden : 16 HIDDEN codes (128 + h_j).
    score  : 16 SCORE values (signed Dp_j of layer 2, all lanes incl. padding).
    result : argmax class 0..9.
    acc    : (acc of layer 1 [16], acc of layer 2 [16]) - debug only.
    dp     : (Dp of layer 1 [16], Dp of layer 2 [16]) - debug only.
    u      : 16 unclipped layer-1 values u_j - debug only.
    """

    hidden: list
    score: list
    result: int
    acc: tuple = field(default=())
    dp: tuple = field(default=())
    u: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Slow literal reference (14.1, 14.2)
# ---------------------------------------------------------------------------

def _check_inputs(inputs, weight_ram, biases, s) -> tuple[list, list, list]:
    """Validate and convert the operands of one inference to Python int lists."""
    check_s(s)
    x = [int(v) for v in inputs]
    ram = [int(v) for v in weight_ram]
    b = [int(v) for v in biases]
    if len(x) != N_IN[0] or any(not 0 <= v <= 255 for v in x):
        raise ValueError("need 64 input codes 0..255")
    if len(ram) != WEIGHT_RAM_BYTES or any(not 0 <= v <= 255 for v in ram):
        raise ValueError("need 2048 weight-RAM bytes 0..255")
    if len(b) != N_BIAS or any(not BIAS_MIN <= v <= BIAS_MAX for v in b):
        raise ValueError("need 32 int16 biases")
    return x, ram, b


def det_inference_reference(inputs: Sequence[int], weight_ram: Sequence[int],
                            biases: Sequence[int], s: int) -> DetResult:
    """Literal, cycle-by-cycle model of one DT-TPU inference (ARCHITECTURE.md 14.1, 14.2).

    ``inputs``: 64 codes; ``weight_ram``: 2048 bytes in the 14.3 layout;
    ``biases``: 32 int16 (index 16*(l-1)+j); ``s``: ACT_SHIFT 0..7.
    Every statement maps to a line of 14.1; the weight fetch follows 14.2/14.3
    (row i = words base_l/4 + 4i .. +3, byte j%4 of word j//4, little-endian).
    """
    x, ram, b = _check_inputs(inputs, weight_ram, biases, s)
    words = bytes_to_words(ram)  # the RAM as the RTL sees it: 512 x 32-bit words

    def layer(codes_in: list, layer_no: int) -> tuple[list, list]:
        n_in = N_IN[layer_no - 1]
        base_w = WEIGHT_BASE[layer_no - 1] // 4
        acc = [0] * NL                                   # acc_j = 0
        for i in range(n_in):                            # one MAC cycle per input row (14.2)
            row = words[base_w + 4 * i: base_w + 4 * i + 4]   # 16 weights of row i in one cycle
            qx = codes_in[i] - CODE_ZERO                 # q(x_i)
            for j in range(NL):
                wcode = (row[j // 4] >> (8 * (j % 4))) & 0xFF
                acc[j] += qx * (wcode - CODE_ZERO)       # acc_j += q(x_i) * q(W_ji)
        dp = [acc[j] + BIAS_SCALE * b[NL * (layer_no - 1) + j] for j in range(NL)]  # Dp = acc + 128 bias
        return acc, dp

    acc1, dp1 = layer(x, 1)
    u = [(dp1[j] * (1 << s)) // 128 for j in range(NL)]  # u = floor(Dp * 2^s / 128); // is floor
    hidden = []
    for j in range(NL):
        h = u[j]
        if h < 0:
            h = 0
        if h > H_MAX:
            h = H_MAX
        hidden.append(CODE_ZERO + h)                     # HIDDEN[j] = 128 + clip(u, 0, 127)
    acc2, dp2 = layer(hidden, 2)                         # layer-2 inputs are the HIDDEN codes
    score = list(dp2)                                    # SCORE[j] = Dp_j (all 16 lanes)
    best = 0
    for j in range(1, N_CLASSES):                        # argmax over lanes 0..9 only
        if score[j] > score[best]:                       # strict ">" -> ties keep the lowest index
            best = j
    for v in score:
        to_u32(v)                                        # SCORE must be representable in 32 bits
    return DetResult(hidden=hidden, score=score, result=best, acc=(acc1, acc2), dp=(dp1, dp2), u=u)


# ---------------------------------------------------------------------------
# Vectorised model (batch of images)
# ---------------------------------------------------------------------------

def _layer_matrices(weight_ram) -> tuple[np.ndarray, np.ndarray]:
    """q(W) as (N_in, 16) int64 matrices [i, j] for both layers, by reshaping the RAM (14.3).

    Because addr = base_l + 16 i + j, the bytes of layer l form a row-major
    (N_in, 16) array: row i = the 16 lanes of input i.
    """
    ram = np.asarray(weight_ram, dtype=np.int64)
    if ram.shape != (WEIGHT_RAM_BYTES,) or ram.min() < 0 or ram.max() > 255:
        raise ValueError("need 2048 weight-RAM bytes 0..255")
    q1 = ram[WEIGHT_BASE[0]: WEIGHT_BASE[0] + NL * N_IN[0]].reshape(N_IN[0], NL) - CODE_ZERO
    q2 = ram[WEIGHT_BASE[1]: WEIGHT_BASE[1] + NL * N_IN[1]].reshape(N_IN[1], NL) - CODE_ZERO
    return q1, q2


def det_inference_batch(inputs, weight_ram, biases, s: int) -> dict:
    """Vectorised exact model of N inferences (14.1); returns numpy int64 arrays.

    ``inputs``: (N, 64) or (64,) codes. Returns a dict with ``hidden`` (N, 16),
    ``score`` (N, 16), ``result`` (N,), and debug ``acc1``, ``dp1``, ``u``,
    ``acc2``, ``dp2`` (N, 16). u uses the identity floor(Dp 2^s / 2^7) =
    Dp >> (7 - s) (arithmetic shift, s <= 7) - a different code path from the
    floor division of the reference.
    """
    check_s(s)
    x = np.atleast_2d(np.asarray(inputs, dtype=np.int64))
    if x.shape[1] != N_IN[0] or x.min() < 0 or x.max() > 255:
        raise ValueError("inputs must be (N, 64) codes 0..255")
    b = np.asarray(biases, dtype=np.int64)
    if b.shape != (N_BIAS,) or b.min() < BIAS_MIN or b.max() > BIAS_MAX:
        raise ValueError("need 32 int16 biases")
    q1, q2 = _layer_matrices(weight_ram)
    acc1 = (x - CODE_ZERO) @ q1                                  # (N, 16)
    dp1 = acc1 + BIAS_SCALE * b[None, :NL]
    u = dp1 >> (HIDDEN_DIV_LOG2 - s)                              # arithmetic shift = floor
    h = np.clip(u, 0, H_MAX)
    hidden = CODE_ZERO + h
    acc2 = h @ q2                                                 # q(HIDDEN) = h
    dp2 = acc2 + BIAS_SCALE * b[None, NL:]
    result = np.argmax(dp2[:, :N_CLASSES], axis=1)               # first max = lowest index
    return {"hidden": hidden, "score": dp2, "result": result,
            "acc1": acc1, "dp1": dp1, "u": u, "acc2": acc2, "dp2": dp2}


def det_inference(inputs, weight_ram, biases, s: int) -> DetResult:
    """Single-image convenience wrapper around :func:`det_inference_batch`."""
    r = det_inference_batch(np.asarray(inputs)[None, :], weight_ram, biases, s)
    return DetResult(hidden=[int(v) for v in r["hidden"][0]], score=[int(v) for v in r["score"][0]],
                     result=int(r["result"][0]),
                     acc=([int(v) for v in r["acc1"][0]], [int(v) for v in r["acc2"][0]]),
                     dp=([int(v) for v in r["dp1"][0]], [int(v) for v in r["dp2"][0]]),
                     u=[int(v) for v in r["u"][0]])


# ---------------------------------------------------------------------------
# Worst-case widths (CALCULATION, 14.1 "internal widths must be sufficient")
# ---------------------------------------------------------------------------

def signed_bits(lo: int, hi: int) -> int:
    """Smallest two's-complement width that holds every integer in [lo, hi]."""
    n = 1
    while not (-(1 << (n - 1)) <= lo and hi <= (1 << (n - 1)) - 1):
        n += 1
    return n


def value_ranges() -> dict:
    """Exact worst-case ranges of every intermediate for legal inputs (CALCULATION).

    Legal inputs: input and weight codes 0..255 (q in -128..127), biases int16,
    s in 0..7. Layer-2 operands are HIDDEN codes 128..255, so q(x) = h in 0..127.
    Bounds are exact (attained): products are independent, so the extreme sum
    is the sum of the per-product extremes, reached at codes 0 / 255; the
    ``witness`` entries give operand values that reach each bound.
    """
    qx1 = (Q_MIN, Q_MAX)          # layer-1 input q range
    qx2 = (0, H_MAX)              # layer-2 input q = h range
    qw = (Q_MIN, Q_MAX)

    def prod_range(a, b):
        c = [a[0] * b[0], a[0] * b[1], a[1] * b[0], a[1] * b[1]]
        return min(c), max(c)

    p1 = prod_range(qx1, qw)      # (-16256, 16384)
    p2 = prod_range(qx2, qw)      # (-16256, 16129)
    acc1 = (N_IN[0] * p1[0], N_IN[0] * p1[1])
    acc2 = (N_IN[1] * p2[0], N_IN[1] * p2[1])
    bt = (BIAS_SCALE * BIAS_MIN, BIAS_SCALE * BIAS_MAX)
    dp1 = (acc1[0] + bt[0], acc1[1] + bt[1])
    dp2 = (acc2[0] + bt[0], acc2[1] + bt[1])
    dp1s = (dp1[0] << S_MAX, dp1[1] << S_MAX)            # Dp * 2^s if computed literally (s = 7)
    # u = floor(Dp 2^s / 128) = Dp >> (7 - s): |u| <= |Dp|, largest at s = 7 (u = Dp)
    u = dp1
    entries = {
        "product_layer1": p1, "product_layer2": p2,
        "acc_layer1": acc1, "acc_layer2": acc2,
        "bias_term_128b": bt,
        "Dp_layer1": dp1, "Dp_layer2": dp2,
        "Dp_layer1_times_2^s_max_s7": dp1s,
        "u_layer1": u,
        "SCORE": dp2,
    }
    out = {name: {"min": lo, "max": hi, "abs_max": max(-lo, hi), "signed_bits": signed_bits(lo, hi)}
           for name, (lo, hi) in entries.items()}
    out["witness"] = {
        "acc_layer1_max": "all x codes 0 and all W1 codes 0: 64 * (-128)(-128) = +2^20 = 1048576",
        "acc_layer1_min": "all x codes 0 and all W1 codes 255: 64 * (-128)(127) = -1040384",
        "Dp_layer1_max": "acc1 max with bias +32767: 1048576 + 4194176 = 5242752",
        "Dp_layer1_min": "acc1 min with bias -32768: -1040384 - 4194304 = -5234688",
        "acc_layer2_max": "all h = 127 and all W2 codes 255: 16 * 127 * 127 = 258064",
        "acc_layer2_min": "all h = 127 and all W2 codes 0: 16 * 127 * (-128) = -260096",
        "Dp_layer2_max": "acc2 max with bias +32767: 258064 + 4194176 = 4452240",
        "Dp_layer2_min": "acc2 min with bias -32768: -260096 - 4194304 = -4454400",
    }
    out["notes"] = [
        "layer-1 products need 16-bit signed (+16384 = (-128)(-128) does not fit in 15 bits); "
        "layer-2 products (h 0..127 unsigned x int8) fit in 15-bit signed",
        "an accumulator pre-loaded with 128*bias stays within the Dp range at every cycle "
        "(partial sums of k products lie inside k times the per-product range)",
        "u = floor(Dp*2^s/128) = Dp >>> (7-s) (arithmetic right shift, s <= 7): no left shift and "
        "no extra width needed; |u| <= |Dp|",
        "floor vs truncation of u differ only for negative Dp, which is clipped to h = 0 either way: "
        "the difference is NOT observable at HIDDEN (rounding to nearest WOULD be observable)",
        "SCORE (Dp layer 2) needs 24 bits; it is sign-extended to 32 bits",
    ]
    return out
