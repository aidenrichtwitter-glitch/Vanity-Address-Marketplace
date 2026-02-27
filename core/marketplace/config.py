from solders.pubkey import Pubkey

PROGRAM_ID = Pubkey.from_string("5saJBeNvrbQ4WcVueFietuBxAixnV1u8StXUriXUuFj5")

PDA_SEED_PREFIX = b"vanity_pkg"

INSTRUCTION_DISCRIMINATOR = bytes([165, 105, 103, 168, 229, 214, 177, 251])

ACCOUNT_DISCRIMINATOR = bytes([0x18, 0x46, 0x62, 0xBF, 0x3A, 0x90, 0x7B, 0x9E])

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
