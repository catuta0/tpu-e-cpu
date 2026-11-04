#!/usr/bin/env python3
"""
uart_divider.py -- UART baud-rate divider budget (CALCULATION).

Purpose
-------
Computes the integer clock divider a UART needs to generate a target baud rate
from the system clock, together with the resulting real baud rate and the
relative baud-rate error. Used as the ST-SYS-01 smoke known-answer calculation
and as an input to requirements/BUDGETS.md.

Inputs (labelled)
-----------------
- f_clk  = 27 000 000 Hz : Tang Nano 9K on-board oscillator. ASSUMPTION
           (secondary source, see management/SOURCES.md S-020; primary page
           could not be fetched in ST-SYS-01).
- baud   = 115 200 Bd    : project choice for the debug UART. ASSUMPTION.

Formulas (CALCULATION)
----------------------
- ideal divider   D_ideal = f_clk / (baud * oversample)
- integer divider D       = round(D_ideal)        (nearest integer)
- real baud       B_real  = f_clk / (D * oversample)
- error           e       = (B_real - baud) / baud * 100 %

"oversample = 1" means the divider produces one tick per bit (TX side and a
simple mid-bit-sampling RX). "oversample = 16" is the classic 16x RX scheme,
reported for information only.

Known answer (smoke test, oversample = 1)
-----------------------------------------
27e6 / 115200 = 234.375 -> D = 234 -> B_real = 115384.6 Bd -> e = +0.16 %.
The script asserts these values and exits with status 1 on mismatch.

Usage
-----
    python3 scripts/budgets/uart_divider.py [f_clk_hz] [baud]
"""

import sys


def uart_divider(f_clk_hz: float, baud: float, oversample: int = 1):
    """Return (ideal divider, integer divider, real baud, error in percent)."""
    d_ideal = f_clk_hz / (baud * oversample)          # exact ratio
    d_int = int(round(d_ideal))                        # nearest integer divider
    b_real = f_clk_hz / (d_int * oversample)           # baud actually produced
    err_pct = (b_real - baud) / baud * 100.0           # signed relative error
    return d_ideal, d_int, b_real, err_pct


def main() -> int:
    # Optional command-line overrides; defaults are the project values.
    f_clk = float(sys.argv[1]) if len(sys.argv) > 1 else 27_000_000.0
    baud = float(sys.argv[2]) if len(sys.argv) > 2 else 115_200.0

    print("UART divider CALCULATION")
    print(f"  f_clk = {f_clk:.0f} Hz (ASSUMPTION, SOURCES.md S-020)")
    print(f"  baud  = {baud:.0f} Bd (ASSUMPTION, project choice)")

    for ovs in (1, 16):
        d_ideal, d_int, b_real, err = uart_divider(f_clk, baud, ovs)
        tag = "primary" if ovs == 1 else "info only"
        print(f"  oversample x{ovs:<2} ({tag}): D_ideal = {d_ideal:.6f}, "
              f"D = {d_int}, B_real = {b_real:.1f} Bd, error = {err:+.3f} %")

    # Known-answer check only applies to the default inputs.
    if f_clk == 27_000_000.0 and baud == 115_200.0:
        d_ideal, d_int, b_real, err = uart_divider(f_clk, baud, 1)
        ok = (abs(d_ideal - 234.375) < 1e-9 and d_int == 234
              and abs(round(err, 2) - 0.16) < 1e-9)
        print("KNOWN-ANSWER CHECK: "
              + ("PASS (234.375 -> 234, +0.16 %)" if ok else "FAIL"))
        return 0 if ok else 1
    print("KNOWN-ANSWER CHECK: NOT RUN (non-default inputs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
