# SolVanity Word Miner

## Overview
SolVanity Word Miner is a GPU-accelerated application for generating Solana vanity addresses. It allows users to mine addresses that end with dictionary words, including support for "X" padding and character substitutions (e.g., 'l' to '1'). The project features both a web-based UI (Flask) and a desktop GUI (PySide6/Qt). A key innovation is its integrated blind vanity key marketplace, leveraging NFT-based burn-to-decrypt mechanics with a **split-key Ed25519 protocol** for trustless blind mining. Mined keys are encrypted using Lit Protocol's Chipotle V3 TEE REST API, paired with an on-chain NFT, and uploaded to Solana devnet PDAs. Buyers can acquire these NFTs and then burn them to decrypt and retrieve the private key locally.

## User Preferences
When making changes, ensure that new features or modifications are implemented identically across both the web application (Flask) and the desktop GUI (PySide6). All marketplace features, including table columns, filtering logic, buyer wallet interactions, and available actions (Buy, Burn & Decrypt, Relist), must maintain a 1:1 parity between the two frontends. Avoid implementing features in one frontend without a corresponding implementation in the other.

## System Architecture
The application is designed around a shared backend (`core/backend.py`) that serves both the Flask web UI and the PySide6 desktop GUI, ensuring feature parity. The core mining functionality is GPU-accelerated using OpenCL for efficient Ed25519 key generation and Base58 encoding, allowing for variable-length suffix matching without constant memory limitations. A `word_miner.py` module manages GPU workers and includes a PID thermal controller for GPU temperature management.

The blind vanity key marketplace integrates with the Solana blockchain on devnet. Keys are encrypted client-side using Lit Protocol's Chipotle V3 REST API (AES-256-GCM within TEEs) and uploaded as compact JSON packages to Solana PDAs. Each uploaded package is associated with a unique SPL token NFT (supply=1, decimals=0), minted upon successful encryption. The marketplace supports buying, selling, relisting, and a burn-to-decrypt mechanism where burning the NFT triggers key decryption. A bounty board allows users to request specific vanity words with SOL rewards.

The UI/UX across both web and desktop versions features a tabbed interface for Word Miner, Marketplace, and Settings tabs. The web UI uses `templates/index.html` with `static/style.css` for a dark theme, while the desktop GUI provides a rich, interactive experience. GPU monitoring (temperature, name, power, max temp settings) is integrated into the UI. The Settings tab allows users to configure their own Lit Protocol API key (with a "Create Free API Key" button linking to the Lit dashboard) and Solana seller wallet, with Save/Apply/Clear profile functionality. Profile data is stored in `solvanity_profile.json`. The `/api/settings/load` endpoint returns only masked key previews (never raw keys) and presence flags. The marketplace search (`search_packages()` in `backend.py`) filters to show only ACTIVE + TEE Verified packages, hiding unverified and unknown-code entries from browse results.

Key technical implementations include:
- GPU searcher (`core/searcher.py`) with an OpenCL kernel (`core/opencl/kernel.cl`) optimized for suffix matching.
- Word processing (`core/words.py`) for loading word lists, including automatic 'l' to '1' substitutions for Base58 compatibility.
- Solana client (`core/marketplace/solana_client.py`) for PDA derivation, transaction building, and on-chain package interaction, with data compaction for Solana transaction limits.
- Lit Protocol encryption (`core/marketplace/lit_encrypt.py`) for secure key storage, relying on TEEs and HTTP calls. No Node.js dependency — pure REST API to Chipotle V3.
- SPL token operations (`core/marketplace/nft.py`) for NFT minting, transfer, and burning.
- `bounties.json` for local storage and management of bounty requests.

## Split-Key Ed25519 Protocol (Trustless Blind Mining)
The marketplace uses a split-key protocol where neither the miner nor the TEE ever holds the complete private key alone:

### Protocol Flow
1. **Setup** (`split_key_setup()` in `lit_encrypt.py`): TEE generates random scalar `t`, computes `T = t*B`, wraps `t` with AES-GCM using HMAC-derived key. Returns `T` (32-byte compressed point) and wrapped scalar blob.
2. **Mining**: GPU kernel receives `T` as kernel argument 8. For each candidate seed, computes miner scalar `s` (SHA-512 + clamping), then `P = s*B + T` (point addition). Checks if Base58(P) ends in a dictionary word.
3. **On match**: Miner's seed is returned. The upload handler derives the clamped scalar `s` from the seed via `SHA-512(seed)[0:32]` with Ed25519 clamping (bits 0,1,2 cleared, bit 254 set, bit 255 cleared).
4. **Combine** (`split_key_encrypt()` in `lit_encrypt.py`): Miner sends scalar `s` to TEE. TEE unwraps `t`, computes `k = s + t mod L`, verifies `k*B` matches the vanity address, encrypts the full private key `k` with AES-GCM. Returns encrypted package.
5. **Neither party** ever has the complete key alone. The miner only has `s`, the TEE only has `t` until step 4, and in step 4 the full key only exists inside the TEE enclave.

