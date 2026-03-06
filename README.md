# SolVanity Word Miner

GPU-accelerated Solana vanity address generator with a trustless blind marketplace. Mine addresses ending in dictionary words, list them as NFTs, and sell them — buyers burn the NFT to decrypt the private key inside a TEE. No shared secrets, no account creation, no trust required.

---

## What This Does

Generates Solana Ed25519 keypairs where the public address ends in a recognizable English word (e.g. `...XXdream`, `...Xdragon`). An OpenCL kernel checks millions of keys per second against a compiled suffix table. Found addresses can be sold through an on-chain blind marketplace where the private key is encrypted inside a hardware enclave and only released when the buyer irreversibly burns an NFT.

## Features

- **GPU-accelerated mining** — OpenCL kernel generates Ed25519 keypairs and performs Base58 suffix matching entirely on-device
- **CPU fallback** — pure-Python miner for machines without a GPU (slower, but functional)
- **3,000-word dictionary** — matches English words in the last 6 characters of Solana addresses with configurable `X` padding
- **Direct-encrypt architecture** — full `[seed(32) + pubkey(32)]` keypair encrypted inside the TEE, producing Phantom-importable keys
- **Lit Protocol Chipotle V3 TEE encryption** — private keys are encrypted inside Intel SGX/TDX hardware enclaves via REST API
- **NFT burn-to-decrypt** — buyers must irreversibly burn a Solana SPL token on-chain before the TEE releases the decrypted key
- **On-chain marketplace** — encrypted packages stored in Solana devnet PDAs with atomic buy transactions
- **Hash-pinned code verification** — Lit Action code is SHA-256 hashed at encryption time; only packages matching trusted template hashes are tradeable
- **Phantom-importable keys** — decrypted keys are standard 64-byte `[seed + pubkey]` format that import directly into Phantom, Solflare, or any Solana wallet
- **Bounty board** — request specific vanity words with SOL rewards; miners fulfill bounties automatically
- **Dual frontend** — Flask web UI and PySide6 desktop GUI with full feature parity
- **PID thermal controller** — automatic GPU power throttling to maintain safe temperatures during mining
- **Blind mining mode** — mine and auto-upload to the marketplace in one step
- **Profile persistence** — wallet keys and Lit Protocol credentials saved to `solvanity_profile.json` for reuse across sessions
- **PyInstaller packaging** — build a standalone `.exe` / binary with `python build.py`
- **Zero configuration** — download, install deps, run. The shared PKP and master key are baked in.

## How It Works

### Mining

The OpenCL kernel (`core/opencl/kernel.cl`, 4,000+ lines) implements Ed25519 scalar multiplication, point encoding, and Base58 conversion entirely on the GPU. Suffix patterns are compiled into the kernel as a constant buffer. Each work item:

1. Takes a 32-byte seed from the host, XORs in its global ID
2. Performs SHA-512 hashing and Ed25519 scalar clamping
3. Computes the public key point via double-and-add scalar multiplication
4. Encodes the point as a 32-byte compressed Ed25519 public key
5. Base58-encodes the last 6 characters
6. Checks against all loaded suffix patterns in parallel
7. Writes matches to a result buffer for the host to collect

The host (`core/word_miner.py`) manages multi-GPU workers via `multiprocessing`, rotating seeds each iteration cycle.

### Direct-Encrypt Key Delivery

The direct-encrypt architecture ensures all delivered keys are standard wallet-importable format:

1. **Mining** — GPU or CPU generates random seeds, derives Ed25519 keypairs via `SigningKey(seed)`, checks if `Base58(pubkey)` ends with a target word
2. **TEE Encryption** — on match, the full keypair `[seed(32) + pubkey(32)]` is base58-encoded and encrypted inside the TEE via `encrypt_private_key()`. The TEE derives an AES wrapping key using `signEcdsa` with the PKP private key (which never leaves the enclave), encrypts the keypair, and returns the ciphertext with burn-gated access conditions
3. **Upload** — the encrypted package is uploaded to a Solana PDA, an SPL token NFT (supply=1) is minted and transferred to the PDA's escrow ATA
4. **Buy** — buyer calls the on-chain program's buy instruction, which atomically transfers SOL to the seller and the NFT from the PDA to the buyer
5. **Burn & Decrypt** — buyer burns the NFT (supply → 0), then calls `decrypt_private_key()`. The TEE fetches `getTokenSupply` from Solana RPC, verifies supply=0, then decrypts and returns the base58 private key
6. **Import** — the returned key is a standard 64-byte `[seed + pubkey]` that imports directly into Phantom wallet

