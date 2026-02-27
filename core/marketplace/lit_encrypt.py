import base64
import hashlib
import hmac
import json
import logging
import os
from typing import Optional

import requests

from core.marketplace.config import SOL_RPC_CONDITIONS, LIT_API_BASE

logger = logging.getLogger(__name__)

_ENCRYPT_TEMPLATE = """
(async () => {{
  try {{
    const dataStr = {data_json};
    const conditionsJson = {cond_json};
    const wrappingKeyB64 = {wrapping_key_json};

    const wrappingKeyRaw = Uint8Array.from(atob(wrappingKeyB64), c => c.charCodeAt(0));
    const wrappingKey = await crypto.subtle.importKey(
      "raw", wrappingKeyRaw, "AES-GCM", false, ["encrypt"]
    );

    const dataKey = await crypto.subtle.generateKey(
      {{ name: "AES-GCM", length: 256 }}, true, ["encrypt", "decrypt"]
    );

    const iv = crypto.getRandomValues(new Uint8Array(12));
    const dataBytes = new TextEncoder().encode(dataStr);
    const cipherBuf = await crypto.subtle.encrypt(
      {{ name: "AES-GCM", iv }}, dataKey, dataBytes
    );

    const exportedKey = await crypto.subtle.exportKey("raw", dataKey);

    const wrapIv = crypto.getRandomValues(new Uint8Array(12));
    const wrappedKeyBuf = await crypto.subtle.encrypt(
      {{ name: "AES-GCM", iv: wrapIv }}, wrappingKey, exportedKey
    );

    const toB64 = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf)));

    const condHash = Array.from(
      new Uint8Array(await crypto.subtle.digest("SHA-256",
        new TextEncoder().encode(conditionsJson)))
    ).map(b => b.toString(16).padStart(2, "0")).join("");

    LitActions.setResponse({{ response: JSON.stringify({{
      ciphertext: toB64(cipherBuf),
      iv: toB64(iv),
      wrappedKey: toB64(wrappedKeyBuf),
      wrapIv: toB64(wrapIv),
      dataToEncryptHash: condHash,
      encryptedInTEE: true
    }}) }});
  }} catch(e) {{
    LitActions.setResponse({{ response: JSON.stringify({{
      error: e.message, stack: e.stack
    }}) }});
  }}
}})();
"""

_DECRYPT_TEMPLATE = """
(async () => {{
  try {{
    const ciphertextB64 = {ct_json};
    const ivB64 = {iv_json};
    const wrappedKeyB64 = {wk_json};
    const wrapIvB64 = {wiv_json};
    const wrappingKeyB64 = {wrapping_key_json};

    const fromB64 = (s) => Uint8Array.from(atob(s), c => c.charCodeAt(0));

    const wrappingKeyRaw = fromB64(wrappingKeyB64);
    const wrappingKey = await crypto.subtle.importKey(
      "raw", wrappingKeyRaw, "AES-GCM", false, ["decrypt"]
    );

    const wrappedKey = fromB64(wrappedKeyB64);
    const wrapIv = fromB64(wrapIvB64);
    const unwrappedKeyBuf = await crypto.subtle.decrypt(
      {{ name: "AES-GCM", iv: wrapIv }}, wrappingKey, wrappedKey
    );

    const dataKey = await crypto.subtle.importKey(
      "raw", unwrappedKeyBuf, "AES-GCM", false, ["decrypt"]
    );

    const ciphertext = fromB64(ciphertextB64);
    const iv = fromB64(ivB64);
    const plainBuf = await crypto.subtle.decrypt(
      {{ name: "AES-GCM", iv }}, dataKey, ciphertext
    );

    const plaintext = new TextDecoder().decode(plainBuf);

    LitActions.setResponse({{ response: JSON.stringify({{
      decryptedString: plaintext
    }}) }});
  }} catch(e) {{
    LitActions.setResponse({{ response: JSON.stringify({{
      error: e.message, stack: e.stack
    }}) }});
  }}
}})();
"""


def _get_api_key() -> str:
    key = os.environ.get("LIT_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "LIT_API_KEY environment variable is not set. "
            "Create an account at https://dashboard.dev.litprotocol.com "
            "or via POST to {}/new_account to get an API key.".format(LIT_API_BASE)
        )
    return key


