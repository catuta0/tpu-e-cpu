"""sctpu - host-side Python package of the SC-TPU + RV32I SoC project.

This package holds the bit-exact golden models and helper utilities that the
software engineer uses to generate reference data for the hardware (the
stochastic-computing TPU on the Tang Nano 9K) and to check simulation results.

Modules
-------
lfsr
    16-bit Fibonacci LFSR (polynomial x^16 + x^14 + x^13 + x^11 + 1), the
    pseudo-random source used to generate stochastic bit streams.

All code is integer-only in the hardware-equivalent path so that results can
be compared bit for bit with RTL simulation.
"""

__all__ = ["lfsr"]
