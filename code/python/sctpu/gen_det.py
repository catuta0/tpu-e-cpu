"""Generate the DT-TPU (rev D) init files, test vectors and SoC expectation (task SW-05, CR-001).

Normative spec: ``design/architecture/ARCHITECTURE.md`` section 14 (14.1 and
14.3 are [BIT-EXACT]); INTERFACES.json revision D key ``tpu``. Golden model:
``sctpu.det_model``. The trained codes of ``sim/data/model_params.json``
(SW-01a, variant ``qat_noise``) are used unchanged - NOT retrained (CR-001).

Outputs in ``sim/data/det/`` (format in ``sim/data/det/README.md``); the SC
comparison-design files in ``sim/data/`` are not touched:

* ``weights.hex``  - 512 x 32-bit weight-RAM words, NEW input-major layout 14.3;
* ``bias.hex``     - 32 x 16-bit two's-complement biases (same content as SC);
* ``input.hex``    - 16 x 32-bit INPUT words of test image 0 (same as SC);
* ``corner/pset<n>_{weights,bias}.hex`` - corner parameter sets (14.3 layout);
* ``det_vectors.txt`` - one inference per line: group 0 = all 360 test images
  at the selected s, group 1 = s sweep 0..7 x test positions 0..15, group 2 =
  corner vectors (psets 1..13 x patterns x s = 0..7); first line ``# spec_rev D``;
* ``soc_expected.json`` - golden RESULT/SCORE/HIDDEN/PARAMS for ``input.hex``.

Bit-exactness evidence printed to the log (logs/sw/gen_det.log): every vector
is re-read FROM THE WRITTEN FILES (vector line + pset hex files) and
recomputed with (a) the slow literal reference ``det_inference_reference``,
(b) the vectorised ``det_inference_batch`` and (c) the earlier SW-01a
``model.int8_inference`` on the SC-layout RAM (independent third path);
33 fields per vector (16 HIDDEN, 16 SCORE, RESULT) are compared and the
mismatch counts printed.

Run: ``cd code/python && ../../.venv/bin/python -m sctpu.gen_det``.
Random corner contents: ``numpy.random.default_rng(CORNER_SEED = 2026)``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

from . import det_model as D
from . import model as M
from . import train as T

DATA_DIR = T.DATA_DIR
DET_DIR = DATA_DIR / "det"
CORNER_SEED = 2026  #: numpy seed of the random corner contents (same value as SW-01a, new stream use)
N_SWEEP = 16  #: test positions 0..15 in the s sweep
N_FIELDS = 42  #: fields per vector line
NA_LABEL = 0xF  #: label value for vectors without a dataset label
SPEC_REV_TAG = "spec_rev"
GRP_MAIN, GRP_SWEEP, GRP_CORNER = 0, 1, 2
GRP_NAMES = {GRP_MAIN: "main (360 test images, selected s)", GRP_SWEEP: "s sweep 0..7 x 16 images",
             GRP_CORNER: "corner"}
SOC_CONFIG_WRITE = 0x08  #: what sim/data/soc_demo_prog.hex writes to CONFIG (rev C: LOG2_L = 8)


# ---------------------------------------------------------------------------
# Writers / readers
# ---------------------------------------------------------------------------

def write_lines(path: Path, lines: list[str]) -> None:
    """Write text lines with LF endings and a trailing newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def write_weights_hex(path: Path, ram) -> None:
    """512 lines x 8 hex digits: word w = RAM bytes 4w..4w+3, little-endian (14.3, 5.6)."""
    words = D.bytes_to_words(ram)
    assert len(words) == D.WEIGHT_RAM_WORDS
    write_lines(path, [f"{w:08x}" for w in words])


def write_bias_hex(path: Path, biases) -> None:
    """32 lines x 4 hex digits, int16 two's complement, index b = 16(l-1)+j (5.4, 5.6)."""
    assert len(biases) == D.N_BIAS
    write_lines(path, [f"{D.to_u16(int(b)):04x}" for b in biases])


