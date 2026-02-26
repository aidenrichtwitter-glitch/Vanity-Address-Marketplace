import logging
import platform
import sys
from pathlib import Path
from typing import Tuple

import pyopencl as cl
from base58 import b58decode


def check_character(name: str, character: str) -> None:
    try:
        b58decode(character)
    except ValueError as e:
        logging.error(f"{str(e)} in {name}")
        raise SystemExit(1)
    except Exception as e:
        raise e


def build_suffix_buffer(ends_with_list: Tuple[str, ...]) -> Tuple[bytearray, int, int]:
    if not ends_with_list:
        return bytearray(1), 0, 0

    suffixes = [list(suffix.encode()) for suffix in ends_with_list]
    max_suffix_len = max((len(s) for s in suffixes), default=0)
    for s in suffixes:
        s.extend([0] * (max_suffix_len - len(s)))

    suffix_count = len(suffixes)
    suffix_width = max_suffix_len

    buf = bytearray(suffix_count * suffix_width)
    for i, s in enumerate(suffixes):
        for j, b in enumerate(s):
            buf[i * suffix_width + j] = b

    return buf, suffix_count, suffix_width


def load_kernel_source(
    starts_with_list: Tuple[str, ...], is_case_sensitive: bool,
    suffix_bytes: int = 0,
) -> str:
    prefixes = (
        [list(prefix.encode()) for prefix in starts_with_list]
        if starts_with_list
        else [[]]
    )

    max_prefix_len = max((len(p) for p in prefixes), default=0)

    for p in prefixes:
        p.extend([0] * (max_prefix_len - len(p)))

    base_path = Path(getattr(sys, '_MEIPASS', Path(__file__).parent.parent.parent))
    kernel_path = base_path / "core" / "opencl" / "kernel.cl"
    if not kernel_path.exists():
        kernel_path = Path(__file__).parent.parent / "opencl" / "kernel.cl"
    if not kernel_path.exists():
        raise FileNotFoundError("Kernel source file not found.")
    with kernel_path.open("r") as f:
        source_lines = f.readlines()

    for i, line in enumerate(source_lines):
        if line.startswith("#define N "):
            source_lines[i] = f"#define N {len(prefixes)}\n"
        elif line.startswith("#define L "):
            source_lines[i] = f"#define L {max_prefix_len}\n"
        elif line.startswith("constant uchar PREFIXES"):
            prefixes_str = "{"
            for prefix in prefixes:
                prefixes_str += "{" + ", ".join(map(str, prefix)) + "}, "
            prefixes_str = prefixes_str.rstrip(", ") + "}"
            source_lines[i] = f"constant uchar PREFIXES[N][L] = {prefixes_str};\n"
        elif line.startswith("constant bool CASE_SENSITIVE"):
            source_lines[i] = (
                f"constant bool CASE_SENSITIVE = {str(is_case_sensitive).lower()};\n"
            )
        elif line.startswith("#define SUFFIX_BYTES"):
            source_lines[i] = f"#define SUFFIX_BYTES {suffix_bytes}\n"

    source_str = "".join(source_lines)
    if "NVIDIA" in str(cl.get_platforms()) and platform.system() == "Windows":
        source_str = source_str.replace("#define __generic\n", "")
    if cl.get_cl_header_version()[0] != 1 and platform.system() != "Windows":
        source_str = source_str.replace("#define __generic\n", "")
    return source_str
