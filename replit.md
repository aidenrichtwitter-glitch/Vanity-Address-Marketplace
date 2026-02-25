# SolVanity Word Miner (SolVanityCL Fork)

## Overview
A desktop GUI application (PySide6/Qt) that mines Solana vanity addresses using GPU (OpenCL), filtering for addresses whose last 6 characters form a pattern: literal "X" padding + a cool dictionary word. Examples:
- `...XXomen` (XX padding + 4-letter word)
- `...Xdream` (X padding + 5-letter word)  
- `...dragon` (6-letter word, no padding needed)

All suffix patterns are compiled directly into the OpenCL kernel for full GPU throughput.

## GPU Setup
Defaults to `PYOPENCL_CTX=0:0` (platform 0, device 0). **Requires an OpenCL-capable GPU.**

## Architecture
- `gui.py` - PySide6 desktop GUI application (main entry point)
- `main.py` - CLI entry point (alternative to GUI)
- `build.py` - PyInstaller build script to create standalone executable
- `core/cli.py` - Original SolVanityCL GPU search command (prefix/suffix)
- `core/searcher.py` - GPU searcher using OpenCL
- `core/config.py` - Host settings for GPU kernel (default iteration bits: 20)
- `core/opencl/kernel.cl` - OpenCL Ed25519 + Base58 kernel
- `core/opencl/manager.py` - OpenCL device manager
- `core/word_miner.py` - GPU word mining engine: builds suffix patterns, feeds them to GPU kernel
- `core/word_filter.py` - Suffix word detection with literal "X" padding check (6-char tail)
- `core/words.py` - Built-in dictionary of 1000+ cool words; supports loading custom word list from .txt file
- `core/utils/crypto.py` - Ed25519 keypair generation and saving
- `core/utils/helpers.py` - Kernel source loader and Base58 validation

## Dependencies
- **PySide6** - Qt GUI framework
- **pyopencl** - GPU acceleration (required)
- **pynacl** - Ed25519 key generation
- **base58** - Base58 encoding for Solana addresses
- **click** - CLI framework (for main.py)
- **cffi** - Native C bindings (required by pynacl)
- **pyinstaller** - Build standalone executable

## Building
```bash
pip install pyopencl pynacl base58 click PySide6 pyinstaller
python build.py
# Output: dist/solvanity.exe (Windows) or dist/solvanity (Linux)
```

## Custom Word Lists
Create a `.txt` file with one word per line. Lines starting with `#` are treated as comments. Only Base58-compatible characters are valid. Use the "Browse" button in the Word List field to select your file.

## Output
Found keypairs saved as `{address}.json` in the output directory, compatible with Solana CLI.