def write_input_hex(path: Path, codes) -> None:
    """16 lines x 8 hex digits: INPUT codes, 4 per word, little-endian (5.4, 5.6)."""
    words = D.input_words(codes)
    assert len(words) == 16
    write_lines(path, [f"{w:08x}" for w in words])


def read_hex(path: Path) -> list[int]:
    """Read a $readmemh-style file without comments."""
    return [int(t, 16) for t in path.read_text().split()]


def read_ram(path: Path) -> list[int]:
    """weights.hex -> 2048 weight-RAM bytes."""
    words = read_hex(path)
    assert len(words) == D.WEIGHT_RAM_WORDS, path
    return D.words_to_bytes(words)


def read_biases(path: Path) -> list[int]:
    """bias.hex -> 32 signed biases."""
    v = read_hex(path)
    assert len(v) == D.N_BIAS, path
    return [x - 65536 if x & 0x8000 else x for x in v]


def vector_line(grp: int, pset: int, s: int, idx: int, label: int, inputs, hidden, score,
                result: int) -> str:
    """One vector = 42 space-separated hex fields (sim/data/det/README.md section 2)."""
    f = [f"{grp:x}", f"{pset:x}", f"{s:x}", f"{idx:x}", f"{label:x}"]
    f += [f"{w:08x}" for w in D.input_words(inputs)]
    f += [f"{w:08x}" for w in D.hidden_words(hidden)]
    f += [f"{w:08x}" for w in D.score_words(score)]
    f += [f"{result:x}"]
    assert len(f) == N_FIELDS
    return " ".join(f)


def parse_vector_line(line: str) -> dict:
    """Inverse of :func:`vector_line`."""
    f = [int(t, 16) for t in line.split()]
    if len(f) != N_FIELDS:
        raise ValueError(f"expected {N_FIELDS} fields, got {len(f)}")
    score = [v - (1 << 32) if v & 0x80000000 else v for v in f[25:41]]
    return {"grp": f[0], "pset": f[1], "s": f[2], "idx": f[3], "label": f[4],
            "inputs": D.words_to_bytes(f[5:21]), "hidden": D.words_to_bytes(f[21:25]),
            "score": score, "result": f[41]}


def read_vectors(path: Path) -> list[dict]:
    """All non-comment lines of a vector file, parsed."""
    return [parse_vector_line(ln) for ln in path.read_text().splitlines()
            if ln.strip() and not ln.startswith("#")]


def read_spec_rev(path: Path) -> str | None:
    """The revision named by the leading '# spec_rev X' line, or None."""
    for ln in path.read_text().splitlines():
        if not ln.startswith("#"):
            break
        tok = ln[1:].split()
        if len(tok) == 2 and tok[0] == SPEC_REV_TAG:
            return tok[1]
    return None


# ---------------------------------------------------------------------------
# Corner parameter sets
# ---------------------------------------------------------------------------

def _rows_w2(spec: list[int]) -> np.ndarray:
    """(16, 16) layer-2 weight codes with row j filled with ``spec[j]``."""
    return np.array([[c] * D.N_IN[1] for c in spec], dtype=np.int64)


