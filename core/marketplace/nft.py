import struct
import logging
from typing import Optional

from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import create_account, CreateAccountParams
from solders.instruction import Instruction, AccountMeta
from solders.transaction import VersionedTransaction
from solders.message import MessageV0
from solana.rpc.api import Client
from solana.rpc.commitment import Confirmed
from solana.rpc.types import TxOpts

from core.marketplace.config import RPC_URL

logger = logging.getLogger(__name__)

TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string(
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
)
SYSVAR_RENT = Pubkey.from_string("SysvarRent111111111111111111111111111111111")

MINT_SIZE = 82


def get_associated_token_address(owner: Pubkey, mint: Pubkey) -> Pubkey:
    seeds = [bytes(owner), bytes(TOKEN_PROGRAM_ID), bytes(mint)]
    ata, _ = Pubkey.find_program_address(seeds, ASSOCIATED_TOKEN_PROGRAM_ID)
    return ata


def _init_mint_ix(mint: Pubkey, authority: Pubkey) -> Instruction:
    data = bytes([0, 0]) + bytes(authority) + bytes([0])
    accounts = [
        AccountMeta(mint, is_signer=False, is_writable=True),
        AccountMeta(SYSVAR_RENT, is_signer=False, is_writable=False),
    ]
    return Instruction(TOKEN_PROGRAM_ID, data, accounts)


def _mint_to_ix(mint: Pubkey, dest: Pubkey, authority: Pubkey, amount: int) -> Instruction:
    data = struct.pack("<BQ", 7, amount)
    accounts = [
        AccountMeta(mint, is_signer=False, is_writable=True),
        AccountMeta(dest, is_signer=False, is_writable=True),
        AccountMeta(authority, is_signer=True, is_writable=False),
    ]
    return Instruction(TOKEN_PROGRAM_ID, data, accounts)


