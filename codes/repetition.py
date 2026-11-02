from typing import List


def encode_repetition(bits, repetition=3) -> List[int]:
    """
    Encode a binary message by sending each bit several times in a row.

    Args:
        bits (List[int]): message bits.
        repetition (int, optional): number of times to repeat each bit. Defaults to 3.

    Returns:
        List[int]: encoded bits, of length len(bits) * repetition.
    """
    encoded_bits = []

    for b in bits:
        encoded_bits.extend([b]*repetition)

    return encoded_bits


def decode_repetition(bits, repetition=3) -> List[int]:
    """
    Decode a binary message with repetition encoding (with various levels
    of repetition). Recovers each message bit by majority vote over its repeats.

    Args:
        bits (List[int]): received bits.
        repetition (int, optional): number of times each bit was repeated. Defaults to 3.

    Returns:
        List[int]: decoded message bits.
    """
    decoded_bits = []
    num_bits = len(bits)//repetition

    for b in range(num_bits):
        # Extract groups of length repetition
        group = bits[b*repetition:(b+1)*repetition]
        # Majority vote
        decoded_bits.append(1 if sum(group) > repetition/2 else 0)

    # print("Received bits:", list(bits))
    # print("Decoded bits: ", decoded_bits)

    return decoded_bits
