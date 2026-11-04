#!/usr/bin/env python3
# =============================================================================
# File    : scripts/budgets/stats_budget.py
# Purpose : REQ-01 statistical budgets (CALCULATION):
#   1. 95 % Wilson confidence half-width of an accuracy measured on the
#      n = 360 image test split, for several accuracies.
#   2. SC noise bound per neuron: with independent Bernoulli product bits,
#      Var(acc) <= N_in*L/4, D = 2*acc - N_in*L  =>  std(D/L) <= sqrt(N_in/L)
#      (units of sum_i v(x_i) v(w_i), which spans [-N_in, +N_in]). Correlated
#      RNG modes can exceed this bound (cross-lane correlation adds covariance).
#   3. register widths of the post-processing (REQ-TPU-008).
# Usage   : python3 scripts/budgets/stats_budget.py > scripts/budgets/logs/stats_budget.log
# =============================================================================
import math


def wilson(k, n, z=1.96):
    """Wilson score interval (lo, hi) for k successes out of n."""
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return c - h, c + h


def main():
    print("# command: python3 scripts/budgets/stats_budget.py")
    n = 360
    print(f"1. Wilson 95 % CI, n = {n} (1 image = {100/n:.2f} pp)")
    for acc in (0.90, 0.93, 0.95):
        k = round(acc * n)
        lo, hi = wilson(k, n)
        print(f"   acc = {k}/{n} = {k/n*100:.1f} %: CI [{lo*100:.1f}, {hi*100:.1f}] %, "
              f"half-width ~ {(hi-lo)/2*100:.1f} pp")
    print("2. SC noise bound std(Dp/L) <= sqrt(N_in/L) (independent streams)")
    print("    K     L   layer1 (N_in=64)   layer2 (N_in=16)")
    for k in range(4, 11):
        L = 2 ** k
        print(f"   {k:2d} {L:5d}   {math.sqrt(64/L):8.3f}           {math.sqrt(16/L):8.3f}")
    print("3. post-processing ranges (any legal input, K = 4..10, s = 0..7, int16 bias)")
    Dmax = 64 * 1024                       # |2*acc - N_in*L| <= N_in*L
    Bmax = 32768 * 1024 // 128             # |floor(bias*2^K/128)| <= 2^15*2^10/2^7
    DPmax = Dmax + Bmax
    print(f"   acc max = 64*1024 = {64*1024} -> {(64*1024).bit_length()} bits unsigned")
    print(f"   |D| <= {Dmax}, |B| <= {Bmax}, |Dp| <= {DPmax} -> "
          f"{DPmax.bit_length()+1} bits signed")
    sh_min, sh_max = 0 + 7 - 10, 7 + 7 - 4
    print(f"   hidden shift exponent s+7-K in [{sh_min}, {sh_max}]; exact |Dp*2^(s+7)| <= "
          f"{DPmax * 2**14} (~2^{math.log2(DPmax*2**14):.1f}) -> needs saturation, not a 32-bit product")


if __name__ == "__main__":
    main()