def corner_psets(trained: dict, test_codes: np.ndarray) -> list[dict]:
    """Hand-crafted corner parameter sets (pset 1..13) and their input patterns.

    ``trained``: dict with w1 (16,64), w2 (10,16), b1 (16,), b2 (10,) codes/ints.
    Each entry: name, purpose, w1 (16,64), w2 (16,16), b (32,), inputs (list of
    64-code arrays), optional ``expect`` (dict of assertions checked after
    generation). Random contents use ``default_rng(CORNER_SEED)``.
    """
    rng = np.random.default_rng(CORNER_SEED)
    rnd_w1 = rng.integers(0, 256, (16, 64))
    rnd_w2 = rng.integers(0, 256, (16, 16))
    rnd_in = rng.integers(0, 256, 64)
    zeros, full = np.zeros(64, np.int64), np.full(64, 255, np.int64)
    img0 = test_codes[0]
    ps = []
    # 1: all codes 0 -> q = -128 everywhere: acc1 = +2^20 (maximum, needs 22-bit signed)
    ps.append({"name": "all_zero_codes", "w1": np.zeros((16, 64), np.int64), "w2": np.zeros((16, 16), np.int64),
               "b": np.zeros(32, np.int64), "inputs": [zeros, full, img0],
               "purpose": "all weight codes 0 (q=-128), biases 0; x=0: acc1=+2^20 (max), h=127, "
                          "acc2=-260096 (min) on all lanes -> tie -> RESULT 0; x=255: acc1=-1040384 (min)",
               "expect": {0: {"acc1": [1 << 20] * 16, "acc2": [-260096] * 16, "result": 0},
                          1: {"acc1": [-1040384] * 16}}})
    # 2: all codes 255 -> q = 127
    ps.append({"name": "all_255_codes", "w1": np.full((16, 64), 255, np.int64),
               "w2": np.full((16, 16), 255, np.int64), "b": np.zeros(32, np.int64),
               "inputs": [full, zeros, img0],
               "purpose": "all weight codes 255 (q=127), biases 0; x=255: acc1=1032256, h=127, "
                          "acc2=+258064 (max); x=0: acc1=-1040384, h=0, scores 0 -> tie -> RESULT 0",
               "expect": {0: {"acc1": [1032256] * 16, "acc2": [258064] * 16, "result": 0},
                          1: {"acc1": [-1040384] * 16, "score": [0] * 16, "result": 0}}})
    # 3: layer-1 Dp extremes: even lanes weight 0 + bias max, odd lanes weight 255 + bias min
    w1 = np.array([[0 if j % 2 == 0 else 255] * 64 for j in range(16)], np.int64)
    b3 = np.concatenate([[32767 if j % 2 == 0 else -32768 for j in range(16)], rng.integers(-3000, 3000, 16)])
    ps.append({"name": "dp1_extremes", "w1": w1, "w2": rnd_w2, "b": b3, "inputs": [zeros, full, img0],
               "purpose": "x=0: Dp1 = +5242752 (even lanes, max) and -5234688 (odd lanes, min); "
                          "Dp1*2^7 reaches +671072256 / -670040064 (31-bit signed if shifted left)",
               "expect": {0: {"dp1": [5242752 if j % 2 == 0 else -5234688 for j in range(16)]}}})
    # 4: layer-2 extremes and padding lanes equal to the maximum
    w2 = _rows_w2([255] * 4 + [0] * 4 + [255] * 4 + [0] * 4)
    b4 = np.concatenate([np.full(16, 32767), [0] * 8 + [32767] * 4 + [-32768] * 4])
    ps.append({"name": "dp2_extremes", "w1": np.zeros((16, 64), np.int64), "w2": w2, "b": b4,
               "inputs": [rnd_in, img0, full],
               "purpose": "layer-1 bias +32767 forces h=127; SCORE lanes 0-3 +258064, 4-7 -260096, "
                          "8-11 +4452240 (max), 12-15 -4454400 (min); tie 8/9 -> RESULT 8 (10,11 equal, ignored)",
               "expect": {k: {"score": [258064] * 4 + [-260096] * 4 + [4452240] * 4 + [-4454400] * 4,
                              "result": 8} for k in range(3)}})
    # 5/6: saturating biases
    ps.append({"name": "bias_sat_pos", "w1": rnd_w1, "w2": rnd_w2, "b": np.full(32, 32767, np.int64),
               "inputs": [rnd_in, img0], "purpose": "all biases +32767: hidden clipped at 127",
               "expect": {0: {"hidden": [255] * 16}, 1: {"hidden": [255] * 16}}})
    ps.append({"name": "bias_sat_neg", "w1": rnd_w1, "w2": rnd_w2, "b": np.full(32, -32768, np.int64),
               "inputs": [rnd_in, img0],
               "purpose": "all biases -32768: hidden 0, all scores -4194304 -> tie -> RESULT 0",
               "expect": {0: {"hidden": [128] * 16, "score": [-4194304] * 16, "result": 0}}})
    # 7: full tie
    b7 = np.concatenate([rng.integers(-3000, 3000, 16), np.full(16, 100)])
    ps.append({"name": "argmax_tie_all", "w1": rnd_w1, "w2": np.zeros((16, 16), np.int64), "b": b7,
               "inputs": [rnd_in, img0], "purpose": "identical layer-2 rows + biases: 16 equal scores -> RESULT 0",
               "expect": {0: {"result": 0}, 1: {"result": 0}}})
    # 8: tie 3/7, padding larger
    w2 = rng.integers(0, 256, (16, 16))
    w2[7] = w2[3]
    b8 = np.concatenate([rng.integers(-3000, 3000, 16),
                         [-20000] * 3 + [20000] + [-20000] * 3 + [20000] + [-20000] * 2 + [32767] * 6])
    ps.append({"name": "argmax_tie_3_7_padding_max", "w1": rnd_w1, "w2": w2, "b": b8, "inputs": [rnd_in, img0],
               "purpose": "lanes 3 and 7 identical (tie -> 3); padding lanes 10..15 larger but ignored",
               "expect": {0: {"result": 3, "tie": (3, 7)}, 1: {"result": 3, "tie": (3, 7)}}})
    # 9: tie 8/9 (top two real lanes), padding larger
    w2 = rng.integers(0, 256, (16, 16))
    w2[9] = w2[8]
    b9 = np.concatenate([rng.integers(-3000, 3000, 16), [-20000] * 8 + [20000, 20000] + [32767] * 6])
    ps.append({"name": "argmax_tie_8_9_padding_max", "w1": rnd_w1, "w2": w2, "b": b9, "inputs": [rnd_in, img0],
               "purpose": "lanes 8 and 9 identical (tie -> 8); padding larger but ignored",
               "expect": {0: {"result": 8, "tie": (8, 9)}, 1: {"result": 8, "tie": (8, 9)}}})
    # 10: lane 9 unique maximum among 0..9 (argmax must include lane 9), padding larger
    b10 = np.concatenate([rng.integers(-3000, 3000, 16), [-20000] * 9 + [20000] + [32767] * 6])
    ps.append({"name": "argmax_lane9_padding_max", "w1": rnd_w1, "w2": rng.integers(0, 256, (16, 16)), "b": b10,
               "inputs": [rnd_in, img0], "purpose": "lane 9 is the unique maximum of lanes 0..9 -> RESULT 9; "
                                                    "padding 10..15 larger but ignored",
               "expect": {0: {"result": 9}, 1: {"result": 9}}})
    # 11: random full range
    ps.append({"name": "random_full_range", "w1": rng.integers(0, 256, (16, 64)),
               "w2": rng.integers(0, 256, (16, 16)), "b": rng.integers(-32768, 32768, 32),
               "inputs": [rng.integers(0, 256, 64), rnd_in, img0],
               "purpose": "random codes and biases over the full ranges"})
    # 12: requantisation boundaries: acc1_j = t_j (one input with q = +1), Dp1_j = t_j + 128 b_j
    t = [0, 1, -1, 127, -127, 0, -1, 1, 127, 0, -1, 1, 127, 0, -128, 0]
    bb = [0, 0, 0, 0, 1, 1, 1, 1, 126, 127, 127, 127, 127, 128, 0, -1]
    w1 = np.full((16, 64), 128, np.int64)
    w1[:, 0] = [128 + v for v in t]
    x_pos = np.full(64, 128, np.int64)
    x_pos[0] = 129  # q = +1
    x_neg = np.full(64, 128, np.int64)
    x_neg[0] = 127  # q = -1 -> acc1 = -t
    b12 = np.concatenate([bb, rng.integers(-3000, 3000, 16)])
    ps.append({"name": "requant_floor_boundaries", "w1": w1, "w2": rng.integers(0, 256, (16, 16)), "b": b12,
               "inputs": [x_pos, x_neg, img0],
               "purpose": "Dp1 = 0,1,-1,127,1,128,127,129,16255,16256,16255,16257,16383,16384,-128,-128: "
                          "floor vs round, clip at 0 and 127, every s",
               "expect": {0: {"dp1": [a + 128 * c for a, c in zip(t, bb)]}}})
    # 13: trained network with active padding lanes (random rows, maximal biases): RESULT must not change
    w2 = np.vstack([np.asarray(trained["w2"], np.int64), rng.integers(0, 256, (6, 16))])
    b13 = np.concatenate([trained["b1"], trained["b2"], np.full(6, 32767)])
    ps.append({"name": "trained_padding_lanes_active", "w1": np.asarray(trained["w1"], np.int64), "w2": w2,
               "b": b13, "inputs": [test_codes[k] for k in range(16)],
               "purpose": "trained weights, padding rows 10..15 random with bias +32767 (larger scores): "
                          "RESULT and lanes 0..9 identical to pset 0 (test positions 0..15)",
               "same_as_trained": True})
    for p in ps:
        p["ram"] = D.pack_weight_ram(p["w1"], p["w2"], fill_code=0)
        p["b"] = np.asarray(p["b"], np.int64)
        assert p["b"].shape == (32,)
    return ps


