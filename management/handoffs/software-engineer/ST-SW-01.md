# ST-SW-01 — Python smoke test (pytest install, LFSR golden model, known-answer tests)
Status: PASS
Agent: software-engineer   Date: 2026-11-04T02:57Z   Input revision: none (branch `claude/awesome-lovelace-hu02o8` has no commits yet; `git rev-parse --short HEAD` -> "fatal: Needed a single revision"; all project files untracked)

## Requirements addressed
Smoke-test task from the manager (no REQUIREMENTS.md IDs exist yet):
1. pytest installed in the project venv only.
2. 16-bit Fibonacci LFSR, polynomial x^16 + x^14 + x^13 + x^11 + 1, in package `code/python/sctpu`.
3. Known-answer tests (LFSR period, digits dataset shape, popcount sum).
4. Test run logged and quoted.
5. MCP tool visibility check.

## Inputs
- Role/skills: `.claude/agents/software-engineer.md`, `CLAUDE.md`, `.claude/skills/{engineering-evidence,python-model-flow,engineering-reporting}/SKILL.md`
- `management/INTERFACES.json` — NOT PRESENT (see Errors).
- Venv `/home/user/tpu-e-cpu/.venv`: Python 3.13.18, numpy 2.5.4, scikit-learn 1.9.1.

## Outputs
- `/home/user/tpu-e-cpu/code/python/sctpu/__init__.py` — package marker + docstring.
- `/home/user/tpu-e-cpu/code/python/sctpu/lfsr.py` — `feedback()`, `step()`, `LFSR16`, `period()`; constants `TAPS=(15,13,12,10)`, `MASK=0xFFFF`, `MAX_PERIOD=65535`, `DEFAULT_SEED=0xACE1`. Shift: `next = ((state << 1) | (b15^b13^b12^b10)) & 0xFFFF`; equivalent RTL documented in the docstring. Zero seed rejected (lock-up state).
- `/home/user/tpu-e-cpu/code/python/tests/test_smoke.py` — 5 tests.
- `/home/user/tpu-e-cpu/logs/smoke/sw_pip.log`, `/home/user/tpu-e-cpu/logs/smoke/sw_pytest.log`.

## Checks actually performed
| Command | Tool+version | Log | Result line quoted |
|---|---|---|---|
| `.venv/bin/pip install pytest` | pip (venv), Python 3.13.18 | logs/smoke/sw_pip.log | "Successfully installed iniconfig-2.3.1 pluggy-1.7.0 pygments-2.21.0 pytest-9.2.0" |
| `.venv/bin/python -m pytest -q code/python/tests` | pytest 9.2.0 | logs/smoke/sw_pytest.log | "5 passed in 0.80s" (exit=0) |
| ToolSearch query "github", max_results 3 (not called) | Claude Code ToolSearch | n/a | returned `mcp__github__actions_get`, `mcp__github__actions_list`, `mcp__github__actions_run_trigger` |

Tests in the run: `test_lfsr_period_from_seed_ace1`, `test_lfsr_first_steps_match_formula`, `test_lfsr_rejects_zero_seed`, `test_digits_dataset_shape`, `test_popcount_bytes_sum`.

## Numerical findings
| Name | Value | Unit | Label | Evidence |
|---|---|---|---|---|
| LFSR period from seed 0xACE1 | 65535 | steps | SIMULATION (Python model, pytest 9.2.0) | logs/smoke/sw_pytest.log; equals 2^16-1 (CALCULATION) |
| Distinct states visited | 65535 | states | SIMULATION | same test; zero state never reached |
| First step from 0xACE1 | 0x59C3 | — | CALCULATION (fb=1^1^0^1=1; (0xACE1<<1\|1)&0xFFFF) confirmed by test | test_lfsr_first_steps_match_formula |
| load_digits shape | 1797 x 64, 10 classes, pixels 0..16 | — | SIMULATION (sklearn 1.9.1) vs SOURCE (sklearn docs) | test_digits_dataset_shape |
| sum popcount(0..255) | 1024 | bits | CALCULATION (8 positions x 128) confirmed by test | test_popcount_bytes_sum |

## Assumptions
- Tests import `sctpu` by adding `code/python/` to `sys.path` (no package install) — ASSUMPTION: acceptable for the smoke stage; a `conftest.py` or `pip install -e` can replace it later.
- The LFSR bit ordering defined here (shift toward MSB, feedback into bit 0) is the one the RTL must match; it is not yet frozen in INTERFACES.json.

## Errors / deviations
- `management/INTERFACES.json` does not exist yet, so no frozen interface could be checked.
- No git revision available (repository has no commits). Not committed, per instructions.
- MCP visibility: the `mcp__github__*` tools are visible (deferred, loadable). Separately, the session reported the plugin server `plugin:engineering:github` failed to connect (proxy 403); not exercised here.
- An untracked top-level `tests/` directory exists that this task did not create; not touched.

## Open decisions (for the manager)
- Freeze the LFSR polynomial, seed, and bit/shift ordering in INTERFACES.json so the fpga-engineer's RTL matches `sctpu/lfsr.py`.

## Next actions
- Once INTERFACES.json exists: add a `$readmemh` vector file of the first N LFSR states in `sim/data/` for RTL comparison with a mismatch count.
