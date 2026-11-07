"""
Print the error and transmission rates for saved test cases:
    python3 -m experiments.summarise                         # every real case
    python3 -m experiments.summarise experiments/results/wood_20cm_none_S50_W50_run1.csv

The confidence intervals treat bits as independent. Bursts break that assumption,
so treat the intervals as too narrow if the PRBS results show bursts.
"""
import csv
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Tuple

from experiments.sequences import prbs_name

RESULTS_DIR = Path(__file__).parent / "results"


def wilson(errors: int, total: int, z: float = 1.96) -> Tuple[float, float]:
    """
    95% Wilson confidence interval for an error rate.

    Args:
        errors (int): number of wrong bits.
        total (int): number of bits.
        z (float, optional): the z-score for the interval. Defaults to 1.96.

    Returns:
        Tuple[float, float]: the lower and upper limits, as fractions.
    """
    if total == 0:
        return 0.0, 1.0

    p = errors / total
    centre = (p + z * z / (2 * total)) / (1 + z * z / total)
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)

    # Exactly 0 or 1 when there are no errors or no correct bits
    low = 0.0 if errors == 0 else max(0.0, centre - half)
    high = 1.0 if errors == total else min(1.0, centre + half)
    return low, high


def rate_text(errors: int, total: int) -> str:
    low, high = wilson(errors, total)
    rate = errors / total if total else 0.0
    return f"{rate:7.2%} [{low:.2%}, {high:.2%}]"


def print_prbs(rows) -> None:
    by_length = defaultdict(list)
    for row in rows:
        if row["block"] not in ("codes", "reference"):
            by_length[int(row["channel_bits"])].append(row)

    for length, group in by_length.items():
        bits = sum(int(r["channel_bits"]) for r in group)
        errors = sum(int(r["channel_errors"]) for r in group)
        false_ones = sum(int(r["zero_to_one"]) for r in group)
        misses = sum(int(r["one_to_zero"]) for r in group)
        print(f"  {prbs_name(length)} x{len(group)}: {rate_text(errors, bits)} of {bits} bits "
              f"(sent 0 read 1: {false_ones}, sent 1 read 0: {misses})")

    # The start and end of a case are only comparable over the same sequence
    for row in (r for r in rows if r["block"] == "reference"):
        length = int(row["channel_bits"])
        name = prbs_name(length)
        if by_length[length]:
            first = by_length[length][0]
            print(f"  Drift check, first {name}: "
                  f"{rate_text(int(first['channel_errors']), length)}")
        print(f"  Drift check, last {name}:  "
              f"{rate_text(int(row['channel_errors']), length)}")


def print_codes(rows) -> None:
    by_code = defaultdict(list)
    for row in rows:
        if row["block"] == "codes":
            by_code[row["code"]].append(row)

    if not by_code:
        return

    print(f"  {'code':<10} {'msgs':>4} {'rate':>5} {'channel errors':>25} "
          f"{'message errors':>25} {'msgs wrong':>10} {'goodput bit/s':>13}")

    for code, group in by_code.items():
        channel_bits = sum(int(r["channel_bits"]) for r in group)
        channel_errors = sum(int(r["channel_errors"]) for r in group)
        info_bits = sum(int(r["info_bits"]) for r in group)
        info_errors = sum(int(r["info_errors"]) for r in group)
        wrong = sum(int(r["info_errors"]) > 0 for r in group)
        elapsed = sum(float(r["elapsed_s"]) for r in group)
        goodput = (info_bits - info_errors) / elapsed if elapsed else 0.0

        print(f"  {code:<10} {len(group):>4} {info_bits / channel_bits:>5.2f} "
              f"{rate_text(channel_errors, channel_bits):>25} "
              f"{rate_text(info_errors, info_bits):>25} "
              f"{wrong:>10} {goodput:>13.2f}")


def print_summary(paths: Iterable[Path]) -> None:
    for path in paths:
        with open(path, newline="") as file:
            rows = list(csv.DictReader(file))

        if not rows:
            continue

        print(f"\n{rows[0]['case']}")
        print_prbs(rows)
        print_codes(rows)


def main():
    paths = [Path(arg) for arg in sys.argv[1:]] or sorted(RESULTS_DIR.glob("*.csv"))
    if not paths:
        print("No results yet.")
        return
    print_summary(paths)


if __name__ == "__main__":
    main()
