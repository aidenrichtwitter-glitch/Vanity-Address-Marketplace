# SolVanity Word Miner

## Overview
SolVanity Word Miner is a GPU-accelerated application for generating Solana vanity addresses. It allows users to mine addresses that end with dictionary words, including support for "X" padding and character substitutions. The project features both a web-based UI (Flask) and a desktop GUI (PySide6/Qt). A key innovation is its integrated blind vanity key marketplace, leveraging NFT-based burn-to-decrypt mechanics with a **split-key Ed25519 protocol** for trustless blind mining. Mined keys are encrypted using Lit Protocol's Chipotle V3 TEE REST API, paired with an on-chain NFT, and uploaded to Solana devnet PDAs. Buyers can acquire these NFTs and then burn them to decrypt and retrieve the private key locally.

## User Preferences
When making changes, ensure that new features or modifications are implemented identically across both the web application (Flask) and the desktop GUI (PySide6). All marketplace features, including table columns, filtering logic, buyer wallet interactions, and available actions (Buy, Burn & Decrypt, Relist), must maintain a 1:1 parity between the two frontends. Avoid implementing features in one frontend without a corresponding implementation in the other.

## System Architecture
The application is designed around a shared backend (`core/backend.py`) that serves both the Flask web UI and the PySide6 desktop GUI, ensuring feature parity. The core mining functionality is GPU-accelerated using OpenCL for efficient Ed25519 key generation and Base58 encoding. A `word_miner.py` module manages GPU workers and includes a PID thermal controller for GPU temperature management.

The blind vanity key marketplace integrates with the Solana blockchain on devnet. Keys are encrypted client-side using Lit Protocol's Chipotle V3 REST API and uploaded as compact JSON packages to Solana PDAs. Each uploaded package is associated with a unique SPL token NFT. NFTs are transferred to the PDA's Associated Token Account, enabling trustless on-chain buying where the Solana program atomically handles SOL payment and NFT transfer. The marketplace supports buying, selling, relisting, and a burn-to-decrypt mechanism, which triggers key decryption only after on-chain NFT burning verification inside the TEE. A bounty board allows users to request specific vanity words with SOL rewards.

The UI/UX across both web and desktop versions features a tabbed interface for Word Miner, Marketplace, and Settings. The web UI uses `templates/index.html` with `static/style.css` for a dark theme. GPU monitoring is integrated into the UI. The Settings tab allows users to configure their Lit Protocol API key and Solana seller wallet, with profile data stored in `solvanity_profile.json`. The marketplace search filters to show only ACTIVE + TEE Verified packages.

A key security feature is the **Split-Key Ed25519 Protocol**, ensuring neither the miner nor the TEE ever holds the complete private key alone. The process involves the TEE generating a scalar `t`, the GPU miner generating scalar `s`, and the TEE combining them (`k = s + t mod L`) to form the full private key `k` only within the secure enclave for encryption. This protocol is implemented via specific OpenCL kernel modifications and Lit Actions.

The marketplace uses a dedicated PKP (Programmable Key Pair) wallet whose private key exists exclusively inside the Lit Protocol TEE. Wrapping keys for encryption and decryption are deterministically derived inside the TEE using `SHA256(signEcdsa(SHA256("solvanity-wrap:" + conditionsJSON), pkpPubKey))`. The PKP public key is stored in each encrypted package (`pkpPublicKey` field), enabling any buyer on any instance to decrypt after burning — no seller environment variables needed. At decrypt time, the PKP key is read from the package itself (with env var fallback for transitional packages). This architecture ensures that the PKP private key remains TEE-held, code is IPFS-immutable, and decryption requires on-chain NFT burning, providing robust cross-instance trustless security.

Hash-pinned code verification is enforced, where each Lit Action template has a stable SHA-256 hash. This `litActionHash` is stored with each package, and packages are only "TEE Verified" if their hash is in the current PKP trusted set, preventing tampered uploads. Both UIs block transactions for unverified packages. Legacy pre-PKP template hashes are tracked in `_LEGACY_TEMPLATE_HASHES` but excluded from the trusted set — legacy packages are labeled "Legacy (Insecure)" and filtered out of marketplace search results. Only packages encrypted with the PKP-signed system are shown.

The Chipotle V3 API uses **Groups** for access control. A PKP group (stored in `LIT_GROUP_ID`) is created with `all_wallets_permitted=True` and `all_actions_permitted=True`, allowing inline Lit Action code execution. The PKP is added to the group via `add_pkp_to_group`. Independent **usage API keys** are created via `add_usage_api_key` with `expiration` and `balance` parameters — these are scoped to the account and allow any participant to independently run Lit Actions (including `signEcdsa`) against the shared PKP. No IPFS pinning is required since actions run inline with `all_actions_permitted=True`.

All marketplace instances share a single PKP wallet (`MARKETPLACE_PKP_PUBLIC_KEY` in `core/marketplace/config.py`) and a single master API key (`MARKETPLACE_LIT_API_KEY` in `config.py`). Both are hardcoded constants — the master key always controls TEE operations and users never need to provide or configure it. `_get_api_key()` always returns `MARKETPLACE_LIT_API_KEY` unconditionally. This is safe because the master key cannot extract the PKP private key (TEE-held) and cannot bypass burn checks. Users generate their own **usage keys** via `create_user_scoped_key()` — these are personal scoped keys created from the master account. The "Generate Usage Key" button in both UIs runs: use shared master key → use shared PKP → `register_ipfs_actions()` (create group) → `create_user_scoped_key()`. Profile saves only user-specific keys (`SOLANA_DEVNET_PRIVKEY`, `LIT_PKP_PUBLIC_KEY`, `LIT_GROUP_ID`, `LIT_USAGE_API_KEY`) to `solvanity_profile.json` — `LIT_API_KEY` is never saved since it's hardcoded.

The OpenCL kernel output buffer is 65 bytes: `[match_length(1), seed(32), pubkey(32)]`. In split-key mode, the GPU-computed public key bytes are used directly.

## External Dependencies
- **Flask**: Web application framework.
- **PySide6**: Desktop GUI framework.
- **pyopencl**: GPU acceleration for OpenCL-compatible devices.
- **pynacl**: Cryptographic operations (Ed25519 key generation, scalar/point operations).
- **base58**: Base58 encoding and decoding.
- **requests**: HTTP client for Lit Protocol API and Solana RPC.
- **solders**: Solana primitive types.
- **solana**: Solana RPC client library.
- **pynvml**: NVIDIA GPU monitoring.
- **Lit Protocol (Chipotle V3 REST API)**: TEE-based encryption, decryption, and split-key operations.
- **Solana Blockchain (Devnet)**: On-chain storage of encrypted packages in PDAs and NFT management via SPL Token Program.