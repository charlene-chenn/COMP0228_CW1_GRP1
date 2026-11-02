from typing import List


def conv_encode(bits) -> List[int]:
    """
    Rate-1/2 convolutional encoder (K=3, generators 7 and 5 octal). Appends
    2 zero tail bits so the register ends in state 0.

    Args:
        bits (List[int]): message bits, as ints 0 or 1.

    Returns:
        List[int]: flat encoded bits, of length 2 * (len(bits) + 2).
    """
    s1, s2 = 0, 0  # s1 = previous input bit, s2 = the one before that
    encoded = []

    for b in list(bits) + [0, 0]:
        encoded.append(b ^ s1 ^ s2)  # generator 7 (111)
        encoded.append(b ^ s2)       # generator 5 (101)
        s1, s2 = b, s1

    return encoded


def decode_viterbi(bits) -> List[int]:
    """
    Decode a binary message with a hard-decision Viterbi decoder, for the
    rate-1/2 convolutional code in conv_encode. Finds the valid encoder path
    closest in Hamming distance to the received bits. Assumes the encoder
    started in state 0 and was flushed back to state 0 by 2 zero tail bits.

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
