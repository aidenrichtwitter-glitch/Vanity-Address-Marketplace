#!/usr/bin/env python3
"""Build standalone executable using PyInstaller.

Run this on the target machine (e.g. Windows with your GPU):
    pip install pyinstaller pyopencl pynacl base58 click
    python build.py

Output: dist/solvanity.exe (Windows) or dist/solvanity (Linux)
"""
import os
import platform
import subprocess
import sys


def build():
    sep = ";" if platform.system() == "Windows" else ":"
    add_data = f"core/opencl/kernel.cl{sep}core/opencl"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--console",
        "--name", "solvanity",
        "--add-data", add_data,
        "--hidden-import", "pyopencl",
        "--hidden-import", "nacl",
        "--hidden-import", "nacl.signing",
        "--hidden-import", "nacl.bindings",
        "--hidden-import", "base58",
        "--hidden-import", "click",
        "--collect-all", "pyopencl",
        "main.py",
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
    print()
    print("  Usage:")
    print(f"    {exe_path} search-words")
    print(f"    {exe_path} search-words --min-word-length 5")
    print(f"    {exe_path} search-words --count 10")
    print(f"    {exe_path} show-device")
    print(f"    {exe_path} list-words")
    print("=" * 60)


if __name__ == "__main__":
    build()
