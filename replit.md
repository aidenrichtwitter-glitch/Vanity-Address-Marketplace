# SolVanity Word Miner (SolVanityCL Fork)

## Overview
A fork of [SolVanityCL](https://github.com/WincerChan/SolVanityCL) that adds CPU-based word suffix filtering on top of GPU-accelerated Solana vanity address mining.

The word miner looks for addresses where the last 6 characters form a pattern: literal "X" padding + a cool word. For example:
- `...XXomen` (XX padding + 4-letter word)
- `...Xdream` (X padding + 5-letter word)  
- `...dragon` (6-letter word, no padding needed)

Padding is always the literal character "X", not arbitrary uppercase letters.

## GPU Setup
Defaults to `PYOPENCL_CTX=0:0` (platform 0, device 0) to target the primary GPU (e.g. RTX 3080) instead of an integrated Intel GPU. Override via environment variable if needed.

## Architecture
- `main.py` - Entry point with click CLI (search-pubkey, search-words, show-device, list-words). Sets PYOPENCL_CTX=0:0.
- `core/cli.py` - Original SolVanityCL GPU search command
- `core/searcher.py` - GPU searcher using OpenCL (original SolVanityCL)
- `core/config.py` - Host settings for GPU kernel (original SolVanityCL)
- `core/opencl/kernel.cl` - OpenCL Ed25519 + Base58 kernel (original SolVanityCL)
- `core/opencl/manager.py` - OpenCL device manager (original SolVanityCL)
- `core/word_miner.py` - CPU word mining engine with live Rich dashboard
- `core/word_filter.py` - Suffix word detection with literal "X" padding check (6-char tail)
- `core/words.py` - Dictionary of ~1500+ cool words valid in Base58
- `core/utils/crypto.py` - Ed25519 keypair generation and saving
- `core/utils/helpers.py` - Kernel source loader and Base58 validation

## Dependencies
- **click** - CLI framework
- **pyopencl** - GPU acceleration (required for search-pubkey, optional for search-words)
- **pynacl** - Ed25519 key generation
- **base58** - Base58 encoding for Solana addresses
- **rich** - Terminal dashboard UI

## Commands
```bash
python main.py search-words              # Mine for word-ending addresses (CPU)
python main.py search-words --threads 4  # Use 4 CPU threads
python main.py search-words --min-word-length 5  # Only 5+ letter words
python main.py search-pubkey --ends-with pump     # Original GPU suffix search
python main.py show-device               # List OpenCL GPU devices
python main.py list-words                # Show all valid words
```

## Output
Found keypairs saved as `{address}.json` in `found_words/` directory, compatible with Solana CLI (`solana-keygen pubkey file.json`).
