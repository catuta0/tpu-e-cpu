#!/usr/bin/env python3
# =============================================================================
# File    : scripts/budgets/latency_budget.py
# Purpose : REQ-01 latency / throughput budget (CALCULATION) for the SC-TPU of
#           design/architecture/ARCHITECTURE.md rev A (sec. 5.3).
#           Prints a table for K = LOG2_L = 4..10.
# Usage   : python3 scripts/budgets/latency_budget.py > scripts/budgets/logs/latency_budget.log
#
# Model (every input is labelled; change the constants to explore):
#   N(K) = T_START + T_TILES*(2^K + O_TILE) + N_LAYERS*(P_POST + C_LAYER) + A_ARGMAX + T_DONE
#   * T_TILES  = 8 (layer 1: 64/IL) + 2 (layer 2: 16/IL) = 10   CALCULATION (spec 5.3)
#   * 2^K      stream cycles per tile                           SOURCE: spec 5.3
#   * O_TILE   per-tile load overhead = 32 weight-word reads
#              (128 B tile / 4 B per word, 1 word/clock from a 32-bit BSRAM
#              port) + 1 BSRAM read latency + 3 cycles input load / FSM
#              hand-over = 36                                   ASSUMPTION
#   * P_POST   = 16 cycles per layer (one neuron per cycle)     ASSUMPTION
#   * C_LAYER  = 2 cycles per layer (acc clear + post-proc pipeline drain) ASSUMPTION
#   * A_ARGMAX = 10 cycles (one score per cycle)                ASSUMPTION
#   * T_START  = 2 (START accept + seed load), T_DONE = 1       ASSUMPTION
#   * f_clk    = 27 MHz                                         ASSUMPTION/SOURCE S-020 (board osc)
# Derived figures:
#   * time per inference      t = N / f_clk
#   * inferences per second   R = f_clk / N
#   * stream efficiency       eta = T_TILES*2^K / N
#   * SC bit-ops/s            = NL*IL * T_TILES*2^K * R  (one XNOR + one APC
#                               add per lane per stream cycle; padding lanes
#                               of layer 2 included)
#   * useful MAC/s            = (64*16 + 16*10) * R = 1184 * R (network MACs)
#   * peak SC bit-ops/s       = NL*IL*f_clk (if streaming 100 % of the time)
# Variant (design option, not in spec): double-buffered weight registers,
# loading tile t+1 while tile t streams -> per-tile overhead hidden when
# 2^K >= O_TILE except for the first tile of each layer.
# =============================================================================
import subprocess

F_CLK = 27.0e6
NL, IL = 16, 8
T_TILES = 64 // IL + 16 // IL
O_TILE = 32 + 1 + 3
P_POST, C_LAYER, N_LAYERS = 16, 2, 2
A_ARGMAX, T_START, T_DONE = 10, 2, 1
MACS = 64 * 16 + 16 * 10


def cycles(k, o_tile=O_TILE, dbuf=False):
    """Cycles START->DONE for LOG2_L = k (CALCULATION)."""
    L = 2 ** k
    if dbuf:
        # first tile of each layer pays the load, later tiles hide it
        # behind the previous tile's stream if L >= o_tile
        hidden = max(0, o_tile - L)
        tiles = 2 * (L + o_tile) + (T_TILES - 2) * (L + hidden)
    else:
        tiles = T_TILES * (L + o_tile)
    return T_START + tiles + N_LAYERS * (P_POST + C_LAYER) + A_ARGMAX + T_DONE


def main():
    try:
        rev = subprocess.run(["git", "-C", "/home/user/tpu-e-cpu", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True).stdout.strip()
    except Exception:
        rev = "unknown"
    print("# command: python3 scripts/budgets/latency_budget.py")
    print(f"# revision: {rev} (inputs: ARCHITECTURE.md rev A)")
    print(f"# constants: f_clk={F_CLK/1e6:.0f} MHz, T_TILES={T_TILES}, O_TILE={O_TILE}, "
          f"P_POST={P_POST}, C_LAYER={C_LAYER}, A_ARGMAX={A_ARGMAX}, T_START={T_START}, T_DONE={T_DONE}")
    print(f"# closed form: N(K) = {T_TILES}*2^K + {cycles(0) - T_TILES}  (CALCULATION)")
    print()
    hdr = (" K     L   N_cycles   t_us     inf/s   eta_%   SCbitop/s    MAC/s    | dbuf N   dbuf t_us")
    print(hdr)
    for k in range(4, 11):
        n = cycles(k)
        r = F_CLK / n
        eta = T_TILES * 2 ** k / n
        bops = NL * IL * T_TILES * 2 ** k * r
        nd = cycles(k, dbuf=True)
        print(f"{k:2d} {2**k:5d} {n:9d} {n/F_CLK*1e6:8.2f} {r:9.0f} {eta*100:7.1f} "
              f"{bops:11.3e} {MACS*r:10.3e} | {nd:7d} {nd/F_CLK*1e6:9.2f}")
    print()
    print(f"peak SC bit-ops/s (100 % streaming) = NL*IL*f_clk = {NL*IL*F_CLK:.3e}")
    print("sensitivity of N(8) to O_TILE: " +
          ", ".join(f"O={o}: {cycles(8, o)}" for o in (34, 36, 40, 48)))
    # Known-answer self-check of the closed form (K = 8, defaults):
    # 10*256 + 10*36 + 2 + 2*18 + 10 + 1 = 2560 + 360 + 49 = 2969
    assert cycles(8) == 2969, cycles(8)
    print("KNOWN-ANSWER CHECK: PASS (N(8) = 2969 cycles)")


if __name__ == "__main__":
    main()