### Implementation Details
- **OpenCL kernel** (`kernel.cl`): Added `ge_frombytes_vartime` (decode compressed point), `ge_p3_add` (extended point addition), `ge_p3_to_cached` + `ge_add_cached` helpers. When `tee_point` is non-zero, the kernel decodes it once per workgroup (lid==0 + barrier), then each thread adds it to their miner point. The `d` constant in `ge_frombytes_vartime` must be `{-10913610,13857413,-15372611,6949391,114729,-8787816,-6275908,-3247719,-18696448,-12055116}` (computed via `fe_frombytes(d_known)` where `d_known = -121665/121666 mod p`). The `d2` constant in `ge_p3_to_cached` must match: `{-21827239,-5839606,-30745221,...}` (note negative third element). Output buffer is 65 bytes: `[match_length(1), seed(32), pubkey(32)]`.
- **Searcher** (`searcher.py`): Accepts `tee_point: bytes` parameter, creates OpenCL buffer, passes as kernel arg 8. All-zeros = normal mode.
- **Worker pipeline** (`word_miner.py`): `_persistent_worker` and `gpu_word_search` accept and forward `tee_point`.
- **CPU mining** (`gui.py`, `web_app.py`): Uses `nacl.bindings.crypto_scalarmult_ed25519_base_noclamp` + `crypto_core_ed25519_add` for split-key point addition.
- **Lit Actions** (`lit_encrypt.py`): Inline Ed25519 BigInt implementation in JavaScript (no external dependencies). `_SPLIT_KEY_SETUP_TEMPLATE` generates TEE scalar, `_SPLIT_KEY_ENCRYPT_TEMPLATE` combines and encrypts.
- **Backend** (`backend.py`): `blind_upload()` accepts optional `session_blob` parameter. When present, derives miner scalar from seed and calls `split_key_encrypt()` instead of `encrypt_private_key()`. Package JSON includes `splitKey: true` field.
- **Graceful fallback**: If split-key setup fails (TEE unavailable), both GUI and web app fall back to direct encryption mode.

### Session Blob Format
```json
{
  "teePoint": "<32 bytes>",
  "wrappedScalar": "<base64 AES-GCM ciphertext>",
  "wrapIv": "<base64 12-byte IV>",
  "sessionId": "<hex 16-byte random>",
  "setupCodeHash": "<SHA-256 hex>"
}
```
Wrapping key: `HMAC-SHA256(api_key, "split-key-{session_id}")`

## Security: Hash-Pinned Code Verification
The marketplace enforces code-signing hash verification to prevent tampered uploads:
- Each Lit Action template (`_ENCRYPT_TEMPLATE`, `_SPLIT_KEY_ENCRYPT_TEMPLATE`) has a stable SHA-256 hash computed from the raw template string via `_template_hash()`. These are stored as module-level constants `_ENCRYPT_HASH` and `_SPLIT_KEY_ENCRYPT_HASH`.
- When a package is uploaded, the corresponding template hash is stored in the package as `litActionHash` (stable across calls, unlike the old approach which hashed fully-formatted code).
- `get_trusted_template_hashes()` returns the set of all trusted template hashes. On the buyer side, `_enrich_packages()` and `_verify_package_hash()` in `backend.py` check if `litActionHash` is in this trusted set.
- Three verification states: "TEE Verified" (hash in trusted set), "Unknown Code" (TEE encrypted but hash not recognized), "Unverified" (not TEE encrypted).
- `buy_nft()` and `burn_and_decrypt()` in `backend.py` reject packages with unrecognized hashes before any transaction.
- Both web UI and desktop GUI block purchase/burn of unverified packages with clear error messages.
- Split-key packages provide stronger security than direct encryption: the miner never sees the full private key, eliminating the process-memory extraction attack vector.

## GPU Output Buffer Format
The OpenCL kernel output buffer is 65 bytes: `[match_length(1), seed(32), pubkey(32)]`. In split-key (TEE) mode, the GPU-computed public key bytes at offset 33-64 are used directly for address display, avoiding host-side re-derivation mismatches between the kernel's Ed25519 implementation and libsodium. If GPU pubkey bytes are all zero (fallback), host re-derives using `crypto_core_ed25519_add`.

## PyInstaller Build
- `build.py` creates a standalone `solvanity.exe` (Windows) or `solvanity` (Linux) using PyInstaller `--onefile --windowed`.
- `multiprocessing.freeze_support()` is called at the top of `if __name__ == "__main__"` before `main()` to ensure spawned GPU worker processes work correctly in frozen executables.
- Error logging redirects stderr/stdout to `solvanity_error.log` next to the exe for debugging `--windowed` builds.
- BrokenPipeError in mining workers is handled via `_send()` wrapper in `core/word_miner.py`.

## External Dependencies
- **Flask**: Web application framework.
- **PySide6**: Desktop GUI framework.
- **pyopencl**: GPU acceleration for OpenCL-compatible devices.
- **pynacl**: Cryptographic operations, specifically Ed25519 key generation and low-level scalar/point operations for split-key protocol.
- **base58**: Base58 encoding and decoding.
- **requests**: HTTP client for interacting with the Lit Protocol API and Solana RPC.
- **solders**: Solana primitive types (keypair, pubkey, instruction).
- **solana**: Solana RPC client library for blockchain interactions.
- **pynvml**: NVIDIA GPU monitoring (temperature, usage).
- **Lit Protocol (Chipotle V3 REST API)**: For TEE-based encryption, decryption, and split-key scalar operations. No Node.js dependency.
- **Solana Blockchain (Devnet)**: On-chain storage of encrypted packages in PDAs and NFT management via SPL Token Program.
