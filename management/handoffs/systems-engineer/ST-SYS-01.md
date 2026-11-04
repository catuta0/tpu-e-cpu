# ST-SYS-01 — Smoke test: device/board sources + UART divider known-answer
Status: PARTIAL
Agent: systems-engineer   Date: 2026-11-04T03:00Z   Input revision: none (repository has no commits; tree untracked)

PARTIAL because no primary datasheet page could be opened (network policy), so
no value could be labelled SOURCE. The UART known-answer smoke check passed and
the MCP tool check was done.

## Requirements addressed
- None formally (requirements/REQUIREMENTS.md does not exist yet). Supports the
  project-definition hard constraints "fit in GW1NR-9 resources" and "meet timing
  at 27 MHz" by registering the input values.

## Inputs
- management/PROJECT_DEFINITION.md (untracked, no revision)
- CLAUDE.md, .claude/skills/engineering-evidence/SKILL.md,
  .claude/skills/engineering-reporting/SKILL.md
- Not present yet: management/INTERFACES.json, design/architecture/ARCHITECTURE.md
- Web: WebSearch result snippets (2026-11-04); document list D-01..D-18 in SOURCES.md

## Outputs
- /home/user/tpu-e-cpu/management/SOURCES.md (new; 26 value rows S-001..S-026, document list, contradictions, re-verification list)
- /home/user/tpu-e-cpu/scripts/budgets/uart_divider.py (new; CALCULATION with built-in known-answer assert)
- /home/user/tpu-e-cpu/logs/smoke/sys_uart.log
- this handoff

## Checks actually performed
1. `curl -sSL <DS117 mirror / gowinsemi.com / szlcsc / dl.sipeed.com schematic>`
   -> `curl: (56) CONNECT tunnel failed, response 403` (all four). Proxy README: policy denial, do not retry.
2. WebFetch `wiki.sipeed.com`, `www.server4.eca.ir` -> `getaddrinfo ENOTFOUND` (host not in allowed
   network domains). Per session rule, no further hosts tried.
3. WebSearch x9 (standard/extended) -> snippets used as secondary sources.
4. `python3 scripts/budgets/uart_divider.py` (Python 3.13.18) -> log logs/smoke/sys_uart.log:
   ```
   oversample x1  (primary): D_ideal = 234.375000, D = 234, B_real = 115384.6 Bd, error = +0.160 %
   oversample x16 (info only): D_ideal = 14.648438, D = 15, B_real = 112500.0 Bd, error = -2.344 %
   KNOWN-ANSWER CHECK: PASS (234.375 -> 234, +0.16 %)
   # exit code: 0
   ```
5. ToolSearch query "github", max_results 3 -> MCP tools visible (not called):
   `mcp__github__actions_get`, `mcp__github__actions_list`, `mcp__github__actions_run_trigger`.
   (Session also reports the plugin `engineering:github` MCP server failed to connect: proxy 403.)

## Numerical findings
| Name | Value | Unit | Label | Evidence |
|---|---|---|---|---|
| LUT4 | 8640 | LUT4 | ASSUMPTION (secondary) | SOURCES S-001 |
| Flip-flops | 6480 | FF | ASSUMPTION | S-002 |
| SSRAM | 17280 (conflict: "16K") | bit | ASSUMPTION | S-003 |
| BSRAM total / blocks | 468 Kbit / 26 | Kbit / block | ASSUMPTION | S-004, S-005 |
| BSRAM per block | 18432 (x9/x18/x36) or 16384 (x1..x32) | bit | ASSUMPTION | S-006 |
| BSRAM configs | 16Kx1, 8Kx2, 4Kx4, 2Kx8, 1Kx16, 512x32; 2Kx9, 1Kx18, 512x36 | — | ASSUMPTION | S-007 |
| 18x18 multipliers | 20 | — | ASSUMPTION | S-010 |
| PLLs | 2 (conflict: "one PLL" in older text) | — | ASSUMPTION | S-011 |
| OSC | 2.5..125 MHz, ±5 % (family figure) | MHz / % | ASSUMPTION | S-012, S-013 |
| PSRAM (QN88P) | 64 Mbit, x16, 1.8 V interface | bit | ASSUMPTION | S-014, S-015 |
| User flash | 608 | Kbit | ASSUMPTION | S-016 |
| User I/O QN88P | 71 (conflict: 70) | I/O | ASSUMPTION | S-017 |
| VCC core | 1.2 typ (1.14..1.26) | V | ASSUMPTION | S-018, S-019 |
| Board oscillator | 27 MHz, pin 52 | MHz | ASSUMPTION | S-020 |
| LEDs | 6, active-low, pins 10,11,13,14,15,16 | — | ASSUMPTION | S-021 |
| Buttons | 2, active-low, pins 3/4 (S1/S2 mapping conflict) | — | ASSUMPTION | S-022 |
| USB bridge / UART | BL702 USB-JTAG + USB-UART; FPGA TX 17, RX 18 | — | ASSUMPTION | S-023, S-024 |
| BSRAM bits check | 26 x 18432 = 479232 bit = 468 Kibit (consistent) | bit | CALCULATION | SOURCES.md |
| UART divider 115200 @ 27 MHz | 234.375 -> 234, real 115384.6 Bd, error +0.160 % | — | CALCULATION | logs/smoke/sys_uart.log |
| UART 16x oversampling divider | 14.648 -> 15, error -2.344 % | — | CALCULATION | logs/smoke/sys_uart.log |

## Assumptions
- All device/board values: ASSUMPTION (secondary = search snippets), see SOURCES.md.
- UART baud 115200: project choice (ASSUMPTION).
- Divider rounding: nearest integer.

## Errors / deviations
- Primary documents not opened: egress proxy 403 for dl.sipeed.com, www.gowinsemi.com,
  atta.szlcsc.com, www.server4.eca.ir; DNS denial for wiki.sipeed.com. No page/table numbers recorded.
- `management/INTERFACES.json` and the architecture spec listed in my first actions do not exist yet.
- No git commit exists, so no revision hash can be recorded.

## Open decisions (for the manager)
1. Ask the user to allow `cdn.gowinsemi.com.cn`, `www.mouser.com`, `dl.sipeed.com`, `wiki.sipeed.com`,
   `www.gowinsemi.com` (environment Network access settings) so values can be upgraded to SOURCE.
2. Until then, budgets will use the ASSUMPTION values with the most conservative side of each
   conflict (SSRAM 16 Kbit, 70 user I/O, 1 PLL guaranteed for timing planning).
3. Design note: a 16x-oversampling RX at 27 MHz gives -2.34 % baud error; prefer a 1x divider
   with mid-bit sampling (or a fractional/PLL-derived clock) for the UART RX.

## Next actions
- Re-verify S-001..S-026 against DS117E (latest), UG285E and the Tang Nano 9K schematic once hosts are allowed.
- Start requirements/REQUIREMENTS.md and requirements/BUDGETS.md using these registered values.
