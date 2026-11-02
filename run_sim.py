"""Send a message through every code and the simulated channel: python3 run_sim.py"""
from channel.sim_channel import flip_one_bit
from codes import CODES


def main():
    message = [1, 0, 1, 1, 0, 0, 1, 0]
    print("Message:", message)

    for code in CODES.values():
        coded = code.encode(message)
        received = flip_one_bit(coded)
        decoded = code.decode(received)[:len(message)]

        # Position of the bit the channel flipped
        flipped = [i for i in range(len(coded)) if coded[i] != received[i]][0]
        errors = sum(a != b for a, b in zip(message, decoded))

        print(
            f"{code.name:<10} sent {len(coded):>2} bits, "
            f"flipped bit {flipped:>2}, "
            f"decoded {decoded}, {errors} wrong"
        )


if __name__ == "__main__":
    main()
