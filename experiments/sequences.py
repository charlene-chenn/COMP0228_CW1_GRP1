"""The bit strings sent in the experiments."""
import random
from typing import List

from scipy.signal import max_len_seq


def prbs9() -> List[int]:
    """
    The 511-bit PRBS-9 sequence. It is the same every time, so repeats can be
    lined up to see which errors depend on the data.

    Returns:
        List[int]: 256 ones and 255 zeros.
    """
    return [int(bit) for bit in max_len_seq(9)[0]]


def random_message(seed: int, length: int = 64) -> List[int]:
    """
    A random message that can be recreated from its seed. Every code and every
    test case gets the same message for a given seed, so they compare fairly.

    Args:
        seed (int): the seed to log.
        length (int, optional): number of bits. Defaults to 64.

    Returns:
        List[int]: the message bits.
    """
    rng = random.Random(seed)
    return [rng.randint(0, 1) for _ in range(length)]
