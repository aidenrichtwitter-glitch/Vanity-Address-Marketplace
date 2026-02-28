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

_ED25519_JS = r"""
const P = 2n ** 255n - 19n;
const ORDER = 2n ** 252n + 27742317777372353535851937790883648493n;
function mod(a, m) { return ((a % m) + m) % m; }
function modPow(b, e, m) {
  let r = 1n; b = mod(b, m);
  while (e > 0n) { if (e & 1n) r = mod(r * b, m); e >>= 1n; b = mod(b * b, m); }
  return r;
}
function modInv(a, m) { return modPow(a, m - 2n, m); }
const D = mod(-121665n * modInv(121666n, P), P);
const I_CONST = modPow(2n, (P - 1n) / 4n, P);
const ZERO_PT = { X: 0n, Y: 1n, Z: 1n, T: 0n };
const BASE_PT = (() => {
  const y = mod(4n * modInv(5n, P), P);
  const y2 = mod(y * y, P);
  const x2 = mod((y2 - 1n) * modInv(mod(D * y2 + 1n, P), P), P);
  let x = modPow(x2, (P + 3n) / 8n, P);
  if (mod(x * x, P) !== x2) x = mod(x * I_CONST, P);
  if (x & 1n) x = mod(-x, P);
  return { X: x, Y: y, Z: 1n, T: mod(x * y, P) };
})();
function ptAdd(p1, p2) {
  const A = mod((p1.Y - p1.X) * (p2.Y - p2.X), P);
  const B = mod((p1.Y + p1.X) * (p2.Y + p2.X), P);
  const C = mod(2n * D * p1.T * p2.T, P);
  const DD = mod(2n * p1.Z * p2.Z, P);
  const E = mod(B - A, P); const F = mod(DD - C, P);
  const G = mod(DD + C, P); const H = mod(B + A, P);
  return { X: mod(E*F,P), Y: mod(G*H,P), Z: mod(F*G,P), T: mod(E*H,P) };
}
function scalarMult(s, pt) {
  let r = ZERO_PT, a = pt;
  while (s > 0n) { if (s & 1n) r = ptAdd(r, a); a = ptAdd(a, a); s >>= 1n; }
  return r;
}
function encPt(p) {
  const zi = modInv(p.Z, P);
  const x = mod(p.X * zi, P); const y = mod(p.Y * zi, P);
  const b = new Uint8Array(32);
  let yy = y; for (let i=0;i<32;i++) { b[i]=Number(yy&0xFFn); yy>>=8n; }
  if (x & 1n) b[31] |= 0x80;
  return b;
}
function bytesToScalar(b) {
  let v = 0n; for (let i=b.length-1;i>=0;i--) v = (v<<8n)|BigInt(b[i]);
  return v;
}
function scalarToBytes(s, len) {
  const b = new Uint8Array(len||32);
  let v = mod(s, ORDER);
  for (let i=0;i<b.length;i++) { b[i]=Number(v&0xFFn); v>>=8n; }
  return b;
}
function scalarMultBase(s) { return scalarMult(s, BASE_PT); }
const toB64 = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf instanceof ArrayBuffer ? buf : buf.buffer || buf)));
const fromB64 = (s) => Uint8Array.from(atob(s), c => c.charCodeAt(0));
"""

_SPLIT_KEY_SETUP_TEMPLATE = """
(async () => {{
  try {{
    {ed25519_js}

    const wrappingKeyB64 = {wrapping_key_json};
    const wrappingKeyRaw = fromB64(wrappingKeyB64);
    const wrappingKey = await crypto.subtle.importKey(
      "raw", wrappingKeyRaw, "AES-GCM", false, ["encrypt"]
    );

    const tRaw = crypto.getRandomValues(new Uint8Array(64));
    let tScalar = 0n;
    for (let i = 63; i >= 0; i--) tScalar = (tScalar << 8n) | BigInt(tRaw[i]);
    tScalar = mod(tScalar, ORDER);
    if (tScalar === 0n) tScalar = 1n;
    const tBytes = scalarToBytes(tScalar, 32);

    const T = scalarMultBase(tScalar);
    const tPointBytes = encPt(T);

    const iv = crypto.getRandomValues(new Uint8Array(12));
    const cipherBuf = await crypto.subtle.encrypt(
      {{ name: "AES-GCM", iv }}, wrappingKey, tBytes
    );

    LitActions.setResponse({{ response: JSON.stringify({{
      teePoint: toB64(tPointBytes),
      wrappedScalar: toB64(cipherBuf),
      wrapIv: toB64(iv)
    }}) }});
  }} catch(e) {{
    LitActions.setResponse({{ response: JSON.stringify({{
      error: e.message, stack: e.stack
    }}) }});
  }}
}})();
"""

