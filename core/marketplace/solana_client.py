import json
import logging
from typing import Optional

import base58 as b58_mod
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import ID as SYSTEM_PROGRAM_ID
from solders.instruction import Instruction, AccountMeta
from solders.transaction import VersionedTransaction
from solders.message import MessageV0
from solana.rpc.api import Client
from solana.rpc.commitment import Confirmed
from solana.rpc.types import TxOpts

from core.marketplace.config import (
    PROGRAM_ID,
    PDA_SEED_PREFIX,
    INSTRUCTION_DISCRIMINATOR,
    ACCOUNT_DISCRIMINATOR,
    RPC_URL,
    SOL_RPC_CONDITIONS,
    LIT_NETWORK,
)

logger = logging.getLogger(__name__)


def transfer_sol(
    from_kp: Keypair,
    to_pubkey: Pubkey,
    lamports: int,
    rpc_url: str = RPC_URL,
) -> str:
    from solders.system_program import transfer, TransferParams
    client = Client(rpc_url)

    ix = transfer(TransferParams(
        from_pubkey=from_kp.pubkey(),
        to_pubkey=to_pubkey,
        lamports=lamports,
    ))

    bh_resp = client.get_latest_blockhash(Confirmed)
    blockhash = bh_resp.value.blockhash

    msg = MessageV0.try_compile(
        payer=from_kp.pubkey(),
        instructions=[ix],
        address_lookup_table_accounts=[],
        recent_blockhash=blockhash,
    )

    tx = VersionedTransaction(msg, [from_kp])
    sig_resp = client.send_transaction(
        tx, opts=TxOpts(skip_preflight=True, preflight_commitment=Confirmed)
    )
    sig = str(sig_resp.value)
    logger.info("Transferred %d lamports to %s (sig: %s)", lamports, to_pubkey, sig)
    return sig


def get_pda(vanity_pubkey: Pubkey) -> Pubkey:
    seeds = [PDA_SEED_PREFIX, bytes(vanity_pubkey)]
    pda, _ = Pubkey.find_program_address(seeds, PROGRAM_ID)
    return pda


def load_seller_keypair(privkey_b58: str) -> Keypair:
    raw = b58_mod.b58decode(privkey_b58)
    return Keypair.from_bytes(raw)