def check_expectations(p: dict, r: dict, s: int, n_pat: int) -> int:
    """Check the by-construction expectations of a corner pset; returns the number checked."""
    n = 0
    for k, exp in p.get("expect", {}).items():
        if k >= n_pat:
            continue
        for key, val in exp.items():
            if key == "tie":
                a, b = val
                assert r["score"][k][a] == r["score"][k][b], (p["name"], s, key)
            else:
                got = [int(v) for v in np.atleast_1d(r[key][k])]
                want = val if isinstance(val, list) else [val]
                assert got == want, (p["name"], s, k, key, got, want)
            n += 1
    return n


# ---------------------------------------------------------------------------
# SoC expectation
# ---------------------------------------------------------------------------

def soc_expected(codes0, ram, biases, label0: int, row0: int, out: Path) -> dict:
    """Golden SoC-level result for ``input.hex`` with the det TPU (14.1, 14.4)."""
    s = D.config_effective_s(SOC_CONFIG_WRITE)
    fast = D.det_inference(codes0, ram, biases, s)
    ref = D.det_inference_reference(codes0, ram, biases, s)
    mism = (sum(int(a != b) for a, b in zip(fast.hidden, ref.hidden))
            + sum(int(a != b) for a, b in zip(fast.score, ref.score)) + int(fast.result != ref.result))
    sha = lambda name: hashlib.sha256((out / name).read_bytes()).hexdigest()  # noqa: E731
    pw = D.params_word()
    return {
        "label": "SIMULATION (Python golden model code/python/sctpu/det_model.py; not a hardware measurement)",
        "generator": "code/python/sctpu/gen_det.py (task SW-05, CR-001)",
        "git_rev": T.git_rev(),
        "spec_rev": D.SPEC_REV,
        "spec": "ARCHITECTURE.md section 14 (DT-TPU, deterministic int8), INTERFACES.json revision D key 'tpu'",
        "input_file": "sim/data/det/input.hex", "input_sha256": sha("input.hex"),
        "weights_file": "sim/data/det/weights.hex (14.3 input-major layout)", "weights_sha256": sha("weights.hex"),
        "bias_file": "sim/data/det/bias.hex", "bias_sha256": sha("bias.hex"),
        "image": {"test_position": 0, "load_digits_row": int(row0), "dataset_label": int(label0)},
        "config_write": f"0x{SOC_CONFIG_WRITE:02x}",
        "config_note": "sim/data/soc_demo_prog.hex writes CONFIG = 0x08 (rev C LOG2_L = 8). In rev D CONFIG[3:0] "
                       "is reserved (writes ignored), so ACT_SHIFT = CONFIG[6:4] = 0 and CONFIG reads back 0x00.",
        "act_shift_s": s,
        "config_readback": f"0x{D.config_readback(SOC_CONFIG_WRITE):02x}",
        "params_expected": f"0x{pw:08x}",
        "params_fields": {"[7:0] NL": D.NL, "[15:8] inputs_per_cycle": D.INPUTS_PER_CYCLE, "[19:16] reserved": 0,
                          "[23:20] TPU_KIND": D.TPU_KIND_DET, "[31:24] version": f"0x{D.PARAMS_VERSION_D:02x}",
                          "calculation": "0x10<<24 | 1<<20 | 0<<16 | 1<<8 | 16 = 0x10000000 + 0x00100000 + "
                                         "0x00000100 + 0x00000010 = 0x10100110"},
        "result": fast.result,
        "score": fast.score,
        "score_words": [f"0x{w:08x}" for w in D.score_words(fast.score)],
        "score_note": "SCORE[j] at TPU 0x2000_0080 + 4j; all 16 lanes (10..15 padding: weight code 0x80, bias 0 "
                      "-> 0; ignored by argmax)",
        "hidden_codes": fast.hidden,
        "hidden_words": [f"0x{w:08x}" for w in D.hidden_words(fast.hidden)],
        "expected_led": fast.result,
        "expected_uart_bytes": [f"0x{0x30 + fast.result:02x}", "0x0a"],
        "expected_tohost": 1,
        "cycles": "RTL-defined (14.4 target <= 300); not part of the bit-exact expectation",
        "debug_layer1": {"acc1": fast.acc[0], "dp1": fast.dp[0], "u": fast.u},
        "debug_layer2": {"acc2": fast.acc[1]},
        "reference_crosscheck_mismatching_fields": mism,
        "result_equals_dataset_label": fast.result == int(label0),
    }


