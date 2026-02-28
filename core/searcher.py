import logging
import time
from typing import Dict, List, Optional, Tuple

import numpy as np
import pyopencl as cl

from core.config import HostSetting
from core.opencl.manager import (
    get_all_gpu_devices,
    get_selected_gpu_devices,
)


class Searcher:
    def __init__(
        self,
        kernel_source: str,
        index: int,
        setting: HostSetting,
        chosen_devices: Optional[Tuple[int, List[int]]] = None,
        suffix_buffer: bytearray = None,
        suffix_count: int = 0,
        suffix_width: int = 0,
        suffix_lengths: bytearray = None,
        tee_point: bytes = None,
    ):
        if chosen_devices is None:
            devices = get_all_gpu_devices()
        else:
            devices = get_selected_gpu_devices(*chosen_devices)
        enabled_device = devices[index]
        self.context = cl.Context([enabled_device])
        self.gpu_chunks = len(devices)
        self.command_queue = cl.CommandQueue(self.context)
        self.setting = setting
        self.index = index
        self.display_index = (
            index if chosen_devices is None else chosen_devices[1][index]
        )

        program = cl.Program(self.context, kernel_source).build()
        self.kernel = cl.Kernel(program, "generate_pubkey")
        self.memobj_key32 = cl.Buffer(
            self.context,
            cl.mem_flags.READ_ONLY | cl.mem_flags.COPY_HOST_PTR,
            len(self.setting.key32),
            hostbuf=self.setting.key32,
        )
        self.memobj_output = cl.Buffer(
            self.context, cl.mem_flags.READ_WRITE, 65
        )
        self.memobj_occupied_bytes = cl.Buffer(
            self.context,
            cl.mem_flags.READ_WRITE | cl.mem_flags.COPY_HOST_PTR,
            hostbuf=bytearray([self.setting.iteration_bytes]),
        )
        self.memobj_group_offset = cl.Buffer(
            self.context,
            cl.mem_flags.READ_WRITE | cl.mem_flags.COPY_HOST_PTR,
            hostbuf=bytearray([self.index]),
        )

        if suffix_buffer is None or len(suffix_buffer) == 0:
            suffix_buffer = bytearray(1)
        if suffix_lengths is None or len(suffix_lengths) == 0:
            suffix_lengths = bytearray(1)
        self.suffix_count = suffix_count
        self.suffix_width = suffix_width
        self.memobj_suffixes = cl.Buffer(
            self.context,
            cl.mem_flags.READ_ONLY | cl.mem_flags.COPY_HOST_PTR,
            len(suffix_buffer),
            hostbuf=suffix_buffer,
        )
        self.memobj_suffix_lengths = cl.Buffer(
            self.context,
            cl.mem_flags.READ_ONLY | cl.mem_flags.COPY_HOST_PTR,
            len(suffix_lengths),
            hostbuf=suffix_lengths,
        )

        tee_buf = bytearray(tee_point) if tee_point else bytearray(32)
        self.memobj_tee_point = cl.Buffer(
            self.context,
            cl.mem_flags.READ_ONLY | cl.mem_flags.COPY_HOST_PTR,
            32,
            hostbuf=tee_buf,
        )

        self.output = bytearray(65)
        self.kernel.set_arg(0, self.memobj_key32)
        self.kernel.set_arg(1, self.memobj_output)
        self.kernel.set_arg(2, self.memobj_occupied_bytes)
        self.kernel.set_arg(3, self.memobj_group_offset)
        self.kernel.set_arg(4, self.memobj_suffixes)
        self.kernel.set_arg(5, np.uint32(self.suffix_count))
        self.kernel.set_arg(6, np.uint32(self.suffix_width))
        self.kernel.set_arg(7, self.memobj_suffix_lengths)
        self.kernel.set_arg(8, self.memobj_tee_point)

    def find(self, log_stats: bool = True) -> bytearray:
        start_time = time.time()
        self.output[:] = bytearray(65)
        cl.enqueue_copy(self.command_queue, self.memobj_output, self.output)
        cl.enqueue_copy(self.command_queue, self.memobj_key32, self.setting.key32)
        global_work_size = self.setting.global_work_size // self.gpu_chunks
        local_size = self.setting.local_work_size
        global_size = ((global_work_size + local_size - 1) // local_size) * local_size
        cl.enqueue_nd_range_kernel(
            self.command_queue,
            self.kernel,
            (global_size,),
            (local_size,),
        )
        self.command_queue.flush()
        self.setting.increase_key32()
        cl.enqueue_copy(self.command_queue, self.output, self.memobj_output).wait()
        if log_stats:
            logging.info(
                f"GPU {self.display_index} Speed: {global_work_size / ((time.time() - start_time) * 1e6):.2f} MH/s"
            )
        return self.output


def multi_gpu_init(
    index: int,
    setting: HostSetting,
    gpu_counts: int,
    stop_flag,
    lock,
    chosen_devices: Optional[Tuple[int, List[int]]] = None,
    suffix_buffer: bytearray = None,
    suffix_count: int = 0,
    suffix_width: int = 0,
    suffix_lengths: bytearray = None,
    tee_point: bytes = None,
) -> List:
    try:
        searcher = Searcher(
            kernel_source=setting.kernel_source,
            index=index,
            setting=setting,
            chosen_devices=chosen_devices,
            suffix_buffer=suffix_buffer,
            suffix_count=suffix_count,
            suffix_width=suffix_width,
            suffix_lengths=suffix_lengths,
            tee_point=tee_point,
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


def _resolve_output_dir(
    pubkey: str,
    default_dir: str,
    starts_with: Tuple[str, ...],
    ends_with: Tuple[str, ...],
    pattern_dirs: Dict[str, str],
    is_case_sensitive: bool,
) -> str:
    if not pattern_dirs:
        return default_dir

    def _cmp(a: str, b: str) -> bool:
        if is_case_sensitive:
            return a == b
        return a.lower() == b.lower()

    for prefix in starts_with:
        key = f"prefix:{prefix}"
        if key in pattern_dirs and _cmp(pubkey[: len(prefix)], prefix):
            return pattern_dirs[key]

    for suffix in ends_with:
        key = f"suffix:{suffix}"
        if key in pattern_dirs and _cmp(pubkey[-len(suffix) :], suffix):
            return pattern_dirs[key]

    return default_dir


def save_result(
    outputs: List,
    output_dir: str,
    starts_with: Tuple[str, ...] = (),
    ends_with: Tuple[str, ...] = (),
    pattern_dirs: Optional[Dict[str, str]] = None,
    is_case_sensitive: bool = True,
) -> int:
    from core.utils.crypto import get_public_key_from_private_bytes, save_keypair

    result_count = 0
    for output in outputs:
        if not output[0]:
            continue
        result_count += 1
        pv_bytes = bytes(output[1:33])
        target_dir = output_dir
        if pattern_dirs:
            pubkey = get_public_key_from_private_bytes(pv_bytes)
            target_dir = _resolve_output_dir(
                pubkey, output_dir, starts_with, ends_with,
                pattern_dirs, is_case_sensitive,
            )
        save_keypair(pv_bytes, target_dir)
    return result_count
