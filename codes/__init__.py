"""
Library of error-correcting codes. Every code has the same interface:

    code = CODES["conv75"]
    coded = code.encode(message)
    decoded = code.decode(received)[:len(message)]  # trim any padding

To add a new code, write its encode and decode functions and add it to CODES.
"""
from dataclasses import dataclass
from typing import Callable, List

from .convolutional import conv_encode, decode_viterbi
from .hamming import decode_hamming, encode_hamming
from .repetition import decode_repetition, encode_repetition


@dataclass(frozen=True)
class Code:
    name: str
    encode: Callable[[List[int]], List[int]]
    decode: Callable[[List[int]], List[int]]


def _repetition_code(n: int) -> Code:
    return Code(
        f"R{n}",
        lambda bits: encode_repetition(bits, n),
        lambda bits: decode_repetition(bits, n),
    )


CODES = {code.name: code for code in [
    Code("none", list, list),
    _repetition_code(3),
    _repetition_code(5),
    Code("hamming74", encode_hamming, decode_hamming),
    Code("conv75", conv_encode, decode_viterbi),
]}
