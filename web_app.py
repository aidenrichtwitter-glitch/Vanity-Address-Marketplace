#!/usr/bin/env python3
import json
import multiprocessing
import os
import queue
import sys
import time
import threading
from pathlib import Path

from flask import Flask, render_template, request, jsonify, Response

from core.word_filter import WordFilter, PAD_CHAR, TAIL_SIZE
from core.word_miner import build_suffix_patterns
from core.config import DEFAULT_ITERATION_BITS
from core.utils.crypto import get_public_key_from_private_bytes, save_keypair
from core.utils.gpu_temp import get_gpu_temp, get_gpu_name, get_recommended_max_temp

app = Flask(__name__)

event_queues = []
event_queues_lock = threading.Lock()

mining_state = {
    "running": False,
    "thread": None,
    "start_time": None,
    "total_found": 0,
    "speed": 0.0,
    "total_keys": 0,
    "status": "Ready",
    "gpu_name": None,
    "gpu_temp": None,
    "gpu_temp_zone": "none",
    "recommended_temp": 80,
    "mining_mode": "mine",
    "suffix_pattern_count": 0,
    "blind_wallet": "",
}
mining_lock = threading.Lock()


def broadcast_event(event_type, data):
    msg = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    with event_queues_lock:
        dead = []
        for q in event_queues:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            event_queues.remove(q)


