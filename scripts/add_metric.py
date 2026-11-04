#!/usr/bin/env python3
"""Append/replace a metric in management/metrics.json (manager tool).
Usage: add_metric.py NAME VALUE UNIT LABEL EVIDENCE [REVISION]
Every metric carries a label (SOURCE/CALCULATION/SIMULATION/MEASUREMENT/ASSUMPTION)
and an evidence path, per the engineering-evidence skill."""
import json, subprocess, sys
p = "management/metrics.json"
name, value, unit, label, evidence = sys.argv[1:6]
rev = sys.argv[6] if len(sys.argv) > 6 else subprocess.run(
    ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
assert label in {"SOURCE", "CALCULATION", "SIMULATION", "MEASUREMENT", "ASSUMPTION"}, label
d = json.load(open(p))
d["metrics"] = [m for m in d["metrics"] if m["name"] != name]
try: value = float(value) if "." in value else int(value)
except ValueError: pass
d["metrics"].append({"name": name, "value": value, "unit": unit, "label": label,
                     "revision": rev, "evidence": evidence})
json.dump(d, open(p, "w"), indent=1)
