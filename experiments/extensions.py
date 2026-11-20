"""
Receiver extensions: other ways of turning a string's raw piezo samples into bits.

The Arduino decides each bit by peak-to-peak against its calibrated threshold.
An extension decides again from the saved raw samples, and the string's code
decodes those bits as usual, so one hardware run gives results for the plain
receiver and every extension. Results go next to the case's CSV, with the same
columns, as experiments/results/<case>/<case>_<extension>.csv.

    filter   band-pass, envelope and a threshold (codes/filtering.py)
    cnn      a trained 1D CNN that decides each bit from the envelope around it
             (codes/cnn_decoder.py; needs PyTorch and a trained model in models/)

Run through run_case (see its --extension and --replay options):
    python3 -m experiments.run_case PORT --material wood --distance 15 ... --extension filter
    python3 -m experiments.run_case --replay --extension filter              # every saved case
    python3 -m experiments.run_case --replay --extension cnn                 # the network instead
    python3 -m experiments.run_case --replay --extension filter cnn          # both
    python3 -m experiments.run_case --replay experiments/results/<case>/<case>.csv --extension filter

The filter's pass band is set once per material, from its run 1, and saved in
experiments/filter_bands.json:
    python3 -m experiments.run_case --set-band experiments/results/<run 1>/<run 1>.csv

The cnn extension's results note "in CNN training set" on strings the model was
trained on, as those results aren't a fair test. To train the model:
    python3 -m codes.cnn_decoder train

To add an extension, write a function like filter_bits and add it to EXTENSIONS.
"""
import csv
import json
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from codes import CODES

RESULTS_DIR = Path(__file__).parent / "results"
PROJECT_DIR = Path(__file__).resolve().parent.parent

# The filter's pass band for each material, set once from a run 1 (see set_band)
BANDS_FILE = Path(__file__).parent / "filter_bands.json"

# The filtering extension's settings. Apart from the band, the same defaults as
# codes/filtering.py. band_from_material takes the band for the run's material
# from BANDS_FILE; auto_band sets it on each string by itself instead.
FILTER_DEFAULTS = {
    "lo": 70.0, "hi": 105.0, "auto_band": False, "band_from_material": False,
    "material": None, "kind": "butter", "order": 4,
    "smooth_hz": 30.0, "notch_hz": None, "sharpen_tau_ms": None, "threshold": None,
}

# The network extension's settings. model is relative to the project folder.
# train_spec is what the saved model was trained on (cnn_decoder train's default);
# it is only used to flag the strings the model has already seen.
CNN_DEFAULTS = {
    "model": "models/cnn_decoder.pt",
    "train_spec": "material=wood,acrylic;noise=none",
}
CNN_IN_TRAINING = "in CNN training set"


def band_from_run(case_csv: Path) -> Tuple[float, float]:
    """
    A pass band from one saved run: filtering.find_motor_band (the strongest peak in
    the spectrum, plus or minus 15 Hz) on every raw sample of every string in the run,
    joined together. One string alone is too short: on PCB its strongest peak is
    sometimes not the motor's drive frequency. Returns (lo, hi) in Hz.
    """
    from codes.filtering import find_motor_band

    case_csv = Path(case_csv)
    with open(case_csv, newline="") as file:
        rows = [row for row in csv.DictReader(file) if row.get("raw_file")]
    pieces, rate = [], None
    for row in rows:
        raw = case_csv.parent / row["raw_file"]
        if raw.exists():
            data = np.load(raw)
            samples = data["samples"].astype(float)
            pieces.append(samples - samples.mean())
            rate = int(data["sample_rate"])
    if not pieces:
        raise FileNotFoundError(f"{case_csv.stem} has no raw samples")
    return find_motor_band(np.concatenate(pieces), rate)


def load_bands() -> Dict[str, dict]:
    """The saved band for each material, e.g. {"wood": {"lo": ..., "hi": ..., ...}}."""
    if not BANDS_FILE.exists():
        return {}
    return json.loads(BANDS_FILE.read_text())


