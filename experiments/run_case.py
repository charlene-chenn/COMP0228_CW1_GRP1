"""
Run one test case: a fixed material, distance and noise source, through every code.

From the project folder (close the Arduino Serial Monitor first):
    python3 -m experiments.run_case PORT --material wood --distance 20 --settle 50 --window 50 --live

A case runs these blocks, and saves each string to experiments/results/<case>/<case>.csv:
    prbs5      PRBS-5, repeated (uncoded), to characterise the noise
    codes      random 32-bit messages, each sent through every code in a shuffled order
    reference  PRBS-5 once more, to compare with the start and check for drift

With --prbs-per-code the case is just the codes block, and every code sends
the same PRBS-5 string as its message. The "none" code is then the uncoded
baseline, so there is no separate PRBS-5 block or reference.

Everything from a case goes in its own folder, experiments/results/<case>/:
    <case>.csv   one row per string
    <case>.png   the live viewer at the end (with --live)
    raw/<block>_<index>_<code>.npz   the raw piezo samples of each string (see save_raw) Use --no-raw to skip them, and keep the choice the same for
every run, as streaming them takes a few ms per bit out of the settle time.

When a case finishes, a video of its raw signal is made too, <case>.mp4 in the
same folder (see experiments/make_video.py). Use --no-video to skip it.

Re-run the same command to carry on after a stop. Finished strings are skipped.
Use --prbs-only for a quick look at a setting, and --sim to try this with no hardware.

Receiver extensions (experiments/extensions.py) decide the bits again from the
raw samples, and save their results to <case>_<extension>.csv:
    --extension filter              also run the filtering extension during the case
    --replay --extension filter     only run the extension, on every saved case
    --replay <case>.csv ... --extension filter     only on these cases
    --extension cnn                 the trained network instead (--extension filter cnn for both)
--replay sends nothing and needs no port, material or distance. With --live, each
extension gets its own window too, updated as each string finishes.

The filter's pass band is set once for each material, from its run 1, and saved in
experiments/filter_bands.json. Every run of that material uses it from then on:
    --set-band <run 1>.csv ...      set the band for each run's material
"""
import argparse
import csv
import queue
import random
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from channel.sim_channel import SimulatedLink
from codes import CODES
from experiments import extensions
from experiments.sequences import map_key, prbs, random_message, shown
from experiments.summarise import print_summary

RESULTS_DIR = Path(__file__).parent / "results"
RECALIBRATE_REST_S = 1.0  # Lets the motor stop first, so it doesn't count as noise
CALIBRATION_S = 3         # Must match CALIBRATION_MS in piezo_receiver_v3.ino

FIELDS = [
    "timestamp", "case", "source", "material", "distance_cm", "noise", "run", "notes",
    "settle_ms", "window_ms", "threshold", "git", "block", "index", "code", "seed",
    "sent", "received", "vibration", "decoded", "message",
    "channel_bits", "channel_errors", "zero_to_one", "one_to_zero",
    "info_bits", "info_errors", "elapsed_s", "late_bits", "raw_file",
]


@dataclass
class Trial:
    block: str
    index: int
    code: str
    seed: str
    message: List[int]

    @property
    def key(self) -> Tuple[str, str, str]:
        return self.block, str(self.index), self.code


def case_name(args, source: str) -> str:
    """Name the case after everything that was fixed for it."""
    message = "Pprbs5" if args.prbs_per_code else f"M{args.message_bits}"
    name = (
        f"{args.material}_{args.distance:g}cm_{args.noise}"
        f"_S{args.settle}_W{args.window}_{message}_run{args.run}"
    )
    name = re.sub(r"[^A-Za-z0-9_.-]+", "-", name)
    return f"sim_{name}" if source == "sim" else name


