"""16-bit Fibonacci LFSR golden model.

Purpose
-------
Stochastic computing converts a binary number into a random bit stream by
comparing it against a pseudo-random number every clock cycle. In hardware the
cheapest pseudo-random source is a linear-feedback shift register (LFSR). This
module is the bit-exact Python reference of that LFSR so that RTL simulation
can be checked against it word for word (task ST-SW-01, smoke test).

Polynomial
----------
    p(x) = x^16 + x^14 + x^13 + x^11 + 1

This is a primitive polynomial over GF(2), so the register visits every
non-zero 16-bit state exactly once before repeating: the period is
2^16 - 1 = 65535 (CALCULATION). The all-zero state is a lock-up state (it maps
to itself) and must never be used as a seed.

Bit numbering and shift direction
---------------------------------
State bits are numbered 0 (LSB) .. 15 (MSB). The polynomial taps 16, 14, 13
and 11 correspond to state bits 15, 13, 12 and 10 (tap k -> bit k-1). Each
step:

    feedback = bit15 XOR bit13 XOR bit12 XOR bit10
    next     = ((state << 1) | feedback) & 0xFFFF

i.e. the register shifts towards the MSB and the feedback bit enters at bit 0.
An RTL implementation must use exactly this ordering to be bit-exact with
this model:

    always @(posedge clk) state <= {state[14:0], state[15]^state[13]^state[12]^state[10]};

Only Python integers are used (no floats), as required by the golden-model
rules in .claude/skills/python-model-flow/SKILL.md.
"""

from __future__ import annotations

from typing import Iterator

#: Register width in bits.
WIDTH = 16

#: Mask that keeps a value inside the 16-bit register.
MASK = (1 << WIDTH) - 1  # 0xFFFF

#: State bit positions (0-based) XORed to form the feedback bit.
#: They are the polynomial exponents 16, 14, 13, 11 minus one.
TAPS = (15, 13, 12, 10)

#: Theoretical period of a maximal-length 16-bit LFSR: 2^16 - 1.
MAX_PERIOD = (1 << WIDTH) - 1  # 65535

#: Conventional non-zero default seed (widely used example value).
DEFAULT_SEED = 0xACE1


def feedback(state: int) -> int:
    """Return the feedback bit (0 or 1) for a 16-bit ``state``.

    The feedback is the XOR of state bits 15, 13, 12 and 10 (see ``TAPS``).
    """
    fb = 0
    for tap in TAPS:
        fb ^= (state >> tap) & 1
    return fb


def step(state: int) -> int:
    """Advance the LFSR by one clock and return the next 16-bit state.

    ``next = ((state << 1) | feedback(state)) & 0xFFFF``. The mask models the
    fixed register width: the old bit 15 is shifted out and discarded (it has
    already contributed to the feedback).

    Raises
    ------
    ValueError
        If ``state`` is outside 0..0xFFFF.
    """
    if not 0 <= state <= MASK:
        raise ValueError(f"state 0x{state:X} is not a 16-bit value")
    return ((state << 1) | feedback(state)) & MASK


class LFSR16:
    """Stateful 16-bit Fibonacci LFSR (wrapper around :func:`step`).

    Parameters
    ----------
    seed:
        Initial non-zero 16-bit state. Zero is rejected because the LFSR would
        stay locked at zero forever (it would never produce a random stream).
    """

    def __init__(self, seed: int = DEFAULT_SEED) -> None:
        if not 0 < seed <= MASK:
            raise ValueError(
                f"seed 0x{seed:X} must be a non-zero 16-bit value (0 is the lock-up state)"
            )
        self.state = seed

    def next(self) -> int:
        """Advance one step, store and return the new state."""
        self.state = step(self.state)
        return self.state

    def __iter__(self) -> Iterator[int]:
        """Iterate forever over successive states (the seed itself is not yielded)."""
        while True:
            yield self.next()


def period(seed: int = DEFAULT_SEED, limit: int = MAX_PERIOD + 1) -> int:
    """Return the number of steps until ``seed`` recurs.

    The search stops after ``limit`` steps so a wrong tap set cannot loop
    forever; in that case ``-1`` is returned. For a maximal-length LFSR the
    result is ``MAX_PERIOD`` (65535) for every non-zero seed.
    """
    reg = LFSR16(seed)
    for n in range(1, limit + 1):
        if reg.next() == seed:
            return n
    return -1
