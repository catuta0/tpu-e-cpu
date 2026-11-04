#!/usr/bin/env python3
# =============================================================================
# File    : scripts/budgets/lfsr_rules_revC.py
# Task    : REQ-02 (systems-engineer) - independent CALCULATION of the rev C
#           LFSR seed rules, written from the spec text only (it does NOT
#           import the software-engineer's golden model, so it is a second,
#           independent implementation of the same definitions).
# Spec    : design/architecture/ARCHITECTURE.md sections 5.3, 11 (rev B) and
#           12 (rev C, CURRENT); management/INTERFACES.json revision C
#           (tpu.lfsr.*); seed rules R1 / R2 as defined in ADR-009/010 and in
#           management/handoffs/software-engineer/SW-03.md ("Finding: R2").
#
# What it checks (all exhaustive over the 65535-state m-sequence):
#   1. The polynomial is maximal (period 65535) and none of the seeds is 0.
#   2. The rev C mode-2 seed tables of ARCHITECTURE.md 12 and INTERFACES.json
#      equal the formula seed_x_i = (0xACE1 + 0x3C5A*i) mod 2^16,
#      seed_w_i = (0x7A5C + 0x2B67*i) mod 2^16; the rev B tables equal
#      S(4096 i) / S(32768 + 4096 i); 0xF9DE = S(32768) (S(n) = state of the
#      LFSR started at 0xACE1 after n single steps).
#   3. Stream-cycle lags. One stream cycle = 8 single steps, so a generator at
#      phase n (single steps) is at stream-cycle phase n * 8^-1 mod 65535
#      (8^-1 = 8192 because 8 * 8192 = 65536 = 1 mod 65535). The circular
#      stream-cycle lag between two generators is min(d, 65535 - d).
#      Reported: minimum pairwise lag among the 16 mode-2 generators,
#      X_i-W_i lags, modes 0/1 X-W lag.
#   4. R1 (ADR-009/010): no two lanes' operand-pair streams are translates,
#      i.e. (n_x(i) - n_x(j)) != (n_w(i) - n_w(j)) mod 65535 for i != j.
#      Equivalent: D_i = n_w(i) - n_x(i) mod 65535 pairwise distinct.
#   5. R2 (SW-03, adopted as documented rule D-C in ADR-010): r is an 8-bit
#      window of one bit sequence, so two generators share >= 1 bit whenever
#      their single-step offset is within +/-7 of a multiple of 8 stream-cycle
#      lag; two lanes' products couple at second order if both operands share
#      bits at the same lag. Condition (single steps, circular mod 65535):
#      direct  |D_i - D_j| <= 14  (i != j),
#      swapped |D_i + D_j| <= 14  (all i, j incl. i = j).
#      R2 forbids both. For modes 0/1 (one pair) only the self-swap term
#      |2 D| <= 14 applies.
#   6. Stream cycles per inference = 10 * 2^K vs the 65535-cycle period.
# Labels  : every number printed is CALCULATION.
# Usage   : python3 scripts/budgets/lfsr_rules_revC.py \
#               > scripts/budgets/logs/lfsr_rules_revC.log
# Exit    : non-zero if any self-check (assert) fails.
# =============================================================================
import itertools
import json
import os
import re
import subprocess
import sys

P = 65535          # period of a maximal 16-bit LFSR
INV8 = 8192        # 8^-1 mod 65535 (8 * 8192 = 65536 = 1 mod 65535)
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def step(s):
    """One single LFSR step exactly as written in ARCHITECTURE.md 5.3."""
    fb = ((s >> 15) ^ (s >> 13) ^ (s >> 12) ^ (s >> 10)) & 1
    return ((s << 1) | fb) & 0xFFFF


def build_phase():
    """Walk the m-sequence from 0xACE1; return (phase dict state->n, list n->state)."""
    phase, seq, s = {}, [], 0xACE1
    while s not in phase:
        phase[s] = len(seq)
        seq.append(s)
        s = step(s)
    return phase, seq


def circ(d):
    """Circular distance on the 65535-cycle ring."""
    d %= P
    return min(d, P - d)


