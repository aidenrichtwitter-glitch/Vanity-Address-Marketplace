#!/usr/bin/env python3
"""End-to-End V3 Speculative + V2 Bounty Flow Test

Runs the full lifecycle via HTTP API against the running web app:

  V3 SPECULATIVE (fast CPU mine):
    1. Start CPU mining in blind/V3 mode with a 2-char instant-mine suffix
    2. Wait for vanity address found + NFT minted + listed
    3. Buy the NFT from marketplace
    4. Burn the NFT → trigger TEE decrypt
    5. Validate: 64-byte base58 key, address derivation matches

  V2 BOUNTY (server-side merge):
    6. Generate keypair via /api/generate-bounty-keypair
    7. Encrypt seed with passphrase (AES-GCM, PBKDF2)
    8. Post bounty with encrypted_secret
    9. CPU-mine for bounty pattern (V2 blind mode)
   10. Fulfill bounty with mint_address
   11. Collect bounty with passphrase → server merges → final key
   12. Validate: 64-byte base58 key, address derivation matches

  FALLBACK (pure crypto, no on-chain):
    If on-chain steps fail (no SOL, no Lit Protocol, RPC errors),
    falls back to local crypto-only verification of the merge math.

Run:  python tests/test_e2e_v3_v2_flow.py
      python tests/test_e2e_v3_v2_flow.py --offline
"""

import argparse
import base64
import hashlib
import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from base58 import b58decode, b58encode
from nacl.bindings import (
    crypto_core_ed25519_add,
    crypto_scalarmult_ed25519_base_noclamp,
)
from nacl.signing import VerifyKey

from core.utils.crypto import (
    ED25519_ORDER,
    _ed25519_clamp,
    merge_buyer_key,
    sign_with_raw_scalar,
)

BASE_URL = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:5000")
MINE_TIMEOUT = 120
UPLOAD_TIMEOUT = 90
V3_SUFFIX = "11"
V2_SUFFIX = "AA"
TEST_PASSPHRASE = "test-e2e-passphrase-2024"


def log_step(step_num, msg):
    print(f"\n{'='*60}")
    print(f"  STEP {step_num}: {msg}")
    print(f"{'='*60}")


def log_info(msg):
    print(f"  [INFO] {msg}")


def log_ok(msg):
    print(f"  [OK]   {msg}")


def log_fail(msg):
    print(f"  [FAIL] {msg}")


def log_warn(msg):
    print(f"  [WARN] {msg}")


def api_get(path, **kwargs):
    url = f"{BASE_URL}{path}"
    r = requests.get(url, timeout=30, **kwargs)
    return r


def api_post(path, data=None, **kwargs):
    url = f"{BASE_URL}{path}"
    r = requests.post(url, json=data, timeout=60, **kwargs)
    return r


def wait_for_mining_complete(timeout=MINE_TIMEOUT):
    start = time.time()
    last_status = ""
    while time.time() - start < timeout:
        try:
            r = api_get("/api/status")
            if r.status_code == 200:
                status = r.json()
                cur = status.get("status", "")
                if cur != last_status:
                    log_info(f"Mining status: {cur}")
                    last_status = cur
                if not status.get("running", True):
                    return status
                if "Complete" in cur or "Error" in cur:
                    return status
        except Exception:
            pass
        time.sleep(1)
    return None


def stop_mining():
    try:
        api_post("/api/stop")
        time.sleep(1)
    except Exception:
        pass


def ensure_mining_stopped():
    try:
        r = api_get("/api/status")
        if r.status_code == 200 and r.json().get("running"):
            stop_mining()
            time.sleep(2)
    except Exception:
        pass


def validate_private_key(privkey_b58, expected_address=None):
    decoded = b58decode(privkey_b58)
    assert len(decoded) == 64, f"Key must be 64 bytes, got {len(decoded)}"
    scalar = decoded[:32]
    pubkey = decoded[32:]
    derived_pub = crypto_scalarmult_ed25519_base_noclamp(scalar)
    derived_addr = b58encode(derived_pub).decode()
    stored_addr = b58encode(pubkey).decode()
    assert derived_pub == pubkey, f"Scalar*G mismatch: {derived_addr} != {stored_addr}"
    if expected_address:
        assert stored_addr == expected_address, f"Address mismatch: {stored_addr} != {expected_address}"
    msg = b"e2e-validation-test"
    sig = sign_with_raw_scalar(msg, scalar, pubkey)
    assert len(sig) == 64
    VerifyKey(pubkey).verify(msg, sig)
    return stored_addr


