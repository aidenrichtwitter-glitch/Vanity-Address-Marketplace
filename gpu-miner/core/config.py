import secrets
from math import ceil

DEFAULT_ITERATION_BITS = 20
DEFAULT_LOCAL_WORK_SIZE = 64


class HostSetting:
    def __init__(self, kernel_source: str, iteration_bits: int):
        if iteration_bits < 0 or iteration_bits > 255:
            raise ValueError("iteration_bits must be between 0 and 255")
        self.iteration_bits = iteration_bits
        # iteration_bytes 为需要被迭代覆盖的字节数（向上取整）
        self.iteration_bytes = int(ceil(iteration_bits / 8))
        self.global_work_size = 1 << iteration_bits
        self.local_work_size = DEFAULT_LOCAL_WORK_SIZE
        self.kernel_source = kernel_source
        self.key32 = self.generate_key32()

    def generate_key32(self) -> bytearray:
        token_bytes = secrets.token_bytes(
            32 - int(self.iteration_bytes)
        ) + b"\x00" * int(self.iteration_bytes)
        return bytearray(token_bytes)

    def increase_key32(self) -> None:
        ib = int(self.iteration_bytes)
        if ib == 0:
            return
        start = 32 - ib
        increment = (1 << self.iteration_bits)
        inc_bytes = (self.iteration_bits // 8) + 1
        loop_start = max(32 - inc_bytes, start - 1)
        carry = 0
        for i in range(31, loop_start - 1, -1):
            shift = (31 - i) * 8
            add_val = (increment >> shift) & 0xFF
            val = self.key32[i] + add_val + carry
            self.key32[i] = val & 0xFF
            carry = val >> 8
        if carry and loop_start > 0:
            self.key32[loop_start - 1] = (self.key32[loop_start - 1] + carry) & 0xFF
