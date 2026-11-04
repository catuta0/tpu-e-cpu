#!/usr/bin/env python3
"""Independent SC-TPU reference written by the independent reviewer (REV-01b).

Written ONLY from design/architecture/ARCHITECTURE.md sections 5.2, 5.3, 5.5,
10 and 12 (rev C) and management/INTERFACES.json rev C. It does NOT import
anything from code/python/sctpu (no shared code with the golden model).

Usage:
  python3 indep_model.py <vector_file> [max_vectors] [--pset-dir sim/data]
Compares every HIDDEN / SCORE / RESULT field of the vector file with this
model and prints the number of mismatching fields. Also prints, for the first
two vectors, the layer-1 accumulators acc_0..acc_3 and the RESULT.
"""
import sys
import os

# ---- spec 5.3 / 12: LFSR -----------------------------------------------------
def step(s):
    # fb = s[15]^s[13]^s[12]^s[10]; s' = ((s<<1)|fb) & 0xFFFF
    fb = ((s >> 15) ^ (s >> 13) ^ (s >> 12) ^ (s >> 10)) & 1
    return ((s << 1) | fb) & 0xFFFF

def rotl8(v, n):
    n &= 7
    return ((v << n) | (v >> (8 - n))) & 0xFF

def seeds(mode):
    # Rev C (ARCHITECTURE.md 12)
    if mode in (0, 1):
        return [0xACE1], [0xF9DE]
    return ([(0xACE1 + 0x3C5A * i) & 0xFFFF for i in range(8)],
            [(0x7A5C + 0x2B67 * i) & 0xFFFF for i in range(8)])

# ---- spec 5.5: weight layout -------------------------------------------------
def waddr(layer, j, i):
    base = 0 if layer == 1 else 1024
    return base + ((i // 8) * 16 + j) * 8 + (i % 8)

def floordiv(a, b):
    # mathematical floor for integers (Python // is already floor)
    return a // b

def infer(inp, wram, bias, K, s, mode):
    L = 1 << K
    sx, sw = seeds(mode)
    hidden = None
    accs = []
    score = None
    for layer in (1, 2):
        n_in = 64 if layer == 1 else 16
        xs = inp if layer == 1 else hidden
        acc = [0] * 16
        for t in range(n_in // 8):
            for k in range(L):
                # one stream cycle: every LFSR 8 single steps, r = low byte of new state
                for n in range(len(sx)):
                    for _ in range(8):
                        sx[n] = step(sx[n]); sw[n] = step(sw[n])
                if mode == 2:
                    rx = [sx[i] & 0xFF for i in range(8)]
                    rw = [sw[i] & 0xFF for i in range(8)]
                elif mode == 1:
                    rx = [rotl8(sx[0] & 0xFF, i) for i in range(8)]
                    rw = [rotl8(sw[0] & 0xFF, i) for i in range(8)]
                else:
                    rx = [sx[0] & 0xFF] * 8
                    rw = [sw[0] & 0xFF] * 8
                bx = [1 if rx[i] < xs[8 * t + i] else 0 for i in range(8)]
                for j in range(16):
                    c = 0
                    for i in range(8):
                        bw = 1 if rw[i] < wram[waddr(layer, j, 8 * t + i)] else 0
                        c += 1 if bw == bx[i] else 0
                    acc[j] += c
        accs.append(acc)
        dp = []
        for j in range(16):
            D = 2 * acc[j] - n_in * L
            B = floordiv(bias[16 * (layer - 1) + j] * (1 << K), 128)
            dp.append(D + B)
        if layer == 1:
            hidden = []
            for j in range(16):
                u = floordiv(dp[j] * (1 << (s + 7)), 1 << K)
                hidden.append(128 + min(max(u, 0), 127))
        else:
            score = dp
    best = 0
    for j in range(1, 10):
        if score[j] > score[best]:
            best = j
    return hidden, score, best, accs

def read_hex(path, width):
    vals = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('//') and not line.startswith('#'):
                vals.append(int(line, 16))
    return vals

def load_pset(ddir, pset):
    if pset == 0:
        wf, bf = os.path.join(ddir, 'weights.hex'), os.path.join(ddir, 'bias.hex')
    else:
        wf = os.path.join(ddir, 'corner', f'pset{pset}_weights.hex')
        bf = os.path.join(ddir, 'corner', f'pset{pset}_bias.hex')
    words = read_hex(wf, 32)
    assert len(words) == 512
    wram = []
    for w in words:  # little-endian: byte 4w at bits [7:0]
        wram += [(w >> (8 * b)) & 0xFF for b in range(4)]
    b16 = read_hex(bf, 16)
    assert len(b16) == 32
    bias = [v - 65536 if v & 0x8000 else v for v in b16]
    return wram, bias

def main():
    vf = sys.argv[1]
    nmax = int(sys.argv[2]) if len(sys.argv) > 2 else 10 ** 9
    ddir = sys.argv[3] if len(sys.argv) > 3 else os.path.dirname(os.path.abspath(vf))
    psets = {}
    nvec = nbad = nfields = 0
    with open(vf) as f:
        for line in f:
            if line.startswith('#') or not line.strip():
                continue
            fl = [int(x, 16) for x in line.split()]
            assert len(fl) == 43, len(fl)
            pset, K, s, mode, idx, label = fl[:6]
            if pset not in psets:
                psets[pset] = load_pset(ddir, pset)
            wram, bias = psets[pset]
            inp = []
            for w in fl[6:22]:
                inp += [(w >> (8 * b)) & 0xFF for b in range(4)]
            hid, sc, res, accs = infer(inp, wram, bias, K, s, mode)
            hw = [hid[4 * w] | hid[4 * w + 1] << 8 | hid[4 * w + 2] << 16 | hid[4 * w + 3] << 24 for w in range(4)]
            sw = [v & 0xFFFFFFFF for v in sc]
            exp_h, exp_s, exp_r = fl[22:26], fl[26:42], fl[42]
            bad = sum(a != b for a, b in zip(hw, exp_h)) + sum(a != b for a, b in zip(sw, exp_s)) + (res != exp_r)
            nfields += 21
            if nvec < 2:
                print(f"vec {nvec}: pset={pset} K={K} s={s} mode={mode} idx={idx} label={label} "
                      f"acc1[0..3]={accs[0][:4]} acc2[0..3]={accs[1][:4]} score[0..9]={sc[:10]} "
                      f"RESULT={res} expected={exp_r} mismatching_fields={bad}")
            nbad += bad
            nvec += 1
            if nvec >= nmax:
                break
    print(f"SUMMARY file={vf} vectors={nvec} fields={nfields} mismatching_fields={nbad}")

if __name__ == '__main__':
    main()
