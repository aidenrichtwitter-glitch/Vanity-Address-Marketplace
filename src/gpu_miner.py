import os
import time
import struct
import hashlib
from multiprocessing import Process, Queue

import base58

GPU_AVAILABLE = False
try:
    import pyopencl as cl
    GPU_AVAILABLE = True
except (ImportError, Exception):
    pass


ED25519_OPENCL_KERNEL = r"""
// Minimal Ed25519 point operations for OpenCL
// This generates random 32-byte seeds, hashes them with SHA-512,
// and performs the Ed25519 scalar*basepoint multiplication to get
// the public key, then we check suffix/prefix in Base58.

// SHA-512 constants
__constant ulong K512[80] = {
    0x428a2f98d728ae22UL, 0x7137449123ef65cdUL, 0xb5c0fbcfec4d3b2fUL, 0xe9b5dba58189dbbcUL,
    0x3956c25bf348b538UL, 0x59f111f1b605d019UL, 0x923f82a4af194f9bUL, 0xab1c5ed5da6d8118UL,
    0xd807aa98a3030242UL, 0x12835b0145706fbeUL, 0x243185be4ee4b28cUL, 0x550c7dc3d5ffb4e2UL,
    0x72be5d74f27b896fUL, 0x80deb1fe3b1696b1UL, 0x9bdc06a725c71235UL, 0xc19bf174cf692694UL,
    0xe49b69c19ef14ad2UL, 0xefbe4786384f25e3UL, 0x0fc19dc68b8cd5b5UL, 0x240ca1cc77ac9c65UL,
    0x2de92c6f592b0275UL, 0x4a7484aa6ea6e483UL, 0x5cb0a9dcbd41fbd4UL, 0x76f988da831153b5UL,
    0x983e5152ee66dfabUL, 0xa831c66d2db43210UL, 0xb00327c898fb213fUL, 0xbf597fc7beef0ee4UL,
    0xc6e00bf33da88fc2UL, 0xd5a79147930aa725UL, 0x06ca6351e003826fUL, 0x142929670a0e6e70UL,
    0x27b70a8546d22ffcUL, 0x2e1b21385c26c926UL, 0x4d2c6dfc5ac42aedUL, 0x53380d139d95b3dfUL,
    0x650a73548baf63deUL, 0x766a0abb3c77b2a8UL, 0x81c2c92e47edaee6UL, 0x92722c851482353bUL,
    0xa2bfe8a14cf10364UL, 0xa81a664bbc423001UL, 0xc24b8b70d0f89791UL, 0xc76c51a30654be30UL,
    0xd192e819d6ef5218UL, 0xd69906245565a910UL, 0xf40e35855771202aUL, 0x106aa07032bbd1b8UL,
    0x19a4c116b8d2d0c8UL, 0x1e376c085141ab53UL, 0x2748774cdf8eeb99UL, 0x34b0bcb5e19b48a8UL,
    0x391c0cb3c5c95a63UL, 0x4ed8aa4ae3418acbUL, 0x5b9cca4f7763e373UL, 0x682e6ff3d6b2b8a3UL,
    0x748f82ee5defb2fcUL, 0x78a5636f43172f60UL, 0x84c87814a1f0ab72UL, 0x8cc702081a6439ecUL,
    0x90befffa23631e28UL, 0xa4506cebde82bde9UL, 0xbef9a3f7b2c67915UL, 0xc67178f2e372532bUL,
    0xca273eceea26619cUL, 0xd186b8c721c0c207UL, 0xeada7dd6cde0eb1eUL, 0xf57d4f7fee6ed178UL,
    0x06f067aa72176fbaUL, 0x0a637dc5a2c898a6UL, 0x113f9804bef90daeUL, 0x1b710b35131c471bUL,
    0x28db77f523047d84UL, 0x32caab7b40c72493UL, 0x3c9ebe0a15c9bebcUL, 0x431d67c49c100d4cUL,
    0x4cc5d4becb3e42b6UL, 0x597f299cfc657e2aUL, 0x5fcb6fab3ad6faecUL, 0x6c44198c4a475817UL
};

__constant uchar BASE58_ALPHABET[58] = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";

// We use a simplified approach: generate seeds on GPU, output seeds + match flags
// The CPU side will do full Ed25519 key derivation for matched seeds
// GPU does fast prefix/suffix checks on simplified address representation

typedef struct {
    uchar seed[32];
    uchar match;
} result_t;

// Simple xorshift128+ PRNG
ulong xorshift128plus(__private ulong *s0, __private ulong *s1) {
    ulong x = *s0;
    ulong y = *s1;
    *s0 = y;
    x ^= (x << 23);
    x ^= (x >> 17);
    x ^= y ^ (y >> 26);
    *s1 = x;
    return x + y;
}

__kernel void generate_seeds(
    __global result_t *results,
    __global const uchar *suffix,
    const uint suffix_len,
    __global const uchar *prefix,
    const uint prefix_len,
    const ulong seed_base_hi,
    const ulong seed_base_lo,
    const uint batch_offset
) {
    uint gid = get_global_id(0);

    ulong s0 = seed_base_hi ^ ((ulong)gid * 6364136223846793005UL + 1442695040888963407UL);
    ulong s1 = seed_base_lo ^ ((ulong)(gid + batch_offset) * 2862933555777941757UL + 3037000493UL);

    // Mix state
    for (int i = 0; i < 4; i++) {
        xorshift128plus(&s0, &s1);
    }

    // Generate 32-byte random seed
    for (int i = 0; i < 4; i++) {
        ulong r = xorshift128plus(&s0, &s1);
        results[gid].seed[i*8+0] = (uchar)(r);
        results[gid].seed[i*8+1] = (uchar)(r >> 8);
        results[gid].seed[i*8+2] = (uchar)(r >> 16);
        results[gid].seed[i*8+3] = (uchar)(r >> 24);
        results[gid].seed[i*8+4] = (uchar)(r >> 32);
        results[gid].seed[i*8+5] = (uchar)(r >> 40);
        results[gid].seed[i*8+6] = (uchar)(r >> 48);
        results[gid].seed[i*8+7] = (uchar)(r >> 56);
    }

    // Mark all as potential match - CPU will do full Ed25519 derivation and filtering
    // In a full implementation, the GPU would do Ed25519 scalar mult and Base58
    // encoding, but that's extremely complex in OpenCL. Instead, we use the GPU
    // as a high-throughput random seed generator and batch the Ed25519 work to CPU.
    results[gid].match = 1;
}
"""