def set_band(case_csv: Path) -> dict:
    """
    Set the band for a run's material from that run (use the material's run 1),
    and save it in BANDS_FILE. Returns the saved entry.
    """
    case_csv = Path(case_csv)
    with open(case_csv, newline="") as file:
        material = next(csv.DictReader(file))["material"]
    lo, hi = band_from_run(case_csv)
    bands = load_bands()
    bands[material] = {
        "lo": round(float(lo), 3), "hi": round(float(hi), 3),
        "drive_hz": round(float(lo + hi) / 2, 3), "set_from": case_csv.stem,
    }
    BANDS_FILE.write_text(json.dumps(bands, indent=2) + "\n")
    return bands[material]


def material_band(material: str) -> Tuple[float, float]:
    """The saved band for a material. Raises KeyError if it hasn't been set."""
    bands = load_bands()
    if material not in bands:
        raise KeyError(
            f"no filter band saved for '{material}'. Set it from that material's run 1 with "
            f"python3 -m experiments.run_case --set-band experiments/results/<run 1>/<run 1>.csv"
        )
    return bands[material]["lo"], bands[material]["hi"]


def case_material(case_csv: Path) -> str:
    with open(case_csv, newline="") as file:
        return next(csv.DictReader(file))["material"]


def resolve(name: str, options: dict, material: str) -> dict:
    """Fill in anything an extension's settings take from the run, e.g. its material's band."""
    if name == "filter" and options.get("band_from_material"):
        lo, hi = material_band(material)
        return {**options, "lo": lo, "hi": hi, "material": material}
    return options


def filter_bits(data, options: dict) -> Tuple[List[int], List[float], float]:
    """
    The filtering extension (codes/filtering.py): band-pass, envelope, mean level
    in each measuring window, then a threshold (the midpoint by default).
    data is the string's .npz from run_case.save_raw. Returns the bits, each bit's
    level and the threshold.
    """
    from codes.filtering import filter_and_detect, find_motor_band

    settings = {**FILTER_DEFAULTS, **options}
    rate = int(data["sample_rate"])
    samples = data["samples"].astype(float)
    bit_length = int(np.diff(data["bit_start"])[0])

    lo, hi = settings["lo"], settings["hi"]
    if settings["auto_band"]:
        lo, hi = find_motor_band(samples, rate)

    result = filter_and_detect(
        samples, rate, bit_ms=bit_length * 1000 / rate, n_bits=len(data["sent"]),
        lo=lo, hi=hi, settle_ms=float(data["settle_ms"]), notch_hz=settings["notch_hz"],
        threshold=settings["threshold"], kind=settings["kind"], order=settings["order"],
        smooth_hz=settings["smooth_hz"], sharpen_tau_ms=settings["sharpen_tau_ms"],
    )
    return result["bits"], list(result["levels"]), result["threshold"]


_cnn_models = {}


def load_cnn(model: str):
    """
    The trained network at model (relative to the project folder), loaded once.
    Raises RuntimeError if PyTorch isn't installed, FileNotFoundError if there's no model.
    """
    path = Path(model)
    path = path if path.is_absolute() else PROJECT_DIR / path
    if path not in _cnn_models:
        try:
            from codes.cnn_decoder import CnnDecoder
        except ImportError as error:
            raise RuntimeError("the cnn extension needs PyTorch: pip install -r requirements.txt") from error
        if not path.exists():
            raise FileNotFoundError(f"no trained model at {path}. Train one with: python3 -m codes.cnn_decoder train")
        _cnn_models[path] = CnnDecoder.load(str(path))
    return _cnn_models[path]


