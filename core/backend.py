"""Shared backend logic for both web app and desktop GUI.

Provides unified APIs for:
  - Marketplace: search, buy & burn
  - Bounty board: load, create, delete, fulfill
  - Blind upload: mint NFT + build package + upload to PDA
"""

import json
import logging
import os
import threading
import time
import traceback as _tb
from pathlib import Path

log = logging.getLogger("backend")

BOUNTIES_FILE = Path("bounties.json")

_upload_lock = threading.Lock()

_trusted_lit_hash_cache = None


def _get_trusted_lit_hash():
    global _trusted_lit_hash_cache
    if _trusted_lit_hash_cache is None:
        try:
            from core.marketplace.lit_encrypt import get_lit_action_hash
            _trusted_lit_hash_cache = get_lit_action_hash()
        except Exception:
            _trusted_lit_hash_cache = ""
    return _trusted_lit_hash_cache


def _verify_package_hash(encrypted_json):
    stored_hash = encrypted_json.get("litActionHash", "")
    trusted = _get_trusted_lit_hash()
    if not trusted:
        return False, "Could not compute trusted code hash"
    if not stored_hash:
        return False, "Package missing code hash — cannot verify integrity"
    if stored_hash != trusted:
        return False, "Package was encrypted by unverified code. Purchase blocked for your safety."
    return True, ""


def load_bounties():
    if BOUNTIES_FILE.exists():
        try:
            return json.loads(BOUNTIES_FILE.read_text())
        except Exception:
            return []
    return []


def save_bounties(bounties):
    BOUNTIES_FILE.write_text(json.dumps(bounties, indent=2))


