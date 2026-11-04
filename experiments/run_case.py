"""
Run one test case: a fixed material, distance and noise source, through every code.

From the project folder (close the Arduino Serial Monitor first):
    python3 -m experiments.run_case PORT --material wood --distance 20 --settle 50 --window 50 --live

A case runs these blocks, and saves each string to experiments/results/<case>.csv:
    prbs       PRBS-9, repeated (uncoded), to characterise the noise
    codes      random messages, each sent through every code in a shuffled order
    reference  PRBS-9 once more, to compare with the start and check for drift

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

from channel.sim_channel import SimulatedLink
from codes import CODES
from experiments.sequences import prbs9, random_message
from experiments.summarise import print_summary

RESULTS_DIR = Path(__file__).parent / "results"
RECALIBRATE_REST_S = 1.0  # Lets the motor stop first, so it doesn't count as noise

FIELDS = [
    "timestamp", "case", "source", "material", "distance_cm", "noise", "run", "notes",
    "settle_ms", "window_ms", "threshold", "git", "block", "index", "code", "seed",
    "sent", "received", "vibration", "decoded", "message",
    "channel_bits", "channel_errors", "zero_to_one", "one_to_zero",
    "info_bits", "info_errors", "elapsed_s",
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
    name = (
        f"{args.material}_{args.distance:g}cm_{args.noise}"
        f"_S{args.settle}_W{args.window}_run{args.run}"
    )
    name = re.sub(r"[^A-Za-z0-9_.-]+", "-", name)
    return f"sim_{name}" if source == "sim" else name


def plan_trials(case: str, prbs_repeats: int, sets: int, prbs_only: bool) -> List[Trial]:
    """List the strings to send, in order. The same case always gets the same order."""
    trials = [Trial("prbs", i, "none", "", prbs9()) for i in range(prbs_repeats)]

    if prbs_only:
        return trials

    for seed in range(sets):
        # Shuffled so that slow drift can't favour whichever code goes last
        names = list(CODES)
        random.Random(f"{case}:{seed}").shuffle(names)
        for name in names:
            trials.append(Trial("codes", seed, name, str(seed), random_message(seed)))

    trials.append(Trial("reference", 0, "none", "", prbs9()))
    return trials


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


def run_trial(link, trial: Trial, on_bit=None) -> dict:
    """Send one string through its code and work out the errors."""
    code = CODES[trial.code]
    coded = code.encode(trial.message)

    start = time.perf_counter()
    received, vibration = link.send_and_receive(coded, on_bit)
    elapsed = time.perf_counter() - start

    decoded = code.decode(received)[:len(trial.message)]

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
    trials = plan_trials(case, args.prbs_repeats, args.sets, args.prbs_only)
    done = load_done(path)
    remaining = [t for t in trials if t.key not in done]

    if done:
        print(f"Resuming: {len(done)} strings already saved, {len(remaining)} to go")
    if not remaining:
        return True

    link.set_settle_ms(args.settle)
    link.set_window_ms(args.window)  # This also calibrates
    print("Threshold:", link.threshold)

    is_new = not path.exists()
    with open(path, "a", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        if is_new:
            writer.writeheader()

        previous_block = None
        for number, trial in enumerate(remaining, 1):
            if stop is not None and stop.is_set():
                return False

            # One threshold per block, so a block's strings are all judged alike
            if previous_block == "prbs" and trial.block == "codes":
                time.sleep(RECALIBRATE_REST_S)
                link.calibrate()
                print("Threshold:", link.threshold)
            previous_block = trial.block

            on_bit = None
            if events is not None and trial.block != "codes":
                row = args.prbs_repeats if trial.block == "reference" else trial.index
                events.put(("trial", row, trial.message, link.threshold))
                on_bit = lambda i, bit, vib: events.put(("bit", i, bit, vib))
            elif events is not None:
                events.put(("status", f"Codes: set {trial.index + 1} of {args.sets}, {trial.code}"))

            result = run_trial(link, trial, on_bit)

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
    parser.add_argument("--prbs-repeats", type=int, default=10, help="uncoded PRBS-9 strings")
    parser.add_argument("--sets", type=int, default=20, help="messages sent through every code")
    parser.add_argument("--prbs-only", action="store_true", help="skip the codes and reference")
    parser.add_argument("--live", action="store_true", help="show the live viewer")
    parser.add_argument("--sim", action="store_true", help="use a simulated channel")

    args = parser.parse_args()
    if not args.sim and not args.port:
        parser.error("give a serial port, or --sim")
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
            return SimulatedLink(bit_s=0.01)
        from channel.hardware import ArduinoLink
        return ArduinoLink(args.port)

    if not args.live:
        print("Connecting, keep the surface still...")
        with connect() as link:
            run_case(link, args, case, path, fixed)
        print_summary([path])
        return

    # The viewer has to stay on the main thread, so the case runs on another
    from experiments.live_view import LiveView, saved_events

    events = queue.Queue()
    stop = threading.Event()
    outcome = {"finished": False, "error": None}

    labels =[f"R{i + 1}" for i in range(args.prbs_repeats)]
    labels += [] if args.prbs_only else ["ref"]

    for event in saved_events(load_done(path), args.prbs_repeats):
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
    view = LiveView(events, case, labels, stop, path.with_suffix(".png"))
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
