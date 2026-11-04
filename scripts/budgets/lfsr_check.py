#!/usr/bin/env python3
# =============================================================================
# File    : scripts/budgets/lfsr_check.py
# Purpose : REQ-01 analysis of the SC-TPU RNG defined in ARCHITECTURE.md rev A
#           sec. 5.3 (CALCULATION, exhaustive enumeration):
#   1. period of the single-step LFSR  fb = s15^s13^s12^s10, s = (s<<1|fb)&0xFFFF
#      (maximal length would be 2^16 - 1 = 65535)
#   2. period of the 8-step leap-forward sequence used per stream cycle
#   3. phase offset (in single steps) between every pair of seeds used
#      (modes 0/1: X=0xACE1, W=0x7A5C; mode 2: X_i, W_i for i = 0..7).
#      All LFSRs share one polynomial, so every stream is a time-shifted copy
#      of the same m-sequence; a small offset (in stream cycles = steps/8)
#      means two "independent" lanes re-use the same random numbers a few
#      cycles apart.
#   4. LFSR steps consumed per inference vs the period, K = 4..10.
#   5. bias of the SNG from the missing all-zero state.
# Usage   : python3 scripts/budgets/lfsr_check.py > scripts/budgets/logs/lfsr_check.log
# =============================================================================
import itertools


def step(s):
    """One single LFSR step exactly as written in spec 5.3."""
    fb = ((s >> 15) ^ (s >> 13) ^ (s >> 12) ^ (s >> 10)) & 1
    return ((s << 1) | fb) & 0xFFFF


def main():
    print("# command: python3 scripts/budgets/lfsr_check.py")
    # ---- 1. period and phase table from seed 0x0001 ----
    phase = {}
    s, n = 0x0001, 0
    while s not in phase:
        phase[s] = n
        s = step(s)
        n += 1
    period = n
    print(f"single-step period from 0x0001: {period} (maximal = 65535) -> "
          f"{'MAXIMAL' if period == 65535 else 'NOT MAXIMAL'}")
    assert 0 not in phase
    # ---- 2. 8-step leap period: P / gcd(P, 8) ----
    from math import gcd
    print(f"8-step leap period: {period // gcd(period, 8)} stream cycles")
    # ---- 3. seeds and pairwise offsets ----
    seeds = {"X": 0xACE1, "W": 0x7A5C}
    for i in range(8):
        seeds[f"X{i}"] = (0xACE1 + 0x3C5A * i) % 65536
        seeds[f"W{i}"] = (0x7A5C + 0x2B67 * i) % 65536
    for k, v in seeds.items():
        assert v != 0, f"seed {k} is the lock-up state 0"
    print("seeds (none is 0): " + ", ".join(f"{k}=0x{v:04X}" for k, v in seeds.items()))

    def off(a, b):
        """forward distance in single steps from state a to state b, and the
        circular distance min(d, P-d), both in single steps."""
        d = (phase[b] - phase[a]) % period
        return d, min(d, period - d)

    d, c = off(seeds["X"], seeds["W"])
    print(f"modes 0/1: offset X->W = {d} steps; circular min = {c} steps = {c/8:.1f} stream cycles")
    m2 = [f"X{i}" for i in range(8)] + [f"W{i}" for i in range(8)]
    worst = None
    for a, b in itertools.combinations(m2, 2):
        _, c = off(seeds[a], seeds[b])
        if worst is None or c < worst[0]:
            worst = (c, a, b)
    print(f"mode 2: smallest circular offset among the 16 LFSRs = {worst[0]} steps "
          f"= {worst[0]/8:.1f} stream cycles ({worst[1]} vs {worst[2]})")
    # ---- 4. steps per inference ----
    print("steps per inference = 10 tiles * 2^K * 8 vs period 65535:")
    for k in range(4, 11):
        steps = 10 * 2 ** k * 8
        print(f"  K={k:2d}: {steps:6d} steps = {steps/period:5.3f} periods"
              f"{'  <-- sequence WRAPS within one inference' if steps > period else ''}")
    print("overlap check modes 0/1: for K where steps > offset, LFSR_W reaches a "
          "state LFSR_X already used (or vice versa) within the same inference:")
    for k in range(4, 11):
        steps = 10 * 2 ** k * 8
        d, _ = off(seeds["X"], seeds["W"])
        e = period - d
        print(f"  K={k:2d}: X reaches W's seed after {d} steps, W reaches X's after {e}: "
              f"{'OVERLAP' if steps > min(d, e) else 'no overlap'}")
    # ---- 4b. same-lane offsets in mode 2 (these pair a lane's x and w streams) ----
    for i in range(8):
        _, c = off(seeds[f"X{i}"], seeds[f"W{i}"])
        print(f"  mode 2 lane {i}: |offset X{i}<->W{i}| = {c} steps = {c/8:.1f} stream cycles")
    # ---- 4c. empirical same-cycle correlation of r bytes over one K=8 inference ----
    import numpy as np

    def rseq(seed, n):
        """r values (low byte after each 8-step leap) for n stream cycles."""
        out, st = [], seed
        for _ in range(n):
            for _ in range(8):
                st = step(st)
            out.append(st & 0xFF)
        return np.array(out, dtype=float)

    def rotl8(v, i):
        v = v.astype(int)
        return (((v << i) | (v >> (8 - i))) & 0xFF).astype(float) if i % 8 else v.astype(float)

    n = 2560  # stream cycles in one K = 8 inference
    rx, rw = rseq(seeds["X"], n), rseq(seeds["W"], n)
    print(f"Pearson corr over {n} stream cycles (K=8), sigma for independent ~ 1/sqrt(n) = {1/np.sqrt(n):.3f}:")
    print(f"  modes 0/1 same lane:   corr(r_x, r_w) = {np.corrcoef(rx, rw)[0,1]:+.3f}")
    worst = max(abs(np.corrcoef(rotl8(rx, a), rotl8(rx, b))[0, 1]) for a in range(8) for b in range(a + 1, 8))
    print(f"  mode 1 cross-lane:     max |corr(rotl8(r_x,a), rotl8(r_x,b))| = {worst:.3f}  (mode 0: 1.000, identical)")
    seqx = [rseq(seeds[f"X{i}"], n) for i in range(8)]
    seqw = [rseq(seeds[f"W{i}"], n) for i in range(8)]
    same = max(abs(np.corrcoef(seqx[i], seqw[i])[0, 1]) for i in range(8))
    allseq = seqx + seqw
    cross = max(abs(np.corrcoef(allseq[a], allseq[b])[0, 1]) for a in range(16) for b in range(a + 1, 16))
    print(f"  mode 2 same lane:      max_i |corr(r_x_i, r_w_i)| = {same:.3f}")
    print(f"  mode 2 any pair:       max |corr| among 16 LFSRs = {cross:.3f}")
    # ---- 5. SNG bias ----
    # Over one full period every non-zero 16-bit state occurs once; the low
    # byte r = 0 occurs 255 times, r = 1..255 occur 256 times each.
    # P(r < c) = (256*c - 1)/65535 for c >= 1 instead of c/256.
    worst_bias = max(abs((256 * c - 1) / 65535 - c / 256) for c in range(1, 256))
    print(f"SNG bias from missing zero state (full period): max |P(r<c) - c/256| = {worst_bias:.2e}")


if __name__ == "__main__":
    main()