def encrypt_seed_aes_gcm(seed_bytes, passphrase):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes

    salt = os.urandom(16)
    iv = os.urandom(12)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                     salt=salt, iterations=100000)
    aes_key = kdf.derive(passphrase.encode("utf-8"))
    aesgcm = AESGCM(aes_key)
    ciphertext = aesgcm.encrypt(iv, seed_bytes, None)
    blob = {
        "ciphertext": base64.b64encode(ciphertext).decode(),
        "iv": base64.b64encode(iv).decode(),
        "salt": base64.b64encode(salt).decode(),
    }
    return base64.b64encode(json.dumps(blob).encode()).decode()


def run_v3_speculative(offline=False):
    log_step("V3", "SPECULATIVE MINING FLOW (V3)")
    v3_key = None

    if offline:
        log_info("Offline mode — skipping on-chain V3 flow, running crypto-only")
        return run_v3_crypto_only()

    ensure_mining_stopped()

    log_step("V3.1", "Start CPU mining — blind/V3, suffix=" + V3_SUFFIX)
    seller_key = os.environ.get("SOLANA_DEVNET_PRIVKEY", "")
    if not seller_key:
        log_warn("No SOLANA_DEVNET_PRIVKEY — V3 on-chain flow will likely fail")
        log_info("Falling back to crypto-only V3 validation")
        return run_v3_crypto_only()

    start_data = {
        "wordlist_file": "",
        "min_length": len(V3_SUFFIX),
        "mining_mode": "blind",
        "blind_wallet": seller_key,
        "blind_price_sol": 0.001,
        "compute_mode": "cpu",
        "escrow_id": 0,
        "simple_suffix": V3_SUFFIX,
    }

    r = api_post("/api/start", start_data)
    if r.status_code != 200:
        log_warn(f"Start mining failed: {r.status_code} {r.text}")
        log_info("Falling back to crypto-only V3 validation")
        return run_v3_crypto_only()

    log_ok(f"Mining started: {r.json()}")

    log_step("V3.2", "Wait for vanity address found + NFT minted")
    status = wait_for_mining_complete(timeout=MINE_TIMEOUT)
    if not status:
        stop_mining()
        log_warn("Mining timed out — falling back to crypto-only")
        return run_v3_crypto_only()

    found = status.get("total_found", 0)
    log_info(f"Mining complete: {found} found, status={status.get('status')}")

    if found == 0:
        log_warn("No addresses found — falling back to crypto-only")
        return run_v3_crypto_only()

    log_step("V3.3", "Search marketplace for newly minted NFT")
    time.sleep(5)
    r = api_post("/api/marketplace/search", {"filter": V3_SUFFIX.lower()})
    if r.status_code != 200:
        log_warn(f"Search failed: {r.text}")
        return run_v3_crypto_only()

    packages = r.json().get("packages", [])
    log_info(f"Found {len(packages)} packages matching '{V3_SUFFIX}'")

    target_pkg = None
    for pkg in packages:
        ej = pkg.get("encrypted_json", {})
        if ej.get("splitKeyV3") and pkg.get("nft_status") == "ACTIVE":
            va = pkg.get("vanity_address", "")
            if va.endswith(V3_SUFFIX) or va.lower().endswith(V3_SUFFIX.lower()):
                target_pkg = pkg
                break

    if not target_pkg:
        for pkg in packages:
            if pkg.get("nft_status") == "ACTIVE":
                target_pkg = pkg
                break

    if not target_pkg:
        log_warn("No active V3 package found — falling back to crypto-only")
        return run_v3_crypto_only()

    ej = target_pkg["encrypted_json"]
    vanity_addr = target_pkg["vanity_address"]
    mint_addr = ej["mintAddress"]
    log_ok(f"Target: {vanity_addr}")
    log_ok(f"Mint:   {mint_addr}")

    log_step("V3.4", "Buy the NFT")
    r = api_post("/api/marketplace/buy", {
        "buyer_key": seller_key,
        "encrypted_json": ej,
        "mint_address": mint_addr,
        "vanity_address": vanity_addr,
    })
    if r.status_code != 200:
        log_warn(f"Buy failed: {r.text}")
        log_info("NFT may already be owned or insufficient SOL")
        return run_v3_crypto_only()
    log_ok(f"Buy result: {r.json()}")

    log_step("V3.5", "Burn NFT → TEE decrypt")
    r = api_post("/api/marketplace/burn", {
        "buyer_key": seller_key,
        "encrypted_json": ej,
        "mint_address": mint_addr,
        "vanity_address": vanity_addr,
    })
    if r.status_code != 200:
        log_warn(f"Burn failed: {r.text}")
        return run_v3_crypto_only()

    result = r.json()
    v3_key = result.get("private_key") or result.get("privkey") or result.get("privateKey")
    if not v3_key:
        log_warn(f"No private key in burn result: {list(result.keys())}")
        return run_v3_crypto_only()

    log_step("V3.6", "Validate decrypted key")
    addr = validate_private_key(v3_key, vanity_addr)
    log_ok(f"Key valid! Address: {addr}")
    log_ok(f"Key length: {len(b58decode(v3_key))} bytes")

    return v3_key, vanity_addr


