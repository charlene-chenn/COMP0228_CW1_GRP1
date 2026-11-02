from typing import List

def decode_repetition(bits, repetition=3) -> List[int]:
    """
    Decode a binary message with repetition encoding (with various levels
    of repetition). Takes the raw bits from the receiver (e.g.
    recording_to_bits) and recovers each message bit by majority vote
    over its repeats.

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

    print("Received bits:", list(bits))
    print("Decoded bits: ", decoded_bits)

    return decoded_bits

def decode_hamming(bits) -> List[int]:
    """
    Decode a binary message with Hamming(7,4) encoding. Each 7-bit block
    is laid out as [p1, p2, d1, p3, d2, d3, d4] (positions 1-7, parity
    bits at the powers of two). Corrects up to one flipped bit per block.

    Args:
        bits (List[int]): received bits.

    Returns:
        List[int]: the 4 data bits of each block.
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

    print("Received bits:", list(bits))
    print("Decoded bits: ", decoded_bits)

    return decoded_bits

def decode_viterbi(bits) -> List[int]:
    """
    Decode a binary message with a hard-decision Viterbi decoder, for the
    rate-1/2 convolutional code (K=3, generators 7 and 5 octal) in conv_enc.py.
    Finds the valid encoder path closest in Hamming distance to the received
    bits. Assumes the encoder started in state 0 and was flushed back to state 0
    by 2 zero tail bits.

    states [00] [01] [10] [11]

    Args:
        bits (List[int]): received bits, as ints 0 or 1, including the tail.

    Returns:
        List[int]: decoded message bits, with the tail removed.
    """
    # A state is the encoder's register as a 2-bit number: (s1 << 1) | s2
    num_steps = len(bits)//2
    inf = float("inf")
    metrics = [0, inf, inf, inf]  # Errors along the best path to each state
    history = []                  # Each step's best previous state, per state

    # Forward pass: extend every path by one input bit at each step
    for t in range(num_steps):
        r0, r1 = bits[2*t], bits[2*t + 1]
        new_metrics = [inf]*4
        previous = [None]*4

        for state in range(4):
            if metrics[state] == inf:
                continue  # Not reachable yet
            s1, s2 = state >> 1, state & 1

            for b in (0, 1):
                # Same outputs as the encoder would produce on this transition
                out0 = b ^ s1 ^ s2
                out1 = b ^ s2
                metric = metrics[state] + (out0 != r0) + (out1 != r1)

                # Two paths merge in each state: keep only the closer one
                next_state = (b << 1) | s1
                if metric < new_metrics[next_state]:
                    new_metrics[next_state] = metric
                    previous[next_state] = state

        metrics = new_metrics
        history.append(previous)

    # Traceback: start from state 0 (the tail guarantees it) and walk backwards
    decoded_bits = []
    state = 0
    for previous in reversed(history):
        decoded_bits.append(state >> 1)  # s1 of a state is the bit that led to it
        state = previous[state]
    decoded_bits.reverse()

    return decoded_bits[:-2]  # Drop the 2 tail bits