class GPUMiner:
    def __init__(self, device_index=0, batch_size=65536):
        self.batch_size = batch_size
        self.device_index = device_index
        self.ctx = None
        self.queue = None
        self.program = None
        self.initialized = False

    def initialize(self):
        if not GPU_AVAILABLE:
            raise RuntimeError("PyOpenCL not available")

        platforms = cl.get_platforms()
        if not platforms:
            raise RuntimeError("No OpenCL platforms found")

        devices = []
        for platform in platforms:
            devices.extend(platform.get_devices(cl.device_type.GPU))

        if not devices:
            for platform in platforms:
                devices.extend(platform.get_devices(cl.device_type.ALL))

        if not devices:
            raise RuntimeError("No OpenCL devices found")

        if self.device_index >= len(devices):
            raise RuntimeError(f"Device index {self.device_index} out of range (found {len(devices)} devices)")

        device = devices[self.device_index]
        self.ctx = cl.Context([device])
        self.queue = cl.CommandQueue(self.ctx)
        self.program = cl.Program(self.ctx, ED25519_OPENCL_KERNEL).build()
        self.initialized = True

        return device.name

    def generate_batch(self, suffix=b"", prefix=b"", batch_offset=0):
        if not self.initialized:
            self.initialize()

        import numpy as np

        result_dtype = np.dtype([("seed", np.uint8, 32), ("match", np.uint8)])
        results = np.zeros(self.batch_size, dtype=result_dtype)

        results_buf = cl.Buffer(
            self.ctx,
            cl.mem_flags.WRITE_ONLY,
            results.nbytes,
        )

        suffix_buf = cl.Buffer(
            self.ctx,
            cl.mem_flags.READ_ONLY | cl.mem_flags.COPY_HOST_PTR,
            hostbuf=suffix if suffix else b"\x00",
        )
        prefix_buf = cl.Buffer(
            self.ctx,
            cl.mem_flags.READ_ONLY | cl.mem_flags.COPY_HOST_PTR,
            hostbuf=prefix if prefix else b"\x00",
        )

        seed_hi = struct.unpack("Q", os.urandom(8))[0]
        seed_lo = struct.unpack("Q", os.urandom(8))[0]

        self.program.generate_seeds(
            self.queue,
            (self.batch_size,),
            None,
            results_buf,
            suffix_buf,
            np.uint32(len(suffix)),
            prefix_buf,
            np.uint32(len(prefix)),
            np.uint64(seed_hi),
            np.uint64(seed_lo),
            np.uint32(batch_offset),
        )

        cl.enqueue_copy(self.queue, results, results_buf)
        self.queue.finish()

        seeds = []
        for i in range(self.batch_size):
            if results[i]["match"]:
                seeds.append(bytes(results[i]["seed"]))

        return seeds


class CPUBatchGenerator:
    def __init__(self, batch_size=4096):
        self.batch_size = batch_size

    def generate_batch(self):
        seeds = []
        for _ in range(self.batch_size):
            seeds.append(os.urandom(32))
        return seeds
