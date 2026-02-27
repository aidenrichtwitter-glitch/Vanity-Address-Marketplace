#!/usr/bin/env python3
"""Build standalone executable using PyInstaller.

Run this on the target machine (e.g. Windows with your GPU):
    pip install pyinstaller pyopencl pynacl base58 click PySide6 solders solana lit-python-sdk
    python build.py

IMPORTANT: Close any running solvanity.exe before building!

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

    exe_name = "solvanity.exe" if platform.system() == "Windows" else "solvanity"
    exe_path = os.path.join("dist", exe_name)
    if os.path.exists(exe_path):
        try:
            os.remove(exe_path)
        except PermissionError:
            print(f"ERROR: Cannot overwrite {exe_path}")
            print(f"       Close the running solvanity app first, then retry.")
            sys.exit(1)

    pyside6_excludes = [
        "PySide6.Qt3DAnimation", "PySide6.Qt3DCore", "PySide6.Qt3DExtras",
        "PySide6.Qt3DInput", "PySide6.Qt3DLogic", "PySide6.Qt3DRender",
        "PySide6.QtBluetooth", "PySide6.QtCharts", "PySide6.QtConcurrent",
        "PySide6.QtDBus", "PySide6.QtDataVisualization", "PySide6.QtDesigner",
        "PySide6.QtGraphs", "PySide6.QtGraphsWidgets", "PySide6.QtHelp",
        "PySide6.QtHttpServer", "PySide6.QtLocation", "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets", "PySide6.QtNetworkAuth", "PySide6.QtNfc",
        "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtPositioning",
        "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickControls2",
        "PySide6.QtQuickTest", "PySide6.QtQuickWidgets", "PySide6.QtRemoteObjects",
        "PySide6.QtScxml", "PySide6.QtSensors", "PySide6.QtSerialBus",
        "PySide6.QtSerialPort", "PySide6.QtSpatialAudio", "PySide6.QtSql",
        "PySide6.QtStateMachine", "PySide6.QtSvg", "PySide6.QtSvgWidgets",
        "PySide6.QtTest", "PySide6.QtTextToSpeech", "PySide6.QtUiTools",
        "PySide6.QtWebChannel", "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineQuick", "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebSockets", "PySide6.QtWebView", "PySide6.QtXml",
        "PySide6.QtQml", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
        "PySide6.QtPrintSupport", "PySide6.QtAsyncio",
    ]

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
        "--hidden-import", "PySide6.QtWidgets",
        "--hidden-import", "PySide6.QtCore",
        "--hidden-import", "PySide6.QtGui",
        "--hidden-import", "PySide6.QtNetwork",
        "--collect-all", "pyopencl",
        "--collect-all", "nacl",
        "--collect-all", "cffi",
        "--collect-all", "solders",
        "--collect-all", "solana",
    ]

    for mod in pyside6_excludes:
        cmd.extend(["--exclude-module", mod])

    cmd.append("gui.py")

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

    print()
    print("=" * 60)
    print(f"  Build complete!")
    print(f"  Executable: {exe_path}")
    print("=" * 60)


if __name__ == "__main__":
    build()
