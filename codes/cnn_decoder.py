"""
1D CNN demodulator: decides each bit from the vibration envelope around it.

For each bit the model sees the envelope of that bit's slot plus 2 bits on each side, so it can
learn the spin-up and spin-down levels. It outputs the probability (0 to 1) that the bit is a 1,
and is also trained to say which transition the slot was (previous bit -> this bit) so it learns
the four level curves. The bits then go to the code's normal decoder. A plain linear model on the
same window is trained alongside, to show what the CNN adds over "a filter and a threshold".

    python3 -m codes.cnn_decoder train
    python3 -m codes.cnn_decoder eval --test "material=pcb"
    python3 -m codes.cnn_decoder predict --npz <capture.npz>
"""
import argparse
import collections
import glob
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import torch
from scipy import signal
from torch import nn

from codes import CODES
from codes.filtering import filter_and_detect, find_motor_band, midpoint_threshold, raw_peak_to_peak

STEPS_PER_BIT = 16   # envelope steps per bit: 2048 samples / 128 = 12.8 ms, longer than one ~100 Hz cycle
CONTEXT = 2          # bits of context on each side of the bit being decided
ENV_HZ = 30.0        # low-pass of the rectified signal (the envelope)
RESULTS_GLOB = "experiments/results/**/*.npz"
CASE_RE = re.compile(r"^(?P<material>[a-z]+)_(?P<dist>\d+)cm_(?P<noise>[a-z-]+?)_S(?P<settle>\d+)_W(?P<window>\d+)")
DEFAULT_MODEL = "models/cnn_decoder.pt"

# Part 1: Prep data
# Define data structure
#   recording file -> envelope (how strong the vibration is) -> one small window per bit.
#   The label for each bit is the bit that was actually sent.

# One recording = raw samples + the bits we sent + what the Arduino decided.
@dataclass
class Recording:
    path: str
    code: str              # none, R3, R5, hamming74, conv75
    meta: Dict[str, str]   # material, dist, noise, settle, window, run
    samples: np.ndarray
    sent: np.ndarray       # the channel bits that were transmitted (the labels)
    received: np.ndarray   # what the Arduino decided (only used for comparison)
    bit_start: np.ndarray
    switch_offset: np.ndarray
    fs: float
    settle_ms: float


# Parse metadata: Read material, distance and noise type from the folder name.
def parse_meta(path: str) -> Optional[Dict[str, str]]:
    for part in Path(path).parts:
        m = CASE_RE.match(part)
        if m:
            meta = m.groupdict()
            run = re.search(r"run(\d+)", part)
            meta["run"] = run.group(1) if run else "0"
            return meta
    return None


# Open one .npz file and put its contents into a Recording.
def load_recording(path: str) -> Optional[Recording]:
    meta = parse_meta(path)
    if meta is None:
        return None
    d = np.load(path)
    return Recording(
        path=path, code=Path(path).stem.rsplit("_", 1)[1], meta=meta,
        samples=d["samples"].astype(np.float32), sent=d["sent"].astype(int),
        received=d["received"].astype(int), bit_start=d["bit_start"].astype(int),
        switch_offset=d["switch_offset"].astype(int), fs=float(d["sample_rate"]),
        settle_ms=float(d["settle_ms"]),
    )


# Find every recording under experiments/results.
def find_recordings(root: str = ".", settle_ms: Optional[float] = 150) -> List[Recording]:
    out = []
    for p in sorted(glob.glob(str(Path(root) / RESULTS_GLOB), recursive=True)):
        rec = load_recording(p)
        if rec is not None and (settle_ms is None or rec.settle_ms == settle_ms):
            out.append(rec)
    return out


# Check a recording against a filter like 'material=wood;noise=none'.
def matches(rec: Recording, spec: str) -> bool:
    """spec like 'material=wood,acrylic;noise=none': clauses ANDed, values ORed. '' matches all."""
    for clause in filter(None, spec.split(";")):
        key, values = clause.split("=")
        if rec.meta[key.strip()] not in [v.strip() for v in values.split(",")]:
            return False
    return True


# Raw wiggles -> smooth strength line -> 16 numbers per bit slot (1 = loud, 0 = silent).
def envelope_steps(rec: Recording) -> np.ndarray:
    """
    (n_bits, STEPS_PER_BIT) envelope of every bit slot, scaled so the string's loud level is 1.
    Envelope = rectify, then low-pass at ENV_HZ. Each slot starts when the motor was switched
    (bit_start + switch_offset) and lasts one slot.
    """
    x = rec.samples - np.median(rec.samples)
    sos = signal.butter(2, ENV_HZ, btype="lowpass", fs=rec.fs, output="sos")
    env = signal.sosfiltfilt(sos, np.abs(x))
    bit_n = int(rec.bit_start[1] - rec.bit_start[0])
    block = bit_n // STEPS_PER_BIT
    out = np.zeros((len(rec.sent), STEPS_PER_BIT), np.float32)
    for i in range(len(rec.sent)):
        a = int(rec.bit_start[i] + rec.switch_offset[i])
        w = env[a:a + bit_n]
        w = np.pad(w, (0, bit_n - len(w)))
        out[i] = w.reshape(STEPS_PER_BIT, block).mean(1)
    return out / max(float(np.percentile(out, 95)), 1.0)


