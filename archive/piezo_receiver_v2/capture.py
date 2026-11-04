"""Capture piezo samples from the GIGA R1 (giga_piezo_logger.ino, MODE_BINARY).

Usage:
    python capture.py PORT SECONDS OUTFILE [MOTOR_MODE]
    e.g.  python capture.py /dev/ttyACM0 10 noise_g1.npy 0
          python capture.py COM5 20 step_g1.npy 2

MOTOR_MODE (default 0) is sent to the board after the port opens:
    0 = motor off
    1 = motor on continuously
    2 = on for MOTOR_ON_MS / off for MOTOR_OFF_MS, repeating (set in the sketch)

Saves the raw uint16 samples to OUTFILE (.npy) and prints a health report:
dropped buffers, DC level, noise, clipping, peak-to-peak swing and the
dominant vibration frequency.

The sketch must be built with OUTPUT_MODE = MODE_BINARY, and the Serial
Monitor/Plotter must be closed (only one program can hold the port).
"""
import sys
import time

import numpy as np
import serial  # pip install pyserial

FS = 10_000           # must match SAMPLE_RATE in the sketch
N = 256               # must match N_SAMPLES in the sketch
VREF = 3.3
FULL_SCALE = 65535    # 16-bit
SYNC = b"\xA5\x5A"
FRAME = 2 + 4 + 2 * N  # sync + uint32 counter + N x uint16


def capture(port: str, seconds: float, motor_mode: int) -> np.ndarray:
    ser = serial.Serial(port, timeout=1)  # pyserial asserts DTR, which the sketch waits for
    time.sleep(0.2)                       # let the sketch leave setup()
    ser.write(str(motor_mode).encode())   # one character: '0', '1' or '2'
    ser.flush()
    ser.reset_input_buffer()              # discard anything sent before the mode change

    buf = bytearray()
    chunks, last, dropped = [], None, 0
    t_end = time.time() + seconds

    try:
        while time.time() < t_end:
            buf += ser.read(8192)
            while True:
                i = buf.find(SYNC)
                if i < 0:
                    del buf[:-1]          # keep last byte: could be half a sync word
                    break
                # Need this frame plus the next sync word, to reject false syncs
                # (0xA5 0x5A can occur inside sample data).
                if len(buf) - i < FRAME + 2:
                    del buf[:i]
                    break
                if buf[i + FRAME:i + FRAME + 2] != SYNC:
                    del buf[:i + 1]       # false sync: skip and search again
                    continue
                frame = bytes(buf[i:i + FRAME])
                del buf[:i + FRAME]
                cnt = int.from_bytes(frame[2:6], "little")
                if last is not None and cnt != last + 1:
                    dropped += max(cnt - last - 1, 0)
                last = cnt
                chunks.append(np.frombuffer(frame[6:], dtype="<u2"))
    finally:
        ser.write(b"0")                   # motor off before closing
        ser.flush()
        ser.close()                       # the sketch also stops the motor on close

    print(f"buffers received: {len(chunks)}, dropped: {dropped}")
    return np.concatenate(chunks) if chunks else np.array([], dtype=np.uint16)


def report(x: np.ndarray) -> None:
    if x.size == 0:
        print("no data received")
        return
    v = x.astype(float) / FULL_SCALE * VREF
    clip = np.mean((x < 200) | (x > FULL_SCALE - 200)) * 100
    print(f"samples: {x.size}  ({x.size / FS:.2f} s at {FS} Hz)")
    print(f"DC level: {v.mean():.3f} V   (expect ~1.65 V with mid-rail bias)")
    print(f"std: {v.std() * 1e3:.2f} mV   peak-to-peak: {np.ptp(v):.3f} V")
    print(f"near-rail samples: {clip:.2f} %   (should be ~0 %)")

    ac = v - v.mean()
    spec = np.abs(np.fft.rfft(ac * np.hanning(ac.size)))
    freqs = np.fft.rfftfreq(ac.size, 1 / FS)
    band = freqs > 20                     # ignore DC and the high-pass corners
    if band.any():
        k = np.argmax(spec[band])
        print(f"dominant frequency: {freqs[band][k]:.1f} Hz")


def main() -> None:
    if len(sys.argv) not in (4, 5):
        print(__doc__)
        sys.exit(1)
    port, seconds, outfile = sys.argv[1], float(sys.argv[2]), sys.argv[3]
    motor_mode = int(sys.argv[4]) if len(sys.argv) == 5 else 0
    if motor_mode not in (0, 1, 2):
        sys.exit("MOTOR_MODE must be 0, 1 or 2")

    print(f"capturing {seconds:g} s from {port}, motor mode {motor_mode}")
    x = capture(port, seconds, motor_mode)
    np.save(outfile, x)
    print(f"saved {outfile}")
    report(x)


if __name__ == "__main__":
    main()