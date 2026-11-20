"""
Real channel: sends bits through the Arduino running piezo_receiver_v3.ino over USB.

Test the link from the project folder (close the Arduino Serial Monitor first):
    python3 -m channel.hardware                  # lists the available ports
    python3 -m channel.hardware /dev/cu.usbmodemXXXX
"""
import re
import sys
import time
from typing import List, Optional, Tuple

import numpy as np
import serial
from serial.tools import list_ports

MAX_BITS = 1000       # Must match MAX_LINE in piezo_receiver_v3.ino
SAMPLE_RATE = 10000   # Hz, must match SAMPLE_RATE in piezo_receiver_v3.ino
BOOT_WAIT_S = 6.0     # Long enough for a board reset and its 3 s calibration
RAW_HEADER = re.compile(r"R(\d+),(-?\d+)")


class ArduinoLink:
    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 5.0,
                 raw: bool = False):
        """
        Connect to the Arduino and wait for it to finish calibrating.

        timeout is the longest wait for a reply line in seconds, so it must be
        longer than one bit takes. With raw=True the piezo samples for every bit
        are kept in last_raw after each send_and_receive.
        """
        self.threshold = None
        self.raw = raw
        self.sample_rate = SAMPLE_RATE
        self.last_raw: Optional[List[np.ndarray]] = None  # Samples for each bit
        self.last_offsets: Optional[List[int]] = None     # Motor switch, samples into each bit
        self.last_late: Optional[int] = None              # Bits that ran long
        self._pending_raw = None
        self.ser = serial.Serial(port, baudrate, timeout=timeout)
        self._wait_until_ready()
        try:
            self._command("R1" if raw else "R0")
        except RuntimeError:
            if raw:
                raise RuntimeError(
                    "The sketch doesn't know the R command. Upload the current "
                    "piezo_receiver_v3.ino to record raw samples."
                ) from None
            # An older sketch, which never streams raw samples anyway

    def send_and_receive(self, bits, on_bit=None) -> Tuple[List[int], List[int]]:
        """
        Transmit bits through the motor and return (detected, vibration) per bit.

        on_bit(index, detected, vibration, raw) is called as each reply arrives,
        for live viewing; raw is None unless raw recording is on. With raw on,
        the samples, motor switch positions and late count are left in last_raw,
        last_offsets and last_late.
        """
        text = "".join(str(int(b)) for b in bits)

        if set(text) - {"0", "1"}:
            raise ValueError("Bits must be 0 or 1")
        if len(text) > MAX_BITS:
            raise ValueError(f"Can't send {len(text)} bits at once (limit {MAX_BITS})")
        if not text:
            self.last_raw, self.last_offsets, self.last_late = [], [], 0
            return [], []

        self.last_raw = [] if self.raw else None
        self.last_offsets = [] if self.raw else None
        self.last_late = None
        rows = [line.split(",") for line in self._command("B" + text, on_bit)]

        # A missing reply would shift every later bit, so never let it through
        if len(rows) != len(text):
            raise RuntimeError(f"Sent {len(text)} bits but got {len(rows)} readings")

        if self.raw and len(self.last_raw) != len(text):
            raise RuntimeError(f"Sent {len(text)} bits but got raw samples for {len(self.last_raw)}")

        received = [int(row[0]) for row in rows]
        vibration = [int(row[1]) for row in rows]

        return received, vibration

    def set_settle_ms(self, ms: int) -> None:
        """Set how long to wait after switching the motor before measuring."""
        self._command(f"S{int(ms)}")

    def set_window_ms(self, ms: int) -> None:
        """Set how long to measure each bit for. Also recalibrates (about 3 s)."""
        self._command(f"W{int(ms)}")

    def calibrate(self) -> None:
        """Recalibrate the threshold (about 3 s). Keep the surface still."""
        self._command("C")

    def close(self) -> None:
        self.ser.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _wait_until_ready(self) -> None:
        # Opening the port restarts some boards, which then calibrate and print
        # READY. Other boards keep running, so ask them if nothing has arrived.
        deadline = time.monotonic() + BOOT_WAIT_S
        while time.monotonic() < deadline:
            raw = self.ser.readline()
            if raw and self._note_line(raw) == "READY":
                return

        self.ser.write(b"?\n")
        while self._read_line() != "READY":
            pass

    def _command(self, command: str, on_bit=None) -> List[str]:
        """Send a command and return its reply lines, up to DONE."""
        self.ser.write((command + "\n").encode())

        replies = []
        while True:
            line = self._read_line()
            if line == "DONE":
                return replies
            if line.startswith("ERR"):
                raise RuntimeError(f"Arduino replied: {line}")
            if line.startswith("Late:"):
                self.last_late = int(line.split(":")[1])
                continue
            header = RAW_HEADER.fullmatch(line)
            if header:
                self._read_raw(int(header[1]), int(header[2]))
                continue
            # Calibration messages aren't data
            if not line.startswith(("Calibrating", "Keep", "Noise", "Threshold")):
                replies.append(line)
                raw = None
                if self._pending_raw is not None:
                    raw, offset = self._pending_raw
                    self._pending_raw = None
                    if self.last_raw is not None:
                        self.last_raw.append(raw)
                        self.last_offsets.append(offset)
                if on_bit is not None:
                    detected, vibration = line.split(",")
                    on_bit(len(replies) - 1, int(detected), int(vibration), raw)

    def _read_raw(self, count: int, offset: int) -> None:
        """Read one bit's raw samples, sent as binary straight after their header."""
        data = self.ser.read(2 * count)
        if len(data) != 2 * count:
            raise TimeoutError(f"Expected {count} raw samples but the Arduino stopped sending")
        self._pending_raw = (np.frombuffer(data, dtype="<u2").copy(), offset)

    def _read_line(self) -> str:
        raw = self.ser.readline()
        if not raw:
            raise TimeoutError(
                "No reply from the Arduino. Check the port, that the sketch is "
                "uploaded, and that the Serial Monitor is closed."
            )
        return self._note_line(raw)

    def _note_line(self, raw: bytes) -> str:
        line = raw.decode(errors="replace").strip()
        if line.startswith("Threshold:"):
            self.threshold = int(line.split(":")[1])
        return line


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 -m channel.hardware <port>\nAvailable ports:")
        for port in list_ports.comports():
            print(" ", port.device, "-", port.description)
        return

    print("Connecting...")
    with ArduinoLink(sys.argv[1]) as link:
        print("Calibrating, keep the surface still...")
        link.calibrate()
        print("Threshold:", link.threshold)

        sent = [1, 0, 1, 0, 1, 1, 0, 0]
        received, vibration = link.send_and_receive(sent)

        print("Sent:     ", sent)
        print("Received: ", received)
        print("Vibration:", vibration)
        print("Wrong:    ", sum(a != b for a, b in zip(sent, received)))

        # Same bits again with raw recording, to check the streaming works
        try:
            link._command("R1")
        except RuntimeError:
            print("Raw:       not supported, upload the current piezo_receiver_v3.ino")
            return
        link.raw = True
        received_raw, vibration_raw = link.send_and_receive(sent)
        link._command("R0")
        link.raw = False

        print("Raw:       ", [len(r) for r in link.last_raw], "samples per bit")
        print("Switch at: ", link.last_offsets, "samples into each bit")
        print("Late bits: ", link.last_late)
        print("Vibration: ", vibration_raw, "(with raw on)")


if __name__ == "__main__":
    main()
