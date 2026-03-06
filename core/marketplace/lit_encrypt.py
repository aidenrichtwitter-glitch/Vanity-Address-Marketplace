import base64
import hashlib
import json
import logging
import os
import time
from typing import Optional

import requests

from core.marketplace.config import SOL_RPC_CONDITIONS, LIT_API_BASE, MARKETPLACE_PKP_PUBLIC_KEY, MARKETPLACE_LIT_API_KEY

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

_PKP_DERIVE_WRAPPING_KEY_JS = r"""
async function deriveWrappingKeyFromPKP(pkpPubKey, purpose, keyUsages) {
  const digestBytes = new Uint8Array(
    await crypto.subtle.digest("SHA-256",
      new TextEncoder().encode(purpose))
  );
  const sigHex = await LitActions.signEcdsa({
    toSign: Array.from(digestBytes),
    publicKey: pkpPubKey,
    sigName: "wk_" + purpose.slice(0, 16).replace(/[^a-zA-Z0-9]/g, "_")
  });
  const sigBytes = new Uint8Array(sigHex.length / 2);
  for (let i = 0; i < sigHex.length; i += 2) {
    sigBytes[i/2] = parseInt(sigHex.substr(i, 2), 16);
  }
  const keyRaw = new Uint8Array(
    await crypto.subtle.digest("SHA-256", sigBytes)
  );
  return await crypto.subtle.importKey(
    "raw", keyRaw, "AES-GCM", false, keyUsages
  );
}
"""

_ESCROW_DERIVE_JS = r"""
async function deriveEscrowScalar(pkpPubKey, escrowId) {
  const purpose = "solvanity-escrow-" + escrowId;
  const digestBytes = new Uint8Array(
    await crypto.subtle.digest("SHA-256", new TextEncoder().encode(purpose))
  );
  const sigHex = await LitActions.signEcdsa({
    toSign: Array.from(digestBytes),
    publicKey: pkpPubKey,
    sigName: "esc_" + escrowId
  });
  const sigBytes = new Uint8Array(sigHex.length / 2);
  for (let i = 0; i < sigHex.length; i += 2) {
    sigBytes[i/2] = parseInt(sigHex.substr(i, 2), 16);
  }
  const rawBytes = new Uint8Array(
    await crypto.subtle.digest("SHA-256", sigBytes)
  );
  return mod(bytesToScalar(rawBytes), ORDER);
}
"""