def check_set(name, xs, ws, phase):
    """Print lags, R1 and R2 results for one mode-2 seed set (lists of 8)."""
    nx = [phase[s] for s in xs]
    nw = [phase[s] for s in ws]
    gens = [(f"X{i}", nx[i]) for i in range(8)] + [(f"W{i}", nw[i]) for i in range(8)]
    # 3. minimum pairwise stream-cycle lag
    lags = sorted((circ((b[1] - a[1]) * INV8), a[0], b[0])
                  for a, b in itertools.combinations(gens, 2))
    same = [circ((nw[i] - nx[i]) * INV8) for i in range(8)]
    # 4. R1: D_i pairwise distinct
    D = [(nw[i] - nx[i]) % P for i in range(8)]
    r1 = [(i, j) for i, j in itertools.combinations(range(8), 2) if D[i] == D[j]]
    # 5. R2: direct |D_i - D_j| <= 14 (i<j), swapped |D_i + D_j| <= 14 (i<=j)
    r2d = [(i, j) for i, j in itertools.combinations(range(8), 2) if circ(D[i] - D[j]) <= 14]
    r2s = [(i, j) for i in range(8) for j in range(i, 8) if circ(D[i] + D[j]) <= 14]
    print(f"[{name}]")
    print("  X seeds: " + " ".join(f"0x{s:04X}" for s in xs))
    print("  W seeds: " + " ".join(f"0x{s:04X}" for s in ws))
    print(f"  min pairwise stream-cycle lag among 16 generators = {lags[0][0]} "
          f"({lags[0][1]}-{lags[0][2]}); next {lags[1][0]} ({lags[1][1]}-{lags[1][2]})")
    print("  X_i-W_i stream-cycle lags: " + ", ".join(str(v) for v in same))
    print(f"  R1 (no translated operand-pair streams): "
          f"{'SATISFIED' if not r1 else f'VIOLATED on {len(r1)} of 28 lane pairs'}")
    print(f"  R2 direct violations {len(r2d)}, swapped violations {len(r2s)} -> "
          f"{'SATISFIED' if not (r2d or r2s) else 'VIOLATED'}")
    return lags[0][0], len(r1), len(r2d) + len(r2s)


