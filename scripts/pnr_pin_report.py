#!/usr/bin/env python3
# =============================================================================
# scripts/pnr_pin_report.py  -  Which package pin did nextpnr put each port on?
#
# Reads a nextpnr-himbaechel-gowin routed netlist (--write *.json), finds every
# IBUF/OBUF/IOBUF/TBUF cell, maps the placed bel (e.g. "X0Y14/IOBA") to the
# Gowin IO name (e.g. "IOL15A") and the package pin number using the Apicula
# chip database installed in the project venv. This independently checks that
# the CST constraints were really applied (nextpnr only prints an *Info* line
# for constraints whose port does not exist, so a typo in a port name is easy
# to miss).
#
# Usage : python scripts/pnr_pin_report.py <pnr.json> [family] [package]
#         defaults: family GW1N-9C, device key GW1NR-9C, package QFN88P
#         (= Tang Nano 9K, GW1NR-LV9QN88PC6/I5).
# Output: one line per port bit: "<port[bit]>  <bel>  <io name>  pin <n>  <attrs>"
# Exit  : 0 always unless the inputs cannot be read (it is a report, the caller
#         greps for the expected pins).
#
# Bel -> IO name rule (Apicula/nextpnr grid, 0-based X/Y; IO names 1-based):
#   left   IOL<n><A|B> = X0,       Y=n-1        right IOR<n> = X=cols-1, Y=n-1
#   top    IOT<n><A|B> = X=n-1,    Y0           bottom IOB<n> = X=n-1, Y=rows-1
# This rule was cross-checked on ST-FPGA-01 for all 8 placed IOs.
# =============================================================================
import json
import os
import re
import sys

import apycula
from apycula import chipdb


def main() -> int:
    pnr = sys.argv[1]
    family = sys.argv[2] if len(sys.argv) > 2 else "GW1N-9C"
    package = sys.argv[3] if len(sys.argv) > 3 else "QFN88P"
    devkey = "GW1NR-9C" if family == "GW1N-9C" else family

    db = chipdb.load_chipdb(os.path.join(os.path.dirname(apycula.__file__),
                                         f"{family}.msgpack.xz"))
    rows, cols = db.rows, db.cols
    pinmap = db.pinout[devkey][package]          # pin -> (io name, functions)
    io2pin = {v[0]: (k, v[1]) for k, v in pinmap.items()}

    def bel_to_io(bel: str) -> str:
        m = re.match(r"X(\d+)Y(\d+)/IOB([AB])", bel)
        if not m:
            return "?"
        x, y, ab = int(m.group(1)), int(m.group(2)), m.group(3)
        if x == 0:
            return f"IOL{y + 1}{ab}"
        if x == cols - 1:
            return f"IOR{y + 1}{ab}"
        if y == 0:
            return f"IOT{x + 1}{ab}"
        if y == rows - 1:
            return f"IOB{x + 1}{ab}"
        return "?"

    net = json.load(open(pnr))
    top = next(iter(net["modules"].values()))
    bit2port = {}
    for pname, p in top["ports"].items():
        for i, b in enumerate(p["bits"]):
            bit2port[b] = f"{pname}[{i}]"

    lines = []
    for cname, c in top["cells"].items():
        if c["type"] not in ("IBUF", "OBUF", "IOBUF", "TBUF"):
            continue
        pad_pin = "I" if c["type"] == "IBUF" else ("IO" if c["type"] == "IOBUF" else "O")
        pad = c["connections"][pad_pin][0]
        bel = c["attributes"].get("NEXTPNR_BEL", "?")
        io = bel_to_io(bel)
        pin, funcs = io2pin.get(io, ("?", []))
        attrs = " ".join(k[1:] for k in c["attributes"] if k.startswith("&"))
        extra = f" (dual-purpose: {','.join(funcs)})" if funcs else ""
        lines.append(f"{bit2port.get(pad, cname):14s} {bel:14s} {io:8s} pin {pin:>3s}  {attrs}{extra}")
    for line in sorted(lines):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
