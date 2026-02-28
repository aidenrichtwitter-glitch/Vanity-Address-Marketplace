# SolVanity Word Miner

## Overview
SolVanity Word Miner is a GPU-accelerated application for generating Solana vanity addresses. It allows users to mine addresses that end with dictionary words, including support for "X" padding and character substitutions (e.g., 'l' to '1'). The project features both a web-based UI (Flask) and a desktop GUI (PySide6/Qt). A key innovation is its integrated blind vanity key marketplace, leveraging NFT-based burn-to-decrypt mechanics. Mined keys are encrypted using Lit Protocol, paired with an on-chain NFT, and uploaded to Solana devnet PDAs. Buyers can acquire these NFTs and then burn them to decrypt and retrieve the private key locally, facilitating a secure and decentralized marketplace for vanity addresses.

## User Preferences
When making changes, ensure that new features or modifications are implemented identically across both the web application (Flask) and the desktop GUI (PySide6). All marketplace features, including table columns, filtering logic, buyer wallet interactions, and available actions (Buy, Burn & Decrypt, Relist), must maintain a 1:1 parity between the two frontends. Avoid implementing features in one frontend without a corresponding implementation in the other.

## System Architecture
The application is designed around a shared backend (`core/backend.py`) that serves both the Flask web UI and the PySide6 desktop GUI, ensuring feature parity. The core mining functionality is GPU-accelerated using OpenCL for efficient Ed25519 key generation and Base58 encoding, allowing for variable-length suffix matching without constant memory limitations. A `word_miner.py` module manages GPU workers and includes a PID thermal controller for GPU temperature management.

The blind vanity key marketplace integrates with the Solana blockchain on devnet. Keys are encrypted client-side using Lit Protocol's Chipotle V3 REST API (AES-256-GCM within TEEs) and uploaded as compact JSON packages to Solana PDAs. Each uploaded package is associated with a unique SPL token NFT (supply=1, decimals=0), minted upon successful encryption. The marketplace supports buying, selling, relisting, and a burn-to-decrypt mechanism where burning the NFT triggers key decryption. A bounty board allows users to request specific vanity words with SOL rewards.

The UI/UX across both web and desktop versions features a tabbed interface for Word Miner and Marketplace functionalities. The web UI uses `templates/index.html` with `static/style.css` for a dark theme, while the desktop GUI provides a rich, interactive experience. GPU monitoring (temperature, name, power, max temp settings) is integrated into the UI.

Key technical implementations include:
- GPU searcher (`core/searcher.py`) with an OpenCL kernel (`core/opencl/kernel.cl`) optimized for suffix matching.
- Word processing (`core/words.py`) for loading word lists, including automatic 'l' to '1' substitutions for Base58 compatibility.
- Solana client (`core/marketplace/solana_client.py`) for PDA derivation, transaction building, and on-chain package interaction, with data compaction for Solana transaction limits.
- Lit Protocol encryption (`core/marketplace/lit_encrypt.py`) for secure key storage, relying on TEEs and HTTP calls. No Node.js dependency — pure REST API to Chipotle V3.
- SPL token operations (`core/marketplace/nft.py`) for NFT minting, transfer, and burning.
- `bounties.json` for local storage and management of bounty requests.

## Security: Hash-Pinned Code Verification
The marketplace enforces code-signing hash verification to prevent tampered uploads:
- The Lit Action encrypt template (`_ENCRYPT_TEMPLATE` in `lit_encrypt.py`) has a fixed SHA-256 hash computed by `get_lit_action_hash()`.
- When a package is uploaded, the hash of the actual code executed in the TEE is stored in the package as `litActionHash`.
- On the buyer side, `_enrich_packages()` in `backend.py` compares the stored `litActionHash` against the known trusted hash.
- Three verification states: "TEE Verified" (hash matches), "Unknown Code" (TEE encrypted but hash mismatch), "Unverified" (not TEE encrypted).
- `search_packages()` filters out non-verified packages — they never appear in marketplace browse results.
- `buy_nft()` and `burn_and_decrypt()` in `backend.py` reject packages with mismatched hashes before any transaction.
- Both web UI and desktop GUI block purchase/burn of unverified packages with clear error messages.
- **Limitation**: This verifies the encryption code was unmodified, but cannot prevent a sophisticated attacker from extracting the key from process memory before encryption. True trustlessness would require key generation inside the TEE.

## PyInstaller Build
- `build.py` creates a standalone `solvanity.exe` (Windows) or `solvanity` (Linux) using PyInstaller `--onefile --windowed`.
- `multiprocessing.freeze_support()` is called at the top of `if __name__ == "__main__"` before `main()` to ensure spawned GPU worker processes work correctly in frozen executables.
- Error logging redirects stderr/stdout to `solvanity_error.log` next to the exe for debugging `--windowed` builds.
- BrokenPipeError in mining workers is handled via `_send()` wrapper in `core/word_miner.py`.

## External Dependencies
- **Flask**: Web application framework.
- **PySide6**: Desktop GUI framework.
- **pyopencl**: GPU acceleration for OpenCL-compatible devices.
- **pynacl**: Cryptographic operations, specifically Ed25519 key generation.
- **base58**: Base58 encoding and decoding.
- **requests**: HTTP client for interacting with the Lit Protocol API and Solana RPC.
- **solders**: Solana primitive types (keypair, pubkey, instruction).
- **solana**: Solana RPC client library for blockchain interactions.
- **pynvml**: NVIDIA GPU monitoring (temperature, usage).
- **Lit Protocol (Chipotle V3 REST API)**: For TEE-based encryption and decryption of private keys.
- **Solana Blockchain (Devnet)**: On-chain storage of encrypted packages in PDAs and NFT management via SPL Token Program.