def create_bounty(word, reward_sol, buyer_address, notes=""):
    word = word.strip().lower()
    if not word:
        return None, "Word is required"
    reward_sol = float(reward_sol)
    if reward_sol <= 0:
        return None, "Reward must be greater than 0"
    buyer_address = buyer_address.strip()
    if not buyer_address:
        return None, "Buyer wallet address is required"

    bounty = {
        "id": int(time.time() * 1000),
        "word": word,
        "reward_sol": reward_sol,
        "reward_lamports": int(reward_sol * 1_000_000_000),
        "buyer_address": buyer_address,
        "notes": notes.strip(),
        "status": "open",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    bounties = load_bounties()
    bounties.append(bounty)
    save_bounties(bounties)
    return bounty, None


def delete_bounty(bounty_id):
    bounties = load_bounties()
    bounties = [b for b in bounties if b.get("id") != bounty_id]
    save_bounties(bounties)
    return True


def fulfill_bounty(bounty_id, vanity_address, mint_address):
    bounties = load_bounties()
    bounty = None
    for b in bounties:
        if b.get("id") == bounty_id:
            bounty = b
            break
    if not bounty:
        return None, "Bounty not found"
    if bounty.get("status") != "open":
        return None, "Bounty is no longer open"

    bounty["status"] = "fulfilled"
    bounty["vanity_address"] = vanity_address.strip()
    bounty["mint_address"] = mint_address.strip()
    bounty["fulfilled_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save_bounties(bounties)
    return bounty, None


def _enrich_packages(packages):
    from core.marketplace.nft import check_nft_supply

    for pkg in packages:
        mint_addr = pkg.get("encrypted_json", {}).get("mintAddress", "")
        if mint_addr:
            try:
                supply = check_nft_supply(mint_addr)
                pkg["nft_status"] = "ACTIVE" if supply > 0 else "BURNED"
            except Exception:
                pkg["nft_status"] = "unknown"
        else:
            pkg["nft_status"] = "no NFT"

        enc_json = pkg.get("encrypted_json", {})

        tee_flag = enc_json.get("encryptedInTEE", False)
        if tee_flag:
            stored_hash = enc_json.get("litActionHash", "")
            if stored_hash and stored_hash == _get_trusted_lit_hash():
                pkg["verified"] = "TEE Verified"
            else:
                pkg["verified"] = "Unknown Code"
        else:
            pkg["verified"] = "Unverified"

        price_lamports = enc_json.get("priceLamports", 0)
        if price_lamports and int(price_lamports) > 0:
            sol = int(price_lamports) / 1_000_000_000
            pkg["price"] = f"{sol:.4f} SOL" if sol < 1 else f"{sol:.2f} SOL"
            pkg["price_lamports"] = int(price_lamports)
        else:
            pkg["price"] = "Free"
            pkg["price_lamports"] = 0

    return packages


def search_packages(search_filter=""):
    from core.marketplace.solana_client import fetch_all_packages

    packages = fetch_all_packages()
    packages = _enrich_packages(packages)

    packages = [
        p for p in packages
        if p.get("nft_status") == "ACTIVE"
        and p.get("verified") == "TEE Verified"
    ]

    search_filter = (search_filter or "").strip().lower()
    if search_filter:
        packages = [
            p for p in packages
            if search_filter in p.get("vanity_address", "").lower()
            or search_filter in (p.get("encrypted_json", {}).get("vanityWord", "")).lower()
        ]

    return packages


def get_owned_nfts(buyer_key, log_fn=None):
    if log_fn is None:
        log_fn = lambda msg: log.info(msg)

    if not buyer_key:
        return None, "Wallet private key required"

    try:
        from core.marketplace.solana_client import load_seller_keypair, fetch_all_packages
        from core.marketplace.nft import check_nft_supply, check_token_balance

        buyer_kp = load_seller_keypair(buyer_key)
        buyer_pub = buyer_kp.pubkey()
        log_fn(f"Checking NFTs for {buyer_pub}...")

        packages = fetch_all_packages()
        packages = _enrich_packages(packages)

        owned = []
        for pkg in packages:
            if pkg.get("nft_status") != "ACTIVE":
                continue
            mint_addr = pkg.get("encrypted_json", {}).get("mintAddress", "")
            if not mint_addr:
                continue
            try:
                balance = check_token_balance(buyer_pub, mint_addr)
                if balance > 0:
                    owned.append(pkg)
            except Exception:
                pass

        log_fn(f"Found {len(owned)} owned NFTs")
        return {"owned": owned, "wallet": str(buyer_pub)}, None

    except Exception as e:
        log_fn(f"Failed to check owned NFTs: {e}")
        return None, str(e)


def buy_nft(buyer_key, encrypted_json, mint_address, vanity_address,
            seller_key_override="", log_fn=None):
    if log_fn is None:
        log_fn = lambda msg: log.info(msg)

    log_fn("=== BUY NFT START ===")
    log_fn(f"  Vanity: {vanity_address}")
    log_fn(f"  Mint: {mint_address}")

    if not buyer_key:
        return None, "Buyer private key required"
    if not encrypted_json:
        return None, "No encrypted data"
    if not mint_address:
        return None, "No NFT mint address"

    verified, verify_err = _verify_package_hash(encrypted_json)
    if not verified:
        log_fn(f"  BLOCKED: {verify_err}")
        return None, verify_err

    try:
        from core.marketplace.solana_client import load_seller_keypair, transfer_sol
        from core.marketplace.nft import check_nft_supply, check_token_balance, transfer_nft
        from solders.pubkey import Pubkey as SoldersPubkey

        supply = check_nft_supply(mint_address)
        log_fn(f"  NFT supply = {supply}")
        if supply == 0:
            return None, "NFT already burned — key was already sold"

        buyer_kp = load_seller_keypair(buyer_key)
        buyer_pub = str(buyer_kp.pubkey())
        log_fn(f"  Buyer: {buyer_pub}")

        balance = check_token_balance(buyer_kp.pubkey(), mint_address)
        if balance > 0:
            return None, "You already own this NFT"

        price_lamports = int(encrypted_json.get("priceLamports", 0))
        seller_addr = encrypted_json.get("sellerAddress", "")
        payment_sig = None

        if price_lamports > 0 and seller_addr:
            seller_pubkey = SoldersPubkey.from_string(seller_addr)
            from solana.rpc.api import Client as SolClient
            from solana.rpc.commitment import Confirmed as SolConfirmed
            sol_client = SolClient("https://api.devnet.solana.com")
            buyer_balance = sol_client.get_balance(buyer_kp.pubkey(), SolConfirmed).value
            log_fn(f"  Buyer balance: {buyer_balance / 1e9:.4f} SOL")
            if buyer_balance < price_lamports + 10_000:
                return None, f"Insufficient SOL. Need {price_lamports / 1e9:.4f} + fees, have {buyer_balance / 1e9:.4f}"

            log_fn(f"  Paying {price_lamports / 1e9:.4f} SOL to {seller_addr[:12]}...")
            payment_sig = transfer_sol(buyer_kp, seller_pubkey, price_lamports)
            log_fn(f"  Payment sent: {payment_sig}")
            time.sleep(2)
        else:
            log_fn("  No payment required (free)")

        seller_key_env = seller_key_override or os.environ.get("SOLANA_DEVNET_PRIVKEY", "")
        if not seller_key_env:
            return None, "Seller key not available for NFT transfer"

        seller_kp_for_transfer = load_seller_keypair(seller_key_env)
        if seller_addr and str(seller_kp_for_transfer.pubkey()) != seller_addr:
            return None, f"Seller key mismatch: server key is {str(seller_kp_for_transfer.pubkey())[:12]}... but package seller is {seller_addr[:12]}..."

        log_fn("  Transferring NFT to buyer...")
        transfer_sig = transfer_nft(seller_kp_for_transfer, buyer_kp.pubkey(), mint_address)
        log_fn(f"  NFT transferred: {transfer_sig}")

        result = {
            "ok": True,
            "vanity_address": vanity_address,
            "mint_address": mint_address,
            "buyer": buyer_pub,
            "transfer_sig": transfer_sig,
        }
        if payment_sig:
            result["payment_sig"] = payment_sig
            result["price_sol"] = price_lamports / 1_000_000_000

        log_fn("=== BUY NFT COMPLETE ===")
        return result, None

    except Exception as e:
        log_fn(f"=== BUY NFT FAILED: {e} ===")
        log_fn(f"  Traceback: {_tb.format_exc()}")
        return None, str(e)


def burn_and_decrypt(buyer_key, encrypted_json, mint_address, vanity_address,
                     log_fn=None):
    if log_fn is None:
        log_fn = lambda msg: log.info(msg)

    log_fn("=== BURN & DECRYPT START ===")
    log_fn(f"  Vanity: {vanity_address}")
    log_fn(f"  Mint: {mint_address}")

    if not buyer_key:
        return None, "Buyer private key required"
    if not encrypted_json:
        return None, "No encrypted data"
    if not mint_address:
        return None, "No NFT mint address"

    verified, verify_err = _verify_package_hash(encrypted_json)
    if not verified:
        log_fn(f"  BLOCKED: {verify_err}")
        return None, verify_err

    try:
        from core.marketplace.solana_client import load_seller_keypair
        from core.marketplace.nft import burn_nft, check_nft_supply, check_token_balance

        supply = check_nft_supply(mint_address)
        if supply == 0:
            return None, "NFT already burned — key was already sold"

        buyer_kp = load_seller_keypair(buyer_key)
        log_fn(f"  Buyer: {buyer_kp.pubkey()}")

        balance = check_token_balance(buyer_kp.pubkey(), mint_address)
        log_fn(f"  NFT balance = {balance}")
        if balance == 0:
            return None, "You don't own this NFT. Buy it first."

        log_fn(f"  Burning NFT {mint_address}...")
        burn_sig = burn_nft(buyer_kp, mint_address)
        log_fn(f"  NFT burned: {burn_sig}")

        privkey = encrypted_json.get("privateKey", "")
        if not privkey:
            log_fn("  Decrypting via Lit Protocol...")
            try:
                from core.marketplace.lit_encrypt import decrypt_private_key
                privkey = decrypt_private_key(encrypted_json, buyer_kp=buyer_kp)
                log_fn("  Decryption succeeded")
            except Exception as e:
                log_fn(f"  Decryption failed: {e}")
                privkey = f"(decryption unavailable: {str(e)[:60]})"

        out_dir = Path("decrypted_keys")
        out_dir.mkdir(exist_ok=True)
        out_file = out_dir / f"{vanity_address}.txt"
        lines = [
            f"Vanity Address: {vanity_address}",
            f"Private Key: {privkey}",
            f"NFT Mint: {mint_address}",
            f"Burn TX: {burn_sig}",
        ]
        out_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        log_fn(f"  Key saved to {out_file}")

        log_fn("=== BURN & DECRYPT COMPLETE ===")
        return {
            "ok": True,
            "file": str(out_file),
            "burn_sig": burn_sig,
            "vanity_address": vanity_address,
            "privkey": privkey,
        }, None

    except Exception as e:
        log_fn(f"=== BURN & DECRYPT FAILED: {e} ===")
        log_fn(f"  Traceback: {_tb.format_exc()}")
        return None, str(e)


def relist_nft(owner_key, mint_address, vanity_address, new_price_sol=0,
               log_fn=None):
    if log_fn is None:
        log_fn = lambda msg: log.info(msg)

    log_fn("=== RELIST NFT START ===")
    log_fn(f"  Vanity: {vanity_address}")
    log_fn(f"  Mint: {mint_address}")
    log_fn(f"  New price: {new_price_sol} SOL")

    if not owner_key:
        return None, "Owner private key required"
    if not mint_address:
        return None, "No NFT mint address"

    try:
        from core.marketplace.solana_client import (
            load_seller_keypair, fetch_all_packages, upload_package, get_pda
        )
        from core.marketplace.nft import check_nft_supply, check_token_balance
        from solders.pubkey import Pubkey as SoldersPubkey

        supply = check_nft_supply(mint_address)
        if supply == 0:
            return None, "NFT already burned — cannot relist"

        owner_kp = load_seller_keypair(owner_key)
        owner_pub = str(owner_kp.pubkey())
        log_fn(f"  Owner: {owner_pub}")

        balance = check_token_balance(owner_kp.pubkey(), mint_address)
        if balance == 0:
            return None, "You don't own this NFT"

        log_fn("  Fetching existing package data...")
        packages = fetch_all_packages()
        existing_pkg = None
        pkg_vanity = None
        for p in packages:
            enc = p.get("encrypted_json", {})
            if enc.get("mintAddress") == mint_address:
                existing_pkg = enc
                pkg_vanity = p.get("vanity_address", "")
                break

        if not existing_pkg:
            return None, "Package not found on-chain for this NFT"

        if pkg_vanity and pkg_vanity != vanity_address:
            return None, f"Vanity address mismatch: on-chain={pkg_vanity[:16]}... vs provided={vanity_address[:16]}..."

        existing_pkg["sellerAddress"] = owner_pub
        try:
            new_price_lamports = int(float(new_price_sol) * 1_000_000_000)
        except (TypeError, ValueError):
            new_price_lamports = existing_pkg.get("priceLamports", 0)
        existing_pkg["priceLamports"] = new_price_lamports
        log_fn(f"  Updated seller to {owner_pub}, price to {new_price_lamports} lamports ({new_price_lamports / 1e9:.4f} SOL)")

        vanity_pubkey = SoldersPubkey.from_string(pkg_vanity or vanity_address)
        result = upload_package(
            seller_kp=owner_kp,
            vanity_pubkey=vanity_pubkey,
            encrypted_json=existing_pkg,
        )
        log_fn(f"  Relist uploaded: {result.get('signature', '')[:40]}...")

        log_fn("=== RELIST COMPLETE ===")
        return {
            "ok": True,
            "vanity_address": vanity_address,
            "mint_address": mint_address,
            "new_price_sol": float(new_price_sol),
            "new_seller": owner_pub,
            "signature": result.get("signature", ""),
            "pda": result.get("pda", ""),
        }, None

    except Exception as e:
        log_fn(f"=== RELIST FAILED: {e} ===")
        log_fn(f"  Traceback: {_tb.format_exc()}")
        return None, str(e)


def blind_upload(pv_bytes, pubkey, wallet, vanity_word="", price_sol=0,
                 log_fn=None, mp_fn=None, on_success=None, on_error=None,
                 session_blob=None):
    if log_fn is None:
        log_fn = lambda msg: log.info(f"[Blind] {msg}")
    if mp_fn is None:
        mp_fn = lambda msg: log.info(f"[MP] {msg}")

    word_label = f" ({vanity_word})" if vanity_word else ""
    price_display = f"{float(price_sol):.4f} SOL" if price_sol and float(price_sol) > 0 else "Free"
    is_split_key = session_blob is not None

    log_fn(f"=== BLIND UPLOAD START for {pubkey[:16]}...{word_label} ===")
    mp_fn(f"--- Upload started for {pubkey}{word_label} ---")
    mp_fn(f"  Price setting: {price_display}")
    mp_fn(f"  Wallet: {wallet[:8]}...({len(wallet)} chars)")
    if is_split_key:
        mp_fn(f"  Protocol: Split-key (oblivious mining)")

    def _upload():
        with _upload_lock:
            _upload_inner()

    def _upload_inner():
        try:
            mp_fn("  Step 1/7: Importing modules...")
            import base58 as b58_mod
            import hashlib as _hashlib
            from nacl.signing import SigningKey
            from core.marketplace.solana_client import load_seller_keypair, upload_package
            from core.marketplace.nft import mint_nft
            from core.marketplace.lit_encrypt import encrypt_private_key, split_key_encrypt
            from solders.pubkey import Pubkey
            mp_fn("  Step 1/7: Imports OK")
        except Exception as e:
            log_fn(f"IMPORT FAILED: {e}")
            mp_fn(f"  FATAL: Import failed: {e}")
            mp_fn(f"  Traceback: {_tb.format_exc()}")
            if on_error:
                on_error(str(e), pubkey)
            return

        try:
            mp_fn("  Step 2/7: Loading seller keypair...")
            seller_kp = load_seller_keypair(wallet)
            seller_pubkey = str(seller_kp.pubkey())
            mp_fn(f"  Step 2/7: Seller loaded: {seller_pubkey}")
        except Exception as e:
            log_fn(f"WALLET LOAD FAILED: {e}")
            mp_fn(f"  FATAL: Could not load seller wallet: {e}")
            mp_fn(f"  Wallet input length: {len(wallet)} chars")
            mp_fn(f"  Traceback: {_tb.format_exc()}")
            if on_error:
                on_error(str(e), pubkey)
            return

        if is_split_key:
            try:
                mp_fn("  Step 3/7: Deriving miner scalar from seed (split-key)...")
                seed_hash = _hashlib.sha512(pv_bytes).digest()
                miner_scalar = bytearray(seed_hash[:32])
                miner_scalar[0] &= 248
                miner_scalar[31] &= 63
                miner_scalar[31] |= 64
                mp_fn(f"  Step 3/7: Miner scalar derived (full key never materializes)")
            except Exception as e:
                log_fn(f"SCALAR DERIVATION FAILED: {e}")
                mp_fn(f"  FATAL: Failed to derive miner scalar: {e}")
                mp_fn(f"  Traceback: {_tb.format_exc()}")
                if on_error:
                    on_error(str(e), pubkey)
                return

            try:
                mp_fn("  Step 4/7: Split-key encrypt in TEE (key combined + encrypted inside TEE)...")
                mp_fn("    Sending miner scalar to TEE for combination with TEE scalar...")
                mp_fn("    Full private key will ONLY exist inside TEE")
                encrypted = split_key_encrypt(
                    bytes(miner_scalar), session_blob, pubkey, seller_kp=seller_kp
                )
                mp_fn("  Step 4/7: Split-key encryption SUCCEEDED")
                mp_fn(f"    splitKey: True")
                mp_fn(f"    encryptedInTEE: True")
                mp_fn(f"    litActionHash: {encrypted.get('litActionHash', '')[:16]}...")
                mp_fn(f"    ciphertext length: {len(encrypted.get('ciphertext', ''))}")
            except Exception as e:
                log_fn(f"ABORT: Split-key encryption failed: {e}")
                mp_fn(f"  ABORT: Split-key encryption failed: {e}")
                mp_fn(f"  The full private key was NEVER assembled on this machine.")
                mp_fn(f"  Traceback: {_tb.format_exc()}")
                if on_error:
                    on_error(f"Split-key encryption failed — upload aborted (key never exposed): {e}", pubkey)
                return
        else:
            try:
                mp_fn("  Step 3/7: Encoding private key...")
                sk = SigningKey(pv_bytes)
                pb_bytes = bytes(sk.verify_key)
                privkey_b58 = b58_mod.b58encode(pv_bytes + pb_bytes).decode("utf-8")
                mp_fn(f"  Step 3/7: Private key encoded ({len(privkey_b58)} chars)")
            except Exception as e:
                log_fn(f"KEY ENCODING FAILED: {e}")
                mp_fn(f"  FATAL: Failed to encode private key: {e}")
                mp_fn(f"  Traceback: {_tb.format_exc()}")
                if on_error:
                    on_error(str(e), pubkey)
                return

            try:
                mp_fn("  Step 4/7: Encrypting private key with Lit Protocol (TEE)...")
                mp_fn("    Connecting to Lit datil network...")
                encrypted = encrypt_private_key(privkey_b58, pubkey, seller_kp=seller_kp)
                mp_fn("  Step 4/7: Lit encryption SUCCEEDED (direct encrypt, real authSig)")
                mp_fn(f"    encryptedInTEE: True")
                mp_fn(f"    litActionHash: {encrypted.get('litActionHash', '')[:16]}...")
                mp_fn(f"    ciphertext length: {len(encrypted.get('ciphertext', ''))}")
                mp_fn(f"    conditions: solRpcConditions (getBalance > 0)")
            except Exception as e:
                log_fn(f"ABORT: Lit Protocol encryption failed — cannot upload without encryption: {e}")
                mp_fn(f"  ABORT: Lit Protocol encryption failed: {e}")
                mp_fn(f"  The private key will NOT be uploaded in plaintext.")
                mp_fn(f"  Lit Protocol must be reachable for blind uploads to work securely.")
                mp_fn(f"  Traceback: {_tb.format_exc()}")
                if on_error:
                    on_error(f"Lit encryption failed — upload aborted (key not exposed): {e}", pubkey)
                return

        try:
            mp_fn("  Step 5/7: Minting NFT on devnet...")
            mp_fn(f"    Seller: {seller_pubkey}")
            mint_address, mint_cost_lamports = mint_nft(seller_kp)
            mint_cost_sol = mint_cost_lamports / 1e9
            log_fn(f"NFT minted: {mint_address} (cost: {mint_cost_sol:.6f} SOL)")
            mp_fn(f"  Step 5/7: NFT minted OK: {mint_address}")
            mp_fn(f"    Mint cost: {mint_cost_sol:.6f} SOL ({mint_cost_lamports} lamports)")
            mp_fn(f"    Explorer: https://explorer.solana.com/address/{mint_address}?cluster=devnet")
        except Exception as e:
            log_fn(f"MINT FAILED: {e}")
            mp_fn(f"  FATAL: NFT mint failed: {e}")
            mp_fn(f"  Key was encrypted but NFT could not be minted")
            mp_fn(f"  This usually means insufficient SOL or RPC error")
            mp_fn(f"  Traceback: {_tb.format_exc()}")
            if on_error:
                on_error(str(e), pubkey)
            return

        try:
            mp_fn("  Step 6/7: Building encrypted package JSON...")
            package_json = {
                "vanityAddress": pubkey,
                "ciphertext": encrypted["ciphertext"],
                "dataToEncryptHash": encrypted["dataToEncryptHash"],
                "solRpcConditions": encrypted.get("solRpcConditions", []),
                "litActionHash": encrypted.get("litActionHash", ""),
                "mintAddress": mint_address,
                "sellerAddress": seller_pubkey,
                "encryptedInTEE": True,
            }
            if is_split_key:
                package_json["splitKey"] = True
            for extra_key in ("iv", "wrappedKey", "wrapIv", "litNetwork"):
                if extra_key in encrypted:
                    package_json[extra_key] = encrypted[extra_key]
            if vanity_word:
                package_json["vanityWord"] = vanity_word
            if price_sol and float(price_sol) > 0:
                package_json["priceLamports"] = int(float(price_sol) * 1_000_000_000)
                mp_fn(f"    Price: {price_display} ({package_json['priceLamports']} lamports)")

            json_size = len(json.dumps(package_json))
            mp_fn(f"  Step 6/7: Package built OK ({json_size} bytes, {len(package_json)} fields)")
            mp_fn(f"    Fields: {list(package_json.keys())}")
            if "privateKey" in package_json:
                raise RuntimeError("SECURITY: plaintext privateKey must never be in the package")
        except Exception as e:
            log_fn(f"PACKAGE BUILD FAILED: {e}")
            mp_fn(f"  FATAL: Failed to build package: {e}")
            mp_fn(f"  Traceback: {_tb.format_exc()}")
            if on_error:
                on_error(str(e), pubkey)
            return

        try:
            mp_fn("  Step 7/7: Uploading encrypted package to Solana devnet PDA...")
            vanity_pubkey = Pubkey.from_string(pubkey)
            mp_fn("    Sending transaction...")
            result = upload_package(
                seller_kp=seller_kp,
                vanity_pubkey=vanity_pubkey,
                encrypted_json=package_json,
            )
            result["mint_address"] = mint_address
            result["vanity_word"] = vanity_word

            sig = result.get("signature", "")
            pda_addr = result.get("pda", "")
            explorer_url = result.get("explorer_url", "")
            nft_url = f"https://explorer.solana.com/address/{mint_address}?cluster=devnet"

            log_fn(f"SUCCESS: {pubkey[:20]}... uploaded ({price_display})")
            mp_fn("  Step 7/7: Upload SUCCESS")
            mp_fn("=== UPLOAD COMPLETE (Lit Encrypted) ===")
            mp_fn(f"  Vanity Address: {pubkey}")
            mp_fn(f"  Word: {vanity_word or '(none)'}")
            mp_fn(f"  NFT Mint: {mint_address}")
            mp_fn(f"  PDA: {pda_addr}")
            mp_fn(f"  Price: {price_display}")
            mp_fn(f"  Encrypted: YES (TEE)")
            mp_fn(f"  TX Signature: {sig}")
            mp_fn(f"  TX Explorer: {explorer_url}")
            mp_fn(f"  NFT Explorer: {nft_url}")
            mp_fn("========================")

            if on_success:
                on_success(result, pubkey)
        except Exception as e:
            log_fn(f"UPLOAD TX FAILED: {e}")
            mp_fn(f"  FATAL: Upload transaction failed: {e}")
            mp_fn(f"  NFT was minted ({mint_address}) but package was NOT uploaded")
            mp_fn(f"  The NFT exists on-chain but has no associated package data")
            mp_fn(f"  Traceback: {_tb.format_exc()}")
            if on_error:
                on_error(str(e), pubkey)

    t = threading.Thread(target=_upload, daemon=True)
    t.start()
    return t
