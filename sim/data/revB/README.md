# sim/data/revB — superseded spec rev B files (traceability only)

Copied unchanged from `sim/data/` on 2026-11-04 (task SW-03) before the rev C
regeneration (sha256 of `tpu_vectors_mode2.txt` d867d38c…, `soc_expected.json`
fabe61ca…, as in the SW-02 handoff). Generated in SW-02 by
`code/python/sctpu/gen_hex.py --spec-rev B` with the rev B phase-spaced seeds of
ARCHITECTURE.md 11 (modes 0/1: X S(0)=0xACE1, W S(32768)=0xF9DE; mode 2:
X_i = S(4096 i), W_i = S(32768 + 4096 i)), RNG_MODE 2 default, PARAMS version 0x02.
**Do not use for rev C hardware**; use `sim/data/` instead.

- Rev B was found defective (SW-02, ADR-009): every mode-2 lane's (r_x, r_w) pair
  stream is the neighbour's delayed by 512 stream cycles (mode 2, K = 9: 89.7 %
  vs rev A 94.4 % on the test split, SIMULATION).
- Same formats as `sim/data/README.md`; the README in force at the time is kept as
  `README_revB_original.md`. Every vector/trace file starts with `# spec_rev B`.
- `weights.hex`, `bias.hex`, `input.hex`, `model_params.json` and `corner/` are
  byte-identical to the rev C files in `sim/data/` (no RNG content); copied so that
  this directory is self-contained (`+DATA=sim/data/revB` for a rev B RTL regression).
- Reproduction: `cd code/python && ../../.venv/bin/python -m sctpu.gen_hex --spec-rev B --out <dir>`
  gives identical data lines (only the `# generated ... rev` provenance line differs);
  checked in SW-03, log `logs/sw/gen_hex_revB_regen_check.log`.