def _derive_wrapping_key(api_key: str, conditions_json: str) -> str:
    raw = hmac.new(
        api_key.encode("utf-8"),
        conditions_json.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(raw).decode("utf-8")


def _run_lit_action(code: str) -> dict:
    api_key = _get_api_key()
    url = f"{LIT_API_BASE}/lit_action"

    payload = {
        "code": code,
        "js_params": None,
    }

    resp = requests.post(
        url,
        json=payload,
        headers={
            "Content-Type": "application/json",
            "X-Api-Key": api_key,
        },
        timeout=60,
    )

    if resp.status_code != 200:
        raise RuntimeError(
            f"Lit Action request failed (HTTP {resp.status_code}): {resp.text}"
        )

    result = resp.json()

    if result.get("has_error"):
        raise RuntimeError(
            f"Lit Action execution error: {result.get('response', '')} "
            f"logs: {result.get('logs', '')}"
        )

    response_str = result.get("response", "{}")
    try:
        parsed = json.loads(response_str)
    except json.JSONDecodeError:
        raise RuntimeError(f"Lit Action returned invalid JSON: {response_str}")

    if "error" in parsed:
        raise RuntimeError(
            f"Lit Action error: {parsed['error']} "
            f"{parsed.get('stack', '')}"
        )

    return parsed


def get_lit_action_hash() -> str:
    code_hash = hashlib.sha256(_ENCRYPT_TEMPLATE.encode("utf-8")).hexdigest()
    return code_hash


def get_lit_action_code() -> str:
    return _ENCRYPT_TEMPLATE


def _hash_executed_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def encrypt_private_key(
    privkey_b58: str,
    vanity_address: str,
    seller_kp=None,
    sol_rpc_conditions: Optional[list] = None,
) -> dict:
    if sol_rpc_conditions is None:
        sol_rpc_conditions = SOL_RPC_CONDITIONS

    api_key = _get_api_key()
    conditions_json = json.dumps(sol_rpc_conditions, sort_keys=True)
    wrapping_key_b64 = _derive_wrapping_key(api_key, conditions_json)

    code = _ENCRYPT_TEMPLATE.format(
        data_json=json.dumps(privkey_b58),
        cond_json=json.dumps(conditions_json),
        wrapping_key_json=json.dumps(wrapping_key_b64),
    )

    logger.info("Encrypting private key for %s via Chipotle TEE...", vanity_address)

    result = _run_lit_action(code)

    ciphertext = result.get("ciphertext", "")
    data_hash = result.get("dataToEncryptHash", "")

    if not ciphertext:
        raise RuntimeError(
            f"Lit Action encrypt returned incomplete result: {list(result.keys())}"
        )

    package = {
        "ciphertext": ciphertext,
        "iv": result.get("iv", ""),
        "wrappedKey": result.get("wrappedKey", ""),
        "wrapIv": result.get("wrapIv", ""),
        "dataToEncryptHash": data_hash,
        "vanityAddress": vanity_address,
        "solRpcConditions": sol_rpc_conditions,
        "encryptedInTEE": True,
        "litNetwork": "chipotle-dev",
        "litActionHash": _hash_executed_code(code),
    }

    logger.info("Encryption successful for %s (hash: %s)", vanity_address, data_hash[:16])
    return package


def decrypt_private_key(
    encrypted_json: dict,
    buyer_kp=None,
    auth_sig: Optional[dict] = None,
    session_sigs: Optional[dict] = None,
) -> str:
    api_key = _get_api_key()

    ciphertext = encrypted_json["ciphertext"]
    iv = encrypted_json.get("iv", "")
    wrapped_key = encrypted_json.get("wrappedKey", "")
    wrap_iv = encrypted_json.get("wrapIv", "")

    conditions = encrypted_json.get(
        "solRpcConditions",
        encrypted_json.get("accessControlConditions", SOL_RPC_CONDITIONS)
    )

    conditions_json = json.dumps(conditions, sort_keys=True)
    wrapping_key_b64 = _derive_wrapping_key(api_key, conditions_json)

    code = _DECRYPT_TEMPLATE.format(
        ct_json=json.dumps(ciphertext),
        iv_json=json.dumps(iv),
        wk_json=json.dumps(wrapped_key),
        wiv_json=json.dumps(wrap_iv),
        wrapping_key_json=json.dumps(wrapping_key_b64),
    )

    logger.info("Decrypting via Chipotle TEE...")

    result = _run_lit_action(code)

    plaintext = result.get("decryptedString", "")
    if not plaintext:
        raise RuntimeError(
            f"Lit Action decrypt returned no plaintext: {list(result.keys())}"
        )

    logger.info("Decryption successful")
    return plaintext
