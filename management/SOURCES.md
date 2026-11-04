# Sources register

Owner: systems-engineer. Created in task ST-SYS-01 (2026-11-04); updated in
REQ-01 (2026-11-04): chip-database totals S-027..S-035, fetched Sipeed wiki
source (D-09), PicoRV32 reference (D-21), RISC-V ISA reference (D-19);
labels of S-001..S-005, S-010, S-011, S-016, S-020, S-023, S-025 upgraded.

## How to read this register
- Every external value used by the project gets one row with an ID `S-xxx`.
- **Label** is `SOURCE` only when the primary document was opened and the value
  read from it (with page/table). Otherwise it is `ASSUMPTION` and the
  secondary source actually used is named.
- **Confidence**: High = several independent secondary sources agree, including
  a vendor-originated snippet; Medium = one or two consistent secondary sources;
  Low = sources disagree or only partial data was seen.

## Access status update in REQ-01 (2026-11-04)
- `raw.githubusercontent.com` IS reachable (github.com HTML is not; `git
  ls-remote https://github.com/...` works). Fetched:
  - D-09 Sipeed wiki source `Nano-9K.md`
    (https://raw.githubusercontent.com/sipeed/sipeed_wiki/main/docs/hardware/en/tang/Tang-Nano-9K/Nano-9K.md,
    repo HEAD 27155123dcd14df571e681055506bf47cfdfbadb, file sha256
    89d65d5ad6e9eac7a9cc6380fa26266823c33b4725cc75193fa83966b6ac40d0),
    table "Indepth specifications of the tang nano 9k" (file lines 30-47).
  - D-21 PicoRV32 README and picorv32.v (repo HEAD ef203c2b0a3fb793280f5114941416c425c5b461).
- The device resource totals of the open-source chip database were read from
  the nextpnr-himbaechel-gowin "Device utilisation" report (D-20). They are an
  independent (reverse-engineered) cross-check of the Gowin figures.
- Gowin documents (DS117, UG285) are still NOT opened (hosts blocked). Values
  that only DS117/UG285 contain stay ASSUMPTION.
- Label rule used: a value is SOURCE when it was read from a fetched document
  (board-vendor wiki source) or from the chip database of the tool flow, and the
  source is named. Values from the Sipeed wiki for chip resources are the board
  vendor quoting Gowin (secondary w.r.t. DS117) — they agree with the chip
  database in every case, which is why they are accepted as SOURCE.

## Access status in ST-SYS-01 (important)
No primary document could be opened in this session:
- `curl` to `dl.sipeed.com`, `www.gowinsemi.com`, `atta.szlcsc.com` and
  `www.server4.eca.ir` returned `CONNECT tunnel failed, response 403`
  (session egress proxy policy denial).