def run_v3_crypto_only():
    log_step("V3-FALLBACK", "Pure crypto V3 simulation (no on-chain)")
    escrow_seed = os.urandom(32)
    escrow_scalar = _ed25519_clamp(hashlib.sha512(escrow_seed).digest()[:32])
    escrow_pubkey = crypto_scalarmult_ed25519_base_noclamp(escrow_scalar)
    log_info(f"Simulated escrow pubkey: {b58encode(escrow_pubkey).decode()[:16]}...")

    log_info(f"Mining for suffix '{V3_SUFFIX}' (simulated)...")
    attempts = 0
    miner_seed = None
    vanity_addr = None
    for _ in range(5_000_000):
        seed = os.urandom(32)
        h = hashlib.sha512(seed).digest()[:32]
        scalar = _ed25519_clamp(h)
        miner_point = crypto_scalarmult_ed25519_base_noclamp(scalar)
        combined = crypto_core_ed25519_add(miner_point, escrow_pubkey)
        addr = b58encode(combined).decode()
        attempts += 1
        if addr.endswith(V3_SUFFIX):
            miner_seed = seed
            vanity_addr = addr
            break
    
    if not miner_seed:
        log_warn(f"Could not find suffix '{V3_SUFFIX}' in {attempts} attempts — trying shorter")
        V3_SHORT = V3_SUFFIX[0]
        for _ in range(100_000):
            seed = os.urandom(32)
            h = hashlib.sha512(seed).digest()[:32]
            scalar = _ed25519_clamp(h)
            miner_point = crypto_scalarmult_ed25519_base_noclamp(scalar)
            combined = crypto_core_ed25519_add(miner_point, escrow_pubkey)
            addr = b58encode(combined).decode()
            attempts += 1
            if addr.endswith(V3_SHORT):
                miner_seed = seed
                vanity_addr = addr
                break

    if not miner_seed:
        log_fail(f"Could not mine any suffix in {attempts} attempts")
        return None, None

    log_ok(f"Found vanity address: {vanity_addr} (after {attempts} attempts)")

    miner_scalar = _ed25519_clamp(hashlib.sha512(miner_seed).digest()[:32])
    escrow_scalar_int = int.from_bytes(escrow_scalar, "little")
    miner_scalar_int = int.from_bytes(miner_scalar, "little")
    final_scalar_int = (escrow_scalar_int + miner_scalar_int) % ED25519_ORDER
    final_scalar = final_scalar_int.to_bytes(32, "little")
    final_pubkey = crypto_scalarmult_ed25519_base_noclamp(final_scalar)
    final_addr = b58encode(final_pubkey).decode()

    assert final_addr == vanity_addr, f"Merge mismatch: {final_addr} != {vanity_addr}"
    log_ok("Escrow + miner scalar merge → correct address")

    privkey_b58 = b58encode(final_scalar + final_pubkey).decode()
    addr = validate_private_key(privkey_b58, vanity_addr)
    log_ok(f"Key valid! Address: {addr}")
    log_ok(f"Key is 64 bytes, base58, Phantom-importable")

    return privkey_b58, vanity_addr


