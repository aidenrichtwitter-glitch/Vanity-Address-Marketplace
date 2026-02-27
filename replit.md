# SolVanity Word Miner (SolVanityCL Fork)

## Overview
A GPU-accelerated Solana vanity address miner with both a web UI (Flask) and a desktop GUI (PySide6/Qt). Mines addresses whose last characters match dictionary words with optional "X" padding. Includes a blind vanity key marketplace with NFT-based burn-to-decrypt mechanics — mined keys are encrypted with Lit Protocol, paired with an on-chain NFT, and uploaded to Solana devnet PDAs. Buyers burn the NFT to decrypt and save the private key locally.

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
- `web_app.py` - Flask web UI server (port 5000) with SSE for real-time updates — primary interface in Replit
- `templates/index.html` - Web frontend with tabbed interface (Word Miner + Marketplace tabs)
- `static/style.css` - Dark theme CSS matching the original Qt design
- `gui.py` - PySide6 desktop GUI (used for Windows builds via PyInstaller)
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
  - `lit_encrypt.py` - Lit Protocol encryption via Lit Actions (TEE) / decryption wrapper; computes and verifies litActionHash
  - `lit_action.js` - JavaScript Lit Action that runs inside Lit's TEE to encrypt private keys; SHA-256 hash stored on-chain for buyer verification
  - `nft.py` - SPL token NFT operations: mint (supply=1, decimals=0), transfer, burn, supply/balance checks

## Mining Modes
The Word Miner tab has a mode toggle:

### Mine Mode (default)
- Found vanity keys are saved locally as .txt files
- Private key is visible to the user
- Standard behavior for personal vanity address mining

### Blind Mode
- Found vanity keys are encrypted inside Lit Protocol's TEE via a Lit Action (datil network) and uploaded to a Solana devnet PDA
- Encryption happens inside Lit's Trusted Execution Environment, not on the seller's machine — the Lit Action code is auditable and its SHA-256 hash is stored on-chain with each package
- An NFT (SPL token, supply=1) is minted alongside each upload to enable burn-to-decrypt
- The encrypted JSON includes mintAddress, sellerAddress, vanityWord, litActionHash, and encryptedInTEE fields
- The private key is NEVER saved locally or shown to the user
- Requires a seller wallet (base58 private key) configured in the inline wallet input
- Only buyers who burn the NFT can decrypt the key

## NFT Burn-to-Decrypt Marketplace
The Marketplace tab enables an NFT-based vanity key marketplace:

### How It Works
1. **Seller (Blind Mode)**: Mines a vanity key → mints an NFT → encrypts key with Lit Protocol → uploads encrypted data + NFT mint address to PDA
2. **Buyer**: Browses marketplace → selects a package → burns the NFT → key is decrypted and saved locally
3. **Resale**: NFTs can be transferred between wallets before burning. Once burned, the key is revealed and cannot be re-sold.

### Buyer Flow
1. Enter buyer wallet (private key) in the Buyer Wallet section
2. Click "Search Packages" to fetch all uploaded PDAs from devnet
3. Packages show: vanity address, vanity word, NFT mint, price, status (ACTIVE/BURNED), verification (TEE Verified/Unknown Code/Unverified)
4. Select an ACTIVE package and click "Burn & Decrypt"
5. The app: transfers NFT to buyer → burns NFT on-chain → decrypts via Lit Protocol → saves key to `decrypted_keys/` folder
6. Burned packages show as "SOLD" and cannot be re-purchased

### Saved Keys
Decrypted keys are saved to `decrypted_keys/<vanity_address>.txt` containing:
- Vanity address
- Private key (Base58)
- NFT mint address
- Burn transaction signature

### On-Chain Program
- Program ID: `EHS97x7xVo4svEVrEsVnihXgPLozCFs1BH7Bnkuf2nP6` (deployed on devnet)
- PDA seed: `b"vanity_pkg"` + vanity pubkey bytes
- Discriminator: `[165, 105, 103, 168, 229, 214, 177, 251]`
- Instruction: `upload_vanity_package(vanity_pubkey, encrypted_json)`

### SPL Token (NFT)
- Token Program: `TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA`
- Associated Token Account Program: `ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL`
- Each NFT: supply=1, decimals=0 (non-fungible)
- Minted to seller's ATA on upload, transferred to buyer on purchase, burned to decrypt

### Environment Variables
- `SOLANA_DEVNET_PRIVKEY` - Base58-encoded seller wallet private key (required for uploads and NFT transfers)

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
- Marketplace: Buyer wallet input, Search with suffix filter, NFT status display, Buy & Burn button, decrypted key file saving

## Word Processing
- Automatic l to 1 substitution: since lowercase 'l' is not a valid Base58 character, words containing 'l' get a variant with '1' substituted (e.g., "gold" becomes "go1d", "level" becomes "1eve1")
- Processed wordlist automatically saved to `wordlists/processed_wordlist.txt`
- ~837 additional words recovered from l to 1 substitution

## Dependencies
- **Flask** - Web UI framework (for Replit webview)
- **PySide6** - Qt GUI framework (for Windows desktop builds)
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