_SPLIT_KEY_ENCRYPT_TEMPLATE = """
(async () => {{
  try {{
    {ed25519_js}

    const minerScalarB64 = {miner_scalar_json};
    const wrappedScalarB64 = {wrapped_scalar_json};
    const wrapIvB64 = {wrap_iv_json};
    const wrappingKeyB64 = {wrapping_key_json};
    const conditionsJson = {cond_json};
    const expectedAddress = {expected_addr_json};

    const wrappingKeyRaw = fromB64(wrappingKeyB64);
    const wrappingKey = await crypto.subtle.importKey(
      "raw", wrappingKeyRaw, "AES-GCM", false, ["decrypt"]
    );

    const wrappedScalar = fromB64(wrappedScalarB64);
    const wrapIv = fromB64(wrapIvB64);
    const tBytesBuf = await crypto.subtle.decrypt(
      {{ name: "AES-GCM", iv: wrapIv }}, wrappingKey, wrappedScalar
    );
    const tBytes = new Uint8Array(tBytesBuf);

    const sBytes = fromB64(minerScalarB64);
    if (sBytes.length !== 32) throw new Error("Miner scalar must be 32 bytes, got " + sBytes.length);
    const sScalar = mod(bytesToScalar(sBytes), ORDER);
    const tScalar = mod(bytesToScalar(tBytes), ORDER);

    const kScalar = mod(sScalar + tScalar, ORDER);
    if (kScalar === 0n) throw new Error("Combined scalar is zero");
    const kBytes = scalarToBytes(kScalar, 32);

    const pubPoint = scalarMultBase(kScalar);
    const pubBytes = encPt(pubPoint);

    const ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
    function b58enc(buf) {{
      let num = 0n;
      for (let i = 0; i < buf.length; i++) num = num * 256n + BigInt(buf[i]);
      let str = "";
      while (num > 0n) {{ str = ALPHABET[Number(num % 58n)] + str; num = num / 58n; }}
      for (let i = 0; i < buf.length && buf[i] === 0; i++) str = "1" + str;
      return str;
    }}

    const derivedAddr = b58enc(pubBytes);
    if (derivedAddr !== expectedAddress) {{
      throw new Error("Address mismatch: derived=" + derivedAddr + " expected=" + expectedAddress);
    }}

    const privB58 = b58enc(new Uint8Array([...kBytes, ...pubBytes]));

    const encWrappingKeyB64 = {enc_wrapping_key_json};
    const encWrappingKeyRaw = fromB64(encWrappingKeyB64);
    const encWrappingKey = await crypto.subtle.importKey(
      "raw", encWrappingKeyRaw, "AES-GCM", false, ["encrypt"]
    );

    const dataKey = await crypto.subtle.generateKey(
      {{ name: "AES-GCM", length: 256 }}, true, ["encrypt", "decrypt"]
    );

    const encIv = crypto.getRandomValues(new Uint8Array(12));
    const dataBytes = new TextEncoder().encode(privB58);
    const cipherBuf = await crypto.subtle.encrypt(
      {{ name: "AES-GCM", iv: encIv }}, dataKey, dataBytes
    );

    const exportedKey = await crypto.subtle.exportKey("raw", dataKey);
    const keyWrapIv = crypto.getRandomValues(new Uint8Array(12));
    const wrappedKeyBuf = await crypto.subtle.encrypt(
      {{ name: "AES-GCM", iv: keyWrapIv }}, encWrappingKey, exportedKey
    );

    const condHash = Array.from(
      new Uint8Array(await crypto.subtle.digest("SHA-256",
        new TextEncoder().encode(conditionsJson)))
    ).map(b => b.toString(16).padStart(2, "0")).join("");

    LitActions.setResponse({{ response: JSON.stringify({{
      ciphertext: toB64(cipherBuf),
      iv: toB64(encIv),
      wrappedKey: toB64(wrappedKeyBuf),
      wrapIv: toB64(keyWrapIv),
      dataToEncryptHash: condHash,
      encryptedInTEE: true,
      splitKey: true
    }}) }});
  }} catch(e) {{
    LitActions.setResponse({{ response: JSON.stringify({{
      error: e.message, stack: e.stack
    }}) }});
  }}
}})();
"""

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

    headers = {
        "Content-Type": "application/json",
        "X-Api-Key": api_key,
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=60,
                         allow_redirects=False)

    if resp.status_code in (301, 302, 303, 307, 308):
        redirect_url = resp.headers.get("Location", "")
        if redirect_url:
            logger.info("Following redirect to %s", redirect_url[:80])
            resp = requests.post(redirect_url, json=payload, headers=headers,
                                 timeout=60)

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
    combined = _ENCRYPT_TEMPLATE + _SPLIT_KEY_SETUP_TEMPLATE + _SPLIT_KEY_ENCRYPT_TEMPLATE
    code_hash = hashlib.sha256(combined.encode("utf-8")).hexdigest()
    return code_hash


