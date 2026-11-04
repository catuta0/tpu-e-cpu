"""REV-01b independent seed/lag checks from ARCHITECTURE.md 5.3/11/12 only."""
def step(s):
    fb = ((s >> 15) ^ (s >> 13) ^ (s >> 12) ^ (s >> 10)) & 1
    return ((s << 1) | fb) & 0xFFFF
seq = []; pos = {}
s = 0xACE1
for n in range(65535):
    seq.append(s); pos[s] = n; s = step(s)
assert s == 0xACE1 and len(pos) == 65535, "not maximal"
print("period 65535 OK; S(32768)=%04X" % seq[32768])
X = [(0xACE1 + 0x3C5A * i) & 0xFFFF for i in range(16)]
W = [(0x7A5C + 0x2B67 * i) & 0xFFFF for i in range(16)]
print("X lanes 0..15:", " ".join("%04X" % v for v in X))
print("W lanes 0..15:", " ".join("%04X" % v for v in W))
inv8 = pow(8, -1, 65535)
gens = [("X%d" % i, X[i]) for i in range(8)] + [("W%d" % i, W[i]) for i in range(8)]
best = None
for a in range(16):
    for b in range(a + 1, 16):
        d = (pos[gens[b][1]] - pos[gens[a][1]]) % 65535
        m = d * inv8 % 65535
        dist = min(m, 65535 - m)
        if best is None or dist < best[0]:
            best = (dist, gens[a][0], gens[b][0])
print("min pairwise stream-cycle lag (mode 2, lanes 0..7):", best)
# R1: pair offsets P_w(i)-P_x(i) pairwise distinct
P = lambda v: pos[v] * inv8 % 65535
offs = [(P(W[i]) - P(X[i])) % 65535 for i in range(8)]
print("R1 pair offsets distinct:", len(set(offs)) == 8)
# 8-step leap: each new low bit = XOR of exactly 4 old bits; high byte = old low byte
cols = []
for p in range(16):
    t = 1 << p
    for _ in range(8): t = step(t)
    cols.append(t)
rows = [sum(1 << p for p in range(16) if (cols[p] >> b) & 1) for b in range(16)]
print("leap8 row weights (bit0..15):", [bin(r).count('1') for r in rows])
