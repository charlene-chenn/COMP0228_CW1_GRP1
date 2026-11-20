import math
import random
import time
from typing import List, Optional, Tuple

import numpy as np


def flip_one_bit(bits, position: Optional[int] = None) -> List[int]:
    """Very basic simulated channel: flips one bit (a random one by default)."""
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

    # Made-up raw signal, only there so raw recording can be tried without hardware
    SAMPLE_RATE = 10000
    BUFFER_SAMPLES = 256
    RAW_MIDDLE = 32768
    MOTOR_HZ = 180
    RAW_NOISE = 300
    OFFSET_SAMPLES = 20

    def __init__(self, bit_s: float = 0.0, seed: int = 1, raw: bool = False):
        """bit_s is the time to wait per bit, in seconds."""
        self.bit_s = bit_s
        self.rng = random.Random(seed)
        self.np_rng = np.random.default_rng(seed)
        self.raw = raw
        self.sample_rate = self.SAMPLE_RATE
        self.last_raw = None
        self.last_offsets = None
        self.last_late = None
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
        previous_level = 0.0
        in_burst = False
        self.last_raw = [] if self.raw else None
        self.last_offsets = [] if self.raw else None
        self.last_late = 0

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

            samples = None
            if self.raw:
                samples = self._raw_bit(previous_level, value)
                self.last_raw.append(samples)
                self.last_offsets.append(self.OFFSET_SAMPLES)
            previous_level = value

            if on_bit is not None:
                on_bit(index, detected, value, samples)
            time.sleep(self.bit_s)

        return received, vibration

    def _raw_bit(self, start_level: float, end_level: float) -> np.ndarray:
        """A sine at the motor speed whose peak-to-peak moves from one level to the next."""
        wanted = (self.settle_ms + self.window_ms) * self.SAMPLE_RATE // 1000
        count = -(-wanted // self.BUFFER_SAMPLES) * self.BUFFER_SAMPLES
        t = np.arange(count) / self.SAMPLE_RATE
        settle = self.settle_ms * self.SAMPLE_RATE // 1000
        ramp = np.clip((np.arange(count) - self.OFFSET_SAMPLES) / max(settle, 1), 0, 1)
        level = start_level + (end_level - start_level) * ramp
        wave = self.RAW_MIDDLE + level / 2 * np.sin(2 * np.pi * self.MOTOR_HZ * t)
        wave += self.np_rng.normal(0, self.RAW_NOISE, count)
        return np.clip(wave, 0, 65535).astype(np.uint16)
