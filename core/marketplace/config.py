from solders.pubkey import Pubkey

PROGRAM_ID = Pubkey.from_string("EHS97x7xVo4svEVrEsVnihXgPLozCFs1BH7Bnkuf2nP6")

PDA_SEED_PREFIX = b"vanity_pkg"

DISCRIMINATOR = bytes([165, 105, 103, 168, 229, 214, 177, 251])

RPC_URL = "https://api.devnet.solana.com"

LIT_NETWORK = "datil"

ACCESS_CONTROL_CONDITIONS = [
    {
        "conditionType": "solRpc",
        "method": "getBalance",
        "params": [":userAddress"],
        "chain": "solanaDevnet",
        "returnValueTest": {"key": "", "comparator": ">=", "value": "1000000"},
    }
]