def cnn_bits(data, options: dict) -> Tuple[List[int], List[float], float]:
    """
    The network extension (codes/cnn_decoder.py): the envelope of each bit's slot and
    the 2 slots either side go into the trained CNN, which gives the probability that
    the bit is a 1. A bit is read as 1 when that is 0.5 or more.

    The levels are the probabilities x 1000, and the threshold 500, so they fit the
    same whole-number columns and plots as the other receivers. data needs switch_offset.
    """
    from codes.cnn_decoder import Recording

    settings = {**CNN_DEFAULTS, **options}
    decoder = load_cnn(settings["model"])
    n_bits = len(data["sent"])   # only the number of bits is used, never their values
    recording = Recording(
        path="", code="", meta={}, samples=np.asarray(data["samples"], dtype=np.float32),
        sent=np.zeros(n_bits, dtype=int), received=np.zeros(n_bits, dtype=int),
        bit_start=np.asarray(data["bit_start"], dtype=int),
        switch_offset=np.asarray(data["switch_offset"], dtype=int),
        fs=float(data["sample_rate"]), settle_ms=float(data["settle_ms"]),
    )
    probabilities = decoder.probabilities(recording)
    return [int(p >= 0.5) for p in probabilities], [float(p) * 1000 for p in probabilities], 500.0


def in_cnn_training(raw_path: Path, data, options: dict) -> bool:
    """Whether the network was trained on this string (same rules as cnn_decoder train)."""
    from types import SimpleNamespace
    from codes.cnn_decoder import matches, parse_meta

    meta = parse_meta(str(raw_path))
    if meta is None or float(data["settle_ms"]) != 150:
        return False
    return matches(SimpleNamespace(meta=meta), {**CNN_DEFAULTS, **options}["train_spec"])


EXTENSIONS = {
    "filter": filter_bits,
    "cnn": cnn_bits,
}


def describe(name: str, options: dict) -> str:
    """The settings an extension ran with, saved in the notes column of its results."""
    if name == "cnn":
        return f"cnn: model {({**CNN_DEFAULTS, **options})['model']}, read as 1 if P(1) >= 0.5"
    if name != "filter":
        return name
    s = {**FILTER_DEFAULTS, **options}
    band = f"{s['lo']:.1f}-{s['hi']:.1f} Hz"
    if s["auto_band"]:
        band = "auto on each string"
    elif s["band_from_material"]:
        band = f"{band} for {s['material']} (from {BANDS_FILE.name})"
    text = f"filter: band {band}, {s['kind']} order {s['order']}, smooth {s['smooth_hz']:g} Hz"
    if s["notch_hz"]:
        text += f", notch {s['notch_hz']:g} Hz"
    if s["sharpen_tau_ms"]:
        text += f", sharpen {s['sharpen_tau_ms']:g} ms"
    text += ", midpoint threshold" if s["threshold"] is None else f", threshold {s['threshold']:g}"
    return text


def extension_path(case_csv: Path, name: str) -> Path:
    """Where an extension's results for a case go: <case>_<name>.csv next to the case's CSV."""
    case_csv = Path(case_csv)
    return case_csv.with_name(f"{case_csv.stem}_{name}.csv")


def is_case_csv(path: Path) -> bool:
    """A case's own CSV is named after its folder. Extension results add a suffix."""
    return path.stem == path.parent.name


def saved_cases() -> List[Path]:
    """Every real case's own CSV (not simulated ones, and not extension results)."""
    return sorted(
        path for path in RESULTS_DIR.glob("*/*.csv")
        if path.parent.name != "sim" and is_case_csv(path)
    )


def can_use(data) -> Optional[str]:
    """Why an extension can't read a string's raw samples, or None if it can."""
    lengths = np.diff(data["bit_start"])
    if "switch_offset" in data and len(data["switch_offset"]) != len(data["sent"]):
        return "the raw file doesn't have every motor switch time"
    if len(lengths) != len(data["sent"]):
        return "the raw file doesn't have every bit"
    if int(data["late_bits"]) > 0 or len(set(lengths.tolist())) != 1:
        return "some bits were late, so the samples have gaps"
    return None


