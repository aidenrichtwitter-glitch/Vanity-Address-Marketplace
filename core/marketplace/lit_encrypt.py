import base58
import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

from core.marketplace.config import SOL_RPC_CONDITIONS, LIT_NETWORK

logger = logging.getLogger(__name__)

_lit_client = None
_lit_lock = threading.Lock()
_lit_action_code = None
_lit_action_hash = None


def _load_lit_action():
    global _lit_action_code, _lit_action_hash
    if _lit_action_hash is not None:
        return

    candidates = [
        Path(__file__).parent / "lit_action.js",
        Path(os.path.dirname(os.path.abspath(__file__))) / "lit_action.js",
    ]

    for p in candidates:
        if p.exists():
            _lit_action_code = p.read_text(encoding="utf-8")
            _lit_action_hash = hashlib.sha256(_lit_action_code.encode("utf-8")).hexdigest()
            logger.info("Loaded Lit Action from %s (hash: %s)", p, _lit_action_hash[:16])
            return

    _lit_action_hash = ""
    _lit_action_code = ""
    logger.warning("lit_action.js not found — litActionHash will be empty (direct encrypt does not require it)")


def get_lit_action_hash() -> str:
    _load_lit_action()
    return _lit_action_hash or ""


def get_lit_action_code() -> str:
    _load_lit_action()
    return _lit_action_code or ""


def _get_lit_client():
    global _lit_client
    with _lit_lock:
        if _lit_client is None:
            import shutil
            import subprocess as _sp
            node_path = shutil.which("node")
            if not node_path:
                raise RuntimeError(
                    "Node.js is not installed or not in PATH. "
                    "Lit Protocol requires Node.js. Install it from https://nodejs.org/"
                )
            try:
                node_ver = _sp.check_output(
                    [node_path, "--version"], timeout=5
                ).decode().strip()
            except Exception:
                node_ver = "unknown"
            logger.info("Node.js found: %s (%s)", node_path, node_ver)

            from lit_python_sdk import LitClient

            orig_wait = LitClient._wait_for_server
            LitClient._wait_for_server = lambda self, timeout=60: orig_wait(self, timeout=timeout)

            from lit_python_sdk.server import NodeServer
            _orig_node_start = NodeServer.start
            _captured_server = [None]

            def _capturing_start(srv_self):
                _captured_server[0] = srv_self
                return _orig_node_start(srv_self)

            NodeServer.start = _capturing_start
            try:
                _lit_client = LitClient()
            except (TimeoutError, Exception) as exc:
                server_logs = ""
                srv = _captured_server[0]
                if srv and hasattr(srv, "get_logs"):
                    server_logs = srv.get_logs()
                log_snippet = ""
                if server_logs:
                    log_snippet = f"\nLit server output:\n{server_logs[-3000:]}"
                _lit_client = None
                raise RuntimeError(
                    f"Lit Node.js server failed to start (Node.js: {node_ver}). "
                    f"Error: {exc}. "
                    f"Make sure Node.js v18+ is installed and no firewall blocks localhost:3092."
                    f"{log_snippet}"
                ) from exc
            finally:
                LitClient._wait_for_server = orig_wait
                NodeServer.start = _orig_node_start

            srv = _captured_server[0]
            if srv and hasattr(srv, "get_logs"):
                startup_logs = srv.get_logs()
                if startup_logs.strip():
                    logger.info("Lit server startup logs:\n%s", startup_logs[-2000:])

            _lit_client.new(lit_network=LIT_NETWORK)
            _lit_client.connect()
            logger.info("Lit Protocol client connected (network: %s)", LIT_NETWORK)
        return _lit_client


def _make_auth_sig(kp):
    from nacl.signing import SigningKey as NaClSigningKey
    from nacl.encoding import RawEncoder

    pubkey_str = str(kp.pubkey())
    message = f"I am creating an account to use Lit Protocol at {int(time.time())}"
    message_bytes = message.encode("utf-8")

    secret_bytes = bytes(kp)
    if len(secret_bytes) == 64:
        seed = secret_bytes[:32]
    else:
        seed = secret_bytes
    nacl_sk = NaClSigningKey(seed, encoder=RawEncoder)
    signed = nacl_sk.sign(message_bytes, encoder=RawEncoder)
    sig_bytes = signed.signature

    sig_b58 = base58.b58encode(sig_bytes).decode("utf-8")

    return {
        "sig": sig_b58,
        "derivedVia": "solana.signMessage",
        "signedMessage": message,
        "address": pubkey_str,
    }


def encrypt_private_key(
    privkey_b58: str,
    vanity_address: str,
    seller_kp=None,
    sol_rpc_conditions: Optional[list] = None,
) -> dict:
    if sol_rpc_conditions is None:
        sol_rpc_conditions = SOL_RPC_CONDITIONS

    _load_lit_action()
    lit = _get_lit_client()

    with _lit_lock:
        result = lit.encrypt_string(
            data_to_encrypt=privkey_b58,
            sol_rpc_conditions=sol_rpc_conditions,
        )

    if isinstance(result, dict):
        ciphertext = result.get("ciphertext", "")
        data_hash = result.get("dataToEncryptHash",
                    result.get("data_to_encrypt_hash", ""))
    else:
        raise RuntimeError(f"Lit encrypt returned unexpected type: {type(result)}")

    if not ciphertext or not data_hash:
        raise RuntimeError(
            f"Lit encrypt returned incomplete result: "
            f"{list(result.keys()) if isinstance(result, dict) else result}"
        )

    package = {
        "ciphertext": ciphertext,
        "dataToEncryptHash": data_hash,
        "vanityAddress": vanity_address,
        "solRpcConditions": sol_rpc_conditions,
        "encryptedInTEE": True,
    }
    if _lit_action_hash:
        package["litActionHash"] = _lit_action_hash

    return package


def decrypt_private_key(
    encrypted_json: dict,
    buyer_kp=None,
    auth_sig: Optional[dict] = None,
    session_sigs: Optional[dict] = None,
) -> str:
    lit = _get_lit_client()

    ciphertext = encrypted_json["ciphertext"]
    data_hash = encrypted_json["dataToEncryptHash"]

    conditions = encrypted_json.get(
        "solRpcConditions",
        encrypted_json.get("accessControlConditions", SOL_RPC_CONDITIONS)
    )

    if auth_sig is None and buyer_kp is not None:
        auth_sig = _make_auth_sig(buyer_kp)

    decrypt_kwargs = {
        "ciphertext": ciphertext,
        "data_to_encrypt_hash": data_hash,
        "sol_rpc_conditions": conditions,
        "chain": "solanaDevnet",
    }
    if session_sigs:
        decrypt_kwargs["session_sigs"] = session_sigs
    if auth_sig:
        decrypt_kwargs["auth_sig"] = auth_sig

    with _lit_lock:
        result = lit.decrypt_string(**decrypt_kwargs)

    if isinstance(result, dict):
        for key in ("decryptedString", "decryptedData", "plaintext"):
            if key in result:
                raw = result[key]
                if isinstance(raw, (bytes, bytearray)):
                    return raw.decode("utf-8")
                return str(raw)
    if isinstance(result, (bytes, bytearray)):
        return result.decode("utf-8")
    if isinstance(result, str):
        return result
    return str(result)
