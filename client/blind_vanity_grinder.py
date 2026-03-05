#!/usr/bin/env python3
"""
Blind Vanity Address Grinder -> Lit Encryption -> On-chain PDA Upload
- Blind generation on Solana devnet
- Privkey encrypted with Lit (never exposed)
- Encrypted package uploaded to PDA via your program
"""

import os
import sys
import json
import time
import base58
import base64

from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import ID as SYSTEM_PROGRAM_ID
from solders.instruction import Instruction, AccountMeta
from solders.transaction import VersionedTransaction
from solders.message import MessageV0
from solana.rpc.api import Client
from solana.rpc.commitment import Confirmed
from solana.rpc.types import TxOpts

try:
    from lit_python_sdk import LitClient
except ImportError:
    print("Error: lit-python-sdk not installed")
    print("Run: pip install lit-python-sdk --force-reinstall")
    sys.exit(1)

RPC_URL = "https://api.devnet.solana.com"
PROGRAM_ID = Pubkey.from_string("EHS97x7xVo4svEVrEsVnihXgPLozCFs1BH7Bnkuf2nP6")

PDA_SEED_PREFIX = b"vanity_pkg"

DISCRIMINATOR = bytes([165, 105, 103, 168, 229, 214, 177, 251])

ACCESS_CONTROL_CONDITIONS = [
    {
        "conditionType": "solRpc",
        "method": "getBalance",
        "params": [":userAddress"],
        "chain": "solanaDevnet",
        "returnValueTest": {"key": "", "comparator": ">", "value": "0"},
    }
]

STATUS_INTERVAL = 250_000


def get_pda(vanity_pubkey: Pubkey) -> Pubkey:
    seeds = [PDA_SEED_PREFIX, bytes(vanity_pubkey)]
    pda, _ = Pubkey.find_program_address(seeds, PROGRAM_ID)
    return pda


def build_upload_ix(
    pda: Pubkey,
    vanity_pubkey: Pubkey,
    encrypted_json: bytes,
    seller: Pubkey,
) -> Instruction:
    data = (
        DISCRIMINATOR
        + bytes(vanity_pubkey)
        + len(encrypted_json).to_bytes(4, "little")
        + encrypted_json
    )

    accounts = [
        AccountMeta(pda, is_signer=False, is_writable=True),
        AccountMeta(seller, is_signer=True, is_writable=True),
        AccountMeta(SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
    ]

    return Instruction(program_id=PROGRAM_ID, accounts=accounts, data=data)


def main():
    print("Blind Vanity Grinder - Lit Encrypt - PDA Upload (devnet)")
    print("Program ID:", PROGRAM_ID)
    print("-" * 50 + "\n")

    client = Client(RPC_URL)

    priv_b58 = os.getenv("SOLANA_DEVNET_PRIVKEY")
    if not priv_b58:
        print("ERROR: Missing env var SOLANA_DEVNET_PRIVKEY")
        print("Set it with: export SOLANA_DEVNET_PRIVKEY=\"your_base58_secret_key\"")
        sys.exit(1)

    seller_kp = Keypair.from_bytes(base58.b58decode(priv_b58))
    print("Using seller wallet:", seller_kp.pubkey())

    lit = LitClient()
    lit.connect()

    prefix = input("Prefix (leave blank to skip): ").strip().lower()
    suffix = input("Suffix (leave blank to skip): ").strip().lower()

    if not prefix and not suffix:
        print("You need at least a prefix or suffix.")
        return

    print(f"\nStarting blind grind for: {prefix or ''}{suffix or ''} ... (Ctrl+C to stop)\n")

    count = 0
    start_time = time.time()

    while True:
        kp = Keypair()
        addr = str(kp.pubkey())
        addr_lower = addr.lower()

        is_match = False
        if prefix and addr_lower.startswith(prefix):
            is_match = True
        if suffix and addr_lower.endswith(suffix):
            is_match = True

        count += 1

        if is_match:
            elapsed = time.time() - start_time
            speed = count / elapsed if elapsed > 0 else 0
            print(f"\nMATCH FOUND after {count:,} attempts (~{speed:,.0f} keys/s)")
            print("Vanity address:", addr)

            priv_b58_str = base58.b58encode(bytes(kp)).decode("utf-8")

            print("Encrypting private key with Lit...")
            try:
                encrypted = lit.encrypt(
                    data=priv_b58_str,
                    access_control_conditions=ACCESS_CONTROL_CONDITIONS,
                    chain="solanaDevnet",
                )
                ciphertext_b64 = encrypted["ciphertext"]
                data_hash_b64 = encrypted["dataToEncryptHash"]
            except Exception as e:
                print("Lit encryption error:", str(e))
                continue

            pkg_json = json.dumps(
                {
                    "ciphertext": ciphertext_b64,
                    "dataToEncryptHash": data_hash_b64,
                    "vanityAddress": addr,
                    "accessControlConditions": ACCESS_CONTROL_CONDITIONS,
                }
            )
            encrypted_json = pkg_json.encode("utf-8")

            pda = get_pda(kp.pubkey())
            print("PDA:", str(pda))

            ix = build_upload_ix(
                pda=pda,
                vanity_pubkey=kp.pubkey(),
                encrypted_json=encrypted_json,
                seller=seller_kp.pubkey(),
            )

            bh_resp = client.get_latest_blockhash(Confirmed)
            blockhash = bh_resp.value.blockhash

            msg = MessageV0.try_compile(
                payer=seller_kp.pubkey(),
                instructions=[ix],
                address_lookup_table_accounts=[],
                recent_blockhash=blockhash,
            )

            tx = VersionedTransaction(msg, [seller_kp])

            try:
                sig_resp = client.send_transaction(
                    tx,
                    opts=TxOpts(skip_preflight=True, preflight_commitment=Confirmed),
                )
                sig = sig_resp.value
                print("\nSuccess - Encrypted vanity package uploaded to PDA!")
                print("PDA address:", str(pda))
                print("Transaction:", str(sig))
                print(f"Explorer: https://explorer.solana.com/tx/{sig}?cluster=devnet")
                break
            except Exception as e:
                print("Transaction send failed:", str(e))
                continue

        if count % STATUS_INTERVAL == 0:
            elapsed = time.time() - start_time
            speed = count / elapsed if elapsed > 0 else 0
            print(
                f"Progress: {count:,} keys | ~{speed:,.0f} keys/s | {time.strftime('%H:%M:%S')}"
            )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped by user.")
    except Exception as e:
        print("Unexpected error:", str(e))
        sys.exit(1)