def get_lit_action_code() -> str:
    return _ENCRYPT_TEMPLATE


def _hash_executed_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def split_key_setup(
    session_id: Optional[str] = None,
) -> dict:
    api_key = _get_api_key()
    if session_id is None:
        session_id = os.urandom(16).hex()

    wrapping_key_raw = hmac.new(
        api_key.encode("utf-8"),
        f"split-key-{session_id}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    wrapping_key_b64 = base64.b64encode(wrapping_key_raw).decode("utf-8")

    code = _SPLIT_KEY_SETUP_TEMPLATE.format(
        ed25519_js=_ED25519_JS,
        wrapping_key_json=json.dumps(wrapping_key_b64),
    )

    logger.info("Running split-key setup in TEE (session=%s)...", session_id[:8])

    result = _run_lit_action(code)

    tee_point_b64 = result.get("teePoint", "")
    wrapped_scalar_b64 = result.get("wrappedScalar", "")
    wrap_iv_b64 = result.get("wrapIv", "")

    if not tee_point_b64 or not wrapped_scalar_b64:
        raise RuntimeError(
            f"Split-key setup returned incomplete result: {list(result.keys())}"
        )

    tee_point_bytes = base64.b64decode(tee_point_b64)
    if len(tee_point_bytes) != 32:
        raise RuntimeError(
            f"TEE point has wrong length: {len(tee_point_bytes)} (expected 32)"
        )

    logger.info("Split-key setup complete, TEE point received")
    return {
        "teePoint": tee_point_bytes,
        "wrappedScalar": wrapped_scalar_b64,
        "wrapIv": wrap_iv_b64,
        "sessionId": session_id,
        "setupCodeHash": _hash_executed_code(code),
    }


def split_key_encrypt(
    miner_scalar: bytes,
    session_blob: dict,
    vanity_address: str,
    seller_kp=None,
    sol_rpc_conditions: Optional[list] = None,
) -> dict:
    if sol_rpc_conditions is None:
        sol_rpc_conditions = SOL_RPC_CONDITIONS

    api_key = _get_api_key()
    session_id = session_blob["sessionId"]

    wrapping_key_raw = hmac.new(
        api_key.encode("utf-8"),
        f"split-key-{session_id}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    wrapping_key_b64 = base64.b64encode(wrapping_key_raw).decode("utf-8")

    conditions_json = json.dumps(sol_rpc_conditions, sort_keys=True)
    enc_wrapping_key_b64 = _derive_wrapping_key(api_key, conditions_json)

    miner_scalar_b64 = base64.b64encode(miner_scalar).decode("utf-8")

    code = _SPLIT_KEY_ENCRYPT_TEMPLATE.format(
        ed25519_js=_ED25519_JS,
        miner_scalar_json=json.dumps(miner_scalar_b64),
        wrapped_scalar_json=json.dumps(session_blob["wrappedScalar"]),
        wrap_iv_json=json.dumps(session_blob["wrapIv"]),
        wrapping_key_json=json.dumps(wrapping_key_b64),
        cond_json=json.dumps(conditions_json),
        expected_addr_json=json.dumps(vanity_address),
        enc_wrapping_key_json=json.dumps(enc_wrapping_key_b64),
    )

    logger.info("Split-key encrypt in TEE for %s...", vanity_address)

    result = _run_lit_action(code)

    ciphertext = result.get("ciphertext", "")
    data_hash = result.get("dataToEncryptHash", "")

    if not ciphertext:
        raise RuntimeError(
            f"Split-key encrypt returned incomplete result: {list(result.keys())}"
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
        "splitKey": True,
        "litNetwork": "chipotle-dev",
        "litActionHash": _hash_executed_code(code),
    }

    logger.info("Split-key encryption successful for %s", vanity_address)
    return package


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