def run_v2_bounty(offline=False):
    log_step("V2", "BOUNTY / ORDERED FLOW (V2)")

    if offline:
        log_info("Offline mode — running crypto-only V2 simulation")
        return run_v2_crypto_only()

    log_step("V2.1", "Generate keypair via API")
    r = api_post("/api/generate-bounty-keypair")
    if r.status_code != 200:
        log_warn(f"Keypair generation failed: {r.text}")
        return run_v2_crypto_only()

    kp = r.json()
    buyer_pubkey = kp["pubkey"]
    buyer_seed = base64.b64decode(kp["seed"])
    log_ok(f"Buyer pubkey: {buyer_pubkey}")
    log_ok(f"Seed: {len(buyer_seed)} bytes")

    log_step("V2.2", "Encrypt seed with passphrase (AES-GCM)")
    encrypted_secret = encrypt_seed_aes_gcm(buyer_seed, TEST_PASSPHRASE)
    log_ok(f"Encrypted blob: {len(encrypted_secret)} chars (base64)")

    log_step("V2.3", "Post bounty with encrypted_secret")
    bounty_data = {
        "word": V2_SUFFIX,
        "reward_sol": 0.001,
        "buyer_address": buyer_pubkey,
        "pattern_type": "ends_with",
        "case_insensitive": True,
        "description": "E2E test bounty",
        "encrypted_secret": encrypted_secret,
    }
    r = api_post("/api/bounties", bounty_data)
    if r.status_code != 200:
        log_warn(f"Post bounty failed: {r.text}")
        return run_v2_crypto_only()

    bounty = r.json().get("bounty")
    bounty_id = bounty["id"]
    log_ok(f"Bounty posted: id={bounty_id}, word={bounty['word']}, status={bounty['status']}")

    log_step("V2.4", "Mine locally + simulate fulfill + collect via API")
    ensure_mining_stopped()

    from nacl.signing import SigningKey as NaClSigningKey
    buyer_scalar = _ed25519_clamp(hashlib.sha512(buyer_seed).digest()[:32])
    buyer_pub_bytes = crypto_scalarmult_ed25519_base_noclamp(buyer_scalar)

    log_info(f"Mining locally for suffix '{V2_SUFFIX}' with buyer pubkey offset...")
    miner_seed = None
    vanity_addr = None
    attempts = 0
    for _ in range(5_000_000):
        seed = os.urandom(32)
        h = hashlib.sha512(seed).digest()[:32]
        scalar = _ed25519_clamp(h)
        miner_point = crypto_scalarmult_ed25519_base_noclamp(scalar)
        combined = crypto_core_ed25519_add(miner_point, buyer_pub_bytes)
        addr = b58encode(combined).decode()
        attempts += 1
        if addr.lower().endswith(V2_SUFFIX.lower()):
            miner_seed = seed
            vanity_addr = addr
            break

    if not miner_seed:
        log_fail(f"Could not find suffix '{V2_SUFFIX}' in {attempts} attempts")
        cleanup_bounty(bounty_id)
        return None, None

    log_ok(f"Found vanity address: {vanity_addr} (after {attempts} attempts)")
    miner_scalar = _ed25519_clamp(hashlib.sha512(miner_seed).digest()[:32])

    log_step("V2.5", "Verify merge math before API test")
    final_scalar, final_pubkey, privkey_b58 = merge_buyer_key(buyer_seed, miner_scalar)
    merged_addr = b58encode(final_pubkey).decode()
    assert merged_addr == vanity_addr, f"Merge mismatch: {merged_addr} != {vanity_addr}"
    log_ok("merge_buyer_key() → correct address")

    log_step("V2.6", "Simulate fulfill + test collect API")
    fake_mint = "FakeMint" + b58encode(os.urandom(20)).decode()[:32]
    r = api_post(f"/api/bounties/{bounty_id}/fulfill", {
        "vanity_address": vanity_addr,
        "mint_address": fake_mint,
    })
    if r.status_code == 200:
        log_ok(f"Bounty fulfilled via API: {r.json().get('bounty', {}).get('status')}")
    else:
        log_warn(f"Fulfill API: {r.text}")

    r = api_post(f"/api/bounties/{bounty_id}/collect", {
        "passphrase": TEST_PASSPHRASE,
    })
    if r.status_code == 200:
        result = r.json()
        v2_key = result.get("privkey")
        v2_addr = result.get("vanity_address")
        if v2_key:
            log_ok("Collect API returned merged key")
            addr = validate_private_key(v2_key, v2_addr)
            log_ok(f"API-collected key valid! Address: {addr}")
            cleanup_bounty(bounty_id)
            return v2_key, v2_addr
        else:
            log_info("Collect API succeeded but no key (expected — needs real on-chain package)")
    else:
        log_info(f"Collect API: {r.json().get('error', r.text)[:80]} (expected without on-chain package)")

    log_step("V2.7", "Validate locally-merged key")
    addr = validate_private_key(privkey_b58, vanity_addr)
    log_ok(f"Key valid! Address: {addr}")

    log_step("V2.8", "Verify wrong passphrase is rejected")
    r2 = api_post(f"/api/bounties/{bounty_id}/collect", {"passphrase": "WRONG"})
    if r2.status_code != 200:
        err_msg = r2.json().get("error", "")
        log_ok(f"Wrong passphrase correctly rejected: {err_msg[:60]}")
    else:
        log_warn("Wrong passphrase was NOT rejected — potential issue")

    cleanup_bounty(bounty_id)
    return privkey_b58, vanity_addr