# For each bit, stack its 16 numbers with the 2 bits before and 2 bits after it.
# Add margin: a 0 after a 1 starts loud (motor still slowing), a 0 after a 0 starts silent.
def bit_windows(rec: Recording) -> np.ndarray:
    """One example per bit: (n_bits, 2, (2*CONTEXT+1)*STEPS_PER_BIT) = envelope and a 'bit exists' flag."""
    env = envelope_steps(rec)
    n = len(rec.sent)
    X = np.zeros((n, 2, (2 * CONTEXT + 1) * STEPS_PER_BIT), np.float32)
    for i in range(n):
        for k, j in enumerate(range(i - CONTEXT, i + CONTEXT + 1)):
            if 0 <= j < n:
                X[i, 0, k * STEPS_PER_BIT:(k + 1) * STEPS_PER_BIT] = env[j]
                X[i, 1, k * STEPS_PER_BIT:(k + 1) * STEPS_PER_BIT] = 1.0
    return X


# Label each bit with what came before it: 0->0, 0->1, 1->0 or 1->1.
def transitions(rec: Recording) -> np.ndarray:
    """Class 0..3 for each bit: 2 * previous bit + this bit (the bit before the first is 0)."""
    prev = np.concatenate([[0], rec.sent[:-1]])
    return (2 * prev + rec.sent).astype(np.int64)


# Join all recordings into one big table: inputs, sent bits, transition labels.
def build_dataset(recs: Sequence[Recording]) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    X = np.concatenate([bit_windows(r) for r in recs])
    y = np.concatenate([r.sent for r in recs]).astype(np.float32)
    t = np.concatenate([transitions(r) for r in recs])
    return X, y, t


# Part 2: Define the models.
#   window of numbers in -> probability that the bit is a 1 (between 0 and 1) out.

# Add a zoomed-in view of small levels, so leftover buzz is not lost next to a loud 1.
def with_log_channel(x: torch.Tensor) -> torch.Tensor:
    """Add a log-level channel so small leftover levels after a 1 stay visible next to the full level."""
    env, flag = x[:, 0:1], x[:, 1:2]
    # The envelope's low-pass can ring slightly below 0 after a loud burst; the floor keeps
    # the log finite there and leaves every other value unchanged.
    return torch.cat([env, torch.log((env + 0.02).clamp(min=1e-3)), flag], 1)

# The CNN: filters find shapes in the window, then a small layer decides 1 or 0.
# It also guesses the transition type, which teaches it spin-up and spin-down.
class Cnn(nn.Module):
    """Small 1D CNN. Returns (bit logit, transition logits for the 4 classes)."""

    def __init__(self):
        super().__init__()
        steps = (2 * CONTEXT + 1) * STEPS_PER_BIT
        self.features = nn.Sequential(
            nn.Conv1d(3, 16, 5, padding=2), nn.ReLU(),
            nn.Conv1d(16, 16, 5, padding=2), nn.ReLU(),
            nn.Flatten(), nn.Dropout(0.3), nn.Linear(16 * steps, 32), nn.ReLU(),
        )
        self.bit = nn.Linear(32, 1)
        self.transition = nn.Linear(32, 4)

    def forward(self, x):
        h = self.features(with_log_channel(x))
        return self.bit(h).squeeze(-1), self.transition(h)


# The simple baseline: add up the window with learned weights and decide. No shapes.
class Linear(nn.Module):
    """Baseline: logistic regression on the same window. A linear filter plus a decision, nothing more."""

    def __init__(self):
        super().__init__()
        self.lin = nn.Linear((2 * CONTEXT + 1) * STEPS_PER_BIT, 1)

    def forward(self, x):
        return self.lin(x[:, 0]).squeeze(-1), None


MODELS = {"linear": Linear, "cnn": Cnn}


