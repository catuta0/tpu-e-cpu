"""sctpu - host-side Python package of the SC-TPU + RV32I SoC project.

This package holds the bit-exact golden models and helper utilities that the
software engineer uses to generate reference data for the hardware (the
stochastic-computing TPU on the Tang Nano 9K) and to check simulation results.

Modules
-------
lfsr
    16-bit Fibonacci LFSR (polynomial x^16 + x^14 + x^13 + x^11 + 1), the
    pseudo-random source used to generate stochastic bit streams, plus the
    8-step leap-forward network (ARCHITECTURE.md 5.3, ADR-005).
model
    Bit-exact golden model of one SC-TPU inference (ARCHITECTURE.md 5):
    slow literal reference, fast exact batch model, expected-value, int8 and
    float models, weight-RAM layout and register packing.
train
    Quantisation-aware training of the 64-16-10 MLP on sklearn digits
    (writes sim/data/model_params.json).
accuracy
    Accuracy study (float / EV / int8 / SC for K=4..10 x RNG_MODE 0..2) and
    the analytical stochastic-error model (reports/sw/).
gen_hex
    Init files ($readmemh) and RTL test vectors in sim/data/.

All code is integer-only in the hardware-equivalent path so that results can
be compared bit for bit with RTL simulation.
"""

__all__ = ["lfsr", "model", "train", "accuracy", "gen_hex"]
