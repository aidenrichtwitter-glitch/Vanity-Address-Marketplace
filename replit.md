# SolVanity Word Miner (SolVanityCL Fork)

## Overview
A desktop GUI application (PySide6/Qt) that mines Solana vanity addresses using GPU (OpenCL), filtering for addresses whose last characters match dictionary words with optional "X" padding. Examples:
- `...XXomen` (XX padding + 4-letter word)
- `...Xdream` (X padding + 5-letter word)  
- `...dragon` (6-letter word, no padding needed)
- `...adventure` (9-letter word, full match)

All suffix patterns (variable length) are compiled directly into the OpenCL kernel for full GPU throughput.

## GPU Setup
Defaults to `PYOPENCL_CTX=0:0` (platform 0, device 0). **Requires an OpenCL-capable GPU.**

## Architecture
- `gui.py` - PySide6 desktop GUI application (main entry point)
- `main.py` - CLI entry point (alternative to GUI)
- `build.py` - PyInstaller build script to create standalone executable
- `wordlist_3000.txt` - Default word list (3000 common English words, ~2000 Base58-valid)
- `core/cli.py` - Original SolVanityCL GPU search command (prefix/suffix)
- `core/searcher.py` - GPU searcher using OpenCL (output buffer cleared between runs)
- `core/config.py` - Host settings for GPU kernel (default iteration bits: 20)
- `core/opencl/kernel.cl` - OpenCL Ed25519 + Base58 kernel (variable-length suffix matching)
- `core/opencl/manager.py` - OpenCL device manager
- `core/word_miner.py` - GPU word mining engine with persistent workers (no kernel recompilation between rounds)
- `core/word_filter.py` - Suffix word detection with literal "X" padding check
- `core/words.py` - Word list loader; defaults to wordlist_3000.txt, supports custom .txt files
- `core/utils/crypto.py` - Ed25519 keypair generation; saves as {word}.txt with address and Base58 private key
- `core/utils/helpers.py` - Kernel source loader and Base58 validation
- `core/utils/gpu_temp.py` - GPU temperature monitoring (pynvml + nvidia-smi fallback)

## GUI Features
- Min Word Length (1-20)
- Output Directory with Browse button
- Word List file picker (Browse/Clear)
- GPU Power slider (10-100%) for manual throttle
- Max GPU Temp setting (60-95°C) with auto-throttle
- Live GPU temperature display (color-coded: green/yellow/red)
- Found Addresses table with word suffix and timing
- Log panel

## Dependencies
- **PySide6** - Qt GUI framework
- **pyopencl** - GPU acceleration (required)
- **pynacl** - Ed25519 key generation
- **base58** - Base58 encoding for Solana addresses
- **click** - CLI framework (for main.py)
- **cffi** - Native C bindings (required by pynacl)
- **pynvml** - NVIDIA GPU temperature monitoring
- **pyinstaller** - Build standalone executable

## Building
```bash
pip install pyopencl pynacl base58 click PySide6 pynvml pyinstaller
python build.py
# Output: dist/solvanity.exe (Windows) or dist/solvanity (Linux)
```

## Custom Word Lists
Create a `.txt` file with one word per line. Lines starting with `#` are treated as comments. Non-Base58 words are silently filtered. Use the "Browse" button to select your file.

## Output
Found keypairs saved as `{word}.txt` (e.g., `dream.txt`, `adventure.txt`) in the output directory. Duplicates get numbered (`dream_1.txt`). Each file contains the address and Base58-encoded private key.

## Performance Notes
- GPU output buffer is cleared between kernel runs to prevent duplicate results
- Persistent worker processes avoid kernel recompilation between rounds
- GPU Power slider adds sleep delays between kernel batches (manual throttle)
- Auto-throttle monitors GPU temp and dynamically adjusts delay when over max temp
- 5°C hysteresis on auto-throttle to prevent rapid on/off cycling
