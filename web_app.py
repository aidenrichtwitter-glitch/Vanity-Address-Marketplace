#!/usr/bin/env python3
import json
import logging
import multiprocessing
import os
import queue
import sys
import time
import threading
from pathlib import Path

_profile_path = Path("solvanity_profile.json")
if _profile_path.exists():
    try:
        import json as _json_init
        _profile_data = _json_init.loads(_profile_path.read_text(encoding="utf-8"))
        for _k in ("SOLANA_DEVNET_PRIVKEY", "LIT_PKP_PUBLIC_KEY", "LIT_GROUP_ID", "LIT_USAGE_API_KEY"):
            _v = _profile_data.get(_k, "").strip()
            if _v and _k not in os.environ:
                os.environ[_k] = _v
    except Exception:
        pass

from flask import Flask, render_template, request, jsonify, Response, send_file

from core.word_filter import WordFilter, PAD_CHAR, TAIL_SIZE
from core.word_miner import build_suffix_patterns
from core.config import DEFAULT_ITERATION_BITS
from core.utils.crypto import get_public_key_from_private_bytes, save_keypair
from core.utils.gpu_temp import get_gpu_temp, get_gpu_name, get_recommended_max_temp
from core import backend as shared

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", os.urandom(32).hex())

IS_PRODUCTION = bool(os.environ.get("REPLIT_DEPLOYMENT"))

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


def cpu_mining_worker(word_filter, output_dir, mining_mode, blind_wallet, stop_event, simple_suffix=None):
    try:
        import secrets
        import hashlib as _hl
        from nacl.signing import SigningKey
        from base58 import b58encode

        if simple_suffix:
            broadcast_event("log", {"msg": f"CPU mining mode — simple suffix match: ends with '{simple_suffix}'"})
        else:
            broadcast_event("log", {"msg": "CPU mining mode — no GPU required"})
        broadcast_event("status", {"msg": "Mining (CPU)..."})

        Path(output_dir).mkdir(parents=True, exist_ok=True)

        result_count = 0
        start_time = time.time()
        keys_checked = 0
        last_speed_report = time.time()

        while not stop_event.is_set():
            if mining_state.get("count_limit", 0) > 0 and result_count >= mining_state["count_limit"]:
                break

            seed = secrets.token_bytes(32)

            sk = SigningKey(seed)
            pk_bytes = bytes(sk.verify_key)
            pubkey = b58encode(pk_bytes).decode()

            keys_checked += 1

            if simple_suffix:
                if pubkey.endswith(simple_suffix):
                    word = simple_suffix
                    padding = ""
                else:
                    word = None
                    padding = None
            else:
                word, padding = word_filter.check_address(pubkey)

            if word:
                pv_bytes = seed
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

            now = time.time()
            if now - last_speed_report >= 2.0:
                elapsed = now - start_time
                speed = keys_checked / elapsed if elapsed > 0 else 0
                with mining_lock:
                    mining_state["speed"] = speed
                    mining_state["total_keys"] = keys_checked
                broadcast_event("speed", {
                    "value": speed,
                    "total_keys": keys_checked,
                    "suffix_pattern_count": mining_state["suffix_pattern_count"],
                })
                last_speed_report = now

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