def build_upload_ix(
    pda: Pubkey,
    vanity_pubkey: Pubkey,
    encrypted_json_bytes: bytes,
    seller: Pubkey,
) -> Instruction:
    data = (
        INSTRUCTION_DISCRIMINATOR
        + bytes(vanity_pubkey)
        + len(encrypted_json_bytes).to_bytes(4, "little")
        + encrypted_json_bytes
    )

    accounts = [
        AccountMeta(pda, is_signer=False, is_writable=True),
        AccountMeta(seller, is_signer=True, is_writable=True),
        AccountMeta(SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
    ]

    return Instruction(program_id=PROGRAM_ID, accounts=accounts, data=data)


COMPACT_KEY_MAP = {
    "ciphertext": "ct",
    "iv": "iv",
    "wrappedKey": "wk",
    "wrapIv": "wi",
    "dataToEncryptHash": "dh",
    "vanityAddress": "va",
    "litActionHash": "lh",
    "mintAddress": "ma",
    "sellerAddress": "sa",
    "vanityWord": "vw",
    "priceLamports": "pl",
}

EXPAND_KEY_MAP = {v: k for k, v in COMPACT_KEY_MAP.items()}

STRIP_ON_UPLOAD = {"solRpcConditions", "encryptedInTEE", "litNetwork"}


def _compact_package(pkg: dict) -> dict:
    compact = {}
    for k, v in pkg.items():
        if k in STRIP_ON_UPLOAD:
            continue
        short = COMPACT_KEY_MAP.get(k, k)
        compact[short] = v
    return compact


def _expand_package(compact: dict) -> dict:
    expanded = {}
    for k, v in compact.items():
        full = EXPAND_KEY_MAP.get(k, k)
        expanded[full] = v
    expanded["solRpcConditions"] = SOL_RPC_CONDITIONS
    expanded["encryptedInTEE"] = True
    expanded["litNetwork"] = LIT_NETWORK
    return expanded


def upload_package(
    seller_kp: Keypair,
    vanity_pubkey: Pubkey,
    encrypted_json: dict,
    rpc_url: str = RPC_URL,
) -> dict:
    logger.info("[upload_package] seller=%s vanity=%s rpc=%s", seller_kp.pubkey(), vanity_pubkey, rpc_url)
    client = Client(rpc_url)
    compact = _compact_package(encrypted_json)
    encrypted_json_bytes = json.dumps(compact, separators=(',', ':')).encode("utf-8")
    logger.info("[upload_package] Package JSON size: %d bytes", len(encrypted_json_bytes))
    pda = get_pda(vanity_pubkey)
    logger.info("[upload_package] PDA: %s", pda)

    ix = build_upload_ix(
        pda=pda,
        vanity_pubkey=vanity_pubkey,
        encrypted_json_bytes=encrypted_json_bytes,
        seller=seller_kp.pubkey(),
    )
    logger.info("[upload_package] Instruction built (data_len=%d, accounts=%d)", len(bytes(ix.data)), len(ix.accounts))

    logger.info("[upload_package] Getting latest blockhash...")
    bh_resp = client.get_latest_blockhash(Confirmed)
    blockhash = bh_resp.value.blockhash
    logger.info("[upload_package] Blockhash: %s", blockhash)

    msg = MessageV0.try_compile(
        payer=seller_kp.pubkey(),
        instructions=[ix],
        address_lookup_table_accounts=[],
        recent_blockhash=blockhash,
    )

    tx = VersionedTransaction(msg, [seller_kp])
    logger.info("[upload_package] Sending upload transaction...")
    sig_resp = client.send_transaction(
        tx, opts=TxOpts(skip_preflight=True, preflight_commitment=Confirmed)
    )
    sig = sig_resp.value
    logger.info("[upload_package] SUCCESS: sig=%s pda=%s", sig, pda)

    return {
        "signature": str(sig),
        "pda": str(pda),
        "explorer_url": f"https://explorer.solana.com/tx/{sig}?cluster=devnet",
    }


def fetch_all_packages(rpc_url: str = RPC_URL) -> list:
    logger.info("[fetch_all_packages] Fetching all program accounts from %s (program=%s)...", rpc_url, PROGRAM_ID)
    client = Client(rpc_url)

    resp = client.get_program_accounts(PROGRAM_ID, commitment=Confirmed)

    packages = []
    for acct_key_pair in resp.value:
        pda_str = str(acct_key_pair.pubkey)
        data = bytes(acct_key_pair.account.data)
        parsed = _parse_package_data(data)
        if parsed:
            parsed["pda"] = pda_str
            packages.append(parsed)

    return packages


def fetch_package(pda_str: str, rpc_url: str = RPC_URL) -> Optional[dict]:
    client = Client(rpc_url)
    pda = Pubkey.from_string(pda_str)
    resp = client.get_account_info(pda, commitment=Confirmed)
    if resp.value is None:
        return None
    data = bytes(resp.value.data)
    parsed = _parse_package_data(data)
    if parsed:
        parsed["pda"] = pda_str
    return parsed


def _parse_package_data(data: bytes) -> Optional[dict]:
    try:
        disc = data[:8]
        known_disc = disc in (INSTRUCTION_DISCRIMINATOR, ACCOUNT_DISCRIMINATOR)

        if not known_disc:
            json_start = data.find(b'{"ct"')
            if json_start == -1:
                json_start = data.find(b'{"ciphertext')
            if json_start == -1:
                json_start = data.find(b'{"vanityAddress')
            if json_start == -1:
                return None
            json_str = data[json_start:].decode("utf-8", errors="ignore")
            last_brace = json_str.rfind("}")
            if last_brace > 0:
                json_str = json_str[: last_brace + 1]
            pkg = json.loads(json_str)
            if "ct" in pkg:
                pkg = _expand_package(pkg)
            return {
                "vanity_address": pkg.get("vanityAddress", "unknown"),
                "encrypted_json": pkg,
            }

        offset = 8
        vanity_pubkey_bytes = data[offset : offset + 32]
        offset += 32
        vanity_address = b58_mod.b58encode(vanity_pubkey_bytes).decode("utf-8")

        if offset + 4 > len(data):
            return None
        json_len = int.from_bytes(data[offset : offset + 4], "little")
        offset += 4

        if offset + json_len > len(data):
            return None
        json_bytes = data[offset : offset + json_len]
        try:
            encrypted_json = json.loads(json_bytes.decode("utf-8"))
            if "ct" in encrypted_json:
                encrypted_json = _expand_package(encrypted_json)
        except (UnicodeDecodeError, json.JSONDecodeError):
            encrypted_json = {
                "ciphertext": b58_mod.b58encode(json_bytes).decode("utf-8"),
                "vanityAddress": vanity_address,
                "encryptedInTEE": False,
                "rawBinary": True,
            }

        return {
            "vanity_address": vanity_address,
            "encrypted_json": encrypted_json,
        }
    except Exception as e:
        logger.debug(f"Failed to parse package data: {e}")
        return None