def mining_worker(word_filter, suffix_patterns, output_dir, iteration_bits,
                  power_pct, max_temp, mining_mode, blind_wallet, stop_event):
    try:
        from core.utils.helpers import build_suffix_buffer, load_kernel_source
        from core.opencl.manager import get_all_gpu_devices

        try:
            gpu_counts = len(get_all_gpu_devices())
        except Exception as e:
            broadcast_event("error", {"msg": f"OpenCL error: {e}\n\nNo GPU found."})
            with mining_lock:
                mining_state["running"] = False
                mining_state["status"] = "Error"
            broadcast_event("stopped", {})
            return

        if gpu_counts == 0:
            broadcast_event("error", {"msg": "No GPU devices found."})
            with mining_lock:
                mining_state["running"] = False
                mining_state["status"] = "Error"
            broadcast_event("stopped", {})
            return

        broadcast_event("log", {"msg": f"Found {gpu_counts} GPU device(s)"})
        broadcast_event("status", {"msg": "Compiling kernel..."})

        suffix_tuple = tuple(suffix_patterns)
        suffix_buffer, suffix_count, suffix_width, suffix_lengths = build_suffix_buffer(suffix_tuple)
        kernel_source = load_kernel_source((), True, suffix_bytes=len(suffix_buffer) if suffix_count > 0 else 0)

        mem_type = "local" if (suffix_count * suffix_width) <= 46080 else "global"
        broadcast_event("log", {"msg": f"Kernel compiled with {len(suffix_patterns)} patterns ({suffix_count * suffix_width} bytes in {mem_type} memory)"})
        broadcast_event("status", {"msg": "Mining..."})

        Path(output_dir).mkdir(parents=True, exist_ok=True)

        result_count = 0
        start_time = time.time()

        from core.word_miner import _persistent_worker

        mp_ctx = multiprocessing.get_context("spawn")
        workers = []
        for idx in range(gpu_counts):
            p_conn, c_conn = mp_ctx.Pipe()
            proc = mp_ctx.Process(
                target=_persistent_worker,
                args=(idx, kernel_source, iteration_bits, gpu_counts, None, c_conn,
                      power_pct, max_temp),
                kwargs={"suffix_buffer": suffix_buffer,
                        "suffix_count": suffix_count,
                        "suffix_width": suffix_width,
                        "suffix_lengths": suffix_lengths},
                daemon=True,
            )
            proc.start()
            workers.append((proc, p_conn))

        for proc, conn in workers:
            if conn.poll(30):
                msg = conn.recv()
            else:
                broadcast_event("error", {"msg": "GPU worker failed to start within 30 seconds"})
                for p, _ in workers:
                    p.terminate()
                with mining_lock:
                    mining_state["running"] = False
                    mining_state["status"] = "Error"
                broadcast_event("stopped", {})
                return

        broadcast_event("log", {"msg": f"Workers running ({gpu_counts} GPU process(es)), mining continuously..."})

        while not stop_event.is_set():
            if mining_state.get("count_limit", 0) > 0 and result_count >= mining_state["count_limit"]:
                break

            for _, conn in workers:
                while conn.poll(0):
                    msg = conn.recv()
                    if not isinstance(msg, dict):
                        continue
                    if msg["type"] == "found":
                        output = msg["data"]
                        pv_bytes = bytes(output[1:])
                        pubkey = get_public_key_from_private_bytes(pv_bytes)
                        word, padding = word_filter.check_address(pubkey)
                        suffix_display = (padding + word) if word else pubkey[-TAIL_SIZE:]
                        if mining_mode != "blind":
                            save_keypair(pv_bytes, output_dir, word=word, pubkey=pubkey)
                        result_count += 1
                        elapsed = time.time() - start_time
                        with mining_lock:
                            mining_state["total_found"] = result_count
                        broadcast_event("found", {
                            "address": pubkey,
                            "suffix": suffix_display,
                            "time": f"{elapsed:.1f}s",
                            "count": result_count,
                        })
                        broadcast_event("log", {"msg": f"[FOUND] #{result_count}: {pubkey} -> {suffix_display}"})

                        if mining_mode == "blind" and blind_wallet:
                            _handle_blind_upload(pv_bytes, pubkey, blind_wallet, suffix_display)

                    elif msg["type"] == "speed":
                        speed = msg["value"]
                        with mining_lock:
                            mining_state["speed"] = speed
                            elapsed = time.time() - start_time
                            mining_state["total_keys"] = int(speed * elapsed)
                        broadcast_event("speed", {
                            "value": speed,
                            "total_keys": mining_state["total_keys"],
                            "suffix_pattern_count": mining_state["suffix_pattern_count"],
                        })
                    elif msg["type"] == "log":
                        broadcast_event("log", {"msg": msg["msg"]})
                    elif msg["type"] == "error":
                        broadcast_event("log", {"msg": f"[GPU ERROR] {msg['msg']}"})

            time.sleep(0.2)

        for _, conn in workers:
            try:
                conn.send("stop")
            except Exception:
                pass
        for proc, _ in workers:
            proc.join(timeout=3)

        with mining_lock:
            mining_state["running"] = False
            mining_state["status"] = f"Complete - {result_count} found"
        broadcast_event("status", {"msg": f"Complete - {result_count} found"})

    except Exception as e:
        broadcast_event("error", {"msg": str(e)})
        with mining_lock:
            mining_state["running"] = False
            mining_state["status"] = "Error"

    broadcast_event("stopped", {})


