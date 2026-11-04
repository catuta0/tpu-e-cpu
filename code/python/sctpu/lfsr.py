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


# ---------------------------------------------------------------------------
# Leap-forward (multi-step) LFSR — ARCHITECTURE.md section 5.3, ADR-005
# ---------------------------------------------------------------------------
#
# The SC-TPU advances every LFSR by 8 single steps per stream cycle so that
# the 8-bit random number r (the low byte of the new state) consists of 8
# fresh feedback bits (ADR-005). Because one step is a linear map over GF(2),
# eight steps are also a linear map: every bit of the new state is the XOR of
# a fixed subset of the bits of the old state. ``LEAP8_MASKS[b]`` is that subset
# for new bit b (bit set at position p <=> old bit p takes part in the XOR).
# The RTL may implement the 8-step network either as 8 chained copies of the
# single-step logic or with these masks directly; both are bit-identical.

#: Number of single LFSR steps per SC-TPU stream cycle (ARCHITECTURE.md 5.3).
STEPS_PER_STREAM_CYCLE = 8


def step_n(state: int, n: int) -> int:
    """Advance ``state`` by ``n`` single steps (reference, ARCHITECTURE.md 5.3).

    This is the literal definition of an n-step leap: ``n`` successive calls of
    :func:`step`. It is deliberately slow and obviously correct; the test suite
    compares the fast mask-based :func:`leap8` against it for every state.
    """
    for _ in range(n):
        state = step(state)
    return state


def _leap_masks(n: int) -> tuple[int, ...]:
    """Return the 16 GF(2) row masks of the n-step transition matrix.

    Method: the transition is linear, so its matrix columns are the images of
    the unit vectors. Column p = step_n(1 << p, n). Row b (new bit b) is then
    the set of p whose column has bit b set. Note ``step`` rejects nothing here
    because a unit vector is non-zero; linearity holds for the zero state too
    (0 maps to 0), so the masks are valid for every state.
    """
    columns = [step_n(1 << p, n) for p in range(WIDTH)]
    rows = []
    for b in range(WIDTH):
        m = 0
        for p in range(WIDTH):
            if (columns[p] >> b) & 1:
                m |= 1 << p
        rows.append(m)
    return tuple(rows)


#: Row masks of the 8-step leap-forward network (new bit b = parity(state & mask)).
LEAP8_MASKS = _leap_masks(STEPS_PER_STREAM_CYCLE)


def leap8(state: int) -> int:
    """Advance ``state`` by 8 steps in one go (ARCHITECTURE.md 5.3, ADR-005).

    Implements the unrolled XOR network with :data:`LEAP8_MASKS`. Equivalent to
    ``step_n(state, 8)`` (checked exhaustively by the unit tests). Python's
    ``int.bit_count`` gives the parity of each masked word.
    """
    out = 0
    for b, mask in enumerate(LEAP8_MASKS):
        out |= ((state & mask).bit_count() & 1) << b
    return out


def stream_r_sequence(seed: int, n_cycles: int) -> list[int]:
    """Return the r values of ``n_cycles`` stream cycles starting from ``seed``.

    ARCHITECTURE.md 5.3: one stream cycle advances the LFSR by 8 steps and uses
    the low byte of the NEW state as r. The seed itself is therefore never used
    as r; the first r is ``leap8(seed) & 0xFF`` (literal reading, see the
    SW-01a handoff, ambiguity A2).
    """
    out = []
    s = seed
    for _ in range(n_cycles):
        s = leap8(s)
        out.append(s & 0xFF)
    return out