### Marketplace Flow

```
Seller                          Solana Devnet                    Buyer
  │                                  │                              │
  ├─ Mine vanity address (GPU/CPU)   │                              │
  ├─ TEE encrypts [seed+pubkey]      │                              │
  ├─ Mint SPL token (supply=1) ────►│                              │
  ├─ Upload encrypted JSON to PDA ─►│                              │
  ├─ Transfer NFT to PDA's ATA ───►│                              │
  │                                  │                              │
  │                                  │◄──── Buy (SOL payment) ─────┤
  │                           SOL ──►│ seller                       │
  │                                  │──── NFT to buyer ATA ──────►│
  │                                  │                              │
  │                                  │◄──── Burn NFT ──────────────┤
  │                                  │                              │
  │                            TEE verifies burn via Solana RPC     │
  │                            TEE decrypts [seed+pubkey] ────────►│
  │                                  │                    Import into Phantom
  │                                  │                    Save key file
```

### Encryption Architecture

All instances share a single **Programmable Key Pair (PKP)** whose private key exists exclusively inside the Lit Protocol TEE hardware. The wrapping key for encryption/decryption is deterministically derived inside the TEE:

```
wrappingKey = AES-import(SHA-256(signEcdsa(SHA-256("solvanity-wrap:" + conditionsJSON), pkpPublicKey)))
```

This means:
- The wrapping key is never exposed outside the TEE
- Any instance with the PKP public key can trigger encryption/decryption (the TEE holds the signing key)
- Decryption requires the TEE to verify on-chain that the NFT supply is 0 (burned) before releasing the plaintext
- The `conditionsJSON` binds the encryption to specific access control conditions
- The `pkpPublicKey` is stored in each encrypted package, making packages fully self-contained

## Security Model

**The master API key (`MARKETPLACE_LIT_API_KEY`) is intentionally public.** Here's why that's safe:

| Concern | Protection |
|---------|------------|
| Extract PKP private key | Impossible — held exclusively in TEE hardware (Intel SGX/TDX) |
| Decrypt without burning | TEE fetches `getTokenSupply` from Solana RPC and aborts if supply ≠ 0 |
| Tamper with encryption code | Hash-pinned — packages with unknown `litActionHash` are rejected by the client as "Unknown Code" |
| Forge encryption results | PKP ECDSA signature is required for wrapping key derivation; only the TEE can produce it |
| Use master key to create rogue usage keys | Usage keys can only invoke Lit Actions against the same PKP; the Lit Action code itself enforces all security checks |
| Man-in-the-middle the TEE | Lit Protocol Chipotle V3 uses attested enclaves; the REST API endpoint is TLS-secured |

The security boundary is the TEE hardware, not the API key. The API key is an authentication token for the Lit Protocol REST API — it grants the ability to *invoke* Lit Actions, but the Lit Action code itself enforces all security invariants (burn verification, address matching, key derivation).

## Setup

### Requirements

- Python 3.11+
- OpenCL-compatible GPU (NVIDIA or AMD) with drivers installed — for GPU mining
- No GPU required for CPU mining, marketplace browsing, buying, or decrypting

### Install

```bash
git clone https://github.com/aidenrichtwitter-glitch/Vanity-Address-Marketplace.git
cd Vanity-Address-Marketplace
pip install -e .
```

### Dependencies

Installed automatically via `pyproject.toml`:

| Package | Purpose |
|---------|---------|
| `pyopencl` | GPU compute (OpenCL kernel execution) |
| `pynacl` | Ed25519 cryptography (key generation) |
| `flask` | Web UI server |
| `pyside6` | Desktop GUI (Qt6) |
| `solana` / `solders` | Solana RPC client and transaction building |
| `base58` | Address encoding/decoding |
| `requests` | Lit Protocol TEE REST API calls |
| `click` | CLI argument parsing |
| `rich` | CLI output formatting |
| `gunicorn` / `gevent` | Production WSGI server |
| `pyinstaller` | Standalone executable packaging |

### Environment Variables

No environment variables are required. The shared PKP and master API key are hardcoded in `core/marketplace/config.py`.

Optional:

```
SOLANA_DEVNET_PRIVKEY     # Base58 Solana devnet private key (for selling/buying)
```

You can also configure your wallet through the Settings tab in the web UI or desktop GUI — it saves to `solvanity_profile.json`.

## Usage

### Web UI

```bash
python web_app.py
```

Opens on `http://localhost:5000`. Three tabs:

