"""
Run one test case: a fixed material, distance and noise source, through every code.

From the project folder (close the Arduino Serial Monitor first):
    python3 -m experiments.run_case PORT --material wood --distance 20 --settle 50 --window 50 --live

A case runs these blocks, and saves each string to experiments/results/<case>.csv:
    prbs5      PRBS-5, repeated (uncoded), to characterise the noise
    codes      random 32-bit messages, each sent through every code in a shuffled order
    reference  PRBS-5 once more, to compare with the start and check for drift

With --prbs-per-code the case is just the codes block, and every code sends
the same PRBS-5 string as its message. The "none" code is then the uncoded
baseline, so there is no separate PRBS-5 block or reference.

The raw piezo samples for every string are saved too, in
experiments/results/<case>_raw/<block>_<index>_<code>.npz (see save_raw for what
each file holds). Use --no-raw to skip them, and keep the choice the same for
every run, as streaming them takes a few ms per bit out of the settle time.

Re-run the same command to carry on after a stop. Finished strings are skipped.
Use --prbs-only for a quick look at a setting, and --sim to try this with no hardware.
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
from experiments.sequences import map_key, prbs, random_message, shown
from experiments.summarise import print_summary

RESULTS_DIR = Path(__file__).parent / "results"
RECALIBRATE_REST_S = 1.0  # Lets the motor stop first, so it doesn't count as noise

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
                prbs_only: bool, codes: List[str], prbs_per_code: bool = False) -> List[Trial]:
    """List the strings to send, in order. The same case always gets the same order."""
    if prbs_per_code:
        trials = []
        for repeat in range(sets):
            # Shuffled so that slow drift can't favour whichever code goes last
            names = list(codes)
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
        random.Random(f"{case}:{seed}").shuffle(names)
        for name in names:
            trials.append(Trial("codes", seed, name, str(seed), random_message(seed, message_bits)))

    trials.append(Trial("reference", 0, "none", "", prbs(5)))
    return trials


def planned(args, case: str) -> List[Trial]:
    return plan_trials(case, args.prbs_repeats, args.sets, args.message_bits,
                       args.prbs_only, args.codes, args.prbs_per_code)


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


def run_case(link, args, case: str, path: Path, fixed: dict,
             events: Optional[queue.Queue] = None,
             stop: Optional[threading.Event] = None) -> bool:
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
    link.set_window_ms(args.window)  # This also calibrates
    print("Threshold:", link.threshold)

    # The Arduino link doesn't keep these, but the raw files need them
    link.settle_ms, link.window_ms = args.settle, args.window
    raw_dir = None if args.no_raw else path.parent / f"{case}_raw"

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
        for number, trial in enumerate(remaining, 1):
            if stop is not None and stop.is_set():
                return False

            # One threshold per block, so a block's strings are all judged alike
            if previous_block not in (None, "codes") and trial.block == "codes":
                time.sleep(RECALIBRATE_REST_S)
                link.calibrate()
                print("Threshold:", link.threshold)
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

    return True


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
    parser.add_argument("port", nargs="?", help="serial port (not needed with --sim)")
    parser.add_argument("--material", required=True, help="surface, e.g. wood")
    parser.add_argument("--distance", required=True, type=float, help="motor to piezo, in cm")
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
    parser.add_argument("--live", action="store_true", help="show the live viewer")
    parser.add_argument("--no-raw", action="store_true", help="don't record the raw piezo samples")
    parser.add_argument("--sim", action="store_true", help="use a simulated channel")

    args = parser.parse_args()
    if not args.sim and not args.port:
        parser.error("give a serial port, or --sim")
    if args.prbs_per_code and args.prbs_only:
        parser.error("--prbs-per-code can't be used with --prbs-only")
    if args.prbs_only and not args.prbs_repeats:
        parser.error("--prbs-only needs at least one PRBS-5 string to send")
    return args


def main():
    args = parse_args()
    source = "sim" if args.sim else "hardware"
    case = case_name(args, source)

    # Kept apart so that simulated strings can't end up in the real results
    folder = RESULTS_DIR / "sim" if args.sim else RESULTS_DIR
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
        print("Connecting, keep the surface still...")
        with connect() as link:
            run_case(link, args, case, path, fixed)
        print_summary([path])
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
    for event in saved_events(load_done(path), path.parent / f"{case}_raw"):
        events.put(event)

    def work():
        try:
            events.put(("status", "Connecting and calibrating, keep the surface still"))
            with connect() as link:
                outcome["finished"] = run_case(link, args, case, path, fixed, events, stop)
            events.put(("done", "Finished" if outcome["finished"] else "Stopped"))
        except Exception as error:
            outcome["error"] = error
            events.put(("done", f"Failed: {error}"))

    worker = threading.Thread(target=work, daemon=True)
    view = LiveView(events, case, layout, stop, path.with_suffix(".png"), raw=not args.no_raw)
    worker.start()
    view.show()

    stop.set()
    worker.join(timeout=1)

    if outcome["error"] is not None:
        raise outcome["error"]
    if not outcome["finished"]:
        print("Stopped early. Run the same command again to carry on.")
    if path.exists():
        print_summary([path])


if __name__ == "__main__":
    main()
