from typing import List


def encode_repetition(bits, repetition=3) -> List[int]:
    """Send each bit `repetition` times in a row."""
    encoded_bits = []

    for b in bits:
        encoded_bits.extend([b]*repetition)

    return encoded_bits


def decode_repetition(bits, repetition=3) -> List[int]:
    """Recover each bit by majority vote over its repeats."""
    decoded_bits = []
    num_bits = len(bits)//repetition

    for b in range(num_bits):
        group = bits[b*repetition:(b+1)*repetition]
        decoded_bits.append(1 if sum(group) > repetition/2 else 0)

    return decoded_bits
