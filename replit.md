# SolVanity Word Miner (SolVanityCL Fork)

## Overview
A desktop GUI application (PySide6/Qt) that mines Solana vanity addresses using GPU (OpenCL), filtering for addresses whose last characters match dictionary words with optional "X" padding. Includes a blind vanity key marketplace where mined keys are encrypted with Lit Protocol and uploaded to Solana devnet PDAs for purchase/decryption by buyers.

Examples of vanity addresses:
- `...XXomen` (XX padding + 4-letter word)
- `...Xdream` (X padding + 5-letter word)  
- `...dragon` (6-letter word, no padding needed)
- `...adventure` (9-letter word, full match)
- `...go1d` (l to 1 substitution: "gold")

Suffix patterns are passed to the GPU via global memory buffers (not constant memory), allowing unlimited pattern count without hitting the 64KB constant memory limit.

## GPU Setup
Defaults to `PYOPENCL_CTX=0:0` (platform 0, device 0). **Requires an OpenCL-capable GPU.**

## Architecture
- `gui.py` - PySide6 desktop GUI with tabbed interface (Word Miner + Marketplace tabs)
- `main.py` - CLI entry point (alternative to GUI)
- `build.py` - PyInstaller build script to create standalone executable
- `wordlist_3000.txt` - Default word list (3000 common English words, ~2000 Base58-valid)
- `wordlists/processed_wordlist.txt` - Auto-generated processed wordlist with l to 1 substitutions applied
- `core/cli.py` - Original SolVanityCL GPU search command (prefix/suffix)
- `core/searcher.py` - GPU searcher using OpenCL (output buffer cleared between runs)
- `core/config.py` - Host settings for GPU kernel (default iteration bits: 20)
- `core/opencl/kernel.cl` - OpenCL Ed25519 + Base58 kernel (variable-length suffix matching)
- `core/opencl/manager.py` - OpenCL device manager
- `core/word_miner.py` - GPU word mining engine with persistent workers; PID thermal controller
- `core/word_filter.py` - Suffix word detection with literal "X" padding check
- `core/words.py` - Word list loader with l to 1 substitution; saves processed list to wordlists/ folder
- `core/utils/crypto.py` - Ed25519 keypair generation; saves as {word}.txt with address and Base58 private key
- `core/utils/helpers.py` - Kernel source loader and Base58 validation
- `core/utils/gpu_temp.py` - GPU temperature monitoring (pynvml + nvidia-smi fallback); GPU name detection and recommended temp lookup
- `core/marketplace/` - Blind vanity key marketplace module
  - `config.py` - On-chain program constants (program ID, PDA seed, discriminator, RPC URL, Lit network)
  - `solana_client.py` - Solana devnet RPC client: PDA derivation, upload instruction building, transaction sending, package fetching/parsing
  - `lit_encrypt.py` - Lit Protocol encryption/decryption wrapper for private keys

## Mining Modes
The Word Miner tab has a mode toggle:

### Mine Mode (default)
- Found vanity keys are saved locally as .txt files
- Private key is visible to the user
- Standard behavior for personal vanity address mining

### Blind Mode
- Found vanity keys are encrypted with Lit Protocol (datil network) and uploaded to a Solana devnet PDA
- The private key is NEVER saved locally or shown to the user
- Requires a seller wallet (base58 private key) configured in the inline wallet input
- Only buyers who meet the solRpc getBalance access conditions can decrypt

## Marketplace Feature
The Marketplace tab enables buying/decrypting blind vanity keys:

### Buyer Flow
1. Click "Browse Packages" to fetch all uploaded PDAs from the on-chain program
2. Select a package to see the vanity address
3. Click "Decrypt Selected" to decrypt using Lit Protocol
4. The decrypted private key is displayed for import into Phantom/Solflare

### On-Chain Program
- Program ID: `EHS97x7xVo4svEVrEsVnihXgPLozCFs1BH7Bnkuf2nP6` (deployed on devnet)
- PDA seed: `b"vanity_pkg"` + vanity pubkey bytes
- Discriminator: `[165, 105, 103, 168, 229, 214, 177, 251]`
- Instruction: `upload_vanity_package(vanity_pubkey, encrypted_json)`

### Environment Variables
- `SOLANA_DEVNET_PRIVKEY` - Base58-encoded seller wallet private key (required for uploads)

## GUI Features
- Tabbed interface: Word Miner and Marketplace
- Collapsible Mining Settings panel (click header to expand/collapse)
- Min Word Length (1-20)
- Output Directory with Browse button
- Word List file picker (Browse/Clear)
- GPU Power slider (10-100%) for manual throttle
- Max GPU Temp setting (60-95 C) with auto-detection of recommended default per GPU model
- Detected GPU name display
- Live GPU temperature display (color-coded: green/yellow/red) in dedicated panel
- Found Addresses table with word suffix and timing
- Log panel
- Mine/Blind mode toggle with color-coded status indicators
- Blind Mode inline seller wallet configuration
- Marketplace buyer panel with package browser and decrypt

## Word Processing
- Automatic l to 1 substitution: since lowercase 'l' is not a valid Base58 character, words containing 'l' get a variant with '1' substituted (e.g., "gold" becomes "go1d", "level" becomes "1eve1")
- Processed wordlist automatically saved to `wordlists/processed_wordlist.txt`
- ~837 additional words recovered from l to 1 substitution

## Dependencies
- **PySide6** - Qt GUI framework
- **pyopencl** - GPU acceleration (required)
- **pynacl** - Ed25519 key generation
- **base58** - Base58 encoding for Solana addresses
- **click** - CLI framework (for main.py)
- **cffi** - Native C bindings (required by pynacl)
- **pynvml** - NVIDIA GPU temperature monitoring
- **pyinstaller** - Build standalone executable
- **solders** - Solana keypair/pubkey/instruction types
- **solana** - Solana RPC client (solana-py)
- **lit-python-sdk** - Lit Protocol encryption/decryption

## Building
```bash
pip install pyopencl pynacl base58 click PySide6 pynvml pyinstaller solders solana lit-python-sdk
python build.py
# Output: dist/solvanity.exe (Windows) or dist/solvanity (Linux)
```

## Custom Word Lists
Create a `.txt` file with one word per line. Lines starting with `#` are treated as comments. Non-Base58 words are silently filtered. l to 1 substitution is applied automatically. Use the "Browse" button to select your file.

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
