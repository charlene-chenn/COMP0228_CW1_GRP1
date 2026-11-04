"""
Real channel: sends bits through the Arduino running piezo_receiver_v3.ino over USB.

Test the link from the project folder (close the Arduino Serial Monitor first):
    python3 -m channel.hardware                  # lists the available ports
    python3 -m channel.hardware /dev/cu.usbmodemXXXX
"""
import sys
import time
from typing import List, Tuple

import serial
from serial.tools import list_ports

MAX_BITS = 1000    # Must match MAX_LINE in piezo_receiver_v3.ino
BOOT_WAIT_S = 6.0  # Long enough for a board reset and its 3 s calibration


class ArduinoLink:
    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 5.0):
        """
        Connect to the Arduino and wait for it to finish calibrating.

        Args:
            port (str): serial port, e.g. /dev/cu.usbmodem1101.
            baudrate (int, optional): must match the sketch. Defaults to 115200.
            timeout (float, optional): longest wait for a reply line in seconds.
                Must be longer than one bit takes. Defaults to 5.0.
        """
        self.threshold = None
        self.ser = serial.Serial(port, baudrate, timeout=timeout)
        self._wait_until_ready()

    def send_and_receive(self, bits, on_bit=None) -> Tuple[List[int], List[int]]:
        """
        Transmit bits through the motor and return what the piezo detected.

        Args:
            bits (List[int]): bits to send, as ints 0 or 1.
            on_bit (Callable, optional): called as on_bit(index, detected, vibration)
                as each bit's reply arrives, for live viewing. Defaults to None.

        Returns:
            Tuple[List[int], List[int]]: the detected bit and the raw
            peak-to-peak vibration reading for each bit sent.
        """
        text = "".join(str(int(b)) for b in bits)

        if set(text) - {"0", "1"}:
            raise ValueError("Bits must be 0 or 1")
        if len(text) > MAX_BITS:
            raise ValueError(f"Can't send {len(text)} bits at once (limit {MAX_BITS})")
        if not text:
            return [], []

        rows = [line.split(",") for line in self._command("B" + text, on_bit)]

        # A missing reply would shift every later bit, so never let it through
        if len(rows) != len(text):
            raise RuntimeError(f"Sent {len(text)} bits but got {len(rows)} readings")

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
            # Calibration messages aren't data
            if not line.startswith(("Calibrating", "Keep", "Noise", "Threshold")):
                replies.append(line)
                if on_bit is not None:
                    detected, vibration = line.split(",")
                    on_bit(len(replies) - 1, int(detected), int(vibration))

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


if __name__ == "__main__":
    main()