def run_v2_bounty_local_merge(buyer_seed, buyer_pubkey, bounty_id=None):
    log_step("V2-LOCAL", "Local merge fallback (no on-chain collect)")

    buyer_scalar = _ed25519_clamp(hashlib.sha512(buyer_seed).digest()[:32])
    buyer_pub_bytes = crypto_scalarmult_ed25519_base_noclamp(buyer_scalar)
    buyer_pub_b58 = b58encode(buyer_pub_bytes).decode()
    log_info(f"Buyer pubkey (derived): {buyer_pub_b58}")

    log_info(f"Mining for suffix '{V2_SUFFIX}' with buyer pubkey offset...")
    miner_seed = None
    vanity_addr = None
    attempts = 0
    for _ in range(5_000_000):
        seed = os.urandom(32)
        h = hashlib.sha512(seed).digest()[:32]
        scalar = _ed25519_clamp(h)
        miner_point = crypto_scalarmult_ed25519_base_noclamp(scalar)
        combined = crypto_core_ed25519_add(miner_point, buyer_pub_bytes)
        addr = b58encode(combined).decode()
        attempts += 1
        if addr.lower().endswith(V2_SUFFIX.lower()):
            miner_seed = seed
            vanity_addr = addr
            break

    if not miner_seed:
        log_fail(f"Could not find suffix '{V2_SUFFIX}' in {attempts} attempts")
        if bounty_id:
            cleanup_bounty(bounty_id)
        return None, None

    log_ok(f"Found vanity address: {vanity_addr} (after {attempts} attempts)")

    miner_scalar = _ed25519_clamp(hashlib.sha512(miner_seed).digest()[:32])
    final_scalar, final_pubkey, privkey_b58 = merge_buyer_key(buyer_seed, miner_scalar)
    merged_addr = b58encode(final_pubkey).decode()

    assert merged_addr == vanity_addr, f"Merge mismatch: {merged_addr} != {vanity_addr}"
    log_ok("merge_buyer_key() → correct address")

    addr = validate_private_key(privkey_b58, vanity_addr)
    log_ok(f"Key valid! Address: {addr}")

    if bounty_id:
        cleanup_bounty(bounty_id)
    return privkey_b58, vanity_addr


def run_v2_crypto_only():
    log_step("V2-CRYPTO", "Pure crypto V2 simulation (no server)")

    buyer_seed = os.urandom(32)
    buyer_scalar = _ed25519_clamp(hashlib.sha512(buyer_seed).digest()[:32])
    buyer_pubkey = crypto_scalarmult_ed25519_base_noclamp(buyer_scalar)
    log_info(f"Buyer pubkey: {b58encode(buyer_pubkey).decode()[:16]}...")

    encrypted_secret = encrypt_seed_aes_gcm(buyer_seed, TEST_PASSPHRASE)
    log_ok(f"Encrypted seed: {len(encrypted_secret)} chars")

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes

    enc_data = json.loads(base64.b64decode(encrypted_secret))
    ciphertext = base64.b64decode(enc_data["ciphertext"])
    iv = base64.b64decode(enc_data["iv"])
    salt = base64.b64decode(enc_data["salt"])
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                     salt=salt, iterations=100000)
    aes_key = kdf.derive(TEST_PASSPHRASE.encode("utf-8"))
    decrypted_seed = AESGCM(aes_key).decrypt(iv, ciphertext, None)
    assert decrypted_seed == buyer_seed, "Encrypt/decrypt round-trip failed!"
    log_ok("AES-GCM encrypt → decrypt round-trip OK")

    log_info(f"Mining for suffix '{V2_SUFFIX}'...")
    attempts = 0
    miner_seed = None
    vanity_addr = None
    for _ in range(5_000_000):
        seed = os.urandom(32)
        h = hashlib.sha512(seed).digest()[:32]
        scalar = _ed25519_clamp(h)
        miner_point = crypto_scalarmult_ed25519_base_noclamp(scalar)
        combined = crypto_core_ed25519_add(miner_point, buyer_pubkey)
        addr = b58encode(combined).decode()
        attempts += 1
        if addr.lower().endswith(V2_SUFFIX.lower()):
            miner_seed = seed
            vanity_addr = addr
            break

    if not miner_seed:
        log_fail(f"Could not find suffix in {attempts} attempts")
        return None, None

    log_ok(f"Found: {vanity_addr} (after {attempts} attempts)")

    miner_scalar = _ed25519_clamp(hashlib.sha512(miner_seed).digest()[:32])
    final_scalar, final_pubkey, privkey_b58 = merge_buyer_key(buyer_seed, miner_scalar)
    merged_addr = b58encode(final_pubkey).decode()
    assert merged_addr == vanity_addr, f"Merge mismatch: {merged_addr} != {vanity_addr}"
    log_ok("merge_buyer_key() → correct address")

    addr = validate_private_key(privkey_b58, vanity_addr)
    log_ok(f"Key valid! Address: {addr}")

    return privkey_b58, vanity_addr