_SPLIT_KEY_SETUP_TEMPLATE = """
(async () => {{
  try {{
    {ed25519_js}
    {pkp_derive_js}

    const pkpPubKey = {pkp_public_key_json};
    const sessionId = {session_id_json};

    const wrappingKey = await deriveWrappingKeyFromPKP(
      pkpPubKey, "solvanity-session:" + sessionId, ["encrypt"]
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
    {pkp_derive_js}

    const pkpPubKey = {pkp_public_key_json};
    const sessionId = {session_id_json};
    const minerScalarB64 = {miner_scalar_json};
    const wrappedScalarB64 = {wrapped_scalar_json};
    const wrapIvB64 = {wrap_iv_json};
    const conditionsJson = {cond_json};
    const expectedAddress = {expected_addr_json};

    const sessionKey = await deriveWrappingKeyFromPKP(
      pkpPubKey, "solvanity-session:" + sessionId, ["decrypt"]
    );

    const wrappedScalar = fromB64(wrappedScalarB64);
    const wrapIv = fromB64(wrapIvB64);
    const tBytesBuf = await crypto.subtle.decrypt(
      {{ name: "AES-GCM", iv: wrapIv }}, sessionKey, wrappedScalar
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

    const encWrappingKey = await deriveWrappingKeyFromPKP(
      pkpPubKey, "solvanity-wrap:" + conditionsJson, ["encrypt"]
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

_SPLIT_KEY_V2_ENCRYPT_TEMPLATE = """
(async () => {{
  try {{
    {ed25519_js}
    {pkp_derive_js}

    const pkpPubKey = {pkp_public_key_json};
    const minerScalarB64 = {miner_scalar_json};
    const buyerPubkeyB64 = {buyer_pubkey_json};
    const conditionsJson = {cond_json};
    const expectedAddress = {expected_addr_json};

    const sBytes = fromB64(minerScalarB64);
    if (sBytes.length !== 32) throw new Error("Miner scalar must be 32 bytes, got " + sBytes.length);
    const sScalar = mod(bytesToScalar(sBytes), ORDER);

    const buyerPubBytes = fromB64(buyerPubkeyB64);
    if (buyerPubBytes.length !== 32) throw new Error("Buyer pubkey must be 32 bytes, got " + buyerPubBytes.length);

    let yVal = 0n;
    for (let i = 31; i >= 0; i--) yVal = (yVal << 8n) | BigInt(buyerPubBytes[i]);
    const xSign = (yVal >> 255n) & 1n;
    yVal &= (1n << 255n) - 1n;
    const y2 = mod(yVal * yVal, P);
    const u = mod(y2 - 1n, P);
    const v = mod(D * y2 + 1n, P);
    const uv3 = mod(u * modPow(v, 3n, P), P);
    const uv7 = mod(uv3 * modPow(v, 4n, P), P);
    let xVal = mod(uv3 * modPow(uv7, (P - 5n) / 8n, P), P);
    if (mod(xVal * xVal, P) !== mod(u * modInv(v, P), P)) {{
      xVal = mod(xVal * I_CONST, P);
    }}
    if (mod(xVal * xVal, P) !== mod(u * modInv(v, P), P)) {{
      throw new Error("Invalid buyer public key point");
    }}
    if ((xVal & 1n) !== xSign) xVal = mod(-xVal, P);
    const buyerPoint = {{ X: xVal, Y: yVal, Z: 1n, T: mod(xVal * yVal, P) }};

    const tG = scalarMultBase(sScalar);
    const vanityPoint = ptAdd(buyerPoint, tG);
    const vanityBytes = encPt(vanityPoint);

    const ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
    function b58enc(buf) {{
      let num = 0n;
      for (let i = 0; i < buf.length; i++) num = num * 256n + BigInt(buf[i]);
      let str = "";
      while (num > 0n) {{ str = ALPHABET[Number(num % 58n)] + str; num = num / 58n; }}
      for (let i = 0; i < buf.length && buf[i] === 0; i++) str = "1" + str;
      return str;
    }}

    const derivedAddr = b58enc(vanityBytes);
    if (derivedAddr !== expectedAddress) {{
      throw new Error("Address mismatch: derived=" + derivedAddr + " expected=" + expectedAddress);
    }}

    const payload = JSON.stringify({{
      partialScalar: toB64(sBytes),
      vanityAddress: expectedAddress,
      splitKeyV2: true
    }});

    const encWrappingKey = await deriveWrappingKeyFromPKP(
      pkpPubKey, "solvanity-wrap:" + conditionsJson, ["encrypt"]
    );

    const dataKey = await crypto.subtle.generateKey(
      {{ name: "AES-GCM", length: 256 }}, true, ["encrypt", "decrypt"]
    );

    const encIv = crypto.getRandomValues(new Uint8Array(12));
    const dataBytes = new TextEncoder().encode(payload);
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
      splitKey: true,
      splitKeyV2: true
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
    {pkp_derive_js}

    const pkpPubKey = {pkp_public_key_json};
    const dataStr = {data_json};
    const conditionsJson = {cond_json};

    const wrappingKey = await deriveWrappingKeyFromPKP(
      pkpPubKey, "solvanity-wrap:" + conditionsJson, ["encrypt"]
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
    const mintAddress = {mint_address_json};
    const rpcUrl = "https://api.devnet.solana.com";

    let supply = -1;
    for (let attempt = 0; attempt < 5; attempt++) {{
      const supplyResp = await fetch(rpcUrl, {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{
          jsonrpc: "2.0", id: 1,
          method: "getTokenSupply",
          params: [mintAddress, {{ commitment: "confirmed" }}]
        }})
      }});
      const supplyData = await supplyResp.json();
      if (supplyData?.error) {{
        if (attempt < 4) {{ await new Promise(r => setTimeout(r, 2000)); continue; }}
        throw new Error("RPC error verifying burn: " + JSON.stringify(supplyData.error));
      }}
      supply = parseInt(supplyData?.result?.value?.amount || "1", 10);
      if (supply === 0) break;
      if (attempt < 4) await new Promise(r => setTimeout(r, 2000));
    }}
    if (supply !== 0) {{
      throw new Error("NFT not burned (supply=" + supply + ") — decryption denied");
    }}

    {pkp_derive_js}

    const pkpPubKey = {pkp_public_key_json};
    const conditionsJson = {cond_json};
    const ciphertextB64 = {ct_json};
    const ivB64 = {iv_json};
    const wrappedKeyB64 = {wk_json};
    const wrapIvB64 = {wiv_json};

    const fromB64 = (s) => Uint8Array.from(atob(s), c => c.charCodeAt(0));

    const wrappingKey = await deriveWrappingKeyFromPKP(
      pkpPubKey, "solvanity-wrap:" + conditionsJson, ["decrypt"]
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

_ESCROW_SETUP_TEMPLATE = """
(async () => {{
  try {{
    {ed25519_js}
    {pkp_derive_js}
    {escrow_derive_js}

    const pkpPubKey = {pkp_public_key_json};
    const count = {count_json};

    const ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
    function b58enc(buf) {{
      let num = 0n;
      for (let i = 0; i < buf.length; i++) num = num * 256n + BigInt(buf[i]);
      let str = "";
      while (num > 0n) {{ str = ALPHABET[Number(num % 58n)] + str; num = num / 58n; }}
      for (let i = 0; i < buf.length && buf[i] === 0; i++) str = "1" + str;
      return str;
    }}

    const escrows = [];
    for (let i = 0; i < count; i++) {{
      const scalar = await deriveEscrowScalar(pkpPubKey, i);
      const point = scalarMultBase(scalar);
      const pubBytes = encPt(point);
      escrows.push({{
        escrowId: i,
        pubkey: b58enc(pubBytes)
      }});
    }}

    LitActions.setResponse({{ response: JSON.stringify({{ escrows }}) }});
  }} catch(e) {{
    LitActions.setResponse({{ response: JSON.stringify({{
      error: e.message, stack: e.stack
    }}) }});
  }}
}})();
"""

_SPLIT_KEY_V3_ENCRYPT_TEMPLATE = """
(async () => {{
  try {{
    {ed25519_js}
    {pkp_derive_js}
    {escrow_derive_js}

    const pkpPubKey = {pkp_public_key_json};
    const minerScalarB64 = {miner_scalar_json};
    const escrowId = {escrow_id_json};
    const conditionsJson = {cond_json};
    const expectedAddress = {expected_addr_json};

    const sBytes = fromB64(minerScalarB64);
    if (sBytes.length !== 32) throw new Error("Miner scalar must be 32 bytes, got " + sBytes.length);
    const sScalar = mod(bytesToScalar(sBytes), ORDER);

    const escrowScalar = await deriveEscrowScalar(pkpPubKey, escrowId);
    const escrowPoint = scalarMultBase(escrowScalar);
    const tG = scalarMultBase(sScalar);
    const vanityPoint = ptAdd(escrowPoint, tG);
    const vanityBytes = encPt(vanityPoint);

    const ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
    function b58enc(buf) {{
      let num = 0n;
      for (let i = 0; i < buf.length; i++) num = num * 256n + BigInt(buf[i]);
      let str = "";
      while (num > 0n) {{ str = ALPHABET[Number(num % 58n)] + str; num = num / 58n; }}
      for (let i = 0; i < buf.length && buf[i] === 0; i++) str = "1" + str;
      return str;
    }}

    const derivedAddr = b58enc(vanityBytes);
    if (derivedAddr !== expectedAddress) {{
      throw new Error("Address mismatch: derived=" + derivedAddr + " expected=" + expectedAddress);
    }}

    const payload = JSON.stringify({{
      partialScalar: toB64(sBytes),
      escrowId: escrowId,
      vanityAddress: expectedAddress,
      splitKeyV3: true
    }});

    const encWrappingKey = await deriveWrappingKeyFromPKP(
      pkpPubKey, "solvanity-wrap:" + conditionsJson, ["encrypt"]
    );

    const dataKey = await crypto.subtle.generateKey(
      {{ name: "AES-GCM", length: 256 }}, true, ["encrypt", "decrypt"]
    );

    const encIv = crypto.getRandomValues(new Uint8Array(12));
    const dataBytes = new TextEncoder().encode(payload);
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
      splitKey: true,
      splitKeyV3: true
    }}) }});
  }} catch(e) {{
    LitActions.setResponse({{ response: JSON.stringify({{
      error: e.message, stack: e.stack
    }}) }});
  }}
}})();
"""

_SPLIT_KEY_V3_DECRYPT_TEMPLATE = """
(async () => {{
  try {{
    const mintAddress = {mint_address_json};
    const rpcUrl = "https://api.devnet.solana.com";

    let supply = -1;
    for (let attempt = 0; attempt < 5; attempt++) {{
      const supplyResp = await fetch(rpcUrl, {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{
          jsonrpc: "2.0", id: 1,
          method: "getTokenSupply",
          params: [mintAddress, {{ commitment: "confirmed" }}]
        }})
      }});
      const supplyData = await supplyResp.json();
      if (supplyData?.error) {{
        if (attempt < 4) {{ await new Promise(r => setTimeout(r, 2000)); continue; }}
        throw new Error("RPC error verifying burn: " + JSON.stringify(supplyData.error));
      }}
      supply = parseInt(supplyData?.result?.value?.amount || "1", 10);
      if (supply === 0) break;
      if (attempt < 4) await new Promise(r => setTimeout(r, 2000));
    }}
    if (supply !== 0) {{
      throw new Error("NFT not burned (supply=" + supply + ") — decryption denied");
    }}

    {ed25519_js}
    {pkp_derive_js}
    {escrow_derive_js}

    const pkpPubKey = {pkp_public_key_json};
    const conditionsJson = {cond_json};
    const ciphertextB64 = {ct_json};
    const ivB64 = {iv_json};
    const wrappedKeyB64 = {wk_json};
    const wrapIvB64 = {wiv_json};

    const wrappingKey = await deriveWrappingKeyFromPKP(
      pkpPubKey, "solvanity-wrap:" + conditionsJson, ["decrypt"]
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
    const data = JSON.parse(plaintext);

    if (!data.splitKeyV3) {{
      LitActions.setResponse({{ response: JSON.stringify({{
        decryptedString: plaintext
      }}) }});
      return;
    }}

    const escrowScalar = await deriveEscrowScalar(pkpPubKey, data.escrowId);
    const partialBytes = fromB64(data.partialScalar);
    const partialScalar = mod(bytesToScalar(partialBytes), ORDER);
    const finalScalar = mod(escrowScalar + partialScalar, ORDER);
    if (finalScalar === 0n) throw new Error("Final scalar is zero");

    const finalPoint = scalarMultBase(finalScalar);
    const finalPubBytes = encPt(finalPoint);
    const finalScalarBytes = scalarToBytes(finalScalar, 32);

    const ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
    function b58enc(buf) {{
      let num = 0n;
      for (let i = 0; i < buf.length; i++) num = num * 256n + BigInt(buf[i]);
      let str = "";
      while (num > 0n) {{ str = ALPHABET[Number(num % 58n)] + str; num = num / 58n; }}
      for (let i = 0; i < buf.length && buf[i] === 0; i++) str = "1" + str;
      return str;
    }}

    const finalAddr = b58enc(finalPubBytes);
    if (finalAddr !== data.vanityAddress) {{
      throw new Error("Merged address mismatch: " + finalAddr + " != " + data.vanityAddress);
    }}

    const finalKey = new Uint8Array(64);
    finalKey.set(finalScalarBytes, 0);
    finalKey.set(finalPubBytes, 32);

    LitActions.setResponse({{ response: JSON.stringify({{
      finalKeyB64: toB64(finalKey),
      vanityAddress: data.vanityAddress,
      escrowMerged: true
    }}) }});
  }} catch(e) {{
    LitActions.setResponse({{ response: JSON.stringify({{
      error: e.message, stack: e.stack
    }}) }});
  }}
}})();
"""


def create_lit_account(account_name: str = "") -> dict:
    import uuid
    if not account_name:
        account_name = "solvanity_" + uuid.uuid4().hex[:8]

    url = f"{LIT_API_BASE}/new_account"
    payload = {
        "account_name": account_name,
        "account_description": "SolVanity Word Miner user account",
    }

    r = requests.post(url, json=payload, timeout=15, allow_redirects=False)
    if r.status_code in (301, 302, 307, 308):
        target = r.headers.get("location", "")
        if not target:
            raise RuntimeError("Lit API returned redirect with no location header")
        r = requests.post(
            target,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30,
        )

    if r.status_code != 200:
        raise RuntimeError(f"Lit account creation failed (HTTP {r.status_code}): {r.text[:300]}")

    data = r.json()
    api_key = data.get("api_key", "")
    if not api_key:
        raise RuntimeError("Lit API returned empty api_key")

    return {
        "api_key": api_key,
        "wallet_address": data.get("wallet_address", ""),
    }


def _get_api_key() -> str:
    return MARKETPLACE_LIT_API_KEY


def _get_pkp_public_key() -> str:
    key = os.environ.get("LIT_PKP_PUBLIC_KEY", "").strip()
    if not key:
        key = MARKETPLACE_PKP_PUBLIC_KEY
        os.environ["LIT_PKP_PUBLIC_KEY"] = key
        logger.info("Using default marketplace PKP: %s", key[:16])
    return key


def setup_pkp_vault() -> dict:
    api_key = _get_api_key()
    headers = {"X-Api-Key": api_key}

    existing_key = os.environ.get("LIT_PKP_PUBLIC_KEY", "").strip()
    if existing_key:
        logger.info("PKP vault already configured: %s", existing_key[:16])
        return {"pkp_public_key": existing_key, "created": False}

    logger.info("Creating PKP vault wallet...")
    r = requests.get(
        f"{LIT_API_BASE}/create_wallet",
        headers=headers, timeout=30, allow_redirects=True,
    )
    if r.status_code != 200:
        raise RuntimeError(f"PKP wallet creation failed (HTTP {r.status_code}): {r.text[:300]}")

    wallet_address = r.json().get("wallet_address", "")
    if not wallet_address:
        raise RuntimeError("PKP wallet creation returned no wallet_address")

    r = requests.get(
        f"{LIT_API_BASE}/list_wallets",
        params={"page_number": "1", "page_size": "50"},
        headers=headers, timeout=30, allow_redirects=True,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Failed to list wallets (HTTP {r.status_code})")

    wallets = r.json()
    pkp_public_key = ""
    for w in wallets:
        if w.get("wallet_address") == wallet_address:
            pkp_public_key = w.get("public_key", "")
            break

    if not pkp_public_key or pkp_public_key == "unmanaged":
        raise RuntimeError(f"Could not find public key for wallet {wallet_address}")

    logger.info("PKP vault created: pubkey=%s", pkp_public_key[:16])

    return {
        "pkp_public_key": pkp_public_key,
        "wallet_address": wallet_address,
        "created": True,
    }


def register_ipfs_actions() -> dict:
    api_key = _get_api_key()
    pkp_public_key = _get_pkp_public_key()

    existing_group_id = os.environ.get("LIT_GROUP_ID", "").strip()
    if existing_group_id:
        logger.info("PKP group already configured: %s", existing_group_id[:16])
        return {"group_id": existing_group_id, "created": False}

    try:
        group_result = _create_pkp_group(api_key, pkp_public_key)
        return group_result
    except Exception as e:
        logger.error("Group creation failed: %s", e)
        raise


def _create_pkp_group(api_key: str, pkp_public_key: str) -> dict:
    headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}

    existing_group_id = os.environ.get("LIT_GROUP_ID", "").strip()
    if existing_group_id:
        logger.info("PKP group already configured: %s", existing_group_id[:16])
        return {"group_id": existing_group_id, "created": False}

    group_payload = {
        "group_name": "SolVanity Trustless Vault",
        "group_description": "PKP group for trustless vanity address encryption/decryption",
        "permitted_actions": [],
        "pkps": [],
        "all_wallets_permitted": True,
        "all_actions_permitted": True,
    }

    r = requests.post(
        f"{LIT_API_BASE}/add_group",
        json=group_payload,
        headers=headers,
        timeout=30,
        allow_redirects=True,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Group creation failed (HTTP {r.status_code}): {r.text[:300]}")

    logger.info("PKP group created successfully")

    r = requests.get(
        f"{LIT_API_BASE}/list_groups",
        params={"page_number": "0", "page_size": "10"},
        headers={"X-Api-Key": api_key},
        timeout=30,
        allow_redirects=True,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Failed to list groups (HTTP {r.status_code})")

    groups = r.json()
    group_id = ""
    for g in groups:
        if g.get("name") == "SolVanity Trustless Vault":
            group_id = g.get("id", "")
            break

    if not group_id:
        raise RuntimeError(
            "Group created but could not retrieve group ID from list_groups. "
            f"Groups returned: {json.dumps(groups)[:300]}"
        )

    logger.info("PKP group ID: %s", group_id)

    r = requests.post(
        f"{LIT_API_BASE}/add_pkp_to_group",
        json={"group_id": group_id, "pkp_public_key": pkp_public_key},
        headers=headers,
        timeout=30,
        allow_redirects=True,
    )
    if r.status_code != 200:
        raise RuntimeError(
            f"Failed to add PKP to group (HTTP {r.status_code}): {r.text[:300]}"
        )
    logger.info("PKP %s added to group", pkp_public_key[:16])

    expiration = str(int(time.time()) + 365 * 24 * 3600)
    r = requests.post(
        f"{LIT_API_BASE}/add_usage_api_key",
        json={"expiration": expiration, "balance": "1000000"},
        headers=headers,
        timeout=30,
        allow_redirects=True,
    )
    if r.status_code == 200:
        usage_data = r.json()
        usage_api_key = usage_data.get("usage_api_key", usage_data.get("api_key", usage_data.get("key", "")))
        if usage_api_key:
            os.environ["LIT_USAGE_API_KEY"] = usage_api_key
            logger.info("Default usage API key created and stored")
    else:
        logger.warning("Default usage API key creation failed (HTTP %d)", r.status_code)

    os.environ["LIT_GROUP_ID"] = group_id
    return {"group_id": group_id, "created": True}


def create_user_scoped_key() -> str:
    api_key = _get_api_key()

    headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}
    expiration = str(int(time.time()) + 365 * 24 * 3600)
    payload = {"expiration": expiration, "balance": "1000000"}

    scoped_key = ""
    for attempt in range(5):
        r = requests.post(
            f"{LIT_API_BASE}/add_usage_api_key",
            json=payload,
            headers=headers,
            timeout=30,
            allow_redirects=True,
        )
        if r.status_code == 200:
            data = r.json()
            scoped_key = data.get("usage_api_key", data.get("api_key", data.get("key", "")))
            if scoped_key:
                break
        if attempt < 4 and r.status_code in (500, 502, 503):
            time.sleep(2 ** attempt)
            continue
        if r.status_code != 200:
            raise RuntimeError(
                f"Scoped key creation failed (HTTP {r.status_code}): {r.text[:300]}"
            )

    if not scoped_key:
        raise RuntimeError("Scoped key creation returned empty key")

    logger.info("User scoped key created successfully")
    return scoped_key


def _run_lit_action(code: str, max_retries: int = 3, api_key: Optional[str] = None) -> dict:
    explicit_key = bool(api_key)
    if not api_key:
        usage_key = os.environ.get("LIT_USAGE_API_KEY", "").strip()
        api_key = usage_key if usage_key else _get_api_key()
    else:
        usage_key = ""
    url = f"{LIT_API_BASE}/lit_action"

    payload = {
        "code": code,
        "js_params": None,
    }

    headers = {
        "Content-Type": "application/json",
        "X-Api-Key": api_key,
    }

    resp = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=60,
                                 allow_redirects=False)

            if resp.status_code in (301, 302, 303, 307, 308):
                redirect_url = resp.headers.get("Location", "")
                if redirect_url:
                    resp = requests.post(redirect_url, json=payload, headers=headers,
                                         timeout=60)

            if resp.status_code in (401, 403) and usage_key and api_key == usage_key:
                logger.warning(
                    "Scoped usage key rejected (HTTP %d) — falling back to primary API key",
                    resp.status_code
                )
                api_key = _get_api_key()
                headers["X-Api-Key"] = api_key
                continue

            if resp.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                wait = 2 ** attempt
                logger.warning("TEE returned HTTP %d (attempt %d/%d) — retrying in %ds",
                               resp.status_code, attempt, max_retries, wait)
                time.sleep(wait)
                continue
            break
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            if attempt < max_retries:
                wait = 2 ** attempt
                logger.warning("TEE request failed (attempt %d/%d): %s — retrying in %ds",
                               attempt, max_retries, e, wait)
                time.sleep(wait)
            else:
                raise

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


def _template_hash(tmpl: str) -> str:
    return hashlib.sha256(tmpl.encode("utf-8")).hexdigest()


_SPLIT_KEY_ENCRYPT_HASH = _template_hash(_SPLIT_KEY_ENCRYPT_TEMPLATE)

_LEGACY_TEMPLATE_HASHES = {
    "1eb0cee61481286e355e9f1222dc27b834934c3c3b23ea7fce52b74b4100eb53",
    "b1689dcad2948d5c63d719d31ccf528211773e609e3deb46b2c43deca51df790",
    _SPLIT_KEY_ENCRYPT_HASH,
}

_SPLIT_KEY_V2_ENCRYPT_HASH = _template_hash(_SPLIT_KEY_V2_ENCRYPT_TEMPLATE)
_SPLIT_KEY_V3_ENCRYPT_HASH = _template_hash(_SPLIT_KEY_V3_ENCRYPT_TEMPLATE)
_SPLIT_KEY_V3_DECRYPT_HASH = _template_hash(_SPLIT_KEY_V3_DECRYPT_TEMPLATE)
_ENCRYPT_HASH = _template_hash(_ENCRYPT_TEMPLATE)
_TRUSTED_TEMPLATE_HASHES = {_SPLIT_KEY_V2_ENCRYPT_HASH, _SPLIT_KEY_V3_ENCRYPT_HASH, _ENCRYPT_HASH}


def get_lit_action_hash() -> str:
    combined = _ENCRYPT_TEMPLATE + _SPLIT_KEY_SETUP_TEMPLATE + _SPLIT_KEY_ENCRYPT_TEMPLATE + _SPLIT_KEY_V2_ENCRYPT_TEMPLATE
    code_hash = hashlib.sha256(combined.encode("utf-8")).hexdigest()
    return code_hash


def get_trusted_template_hashes() -> set:
    return set(_TRUSTED_TEMPLATE_HASHES)


def get_legacy_template_hashes() -> set:
    return set(_LEGACY_TEMPLATE_HASHES)


def get_lit_action_code() -> str:
    return _ENCRYPT_TEMPLATE


def _hash_executed_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _format_split_key_setup_template(session_id: str, pkp_public_key: str) -> str:
    return _SPLIT_KEY_SETUP_TEMPLATE.format(
        ed25519_js=_ED25519_JS,
        pkp_derive_js=_PKP_DERIVE_WRAPPING_KEY_JS,
        pkp_public_key_json=json.dumps(pkp_public_key),
        session_id_json=json.dumps(session_id),
    )


def _format_split_key_encrypt_template(
    miner_scalar_b64: str, wrapped_scalar_b64: str, wrap_iv_b64: str,
    conditions_json: str, expected_addr: str, session_id: str,
    pkp_public_key: str,
) -> str:
    return _SPLIT_KEY_ENCRYPT_TEMPLATE.format(
        ed25519_js=_ED25519_JS,
        pkp_derive_js=_PKP_DERIVE_WRAPPING_KEY_JS,
        pkp_public_key_json=json.dumps(pkp_public_key),
        session_id_json=json.dumps(session_id),
        miner_scalar_json=json.dumps(miner_scalar_b64),
        wrapped_scalar_json=json.dumps(wrapped_scalar_b64),
        wrap_iv_json=json.dumps(wrap_iv_b64),
        cond_json=json.dumps(conditions_json),
        expected_addr_json=json.dumps(expected_addr),
    )


def _format_split_key_v2_encrypt_template(
    miner_scalar_b64: str, buyer_pubkey_b64: str,
    conditions_json: str, expected_addr: str,
    pkp_public_key: str,
) -> str:
    return _SPLIT_KEY_V2_ENCRYPT_TEMPLATE.format(
        ed25519_js=_ED25519_JS,
        pkp_derive_js=_PKP_DERIVE_WRAPPING_KEY_JS,
        pkp_public_key_json=json.dumps(pkp_public_key),
        miner_scalar_json=json.dumps(miner_scalar_b64),
        buyer_pubkey_json=json.dumps(buyer_pubkey_b64),
        cond_json=json.dumps(conditions_json),
        expected_addr_json=json.dumps(expected_addr),
    )


def _format_encrypt_template(
    data_str: str, conditions_json: str, pkp_public_key: str,
) -> str:
    return _ENCRYPT_TEMPLATE.format(
        pkp_derive_js=_PKP_DERIVE_WRAPPING_KEY_JS,
        pkp_public_key_json=json.dumps(pkp_public_key),
        data_json=json.dumps(data_str),
        cond_json=json.dumps(conditions_json),
    )


def _format_decrypt_template(
    mint_address: str, ciphertext: str, iv: str,
    wrapped_key: str, wrap_iv: str,
    conditions_json: str, pkp_public_key: str,
) -> str:
    return _DECRYPT_TEMPLATE.format(
        pkp_derive_js=_PKP_DERIVE_WRAPPING_KEY_JS,
        pkp_public_key_json=json.dumps(pkp_public_key),
        mint_address_json=json.dumps(mint_address),
        ct_json=json.dumps(ciphertext),
        iv_json=json.dumps(iv),
        wk_json=json.dumps(wrapped_key),
        wiv_json=json.dumps(wrap_iv),
        cond_json=json.dumps(conditions_json),
    )


def _format_escrow_setup_template(count: int, pkp_public_key: str) -> str:
    return _ESCROW_SETUP_TEMPLATE.format(
        ed25519_js=_ED25519_JS,
        pkp_derive_js=_PKP_DERIVE_WRAPPING_KEY_JS,
        escrow_derive_js=_ESCROW_DERIVE_JS,
        pkp_public_key_json=json.dumps(pkp_public_key),
        count_json=json.dumps(count),
    )


def _format_split_key_v3_encrypt_template(
    miner_scalar_b64: str, escrow_id: int,
    conditions_json: str, expected_addr: str,
    pkp_public_key: str,
) -> str:
    return _SPLIT_KEY_V3_ENCRYPT_TEMPLATE.format(
        ed25519_js=_ED25519_JS,
        pkp_derive_js=_PKP_DERIVE_WRAPPING_KEY_JS,
        escrow_derive_js=_ESCROW_DERIVE_JS,
        pkp_public_key_json=json.dumps(pkp_public_key),
        miner_scalar_json=json.dumps(miner_scalar_b64),
        escrow_id_json=json.dumps(escrow_id),
        cond_json=json.dumps(conditions_json),
        expected_addr_json=json.dumps(expected_addr),
    )


def _format_split_key_v3_decrypt_template(
    mint_address: str, ciphertext: str, iv: str,
    wrapped_key: str, wrap_iv: str,
    conditions_json: str, pkp_public_key: str,
    escrow_id: int,
) -> str:
    return _SPLIT_KEY_V3_DECRYPT_TEMPLATE.format(
        ed25519_js=_ED25519_JS,
        pkp_derive_js=_PKP_DERIVE_WRAPPING_KEY_JS,
        escrow_derive_js=_ESCROW_DERIVE_JS,
        pkp_public_key_json=json.dumps(pkp_public_key),
        mint_address_json=json.dumps(mint_address),
        ct_json=json.dumps(ciphertext),
        iv_json=json.dumps(iv),
        wk_json=json.dumps(wrapped_key),
        wiv_json=json.dumps(wrap_iv),
        cond_json=json.dumps(conditions_json),
    )


_ESCROW_PUBKEYS_CACHE: list = []


def escrow_setup(count: int = 10, api_key: Optional[str] = None) -> list:
    global _ESCROW_PUBKEYS_CACHE
    pkp_public_key = _get_pkp_public_key()

    code = _format_escrow_setup_template(count, pkp_public_key)
    logger.info("Deriving %d escrow pubkeys in TEE...", count)

    result = _run_lit_action(code, api_key=api_key)
    escrows = result.get("escrows", [])

    if not escrows:
        raise RuntimeError("Escrow setup returned no escrow pubkeys")

    _ESCROW_PUBKEYS_CACHE = escrows
    logger.info("Escrow setup complete: %d pubkeys derived", len(escrows))
    return escrows


def get_escrow_pubkeys(count: int = 10) -> list:
    global _ESCROW_PUBKEYS_CACHE
    if _ESCROW_PUBKEYS_CACHE:
        return _ESCROW_PUBKEYS_CACHE
    return escrow_setup(count=count)


def split_key_v3_encrypt(
    miner_scalar: bytes,
    escrow_id: int,
    vanity_address: str,
    seller_kp=None,
    sol_rpc_conditions: Optional[list] = None,
    api_key: Optional[str] = None,
) -> dict:
    if sol_rpc_conditions is None:
        sol_rpc_conditions = SOL_RPC_CONDITIONS

    pkp_public_key = _get_pkp_public_key()
    conditions_json = json.dumps(sol_rpc_conditions, sort_keys=True)
    miner_scalar_b64 = base64.b64encode(miner_scalar).decode("utf-8")

    code = _format_split_key_v3_encrypt_template(
        miner_scalar_b64=miner_scalar_b64,
        escrow_id=escrow_id,
        conditions_json=conditions_json,
        expected_addr=vanity_address,
        pkp_public_key=pkp_public_key,
    )

    logger.info("Split-key v3 encrypt in TEE for %s (escrow=%d)...", vanity_address, escrow_id)

    result = _run_lit_action(code, api_key=api_key)

    ciphertext = result.get("ciphertext", "")
    data_hash = result.get("dataToEncryptHash", "")

    if not ciphertext:
        raise RuntimeError(
            f"Split-key v3 encrypt returned incomplete result: {list(result.keys())}"
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
        "splitKeyV3": True,
        "escrowId": escrow_id,
        "litNetwork": "chipotle-dev",
        "litActionHash": _SPLIT_KEY_V3_ENCRYPT_HASH,
        "pkpPublicKey": pkp_public_key,
    }

    logger.info("Split-key v3 encryption successful for %s", vanity_address)
    return package


def split_key_v3_decrypt(
    encrypted_json: dict,
    mint_address: str = "",
    api_key: Optional[str] = None,
) -> dict:
    pkp_public_key = encrypted_json.get("pkpPublicKey", "").strip()
    if not pkp_public_key:
        pkp_public_key = _get_pkp_public_key()

    if not mint_address:
        raise RuntimeError("mint_address required for V3 decryption (TEE verifies burn on-chain)")

    escrow_id = encrypted_json.get("escrowId", 0)

    conditions = encrypted_json.get(
        "solRpcConditions",
        encrypted_json.get("accessControlConditions", SOL_RPC_CONDITIONS)
    )
    conditions_json = json.dumps(conditions, sort_keys=True)

    code = _format_split_key_v3_decrypt_template(
        mint_address=mint_address,
        ciphertext=encrypted_json["ciphertext"],
        iv=encrypted_json.get("iv", ""),
        wrapped_key=encrypted_json.get("wrappedKey", ""),
        wrap_iv=encrypted_json.get("wrapIv", ""),
        conditions_json=conditions_json,
        pkp_public_key=pkp_public_key,
        escrow_id=escrow_id,
    )

    logger.info("V3 decrypt+merge in TEE (escrow=%d)...", escrow_id)

    result = _run_lit_action(code, api_key=api_key)

    final_key_b64 = result.get("finalKeyB64", "")
    vanity_address = result.get("vanityAddress", "")

    if not final_key_b64:
        raise RuntimeError(
            f"V3 decrypt returned incomplete result: {list(result.keys())}"
        )

    final_key_bytes = base64.b64decode(final_key_b64)
    if len(final_key_bytes) != 64:
        raise RuntimeError(f"V3 decrypt returned key of wrong length: {len(final_key_bytes)}")

    import base58 as b58mod
    final_key_b58 = b58mod.b58encode(final_key_bytes).decode("utf-8")

    logger.info("V3 decrypt+merge successful for %s", vanity_address)
    return {
        "privkey_b58": final_key_b58,
        "vanity_address": vanity_address,
        "escrow_merged": True,
    }


def split_key_setup(
    session_id: Optional[str] = None,
    api_key: Optional[str] = None,
) -> dict:
    pkp_public_key = _get_pkp_public_key()
    if session_id is None:
        session_id = os.urandom(16).hex()

    code = _format_split_key_setup_template(session_id, pkp_public_key)

    logger.info("Running split-key setup in TEE (session=%s)...", session_id[:8])

    result = _run_lit_action(code, api_key=api_key)

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
    api_key: Optional[str] = None,
) -> dict:
    if sol_rpc_conditions is None:
        sol_rpc_conditions = SOL_RPC_CONDITIONS

    pkp_public_key = _get_pkp_public_key()
    session_id = session_blob["sessionId"]
    conditions_json = json.dumps(sol_rpc_conditions, sort_keys=True)
    miner_scalar_b64 = base64.b64encode(miner_scalar).decode("utf-8")

    code = _format_split_key_encrypt_template(
        miner_scalar_b64=miner_scalar_b64,
        wrapped_scalar_b64=session_blob["wrappedScalar"],
        wrap_iv_b64=session_blob["wrapIv"],
        conditions_json=conditions_json,
        expected_addr=vanity_address,
        session_id=session_id,
        pkp_public_key=pkp_public_key,
    )

    logger.info("Split-key encrypt in TEE for %s...", vanity_address)

    result = _run_lit_action(code, api_key=api_key)

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
        "litActionHash": _SPLIT_KEY_ENCRYPT_HASH,
        "pkpPublicKey": pkp_public_key,
    }

    logger.info("Split-key encryption successful for %s", vanity_address)
    return package


def split_key_v2_encrypt(
    miner_scalar: bytes,
    buyer_pubkey: str,
    vanity_address: str,
    seller_kp=None,
    sol_rpc_conditions: Optional[list] = None,
    api_key: Optional[str] = None,
) -> dict:
    if sol_rpc_conditions is None:
        sol_rpc_conditions = SOL_RPC_CONDITIONS

    pkp_public_key = _get_pkp_public_key()
    conditions_json = json.dumps(sol_rpc_conditions, sort_keys=True)
    miner_scalar_b64 = base64.b64encode(miner_scalar).decode("utf-8")

    import base58 as b58mod
    buyer_pubkey_bytes = b58mod.b58decode(buyer_pubkey)
    if len(buyer_pubkey_bytes) != 32:
        raise RuntimeError(f"Buyer pubkey must be 32 bytes, got {len(buyer_pubkey_bytes)}")
    buyer_pubkey_b64 = base64.b64encode(buyer_pubkey_bytes).decode("utf-8")

    code = _format_split_key_v2_encrypt_template(
        miner_scalar_b64=miner_scalar_b64,
        buyer_pubkey_b64=buyer_pubkey_b64,
        conditions_json=conditions_json,
        expected_addr=vanity_address,
        pkp_public_key=pkp_public_key,
    )

    logger.info("Split-key v2 encrypt in TEE for %s...", vanity_address)

    result = _run_lit_action(code, api_key=api_key)

    ciphertext = result.get("ciphertext", "")
    data_hash = result.get("dataToEncryptHash", "")

    if not ciphertext:
        raise RuntimeError(
            f"Split-key v2 encrypt returned incomplete result: {list(result.keys())}"
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
        "splitKeyV2": True,
        "litNetwork": "chipotle-dev",
        "litActionHash": _SPLIT_KEY_V2_ENCRYPT_HASH,
        "pkpPublicKey": pkp_public_key,
    }

    logger.info("Split-key v2 encryption successful for %s", vanity_address)
    return package


def encrypt_private_key(
    privkey_b58: str,
    vanity_address: str,
    seller_kp=None,
    sol_rpc_conditions: Optional[list] = None,
    api_key: Optional[str] = None,
) -> dict:
    if sol_rpc_conditions is None:
        sol_rpc_conditions = SOL_RPC_CONDITIONS

    pkp_public_key = _get_pkp_public_key()
    conditions_json = json.dumps(sol_rpc_conditions, sort_keys=True)

    code = _format_encrypt_template(privkey_b58, conditions_json, pkp_public_key)

    logger.info("Encrypting private key for %s via Chipotle TEE...", vanity_address)

    result = _run_lit_action(code, api_key=api_key)

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
        "litActionHash": _ENCRYPT_HASH,
        "pkpPublicKey": pkp_public_key,
    }

    logger.info("Encryption successful for %s (hash: %s)", vanity_address, data_hash[:16])
    return package


def decrypt_private_key(
    encrypted_json: dict,
    buyer_kp=None,
    auth_sig: Optional[dict] = None,
    session_sigs: Optional[dict] = None,
    mint_address: str = "",
    api_key: Optional[str] = None,
) -> str:
    pkp_public_key = encrypted_json.get("pkpPublicKey", "").strip()
    if not pkp_public_key:
        pkp_public_key = _get_pkp_public_key()

    if not mint_address:
        raise RuntimeError("mint_address required for decryption (TEE verifies burn on-chain)")

    pkg_hash = encrypted_json.get("litActionHash", "")
    if pkg_hash and pkg_hash in _LEGACY_TEMPLATE_HASHES:
        raise RuntimeError(
            "This package was encrypted with a legacy wrapping key (pre-PKP). "
            "It cannot be decrypted with the current PKP-signed architecture. "
            f"Legacy hash: {pkg_hash[:16]}..."
        )

    conditions = encrypted_json.get(
        "solRpcConditions",
        encrypted_json.get("accessControlConditions", SOL_RPC_CONDITIONS)
    )
    conditions_json = json.dumps(conditions, sort_keys=True)

    ciphertext = encrypted_json["ciphertext"]
    iv = encrypted_json.get("iv", "")
    wrapped_key = encrypted_json.get("wrappedKey", "")
    wrap_iv = encrypted_json.get("wrapIv", "")

    code = _format_decrypt_template(
        mint_address=mint_address,
        ciphertext=ciphertext,
        iv=iv,
        wrapped_key=wrapped_key,
        wrap_iv=wrap_iv,
        conditions_json=conditions_json,
        pkp_public_key=pkp_public_key,
    )

    logger.info("Decrypting via Chipotle TEE (PKP-signed wrapping key)...")

    result = _run_lit_action(code, api_key=api_key)
    plaintext = result.get("decryptedString", "")

    if not plaintext:
        raise RuntimeError("Decrypt returned empty plaintext")

    logger.info("Decryption successful via PKP-signed wrapping key")
    return plaintext
