---
name: python-model-flow
description: Workflow for the Python side of the project - venv usage, deterministic training, bit-exact golden models, hex-file formats for $readmemh, and test/report conventions.
---

# Python model flow

- Interpreter: `/home/user/tpu-e-cpu/.venv/bin/python` (Python 3.13, numpy 2.x,
  scikit-learn 1.9, matplotlib). Do not pip install outside the venv.
- Fix seeds (`numpy.random.default_rng(seed)`), print them in every log.
- Golden models are written for bit-exactness first, speed second: integer
  arithmetic only (numpy int64), no floats in the hardware-equivalent path.
- Hex files for `$readmemh`: one word per line, lowercase hex, no `0x`, width
  fixed by the spec; a header comment line `// <description>` is allowed.
- Tests: `code/python/tests/test_*.py`, runnable with
  `.venv/bin/python -m pytest -q code/python/tests` (install pytest in the venv if missing).
- Results: write machine-readable JSON in `reports/sw/` and quote it in the handoff.

## Lessons learned
- (none yet)
