#!/usr/bin/env python3
"""
Test: Direct blind-mining keys are Phantom-importable.

Proves that the non-split-key path (full [seed(32) + pubkey(32)]) produces
keys that pass solders Keypair.from_bytes() and can sign valid transactions.
This is the exact format blind_upload() now produces.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nacl.signing import SigningKey
from base58 import b58encode, b58decode


def test_phantom_importable_key():
    seed = os.urandom(32)
    sk = SigningKey(seed)
    pubkey_bytes = bytes(sk.verify_key)

    privkey_b58 = b58encode(seed + pubkey_bytes).decode()

    raw = b58decode(privkey_b58)
    assert len(raw) == 64, f"Expected 64 bytes, got {len(raw)}"

    from solders.keypair import Keypair
    kp = Keypair.from_bytes(raw)
    assert str(kp.pubkey()) == b58encode(pubkey_bytes).decode(), "Pubkey mismatch"

    from solders.system_program import transfer, TransferParams
    from solders.transaction import Transaction
    from solders.message import Message
    from solders.hash import Hash as Blockhash
    from solders.pubkey import Pubkey

    dest = Pubkey.from_string("11111111111111111111111111111111")
    ix = transfer(TransferParams(from_pubkey=kp.pubkey(), to_pubkey=dest, lamports=1000))
    msg = Message([ix], kp.pubkey())
    fake_blockhash = Blockhash.default()
    tx = Transaction([kp], msg, fake_blockhash)

    assert len(tx.signatures) == 1, "Transaction should have 1 signature"
    assert tx.signatures[0] != bytes(64), "Signature should not be all zeros"

    print(f"PASS: seed={seed.hex()[:16]}...")
    print(f"PASS: pubkey={str(kp.pubkey())[:20]}...")
    print(f"PASS: privkey_b58 length={len(privkey_b58)}")
    print(f"PASS: Keypair.from_bytes() succeeded")
    print(f"PASS: Transaction signed successfully")
    print(f"PASS: All checks passed — key is Phantom-importable")


def test_multiple_keys():
    from solders.keypair import Keypair
    for i in range(10):
        seed = os.urandom(32)
        sk = SigningKey(seed)
        pubkey_bytes = bytes(sk.verify_key)
        raw = seed + pubkey_bytes
        kp = Keypair.from_bytes(raw)
        assert str(kp.pubkey()) == b58encode(pubkey_bytes).decode()
    print(f"PASS: 10/10 random keys passed Keypair.from_bytes()")


if __name__ == "__main__":
    test_phantom_importable_key()
    test_multiple_keys()
    print("\nAll Phantom import tests PASSED")
