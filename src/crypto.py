import hashlib
import os

import base58
import nacl.signing


def generate_keypair():
    signing_key = nacl.signing.SigningKey.generate()
    verify_key = signing_key.verify_key
    public_key_bytes = bytes(verify_key)
    private_key_bytes = bytes(signing_key)
    address = base58.b58encode(public_key_bytes).decode("ascii")
    return private_key_bytes, public_key_bytes, address


def keypair_from_seed(seed_bytes):
    signing_key = nacl.signing.SigningKey(seed_bytes)
    verify_key = signing_key.verify_key
    public_key_bytes = bytes(verify_key)
    private_key_bytes = bytes(signing_key)
    address = base58.b58encode(public_key_bytes).decode("ascii")
    return private_key_bytes, public_key_bytes, address


def export_keypair(private_key_bytes, public_key_bytes):
    full_key = private_key_bytes + public_key_bytes
    return list(full_key)


def save_keypair(filepath, private_key_bytes, public_key_bytes, address, words_found=None):
    key_json = export_keypair(private_key_bytes, public_key_bytes)
    with open(filepath, "a") as f:
        f.write(f"Address: {address}\n")
        if words_found:
            f.write(f"Words found: {', '.join(words_found)}\n")
        f.write(f"Secret key: {key_json}\n")
        f.write("-" * 80 + "\n")