def plan_trials(case: str, prbs_repeats: int, sets: int, message_bits: int,
                prbs_only: bool, codes: List[str], prbs_per_code: bool = False,
                fixed_order: bool = False) -> List[Trial]:
    """
    List the strings to send, in order. The same case always gets the same order.
    With fixed_order, the codes go in the order given (e.g. for a demo) instead of shuffled.
    """
    if prbs_per_code:
        trials = []
        for repeat in range(sets):
            # Shuffled so that slow drift can't favour whichever code goes last
            names = list(codes)
            if not fixed_order:
                random.Random(f"{case}:{repeat}").shuffle(names)
            for name in names:
                trials.append(Trial("codes", repeat, name, "prbs5", prbs(5)))
        return trials

    trials = [Trial("prbs5", i, "none", "", prbs(5)) for i in range(prbs_repeats)]

    if prbs_only:
        return trials

    for seed in range(sets):
        # Shuffled so that slow drift can't favour whichever code goes last
        names = list(codes)
        if not fixed_order:
            random.Random(f"{case}:{seed}").shuffle(names)
        for name in names:
            trials.append(Trial("codes", seed, name, str(seed), random_message(seed, message_bits)))

    trials.append(Trial("reference", 0, "none", "", prbs(5)))
    return trials


def planned(args, case: str) -> List[Trial]:
    return plan_trials(case, args.prbs_repeats, args.sets, args.message_bits,
                       args.prbs_only, args.codes, args.prbs_per_code, args.fixed_order)


def load_done(path: Path) -> Dict[Tuple[str, str, str], dict]:
    """Read the strings a previous run of this case already finished."""
    if not path.exists():
        return {}
    with open(path, newline="") as file:
        return {(r["block"], r["index"], r["code"]): r for r in csv.DictReader(file)}


def git_hash() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def bit_text(bits) -> str:
    return "".join(str(bit) for bit in bits)


def raw_name(trial: Trial) -> str:
    return f"{trial.block}_{trial.index}_{trial.code}.npz"


def save_raw(path: Path, link, sent, received, vibration) -> None:
    """
    Save the raw piezo samples of one string, as recorded in link.last_raw.

    The file holds:
        samples        every sample, all bits joined together (uint16 ADC counts)
        bit_start      where each bit starts in samples, plus the end (length bits + 1)
        switch_offset  samples into each bit at which the motor was switched
        sent, received, vibration   the same per-bit values as the CSV
        threshold, sample_rate, settle_ms, window_ms, late_bits

    Bit i is samples[bit_start[i]:bit_start[i + 1]]. The measuring window is
    settle_ms to settle_ms + window_ms from the start of each bit. Consecutive bits
    join up unless late_bits > 0, in which case some bits have a gap after them.
    """
    lengths = [len(r) for r in link.last_raw]
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path,
        samples=np.concatenate(link.last_raw).astype(np.uint16),
        bit_start=np.concatenate([[0], np.cumsum(lengths)]).astype(np.int64),
        switch_offset=np.array(link.last_offsets, dtype=np.int64),
        sent=np.array(sent, dtype=np.int8),
        received=np.array(received, dtype=np.int8),
        vibration=np.array(vibration, dtype=np.int64),
        threshold=link.threshold,
        sample_rate=link.sample_rate,
        settle_ms=getattr(link, "settle_ms", -1),
        window_ms=getattr(link, "window_ms", -1),
        late_bits=link.last_late if link.last_late is not None else -1,
    )


def run_trial(link, trial: Trial, on_bit=None, raw_dir: Optional[Path] = None) -> dict:
    """Send one string through its code and work out the errors."""
    code = CODES[trial.code]
    coded = code.encode(trial.message)

    start = time.perf_counter()
    received, vibration = link.send_and_receive(coded, on_bit)
    elapsed = time.perf_counter() - start

    decoded = code.decode(received)[:len(trial.message)]

    # Saved before the CSV row, so a string is only marked done once its samples are kept
    raw_file = ""
    if raw_dir is not None and getattr(link, "last_raw", None) is not None:
        save_raw(raw_dir / raw_name(trial), link, coded, received, vibration)
        raw_file = f"{raw_dir.name}/{raw_name(trial)}"

    return {
        "block": trial.block,
        "index": trial.index,
        "code": trial.code,
        "seed": trial.seed,
        "threshold": link.threshold,
        "sent": bit_text(coded),
        "received": bit_text(received),
        "vibration": " ".join(str(v) for v in vibration),
        "decoded": bit_text(decoded),
        "message": bit_text(trial.message),
        "channel_bits": len(coded),
        "channel_errors": sum(a != b for a, b in zip(coded, received)),
        "zero_to_one": sum(a == 0 and b == 1 for a, b in zip(coded, received)),
        "one_to_zero": sum(a == 1 and b == 0 for a, b in zip(coded, received)),
        "info_bits": len(trial.message),
        "info_errors": sum(a != b for a, b in zip(trial.message, decoded)),
        "elapsed_s": round(elapsed, 3),
        "late_bits": "" if getattr(link, "last_late", None) is None else link.last_late,
        "raw_file": raw_file,
    }