# ---------------------------------------------------------------------------
# Cross-check from the written files
# ---------------------------------------------------------------------------

def crosscheck_files(out: Path) -> dict:
    """Recompute EVERY vector of det_vectors.txt from the files on disk with three models.

    Returns per-group and total counts of vectors and mismatching fields for
    (a) the slow reference, (b) the vectorised model, (c) model.int8_inference
    on the SC layout (5.5) - 33 fields per vector.
    """
    vecs = read_vectors(out / "det_vectors.txt")
    psets = {0: (read_ram(out / "weights.hex"), read_biases(out / "bias.hex"))}
    for p in sorted(out.glob("corner/pset*_weights.hex")):
        n = int(p.name[4:].split("_")[0])
        psets[n] = (read_ram(p), read_biases(out / "corner" / f"pset{n}_bias.hex"))
    stats = {g: {"vectors": 0, "ref": 0, "vec": 0, "int8": 0} for g in GRP_NAMES}

    def cmp(h, sc, res, v) -> int:
        return (sum(int(int(a) != b) for a, b in zip(h, v["hidden"]))
                + sum(int(int(a) != b) for a, b in zip(sc, v["score"])) + int(int(res) != v["result"]))

    for v in vecs:
        ram, b = psets[v["pset"]]
        st = stats[v["grp"]]
        st["vectors"] += 1
        r = D.det_inference_reference(v["inputs"], ram, b, v["s"])
        st["ref"] += cmp(r.hidden, r.score, r.result, v)
        f = D.det_inference_batch(np.array([v["inputs"]]), ram, b, v["s"])
        st["vec"] += cmp(f["hidden"][0], f["score"][0], f["result"][0], v)
        w1, w2 = D.unpack_weight_ram(ram)
        i8 = M.int8_inference(np.array([v["inputs"]]), M.pack_weight_ram(w1, w2), np.array(b), v["s"])
        st["int8"] += cmp(i8["hidden"][0], i8["score"][0], i8["result"][0], v)
    tot = {k: sum(st[k] for st in stats.values()) for k in ("vectors", "ref", "vec", "int8")}
    return {"per_group": stats, "total": tot}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def header_lines(rev: str, s_sel: int, corner_desc: list[str]) -> list[str]:
    """'#' header of det_vectors.txt (first line = spec revision tag)."""
    return [f"# {SPEC_REV_TAG} {D.SPEC_REV}",
            "# DT-TPU (deterministic int8) test vectors - ARCHITECTURE.md section 14 (14.1, 14.3 bit-exact), "
            "INTERFACES.json rev D key 'tpu'",
            f"# generated by code/python/sctpu/gen_det.py (task SW-05, CR-001), rev {rev}; trained codes of "
            "sim/data/model_params.json (not retrained)",
            "# one vector per line, 42 hex fields: grp pset s idx label in[0..15] hidden[0..3] score[0..15] result"
            "  (see sim/data/det/README.md)",
            "# write CONFIG = s << 4 (CONFIG[3:0] reserved in rev D); pset 0 = weights.hex + bias.hex, "
            "pset n > 0 = corner/pset<n>_weights.hex + corner/pset<n>_bias.hex",
            f"# grp 0: all 360 test images, s = {s_sel} (selected), idx = position in test_indices; "
            "grp 1: s = 0..7 x test positions 0..15; grp 2: corner psets x patterns x s = 0..7 "
            "(idx = pattern number, label f = n/a)"] + ["# " + c for c in corner_desc]


