from typing import List


def viterbi_encoder(bits) -> list[int]:
    
    s1, s2 = 0, 0  # s1 = previous input bit, s2 = the one before that
    encoded = []

    for b in list(bits) + [0, 0]:
        encoded.append(b ^ s1 ^ s2)  # generator 7 (111)
        encoded.append(b ^ s2)       # generator 5 (101)
        s1, s2 = b, s1

    return encoded

def main():
    inputs = [1, 0, 1, 1, 0, 0, 1, 0]

    encoded = viterbi_encoder(inputs)

    print(encoded)


if __name__ == "__main__":
    main()