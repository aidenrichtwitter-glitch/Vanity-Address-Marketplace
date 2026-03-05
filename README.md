# SolVanity Word Miner

GPU-accelerated Solana vanity address generator with a trustless blind marketplace. Mine addresses ending in dictionary words, list them as NFTs, and sell them — buyers burn the NFT to decrypt the private key inside a TEE. No shared secrets, no account creation, no trust required.

## Features

- **GPU-accelerated mining** — OpenCL kernel generates Ed25519 keypairs and performs Base58 suffix matching on-device
- **3,000-word dictionary** — matches English words at the end of Solana addresses with configurable "X" padding and character substitutions (1→l, 0→o, etc.)
- **Split-key Ed25519 protocol** — neither the GPU miner nor the TEE ever holds the complete private key alone
- **Lit Protocol Chipotle V3 TEE encryption** — private keys are encrypted inside Intel SGX/TDX hardware enclaves
- **NFT burn-to-decrypt** — buyers must burn a Solana SPL token on-chain before the TEE releases the decrypted key
- **On-chain marketplace** — encrypted packages stored in Solana devnet PDAs with atomic buy transactions
- **Hash-pinned code verification** — Lit Action code is SHA-256 hashed; only packages matching trusted hashes are tradeable
- **Bounty board** — request specific vanity words with SOL rewards
- **Dual frontend** — Flask web UI and PySide6 desktop GUI with full feature parity
- **PID thermal controller** — automatic GPU clock management to maintain safe temperatures during mining
- **Zero configuration** — download, install dependencies, run. The shared PKP and master key are baked in.

## How It Works

### Split-Key Protocol

The split-key Ed25519 protocol ensures no single party ever holds the complete private key:

1. **TEE Setup** — The TEE generates a random scalar `t` and its corresponding curve point `T = t·G`. The scalar `t` is AES-GCM encrypted with a wrapping key derived from the PKP via `signEcdsa`. The encrypted scalar and point `T` are returned to the miner.
2. **GPU Mining** — The OpenCL kernel generates random scalars `s` and computes combined public keys `P = s·G + T`. It checks if `Base58(P)` ends with a target word. On match, it returns `s` and `P`.
3. **TEE Combine & Encrypt** — The miner sends `s` and the wrapped `t` back to the TEE. Inside the enclave, `t` is unwrapped, the full private key `k = s + t mod L` is computed, the address is verified, and `k` is immediately AES-GCM encrypted under a PKP-derived wrapping key. The plaintext `k` never leaves the TEE.

### Marketplace Flow

```
Seller                          Solana Devnet                    Buyer
  │                                  │                              │
  ├─ Mine vanity address (GPU)       │                              │
  ├─ TEE encrypts private key ──────►│ Upload to PDA               │
  ├─ Mint SPL token NFT ───────────►│ NFT in PDA's ATA            │
  │                                  │                              │
  │                                  │◄──────── Buy (SOL payment)──┤
  │                                  │ ─── NFT transferred ───────►│
  │                                  │                              │
  │                                  │◄──────── Burn NFT ──────────┤
  │                                  │                              │
  │                                  │  TEE verifies burn on-chain  │
  │                                  │  TEE decrypts key ─────────►│
  │                                  │                              ├─ Save key file
```

### Encryption Architecture

All instances share a single **Programmable Key Pair (PKP)** whose private key exists exclusively inside the Lit Protocol TEE hardware. The wrapping key for encryption/decryption is deterministically derived inside the TEE:

```
wrappingKey = AES-import(SHA-256(signEcdsa(SHA-256("solvanity-wrap:" + conditions), pkpPublicKey)))
```

This means:
- The wrapping key is never exposed outside the TEE
- Any instance with the PKP public key can trigger encryption/decryption (the TEE holds the signing key)
- Decryption requires the TEE to verify on-chain that the NFT was burned before releasing the plaintext

## Security Model