def main():
    rev = subprocess.run(["git", "-C", REPO, "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", REPO, "status", "--porcelain"],
                           capture_output=True, text=True).stdout.strip()
    print("# command: python3 scripts/budgets/lfsr_rules_revC.py")
    print(f"# input revision: {rev}{'-dirty' if dirty else ''}; python {sys.version.split()[0]}")
    print("# label: CALCULATION (exhaustive walk of the m-sequence)")
    phase, seq = build_phase()
    # ---- 1. period ----
    print(f"period from 0xACE1: {len(seq)} -> {'MAXIMAL' if len(seq) == P else 'NOT MAXIMAL'}")
    assert len(seq) == P and 0 not in phase
    S = lambda n: seq[n % P]  # noqa: E731  state after n single steps from 0xACE1

    # ---- 2. seed tables ----
    revc_x = [(0xACE1 + 0x3C5A * i) % 65536 for i in range(8)]
    revc_w = [(0x7A5C + 0x2B67 * i) % 65536 for i in range(8)]
    revb_x = [S(4096 * i) for i in range(8)]
    revb_w = [S(32768 + 4096 * i) for i in range(8)]
    # tables as printed in the spec (ARCHITECTURE.md 11 and 12)
    arch = open(os.path.join(REPO, "design/architecture/ARCHITECTURE.md")).read()
    sec12 = arch[arch.index("## 12."):]
    sec11 = arch[arch.index("## 11."):arch.index("## 12.")]
    m = re.search(r"X = ((?:0x[0-9A-F]{4} ?){8});\s*W = ((?:0x[0-9A-F]{4} ?){8})", sec12)
    spec_x = [int(v, 16) for v in m.group(1).split()]
    spec_w = [int(v, 16) for v in m.group(2).split()]
    bx = [int(v, 16) for v in re.search(r"seed_x_i = S\(4096 i\) = ([^.]*?)\s*;", sec11).group(1).replace(",", " ").split()]
    bw = [int(v, 16) for v in re.search(r"seed_w_i = S\(32768 \+ 4096 i\) = ([^.]*?)\.", sec11).group(1).replace(",", " ").split()]
    itf = json.load(open(os.path.join(REPO, "management/INTERFACES.json")))["tpu"]["lfsr"]
    jx = [int(v, 16) for v in itf["seed_x_i_mode2"].split(",")]
    jw = [int(v, 16) for v in itf["seed_w_i_mode2"].split(",")]
    print(f"rev C formula == ARCHITECTURE.md 12 table: X {revc_x == spec_x}, W {revc_w == spec_w}")
    print(f"rev C formula == INTERFACES.json rev {itf and json.load(open(os.path.join(REPO, 'management/INTERFACES.json')))['revision']} "
          f"table: X {revc_x == jx}, W {revc_w == jw}")
    print(f"rev B S(4096 i) == ARCHITECTURE.md 11 table: X {revb_x == bx}, W {revb_w == bw}")
    print(f"S(32768) = 0x{S(32768):04X} (spec: 0xF9DE); INTERFACES seed_w = {itf['seed_w']}")
    assert revc_x == spec_x == jx and revc_w == spec_w == jw
    assert revb_x == bx and revb_w == bw and S(32768) == 0xF9DE == int(itf["seed_w"], 16)
    assert all(v != 0 for v in revc_x + revc_w + revb_x + revb_w)

    # ---- 3..5. per seed set ----
    lag_c, r1_c, r2_c = check_set("rev C mode 2 (= rev A mode 2, candidate C0)", revc_x, revc_w, phase)
    lag_b, r1_b, r2_b = check_set("rev B mode 2 (candidate C1, superseded)", revb_x, revb_w, phase)
    assert lag_c == 321 and r1_c == 0 and r2_c == 0      # matches ARCHITECTURE.md 12 / SW-03
    assert r1_b == 28                                     # matches ADR-009 / SW-03 (28 of 28)
    # modes 0/1: one pair (0xACE1, 0xF9DE)
    dx = (phase[0xF9DE] - phase[0xACE1]) % P
    print("[modes 0/1, rev B/C pair 0xACE1 / 0xF9DE]")
    print(f"  X->W offset {dx} single steps = {circ(dx * INV8)} stream cycles; "
          f"self-swap |2D| mod 65535 = {circ(2 * dx)} -> R2 {'VIOLATED' if circ(2 * dx) <= 14 else 'SATISFIED'} "
          f"(accepted, ADR-010 D-B); R1 not applicable (one pair)")
    da = (phase[0x7A5C] - phase[0xACE1]) % P
    print(f"  (rev A pair 0xACE1 / 0x7A5C for reference: self-swap |2D| = {circ(2 * da)} -> "
          f"R2 {'VIOLATED' if circ(2 * da) <= 14 else 'SATISFIED'})")

    # ---- 6. stream cycles per inference vs period ----
    # The leap-8 state sequence S(8k) has period 65535 stream cycles, so no
    # state (and no r value sequence) repeats inside one inference. But the
    # underlying BIT sequence is consumed 8 bits per cycle and wraps after
    # 65536 single steps = 8192 stream cycles: the window at cycle k + 8192
    # starts one bit later than the window at cycle k, i.e. it shares 7 of 8
    # bits with it (a self-overlap of the same kind as the R2 coupling).
    print("stream cycles per inference (10 tiles x 2^K) vs state period 65535, bit-sequence wrap 8192, rev C min lag 321:")
    for k in range(4, 11):
        n = 10 * 2 ** k
        notes = []
        if n > 321:
            notes.append("> 321: lagged copies of other generators overlap in time (allowed by R1/R2)")
        if n > 8192:
            notes.append("> 8192: each generator re-uses its own bit sequence shifted by 1 bit (7-of-8 shared bits at lag 8192)")
        print(f"  K={k:2d}: {n:6d} cycles = {n / P:.3f} state periods; " + ("; ".join(notes) if notes else "no overlap"))
    print("ALL SELF-CHECKS PASSED")


if __name__ == "__main__":
    main()
