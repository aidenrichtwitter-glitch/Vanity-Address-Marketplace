# Solana Devnet Blind Vanity Address Marketplace

## Overview
A marketplace where users grind Solana vanity keypairs using a GPU miner, encrypt private keys with Lit Protocol ('datil' network), store encrypted packages on-chain in deterministic PDAs via an Anchor program, and buyers can discover/decrypt packages if they meet Lit access conditions (wallet balance > 0 SOL on devnet).

## Architecture

### Components
1. **GPU Vanity Miner** (`gpu-miner/`) - Python + OpenCL GPU-accelerated vanity address mining tool
2. **Client Scripts** (`client/`) - JavaScript/Node.js scripts for buying, claiming, and decrypting vanity packages
3. **On-chain Program** (`programs/blind_vanity/`) - Rust/Anchor program deployed on Solana devnet

### Key Details
- **Program ID**: `EHS97x7xVo4svEVrEsVnihXgPLozCFs1BH7Bnkuf2nP6`
- **Lit Network**: `datil` (never `datil-dev`)
- **PDA Seed**: `b"vanity_pkg"` + vanity_pubkey bytes
- **Access Condition**: `solRpcCondition getBalance > 0` on `solanaDevnet`

### File Structure
```
/
├── gpu-miner/               # GPU vanity address miner
│   ├── main.py              # CLI entry point
│   ├── gui.py               # PySide6 GUI application
│   ├── build.py             # PyInstaller build script
│   ├── pyproject.toml       # Python dependencies
│   ├── wordlist_3000.txt    # Word list for word mining
│   └── core/                # Core mining modules
│       ├── cli.py           # CLI search commands
│       ├── config.py        # Host/GPU settings
│       ├── searcher.py      # GPU searcher (OpenCL)
│       ├── word_miner.py    # Word mining engine
│       ├── word_filter.py   # Suffix word detection
│       ├── words.py         # Word list loader
│       ├── opencl/          # OpenCL kernel and device manager
│       │   ├── kernel.cl    # Ed25519 + Base58 GPU kernel
│       │   └── manager.py   # OpenCL device management
│       └── utils/           # Utilities
│           ├── crypto.py    # Ed25519 keypair generation
│           ├── gpu_temp.py  # GPU temperature monitoring
│           └── helpers.py   # Kernel loading, Base58 validation
├── client/                  # Marketplace client scripts
│   ├── package.json         # Node.js dependencies
│   ├── idl.json             # Anchor IDL for the on-chain program
│   ├── blind_vanity_grinder.py  # Python grinder + Lit encrypt + PDA upload
│   ├── buy.js               # Buy vanity package
│   ├── claim.js             # Claim/decrypt from PDA
│   └── buyer_decrypt.js     # Buyer decrypt script
├── programs/                # On-chain Anchor program
│   └── blind_vanity/
│       ├── Cargo.toml
│       └── src/lib.rs       # Anchor program with VanityPackage PDA
├── main.py                  # GitHub integration check script
└── push_to_github.py        # GitHub push automation
```

### Technical Notes
- **Anchor TS Bug**: Never use `new Program()` constructor — use raw `TransactionInstruction` + `BorshInstructionCoder`
- **Discriminator**: Read from IDL as byte array: `Buffer.from(ixDef.discriminator)`, no bs58 decode
- **Vec<u8>**: Must be `Buffer` instance, not `Array<number>`
- **Devnet Lag**: PDA may be invisible for 30-120s after confirmation — normal behavior

### GitHub Repository
- **URL**: `https://github.com/aidenrichtwitter-glitch/Vanity-Address-Marketplace`
- **GitHub Connector**: `connection:conn_github_01KJK8NZ32BH1D8K4MSN3538Y2`

### Dependencies
- Python 3.11 (GPU miner)
- Node.js 20 (client scripts)
- replit-connectors (GitHub integration)