**The master API key (`MARKETPLACE_LIT_API_KEY`) is intentionally public.** Here's why that's safe:

| Concern | Protection |
|---------|------------|
| Extract PKP private key | Impossible — held exclusively in TEE hardware |
| Decrypt without burning | TEE verifies burn transaction on Solana RPC before decrypting |
| Tamper with encryption code | Hash-pinned — packages with unknown `litActionHash` are rejected as unverified |
| Forge encryption results | PKP signature is required for wrapping key derivation; only TEE can produce it |
| Use master key to create rogue usage keys | Usage keys can only run Lit Actions against the same PKP with the same burn checks |

The security boundary is the TEE hardware, not the API key. The API key is an authentication token for the Lit Protocol REST API — it grants the ability to *invoke* Lit Actions, but the Lit Action code itself enforces all security invariants.

**Legacy packages** (encrypted before the PKP-signed system) are tagged "Legacy (Insecure)" and filtered out of marketplace search results. Their template hashes are tracked in `_LEGACY_TEMPLATE_HASHES` but excluded from the trusted set.

## Setup

### Requirements

- Python 3.11+
- OpenCL-compatible GPU (NVIDIA or AMD) with drivers installed
- Solana devnet wallet (for marketplace operations)

### Install

```bash
git clone https://github.com/aidenrichtwitter-glitch/Vanity-Address-Marketplace.git
cd Vanity-Address-Marketplace
pip install -e .
```

### Dependencies

Installed automatically via `pyproject.toml`:

- `pyopencl` — GPU compute
- `pynacl` — Ed25519 cryptography
- `flask` — web UI server
- `pyside6` — desktop GUI
- `solana` / `solders` — Solana RPC and transaction building
- `base58` — address encoding
- `requests` — Lit Protocol REST API calls
- `pynvml` — NVIDIA GPU temperature monitoring

### Environment Variables (Optional)

Copy `.env.example` and fill in as needed:

```
SOLANA_DEVNET_PRIVKEY=     # Base58 Solana devnet private key (for selling/buying)
```

No Lit Protocol keys are needed — the master key and PKP are hardcoded in `core/marketplace/config.py`.

## Usage

### Web UI

```bash
python web_app.py
```

Opens on `http://localhost:5000`. Three tabs:

- **Word Miner** — select words, configure GPU workers, start/stop mining, view found addresses
- **Marketplace** — browse listed addresses, buy NFTs, burn-to-decrypt, bounty board
- **Settings** — configure Solana wallet, generate Lit Protocol usage key

### Desktop GUI

```bash
python gui.py
```

PySide6/Qt application with identical functionality to the web UI.

### CLI

```bash
python main.py
```

### Mining

1. Open the Word Miner tab
2. Select target words from the 3,000-word dictionary
3. Configure GPU workers and iteration bits
4. Click "Start Mining"
5. Found addresses appear in the results table with their vanity word match

### Selling

1. Configure your Solana devnet wallet in Settings
2. Generate a Lit Protocol usage key (one-click, uses the shared master account)
3. Select a found address and click "Upload to Marketplace"
4. Set your price in SOL
5. The address is encrypted in the TEE, an NFT is minted, and both are uploaded to a Solana PDA

### Buying & Decrypting

1. Browse the marketplace for addresses you want
2. Click "Buy" — SOL is transferred to the seller, NFT is transferred to you
3. Click "Burn & Decrypt" — the NFT is burned on-chain
4. The TEE verifies the burn and decrypts the private key
5. The key is saved directly to a file (never displayed in the browser)

## Project Structure

