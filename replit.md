# SolVanity - Solana Vanity Address Miner

## Overview
GPU-accelerated Solana vanity address miner inspired by solvanityCL. Uses a two-stage filtering pipeline:
1. **Stage 1 (GPU/fast)**: Mass-generate Ed25519 keypairs and filter by case-sensitive suffix/prefix matching
2. **Stage 2 (CPU)**: Check filtered addresses for cool/interesting English words embedded in the Base58 address

## Architecture
- `main.py` - Entry point, CLI argument parsing and validation
- `src/config.py` - Argument parser configuration
- `src/crypto.py` - Solana keypair generation (Ed25519 via PyNaCl), Base58 encoding, key export
- `src/gpu_miner.py` - OpenCL GPU kernel for batch seed generation, CPU fallback generator
- `src/miner.py` - Main mining orchestrator with producer/consumer threading model
- `src/word_filter.py` - Cool word detection engine with scoring system
- `src/words.py` - Dictionary of ~1500+ cool words valid in Base58 encoding
- `src/display.py` - Rich terminal UI with live stats dashboard

## Dependencies
- **pynacl** - Ed25519 key generation (libsodium bindings)
- **base58** - Base58 encoding for Solana addresses
- **rich** - Terminal UI with live updating dashboard
- **pyopencl** - OpenCL GPU acceleration (optional, falls back to CPU)

## Usage
```bash
python main.py                           # Mine with defaults (CPU, 4+ letter words)
python main.py --suffix abc              # Require addresses ending in "abc"
python main.py --prefix XYZ              # Require addresses starting with "XYZ"
python main.py --min-word-length 5       # Only find 5+ letter words
python main.py --custom-words sol,moon   # Add custom words to search
python main.py --gpu-only --suffix dead  # Only suffix match, no word check
python main.py --list-words              # Show all valid cool words
python main.py --no-gpu                  # Force CPU-only mode
```

## Output
Found addresses are saved to `found_addresses.txt` with the address, words found, and full 64-byte secret key (compatible with Solana CLI).

## How It Works
- GPU (or CPU fallback) generates random 32-byte seeds in batches
- Each seed creates an Ed25519 signing key → public key → Base58 Solana address
- Stage 1: Quick suffix/prefix filter (case-sensitive by default)
- Stage 2: CPU scans remaining addresses for dictionary words
- Addresses with words are scored (longer words = higher score) and saved
- Live terminal dashboard shows speed, matches, and best finds
