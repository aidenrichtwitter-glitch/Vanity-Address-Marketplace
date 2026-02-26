# SolVanity Word Miner (SolVanityCL Fork)

## Overview
A desktop GUI application (PySide6/Qt) that mines Solana vanity addresses using GPU (OpenCL), filtering for addresses whose last characters match dictionary words with optional "X" padding. Examples:
- `...XXomen` (XX padding + 4-letter word)
- `...Xdream` (X padding + 5-letter word)  
- `...dragon` (6-letter word, no padding needed)
- `...adventure` (9-letter word, full match)
- `...go1d` (l→1 substitution: "gold")

Suffix patterns are passed to the GPU via global memory buffers (not constant memory), allowing unlimited pattern count without hitting the 64KB constant memory limit.

## GPU Setup
Defaults to `PYOPENCL_CTX=0:0` (platform 0, device 0). **Requires an OpenCL-capable GPU.**

## Architecture
- `gui.py` - PySide6 desktop GUI application (main entry point); collapsible Mining Settings panel
- `main.py` - CLI entry point (alternative to GUI)
- `build.py` - PyInstaller build script to create standalone executable
- `wordlist_3000.txt` - Default word list (3000 common English words, ~2000 Base58-valid)
- `wordlists/processed_wordlist.txt` - Auto-generated processed wordlist with l→1 substitutions applied
- `core/cli.py` - Original SolVanityCL GPU search command (prefix/suffix)
- `core/searcher.py` - GPU searcher using OpenCL (output buffer cleared between runs)
- `core/config.py` - Host settings for GPU kernel (default iteration bits: 20)
- `core/opencl/kernel.cl` - OpenCL Ed25519 + Base58 kernel (variable-length suffix matching)
- `core/opencl/manager.py` - OpenCL device manager
- `core/word_miner.py` - GPU word mining engine with persistent workers; PID thermal controller
- `core/word_filter.py` - Suffix word detection with literal "X" padding check
- `core/words.py` - Word list loader with l→1 substitution; saves processed list to wordlists/ folder
- `core/utils/crypto.py` - Ed25519 keypair generation; saves as {word}.txt with address and Base58 private key
- `core/utils/helpers.py` - Kernel source loader and Base58 validation
- `core/utils/gpu_temp.py` - GPU temperature monitoring (pynvml + nvidia-smi fallback); GPU name detection and recommended temp lookup

## GUI Features
- Collapsible Mining Settings panel (click header to expand/collapse)
- Min Word Length (1-20)
- Output Directory with Browse button
- Word List file picker (Browse/Clear)
- GPU Power slider (10-100%) for manual throttle
- Max GPU Temp setting (60-95°C) with auto-detection of recommended default per GPU model
- Detected GPU name display
- Live GPU temperature display (color-coded: green/yellow/red) in dedicated panel
- Found Addresses table with word suffix and timing
- Log panel

## Word Processing
- Automatic l→1 substitution: since lowercase 'l' is not a valid Base58 character, words containing 'l' get a variant with '1' substituted (e.g., "gold"→"go1d", "level"→"1eve1")
- Processed wordlist automatically saved to `wordlists/processed_wordlist.txt`
- ~837 additional words recovered from l→1 substitution

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
Create a `.txt` file with one word per line. Lines starting with `#` are treated as comments. Non-Base58 words are silently filtered. l→1 substitution is applied automatically. Use the "Browse" button to select your file.

## Output
Found keypairs saved as `{word}.txt` (e.g., `dream.txt`, `go1d.txt`) in the output directory. Duplicates get numbered (`dream_1.txt`). Each file contains the address and Base58-encoded private key.

## Performance Notes
- GPU output buffer is cleared between kernel runs to prevent duplicate results
- Persistent worker processes avoid kernel recompilation between rounds
- GPU Power slider adds sleep delays between kernel batches (manual throttle)
- PID thermal controller smoothly adjusts delay to hold GPU at target temperature
- Temperature polling runs in background thread to avoid UI lag
- nvidia-smi subprocess uses CREATE_NO_WINDOW on Windows to prevent console flicker
- Suffix lengths pre-computed on host and passed as separate buffer (eliminates per-work-item length scan in kernel)
- Suffix bytes pre-encoded as base58 indices on host (eliminates alphabet_indices lookup per comparison in kernel)
- OpenCL kernel caching enabled (PYOPENCL_NO_CACHE=FALSE) for faster startup
- Local work size increased to 64 for better GPU occupancy
- increase_key32 uses byte-level arithmetic instead of Python big-integer conversion
- save_keypair accepts pre-computed pubkey to avoid redundant Ed25519 derivation
- Word count loading debounced (400ms) to prevent UI lag while typing
- Speed reports time-based (~2s intervals) instead of iteration-count-based
- GUI shows total keys checked and probability-based ETA
