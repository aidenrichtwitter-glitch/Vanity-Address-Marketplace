import logging
import threading
from typing import Optional

from core.marketplace.config import ACCESS_CONTROL_CONDITIONS, LIT_NETWORK

logger = logging.getLogger(__name__)

_lit_client = None
_lit_lock = threading.Lock()


def _get_lit_client():
    global _lit_client
    with _lit_lock:
        if _lit_client is None:
            from lit_python_sdk import LitClient
            _lit_client = LitClient(network=LIT_NETWORK)
            _lit_client.connect()
            logger.info("Lit Protocol client connected (network: %s)", LIT_NETWORK)
        return _lit_client


def encrypt_private_key(
    privkey_b58: str,
    vanity_address: str,
    access_conditions: Optional[list] = None,
) -> dict:
    if access_conditions is None:
        access_conditions = ACCESS_CONTROL_CONDITIONS

    lit = _get_lit_client()

    with _lit_lock:
        encrypted = lit.encrypt(
            data=privkey_b58,
            access_control_conditions=access_conditions,
            chain="solanaDevnet",
        )

    ciphertext = encrypted["ciphertext"]
    data_hash = encrypted["dataToEncryptHash"]

    package = {
        "ciphertext": ciphertext,
        "dataToEncryptHash": data_hash,
        "vanityAddress": vanity_address,
        "accessControlConditions": access_conditions,
    }

    return package


def decrypt_private_key(
    encrypted_json: dict,
    auth_sig: Optional[dict] = None,
) -> str:
    lit = _get_lit_client()

    ciphertext = encrypted_json["ciphertext"]
    data_hash = encrypted_json["dataToEncryptHash"]
    conditions = encrypted_json.get(
        "accessControlConditions", ACCESS_CONTROL_CONDITIONS
    )

    decrypt_kwargs = {
        "ciphertext": ciphertext,
        "data_to_encrypt_hash": data_hash,
        "access_control_conditions": conditions,
        "chain": "solanaDevnet",
    }
    if auth_sig:
        decrypt_kwargs["auth_sig"] = auth_sig

    with _lit_lock:
        result = lit.decrypt(**decrypt_kwargs)

    if isinstance(result, dict) and "decryptedData" in result:
        raw = result["decryptedData"]
        if isinstance(raw, (bytes, bytearray)):
            return raw.decode("utf-8")
        return str(raw)
    if isinstance(result, (bytes, bytearray)):
        return result.decode("utf-8")
    return str(result)
