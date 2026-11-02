import random
from typing import List, Optional


def flip_one_bit(bits, position: Optional[int] = None) -> List[int]:
    """
    Very basic simulated channel: returns a copy of the bits with one flipped.

    Args:
        bits (List[int]): bits going into the channel.
        position (int, optional): index of the bit to flip. Defaults to a random one.

    Returns:
        List[int]: bits coming out of the channel.
    """
    received = list(bits)

    if position is None:
        position = random.randrange(len(received))

    received[position] ^= 1

    return received
