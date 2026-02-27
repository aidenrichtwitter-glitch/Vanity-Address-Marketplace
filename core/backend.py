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


def search_packages(search_filter=""):
    from core.marketplace.solana_client import fetch_all_packages
    from core.marketplace.nft import check_nft_supply

    packages = fetch_all_packages()

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
        pkg["verified"] = "TEE Verified" if tee_flag else "Unverified"

        price_lamports = enc_json.get("priceLamports", 0)
        if price_lamports and int(price_lamports) > 0:
            sol = int(price_lamports) / 1_000_000_000
            pkg["price"] = f"{sol:.4f} SOL" if sol < 1 else f"{sol:.2f} SOL"
            pkg["price_lamports"] = int(price_lamports)
        else:
            pkg["price"] = "Free"
            pkg["price_lamports"] = 0

    search_filter = (search_filter or "").strip().lower()
    if search_filter:
        packages = [
            p for p in packages
            if search_filter in p.get("vanity_address", "").lower()
            or search_filter in (p.get("encrypted_json", {}).get("vanityWord", "")).lower()
        ]

    return packages


def buy_and_burn(buyer_key, encrypted_json, mint_address, vanity_address,
                 seller_key_override="", log_fn=None):
    if log_fn is None:
        log_fn = lambda msg: log.info(msg)

    log_fn("=== BUY & BURN START ===")
    log_fn(f"  Vanity: {vanity_address}")
    log_fn(f"  Mint: {mint_address}")
    log_fn(f"  Buyer key provided: {'yes' if buyer_key else 'no'} ({len(buyer_key)} chars)")
    log_fn(f"  encrypted_json keys: {list((encrypted_json or {}).keys())}")

    if not buyer_key:
        return None, "Buyer private key required"
    if not encrypted_json:
        return None, "No encrypted data"
    if not mint_address:
        return None, "No NFT mint address"

    try:
        from core.marketplace.solana_client import load_seller_keypair, transfer_sol
        from core.marketplace.nft import burn_nft, check_nft_supply, check_token_balance, transfer_nft
        from solders.pubkey import Pubkey as SoldersPubkey

        log_fn("  Step 1: Checking NFT supply...")
        supply = check_nft_supply(mint_address)
        log_fn(f"  Step 1: Supply = {supply}")
        if supply == 0:
            return None, "NFT already burned — key was already sold"

        log_fn("  Step 2: Loading buyer keypair...")
        buyer_kp = load_seller_keypair(buyer_key)
        log_fn(f"  Step 2: Buyer pubkey = {buyer_kp.pubkey()}")

        price_lamports = int(encrypted_json.get("priceLamports", 0))
        seller_addr = encrypted_json.get("sellerAddress", "")
        payment_sig = None
        log_fn(f"  Price: {price_lamports} lamports ({price_lamports / 1e9:.4f} SOL), Seller: {seller_addr or '(none)'}")

        if price_lamports > 0 and seller_addr:
            log_fn("  Step 3: SOL payment required, checking balance...")
            seller_pubkey = SoldersPubkey.from_string(seller_addr)
            from solana.rpc.api import Client as SolClient
            from solana.rpc.commitment import Confirmed as SolConfirmed
            sol_client = SolClient("https://api.devnet.solana.com")
            buyer_balance = sol_client.get_balance(buyer_kp.pubkey(), SolConfirmed).value
            log_fn(f"  Step 3: Buyer balance = {buyer_balance} lamports ({buyer_balance / 1e9:.4f} SOL)")
            if buyer_balance < price_lamports + 10_000:
                sol_needed = price_lamports / 1_000_000_000
                sol_have = buyer_balance / 1_000_000_000
                return None, f"Insufficient SOL. Need {sol_needed:.4f} SOL + fees, have {sol_have:.4f} SOL"

            log_fn(f"  Step 3: Transferring {price_lamports} lamports to seller {seller_addr}...")
            payment_sig = transfer_sol(buyer_kp, seller_pubkey, price_lamports)
            log_fn(f"  Step 3: Payment sent, sig = {payment_sig}")
            log_fn("  Step 3: Waiting 2s for confirmation...")
            time.sleep(2)
        else:
            log_fn("  Step 3: No payment required (free)")

        log_fn("  Step 4: Checking buyer NFT balance...")
        balance = check_token_balance(buyer_kp.pubkey(), mint_address)
        log_fn(f"  Step 4: Buyer NFT balance = {balance}")
        if balance == 0:
            if seller_addr:
                seller_key_env = seller_key_override or os.environ.get("SOLANA_DEVNET_PRIVKEY", "")
                if seller_key_env:
                    log_fn("  Step 4: Transferring NFT from seller to buyer...")
                    seller_kp_for_transfer = load_seller_keypair(seller_key_env)
                    transfer_nft(seller_kp_for_transfer, buyer_kp.pubkey(), mint_address)
                    log_fn("  Step 4: NFT transferred to buyer")
                else:
                    return None, "You don't own this NFT. Transfer it first."
            else:
                return None, "You don't own this NFT. Transfer it first."

        log_fn(f"  Step 5: Burning NFT {mint_address}...")
        burn_sig = burn_nft(buyer_kp, mint_address)
        log_fn(f"  Step 5: NFT burned, sig = {burn_sig}")

        privkey = encrypted_json.get("privateKey", "")
        if not privkey:
            log_fn("  Step 6: No plaintext key, attempting Lit decryption...")
            try:
                from core.marketplace.lit_encrypt import decrypt_private_key
                privkey = decrypt_private_key(encrypted_json, buyer_kp=buyer_kp)
                log_fn("  Step 6: Lit decryption succeeded")
            except Exception as e:
                log_fn(f"  Step 6: Lit decryption failed: {e}")
                privkey = f"(decryption unavailable: {str(e)[:60]})"
        else:
            log_fn(f"  Step 6: Plaintext key found in package ({len(privkey)} chars)")

        out_dir = Path("decrypted_keys")
        out_dir.mkdir(exist_ok=True)
        out_file = out_dir / f"{vanity_address}.txt"
        lines = [
            f"Vanity Address: {vanity_address}",
            f"Private Key: {privkey}",
            f"NFT Mint: {mint_address}",
            f"Burn TX: {burn_sig}",
        ]
        if payment_sig:
            lines.append(f"Payment TX: {payment_sig}")
            lines.append(f"Price: {price_lamports} lamports ({price_lamports / 1e9:.4f} SOL)")
        out_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        log_fn(f"  Step 7: Key saved to {out_file}")

        result = {
            "ok": True,
            "file": str(out_file),
            "burn_sig": burn_sig,
            "vanity_address": vanity_address,
            "privkey": privkey,
        }
        if payment_sig:
            result["payment_sig"] = payment_sig
            result["price_sol"] = price_lamports / 1_000_000_000

        log_fn("=== BUY & BURN COMPLETE ===")
        log_fn(f"  Burn sig: {burn_sig}")
        if payment_sig:
            log_fn(f"  Payment sig: {payment_sig}")
        log_fn(f"  Key file: {out_file}")
        return result, None

    except Exception as e:
        log_fn(f"=== BUY & BURN FAILED ===")
        log_fn(f"  Error: {e}")
        log_fn(f"  Traceback: {_tb.format_exc()}")
        return None, str(e)


