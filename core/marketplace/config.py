from solders.pubkey import Pubkey

PROGRAM_ID = Pubkey.from_string("5saJBeNvrbQ4WcVueFietuBxAixnV1u8StXUriXUuFj5")

PDA_SEED_PREFIX = b"vanity_pkg"

INSTRUCTION_DISCRIMINATOR = bytes([165, 105, 103, 168, 229, 214, 177, 251])

BUY_INSTRUCTION_DISCRIMINATOR = bytes([0xb2, 0x7a, 0x78, 0xb9, 0xf6, 0xe7, 0xc2, 0x0c])

ACCOUNT_DISCRIMINATOR = bytes([0x18, 0x46, 0x62, 0xBF, 0x3A, 0x90, 0x7B, 0x9E])

RPC_URL = "https://api.devnet.solana.com"

LIT_NETWORK = "chipotle-dev"

LIT_API_BASE = "https://api.dev.litprotocol.com/core/v1"

MARKETPLACE_PKP_PUBLIC_KEY = "03137256bae2971c2db56a4302a5d288c51461899097df5fd457b0b6d1f675dcf6"

MARKETPLACE_LIT_API_KEY = "GK4rv4T/ZgPgVNBgIDwzKx1vdM8L/buH+748DqUhIEY="

SOL_RPC_CONDITIONS = [
    {
        "method": "getBalance",
        "params": [":userAddress"],
        "chain": "solanaDevnet",
        "returnValueTest": {"key": "", "comparator": ">", "value": "0"},
        "pdaInterface": {"offset": 0, "fields": {}},
        "pdaKey": "",
    }
]

ACCESS_CONTROL_CONDITIONS = SOL_RPC_CONDITIONS