- **Word Miner** — select words, choose GPU or CPU compute, configure power/temperature limits, start/stop mining, view found addresses in real-time via SSE
- **Marketplace** — browse listed vanity addresses (TEE-verified only), buy NFTs, burn-to-decrypt, download key files, bounty board for requesting specific words
- **Settings** — configure Solana devnet wallet, generate Lit Protocol usage key (one-click), persist credentials

Mining is disabled on the hosted production version (`REPLIT_DEPLOYMENT` flag). Download the source to mine locally.

### Desktop GUI

```bash
python gui.py
```

PySide6/Qt6 application with identical functionality to the web UI. Reads from the same `solvanity_profile.json` and `core/` modules.

### CLI

```bash
# Mine for addresses ending in cool words (GPU)
python main.py search-words --min-word-length 4 --output-dir ./found_words

# Mine for specific prefix/suffix patterns (GPU)
python main.py search-pubkey --starts-with SoL --ends-with Pay

# List available OpenCL devices
python main.py show-device

# List all valid words in the dictionary
python main.py list-words --min-length 3
```

### Blind Mining

Blind mining mode combines mining and marketplace upload into one step:

1. Open the Word Miner tab
2. Switch to "Blind" mining mode
3. Enter your seller wallet address and price per address
4. Start mining — each found address is immediately encrypted in the TEE, an NFT is minted, and the package is uploaded to a Solana PDA
5. The private key is encrypted before upload and can only be decrypted after an on-chain NFT burn

### Building a Standalone Executable

```bash
python build.py
```

Produces `dist/solvanity.exe` (Windows) or `dist/solvanity` (Linux/macOS) via PyInstaller. Bundles the OpenCL kernel, wordlist, templates, and all dependencies.

## Project Structure

```
├── web_app.py                          # Flask web application
├── gui.py                              # PySide6 desktop GUI (2,800+ lines)
├── main.py                             # CLI entry point (search-pubkey, search-words, show-device, list-words)
├── build.py                            # PyInstaller build script
├── wordlist_3000.txt                   # Extended dictionary of target words
├── bounties.json                       # Bounty board state (JSON)
├── solvanity_profile.json              # User credentials (wallet key, Lit keys)
├── pyproject.toml                      # Python project config and dependencies
├── LICENSE                             # GPL-3.0
│
├── core/
│   ├── backend.py                      # Shared backend (marketplace search/buy/burn, bounties, blind upload)
│   ├── word_miner.py                   # Multi-GPU worker management, PID thermal controller
│   ├── word_filter.py                  # Suffix matching — last 6 chars with X-padding
│   ├── words.py                        # 3,000-word dictionary (Base58-valid English words)
│   ├── searcher.py                     # OpenCL kernel execution, result collection
│   ├── config.py                       # HostSetting, iteration bits, work sizes
│   ├── cli.py                          # Click CLI commands
│   │
│   ├── opencl/
│   │   ├── kernel.cl                   # GPU kernel — Ed25519 scalar mult, Base58 encode, suffix match (4,000+ lines)
│   │   └── manager.py                  # OpenCL platform/device enumeration
│   │
│   ├── marketplace/
│   │   ├── config.py                   # Program ID, PDA seeds, discriminators, PKP, master key, RPC URL
│   │   ├── lit_encrypt.py              # Lit Protocol TEE operations — encrypt, decrypt, key management
│   │   ├── lit_action.js               # Lit Action JavaScript (runs inside TEE)
│   │   ├── nft.py                      # SPL token mint, burn, ATA creation, batch balance checks
│   │   └── solana_client.py            # Solana RPC client — PDA derivation, upload, buy, fetch packages
│   │
│   └── utils/
│       ├── crypto.py                   # Ed25519 utilities
│       ├── gpu_temp.py                 # GPU temperature monitoring (pynvml/nvidia-smi)
│       └── helpers.py                  # Suffix buffer construction, kernel source loading
│
├── templates/
│   └── index.html                      # Web UI — single-page tabbed interface (1,400+ lines)
│
├── static/
│   └── style.css                       # Dark theme stylesheet
│
├── tests/
│   ├── e2e_trustless.py                # 15-step end-to-end test (mine → encrypt → upload → buy → burn → decrypt → verify Phantom-importable)
│   ├── test_real_onchain.py            # Real on-chain burn+decrypt test with Phantom key validation
│   ├── test_phantom_import.py          # Keypair.from_bytes() format validation
│   └── test_split_key_merge.py         # Legacy split-key merge math tests (historical reference)
│
└── anchor_program/
    └── programs/blind_vanity/src/
        └── lib.rs                      # Solana on-chain program (native, not Anchor framework)
```