def gpu_mining_worker(word_filter, suffix_patterns, output_dir, iteration_bits,
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
            worker_kwargs = {
                "suffix_buffer": suffix_buffer,
                "suffix_count": suffix_count,
                "suffix_width": suffix_width,
                "suffix_lengths": suffix_lengths,
            }
            proc = mp_ctx.Process(
                target=_persistent_worker,
                args=(idx, kernel_source, iteration_bits, gpu_counts, None, c_conn,
                      power_pct, max_temp),
                kwargs=worker_kwargs,
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
                        pv_bytes = bytes(output[1:33])
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

    def _log(msg):
        broadcast_event("log", {"msg": f"[Blind] {msg}"})

    def _mp(msg):
        broadcast_event("mp_log", {"msg": msg})

    def _on_error(err, addr):
        broadcast_event("error", {"msg": f"Blind upload failed: {str(err)[:80]}"})

    def _on_success(result, addr):
        mint_address = result.get("mint_address", "")
        if vanity_word and mint_address:
            bounties = shared.load_bounties()
            for b in bounties:
                if b.get("status") in ("open", "claimed") and b.get("word", "").lower() == vanity_word.lower():
                    shared.fulfill_bounty(b["id"], addr, mint_address)
                    broadcast_event("mp_log", {"msg": f"Auto-fulfilled bounty '{b['word']}' -> {addr[:20]}..."})
                    break

    shared.blind_upload(
        pv_bytes, pubkey, wallet, vanity_word=vanity_word,
        price_sol=price_sol, log_fn=_log, mp_fn=_mp,
        on_error=_on_error, on_success=_on_success,
    )


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
    if IS_PRODUCTION:
        return jsonify({"error": "Mining is disabled on the hosted version."}), 403
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
    return render_template("index.html", show_miner=not IS_PRODUCTION)


@app.route("/api/escrow-pubkeys")
def api_escrow_pubkeys():
    try:
        from core.marketplace.lit_encrypt import get_escrow_pubkeys
        escrows = get_escrow_pubkeys()
        return jsonify({"escrows": escrows})
    except Exception as e:
        return jsonify({"error": str(e), "escrows": []}), 500


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
    if IS_PRODUCTION:
        return jsonify({"error": "Mining is disabled on the hosted version."}), 403
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
    if IS_PRODUCTION:
        return jsonify({"error": "Mining is disabled on the hosted version. Download the source to mine locally."}), 403
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
    compute_mode = data.get("compute_mode", "cpu")
    simple_suffix = data.get("simple_suffix", "")

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
    if compute_mode == "gpu":
        broadcast_event("log", {"msg": f"Compute: GPU  |  Power: {power_pct}%  |  Max Temp: {max_temp}°C"})
    else:
        broadcast_event("log", {"msg": f"Compute: CPU (pure Python)"})

    _stop_event = threading.Event()

    count_limit = 0
    if mining_mode == "blind":
        count_limit = len(word_filter.words)
        broadcast_event("log", {"msg": f"[Blind] Will stop after finding {count_limit} addresses (one per word)"})
        broadcast_event("log", {"msg": "[Blind] Keys will be encrypted by TEE and uploaded as NFTs (Phantom-importable)"})

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
        mining_state["compute_mode"] = compute_mode

    broadcast_event("status", {"msg": "Starting..."})

    if compute_mode == "gpu":
        t = threading.Thread(
            target=gpu_mining_worker,
            args=(word_filter, suffix_patterns, output_dir, DEFAULT_ITERATION_BITS,
                  power_pct, max_temp, mining_mode, blind_wallet, _stop_event),
            daemon=True,
        )
    else:
        t = threading.Thread(
            target=cpu_mining_worker,
            args=(word_filter, output_dir, mining_mode, blind_wallet, _stop_event),
            kwargs={"simple_suffix": simple_suffix} if simple_suffix else {},
            daemon=True,
        )

    with mining_lock:
        mining_state["thread"] = t
    t.start()

    return jsonify({"ok": True, "words": len(word_filter.words), "patterns": len(suffix_patterns)})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    if IS_PRODUCTION:
        return jsonify({"error": "Mining is disabled on the hosted version."}), 403
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


@app.route("/api/marketplace/search", methods=["POST"])
def api_marketplace_search():
    data = request.json or {}
    search_filter = data.get("filter", "").strip().lower()
    try:
        packages = shared.search_packages(search_filter)
        return jsonify({"packages": packages, "total": len(packages)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/marketplace/owned", methods=["POST"])
def api_marketplace_owned():
    data = request.json or {}
    buyer_key = data.get("buyer_key", "").strip()
    result, err = shared.get_owned_nfts(buyer_key)
    if err:
        return jsonify({"error": err}), 400
    return jsonify(result)


@app.route("/api/marketplace/buy", methods=["POST"])
def api_marketplace_buy():
    buy_log = logging.getLogger("marketplace.buy")
    data = request.json or {}
    buyer_key = data.get("buyer_key", "").strip()
    encrypted_json = data.get("encrypted_json")
    mint_address = data.get("mint_address", "")
    vanity_address = data.get("vanity_address", "")

    result, err = shared.buy_nft(
        buyer_key, encrypted_json, mint_address, vanity_address,
        log_fn=lambda msg: buy_log.info(msg),
    )
    if err:
        return jsonify({"error": err}), 400
    return jsonify(result)


@app.route("/api/marketplace/burn", methods=["POST"])
def api_marketplace_burn():
    burn_log = logging.getLogger("marketplace.burn")
    data = request.json or {}
    buyer_key = data.get("buyer_key", "").strip()
    encrypted_json = data.get("encrypted_json")
    mint_address = data.get("mint_address", "")
    vanity_address = data.get("vanity_address", "")

    result, err = shared.burn_and_decrypt(
        buyer_key, encrypted_json, mint_address, vanity_address,
        log_fn=lambda msg: burn_log.info(msg),
        skip_file_save=True,
    )
    if err:
        return jsonify({"error": err}), 400
    return jsonify(result)


@app.route("/api/marketplace/relist", methods=["POST"])
def api_marketplace_relist():
    relist_log = logging.getLogger("marketplace.relist")
    data = request.json or {}
    owner_key = data.get("owner_key", "").strip()
    mint_address = data.get("mint_address", "")
    vanity_address = data.get("vanity_address", "")
    new_price_sol = data.get("new_price_sol", 0)

    result, err = shared.relist_nft(
        owner_key, mint_address, vanity_address, new_price_sol,
        log_fn=lambda msg: relist_log.info(msg),
    )
    if err:
        return jsonify({"error": err}), 400
    return jsonify(result)


@app.route("/api/bounties", methods=["GET"])
def api_bounties_list():
    bounties = shared.load_bounties()
    return jsonify({"bounties": bounties})


@app.route("/api/bounties", methods=["POST"])
def api_bounties_create():
    data = request.json or {}
    word = data.get("word", "").strip()
    reward_sol = data.get("reward_sol", 0)
    buyer_address = data.get("buyer_address", "").strip()
    notes = data.get("notes", "").strip()
    pattern_type = data.get("pattern_type", "ends_with").strip()
    case_insensitive = data.get("case_insensitive", True)
    description = data.get("description", "").strip()
    bounty, err = shared.create_bounty(
        word, reward_sol, buyer_address, notes,
        pattern_type=pattern_type,
        case_insensitive=case_insensitive,
        description=description,
    )
    if err:
        return jsonify({"error": err}), 400

    broadcast_event("mp_log", {"msg": f"Bounty posted: '{bounty['word']}' ({bounty.get('pattern_type','ends_with')}) for {bounty['reward_sol']} SOL"})
    return jsonify({"ok": True, "bounty": bounty})


@app.route("/api/bounties/<int:bounty_id>", methods=["DELETE"])
def api_bounties_delete(bounty_id):
    shared.delete_bounty(bounty_id)
    return jsonify({"ok": True})


@app.route("/api/bounties/<int:bounty_id>/fulfill", methods=["POST"])
def api_bounties_fulfill(bounty_id):
    data = request.json or {}
    vanity_address = data.get("vanity_address", "").strip()
    mint_address = data.get("mint_address", "").strip()

    bounty, err = shared.fulfill_bounty(bounty_id, vanity_address, mint_address)
    if err:
        code = 404 if "not found" in err else 400
        return jsonify({"error": err}), code

    broadcast_event("mp_log", {"msg": f"Bounty fulfilled: '{bounty['word']}' -> {vanity_address[:20]}..."})
    return jsonify({"ok": True, "bounty": bounty})


@app.route("/api/bounty-wordlist", methods=["GET"])
def api_bounty_wordlist():
    wordlist = shared.get_bounty_wordlist()
    return jsonify({"wordlist": wordlist})


_PROFILE_PATH = Path("solvanity_profile.json")


def _load_web_profile():
    if _PROFILE_PATH.exists():
        try:
            return json.loads(_PROFILE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_web_profile(data: dict):
    _PROFILE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _mask_key(key: str) -> str:
    if not key or len(key) < 8:
        return ""
    return key[:4] + "****" + key[-4:]


@app.route("/api/settings/load")
def api_settings_load():
    usage_raw = os.environ.get("LIT_USAGE_API_KEY", "")
    seller_raw = os.environ.get("SOLANA_DEVNET_PRIVKEY", "")
    return jsonify({
        "usage_key_masked": _mask_key(usage_raw),
        "usage_key_present": bool(usage_raw),
        "seller_key_masked": _mask_key(seller_raw),
        "seller_key_present": bool(seller_raw),
    })


@app.route("/api/settings/save", methods=["POST"])
def api_settings_save():
    data = request.json or {}
    seller_key = data.get("seller_key", "").strip()
    persist = data.get("persist", False)

    if seller_key:
        os.environ["SOLANA_DEVNET_PRIVKEY"] = seller_key

    if persist:
        profile = {}
        if seller_key:
            profile["SOLANA_DEVNET_PRIVKEY"] = seller_key
        for env_key in ("LIT_PKP_PUBLIC_KEY", "LIT_GROUP_ID", "LIT_USAGE_API_KEY"):
            val = os.environ.get(env_key, "").strip()
            if val:
                profile[env_key] = val
        try:
            _save_web_profile(profile)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    return jsonify({"ok": True})


@app.route("/api/settings/create-lit-key", methods=["POST"])
def api_create_lit_key():
    try:
        from core.marketplace.lit_encrypt import (
            _get_api_key, _get_pkp_public_key,
            register_ipfs_actions, create_user_scoped_key,
        )

        api_key = _get_api_key()
        pkp_public_key = _get_pkp_public_key()
        setup_steps = ["pkp"]

        if not os.environ.get("LIT_GROUP_ID", "").strip():
            try:
                register_ipfs_actions()
                setup_steps.append("group")
            except Exception:
                pass

        scoped_key = create_user_scoped_key()
        os.environ["LIT_USAGE_API_KEY"] = scoped_key
        setup_steps.append("usage_key")

        profile = _load_web_profile()
        profile["LIT_PKP_PUBLIC_KEY"] = pkp_public_key
        group_id = os.environ.get("LIT_GROUP_ID", "").strip()
        if group_id:
            profile["LIT_GROUP_ID"] = group_id
        profile["LIT_USAGE_API_KEY"] = scoped_key
        _save_web_profile(profile)

        return jsonify({
            "ok": True,
            "usage_key_masked": _mask_key(scoped_key),
            "has_scoped_key": True,
            "setup_steps": setup_steps,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/settings/clear", methods=["POST"])
def api_settings_clear():
    if _PROFILE_PATH.exists():
        _PROFILE_PATH.unlink()
    return jsonify({"ok": True})


@app.route("/download/source")
def download_source():
    import zipfile
    import io
    import fnmatch

    buf = io.BytesIO()
    root = Path(".")
    include_patterns = [
        "gui.py", "web_app.py", "main.py", "build.py",
        "pyi_rth_pyside6_plugins.py", "wordlist_3000.txt",
        "export_source.py",
    ]
    include_dirs = ["core", "templates", "static", "wordlists"]
    exclude_dirs = {"__pycache__", ".git", ".pythonlibs", "anchor_program",
                    ".cache", ".upm", ".local", ".config", "attached_assets",
                    "decrypted_keys", "found_words", "uploaded_wordlists",
                    "dist", "build"}

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in include_patterns:
            p = root / name
            if p.is_file():
                zf.write(p, name)

        for d in include_dirs:
            dp = root / d
            if not dp.is_dir():
                continue
            for fp in dp.rglob("*"):
                if fp.is_file() and not any(part in exclude_dirs for part in fp.parts):
                    zf.write(fp, str(fp))

    buf.seek(0)
    return send_file(buf, mimetype="application/zip",
                     as_attachment=True, download_name="solvanity_source.zip")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    temp_thread = threading.Thread(target=gpu_temp_monitor, daemon=True)
    temp_thread.start()
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
