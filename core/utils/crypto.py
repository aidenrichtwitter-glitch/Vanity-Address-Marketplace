import json
import logging
from pathlib import Path

from base58 import b58encode
from nacl.signing import SigningKey


def get_public_key_from_private_bytes(pv_bytes: bytes) -> str:
    """
    Private key -> Public key (base58 encode)
    """
    pv = SigningKey(pv_bytes)
    pb_bytes = bytes(pv.verify_key)
    return b58encode(pb_bytes).decode()


def save_keypair(pv_bytes: bytes, output_dir: str) -> str:
    """
    Save address and private key to txt file, return public key
    """
    pv = SigningKey(pv_bytes)
    pb_bytes = bytes(pv.verify_key)
    pubkey = b58encode(pb_bytes).decode()
    privkey = b58encode(pv_bytes + pb_bytes).decode()
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    file_path = Path(output_dir) / f"{pubkey}.txt"
    file_path.write_text(f"Address: {pubkey}\nPrivate Key: {privkey}\n")
    logging.info(f"Found: {pubkey}")
    return pubkey
