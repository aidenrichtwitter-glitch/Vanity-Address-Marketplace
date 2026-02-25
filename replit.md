# SolVanity Word Miner (SolVanityCL Fork)

## Overview
A fork of [SolVanityCL](https://github.com/WincerChan/SolVanityCL) that mines Solana vanity addresses using GPU (OpenCL), filtering for addresses whose last 6 characters form a pattern: literal "X" padding + a cool dictionary word. Examples:
- `...XXomen` (XX padding + 4-letter word)
- `...Xdream` (X padding + 5-letter word)  
- `...dragon` (6-letter word, no padding needed)

All suffix patterns are compiled directly into the OpenCL kernel for full GPU throughput.

## GPU Setup
Defaults to `PYOPENCL_CTX=0:0` (platform 0, device 0) to target the primary GPU (e.g. RTX 3080). Override via environment variable if needed. **Requires an OpenCL-capable GPU — no CPU fallback.**

## Architecture
- `main.py` - Entry point with click CLI (search-pubkey, search-words, show-device, list-words). Sets PYOPENCL_CTX=0:0.
- `build.py` - PyInstaller build script to create standalone executable
- `core/cli.py` - Original SolVanityCL GPU search command (prefix/suffix)
- `core/searcher.py` - GPU searcher using OpenCL (original SolVanityCL)
- `core/config.py` - Host settings for GPU kernel (original SolVanityCL)
- `core/opencl/kernel.cl` - OpenCL Ed25519 + Base58 kernel (original SolVanityCL)
- `core/opencl/manager.py` - OpenCL device manager (original SolVanityCL)
- `core/word_miner.py` - GPU word mining engine: builds suffix patterns, feeds them to GPU kernel
- `core/word_filter.py` - Suffix word detection with literal "X" padding check (6-char tail)
- `core/words.py` - Dictionary of ~1500+ cool words valid in Base58
- `core/utils/crypto.py` - Ed25519 keypair generation and saving
- `core/utils/helpers.py` - Kernel source loader and Base58 validation

## Dependencies
- **click** - CLI framework
- **pyopencl** - GPU acceleration (required)
- **pynacl** - Ed25519 key generation
- **base58** - Base58 encoding for Solana addresses
- **pyinstaller** - Build standalone executable

## Commands
```bash
python main.py search-words              # Mine for word-ending addresses (GPU)
python main.py search-words --count 10   # Find exactly 10 addresses
python main.py search-words --min-word-length 5  # Only 5+ letter words
python main.py search-pubkey --ends-with pump     # Original GPU suffix search
python main.py show-device               # List OpenCL GPU devices
python main.py list-words                # Show all valid words
python build.py                          # Build standalone .exe
```

## Building Executable
Run `python build.py` to create `dist/solvanity` (or `dist/solvanity.exe` on Windows) using PyInstaller.

## Output
Found keypairs saved as `{address}.json` in `found_words/` directory, compatible with Solana CLI.