def _handle_blind_upload(pv_bytes, pubkey, wallet, vanity_word=""):
    price_sol = mining_state.get("blind_price_sol", 0)

    def _upload():
        try:
            import base58 as b58_mod
            from nacl.signing import SigningKey
            from core.marketplace.solana_client import load_seller_keypair, upload_package
            from core.marketplace.nft import mint_nft
            from solders.pubkey import Pubkey

            seller_kp = load_seller_keypair(wallet)
            mint_address = mint_nft(seller_kp)
            broadcast_event("log", {"msg": f"[Blind] NFT minted: {mint_address[:20]}..."})
            broadcast_event("mp_log", {"msg": f"NFT minted: {mint_address}"})

            sk = SigningKey(pv_bytes)
            pb_bytes = bytes(sk.verify_key)
            privkey_b58 = b58_mod.b58encode(pv_bytes + pb_bytes).decode("utf-8")

            package_json = {
                "vanityAddress": pubkey,
                "privateKey": privkey_b58,
                "mintAddress": mint_address,
                "sellerAddress": str(seller_kp.pubkey()),
                "encryptedInTEE": False,
            }
            if vanity_word:
                package_json["vanityWord"] = vanity_word
            if price_sol and float(price_sol) > 0:
                package_json["priceLamports"] = int(float(price_sol) * 1_000_000_000)

            vanity_pubkey = Pubkey.from_string(pubkey)
            result = upload_package(
                seller_kp=seller_kp,
                vanity_pubkey=vanity_pubkey,
                encrypted_json=package_json,
            )
            sig = result.get("signature", "")
            pda = result.get("pda", "")
            explorer_url = result.get("explorer_url", "")
            nft_url = f"https://explorer.solana.com/address/{mint_address}?cluster=devnet" if mint_address else ""
            price_display = f"{float(price_sol):.4f} SOL" if price_sol and float(price_sol) > 0 else "Free"
            broadcast_event("log", {"msg": f"[Blind] SUCCESS: {pubkey[:20]}... uploaded ({price_display})"})
            broadcast_event("mp_log", {"msg": f"SUCCESS: Uploaded {pubkey}"})
            broadcast_event("mp_log", {"msg": f"  NFT Mint: {mint_address}"})
            broadcast_event("mp_log", {"msg": f"  PDA: {pda}"})
            broadcast_event("mp_log", {"msg": f"  Price: {price_display}"})
            broadcast_event("mp_log", {"msg": f"  TX: {sig}"})
            broadcast_event("mp_log", {"msg": f"  Explorer: {explorer_url}"})
            if nft_url:
                broadcast_event("mp_log", {"msg": f"  NFT Explorer: {nft_url}"})
            if vanity_word:
                broadcast_event("mp_log", {"msg": f"  Word: {vanity_word}"})
        except Exception as e:
            broadcast_event("log", {"msg": f"[Blind] FAILED: {str(e)[:60]}"})
            broadcast_event("mp_log", {"msg": f"FAILED: Upload for {pubkey}: {e}"})
            broadcast_event("error", {"msg": f"Blind upload failed for {pubkey[:20]}...: {str(e)[:80]}"})

    t = threading.Thread(target=_upload, daemon=True)
    t.start()


_stop_event = None


def gpu_temp_monitor():
    while True:
        try:
            if not mining_state.get("gpu_name"):
                name = get_gpu_name()
                rec = get_recommended_max_temp(name)
                with mining_lock:
                    mining_state["gpu_name"] = name or "Not detected"
                    mining_state["recommended_temp"] = rec
                broadcast_event("gpu_detected", {"name": name or "Not detected", "recommended_temp": rec})
        except Exception:
            pass
        try:
            temp = get_gpu_temp()
            with mining_lock:
                mining_state["gpu_temp"] = temp
            broadcast_event("temp", {"value": temp})
        except Exception:
            pass
        time.sleep(2)


@app.route("/api/upload-wordlist", methods=["POST"])
def api_upload_wordlist():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "No file selected"}), 400
    upload_dir = Path("uploaded_wordlists")
    upload_dir.mkdir(exist_ok=True)
    safe_name = Path(f.filename).name
    dest = upload_dir / safe_name
    f.save(str(dest))
    return jsonify({"path": str(dest), "filename": safe_name})


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    with mining_lock:
        return jsonify({
            "running": mining_state["running"],
            "status": mining_state["status"],
            "speed": mining_state["speed"],
            "total_found": mining_state["total_found"],
            "total_keys": mining_state["total_keys"],
            "gpu_name": mining_state["gpu_name"],
            "gpu_temp": mining_state["gpu_temp"],
            "recommended_temp": mining_state["recommended_temp"],
            "mining_mode": mining_state["mining_mode"],
        })


def _parse_wordlist_input(raw):
    if not raw or not raw.strip():
        return None, None
    val = raw.strip()
    if os.path.isfile(val):
        return val, None
    words = [w.strip().lower() for w in val.replace(",", " ").split() if w.strip()]
    if words:
        return None, words
    return None, None


