from typing import List


def encode_hamming(bits) -> List[int]:
    """
    Encode a binary message with Hamming(7,4) encoding. Each 4 data bits become
    a 7-bit block laid out as [p1, p2, d1, p3, d2, d3, d4] (positions 1-7, parity
    bits at the powers of two). The message is padded with zeros to a multiple
    of 4 bits, so the decoded output can be longer than the original message.

    Args:
        bits (List[int]): message bits.

    Returns:
        List[int]: encoded bits, 7 for each (possibly padded) group of 4.
    """
    padded = list(bits) + [0]*(-len(bits) % 4)
    encoded_bits = []

    for b in range(0, len(padded), 4):
        d1, d2, d3, d4 = padded[b:b + 4]

        # Each parity bit makes its parity check in decode_hamming come out as 0
        p1 = d1 ^ d2 ^ d4  # checks positions 1,3,5,7
        p2 = d1 ^ d3 ^ d4  # checks positions 2,3,6,7
        p3 = d2 ^ d3 ^ d4  # checks positions 4,5,6,7

        encoded_bits.extend([p1, p2, d1, p3, d2, d3, d4])

    return encoded_bits


def decode_hamming(bits) -> List[int]:
    """
    Decode a binary message with Hamming(7,4) encoding. Each 7-bit block
    is laid out as [p1, p2, d1, p3, d2, d3, d4] (positions 1-7, parity
    bits at the powers of two). Corrects up to one flipped bit per block.

    Args:
        bits (List[int]): received bits.

    Returns:
        List[int]: the 4 data bits of each block, including any padding.
    """
    decoded_bits = []
    num_blocks = len(bits)//7

    for b in range(num_blocks):
        # Extract blocks of length 7
        block = list(bits[b*7:(b+1)*7])

        # Each parity check covers the positions whose index has that bit set
        s1 = block[0] ^ block[2] ^ block[4] ^ block[6]  # positions 1,3,5,7
        s2 = block[1] ^ block[2] ^ block[5] ^ block[6]  # positions 2,3,6,7
        s3 = block[3] ^ block[4] ^ block[5] ^ block[6]  # positions 4,5,6,7

        # Syndrome gives the 1-indexed position of the error (0 = no error)
        syndrome = s1 + 2*s2 + 4*s3
        if syndrome != 0:
            block[syndrome - 1] ^= 1

        decoded_bits.extend([block[2], block[4], block[5], block[6]])

    # print("Received bits:", list(bits))
    # print("Decoded bits: ", decoded_bits)

    return decoded_bits