```
├── web_app.py                          # Flask web application (907 lines)
├── gui.py                              # PySide6 desktop GUI
├── main.py                             # CLI entry point
├── build.py                            # PyInstaller build script
├── wordlist_3000.txt                   # Dictionary of target words
├── bounties.json                       # Bounty board data
├── pyproject.toml                      # Python dependencies
├── LICENSE                             # GPL-3.0
│
├── core/
│   ├── backend.py                      # Shared backend (mining state, marketplace ops)
│   ├── word_miner.py                   # GPU worker management, PID thermal controller
│   ├── word_filter.py                  # Word matching with substitutions and X-padding
│   ├── words.py                        # Word list loader
│   ├── searcher.py                     # Address search engine
│   ├── config.py                       # Mining configuration constants
│   ├── cli.py                          # CLI interface
│   │
│   ├── opencl/
│   │   ├── manager.py                  # OpenCL device management
│   │   └── kernel.cl                   # GPU kernel (Ed25519 + Base58 suffix match)
│   │
│   ├── marketplace/
│   │   ├── config.py                   # Program ID, PKP, master key, RPC URL
│   │   ├── lit_encrypt.py              # Lit Protocol TEE operations (encrypt/decrypt/split-key)
│   │   ├── lit_action.js               # Lit Action code (runs inside TEE)
│   │   ├── nft.py                      # SPL token minting, burning, ATA management
│   │   └── solana_client.py            # Solana RPC client, PDA derivation, transactions
│   │
│   └── utils/
│       ├── crypto.py                   # Ed25519 key utilities
│       ├── gpu_temp.py                 # GPU temperature monitoring (pynvml)
│       └── helpers.py                  # Miscellaneous utilities
│
├── templates/
│   └── index.html                      # Web UI (single-page, tabbed interface)
│
├── static/
│   └── style.css                       # Dark theme stylesheet
│
├── tests/
│   ├── e2e_trustless.py                # 16-step end-to-end marketplace test
│   ├── test_split_key.py               # Split-key protocol unit tests
│   └── test_split_key_integration.py   # Split-key integration tests (live TEE)
│
└── anchor_program/
    └── programs/blind_vanity/src/
        └── lib.rs                      # Solana on-chain program (upload + buy instructions)
```

## On-Chain Program

**Program ID:** `5saJBeNvrbQ4WcVueFietuBxAixnV1u8StXUriXUuFj5` (Solana devnet)

**PDA Derivation:** `["vanity_pkg", vanity_pubkey_bytes]`

**Instructions:**

| Instruction | Discriminator | Description |
|-------------|--------------|-------------|
| Upload | `a56967a8e5d6b1fb` | Creates PDA, stores encrypted JSON, mints NFT, sets price |
| Buy | `b27a78b9f6e7c20c` | Transfers SOL to seller, transfers NFT to buyer, updates PDA owner |

**Account Discriminator:** `184662bf3a907b9e` (first 8 bytes of every PDA account)

**PDA Layout:**
- 8 bytes: account discriminator
- 32 bytes: seller pubkey
- 32 bytes: owner pubkey (updated on buy)
- 32 bytes: vanity pubkey
- 32 bytes: NFT mint address
- 8 bytes: price in lamports
- 1 byte: status (0=Active, 1=Sold)
- 4 bytes: JSON length (little-endian u32)
- N bytes: encrypted JSON package

## Shared Constants

These are hardcoded in `core/marketplace/config.py` and are intentionally public:

```python
MARKETPLACE_PKP_PUBLIC_KEY = "03137256bae2971c2db56a4302a5d288c51461899097df5fd457b0b6d1f675dcf6"
MARKETPLACE_LIT_API_KEY = "GK4rv4T/ZgPgVNBgIDwzKx1vdM8L/buH+748DqUhIEY="
```

See [Security Model](#security-model) for why shipping these publicly is safe.

## Testing

```bash
# Unit tests
python -m pytest tests/test_split_key.py -v

# Integration tests (requires network access to Lit Protocol + Solana devnet)
python -m pytest tests/test_split_key_integration.py -v

# Full 16-step end-to-end test (mines, encrypts, uploads, buys, burns, decrypts)
python tests/e2e_trustless.py
```

## License

GPL-3.0 — see [LICENSE](LICENSE) for full text.
