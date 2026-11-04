# Sources register

Owner: systems-engineer. Created in task ST-SYS-01 (2026-11-04).

## How to read this register
- Every external value used by the project gets one row with an ID `S-xxx`.
- **Label** is `SOURCE` only when the primary document was opened and the value
  read from it (with page/table). Otherwise it is `ASSUMPTION` and the
  secondary source actually used is named.
- **Confidence**: High = several independent secondary sources agree, including
  a vendor-originated snippet; Medium = one or two consistent secondary sources;
  Low = sources disagree or only partial data was seen.

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
| D-09 | Sipeed Wiki source (GitHub) | https://github.com/sipeed/sipeed_wiki/blob/main/docs/hardware/en/tang/Tang-Nano-9K/Nano-9K.md | No (snippet only) |
| D-10 | Tang Nano 9K schematic 3674 (Sipeed) | https://dl.sipeed.com/fileList/TANG/Nano%209K/2_Schematic/Tang_nano_9K_3674_schematics.pdf | No (403) |
| D-11 | Tang Nano 9K schematic 3672, 2021-09-22 (Lushay Labs mirror) | https://learn.lushaylabs.com/content/files/2022/08/Tang_Nano_9K_3672_schematic.pdf | No (snippet only) |
| D-12 | CNX Software article on Tang Nano 9K, 2022-01-17 | https://www.cnx-software.com/2022/01/17/tang-nano-9k-fpga-board-can-emulate-picorv32-risc-v-soft-core-with-all-peripherals/ | No (snippet only) |
| D-13 | LiteX board file sipeed_tang_nano_9k.py | https://github.com/litex-hub/litex-boards/blob/master/litex_boards/platforms/sipeed_tang_nano_9k.py | No (snippet only) |
| D-14 | AtomFpga Tang Nano 9K constraints (.cst) | https://github.com/hoglet67/AtomFpga/blob/master/gowin/AtomFpga_TangNano9K/src/AtomFpga_TangNano9K.cst | No (snippet only) |
| D-15 | weigu.lu Tang Nano 9K notes | https://www.weigu.lu/other_projects/fpga/fpga_tang_nano_9k/index.html | No (snippet only) |
| D-16 | Tang Nano 9K pin & constraints reference (senolgulgonul) | https://senolgulgonul.github.io/verilog/weeks/tang-nano-9k-reference.html | No (snippet only) |
| D-17 | HiTechChain Tang Nano 9K product page | https://hitechchain.se/en/startsida/tang-nano-9k-fpga-board-gowin-gw1nr-9-fpga-with-8640-lut4-6480-flip-flops | No (snippet only) |
| D-18 | Lushay Labs, Tang Nano 9K getting setup | https://learn.lushaylabs.com/getting-setup-with-the-tang-nano-9k/ | No (snippet only) |

## Values — GW1NR-9 device (GW1NR-LV9QN88PC6/I5)
| ID | Item | Value | Unit | Source URL (secondary used) | Section / table | Accessed | Label | Confidence |
|---|---|---|---|---|---|---|---|---|
| S-001 | LUT4 count | 8640 | LUT4 | D-04 https://www.gowinsemi.com/en/product/detail/49/ ; D-08/D-09 Sipeed wiki; D-12; D-17 | DS117 product resources table (Table 1-1 expected; not seen) | 2026-11-04 | ASSUMPTION | High |
| S-002 | Flip-flops | 6480 | FF | D-04; D-12; D-17 | as S-001 | 2026-11-04 | ASSUMPTION | High |
| S-003 | Shadow SRAM (SSRAM, distributed LUT RAM) | 17280 | bit | D-12 CNX; D-17 HiTechChain (third-party). One search summary claimed the Gowin table shows "16K"; not confirmed | as S-001 | 2026-11-04 | ASSUMPTION | Low (conflict) |
| S-004 | Block SRAM total | 468 | Kbit | D-04; D-08 wiki; Amazon/retail listings. (One retailer lists "486K", treated as typo) | as S-001 | 2026-11-04 | ASSUMPTION | High |
| S-005 | Number of BSRAM blocks | 26 | block | D-04 (search snippet of Gowin family table) | as S-001 | 2026-11-04 | ASSUMPTION | Medium |
| S-006 | Bits per BSRAM block | 18432 (18 Kbit) in x9/x18/x36 modes; 16384 (16 Kbit) in x1..x32 modes | bit | D-05 UG285 ("each BSRAM can be configured as 16 Kbits or 18 Kbits"); D-02 ("up to 18,432 bits") | UG285 sec. 2 / Table 2-1 | 2026-11-04 | ASSUMPTION | High |
| S-007 | BSRAM width x depth configurations | 16Kx1, 8Kx2, 4Kx4, 2Kx8, 1Kx16, 512x32 (16 Kbit); 2Kx9, 1Kx18, 512x36 (18 Kbit) | — | D-05 UG285 Table 2-1. Snippet confirmed only 1Kx16, 2Kx9, 1Kx18, 512x36; others are domain knowledge consistent with the 16 Kbit mode | UG285 Table 2-1 | 2026-11-04 | ASSUMPTION | Medium |
| S-008 | BSRAM port modes | Single Port, Dual Port, Semi-Dual Port, ROM | — | D-05; D-02 | UG285 sec. 2; DS117 BSRAM section | 2026-11-04 | ASSUMPTION | High |
| S-009 | Per-mode max width (512x32/36 only in SP/SDP/ROM; true DP max x16/x18) | see text | — | Not seen in any snippet; domain knowledge | UG285 Table 2-1 (to check) | 2026-11-04 | ASSUMPTION | Low |
| S-010 | 18x18 multipliers (DSP) | 20 | mult | D-04 (search snippet); DSP macro = 2x 18x18 or 4x 9x9 | as S-001; DS117 DSP section | 2026-11-04 | ASSUMPTION | Medium |
| S-011 | PLLs | 2 (rPLL) | PLL | D-04; D-08 wiki. Conflict: an older DS117 revision states "GW1NR provides one PLL" (likely GW1NR-1/-4 wording) | as S-001; DS117 clock section | 2026-11-04 | ASSUMPTION | Medium |
| S-012 | On-chip oscillator | 1, programmable 2.5 to 125 MHz (divider table entries e.g. 2.5, 7.8, 15.6 ... 125 MHz) | MHz | D-02 DS117 3.2.2E divider table (snippet) | DS117 OSC section | 2026-11-04 | ASSUMPTION | Medium |
| S-013 | On-chip oscillator accuracy | ±5 | % | D-06 DS100 (GW1N family wording), not GW1NR-9-specific | DS100 OSC section | 2026-11-04 | ASSUMPTION | Low |
| S-014 | Embedded PSRAM ("R"), QN88P package | 64 Mbit, 16-bit data width | bit | D-02 DS117 (snippet "QN88P ... PSRAM, 64M, 16 bits"); D-04 says 64-128M across packages | DS117 product resources / PSRAM section | 2026-11-04 | ASSUMPTION | Medium |
| S-015 | PSRAM interface supply | 1.8 | V | D-02 DS117 (snippet) | DS117 power supply section | 2026-11-04 | ASSUMPTION | Medium |
| S-016 | User flash | 608 (304 rows x 64 cols x 32) | Kbit | D-02 DS117 (snippet) | DS117 User Flash section | 2026-11-04 | ASSUMPTION | Medium |
| S-017 | Max user I/O, QN88P | 71 (DS117 package table "71(11) / 71(17)"); Gowin product page and Mouser say 70 | I/O | D-02; D-04; D-07 | DS117 package/I/O table | 2026-11-04 | ASSUMPTION | Low (conflict 70 vs 71) |
| S-018 | Core voltage VCC (LV), typical | 1.2 | V | D-04 ("Core Voltage Typ. (LV) 1.2V") | DS117 recommended operating conditions | 2026-11-04 | ASSUMPTION | High |
| S-019 | Core voltage range | 1.14 to 1.26 | V | D-07 Mouser | DS117 recommended operating conditions | 2026-11-04 | ASSUMPTION | Medium |
| S-026 | Ordering code | GW1NR-LV9QN88PC6/I5 (LV, QN88P, speed C6/I5) | — | D-07 | DS117 ordering information | 2026-11-04 | ASSUMPTION | High |