def _create_ata_ix(payer: Pubkey, owner: Pubkey, mint: Pubkey) -> Instruction:
    ata = get_associated_token_address(owner, mint)
    accounts = [
        AccountMeta(payer, is_signer=True, is_writable=True),
        AccountMeta(ata, is_signer=False, is_writable=True),
        AccountMeta(owner, is_signer=False, is_writable=False),
        AccountMeta(mint, is_signer=False, is_writable=False),
        AccountMeta(Pubkey.from_string("11111111111111111111111111111111"), is_signer=False, is_writable=False),
        AccountMeta(TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
        AccountMeta(SYSVAR_RENT, is_signer=False, is_writable=False),
    ]
    return Instruction(ASSOCIATED_TOKEN_PROGRAM_ID, bytes(), accounts)


def _burn_ix(token_account: Pubkey, mint: Pubkey, owner: Pubkey, amount: int) -> Instruction:
    data = struct.pack("<BQ", 8, amount)
    accounts = [
        AccountMeta(token_account, is_signer=False, is_writable=True),
        AccountMeta(mint, is_signer=False, is_writable=True),
        AccountMeta(owner, is_signer=True, is_writable=False),
    ]
    return Instruction(TOKEN_PROGRAM_ID, data, accounts)


def _transfer_ix(src: Pubkey, dest: Pubkey, owner: Pubkey, amount: int) -> Instruction:
    data = struct.pack("<BQ", 3, amount)
    accounts = [
        AccountMeta(src, is_signer=False, is_writable=True),
        AccountMeta(dest, is_signer=False, is_writable=True),
        AccountMeta(owner, is_signer=True, is_writable=False),
    ]
    return Instruction(TOKEN_PROGRAM_ID, data, accounts)


def mint_nft(seller_kp: Keypair, rpc_url: str = RPC_URL) -> str:
    logger.info("[mint_nft] Starting mint for seller=%s rpc=%s", seller_kp.pubkey(), rpc_url)
    client = Client(rpc_url)
    mint_kp = Keypair()
    logger.info("[mint_nft] New mint keypair: %s", mint_kp.pubkey())

    logger.info("[mint_nft] Getting rent exemption for %d bytes...", MINT_SIZE)
    rent_resp = client.get_minimum_balance_for_rent_exemption(MINT_SIZE)
    mint_rent = rent_resp.value
    logger.info("[mint_nft] Rent exemption: %d lamports (%.6f SOL)", mint_rent, mint_rent / 1e9)

    create_mint_ix = create_account(CreateAccountParams(
        from_pubkey=seller_kp.pubkey(),
        to_pubkey=mint_kp.pubkey(),
        lamports=mint_rent,
        space=MINT_SIZE,
        owner=TOKEN_PROGRAM_ID,
    ))

    init_mint = _init_mint_ix(mint_kp.pubkey(), seller_kp.pubkey())
    create_ata = _create_ata_ix(seller_kp.pubkey(), seller_kp.pubkey(), mint_kp.pubkey())
    seller_ata = get_associated_token_address(seller_kp.pubkey(), mint_kp.pubkey())
    logger.info("[mint_nft] Seller ATA: %s", seller_ata)
    mint_to = _mint_to_ix(mint_kp.pubkey(), seller_ata, seller_kp.pubkey(), 1)

    logger.info("[mint_nft] Getting latest blockhash...")
    bh_resp = client.get_latest_blockhash(Confirmed)
    blockhash = bh_resp.value.blockhash
    logger.info("[mint_nft] Blockhash: %s", blockhash)

    msg = MessageV0.try_compile(
        payer=seller_kp.pubkey(),
        instructions=[create_mint_ix, init_mint, create_ata, mint_to],
        address_lookup_table_accounts=[],
        recent_blockhash=blockhash,
    )

    tx = VersionedTransaction(msg, [seller_kp, mint_kp])
    logger.info("[mint_nft] Sending transaction (4 instructions: create_account, init_mint, create_ata, mint_to)...")
    sig_resp = client.send_transaction(
        tx, opts=TxOpts(skip_preflight=True, preflight_commitment=Confirmed)
    )

    mint_addr = str(mint_kp.pubkey())
    tx_fee = 5000
    total_cost_lamports = mint_rent + tx_fee
    logger.info("[mint_nft] SUCCESS: Minted NFT %s (sig: %s) cost: %d lamports (%.6f SOL)",
                mint_addr, sig_resp.value, total_cost_lamports, total_cost_lamports / 1e9)
    return mint_addr, total_cost_lamports


def transfer_nft(
    from_kp: Keypair,
    to_pubkey: Pubkey,
    mint_address: str,
    rpc_url: str = RPC_URL,
) -> str:
    logger.info("[transfer_nft] from=%s to=%s mint=%s", from_kp.pubkey(), to_pubkey, mint_address)
    client = Client(rpc_url)
    mint = Pubkey.from_string(mint_address)

    src_ata = get_associated_token_address(from_kp.pubkey(), mint)
    dest_ata = get_associated_token_address(to_pubkey, mint)
    logger.info("[transfer_nft] src_ata=%s dest_ata=%s", src_ata, dest_ata)

    dest_info = client.get_account_info(dest_ata, commitment=Confirmed)
    instructions = []
    if dest_info.value is None:
        logger.info("[transfer_nft] Dest ATA does not exist, creating...")
        instructions.append(_create_ata_ix(from_kp.pubkey(), to_pubkey, mint))
    else:
        logger.info("[transfer_nft] Dest ATA already exists")

    instructions.append(_transfer_ix(src_ata, dest_ata, from_kp.pubkey(), 1))

    bh_resp = client.get_latest_blockhash(Confirmed)
    blockhash = bh_resp.value.blockhash
    logger.info("[transfer_nft] Blockhash: %s, sending %d instructions...", blockhash, len(instructions))

    msg = MessageV0.try_compile(
        payer=from_kp.pubkey(),
        instructions=instructions,
        address_lookup_table_accounts=[],
        recent_blockhash=blockhash,
    )

    tx = VersionedTransaction(msg, [from_kp])
    sig_resp = client.send_transaction(
        tx, opts=TxOpts(skip_preflight=True, preflight_commitment=Confirmed)
    )
    logger.info("[transfer_nft] SUCCESS: NFT %s transferred to %s (sig: %s)", mint_address, to_pubkey, sig_resp.value)
    return str(sig_resp.value)


def burn_nft(owner_kp: Keypair, mint_address: str, rpc_url: str = RPC_URL) -> str:
    logger.info("[burn_nft] owner=%s mint=%s", owner_kp.pubkey(), mint_address)
    client = Client(rpc_url)
    mint = Pubkey.from_string(mint_address)
    owner_ata = get_associated_token_address(owner_kp.pubkey(), mint)
    logger.info("[burn_nft] Owner ATA: %s", owner_ata)

    burn_instruction = _burn_ix(owner_ata, mint, owner_kp.pubkey(), 1)

    bh_resp = client.get_latest_blockhash(Confirmed)
    blockhash = bh_resp.value.blockhash
    logger.info("[burn_nft] Blockhash: %s, sending burn TX...", blockhash)

    msg = MessageV0.try_compile(
        payer=owner_kp.pubkey(),
        instructions=[burn_instruction],
        address_lookup_table_accounts=[],
        recent_blockhash=blockhash,
    )

    tx = VersionedTransaction(msg, [owner_kp])
    sig_resp = client.send_transaction(
        tx, opts=TxOpts(skip_preflight=True, preflight_commitment=Confirmed)
    )
    logger.info("[burn_nft] SUCCESS: Burned NFT %s (sig: %s)", mint_address, sig_resp.value)
    return str(sig_resp.value)


def check_nft_supply(mint_address: str, rpc_url: str = RPC_URL) -> int:
    client = Client(rpc_url)
    mint = Pubkey.from_string(mint_address)
    resp = client.get_account_info(mint, commitment=Confirmed)
    if resp.value is None:
        logger.debug("[check_nft_supply] %s: account not found (supply=0)", mint_address[:16])
        return 0
    data = bytes(resp.value.data)
    if len(data) < 44:
        logger.debug("[check_nft_supply] %s: data too short (%d bytes, supply=0)", mint_address[:16], len(data))
        return 0
    supply = struct.unpack("<Q", data[36:44])[0]
    logger.debug("[check_nft_supply] %s: supply=%d", mint_address[:16], supply)
    return supply


def check_nft_supply_batch(mint_addresses: list, rpc_url: str = RPC_URL) -> dict:
    BATCH_SIZE = 100
    client = Client(rpc_url)
    result = {}

    for i in range(0, len(mint_addresses), BATCH_SIZE):
        chunk = mint_addresses[i : i + BATCH_SIZE]
        pubkeys = [Pubkey.from_string(addr) for addr in chunk]
        resp = client.get_multiple_accounts(pubkeys, commitment=Confirmed)
        for addr, acct in zip(chunk, resp.value):
            if acct is None:
                result[addr] = 0
                continue
            data = bytes(acct.data)
            if len(data) < 44:
                result[addr] = 0
                continue
            result[addr] = struct.unpack("<Q", data[36:44])[0]

    logger.info("[check_nft_supply_batch] checked %d mints in %d batches",
                len(mint_addresses), (len(mint_addresses) + BATCH_SIZE - 1) // BATCH_SIZE)
    return result


def check_token_balance(owner: Pubkey, mint_address: str, rpc_url: str = RPC_URL) -> int:
    client = Client(rpc_url)
    mint = Pubkey.from_string(mint_address)
    ata = get_associated_token_address(owner, mint)
    logger.debug("[check_token_balance] owner=%s mint=%s ata=%s", owner, mint_address[:16], ata)
    resp = client.get_account_info(ata, commitment=Confirmed)
    if resp.value is None:
        logger.debug("[check_token_balance] ATA not found, balance=0")
        return 0
    data = bytes(resp.value.data)
    if len(data) < 72:
        return 0
    amount = struct.unpack("<Q", data[64:72])[0]
    return amount


def check_token_balance_batch(owner: Pubkey, mint_addresses: list, rpc_url: str = RPC_URL) -> dict:
    BATCH_SIZE = 100
    client = Client(rpc_url)
    result = {}

    ata_mint_pairs = []
    for addr in mint_addresses:
        mint = Pubkey.from_string(addr)
        ata = get_associated_token_address(owner, mint)
        ata_mint_pairs.append((ata, addr))

    for i in range(0, len(ata_mint_pairs), BATCH_SIZE):
        chunk = ata_mint_pairs[i : i + BATCH_SIZE]
        chunk_atas = [pair[0] for pair in chunk]
        resp = client.get_multiple_accounts(chunk_atas, commitment=Confirmed)
        for (_, mint_addr), acct in zip(chunk, resp.value):
            if acct is None:
                result[mint_addr] = 0
                continue
            data = bytes(acct.data)
            if len(data) < 72:
                result[mint_addr] = 0
                continue
            result[mint_addr] = struct.unpack("<Q", data[64:72])[0]

    logger.info("[check_token_balance_batch] checked %d ATAs in %d batches",
                len(mint_addresses), (len(mint_addresses) + BATCH_SIZE - 1) // BATCH_SIZE)
    return result


def check_pda_ata_balance_batch(owner_mint_pairs: list, rpc_url: str = RPC_URL) -> dict:
    BATCH_SIZE = 100
    client = Client(rpc_url)
    result = {}

    ata_key_list = []
    for owner, mint_addr in owner_mint_pairs:
        mint = Pubkey.from_string(mint_addr)
        ata = get_associated_token_address(owner, mint)
        ata_key_list.append((ata, mint_addr))

    for i in range(0, len(ata_key_list), BATCH_SIZE):
        chunk = ata_key_list[i : i + BATCH_SIZE]
        chunk_atas = [pair[0] for pair in chunk]
        resp = client.get_multiple_accounts(chunk_atas, commitment=Confirmed)
        for (_, mint_addr), acct in zip(chunk, resp.value):
            if acct is None:
                result[mint_addr] = 0
                continue
            data = bytes(acct.data)
            if len(data) < 72:
                result[mint_addr] = 0
                continue
            result[mint_addr] = struct.unpack("<Q", data[64:72])[0]

    logger.info("[check_pda_ata_balance_batch] checked %d ATAs in %d batches",
                len(owner_mint_pairs), (len(owner_mint_pairs) + BATCH_SIZE - 1) // BATCH_SIZE)
    return result