def main(argv=None) -> int:
    """Generate every rev D file into sim/data/det/ and print the cross-check summary."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=DET_DIR, help="output directory (default sim/data/det)")
    args = ap.parse_args(argv)
    out = args.out
    rev = T.git_rev()
    mp = json.loads((DATA_DIR / "model_params.json").read_text())
    s_sel = int(mp["act_shift_s"])
    d = T.load_split()
    te = np.array(mp["test_indices"])
    assert np.array_equal(te, d["test_idx"]), "test split differs from model_params.json"
    codes, labels = d["codes"][te], d["y"][te]
    trained = {"w1": np.array(mp["w1_codes"]), "w2": np.array(mp["w2_codes"]),
               "b1": np.array(mp["b1_int16"]), "b2": np.array(mp["b2_int16"])}
    ram = D.pack_weight_ram(trained["w1"], trained["w2"])  # padding rows 0x80, unused bytes 0x00
    biases = D.pack_biases(trained["b1"], trained["b2"])
    print(f"# gen_det.py rev={rev} numpy={np.__version__} spec_rev={D.SPEC_REV} out={out} variant={mp['variant']} "
          f"selected s={s_sel} test images={len(te)} corner seed={CORNER_SEED}")
    print("# weights NOT retrained: sim/data/model_params.json (SW-01a)")

    write_weights_hex(out / "weights.hex", ram)
    write_bias_hex(out / "bias.hex", biases)
    write_input_hex(out / "input.hex", codes[0])
    print(f"input.hex = test position 0 = load_digits row {te[0]}, label {labels[0]}")

    lines_main, lines_sweep, lines_corner = [], [], []
    r = D.det_inference_batch(codes, ram, biases, s_sel)
    for n in range(len(te)):
        lines_main.append(vector_line(GRP_MAIN, 0, s_sel, n, int(labels[n]), codes[n], r["hidden"][n],
                                      r["score"][n], int(r["result"][n])))
    trained_res = {}
    for s in range(D.S_MIN, D.S_MAX + 1):
        r = D.det_inference_batch(codes[:N_SWEEP], ram, biases, s)
        trained_res[s] = r
        for n in range(N_SWEEP):
            lines_sweep.append(vector_line(GRP_SWEEP, 0, s, n, int(labels[n]), codes[n], r["hidden"][n],
                                           r["score"][n], int(r["result"][n])))
    cps = corner_psets(trained, codes)
    corner_desc, n_expect = [], 0
    for pn, p in enumerate(cps, start=1):
        write_weights_hex(out / "corner" / f"pset{pn}_weights.hex", p["ram"])
        write_bias_hex(out / "corner" / f"pset{pn}_bias.hex", p["b"])
        corner_desc.append(f"pset {pn}: {p['name']} - {p['purpose']}")
        X = np.array(p["inputs"], dtype=np.int64)
        for s in range(D.S_MIN, D.S_MAX + 1):
            r = D.det_inference_batch(X, p["ram"], p["b"], s)
            n_expect += check_expectations(p, r, s, len(X))
            if p.get("same_as_trained"):
                t = trained_res[s]
                assert np.array_equal(r["result"], t["result"]) and np.array_equal(r["hidden"], t["hidden"]) \
                    and np.array_equal(r["score"][:, :10], t["score"][:, :10]), (p["name"], s)
                assert (r["score"][:, 10:].max(axis=1) > r["score"][:, :10].max(axis=1)).all()
                n_expect += 1
            for k in range(len(X)):
                lines_corner.append(vector_line(GRP_CORNER, pn, s, k, NA_LABEL, X[k], r["hidden"][k],
                                                r["score"][k], int(r["result"][k])))
    print(f"corner by-construction expectations checked: {n_expect} (all PASS, assertion-based)")
    hdr = header_lines(rev, s_sel, corner_desc)
    write_lines(out / "det_vectors.txt", hdr + lines_main + lines_sweep + lines_corner)
    print(f"det_vectors.txt: {len(lines_main)} main + {len(lines_sweep)} sweep + {len(lines_corner)} corner "
          f"= {len(lines_main) + len(lines_sweep) + len(lines_corner)} vectors, {len(cps)} corner psets")

    # round trip of the init files
    assert read_ram(out / "weights.hex") == [int(v) for v in ram]
    assert read_biases(out / "bias.hex") == [int(v) for v in biases]
    assert D.words_to_bytes(read_hex(out / "input.hex")) == [int(v) for v in codes[0]]
    assert read_spec_rev(out / "det_vectors.txt") == D.SPEC_REV

    # full cross-check from the written files
    cc = crosscheck_files(out)
    for g, st in cc["per_group"].items():
        print(f"crosscheck grp {g} ({GRP_NAMES[g]}): {st['vectors']} vectors x 33 fields; mismatching fields: "
              f"reference {st['ref']}, vectorised {st['vec']}, int8_inference(SW-01a) {st['int8']}")
    t = cc["total"]
    print(f"CROSSCHECK TOTAL: {t['vectors']} vectors x 33 fields; mismatches reference = {t['ref']}, "
          f"vectorised = {t['vec']}, int8_inference = {t['int8']}")
    total_bad = t["ref"] + t["vec"] + t["int8"]

    se = soc_expected(codes[0], ram, biases, int(labels[0]), int(te[0]), out)
    (out / "soc_expected.json").write_text(json.dumps(se, indent=1) + "\n")
    total_bad += se["reference_crosscheck_mismatching_fields"]
    print(f"soc_expected.json: s={se['act_shift_s']} RESULT={se['result']} (label "
              f"{se['image']['dataset_label']}) PARAMS={se['params_expected']} SCORE[0..9]={se['score'][:10]} "
              f"HIDDEN words={se['hidden_words']} reference mismatches = {se['reference_crosscheck_mismatching_fields']}")
    for name in ("weights.hex", "bias.hex", "input.hex", "det_vectors.txt", "soc_expected.json"):
        p = out / name
        if p.exists():
            print(f"sha256 {hashlib.sha256(p.read_bytes()).hexdigest()}  {name}")
    for name in ("bias.hex", "input.hex", "weights.hex"):
        same = (out / name).read_bytes() == (DATA_DIR / name).read_bytes()
        print(f"{name} byte-identical to SC sim/data/{name}: {same}")
    print(f"FINAL MISMATCH COUNT (all vectors x 3 models + soc_expected): {total_bad}")
    return 1 if total_bad else 0


if __name__ == "__main__":
    sys.exit(main())
