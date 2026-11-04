#!/usr/bin/env python3
"""REV-01a: SoC mutation experiments on COPIES of design/rtl/soc (originals untouched).
Each mutant: list of exact (old, new) replacements in one file (each must match once).
Run: tb_soc demo, tb_soc_bfm, tb_soc CPU mode with dir_mmio dir_stores rand_00 trap_misaligned_sw.
"""
import shutil, subprocess
from pathlib import Path
ROOT = Path("/home/user/tpu-e-cpu"); B = ROOT / "reports/review/build/REV-01a"
SRC = ROOT / "design/rtl/soc"
M = [
 ("S01", "LED pins not inverted", "soc_top.v", [("assign led_n = ~led;", "assign led_n = led;")]),
 ("S02", "UART sends MSB first", "soc_periph.v", [("tx_sh   <= {1'b1, mem_wdata[7:0]};",
   "tx_sh   <= {1'b1, mem_wdata[0], mem_wdata[1], mem_wdata[2], mem_wdata[3], mem_wdata[4], mem_wdata[5], mem_wdata[6], mem_wdata[7]};")]),
 ("S03", "UART 233 clocks per bit", "soc_periph.v", [("localparam integer    DIV_M1     = UART_DIV - 1;", "localparam integer    DIV_M1     = UART_DIV - 2;")]),
 ("S04", "UART frame ends after d7 (no full stop bit)", "soc_periph.v", [("end else if (tx_nbit == 4'd9) begin", "end else if (tx_nbit == 4'd8) begin")]),
 ("S05", "RAM byte enables of lanes 1 and 2 swapped", "soc_ram.v", [("if (we[1]) mem[word][15:8]", "if (we[2]) mem[word][15:8]"), ("if (we[2]) mem[word][23:16]", "if (we[1]) mem[word][23:16]")]),
 ("S06", "bus_err not sticky", "soc_bus.v", [("if (un_valid) bus_err <= 1'b1;", "bus_err <= un_valid;")]),
 ("S07", "reset synchroniser reduced to 1 FF", "soc_top.v", [("wire rst = rst_sync[1];", "wire rst = rst_sync[0];")]),
 ("S08", "UART_TX write while busy restarts the frame", "soc_periph.v", [("wire tx_start = wr && sel_tx && mem_wstrb[0] && !tx_busy;", "wire tx_start = wr && sel_tx && mem_wstrb[0];"), ("end else if (!tx_busy) begin", "end else if (!tx_busy || tx_start) begin")]),
 ("S09", "CYCLE counter reset value 5", "soc_periph.v", [("if (rst) cycle_q <= 32'd0;", "if (rst) cycle_q <= 32'd5;")]),
 ("S10", "region 0xF decoded as RAM", "soc_bus.v", [("wire       sel_ram = (region == 4'h0);", "wire       sel_ram = (region == 4'h0) || (region == 4'hF);")]),
 ("S11", "UART_STATUS always reads 0", "soc_periph.v", [("if (sel_status) rd_mux = {31'd0, tx_busy};", "if (sel_status) rd_mux = 32'd0;")]),
 ("S12", "periph accepts again in its ready cycle (double ready)", "soc_periph.v", [("wire       accept = mem_valid && !ready_q;", "wire       accept = mem_valid;")]),
 ("S13", "RAM writes all lanes on any strobe", "soc_ram.v", [("wire [3:0] we     = accept ? mem_wstrb : 4'b0000;", "wire [3:0] we     = accept ? {4{|mem_wstrb}} : 4'b0000;")]),
 ("S14", "TOHOST reset value 1", "soc_periph.v", [("if (rst) tohost_q <= 32'd0;", "if (rst) tohost_q <= 32'd1;")]),
 ("S15", "CYCLE counts 2 per clock", "soc_periph.v", [("else     cycle_q <= cycle_q + 32'd1;", "else     cycle_q <= cycle_q + 32'd2;")]),
 ("S16", "LED register written without byte-0 strobe check, from lane 1", "soc_periph.v", [("led_q <= mem_wdata[5:0];", "led_q <= mem_wdata[13:8];")]),
 ("S17", "unmapped read returns RAM data", "soc_bus.v", [("({32{sel_tpu}} & tpu_rdata);      // sel_un: 0", "({32{sel_tpu}} & tpu_rdata) | ({32{sel_un}} & ram_rdata);")]),
 ("S18", "RAM ignores addr bit 11 (2 KiB)", "soc_ram.v", [("wire [9:0] word = mem_addr[11:2];", "wire [9:0] word = {1'b0, mem_addr[10:2]};")]),
]
rows = []
for mid, desc, fname, reps in M:
    d = B / "mut" / mid; shutil.rmtree(d, ignore_errors=True); (d / "soc").mkdir(parents=True)
    for f in SRC.glob("*.v"): shutil.copy(f, d / "soc" / f.name)
    p = d / "soc" / fname; t = p.read_text(); ok = True
    for o, n in reps:
        if t.count(o) != 1: ok = False; break
        t = t.replace(o, n)
    if not ok: rows.append(f"{mid} | {desc} | NOT APPLIED"); print(rows[-1]); continue
    p.write_text(t)
    (d / "mutation.diff").write_text(subprocess.run(["diff", "-u", str(SRC / fname), str(p)], capture_output=True, text=True).stdout)
    r = subprocess.run([str(B / "scripts/run_soc.sh"), str(d / "sim"), str(d / "soc"), "design/rtl/cpu",
                        "dir_mmio", "dir_stores", "rand_00", "trap_misaligned_sw"], capture_output=True, text=True, timeout=1800)
    res = " ".join(r.stdout.split())
    status = "KILLED" if "FAIL" in res else "SURVIVED"
    rows.append(f"{mid} | {desc} | {status} | {res}"); print(rows[-1], flush=True)
(B / "mut" / "soc_mutation_results.txt").write_text("\n".join(rows) + "\n")