@app.route("/api/wordcount", methods=["POST"])
def api_wordcount():
    data = request.json or {}
    min_length = data.get("min_length", 4)
    raw_wordlist = data.get("wordlist_file", "") or ""
    wordlist_file, custom_words = _parse_wordlist_input(raw_wordlist)
    try:
        wf = WordFilter(min_length=min_length, wordlist_file=wordlist_file, custom_words=custom_words)
        patterns = build_suffix_patterns(wf)
        if custom_words:
            source = "inline words"
        elif wordlist_file:
            source = "custom file"
        else:
            source = "built-in"
        return jsonify({
            "words": len(wf.words),
            "patterns": len(patterns),
            "source": source,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/start", methods=["POST"])
def api_start():
    global _stop_event
    with mining_lock:
        if mining_state["running"]:
            return jsonify({"error": "Mining already running"}), 400

    data = request.json or {}
    min_length = data.get("min_length", 4)
    output_dir = data.get("output_dir", "./found_words")
    raw_wordlist = data.get("wordlist_file", "") or ""
    wordlist_file, custom_words = _parse_wordlist_input(raw_wordlist)
    power_pct = data.get("power_pct", 100)
    max_temp = data.get("max_temp", 80)
    mining_mode = data.get("mining_mode", "mine")
    blind_wallet = data.get("blind_wallet", "")
    blind_price_sol = data.get("blind_price_sol", 0)

    try:
        word_filter = WordFilter(min_length=min_length, wordlist_file=wordlist_file, custom_words=custom_words)
        suffix_patterns = build_suffix_patterns(word_filter)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    if custom_words:
        source = f"inline: {', '.join(custom_words)}"
    elif wordlist_file:
        source = f"from {wordlist_file}"
    else:
        source = "from built-in list"
    broadcast_event("log", {"msg": f"Loaded {len(word_filter.words)} words ({source}), {len(suffix_patterns)} suffix patterns"})
    pad_example = "X" * max(0, TAIL_SIZE - min_length)
    broadcast_event("log", {"msg": f"Tail pattern: {pad_example}<word> (last {TAIL_SIZE} chars of address)"})
    broadcast_event("log", {"msg": f"Sample: {', '.join(suffix_patterns[:6])}..."})
    broadcast_event("log", {"msg": f"Power: {power_pct}%  |  Max Temp: {max_temp}°C"})

    _stop_event = threading.Event()

    count_limit = 0
    if mining_mode == "blind":
        count_limit = len(word_filter.words)
        broadcast_event("log", {"msg": f"[Blind] Will stop after finding {count_limit} addresses (one per word)"})

    with mining_lock:
        mining_state["running"] = True
        mining_state["status"] = "Starting..."
        mining_state["start_time"] = time.time()
        mining_state["total_found"] = 0
        mining_state["speed"] = 0.0
        mining_state["total_keys"] = 0
        mining_state["mining_mode"] = mining_mode
        mining_state["suffix_pattern_count"] = len(suffix_patterns)
        mining_state["blind_wallet"] = blind_wallet
        mining_state["blind_price_sol"] = blind_price_sol
        mining_state["count_limit"] = count_limit

    broadcast_event("status", {"msg": "Starting..."})

    t = threading.Thread(
        target=mining_worker,
        args=(word_filter, suffix_patterns, output_dir, DEFAULT_ITERATION_BITS,
              power_pct, max_temp, mining_mode, blind_wallet, _stop_event),
        daemon=True,
    )
    with mining_lock:
        mining_state["thread"] = t
    t.start()

    return jsonify({"ok": True, "words": len(word_filter.words), "patterns": len(suffix_patterns)})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    global _stop_event
    if _stop_event:
        _stop_event.set()
    with mining_lock:
        mining_state["status"] = "Stopping..."
    broadcast_event("status", {"msg": "Stopping..."})
    return jsonify({"ok": True})


@app.route("/api/stream")
def api_stream():
    q = queue.Queue(maxsize=256)
    with event_queues_lock:
        event_queues.append(q)

    def generate():
        try:
            yield f"event: init\ndata: {json.dumps({'status': mining_state['status']})}\n\n"
            while True:
                try:
                    msg = q.get(timeout=30)
                    yield msg
                except queue.Empty:
                    yield ": keepalive\n\n"
        except GeneratorExit:
            pass
        finally:
            with event_queues_lock:
                if q in event_queues:
                    event_queues.remove(q)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/gpu")
def api_gpu():
    with mining_lock:
        return jsonify({
            "name": mining_state["gpu_name"],
            "temp": mining_state["gpu_temp"],
            "recommended_temp": mining_state["recommended_temp"],
        })


BOUNTIES_FILE = Path("bounties.json")


def _load_bounties():
    if BOUNTIES_FILE.exists():
        try:
            return json.loads(BOUNTIES_FILE.read_text())
        except Exception:
            return []
    return []


def _save_bounties(bounties):
    BOUNTIES_FILE.write_text(json.dumps(bounties, indent=2))


@app.route("/api/marketplace/search", methods=["POST"])
def api_marketplace_search():
    data = request.json or {}
    search_filter = data.get("filter", "").strip().lower()

    try:
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
            if tee_flag:
                pkg["verified"] = "TEE Verified"
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

        if search_filter:
            packages = [p for p in packages if search_filter in p.get("vanity_address", "").lower()
                        or search_filter in (p.get("encrypted_json", {}).get("vanityWord", "")).lower()]

        return jsonify({"packages": packages, "total": len(packages)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/marketplace/buy", methods=["POST"])
def api_marketplace_buy():
    data = request.json or {}
    buyer_key = data.get("buyer_key", "").strip()
    encrypted_json = data.get("encrypted_json")
    mint_address = data.get("mint_address", "")
    vanity_address = data.get("vanity_address", "")

    if not buyer_key:
        return jsonify({"error": "Buyer private key required"}), 400
    if not encrypted_json:
        return jsonify({"error": "No encrypted data"}), 400
    if not mint_address:
        return jsonify({"error": "No NFT mint address"}), 400

    try:
        from core.marketplace.solana_client import load_seller_keypair, transfer_sol
        from core.marketplace.nft import burn_nft, check_nft_supply, check_token_balance, transfer_nft
        from solders.pubkey import Pubkey as SoldersPubkey

        supply = check_nft_supply(mint_address)
        if supply == 0:
            return jsonify({"error": "NFT already burned — key was already sold"}), 400

        buyer_kp = load_seller_keypair(buyer_key)

        price_lamports = int(encrypted_json.get("priceLamports", 0))
        seller_addr = encrypted_json.get("sellerAddress", "")
        payment_sig = None

        if price_lamports > 0 and seller_addr:
            seller_pubkey = SoldersPubkey.from_string(seller_addr)
            from solana.rpc.api import Client as SolClient
            from solana.rpc.commitment import Confirmed as SolConfirmed
            sol_client = SolClient("https://api.devnet.solana.com")
            buyer_balance = sol_client.get_balance(buyer_kp.pubkey(), SolConfirmed).value
            if buyer_balance < price_lamports + 10_000:
                sol_needed = price_lamports / 1_000_000_000
                sol_have = buyer_balance / 1_000_000_000
                return jsonify({"error": f"Insufficient SOL. Need {sol_needed:.4f} SOL + fees, have {sol_have:.4f} SOL"}), 400

            payment_sig = transfer_sol(buyer_kp, seller_pubkey, price_lamports)
            import time
            time.sleep(2)

        balance = check_token_balance(buyer_kp.pubkey(), mint_address)
        if balance == 0:
            if seller_addr:
                seller_key_env = os.environ.get("SOLANA_DEVNET_PRIVKEY", "")
                if seller_key_env:
                    seller_kp_for_transfer = load_seller_keypair(seller_key_env)
                    transfer_nft(seller_kp_for_transfer, buyer_kp.pubkey(), mint_address)
                else:
                    return jsonify({"error": "You don't own this NFT. Transfer it first."}), 400

        burn_sig = burn_nft(buyer_kp, mint_address)

        privkey = encrypted_json.get("privateKey", "")
        if not privkey:
            try:
                from core.marketplace.lit_encrypt import decrypt_private_key
                privkey = decrypt_private_key(encrypted_json)
            except Exception as e:
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
        if payment_sig:
            lines.append(f"Payment TX: {payment_sig}")
            lines.append(f"Price: {price_lamports} lamports ({price_lamports / 1e9:.4f} SOL)")
        out_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = {
            "ok": True,
            "file": str(out_file),
            "burn_sig": burn_sig,
            "vanity_address": vanity_address,
        }
        if payment_sig:
            result["payment_sig"] = payment_sig
            result["price_sol"] = price_lamports / 1_000_000_000
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/bounties", methods=["GET"])
def api_bounties_list():
    bounties = _load_bounties()
    return jsonify({"bounties": bounties})


@app.route("/api/bounties", methods=["POST"])
def api_bounties_create():
    data = request.json or {}
    word = data.get("word", "").strip().lower()
    reward_sol = data.get("reward_sol", 0)
    buyer_address = data.get("buyer_address", "").strip()
    notes = data.get("notes", "").strip()

    if not word:
        return jsonify({"error": "Word is required"}), 400
    if not reward_sol or float(reward_sol) <= 0:
        return jsonify({"error": "Reward must be greater than 0"}), 400
    if not buyer_address:
        return jsonify({"error": "Buyer wallet address is required"}), 400

    bounty = {
        "id": int(time.time() * 1000),
        "word": word,
        "reward_sol": float(reward_sol),
        "reward_lamports": int(float(reward_sol) * 1_000_000_000),
        "buyer_address": buyer_address,
        "notes": notes,
        "status": "open",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    bounties = _load_bounties()
    bounties.append(bounty)
    _save_bounties(bounties)

    broadcast_event("mp_log", {"msg": f"Bounty posted: '{word}' for {reward_sol} SOL by {buyer_address[:12]}..."})
    return jsonify({"ok": True, "bounty": bounty})


@app.route("/api/bounties/<int:bounty_id>", methods=["DELETE"])
def api_bounties_delete(bounty_id):
    bounties = _load_bounties()
    bounties = [b for b in bounties if b.get("id") != bounty_id]
    _save_bounties(bounties)
    return jsonify({"ok": True})


@app.route("/api/bounties/<int:bounty_id>/fulfill", methods=["POST"])
def api_bounties_fulfill(bounty_id):
    data = request.json or {}
    vanity_address = data.get("vanity_address", "").strip()
    mint_address = data.get("mint_address", "").strip()

    bounties = _load_bounties()
    bounty = None
    for b in bounties:
        if b.get("id") == bounty_id:
            bounty = b
            break
    if not bounty:
        return jsonify({"error": "Bounty not found"}), 404
    if bounty.get("status") != "open":
        return jsonify({"error": "Bounty is no longer open"}), 400

    bounty["status"] = "fulfilled"
    bounty["vanity_address"] = vanity_address
    bounty["mint_address"] = mint_address
    bounty["fulfilled_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save_bounties(bounties)

    broadcast_event("mp_log", {"msg": f"Bounty fulfilled: '{bounty['word']}' -> {vanity_address[:20]}..."})
    return jsonify({"ok": True, "bounty": bounty})


if __name__ == "__main__":
    multiprocessing.freeze_support()
    temp_thread = threading.Thread(target=gpu_temp_monitor, daemon=True)
    temp_thread.start()
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