# Part 3: Train model
#   repeat: show a batch of windows -> model guesses -> compare with the sent bits -> adjust weights.
def train_model(kind: str, X, y, t, epochs: int, lr: float, batch: int, seed: int,
                transition_weight: float = 0.5, gain_jitter: float = 0.2) -> nn.Module:
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    model = MODELS[kind]()
    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
    bce, ce = nn.BCEWithLogitsLoss(), nn.CrossEntropyLoss()
    Xt, yt, tt = torch.from_numpy(X), torch.from_numpy(y), torch.from_numpy(t)
    for epoch in range(epochs):
        model.train()
        order = rng.permutation(len(X))
        total = 0.0
        for i in range(0, len(order), batch):
            idx = order[i:i + batch]
            xb = Xt[idx].clone()
            xb[:, 0] *= torch.from_numpy(rng.uniform(1 - gain_jitter, 1 + gain_jitter, (len(idx), 1)).astype(np.float32))
            bit_logit, trans_logit = model(xb)
            loss = bce(bit_logit, yt[idx])
            if trans_logit is not None:
                loss = loss + transition_weight * ce(trans_logit, tt[idx])
            opt.zero_grad()
            loss.backward()
            opt.step()
            total += float(loss.detach()) * len(idx)
        if epoch % 10 == 0 or epoch == epochs - 1:
            print(f"  {kind} epoch {epoch + 1:3}/{epochs}  loss {total / len(X):.4f}")
    model.eval()
    return model