def extension_row(row: dict, case_csv: Path, name: str, options: dict) -> Optional[dict]:
    """
    Redo one saved string with an extension's decision in place of the Arduino's.
    Returns None if the string has no usable raw samples.
    """
    if not row.get("raw_file"):
        return None
    raw_path = Path(case_csv).parent / row["raw_file"]
    if not raw_path.exists():
        return None
    data = np.load(raw_path)
    if can_use(data) is not None:
        return None

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")   # e.g. scipy warning about a flat string
        received, levels, threshold = EXTENSIONS[name](data, options)

    sent = [int(bit) for bit in row["sent"]]
    message = [int(bit) for bit in row["message"]]
    decoded = CODES[row["code"]].decode(received)[:len(message)]

    trained = name == "cnn" and in_cnn_training(raw_path, data, options)
    return {
        **row,
        "case": f"{row['case']}+{name}",
        "notes": "; ".join(filter(None, [row.get("notes", ""), describe(name, options),
                                         CNN_IN_TRAINING if trained else ""])),
        "threshold": round(threshold),
        "received": "".join(str(bit) for bit in received),
        "vibration": " ".join(str(round(level)) for level in levels),
        "decoded": "".join(str(bit) for bit in decoded),
        "channel_errors": sum(a != b for a, b in zip(sent, received)),
        "zero_to_one": sum(a == 0 and b == 1 for a, b in zip(sent, received)),
        "one_to_zero": sum(a == 1 and b == 0 for a, b in zip(sent, received)),
        "info_errors": sum(a != b for a, b in zip(message, decoded)),
    }


def replay(case_csv: Path, name: str, options: dict, quiet: bool = False) -> Optional[Path]:
    """
    Run an extension over every saved string of a case and write <case>_<name>.csv.
    The file is rewritten from scratch each time, so it always matches the case CSV.
    Returns None if no string had usable raw samples.
    """
    case_csv = Path(case_csv)
    try:
        options = resolve(name, options, case_material(case_csv))
    except KeyError as error:
        if not quiet:
            print(f"{case_csv.stem}: no {name} results, {error}")
        return None
    with open(case_csv, newline="") as file:
        reader = csv.DictReader(file)
        fields = reader.fieldnames
        rows = list(reader)

    done, skipped = [], 0
    for row in rows:
        new = extension_row(row, case_csv, name, options)
        if new is None:
            skipped += 1
        else:
            done.append(new)

    if not done:
        if not quiet:
            print(f"{case_csv.stem}: no raw samples, so no {name} results")
        return None

    path = extension_path(case_csv, name)
    with open(path, "w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(done)

    if not quiet:
        before = sum(int(r["channel_errors"]) for r in rows if r.get("raw_file"))
        after = sum(int(r["channel_errors"]) for r in done)
        bits = sum(int(r["channel_bits"]) for r in done)
        note = f", {skipped} strings skipped (no usable raw samples)" if skipped else ""
        trained = sum(CNN_IN_TRAINING in r["notes"] for r in done)
        if trained:
            note += f", {trained} of {len(done)} strings were in the CNN's training set"
        print(f"{case_csv.stem}: channel errors {before} -> {after} of {bits} "
              f"({describe(name, options)}){note}")
    return path


def string_result(link, trial_code: str, sent: List[int], message: List[int],
                  name: str, options: dict, material: str) -> Optional[dict]:
    """
    The extension's decision on the string just sent, from the link's raw samples,
    for showing during a run. None if there are no usable raw samples or no band.
    """
    if getattr(link, "last_raw", None) is None or not link.last_raw:
        return None
    try:
        options = resolve(name, options, material)
    except KeyError:
        return None
    lengths = [len(r) for r in link.last_raw]
    data = {
        "samples": np.concatenate(link.last_raw),
        "bit_start": np.concatenate([[0], np.cumsum(lengths)]),
        "switch_offset": np.array(link.last_offsets or [], dtype=int),
        "sent": np.array(sent), "sample_rate": link.sample_rate,
        "settle_ms": link.settle_ms, "late_bits": link.last_late or 0,
    }
    if can_use(data) is not None:
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        received, levels, threshold = EXTENSIONS[name](data, options)
    decoded = CODES[trial_code].decode(received)[:len(message)]
    return {
        "received": received, "levels": levels, "threshold": threshold, "decoded": decoded,
        "channel_errors": sum(a != b for a, b in zip(sent, received)),
        "info_errors": sum(a != b for a, b in zip(message, decoded)),
    }
