# sim/data/revA — superseded spec rev A files (traceability only)

Copied unchanged from `sim/data/` on 2026-11-04 (task SW-02) before the rev B
regeneration. Generated in SW-01a by `code/python/sctpu/gen_hex.py` with the rev A
seeds of ARCHITECTURE.md 5.3 (modes 0/1: X 0xACE1, W 0x7A5C; mode 2:
X_i = 0xACE1 + 0x3C5A i, W_i = 0x7A5C + 0x2B67 i, mod 2^16) and PARAMS version 0x01.
**Do not use for rev B hardware**; use `sim/data/` instead.

- Same formats as `sim/data/README.md` (the original rev A README is kept as
  `README_revA_original.md`). These files carry no `# spec_rev` tag; the readers in
  `gen_hex.py` treat an untagged file as rev A.
- `weights.hex`, `bias.hex`, `input.hex`, `model_params.json` and `corner/` are
  byte-identical to the rev B files in `sim/data/` (no RNG content); they are copied
  so that this directory is self-contained (e.g. `+DATA=sim/data/revA` for a rev A
  regression of the RTL).
- Reproduction: `cd code/python && ../../.venv/bin/python -m sctpu.gen_hex --spec-rev A --out <dir>`
  gives identical data lines for all 30 files (only the `#` provenance header differs).
