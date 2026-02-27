#!/usr/bin/env python3
"""Build standalone executable using PyInstaller.

Run this on the target machine (e.g. Windows with your GPU):
    pip install pyinstaller pyopencl pynacl base58 click PySide6 solders solana lit-python-sdk
    python build.py

Output: dist/solvanity.exe (Windows) or dist/solvanity (Linux)
"""
import os
import platform
import subprocess
import sys


def build():
    sep = ";" if platform.system() == "Windows" else ":"
    add_data_kernel = f"core/opencl/kernel.cl{sep}core/opencl"
    add_data_wordlist = f"wordlist_3000.txt{sep}."
    add_data_lit_action = f"core/marketplace/lit_action.js{sep}core/marketplace"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", "solvanity",
        "--add-data", add_data_kernel,
        "--add-data", add_data_wordlist,
        "--add-data", add_data_lit_action,
        "--hidden-import", "cffi",
        "--hidden-import", "_cffi_backend",
        "--hidden-import", "pyopencl",
        "--hidden-import", "nacl",
        "--hidden-import", "nacl.signing",
        "--hidden-import", "nacl.bindings",
        "--hidden-import", "nacl.bindings.crypto_aead",
        "--hidden-import", "nacl.bindings.crypto_box",
        "--hidden-import", "nacl.bindings.crypto_generichash",
        "--hidden-import", "nacl.bindings.crypto_hash",
        "--hidden-import", "nacl.bindings.crypto_pwhash",
        "--hidden-import", "nacl.bindings.crypto_scalarmult",
        "--hidden-import", "nacl.bindings.crypto_secretbox",
        "--hidden-import", "nacl.bindings.crypto_secretstream",
        "--hidden-import", "nacl.bindings.crypto_shorthash",
        "--hidden-import", "nacl.bindings.crypto_sign",
        "--hidden-import", "nacl.bindings.randombytes",
        "--hidden-import", "nacl.bindings.utils",
        "--hidden-import", "base58",
        "--hidden-import", "click",
        "--hidden-import", "pynvml",
        "--hidden-import", "solders",
        "--hidden-import", "solana",
        "--hidden-import", "solana.rpc",
        "--hidden-import", "solana.rpc.api",
        "--hidden-import", "lit_python_sdk",
        "--collect-all", "pyopencl",
        "--collect-all", "nacl",
        "--collect-all", "cffi",
        "--collect-all", "PySide6",
        "--collect-all", "solders",
        "--collect-all", "solana",
        "gui.py",
    ]
    print("=" * 60)
    print("  SolVanity Word Miner - Build")
    print("=" * 60)
    print()
    print(f"  Platform:  {platform.system()} {platform.machine()}")
    print(f"  Python:    {sys.version.split()[0]}")
    print()
    print("Building executable...")
    print()
    subprocess.run(cmd, check=True)

    exe_name = "solvanity.exe" if platform.system() == "Windows" else "solvanity"
    exe_path = os.path.join("dist", exe_name)
    print()
    print("=" * 60)
    print(f"  Build complete!")
    print(f"  Executable: {exe_path}")
    print("=" * 60)


if __name__ == "__main__":
    build()