## Values — Tang Nano 9K board
| ID | Item | Value | Unit | Source URL (secondary used) | Section / table | Accessed | Label | Confidence |
|---|---|---|---|---|---|---|---|---|
| S-020 | On-board oscillator frequency / FPGA pin | 27 MHz, pin 52 (IOR17A / GCLKT_3) | MHz | D-08/D-09 wiki; D-10/D-11 schematic (XTAL_IN on pin 52); D-18 (`IO_LOC "clk" 52`) | Wiki spec table; schematic | 2026-11-04 | ASSUMPTION | High |
| S-021 | User LEDs | 6, active-low, pins 10, 11, 13, 14, 15, 16 (LED0..LED5) | LED | D-15; D-16; D-11 schematic (LEDs to 1.8 V rail) | Wiki/schematic LED section | 2026-11-04 | ASSUMPTION | High (count, polarity); Medium (pins) |
| S-022 | User buttons | 2, active-low, 10 kOhm pull-up to 1.8 V, pins 3 and 4. S1/S2 label mapping conflicts (D-15/D-16: S1=4, S2=3; D-11 schematic: S1=3, S2=4, with silkscreen-fix note) | button | D-11; D-15; D-16 | schematic | 2026-11-04 | ASSUMPTION | Medium (Low for label mapping) |
| S-023 | USB bridge | BL702: USB-JTAG (configuration) + USB-UART | — | D-08/D-09 wiki; D-13 | Wiki spec table | 2026-11-04 | ASSUMPTION | High |
| S-024 | UART pins (FPGA side) | TX = pin 17, RX = pin 18, LVCMOS33 | pin | D-13 LiteX (`tx` 17, `rx` 18); D-14 .cst; D-10 schematic labels FPGA_TX 17 / FPGA_RX 18. A Lushay-derived tutorial labels them reversed | constraints / schematic | 2026-11-04 | ASSUMPTION | Medium |
| S-025 | External SPI flash | 32 | Mbit | D-08 wiki (snippet) | Wiki spec table | 2026-11-04 | ASSUMPTION | Medium |

## Consistency checks (CALCULATION)
- BSRAM: 26 blocks x 18 432 bit = 479 232 bit = 468 Kibit -> consistent with S-004/S-005/S-006.
- BSRAM usable in x1..x32 modes: 26 x 16 384 bit = 425 984 bit (416 Kibit).

## Contradictions to resolve
1. S-003 SSRAM: 17 280 bit (third-party) vs "16K" (unconfirmed Gowin snippet).
2. S-011 PLLs: 2 (product page, wiki) vs "one PLL" (older DS117 wording).
3. S-017 QN88P user I/O: 71 (DS117 table) vs 70 (product page, Mouser).
4. S-022 S1/S2 pin labels: 3/4 vs 4/3.
5. S-024 UART direction: one tutorial reverses TX/RX.

## Re-verification needed
Allow `cdn.gowinsemi.com.cn`, `www.mouser.com`, `dl.sipeed.com`,
`wiki.sipeed.com` (and `www.gowinsemi.com`) in the session network settings,
then open D-01 (DS117E latest), D-05 (UG285E), D-08 and D-10, record page/table
for each row and change the label to SOURCE.
