#!/usr/bin/env python3
import sys
from src.config import parse_args
from src.words import get_valid_words, BASE58_CHARS
from src.miner import VanityMiner


def validate_base58(text, label):
    for ch in text:
        if ch not in BASE58_CHARS:
            print(f"Error: '{ch}' in {label} is not a valid Base58 character.")
            print(f"Valid Base58 chars: 123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")
            sys.exit(1)


def main():
    args = parse_args()

    if args.list_words:
        words = get_valid_words()
        if args.min_word_length > 0:
            words = [w for w in words if len(w) >= args.min_word_length]
        if args.max_word_length > 0:
            words = [w for w in words if len(w) <= args.max_word_length]
        print(f"Valid cool words ({len(words)} total):")
        print("-" * 60)
        col_width = max(len(w) for w in words) + 2
        cols = 80 // col_width
        for i in range(0, len(words), cols):
            row = words[i : i + cols]
            print("".join(w.ljust(col_width) for w in row))
        sys.exit(0)

    if args.suffix:
        validate_base58(args.suffix, "suffix")
    if args.prefix:
        validate_base58(args.prefix, "prefix")

    miner = VanityMiner(args)
    miner.run()


if __name__ == "__main__":
    main()
