import json
import logging
import multiprocessing
import os
import sys
import time
from multiprocessing.pool import Pool
from pathlib import Path
from typing import List, Optional, Tuple

from core.config import DEFAULT_ITERATION_BITS, HostSetting
from core.opencl.manager import get_all_gpu_devices, get_chosen_devices
from core.searcher import Searcher
from core.utils.crypto import get_public_key_from_private_bytes, save_keypair
from core.utils.helpers import load_kernel_source
from core.word_filter import WordFilter, PAD_CHAR, TAIL_SIZE

logging.basicConfig(level="INFO", format="[%(levelname)s %(asctime)s] %(message)s")


def build_suffix_patterns(word_filter):
    patterns = []
    for word in word_filter.words:
        wlen = len(word)
        if wlen >= TAIL_SIZE:
            patterns.append(word[:TAIL_SIZE])
        else:
            pad_needed = TAIL_SIZE - wlen
            pattern = (PAD_CHAR * pad_needed) + word
            patterns.append(pattern)
    return sorted(set(patterns))


def gpu_word_search(
    index,
    kernel_source,
    iteration_bits,
    gpu_counts,
    stop_flag,
    lock,
    chosen_devices,
):
    try:
        setting = HostSetting(kernel_source, iteration_bits)
        searcher = Searcher(
            kernel_source=kernel_source,
            index=index,
            setting=setting,
            chosen_devices=chosen_devices,
        )
        i = 0
        st = time.time()
        while True:
            result = searcher.find(i == 0)
            if result[0]:
                with lock:
                    if not stop_flag.value:
                        stop_flag.value = 1
                return list(result)
            if time.time() - st > max(gpu_counts, 1):
                i = 0
                st = time.time()
                with lock:
                    if stop_flag.value:
                        return list(result)
            else:
                i += 1
    except Exception as e:
        logging.exception(e)
    return [0]


def run_word_miner(
    min_word_length=4,
    max_word_length=0,
    custom_words=None,
    output_dir="./found_words",
    count=0,
    iteration_bits=DEFAULT_ITERATION_BITS,
    select_device=False,
):
    custom = None
    if custom_words:
        custom = [w.strip() for w in custom_words.split(",") if w.strip()]

    word_filter = WordFilter(
        min_length=min_word_length,
        max_length=max_word_length,
        custom_words=custom,
    )

    suffix_patterns = build_suffix_patterns(word_filter)

    print("=" * 64)
    print("  SolVanity Word Miner (SolVanityCL Fork)")
    print("  GPU-Accelerated Vanity Address Mining + Word Suffix Filter")
    print("=" * 64)
    print()
    print(f"  Words loaded:     {len(word_filter.words)}")
    print(f"  Suffix patterns:  {len(suffix_patterns)}")
    print(f"  Word length:      {min_word_length}-{max_word_length if max_word_length else '∞'}")
    print(f"  Tail format:      {'X' * max(0, TAIL_SIZE - min_word_length)}{'<word>'}")
    print(f"  Output dir:       {output_dir}")
    print(f"  Count:            {'unlimited' if count <= 0 else count}")
    print(f"  Iteration bits:   {iteration_bits}")
    print()

    if not suffix_patterns:
        logging.error("No valid suffix patterns generated. Check word list and length settings.")
        sys.exit(1)

    logging.info(f"Sample patterns: {', '.join(suffix_patterns[:10])}{'...' if len(suffix_patterns) > 10 else ''}")

    chosen_devices: Optional[Tuple[int, List[int]]] = None
    try:
        if select_device:
            chosen_devices = get_chosen_devices()
            gpu_counts = len(chosen_devices[1])
        else:
            gpu_counts = len(get_all_gpu_devices())
    except Exception as e:
        logging.error(f"OpenCL error: {e}")
        logging.error("No GPU/OpenCL platform found. This tool requires an OpenCL-capable GPU.")
        logging.error("Install GPU drivers and OpenCL runtime, then try again.")
        logging.error("Run 'python main.py show-device' to check available devices.")
        sys.exit(1)

    if gpu_counts == 0:
        logging.error("No GPU devices found. This tool requires an OpenCL-capable GPU.")
        logging.error("Make sure your GPU drivers and OpenCL runtime are installed.")
        logging.error("Run 'python main.py show-device' to check available devices.")
        sys.exit(1)

    logging.info(f"Using {gpu_counts} GPU device(s)")

    suffix_tuple = tuple(suffix_patterns)
    kernel_source = load_kernel_source((), suffix_tuple, True)

    logging.info("GPU kernel compiled with %d suffix patterns", len(suffix_patterns))
    logging.info("Mining started - press Ctrl+C to stop")
    print()

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    result_count = 0
    start_time = time.time()

    try:
        with multiprocessing.Manager() as manager:
            with Pool(processes=gpu_counts) as pool:
                while count <= 0 or result_count < count:
                    stop_flag = manager.Value("i", 0)
                    lock = manager.Lock()

                    results = pool.starmap(
                        gpu_word_search,
                        [
                            (
                                x,
                                kernel_source,
                                iteration_bits,
                                gpu_counts,
                                stop_flag,
                                lock,
                                chosen_devices,
                            )
                            for x in range(gpu_counts)
                        ],
                    )

                    for output in results:
                        if not output[0]:
                            continue
                        pv_bytes = bytes(output[1:])
                        pubkey = get_public_key_from_private_bytes(pv_bytes)

                        word, padding = word_filter.check_address(pubkey)
                        suffix_display = (padding + word) if word else pubkey[-TAIL_SIZE:]

                        save_keypair(pv_bytes, output_dir)
                        result_count += 1
                        elapsed = time.time() - start_time

                        print(f"  [{result_count}] {pubkey}")
                        print(f"       Suffix: {suffix_display}  |  Time: {elapsed:.1f}s")
                        print()

    except KeyboardInterrupt:
        print()
        logging.info("Shutting down...")

    elapsed = time.time() - start_time
    print()
    print("=" * 64)
    print(f"  Results:  {result_count} addresses found in {elapsed:.1f}s")
    print(f"  Saved to: {output_dir}/")
    print("=" * 64)
