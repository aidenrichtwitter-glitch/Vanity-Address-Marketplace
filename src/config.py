import argparse
import os


def parse_args():
    parser = argparse.ArgumentParser(
        description="SolVanity - GPU-accelerated Solana vanity address miner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --suffix abc
  python main.py --suffix XYZ --min-word-length 4
  python main.py --suffix dead --case-sensitive --threads 8
  python main.py --suffix abc --gpu-only
  python main.py --list-words
        """,
    )

    parser.add_argument(
        "--suffix",
        type=str,
        default="",
        help="Required suffix for addresses (case-sensitive, Base58 chars only)",
    )
    parser.add_argument(
        "--prefix",
        type=str,
        default="",
        help="Required prefix for addresses (after the leading '1')",
    )
    parser.add_argument(
        "--case-sensitive",
        action="store_true",
        default=True,
        help="Case-sensitive suffix/prefix matching (default: True)",
    )
    parser.add_argument(
        "--no-case-sensitive",
        action="store_false",
        dest="case_sensitive",
        help="Case-insensitive suffix/prefix matching",
    )
    parser.add_argument(
        "--min-word-length",
        type=int,
        default=3,
        help="Minimum word length to search for (default: 3)",
    )
    parser.add_argument(
        "--max-word-length",
        type=int,
        default=0,
        help="Maximum word length to search for (0 = no limit)",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=os.cpu_count() or 4,
        help="Number of CPU threads for word checking (default: all cores)",
    )
    parser.add_argument(
        "--gpu-batch-size",
        type=int,
        default=65536,
        help="Number of keys to generate per GPU batch (default: 65536)",
    )
    parser.add_argument(
        "--gpu-device",
        type=int,
        default=0,
        help="GPU device index to use (default: 0)",
    )
    parser.add_argument(
        "--gpu-only",
        action="store_true",
        help="Skip CPU word filtering, only check suffix/prefix",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="found_addresses.txt",
        help="Output file for found addresses (default: found_addresses.txt)",
    )
    parser.add_argument(
        "--list-words",
        action="store_true",
        help="List all valid cool words and exit",
    )
    parser.add_argument(
        "--custom-words",
        type=str,
        default="",
        help="Comma-separated list of custom words to search for",
    )
    parser.add_argument(
        "--no-gpu",
        action="store_true",
        help="Force CPU-only mode (no OpenCL)",
    )

    return parser.parse_args()
