"""Build sim/soc/build/soc_expected.hex for tests/soc/tb_soc.v.
Layout (one 32-bit hex word per line): 0 RESULT, 1 TOHOST, 2 LED, 3 K,
4..7 HIDDEN words, 8..23 SCORE words, 24 number of UART bytes, 25.. bytes,
zero padding to 32 words."""
import hashlib, json, sys
from pathlib import Path
data, out = Path(sys.argv[1]), Path(sys.argv[2])
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()

# Golden line of the vector file: pset 0, test position 0, K=8, s=0, mode 2.
vf = data / "tpu_vectors_mode2.txt"
lines = vf.read_text().splitlines()
print(f"vector file {vf} sha256 {sha(vf)}")
REV = sys.argv[3]   # required spec revision (SPEC_REV of the shell script)
hdr = f"# spec_rev {REV}"
print(f"vector file '{hdr}' header:", "present" if any(l.strip() == hdr for l in lines[:5]) else "MISSING")
if not any(l.strip() == hdr for l in lines[:5]):
    sys.exit(f"vector file is not spec_rev {REV}")
vec = None
for l in lines:
    if not l.strip() or l.startswith("#"):
        continue
    f = [int(x, 16) for x in l.split()]
    if f[0] == 0 and f[4] == 0:
        vec = f
        break
assert vec is not None and vec[1] == 8 and vec[2] == 0 and vec[3] == 2, "vector line idx 0 not K=8 s=0 mode 2"
v_in, v_hid, v_sc, v_res = vec[6:22], vec[22:26], vec[26:42], vec[42]
inp = [int(l.split("//")[0], 16) for l in (data / "input.hex").read_text().splitlines() if l.split("//")[0].strip()]
assert inp == v_in, "input.hex != INPUT words of vector idx 0"
print("input.hex == INPUT words of the idx-0 vector: yes")

j = data / "soc_expected.json"
if j.exists():
    e = json.loads(j.read_text())
    print(f"source: {j} (sha256 {sha(j)}), generator {e.get('generator')}, git_rev {e.get('git_rev')}")
    assert e["spec_rev"] == REV, f"soc_expected.json is not spec_rev {REV}"
    assert e["K"] == 8 and e["act_shift_s"] == 0 and e["rng_mode"] == 2
    for k, fname in (("input_sha256", "input.hex"), ("weights_sha256", "weights.hex"), ("bias_sha256", "bias.hex")):
        assert e[k] == sha(data / fname), f"{fname} sha256 differs from soc_expected.json"
        print(f"{fname} sha256 matches soc_expected.json")
    res, tohost, led, K = e["result"], e["expected_tohost"], e["expected_led"], e["K"]
    hid = [int(x, 16) for x in e["hidden_words"]]
    sc = [int(x, 16) & 0xFFFFFFFF for x in e["score_words"]]
    uart = [int(x, 16) for x in e["expected_uart_bytes"]]
    assert hid == v_hid and sc == v_sc and res == v_res, "soc_expected.json != vector file line idx 0"
    print("cross-check soc_expected.json == tpu_vectors_mode2.txt idx 0 (HIDDEN, SCORE, RESULT): OK")
else:
    print("SOURCE: soc_expected.json ABSENT -> expectation from tpu_vectors_mode2.txt idx 0 (documented fallback)")
    res, tohost, led, K = v_res, 1, v_res, 8
    hid, sc, uart = v_hid, v_sc, [0x30 + v_res, 0x0A]
assert uart == [0x30 + res, 0x0A] and led == res and tohost == 1
w = [res, tohost, led, K] + hid + sc + [len(uart)] + uart
w += [0] * (32 - len(w))
out.write_text("".join(f"{x & 0xFFFFFFFF:08x}\n" for x in w))
print(f"EXPECTED RESULT={res} LED={led} TOHOST={tohost} K={K} UART={[hex(u) for u in uart]}")
print(f"EXPECTED HIDDEN={[hex(x) for x in hid]}")
print(f"EXPECTED SCORE={[x - (1 << 32) if x >> 31 else x for x in sc]}")
params = e["params_expected"] if j.exists() else {"B": "0x02020810", "C": "0x03020810"}[REV]
print(f"PARAMS_EXPECTED={int(params, 16):08x}")
print(f"wrote {out}")
print("EXPECTATION_OK")