# Part 4: Run inference
#   recording in -> probability per bit -> 0 if under 0.5, 1 if 0.5 or over.
class CnnDecoder:
    """Trained model wrapper: CnnDecoder.load(path).decode(rec) gives a 0/1 for every bit of a recording."""

    def __init__(self, model: nn.Module, kind: str):
        self.model, self.kind = model, kind

    @classmethod
    def load(cls, path: str) -> "CnnDecoder":
        ck = torch.load(path, map_location="cpu", weights_only=True)
        model = MODELS[ck["kind"]]()
        model.load_state_dict(ck["state"])
        model.eval()
        return cls(model, ck["kind"])

    def save(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        torch.save({"kind": self.kind, "state": self.model.state_dict()}, path)

    def probabilities(self, rec: Recording) -> np.ndarray:
        """Probability that each bit is a 1 (usable as a soft decision)."""
        with torch.no_grad():
            return torch.sigmoid(self.model(torch.from_numpy(bit_windows(rec)))[0]).numpy()

    def decode(self, rec: Recording) -> List[int]:
        return [int(p >= 0.5) for p in self.probabilities(rec)]


# Part 5: Evaluation
#   bits from each method -> the code's decoder -> message -> count the wrong bits.

# The other methods to compare against: Arduino, adaptive threshold, band-pass filter.
def baseline_bits(rec: Recording) -> Dict[str, List[int]]:
    """The other demodulators on the same recording."""
    x, fs = rec.samples.astype(float), rec.fs
    start = int(rec.bit_start[0])
    bit_ms = (rec.bit_start[1] - rec.bit_start[0]) * 1000 / fs
    n = len(rec.sent)
    raw = raw_peak_to_peak(x, fs, bit_ms, n, rec.settle_ms, start)
    lo, hi = find_motor_band(x, fs, halfwidth=25)
    filt = filter_and_detect(x, fs, bit_ms, n, lo, hi, rec.settle_ms, start, smooth_hz=40)["bits"]
    return {"hardware": [int(b) for b in rec.received],
            "adaptive raw": [int(v >= midpoint_threshold(raw)) for v in raw],
            "band-pass": filt}


# Count errors for every method and code, then print the tables.
def evaluate(recs: Sequence[Recording], predictors: Dict[str, Callable[[Recording], List[int]]]) -> None:
    """Message-bit error rate per code and demodulator, then channel errors by transition."""
    order = ["none", "R3", "R5", "hamming74", "conv75"]
    msg = collections.defaultdict(lambda: np.zeros(2))
    chan = collections.defaultdict(lambda: np.zeros(2))
    trans = collections.defaultdict(lambda: np.zeros(2))
    for rec in recs:
        if rec.code not in CODES or len(set(rec.sent)) < 2:
            continue
        group = f"{rec.meta['material']}, noise={rec.meta['noise']}"
        code = CODES[rec.code]
        truth = code.decode(list(rec.sent))
        cls = transitions(rec)
        for name, fn in predictors.items():
            bits = np.array(fn(rec))
            decoded = code.decode(list(bits))
            msg[(group, name, rec.code)] += [sum(a != b for a, b in zip(truth, decoded)), len(truth)]
            wrong = bits != rec.sent
            chan[(group, name)] += [wrong.sum(), len(bits)]
            for c in range(4):
                trans[(group, name, c)] += [wrong[cls == c].sum(), (cls == c).sum()]
    for g in sorted({k[0] for k in msg}):
        print(f"\n{g}: message-bit error rate after each code's decoder")
        print(f"  {'demodulator':14}" + "".join(f"{c:>11}" for c in order) + f"{'channel BER':>13}")
        for n in predictors:
            cells = "".join(f"{msg[(g, n, c)][0] / msg[(g, n, c)][1]:>10.1%} " if msg[(g, n, c)][1] else f"{'-':>11}" for c in order)
            print(f"  {n:14}{cells}{chan[(g, n)][0] / max(chan[(g, n)][1], 1):>12.1%}")
        print(f"  channel bit errors by transition (previous->this):  " + "   ".join(["0->0", "0->1", "1->0", "1->1"]))
        for n in predictors:
            print(f"  {n:14}" + "".join(f"{trans[(g, n, c)][0] / max(trans[(g, n, c)][1], 1):>14.1%}" for c in range(4)))


# Put the trained models next to the other methods, then run evaluate.
def run_eval(recs, models: Dict[str, nn.Module]) -> None:
    predictors = {k: (lambda r, k=k: baseline_bits(r)[k]) for k in ("hardware", "adaptive raw", "band-pass")}
    for kind, m in models.items():
        predictors[kind] = CnnDecoder(m, kind).decode
    evaluate(recs, predictors)


# CLI
#   train = learn and test, eval = test a saved model, predict = decode one file.

def side_path(model_path: str, kind: str) -> str:
    return str(Path(model_path).with_name(f"{Path(model_path).stem}_{kind}.pt"))


# train: pick train and test files -> train both models -> save -> print the tables.
def cmd_train(a):
    recs = find_recordings(a.root, None if a.settle < 0 else a.settle)
    train = [r for r in recs if matches(r, a.train)]
    test = [r for r in recs if (matches(r, a.test) if a.test else r not in train)]
    if not train:
        raise SystemExit(f"No training recordings match '{a.train}'")
    print(f"{len(recs)} recordings. Train: {len(train)} files, test: {len(test)} files.")
    X, y, t = build_dataset(train)
    print(f"Training set: {len(y)} bits ({int(y.sum())} ones)")
    models = {k: train_model(k, X, y, t, a.epochs, a.lr, a.batch, a.seed) for k in ("linear", "cnn")}
    CnnDecoder(models["cnn"], "cnn").save(a.model)
    CnnDecoder(models["linear"], "linear").save(side_path(a.model, "linear"))
    print(f"Saved {a.model}")
    if test:
        run_eval(test, models)

# eval: load saved models -> test them on the chosen files.
def cmd_eval(a):
    models = {}
    for kind in ("linear", "cnn"):
        path = a.model if kind == "cnn" else side_path(a.model, kind)
        if Path(path).exists():
            models[kind] = CnnDecoder.load(path).model
    if not models:
        raise SystemExit(f"No saved model at {a.model}")
    recs = [r for r in find_recordings(a.root, None if a.settle < 0 else a.settle) if matches(r, a.test)]
    print(f"Evaluating on {len(recs)} recordings matching '{a.test or 'all'}'")
    run_eval(recs, models)

# predict: load a model -> decode one recording -> show the result next to the Arduino's.
def cmd_predict(a):
    rec = load_recording(a.npz)
    if rec is None:
        raise SystemExit("Could not read this file (expected a capture under experiments/results/<case>/...)")
    bits = CnnDecoder.load(a.model).decode(rec)
    s = lambda v: "".join(map(str, v))
    print("CNN:     ", s(bits), f"({sum(x != y for x, y in zip(rec.sent, bits))} wrong)")
    print("Hardware:", s(rec.received), f"({int((rec.received != rec.sent).sum())} wrong)")
    print("Sent:    ", s(rec.sent))
    if rec.code in CODES:
        print(f"Decoded message ({rec.code}):", s(CODES[rec.code].decode(bits)))

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--root", default=".")
        p.add_argument("--settle", type=float, default=150, help="only recordings with this settle ms (-1 = all)")
        p.add_argument("--model", default=DEFAULT_MODEL)

    t = sub.add_parser("train", help="train the CNN and the linear baseline, then print the comparison tables")
    common(t)
    t.add_argument("--train", default="material=wood,acrylic;noise=none", help="filter for training files")
    t.add_argument("--test", default="", help="filter for test files (default: every file not used for training)")
    t.add_argument("--epochs", type=int, default=60)
    t.add_argument("--lr", type=float, default=2e-3)
    t.add_argument("--batch", type=int, default=128)
    t.add_argument("--seed", type=int, default=0)
    t.set_defaults(fn=cmd_train)

    e = sub.add_parser("eval", help="evaluate saved models")
    common(e)
    e.add_argument("--test", default="")
    e.set_defaults(fn=cmd_eval)

    p = sub.add_parser("predict", help="decode one raw capture")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--npz", required=True)
    p.set_defaults(fn=cmd_predict)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
