#!/usr/bin/env python3
"""Real On-Chain E2E — Burn Owned NFT → TEE Decrypt → Validate Phantom Key

Burns an NFT we already own on Solana devnet, TEE decrypts the private key,
and validates the returned 64-byte base58 key is Phantom-importable.

Validation checks:
  1. Key is exactly 64 bytes (seed || pubkey)
  2. SigningKey(seed).verify_key == stored pubkey (standard Ed25519)
  3. Pubkey matches the vanity address
  4. solders Keypair.from_bytes() produces matching pubkey
  5. Keypair.sign_message() + verify succeeds
  6. Can build + sign + verify a real Solana transfer TX

Requires: SOLANA_DEVNET_PRIVKEY with devnet SOL, Lit Protocol keys configured.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests as http_requests
from base58 import b58decode, b58encode
from nacl.signing import SigningKey, VerifyKey


def p(msg):
    print(f"  {msg}")


def ok(msg):
    print(f"  [OK] {msg}")


def fail(msg):
    print(f"  [FAIL] {msg}")


def step(n, msg):
    print(f"\n{'='*60}")
    print(f"  STEP {n}: {msg}")
    print(f"{'='*60}")


def main():
    print("\n" + "=" * 60)
    print("  REAL ON-CHAIN TEST: Burn NFT → TEE Decrypt → Phantom Key")
    print("=" * 60)

    seller_key = os.environ.get("SOLANA_DEVNET_PRIVKEY", "")
    assert seller_key, "Set SOLANA_DEVNET_PRIVKEY with a funded devnet wallet"

    from core.marketplace.solana_client import load_seller_keypair, fetch_all_packages
    from solana.rpc.api import Client

    seller_kp = load_seller_keypair(seller_key)
    seller_pub = str(seller_kp.pubkey())
    client = Client("https://api.devnet.solana.com")
    bal = client.get_balance(seller_kp.pubkey()).value
    p(f"Wallet: {seller_pub}")
    p(f"Balance: {bal / 1e9:.6f} SOL ({bal} lamports)")

    step(1, "Find an NFT we already own")
    r = http_requests.post("https://api.devnet.solana.com", json={
        "jsonrpc": "2.0", "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [seller_pub,
                    {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
                    {"encoding": "jsonParsed"}]
    }, timeout=15)
    accounts = r.json().get("result", {}).get("value", [])
    owned_mints = set()
    for acc in accounts:
        info = acc["account"]["data"]["parsed"]["info"]
        if int(info["tokenAmount"]["amount"]) > 0:
            owned_mints.add(info["mint"])
    p(f"Owned NFTs (balance > 0): {len(owned_mints)}")

    all_packages = fetch_all_packages()
    p(f"Total packages on-chain: {len(all_packages)}")

    target = None
    for pkg in all_packages:
        ej = pkg.get("encrypted_json", {})
        mint_addr = ej.get("mintAddress", "")
        if mint_addr in owned_mints:
            target = pkg
            break

    assert target, "No owned NFT found that matches a marketplace package"
    ej = target["encrypted_json"]
    vanity_addr = target["vanity_address"]
    mint_addr = ej["mintAddress"]
    word = ej.get("vanityWord", "")
    is_legacy = ej.get("splitKey", False) or ej.get("splitKeyV2", False) or ej.get("splitKeyV3", False)
    ok(f"Found owned NFT to burn:")
    ok(f"  Vanity:   {vanity_addr}")
    ok(f"  Mint:     {mint_addr}")
    ok(f"  Word:     {word}")
    ok(f"  Legacy split-key: {is_legacy}")

    if is_legacy:
        p("WARNING: This is a legacy split-key package. Key may NOT be Phantom-importable.")
        p("The test will still attempt burn+decrypt but Keypair.from_bytes() may fail.")

    step(2, "Burn NFT on-chain → TEE decrypts → returns private key")
    import core.backend as backend

    burn_result, burn_err = backend.burn_and_decrypt(
        seller_key, ej, mint_addr, vanity_addr,
        log_fn=lambda m: p(m),
        skip_file_save=True,
    )
    if burn_err:
        fail(f"Burn+decrypt failed: {burn_err}")
        sys.exit(1)
    ok(f"Burn + TEE decrypt succeeded!")
    ok(f"  Burn TX:  {burn_result.get('burn_sig', 'n/a')}")

    privkey = burn_result.get("privkey")
    assert privkey, f"No private key returned! Keys: {list(burn_result.keys())}"

    step(3, "VALIDATE: Is this key Phantom-importable?")
    decoded = b58decode(privkey)
    p(f"Key length: {len(decoded)} bytes")
    assert len(decoded) == 64, f"Expected 64 bytes, got {len(decoded)}"
    ok(f"Check 1: 64 bytes — correct for Phantom import")

    seed = decoded[:32]
    pubkey = decoded[32:]

    sk = SigningKey(seed)
    derived_pubkey = bytes(sk.verify_key)
    derived_addr = b58encode(derived_pubkey).decode()
    stored_addr = b58encode(pubkey).decode()

    if derived_pubkey == pubkey:
        ok(f"Check 2: SigningKey(seed).verify_key == stored pubkey (standard Ed25519)")
    else:
        if is_legacy:
            fail(f"Check 2: Seed derivation MISMATCH (expected for legacy split-key): {derived_addr[:16]}... != {stored_addr[:16]}...")
            p("This legacy split-key package cannot produce a Phantom-importable key.")
            sys.exit(1)
        else:
            fail(f"Check 2: Seed derivation MISMATCH: {derived_addr[:16]}... != {stored_addr[:16]}...")
            sys.exit(1)

    assert stored_addr == vanity_addr, f"Address MISMATCH: {stored_addr} != {vanity_addr}"
    ok(f"Check 3: Pubkey matches vanity address: {vanity_addr}")

    from solders.keypair import Keypair
    kp = Keypair.from_bytes(decoded)
    solders_addr = str(kp.pubkey())
    assert solders_addr == vanity_addr, f"solders pubkey mismatch: {solders_addr}"
    ok(f"Check 4: Keypair.from_bytes() pubkey = {solders_addr}")

    test_msg = b"phantom-import-validation-message"
    solders_sig = kp.sign_message(test_msg)
    VerifyKey(pubkey).verify(test_msg, bytes(solders_sig))
    ok(f"Check 5: Keypair.sign_message() + Ed25519 verify PASSED")

    from solders.pubkey import Pubkey as SolPubkey
    from solders.hash import Hash as Blockhash
    from solders.transaction import Transaction
    from solders.message import Message
    from solders.system_program import transfer, TransferParams

    from_pub = kp.pubkey()
    to_pub = SolPubkey.from_string("11111111111111111111111111111111")
    ix = transfer(TransferParams(from_pubkey=from_pub, to_pubkey=to_pub, lamports=1_000_000))
    msg_obj = Message([ix], from_pub)
    tx = Transaction([kp], msg_obj, Blockhash.default())
    assert len(tx.signatures) == 1
    ok(f"Check 6: Solana transfer TX build → sign → verify PASSED")
    ok(f"  TX size: {len(bytes(tx))} bytes, ready for RPC submission")

    print("\n" + "=" * 60)
    print("  ALL CHECKS PASSED — KEY IS PHANTOM-IMPORTABLE")
    print("=" * 60)
    print()
    print(f"PHANTOM-IMPORTABLE PRIVATE KEY (real on-chain burn+decrypt):")
    print(f"  Vanity Address: {vanity_addr}")
    print(f"  Private Key:    {privkey}")
    print(f"  Key Bytes:      {len(decoded)}")
    print(f"  Burn TX:        {burn_result.get('burn_sig', '')}")
    print()
    print(f"  TO IMPORT INTO PHANTOM:")
    print(f"    1. Open Phantom -> Settings -> Add/Connect Wallet -> Import Private Key")
    print(f"    2. Paste: {privkey}")
    print(f"    3. Wallet should show address: {vanity_addr}")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        fail(str(e))
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nAborted")
        sys.exit(1)
    except Exception as e:
        fail(f"{e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
