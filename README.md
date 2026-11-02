# COMP0228 CW1

Sends coded bits across a motor-to-piezo vibration channel. Python does the encoding and decoding, and the Arduino Giga sends and measures the bits.

## Setup

```
pip install -r requirements.txt
```

Upload `piezo_reciever.ino` to the Giga, then close the Serial Monitor.

## Use

Run from this folder:

```
python3 run_sim.py                     # all codes, simulated channel
python3 -m channel.hardware            # list serial ports
python3 -m channel.hardware <port>     # test the real channel
```

Keep the surface still during calibration.