def announce(message: str, events: Optional[queue.Queue] = None, beep: bool = False) -> None:
    """Tell the person running the case, in the terminal and in the live viewer."""
    print(("\a" if beep else "") + message, flush=True)
    if events is not None:
        events.put(("status", message))


def calibrate(link, events, set_window: Optional[int] = None) -> None:
    """Calibrate (by setting the window, or directly), saying when it starts and ends."""
    announce(f">>> Calibrating: keep the surface still ({CALIBRATION_S} s)", events)
    if set_window is not None:
        link.set_window_ms(set_window)  # This also calibrates
    else:
        link.calibrate()
    announce(f">>> Calibration complete, threshold {link.threshold}", events, beep=True)


def countdown(seconds: int, events) -> None:
    """Count down before the first bit, so a disturbance can be started in time."""
    for left in range(seconds, 0, -1):
        announce(f">>> Starting in {left}...", events)
        time.sleep(1)
    announce(">>> Sending now", events, beep=True)


def run_case(link, args, case: str, path: Path, fixed: dict,
             events: Optional[queue.Queue] = None,
             stop: Optional[threading.Event] = None,
             ext_events: Optional[Dict[str, queue.Queue]] = None) -> bool:
    """
    Send every string in the case that isn't already saved.

    Args:
        link: an ArduinoLink or SimulatedLink.
        args: the command-line arguments.
        case (str): the case name.
        path (Path): the CSV file to add to.
        fixed (dict): the columns that are the same for every string in the case.
        events (queue.Queue, optional): where to send updates for the live viewer.
        stop (threading.Event, optional): set to stop after the current string.
        ext_events (dict, optional): a queue for each extension's live window.

    Returns:
        bool: True if the whole case has now been sent.
    """
    trials = planned(args, case)
    check_header(path)
    done = load_done(path)
    remaining = [t for t in trials if t.key not in done]

    if done:
        print(f"Resuming: {len(done)} strings already saved, {len(remaining)} to go")
    if not remaining:
        return True

    link.set_settle_ms(args.settle)
    calibrate(link, events, set_window=args.window)

    # The Arduino link doesn't keep these, but the raw files need them
    link.settle_ms, link.window_ms = args.settle, args.window
    raw_dir = None if args.no_raw else path.parent / "raw"

    if events is not None:
        events.put(("config", args.settle, args.window, getattr(link, "sample_rate", 0)))

    # A run stopped during its first string can leave an empty file behind
    is_new = not path.exists() or path.stat().st_size == 0
    with open(path, "a", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        if is_new:
            writer.writeheader()
            file.flush()

        previous_block = None
        countdown(args.countdown, events)
        for number, trial in enumerate(remaining, 1):
            if stop is not None and stop.is_set():
                return False

            # One threshold per block, so a block's strings are all judged alike
            if previous_block not in (None, "codes") and trial.block == "codes":
                time.sleep(RECALIBRATE_REST_S)
                calibrate(link, events)
                countdown(args.countdown, events)
            previous_block = trial.block

            on_bit = None
            viewed = events is not None and shown(trial.block, trial.seed)
            if viewed:
                coded = CODES[trial.code].encode(trial.message)
                row = (trial.block, trial.index, trial.code)
                events.put(("trial", map_key(trial.block, len(coded)), row, coded, link.threshold))
                on_bit = lambda i, bit, vib, raw: events.put(("bit", i, bit, vib, raw))
            elif events is not None:
                events.put(("status", f"Codes: set {trial.index + 1} of {args.sets}, {trial.code}"))

            result = run_trial(link, trial, on_bit, raw_dir)

            if viewed and trial.block == "codes":
                decoded = [int(bit) for bit in result["decoded"]]
                events.put(("decoded", row, trial.message, decoded))

            writer.writerow({
                **fixed,
                **result,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
            })
            file.flush()

            print(
                f"[{number}/{len(remaining)}] {trial.block:<9} {trial.index:>2} {trial.code:<10} "
                f"channel errors {result['channel_errors']}/{result['channel_bits']}, "
                f"message errors {result['info_errors']}/{result['info_bits']}"
            )
            print_extensions(link, args, trial, result, ext_events)

    return True


def extension_options(args, name: str) -> dict:
    """An extension's settings from the command line."""
    if name == "cnn":
        return {"model": args.cnn_model}
    options = {
        "kind": args.filter_kind, "smooth_hz": args.filter_smooth,
        "notch_hz": args.filter_notch, "sharpen_tau_ms": args.filter_sharpen,
    }
    if args.filter_band == ["material"]:
        options["band_from_material"] = True
    elif args.filter_band == ["auto"]:
        options["auto_band"] = True
    else:
        options["lo"], options["hi"] = (float(value) for value in args.filter_band)
    return options


def print_extensions(link, args, trial: Trial, result: dict,
                     ext_events: Optional[Dict[str, queue.Queue]] = None) -> None:
    """
    Under each string's line, how every extension did on the same string. With
    --live, also send the extension's decisions to its own window.
    """
    for name in args.extension:
        sent = [int(bit) for bit in result["sent"]]
        outcome = extensions.string_result(link, trial.code, sent, trial.message,
                                           name, extension_options(args, name), args.material)
        if outcome is None:
            print(f"{'':>8}{name}: no usable raw samples")
            continue
        print(f"{'':>8}{name + ':':<31}channel errors {outcome['channel_errors']}/"
              f"{result['channel_bits']}, message errors {outcome['info_errors']}/"
              f"{result['info_bits']}")

        view = (ext_events or {}).get(name)
        if view is None or not shown(trial.block, trial.seed):
            continue
        row = (trial.block, trial.index, trial.code)
        view.put(("trial", map_key(trial.block, len(sent)), row, sent, round(outcome["threshold"])))
        for i, (bit, level) in enumerate(zip(outcome["received"], outcome["levels"])):
            view.put(("bit", i, int(bit), round(level), None))
        if trial.block == "codes":
            view.put(("decoded", row, trial.message, outcome["decoded"]))


def check_bands(args) -> None:
    """Stop before sending anything if the filter has no band for this material."""
    if "filter" in args.extension and args.filter_band == ["material"]:
        try:
            extensions.material_band(args.material)
        except KeyError as error:
            raise SystemExit(f"Can't use --extension filter: {error.args[0]}") from None


def check_cnn(args) -> None:
    """Stop before doing anything if the network can't run (no PyTorch or no model)."""
    if "cnn" in args.extension:
        try:
            extensions.load_cnn(args.cnn_model)
        except (RuntimeError, FileNotFoundError) as error:
            raise SystemExit(f"Can't use --extension cnn: {error}") from None


def save_extensions(args, path: Path) -> List[Path]:
    """
    Write <case>_<extension>.csv for each extension, from everything saved so far,
    and its picture <case>_<extension>.png (the same view as the case's own).
    """
    from experiments.live_view import view_saved

    written = []
    for name in args.extension:
        out = extensions.replay(path, name, extension_options(args, name))
        if out is not None:
            written.append(out)
            print("Saved", view_saved(out, show=False))
    return written


def replay_main(args) -> None:
    """--replay: run the extensions on saved cases, without sending anything."""
    paths = [Path(p) for p in args.replay] or extensions.saved_cases()
    if not paths:
        print("No saved cases.")
        return
    written = []
    for path in paths:
        if not extensions.is_case_csv(path):
            print(f"Skipping {path}: give the case's own CSV, not an extension's results")
            continue
        written += save_extensions(args, path)
    if written:
        print_summary(written)


def check_header(path: Path) -> None:
    """Refuse to add to a CSV written with different columns, which would misalign them."""
    if not path.exists() or path.stat().st_size == 0:
        return
    with open(path, newline="") as file:
        header = next(csv.reader(file), [])
    if header != FIELDS:
        raise SystemExit(
            f"{path} was written by an older version of run_case with different "
            "columns. Move it to archive/ and run the case again."
        )


def parse_args():
    parser = argparse.ArgumentParser(description="Run one test case through every code.")
    parser.add_argument("port", nargs="?", help="serial port (not needed with --sim or --replay)")
    parser.add_argument("--material", help="surface, e.g. wood (required unless --replay)")
    parser.add_argument("--distance", type=float,
                        help="motor to piezo, in cm (required unless --replay)")
    parser.add_argument("--noise", default="none", help="physical noise source, e.g. fan")
    parser.add_argument("--settle", type=int, default=100, help="settle time in ms")
    parser.add_argument("--window", type=int, default=100, help="measuring window in ms")
    parser.add_argument("--run", type=int, default=1, help="repeat number, e.g. after re-mounting")
    parser.add_argument("--notes", default="", help="anything else worth recording")
    parser.add_argument("--prbs-repeats", type=int, default=10, help="uncoded PRBS-5 strings")
    parser.add_argument("--sets", type=int, default=20, help="messages sent through every code")
    parser.add_argument("--message-bits", type=int, default=32, help="bits in each message")
    parser.add_argument("--codes", nargs="+", choices=list(CODES), default=list(CODES),
                        help="codes to run, all of them by default")
    parser.add_argument("--prbs-only", action="store_true", help="skip the codes and reference")
    parser.add_argument("--prbs-per-code", action="store_true",
                        help="send PRBS-5 through every code, --sets times, and nothing else")
    parser.add_argument("--fixed-order", action="store_true",
                        help="send the codes in the order given by --codes, not shuffled (for a demo)")
    parser.add_argument("--live", action="store_true", help="show the live viewer")
    parser.add_argument("--no-raw", action="store_true", help="don't record the raw piezo samples")
    parser.add_argument("--countdown", type=int, default=3,
                        help="seconds to count down after calibrating, before sending (0 for none)")
    parser.add_argument("--no-video", action="store_true",
                        help="don't make a video of the raw signal when the case finishes")
    parser.add_argument("--sim", action="store_true", help="use a simulated channel")

    ext = parser.add_argument_group("receiver extensions (see experiments/extensions.py)")
    ext.add_argument("--extension", nargs="+", default=[], choices=list(extensions.EXTENSIONS),
                     help="also decide the bits with these extensions, from the raw samples")
    ext.add_argument("--replay", nargs="*", metavar="CSV",
                     help="send nothing: only run --extension on these saved case CSVs "
                          "(every saved case if none are given)")
    ext.add_argument("--set-band", nargs="+", metavar="CSV",
                     help="send nothing: set the filter's band for each run's material from "
                          "that run (give each material's run 1), saved in "
                          "experiments/filter_bands.json")
    ext.add_argument("--filter-band", nargs="+", default=["material"], metavar="HZ",
                     help="filter pass band: 'material' (default) uses the band saved for the "
                          "run's material (see --set-band); 'auto' finds the motor's peak in "
                          "each string by itself; or give LO HI in Hz")
    ext.add_argument("--filter-kind", default="butter", choices=["butter", "bessel", "cheby1"],
                     help="filter type (default butter)")
    ext.add_argument("--filter-smooth", type=float, default=30.0, metavar="HZ",
                     help="envelope low-pass (default 30)")
    ext.add_argument("--filter-notch", type=float, metavar="HZ", help="extra notch, e.g. 50")
    ext.add_argument("--filter-sharpen", type=float, metavar="TAU_MS",
                     help="undo the motor's spin-down with this time constant, e.g. 40")
    ext.add_argument("--cnn-model", default=extensions.CNN_DEFAULTS["model"], metavar="PT",
                     help="trained network for --extension cnn, relative to the project folder "
                          f"(default {extensions.CNN_DEFAULTS['model']})")

    args = parser.parse_args()
    if args.filter_band not in (["material"], ["auto"]):
        try:
            lo, hi = (float(value) for value in args.filter_band)
        except ValueError:
            parser.error("--filter-band takes 'material', 'auto', or LO HI in Hz")
        if not 0 < lo < hi:
            parser.error("--filter-band needs 0 < LO < HI")
    if args.set_band is not None:
        return args
    if args.replay is not None:
        if not args.extension:
            parser.error("--replay needs --extension, e.g. --extension filter")
        return args
    if args.material is None or args.distance is None:
        parser.error("--material and --distance are required (unless --replay)")
    if args.extension and args.no_raw:
        parser.error("--extension needs the raw samples, so it can't be used with --no-raw")
    if not args.sim and not args.port:
        parser.error("give a serial port, or --sim")
    if args.prbs_per_code and args.prbs_only:
        parser.error("--prbs-per-code can't be used with --prbs-only")
    if args.prbs_only and not args.prbs_repeats:
        parser.error("--prbs-only needs at least one PRBS-5 string to send")
    return args


def finish(args, path: Path) -> None:
    """Make the raw signal video for a finished case."""
    if args.no_raw or args.no_video:
        return
    from experiments.make_video import make_video
    try:
        print("Saved", make_video(path))
    except (SystemExit, RuntimeError) as error:
        # The results are already saved, so a missing ffmpeg shouldn't look like a failed run
        print(f"No video made: {error}")


def main():
    args = parse_args()
    if args.set_band is not None:
        for csv_path in args.set_band:
            band = extensions.set_band(Path(csv_path))
            print(f"{Path(csv_path).stem}: drive frequency {band['drive_hz']:.1f} Hz, "
                  f"band {band['lo']:.1f}-{band['hi']:.1f} Hz saved for every run of this material")
        return
    check_cnn(args)
    if args.replay is not None:
        replay_main(args)
        return
    check_bands(args)
    source = "sim" if args.sim else "hardware"
    case = case_name(args, source)

    # Kept apart so that simulated strings can't end up in the real results
    # Each case gets its own folder holding its CSV, picture and raw samples
    folder = (RESULTS_DIR / "sim" if args.sim else RESULTS_DIR) / case
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{case}.csv"

    fixed = {
        "case": case, "source": source, "material": args.material,
        "distance_cm": f"{args.distance:g}", "noise": args.noise, "run": args.run,
        "notes": args.notes, "settle_ms": args.settle, "window_ms": args.window,
        "git": git_hash(),
    }

    print("Case:", case)

    def connect():
        if args.sim:
            return SimulatedLink(bit_s=0.01, raw=not args.no_raw)
        from channel.hardware import ArduinoLink
        return ArduinoLink(args.port, raw=not args.no_raw)

    if not args.live:
        print("Connecting (up to about 10 s), keep the surface still...")
        with connect() as link:
            finished = run_case(link, args, case, path, fixed)
        print_summary([path, *save_extensions(args, path)])
        if finished:
            finish(args, path)
        return

    # The viewer has to stay on the main thread, so the case runs on another
    from experiments.live_view import LiveView, map_layout, saved_events

    events = queue.Queue()
    stop = threading.Event()
    outcome = {"finished": False, "error": None}

    layout = map_layout(
        (t.block, t.index, t.code, len(CODES[t.code].encode(t.message)), len(t.message))
        for t in planned(args, case) if shown(t.block, t.seed)
    )

    check_header(path)
    for event in saved_events(load_done(path), path.parent / "raw"):
        events.put(event)

    # A window for each extension, showing its decisions as each string finishes.
    # Strings saved before a resume come from its results file, if there is one.
    ext_events = {name: queue.Queue() for name in args.extension}
    ext_views = []
    for name, ext_queue in ext_events.items():
        ext_path = extensions.extension_path(path, name)
        if ext_path.exists():
            for event in saved_events(load_done(ext_path)):
                ext_queue.put(event)
        ext_views.append(LiveView(
            ext_queue, f"{case}_{name}", layout,
            level_label="Filtered level (ADC counts)" if name == "filter" else f"{name} level",
            window_title=f"{name} extension live view",
        ))

    def work():
        try:
            events.put(("status", "Connecting and calibrating, keep the surface still"))
            with connect() as link:
                outcome["finished"] = run_case(link, args, case, path, fixed, events, stop,
                                               ext_events)
            message = "Finished" if outcome["finished"] else "Stopped"
        except Exception as error:
            outcome["error"] = error
            message = f"Failed: {error}"
        for ext_queue in [events, *ext_events.values()]:
            ext_queue.put(("done", message))

    worker = threading.Thread(target=work, daemon=True)
    view = LiveView(events, case, layout, stop, path.with_suffix(".png"), raw=not args.no_raw)
    for ext_view in ext_views:
        ext_view.start()
    worker.start()
    view.show()

    stop.set()
    worker.join(timeout=1)

    if outcome["error"] is not None:
        raise outcome["error"]
    if not outcome["finished"]:
        print("Stopped early. Run the same command again to carry on.")
    if path.exists():
        print_summary([path, *save_extensions(args, path)])
    if outcome["finished"]:
        finish(args, path)


if __name__ == "__main__":
    main()
