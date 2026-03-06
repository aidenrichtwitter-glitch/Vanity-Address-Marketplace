import hashlib
import json
import logging
from pathlib import Path

from base58 import b58encode, b58decode
from nacl.signing import SigningKey
import nacl.bindings

logger = logging.getLogger(__name__)

ED25519_ORDER = 2**252 + 27742317777372353535851937790883648493


def get_public_key_from_private_bytes(pv_bytes: bytes) -> str:
    pv = SigningKey(pv_bytes)
    pb_bytes = bytes(pv.verify_key)
    return b58encode(pb_bytes).decode()


def save_keypair(pv_bytes: bytes, output_dir: str, word: str = None, pubkey: str = None) -> str:
    pv = SigningKey(pv_bytes)
    pb_bytes = bytes(pv.verify_key)
    if pubkey is None:
        pubkey = b58encode(pb_bytes).decode()
    privkey = b58encode(pv_bytes + pb_bytes).decode()
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    filename = f"{word}.txt" if word else f"{pubkey}.txt"
    file_path = Path(output_dir) / filename
    counter = 1
    while file_path.exists():
        filename = f"{word}_{counter}.txt" if word else f"{pubkey}_{counter}.txt"
        file_path = Path(output_dir) / filename
        counter += 1
    file_path.write_text(f"Address: {pubkey}\nPrivate Key: {privkey}\n")
    logging.info(f"Found: {pubkey}")
    return pubkey


def sign_with_raw_scalar(message: bytes, scalar: bytes, pubkey: bytes) -> bytes:
    nonce_input = scalar + message
    nonce_hash = hashlib.sha512(nonce_input).digest()
    r = int.from_bytes(nonce_hash, "little") % ED25519_ORDER
    r_bytes = r.to_bytes(32, "little")
    R = nacl.bindings.crypto_scalarmult_ed25519_base_noclamp(r_bytes)
    h_input = R + pubkey + message
    h_hash = hashlib.sha512(h_input).digest()
    h = int.from_bytes(h_hash, "little") % ED25519_ORDER
    k = int.from_bytes(scalar, "little")
    S = (r + h * k) % ED25519_ORDER
    S_bytes = S.to_bytes(32, "little")
    return R + S_bytes


def _ed25519_clamp(scalar_bytes: bytes) -> bytes:
    s = bytearray(scalar_bytes)
    s[0] &= 248
    s[31] &= 127
    s[31] |= 64
    return bytes(s)


def merge_buyer_key(buyer_seed_bytes: bytes, partial_scalar: bytes) -> tuple[bytes, bytes, str]:
    buyer_scalar = _ed25519_clamp(hashlib.sha512(buyer_seed_bytes).digest()[:32])
    buyer_scalar_int = int.from_bytes(buyer_scalar, "little")
    partial_scalar_int = int.from_bytes(partial_scalar, "little")
    final_scalar_int = (buyer_scalar_int + partial_scalar_int) % ED25519_ORDER
    final_scalar = final_scalar_int.to_bytes(32, "little")
    final_pubkey = nacl.bindings.crypto_scalarmult_ed25519_base_noclamp(final_scalar)
    base58_privkey_64 = b58encode(final_scalar + final_pubkey).decode()
    return (final_scalar, final_pubkey, base58_privkey_64)


