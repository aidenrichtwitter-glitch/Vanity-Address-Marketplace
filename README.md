# Solana Devnet Blind Vanity Address Marketplace

A marketplace where users grind Solana vanity keypairs using a GPU miner, encrypt private keys with Lit Protocol ('datil' network), store encrypted packages on-chain in deterministic PDAs via an Anchor program, and buyers can discover/decrypt packages if they meet Lit access conditions (wallet balance > 0 SOL on devnet).

## Architecture

### Components

1. **GPU Vanity Miner** (`gpu-miner/`) - Python + OpenCL GPU-accelerated vanity address mining tool with PySide6 GUI
2. **Client Scripts** (`client/`) - JavaScript/Node.js scripts for buying, claiming, and decrypting vanity packages
3. **On-chain Program** (`programs/blind_vanity/`) - Rust/Anchor program deployed on Solana devnet

### How It Works

1. **Mine** - GPU miner generates Solana keypairs, searching for addresses ending in dictionary words (e.g., `...XXomen`, `...dragon`)
2. **Encrypt** - Private key is encrypted with Lit Protocol using `solRpcConditions` (buyer must have SOL balance > 0)
3. **Upload** - Encrypted package stored in a deterministic PDA on Solana devnet
4. **Buy/Claim** - Buyer discovers PDA, meets access conditions, decrypts private key

### Key Details

- **Program ID**: `EHS97x7xVo4svEVrEsVnihXgPLozCFs1BH7Bnkuf2nP6`
- **Lit Network**: `datil` only (never `datil-dev`)
- **PDA Seed**: `b"vanity_pkg"` + vanity_pubkey bytes
- **Access Condition**: `solRpcCondition getBalance > 0` on `solanaDevnet`

## Project Structure

```
gpu-miner/                   # GPU vanity address miner
  main.py                    # CLI entry point
  gui.py                     # PySide6 GUI application
  build.py                   # PyInstaller build script
  wordlist_3000.txt          # Word list for word mining
  core/                      # Core mining modules
    cli.py                   # CLI search commands
    config.py                # Host/GPU settings
    searcher.py              # GPU searcher (OpenCL)
    word_miner.py            # Word mining engine
    word_filter.py           # Suffix word detection
    words.py                 # Word list loader
    opencl/
      kernel.cl              # Ed25519 + Base58 GPU kernel (3800+ lines)
      manager.py             # OpenCL device management
    utils/
      crypto.py              # Ed25519 keypair generation
      gpu_temp.py            # GPU temperature monitoring
      helpers.py             # Kernel loading, Base58 validation

client/                      # Marketplace client scripts
  idl.json                   # Anchor IDL for the on-chain program
  blind_vanity_grinder.py    # Python grinder + Lit encrypt + PDA upload
  buy.js                     # Buy vanity package
  claim.js                   # Claim/decrypt from PDA
  buyer_decrypt.js           # Buyer decrypt script

programs/blind_vanity/       # On-chain Anchor program
  Cargo.toml
  src/lib.rs                 # VanityPackage PDA with upload instruction
```

## GPU Miner Setup

Requires an OpenCL-capable GPU (NVIDIA or AMD).

```bash
cd gpu-miner
pip install pyopencl pynacl base58 click PySide6 pynvml
python main.py              # CLI mode
python gui.py               # GUI mode
python build.py             # Build standalone executable
```

## Client Setup

```bash
cd client
npm install
node buyer_decrypt.js       # Decrypt a vanity package from PDA
node claim.js               # Claim from PDA
node buy.js                 # Buy a vanity package
```

## Technical Notes

- **Anchor TS Bug Workaround**: Uses raw `TransactionInstruction` + `BorshInstructionCoder` instead of `new Program()` constructor
- **Discriminator**: Read from IDL as byte array via `Buffer.from(ixDef.discriminator)`, no bs58 decode
- **Vec<u8>**: Must be `Buffer` instance, not `Array<number>`
- **Devnet Lag**: PDA may be invisible for 30-120s after confirmation (normal devnet behavior)

## License

See `gpu-miner/LICENSE` for GPU miner license. Other components are ISC licensed.