def blind_upload(pv_bytes, pubkey, wallet, vanity_word="", price_sol=0,
                 log_fn=None, mp_fn=None, on_success=None, on_error=None):
    if log_fn is None:
        log_fn = lambda msg: log.info(f"[Blind] {msg}")
    if mp_fn is None:
        mp_fn = lambda msg: log.info(f"[MP] {msg}")

    word_label = f" ({vanity_word})" if vanity_word else ""
    price_display = f"{float(price_sol):.4f} SOL" if price_sol and float(price_sol) > 0 else "Free"

    log_fn(f"=== BLIND UPLOAD START for {pubkey[:16]}...{word_label} ===")
    mp_fn(f"--- Upload started for {pubkey}{word_label} ---")
    mp_fn(f"  Price setting: {price_display}")
    mp_fn(f"  Wallet: {wallet[:8]}...({len(wallet)} chars)")

    def _upload():
        try:
            mp_fn("  Step 1/7: Importing modules...")
            import base58 as b58_mod
            from nacl.signing import SigningKey
            from core.marketplace.solana_client import load_seller_keypair, upload_package
            from core.marketplace.nft import mint_nft
            from core.marketplace.lit_encrypt import encrypt_private_key
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
            mint_address = mint_nft(seller_kp)
            log_fn(f"NFT minted: {mint_address}")
            mp_fn(f"  Step 5/7: NFT minted OK: {mint_address}")
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
