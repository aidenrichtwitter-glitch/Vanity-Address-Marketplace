#!/usr/bin/env python3
"""Build standalone executable using PyInstaller."""
import subprocess
import sys


def build():
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", "solvanity",
        "--add-data", "core/opencl/kernel.cl:core/opencl",
        "--hidden-import", "pyopencl",
        "--hidden-import", "nacl",
        "--hidden-import", "nacl.signing",
        "--hidden-import", "base58",
        "--hidden-import", "click",
        "--collect-all", "pyopencl",
        "main.py",
    ]
    print("Building executable...")
    print(f"Command: {' '.join(cmd)}")
    print()
    subprocess.run(cmd, check=True)
    print()
    print("Build complete! Executable: dist/solvanity")
    print("On Windows: dist/solvanity.exe")


if __name__ == "__main__":
    build()
