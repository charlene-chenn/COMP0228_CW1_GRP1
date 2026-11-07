"""The bit strings sent in the experiments."""
import math
import random
from typing import List

from scipy.signal import max_len_seq


def prbs(order: int) -> List[int]:
    """
    A PRBS sequence of 2^order - 1 bits: 31 for PRBS-5 and 511 for PRBS-9. It is
    the same every time, so repeats can be lined up to see which errors depend on
    the data.

    Args:
        order (int): the PRBS order. The longest run of ones is this long.

    Returns:
        List[int]: the sequence, with one more one than zeros.
    """
    return [int(bit) for bit in max_len_seq(order)[0]]


def prbs_name(length: int) -> str:
    """Name a PRBS sequence from its length, e.g. 31 gives PRBS-5."""
    return f"PRBS-{round(math.log2(length + 1))}"


def row_label(block: str, index: int) -> str:
    """The label for one PRBS string in an error map."""
    return "ref" if block == "reference" else f"R{index + 1}"


def random_message(seed: int, length: int = 32) -> List[int]:
    """
    A random message that can be recreated from its seed. Every code and every
    test case gets the same message for a given seed, so they compare fairly.

    Args:
        seed (int): the seed to log.
        length (int, optional): number of bits. Defaults to 32.

    Returns:
        List[int]: the message bits.
    """
    rng = random.Random(seed)
    return [rng.randint(0, 1) for _ in range(length)]
