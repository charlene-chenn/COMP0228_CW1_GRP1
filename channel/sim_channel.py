import math
import random
import time
from typing import List, Optional, Tuple


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


class SimulatedLink:
    """
    Stands in for ArduinoLink so the experiment code can be tried with no hardware.
    Its motor tail and bursts are made up, so its results say nothing about the channel.
    """

    ON_LEVEL = 40000
    NOISE_LEVEL = 3000
    TAIL_LEVEL = 30000
    TAIL_MS = 30
    BURST_CHANCE = 0.004
    BURST_STOP_CHANCE = 0.3

    def __init__(self, bit_s: float = 0.0, seed: int = 1):
        """
        Args:
            bit_s (float, optional): time to wait per bit. Defaults to 0.0.
            seed (int, optional): seed for the noise. Defaults to 1.
        """
        self.bit_s = bit_s
        self.rng = random.Random(seed)
        self.settle_ms = 100
        self.window_ms = 100
        self.threshold = 0
        self.calibrate()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self) -> None:
        pass

    def set_settle_ms(self, ms: int) -> None:
        self.settle_ms = ms

    def set_window_ms(self, ms: int) -> None:
        self.window_ms = ms
        self.calibrate()

    def calibrate(self) -> None:
        self.threshold = 2 * self.NOISE_LEVEL + 3000

    def send_and_receive(self, bits, on_bit=None) -> Tuple[List[int], List[int]]:
        """Same as ArduinoLink.send_and_receive, through a simulated motor and piezo."""
        received, vibration = [], []
        previous = 0
        in_burst = False

        for index, bit in enumerate(bits):
            in_burst = (
                self.rng.random() > self.BURST_STOP_CHANCE if in_burst
                else self.rng.random() < self.BURST_CHANCE
            )

            value = self.rng.gauss(self.NOISE_LEVEL, 800)
            if bit:
                value += self.ON_LEVEL
            elif previous:
                value += self.TAIL_LEVEL * math.exp(-self.settle_ms / self.TAIL_MS)
            if in_burst:
                value = self.rng.uniform(0, 2 * self.threshold)

            value = max(0, int(value))
            detected = 1 if value >= self.threshold else 0
            received.append(detected)
            vibration.append(value)
            previous = bit

            if on_bit is not None:
                on_bit(index, detected, value)
            time.sleep(self.bit_s)

        return received, vibration