- WebFetch of `wiki.sipeed.com` and `www.server4.eca.ir` failed with
  `getaddrinfo ENOTFOUND` (host outside the session's allowed network domains).
  Per the session rules no further hosts were tried.
- Only **web-search result snippets** (WebSearch tool, 2026-11-04) were
  available. They quote the documents below but give no page numbers.

Therefore **every value below is labelled ASSUMPTION** (secondary source =
search snippet of the named document). All rows must be re-verified against the
PDF/page and upgraded to SOURCE once the hosts are allowed (see "Re-verification
needed" at the end).

## Documents referenced (D-xx)
| Doc | Title / revision | URL | Fetched? |
|---|---|---|---|
| D-01 | Gowin DS117 GW1NR series Data Sheet, 3.2.5E, 07/31/2026 (latest seen) | https://cdn.gowinsemi.com.cn/DS117E.pdf | No (not attempted after policy denials) |
| D-02 | Gowin DS117, 3.2.2E, 06/13/2025 (Mouser mirror) | https://www.mouser.com/datasheet/2/1033/DS117E-2820893.pdf | No (snippet only) |
| D-03 | Gowin DS117, 2.9.3E, 10/26/2021 (Sipeed mirror) | https://dl.sipeed.com/fileList/TANG/Nano%209K/6_Chip_Manual/EN/DS117-2.9.3E_GW1NR%20series%20of%20%20FPGA%20Products%20DataSheet.pdf | No (dl.sipeed.com 403) |
| D-04 | Gowin GW1NR product page | https://www.gowinsemi.com/en/product/detail/49/ | No (gowinsemi.com 403) |
| D-05 | Gowin UG285 BSRAM & SSRAM User Guide, 1.4E, 10/17/2025 | https://cdn.gowinsemi.com.cn/UG285E.pdf | No (snippet only) |
| D-06 | Gowin DS100 GW1N series Data Sheet, 3.3.3E, 06/17/2026 | https://cdn.gowinsemi.com.cn/DS100E.pdf | No (snippet only) |
| D-07 | Mouser product page GW1NR-LV9QN88PC6/I5 | https://www.mouser.com/en/ProductDetail/GOWIN-Semiconductor/GW1NR-LV9QN88PC6-I5?qs=OlC7AqGiEDl79xFXbRQ68Q%3D%3D | No (snippet only) |
| D-08 | Sipeed Wiki, Tang Nano 9K | https://wiki.sipeed.com/hardware/en/tang/Tang-Nano-9K/Nano-9K.html | No (ENOTFOUND) |
| D-09 | Sipeed Wiki source (GitHub) | https://github.com/sipeed/sipeed_wiki/blob/main/docs/hardware/en/tang/Tang-Nano-9K/Nano-9K.md (fetched via raw.githubusercontent.com, HEAD 2715512) | **Yes (REQ-01)** |
| D-10 | Tang Nano 9K schematic 3674 (Sipeed) | https://dl.sipeed.com/fileList/TANG/Nano%209K/2_Schematic/Tang_nano_9K_3674_schematics.pdf | No (403) |
| D-11 | Tang Nano 9K schematic 3672, 2021-09-22 (Lushay Labs mirror) | https://learn.lushaylabs.com/content/files/2022/08/Tang_Nano_9K_3672_schematic.pdf | No (snippet only) |
| D-12 | CNX Software article on Tang Nano 9K, 2022-01-17 | https://www.cnx-software.com/2022/01/17/tang-nano-9k-fpga-board-can-emulate-picorv32-risc-v-soft-core-with-all-peripherals/ | No (snippet only) |
| D-13 | LiteX board file sipeed_tang_nano_9k.py | https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/sipeed_tang_nano_9k.py | No (snippet only) |
| D-14 | AtomFpga Tang Nano 9K constraints (.cst) | https://github.com/hoglet67/AtomFpga/blob/master/gowin/AtomFpga_TangNano9K/src/AtomFpga_TangNano9K.cst | No (snippet only) |
| D-15 | weigu.lu Tang Nano 9K notes | https://www.weigu.lu/other_projects/fpga/fpga_tang_nano_9k/index.html | No (snippet only) |
| D-16 | Tang Nano 9K pin & constraints reference (senolgulgonul) | https://senolgulgonul.github.io/verilog/weeks/tang-nano-9k-reference.html | No (snippet only) |
| D-17 | HiTechChain Tang Nano 9K product page | https://hitechchain.se/en/startsida/tang-nano-9k-fpga-board-gowin-gw1nr-9-fpga-with-8640-lut4-6480-flip-flops | No (snippet only) |
| D-18 | Lushay Labs, Tang Nano 9K getting setup | https://learn.lushaylabs.com/getting-setup-with-the-tang-nano-9k/ | No (snippet only) |
| D-19 | RISC-V Unprivileged ISA specification (RV32I base) — referenced for instruction semantics, version to be pinned by the CPU owner (e.g. 20191213) | https://github.com/riscv/riscv-isa-manual | No (reference only, no numeric value taken) |
| D-20 | Apicula / nextpnr-himbaechel-gowin chip database (reverse-engineered), as shipped in yowasp-nextpnr-himbaechel-gowin 0.11.1.0.post826 (nextpnr-0.11.1) with Apycula 0.32; read through the "Device utilisation" report for `--device GW1NR-LV9QN88PC6/I5 --vopt family=GW1N-9C` | logs/smoke/fpga_pnr.log (ST-FPGA-01); scripts/budgets/build/smoke_pnr.log; scripts/budgets/logs/ubench_run*.log | Yes (tool output) |
| D-21 | PicoRV32 README, "Utilization on Xilinx 7-Series FPGAs" table and core source (YosysHQ, HEAD ef203c2) | https://raw.githubusercontent.com/YosysHQ/picorv32/main/README.md (sha256 399c2d2e00e4581ee4ef33034089992401e10c4e917a33cd363b80dfb283e964) | Yes |

## Values — GW1NR-9 device (GW1NR-LV9QN88PC6/I5)
| ID | Item | Value | Unit | Source URL (secondary used) | Section / table | Accessed | Label | Confidence |
|---|---|---|---|---|---|---|---|---|
| S-001 | LUT4 count | 8640 | LUT4 | D-09 Sipeed wiki source (fetched), spec table line 32 "Logic units(LUT4) 8640"; D-20 chip DB "LUT4 .../8640"; earlier snippets D-04, D-12, D-17 | D-09 spec table; D-20 utilisation report | 2026-11-04 | SOURCE | High |
| S-002 | Flip-flops | 6480 | FF | D-09 line 33 "Registers(FF) 6480"; D-20 "DFF .../6480" | D-09 spec table; D-20 | 2026-11-04 | SOURCE | High |
| S-003 | Shadow SRAM (SSRAM, distributed LUT RAM) | 17280 | bit | D-09 line 34 "ShadowSRAM SSRAM(bits) 17280"; D-20: 270 RAM16SDP4 x 64 bit = 17280 bit (CALCULATION) — resolves the "16K" conflict in favour of 17280 | D-09; D-20 | 2026-11-04 | SOURCE | High |
| S-004 | Block SRAM total | 468 | Kbit | D-09 line 35 "Block SRAM BSRAM(bits) 468K"; consistent with 26 x 18 Kbit | D-09 | 2026-11-04 | SOURCE | High |
| S-005 | Number of BSRAM blocks | 26 | block | D-09 line 36 "Number of B-SRAM 26"; D-20 "BSRAM .../26" | D-09; D-20 | 2026-11-04 | SOURCE | High |
| S-006 | Bits per BSRAM block | 18432 (18 Kbit) in x9/x18/x36 modes; 16384 (16 Kbit) in x1..x32 modes | bit | D-05 UG285 ("each BSRAM can be configured as 16 Kbits or 18 Kbits"); D-02 ("up to 18,432 bits") | UG285 sec. 2 / Table 2-1 | 2026-11-04 | ASSUMPTION | High |
| S-007 | BSRAM width x depth configurations | 16Kx1, 8Kx2, 4Kx4, 2Kx8, 1Kx16, 512x32 (16 Kbit); 2Kx9, 1Kx18, 512x36 (18 Kbit) | — | D-05 UG285 Table 2-1. Snippet confirmed only 1Kx16, 2Kx9, 1Kx18, 512x36; others are domain knowledge consistent with the 16 Kbit mode | UG285 Table 2-1 | 2026-11-04 | ASSUMPTION | Medium |
| S-008 | BSRAM port modes | Single Port, Dual Port, Semi-Dual Port, ROM | — | D-05; D-02 | UG285 sec. 2; DS117 BSRAM section | 2026-11-04 | ASSUMPTION | High |
| S-009 | Per-mode max width (512x32/36 only in SP/SDP/ROM; true DP max x16/x18) | see text | — | Not seen in any snippet; domain knowledge | UG285 Table 2-1 (to check) | 2026-11-04 | ASSUMPTION | Low |
| S-010 | 18x18 multipliers (DSP) | 20 | mult | D-09 line 39 "18 x 18 Multiplier 20"; D-20 "MULT18X18 .../20", "MULT9X9 .../40" | D-09; D-20 | 2026-11-04 | SOURCE | High |
| S-011 | PLLs | 2 (rPLL) | PLL | D-09 line 41 "Number of PLL 2"; D-20 "rPLL .../2" — resolves the "one PLL" conflict in favour of 2 | D-09; D-20 | 2026-11-04 | SOURCE | High |
| S-012 | On-chip oscillator | 1, programmable 2.5 to 125 MHz (divider table entries e.g. 2.5, 7.8, 15.6 ... 125 MHz) | MHz | D-02 DS117 3.2.2E divider table (snippet) | DS117 OSC section | 2026-11-04 | ASSUMPTION | Medium |
| S-013 | On-chip oscillator accuracy | ±5 | % | D-06 DS100 (GW1N family wording), not GW1NR-9-specific | DS100 OSC section | 2026-11-04 | ASSUMPTION | Low |
| S-014 | Embedded PSRAM ("R"), QN88P package | 64 Mbit, 16-bit data width | bit | D-02 DS117 (snippet "QN88P ... PSRAM, 64M, 16 bits"); D-04 says 64-128M across packages | DS117 product resources / PSRAM section | 2026-11-04 | ASSUMPTION | Medium |
| S-015 | PSRAM interface supply | 1.8 | V | D-02 DS117 (snippet) | DS117 power supply section | 2026-11-04 | ASSUMPTION | Medium |
| S-016 | User flash | 608 | Kbit | D-09 line 37 "User flash(bits) 608K"; D-20 "FLASH608K .../1" | D-09; D-20 | 2026-11-04 | SOURCE | High |
| S-017 | Max user I/O, QN88P | 71 (DS117 package table "71(11) / 71(17)"); Gowin product page and Mouser say 70 | I/O | D-02; D-04; D-07 | DS117 package/I/O table | 2026-11-04 | ASSUMPTION | Low (conflict 70 vs 71) |
| S-018 | Core voltage VCC (LV), typical | 1.2 | V | D-04 ("Core Voltage Typ. (LV) 1.2V") | DS117 recommended operating conditions | 2026-11-04 | ASSUMPTION | High |
| S-019 | Core voltage range | 1.14 to 1.26 | V | D-07 Mouser | DS117 recommended operating conditions | 2026-11-04 | ASSUMPTION | Medium |
| S-026 | Ordering code | GW1NR-LV9QN88PC6/I5 (LV, QN88P, speed C6/I5) | — | D-07 | DS117 ordering information | 2026-11-04 | ASSUMPTION | High |

## Values — open-source chip database (D-20), GW1NR-LV9QN88PC6/I5, family GW1N-9C
Source = "Apicula/nextpnr chip database (reverse-engineered), tool version
yowasp-nextpnr-himbaechel-gowin 0.11.1.0.post826 (nextpnr-0.11.1), Apycula 0.32".
Read from the "Device utilisation" report (used/total); evidence
`logs/smoke/fpga_pnr.log` and `scripts/budgets/build/smoke_pnr.log` (identical totals).
| ID | Item | Value (total) | Unit | Cross-check | Label | Confidence |
|---|---|---|---|---|---|---|
| S-027 | LUT4 positions (count includes positions used by ALU and LUT-RAM cells, see BUDGETS.md 1.1) | 8640 | LUT4 | = S-001 | SOURCE (D-20) | High |
| S-028 | DFF | 6480 | FF | = S-002 | SOURCE (D-20) | High |
| S-029 | ALU (carry-chain) cells | 6480 | cell | not in D-09 | SOURCE (D-20) | Medium (reverse-engineered) |
| S-030 | RAM16SDP4 (16x4 LUT-RAM) | 270 | cell | 270 x 64 bit = 17280 bit = S-003 | SOURCE (D-20) | High |
| S-031 | BSRAM | 26 | block | = S-005 | SOURCE (D-20) | High |
| S-032 | Multipliers: MULT9X9 / MULT18X18 / MULT36X36 / MULTALU18X18 / MULTADDALU18X18 / MULTALU36X18 / ALU54D / PADD9 / PADD18 | 40 / 20 / 5 / 10 / 10 / 10 / 10 / 40 / 20 | cell | MULT18X18 = S-010 | SOURCE (D-20) | High |
| S-033 | MUX2_LUT5 / LUT6 / LUT7 / LUT8 (wide-function muxes) | 4320 / 2160 / 1080 / 1080 | cell | — | SOURCE (D-20) | Medium |
| S-034 | IOB (die-level I/O sites; package QN88P bonds fewer, see S-017) | 276 | IOB | not a package figure | SOURCE (D-20) | Medium |
| S-035 | rPLL / OSC / FLASH608K / BUFG / CLKDIV / CLKDIV2 / DQCE / DCS / DHCEN | 2 / 1 / 1 / 22 / 8 / 16 / 24 / 8 / 24 | cell | rPLL = S-011, FLASH = S-016 | SOURCE (D-20) | Medium |

## Values — reference designs
| ID | Item | Value | Unit | Source | Label | Confidence |
|---|---|---|---|---|---|---|
| S-036 | PicoRV32 "regular" (default config) on Xilinx 7-Series, area-optimised: Slice LUTs / LUTs as memory / Slice registers | 917 / 48 / 583 | LUT6 / LUT / FF | D-21 README table "Utilization on Xilinx 7-Series FPGAs" | SOURCE | High |
| S-037 | PicoRV32 "small" on Xilinx 7-Series | 761 / 48 / 442 | LUT6 / LUT / FF | D-21 same table | SOURCE | High |

## Values — Tang Nano 9K board
| ID | Item | Value | Unit | Source URL (secondary used) | Section / table | Accessed | Label | Confidence |
|---|---|---|---|---|---|---|---|---|
| S-020 | On-board oscillator frequency / FPGA pin | 27 MHz (D-09 line 18 "Crystal oscillator 27MHZ", fetched); pin 52 (tangnano9k.cst sources: Apicula example + Sipeed examples, fetched by fpga-engineer) | MHz | D-09; design/constraints/tangnano9k.cst header [A][B] | D-09 board table | 2026-11-04 | SOURCE | High |
| S-021 | User LEDs | 6, active-low, pins 10, 11, 13, 14, 15, 16 (LED0..LED5) | LED | D-15; D-16; D-11 schematic (LEDs to 1.8 V rail) | Wiki/schematic LED section | 2026-11-04 | ASSUMPTION | High (count, polarity); Medium (pins) |
| S-022 | User buttons | 2, active-low, 10 kOhm pull-up to 1.8 V, pins 3 and 4. S1/S2 label mapping conflicts (D-15/D-16: S1=4, S2=3; D-11 schematic: S1=3, S2=4, with silkscreen-fix note) | button | D-11; D-15; D-16 | schematic | 2026-11-04 | ASSUMPTION | Medium (Low for label mapping) |
| S-023 | USB bridge | BL702: USB-JTAG (configuration) + USB-UART | — | D-09 line 43 "Onboard BL702 chip provides USB-JTAG and USB-UART functions" | D-09 | 2026-11-04 | SOURCE | High |
| S-024 | UART pins (FPGA side) | TX = pin 17, RX = pin 18, LVCMOS33 | pin | D-13 LiteX (`tx` 17, `rx` 18); D-14 .cst; D-10 schematic labels FPGA_TX 17 / FPGA_RX 18. A Lushay-derived tutorial labels them reversed | constraints / schematic | 2026-11-04 | ASSUMPTION | Medium |
| S-025 | External SPI flash | 32 | Mbit | D-09 line 40 "SPI FLASH 32M-bit" | D-09 | 2026-11-04 | SOURCE | High |

## Consistency checks (CALCULATION)
- BSRAM: 26 blocks x 18 432 bit = 479 232 bit = 468 Kibit -> consistent with S-004/S-005/S-006.
- BSRAM usable in x1..x32 modes: 26 x 16 384 bit = 425 984 bit (416 Kibit).

## Contradictions to resolve
1. ~~S-003 SSRAM: 17 280 bit vs "16K"~~ RESOLVED in REQ-01: 17 280 (D-09 fetched + D-20 270 x 64 bit).
2. ~~S-011 PLLs: 2 vs "one PLL"~~ RESOLVED in REQ-01: 2 (D-09 fetched + D-20 rPLL 2).
3. S-017 QN88P user I/O: 71 (DS117 table) vs 70 (product page, Mouser).
4. S-022 S1/S2 pin labels: 3/4 vs 4/3.
5. S-024 UART direction: one tutorial reverses TX/RX.

## Re-verification needed
Still open after REQ-01: S-006..S-009 (BSRAM modes/widths, UG285), S-012/S-013
(OSC), S-014/S-015 (PSRAM), S-017 (package I/O count), S-018/S-019 (core
voltage), S-021/S-022/S-024 (pins: largely covered by the fetched constraint
sources in tangnano9k.cst; S1/S2 mapping still open), S-026 (ordering code).
Original note (ST-SYS-01):
Allow `cdn.gowinsemi.com.cn`, `www.mouser.com`, `dl.sipeed.com`,
`wiki.sipeed.com` (and `www.gowinsemi.com`) in the session network settings,
then open D-01 (DS117E latest), D-05 (UG285E), D-08 and D-10, record page/table
for each row and change the label to SOURCE.
