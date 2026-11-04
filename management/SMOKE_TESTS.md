# Smoke tests (G2) — 2026-11-04

| ID | Agent | Tool / version | Known answer | Result | Evidence |
|---|---|---|---|---|---|
| ST-FPGA-01 | fpga-engineer | Verilator 5.020, Icarus 12.0, Yosys 0.70 (YoWASP), nextpnr-himbaechel 0.11.1, Apicula 0.32 | 24-bit counter = 998 after 1000 edges (2-FF sync latency), 4-bit wrap 15->0; P&R at 27 MHz; .fs produced | **PASS** (21 checks, TEST PASSED; fault-injection run TEST FAILED as expected; Fmax 245.52 MHz PASS at 27 MHz; 34 LUT4/26 DFF/8 IOB; .fs 2,069,320 B) | logs/smoke/fpga_*.log, handoffs/fpga-engineer/ST-FPGA-01.md |
| ST-SW-01 | software-engineer | Python 3.13.18, numpy 2.5.4, sklearn 1.9.1, pytest 9.2.0 | LFSR period 65535; digits 1797x64, 10 classes; popcount sum 1024 | **PASS** (5 passed) | logs/smoke/sw_pytest.log |
| ST-SYS-01 | systems-engineer | web search, Python | UART divider 234.375 -> 234, +0.16 % | **PARTIAL**: calculation PASS; primary datasheets unreachable (proxy 403 / host not allowed) -> device values ASSUMPTION, being re-sourced from the Apicula/nextpnr chip database | logs/smoke/sys_uart.log, management/SOURCES.md |
| ST-DOC-01 | documentation-engineer | TeX Live 2023, IEEEtran, latexmk, matplotlib 3.11.2 | 1 page, 0 undefined refs, 2 bib entries | **PASS** | logs/smoke/doc_latex.log |
| ST-MGR-01 | manager | pdfTeX 1.40.25 | 1 page | **PASS** | logs/smoke/manager_latex.log |
| ST-REV-01 | independent-reviewer | Icarus 12.0, Verilator 5.020 | hand-derived 998; TB must fail on mutants | **PASS** (re-run TEST PASSED; 9/11 mutants killed; 2 MINOR TB-coverage findings R-001/R-002 accepted for the smoke design only) | reports/review/ST-REV-01.md |

MCP visibility: every specialist reported the session GitHub MCP tools visible via ToolSearch
(mcp__github__actions_get/list/run_trigger); the plugin GitHub MCP server failed (proxy 403).
The EDA routes are shell-tool integrations, not MCP.