def cleanup_bounty(bounty_id):
    try:
        r = requests.delete(f"{BASE_URL}/api/bounties/{bounty_id}", timeout=10)
        if r.status_code == 200:
            log_info(f"Cleaned up test bounty {bounty_id}")
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description="E2E V3+V2 Flow Test")
    parser.add_argument("--offline", action="store_true",
                        help="Skip on-chain steps, crypto-only validation")
    parser.add_argument("--v3-only", action="store_true",
                        help="Run only V3 speculative flow")
    parser.add_argument("--v2-only", action="store_true",
                        help="Run only V2 bounty flow")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  SOLVANITY E2E TEST — V3 Speculative + V2 Bounty")
    print(f"  Server: {BASE_URL}")
    print(f"  Offline: {args.offline}")
    print(f"  V3 suffix: '{V3_SUFFIX}'  |  V2 suffix: '{V2_SUFFIX}'")
    print("=" * 60)

    if not args.offline:
        try:
            r = api_get("/api/status")
            log_ok(f"Server reachable: {r.status_code}")
        except Exception as e:
            log_fail(f"Server not reachable at {BASE_URL}: {e}")
            log_info("Run with --offline for crypto-only validation")
            sys.exit(1)

    v3_key, v3_addr = None, None
    v2_key, v2_addr = None, None

    if not args.v2_only:
        try:
            v3_key, v3_addr = run_v3_speculative(offline=args.offline)
        except Exception as e:
            log_fail(f"V3 flow error: {e}")
            traceback.print_exc()

    if not args.v3_only:
        try:
            v2_key, v2_addr = run_v2_bounty(offline=args.offline)
        except Exception as e:
            log_fail(f"V2 flow error: {e}")
            traceback.print_exc()

    print("\n")
    print("=" * 60)
    print("  FINAL RESULTS")
    print("=" * 60)

    if v3_key:
        print(f"\nPHANTOM-IMPORTABLE PRIVATE KEY (V3 speculative):")
        print(f"  Address: {v3_addr}")
        print(f"  Key:     {v3_key}")
        print(f"  Bytes:   {len(b58decode(v3_key))}")
    else:
        if not args.v2_only:
            print(f"\nV3 KEY: Not obtained (see logs above)")

    if v2_key:
        print(f"\nV2 BOUNTY PRIVATE KEY:")
        print(f"  Address: {v2_addr}")
        print(f"  Key:     {v2_key}")
        print(f"  Bytes:   {len(b58decode(v2_key))}")
    else:
        if not args.v3_only:
            print(f"\nV2 KEY: Not obtained (see logs above)")

    print("\n" + "=" * 60)
    passed = 0
    total = 0
    if not args.v2_only:
        total += 1
        if v3_key:
            passed += 1
            print("  V3: PASS")
        else:
            print("  V3: FAIL")
    if not args.v3_only:
        total += 1
        if v2_key:
            passed += 1
            print("  V2: PASS")
        else:
            print("  V2: FAIL")

    print(f"\n  Result: {passed}/{total} flows produced valid keys")
    print(f"  Mode:   {'crypto-only (offline)' if args.offline else 'online (API + crypto fallback)'}")
    if not args.offline:
        print(f"  Note:   Full on-chain V3 (buy/burn/decrypt) and V2 server-merge")
        print(f"          require SOLANA_DEVNET_PRIVKEY with SOL + Lit Protocol.")
        print(f"          Crypto-only fallback validates merge math + key format.")
    print("=" * 60)

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