## On-Chain Program

**Program ID:** `5saJBeNvrbQ4WcVueFietuBxAixnV1u8StXUriXUuFj5` (Solana devnet)

**PDA Derivation:** `Pubkey::find_program_address(&[b"vanity_pkg", vanity_pubkey.as_ref()], program_id)`

### Instructions

| Instruction | Discriminator (hex) | Accounts | Description |
|-------------|-------------------|----------|-------------|
| Upload | `a56967a8e5d6b1fb` | `[pda, authority☑, system_program]` | Creates/resizes PDA, stores encrypted JSON + authority + price. Authority must sign. |
| Buy | `b27a78b9f6e7c20c` | `[pda, buyer☑, seller, mint, pda_ata, buyer_ata, token_program, system_program, ata_program]` | Validates seller matches PDA authority, transfers SOL to seller, creates buyer ATA if needed, transfers NFT from PDA's ATA to buyer's ATA via PDA-signed `invoke_signed`. |

☑ = signer required

**Account Discriminator:** `184662bf3a907b9e` (first 8 bytes of every PDA account)

### PDA Data Layout

| Offset | Size | Field |
|--------|------|-------|
| 0 | 8 | Account discriminator (`0x184662bf3a907b9e`) |
| 8 | 32 | Vanity pubkey |
| 40 | 4 | JSON length (little-endian u32) |
| 44 | N | Encrypted JSON package (ciphertext, IV, wrapped key, mint address, seller, price, Lit Action hash) |
| 44+N | 32 | Authority pubkey (seller who uploaded) |
| 76+N | 1 | PDA bump seed |
| 77+N | 8 | Price in lamports (little-endian u64) |

### Encrypted JSON Package Fields

Each package stored in the PDA contains:

| Field | Description |
|-------|-------------|
| `ciphertext` | AES-GCM encrypted private key (Base64) |
| `iv` | AES-GCM initialization vector (Base64) |
| `wrappedKey` | Data key wrapped with PKP-derived wrapping key (Base64) |
| `wrapIv` | Wrapping IV (Base64) |
| `dataToEncryptHash` | SHA-256 of the conditions JSON (hex) |
| `mintAddress` | SPL token mint address |
| `sellerAddress` | Seller's Solana pubkey |
| `priceLamports` | Listing price |
| `vanityWord` | The matched word |
| `litActionHash` | SHA-256 of the Lit Action code used for encryption |
| `pkpPublicKey` | The PKP public key (makes package self-contained for cross-instance decrypt) |
| `encryptedInTEE` | Boolean flag |

## Shared Constants

These are hardcoded in `core/marketplace/config.py` and are intentionally public:

```python
PROGRAM_ID = "5saJBeNvrbQ4WcVueFietuBxAixnV1u8StXUriXUuFj5"
MARKETPLACE_PKP_PUBLIC_KEY = "03137256bae2971c2db56a4302a5d288c51461899097df5fd457b0b6d1f675dcf6"
MARKETPLACE_LIT_API_KEY = "GK4rv4T/ZgPgVNBgIDwzKx1vdM8L/buH+748DqUhIEY="
RPC_URL = "https://api.devnet.solana.com"
LIT_API_BASE = "https://api.dev.litprotocol.com/core/v1"
```

See [Security Model](#security-model) for why shipping these publicly is safe.

## Testing

```bash
# Full 15-step end-to-end test (mines, encrypts, uploads, buys, burns, decrypts on devnet)
# Validates the decrypted key is Phantom-importable via Keypair.from_bytes() + TX signing
python tests/e2e_trustless.py

# Offline mode (skips Solana devnet transactions, validates crypto flow only)
python tests/e2e_trustless.py --offline

# Real on-chain burn+decrypt test (requires owned NFT + funded wallet)
python tests/test_real_onchain.py

# Phantom import format validation (offline)
python -m pytest tests/test_phantom_import.py -v
```

The e2e test validates the full two-person trustless flow: seller and buyer each get independent usage keys from the shared master account, mine a vanity address, encrypt the full `[seed+pubkey]` keypair in the TEE, upload to a PDA with an NFT, buy via the on-chain program, verify pre-burn decryption is rejected, burn the NFT, decrypt, and confirm the decrypted key passes `Keypair.from_bytes()` and can sign Solana transactions. **All 15 steps pass on Solana devnet.**

## License

GPL-3.0 — see [LICENSE](LICENSE) for full text.
