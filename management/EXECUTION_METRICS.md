# Execution metrics (manager log)

Model identifiers are not recorded in repository files (platform policy); the
session configuration is available from the session itself. Specialist effort:
`high` (agent frontmatter). Hardware: 4 vCPU, 15 GiB RAM, no GPU (TOOLCHAIN.md).
Durations and token counts are those reported by the agent harness on completion.

| Task | Agent | Mode | Duration (s) | Subagent tokens | Tool uses | Status | Retries / notes |
|---|---|---|---|---|---|---|---|
| ST-FPGA-01 | fpga-engineer | fallback | 665 | 192 396 | 73 | PASS | — |
| ST-SW-01 | software-engineer | fallback | 85 | 75 302 | 11 | PASS | — |
| ST-SYS-01 | systems-engineer | fallback | 234 | 104 773 | 27 | PARTIAL | vendor hosts blocked by proxy |
| ST-DOC-01 | documentation-engineer | fallback | 91 | 76 322 | 11 | PASS | — |
| ST-REV-01 | independent-reviewer | fallback | 205 | 122 271 | 17 | PASS | — |
| SW-01b | software-engineer | fallback | 1308 | 217 364 | 42 | PASS | — |
| SW-01a | software-engineer | fallback | 1439 | 236 917 | 51 | PASS | 1 test-count fix |
| RTL-CPU | fpga-engineer | fallback | 1577 | 272 009 | 84 | PASS | — |
| REQ-01 | systems-engineer | fallback | 2062 | 265 606 | 63 | PARTIAL | datasheets blocked |
| DOC-01 | documentation-engineer | fallback | 785 | 247 561 | 68 | PARTIAL | TBD placeholders by design |
| RTL-TPU | fpga-engineer | fallback | 11 171 | 394 808 | 133 | PASS | long IL=16 P&R attempts |
| SW-02 | software-engineer | fallback | 1471 | 280 558 | 61 | PASS | found rev B defect |
| SW-03 | software-engineer | fallback | 2230 | 335 078 | 84 | PASS | — |
| RTL-SOC | fpga-engineer | fallback | 8570 | 413 118 | 160 | PASS | rev B then rev C runs |
| REQ-02 | systems-engineer | fallback | 1042 | 312 438 | 83 | PASS | — |
| REV-01 (1st try) | independent-reviewer | fallback | — | — | — | NOT RUN | killed by usage limit (HTTP 429) |
| REV-01a/b | independent-reviewer | native | (running) | | | | restarted 13:08 UTC |
| DOC-02 | documentation-engineer | native | (running) | | | | |

Manager re-runs (independent of specialists): sim_cpu.sh 176/176 PASS; sim_soc.sh
SIM_SOC ALL PASSED (18 s); log greps for TPU bit-exact and P&R Fmax.
