import hashlib
import json
import logging
import os
import threading
from pathlib import Path
from typing import Optional

from core.marketplace.config import ACCESS_CONTROL_CONDITIONS, LIT_NETWORK

logger = logging.getLogger(__name__)

_lit_client = None
_lit_lock = threading.Lock()
_lit_action_code = None
_lit_action_hash = None


def _load_lit_action():
    global _lit_action_code, _lit_action_hash
    if _lit_action_code is not None:
        return

    candidates = [
        Path(__file__).parent / "lit_action.js",
        Path(os.path.dirname(os.path.abspath(__file__))) / "lit_action.js",
    ]

    for p in candidates:
        if p.exists():
            _lit_action_code = p.read_text(encoding="utf-8")
            _lit_action_hash = hashlib.sha256(_lit_action_code.encode("utf-8")).hexdigest()
            logger.info("Loaded Lit Action from %s (hash: %s)", p, _lit_action_hash[:16])
            return

    raise FileNotFoundError("lit_action.js not found alongside lit_encrypt.py")


def get_lit_action_hash() -> str:
    _load_lit_action()
    return _lit_action_hash


def get_lit_action_code() -> str:
    _load_lit_action()
    return _lit_action_code


def _get_lit_client():
    global _lit_client
    with _lit_lock:
        if _lit_client is None:
            from lit_python_sdk import LitClient
            _lit_client = LitClient()
            _lit_client.new(lit_network=LIT_NETWORK)
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

    _load_lit_action()
    lit = _get_lit_client()

    js_params = {
        "privateKey": privkey_b58,
        "vanityAddress": vanity_address,
        "accessControlConditions": access_conditions,
    }

    with _lit_lock:
        result = lit.execute_js(
            code=_lit_action_code,
            js_params=js_params,
        )

    response_str = result.get("response", "{}")
    if isinstance(response_str, str):
        response = json.loads(response_str)
    else:
        response = response_str

    if "error" in response:
        raise RuntimeError(f"Lit Action error: {response['error']}")

    if "ciphertext" not in response or "dataToEncryptHash" not in response:
        raise RuntimeError(f"Lit Action returned incomplete response: {list(response.keys())}")

    package = {
        "ciphertext": response["ciphertext"],
        "dataToEncryptHash": response["dataToEncryptHash"],
        "vanityAddress": vanity_address,
        "accessControlConditions": access_conditions,
        "litActionHash": _lit_action_hash,
        "encryptedInTEE": True,
    }

    return package


def decrypt_private_key(
    encrypted_json: dict,
    auth_sig: Optional[dict] = None,
    session_sigs: Optional[dict] = None,
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
    if session_sigs:
        decrypt_kwargs["session_sigs"] = session_sigs
    if auth_sig:
        decrypt_kwargs["auth_sig"] = auth_sig

    with _lit_lock:
        result = lit.decrypt_string(**decrypt_kwargs)

    if isinstance(result, dict) and "decryptedString" in result:
        raw = result["decryptedString"]
        if isinstance(raw, (bytes, bytearray)):
            return raw.decode("utf-8")
        return str(raw)
    if isinstance(result, dict) and "decryptedData" in result:
        raw = result["decryptedData"]
        if isinstance(raw, (bytes, bytearray)):
            return raw.decode("utf-8")
        return str(raw)
    if isinstance(result, (bytes, bytearray)):
        return result.decode("utf-8")
    return str(result)
