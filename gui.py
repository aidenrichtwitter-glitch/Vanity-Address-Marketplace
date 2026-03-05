#!/usr/bin/env python3
import multiprocessing
import os
import sys
import time
import threading
from pathlib import Path

import json as _json

def _get_app_dir():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))

def _get_profile_path():
    return _get_app_dir() / "solvanity_profile.json"

def _load_dotenv():
    env_path = _get_app_dir() / ".env"
    if not env_path.exists():
        env_path = Path(__file__).resolve().parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val

def _load_profile():
    p = _get_profile_path()
    if p.exists():
        try:
            data = _json.loads(p.read_text(encoding="utf-8"))
            for key in ("SOLANA_DEVNET_PRIVKEY", "LIT_PKP_PUBLIC_KEY", "LIT_GROUP_ID", "LIT_USAGE_API_KEY"):
                val = data.get(key, "").strip()
                if val and key not in os.environ:
                    os.environ[key] = val
            return data
        except Exception:
            pass
    return {}

def _save_profile(data: dict):
    p = _get_profile_path()
    p.write_text(_json.dumps(data, indent=2), encoding="utf-8")

_load_dotenv()
_load_profile()

os.environ.setdefault("PYOPENCL_CTX", "0:0")
if sys.platform != "win32":
    os.environ.setdefault("DISPLAY", ":0")
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
    os.environ.setdefault("QT_QUICK_BACKEND", "software")
    os.environ.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")
    os.environ.setdefault("XDG_RUNTIME_DIR", "/tmp/runtime-runner")

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSpinBox, QDoubleSpinBox, QLineEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QGroupBox, QTextEdit,
    QFileDialog, QSplitter, QSlider, QFrame, QTabWidget, QCheckBox,
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QFont, QColor

from core.word_filter import WordFilter, PAD_CHAR, TAIL_SIZE
from core.word_miner import build_suffix_patterns
from core.config import DEFAULT_ITERATION_BITS
from core.utils.crypto import get_public_key_from_private_bytes, save_keypair
from core.utils.gpu_temp import get_gpu_temp, get_gpu_name, get_recommended_max_temp

STYLESHEET = """
QMainWindow, QWidget {
    background-color: #1b1b2f;
    color: #e0e0e0;
    font-family: "Segoe UI", "DejaVu Sans", sans-serif;
}
QGroupBox {
    background-color: #222244;
    border: 1px solid #3a3a5c;
    border-radius: 6px;
    margin-top: 14px;
    padding: 14px 10px 10px 10px;
    font-weight: bold;
    color: #a0a0cc;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 2px 10px;
    color: #b0b0dd;
}
QLabel {
    color: #c8c8e0;
    background: transparent;
}
QSpinBox {
    background-color: #2a2a4a;
    border: 1px solid #4a4a6e;
    border-radius: 4px;
    padding: 5px 8px;
    color: #e0e0ff;
    min-width: 70px;
    min-height: 22px;
}
QSpinBox:focus {
    border-color: #6090ff;
}
QSpinBox::up-button, QSpinBox::down-button {
    background-color: #3a3a5c;
    border: none;
    width: 18px;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {
    background-color: #5050aa;
}
QLineEdit {
    background-color: #2a2a4a;
    border: 1px solid #4a4a6e;
    border-radius: 4px;
    padding: 5px 8px;
    color: #e0e0ff;
    min-height: 22px;
}
QLineEdit:focus {
    border-color: #6090ff;
}
QPushButton#startBtn {
    background-color: #2d8f4e;
    border: none;
    border-radius: 5px;
    color: #ffffff;
    padding: 8px 28px;
    font-size: 13px;
    font-weight: bold;
    min-height: 32px;
}
QPushButton#startBtn:hover {
    background-color: #36a85c;
}
QPushButton#startBtn:pressed {
    background-color: #257a42;
}
QPushButton#stopBtn {
    background-color: #c03030;
    border: none;
    border-radius: 5px;
    color: #ffffff;
    padding: 8px 28px;
    font-size: 13px;
    font-weight: bold;
    min-height: 32px;
}
QPushButton#stopBtn:hover {
    background-color: #dd3a3a;
}
QPushButton#stopBtn:pressed {
    background-color: #a02828;
}
QPushButton#browseBtn {
    background-color: #3a3a5c;
    border: 1px solid #4a4a6e;
    border-radius: 4px;
    color: #c8c8e0;
    min-height: 22px;
}
QPushButton#browseBtn:hover {
    background-color: #5050aa;
}
QTableWidget {
    background-color: #1e1e38;
    border: 1px solid #3a3a5c;
    gridline-color: #2e2e4e;
    color: #d0d0e8;
    selection-background-color: #3a4a7a;
    alternate-background-color: #242448;
}
QHeaderView::section {
    background-color: #2a2a50;
    border: 1px solid #3a3a5c;
    padding: 6px;
    color: #b0b0dd;
    font-weight: bold;
}
QTextEdit {
    background-color: #141428;
    border: 1px solid #3a3a5c;
    color: #a0a0c0;
    font-family: "Consolas", "DejaVu Sans Mono", monospace;
    font-size: 10px;
}
QSplitter::handle {
    background-color: #3a3a5c;
    height: 3px;
}
QScrollBar:vertical {
    background: #1e1e38;
    width: 10px;
    border: none;
}
QScrollBar::handle:vertical {
    background: #4a4a6e;
    border-radius: 5px;
    min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
"""


class MiningSignals(QObject):
    found = Signal(str, str, str, int)
    found_with_key = Signal(str, bytes, str)
    log = Signal(str)
    status = Signal(str)
    speed = Signal(float)
    error = Signal(str)
    stopped = Signal()
    gpu_detected = Signal(str, int)


class ThreadBridgeSignals(QObject):
    log_signal = Signal(str)
    mp_log_signal = Signal(str)
    burn_status_signal = Signal(str)
    burn_success_signal = Signal(str, str, str)
    burn_error_signal = Signal(str)
    buy_success_signal = Signal(dict)
    buy_error_signal = Signal(str)
    upload_success_signal = Signal(dict, str)
    upload_error_signal = Signal(str, str)
    populate_packages_signal = Signal(list, str)
    browse_error_signal = Signal(str)
    owned_nfts_signal = Signal(dict)
    owned_error_signal = Signal(str)
    relist_success_signal = Signal(str)
    relist_error_signal = Signal(str)


class MiningThread(threading.Thread):
    def __init__(self, signals, word_filter, suffix_patterns, output_dir,
                 count, iteration_bits, power_pct=100, max_temp=80,
                 mining_mode="mine", tee_point=None):
        super().__init__(daemon=True)
        self.signals = signals
        self.word_filter = word_filter
        self.suffix_patterns = suffix_patterns
        self.output_dir = output_dir
        self.count = count
        self.iteration_bits = iteration_bits
        self.power_pct = power_pct
        self.max_temp = max_temp
        self.mining_mode = mining_mode
        self.tee_point = tee_point
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        try:
            from core.utils.helpers import build_suffix_buffer, load_kernel_source
            from core.opencl.manager import get_all_gpu_devices

            try:
                gpu_counts = len(get_all_gpu_devices())
            except Exception as e:
                self.signals.error.emit(
                    f"OpenCL error: {e}\n\n"
                    "No GPU found. This tool requires an OpenCL-capable GPU.\n"
                    "Install GPU drivers and OpenCL runtime, then try again."
                )
                self.signals.stopped.emit()
                return

            if gpu_counts == 0:
                self.signals.error.emit(
                    "No GPU devices found.\n"
                    "Make sure GPU drivers and OpenCL runtime are installed."
                )
                self.signals.stopped.emit()
                return

            self.signals.log.emit(f"Found {gpu_counts} GPU device(s)")
            self.signals.status.emit("Compiling kernel...")

            suffix_tuple = tuple(self.suffix_patterns)
            suffix_buffer, suffix_count, suffix_width, suffix_lengths = build_suffix_buffer(suffix_tuple)
            kernel_source = load_kernel_source((), True, suffix_bytes=len(suffix_buffer) if suffix_count > 0 else 0)

            mem_type = "local" if (suffix_count * suffix_width) <= 46080 else "global"
            self.signals.log.emit(f"Kernel compiled with {len(self.suffix_patterns)} patterns ({suffix_count * suffix_width} bytes in {mem_type} memory)")
            self.signals.status.emit("Mining...")

            Path(self.output_dir).mkdir(parents=True, exist_ok=True)

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
                if self.tee_point:
                    worker_kwargs["tee_point"] = self.tee_point
                proc = mp_ctx.Process(
                    target=_persistent_worker,
                    args=(idx, kernel_source, self.iteration_bits, gpu_counts, None, c_conn,
                          self.power_pct, self.max_temp),
                    kwargs=worker_kwargs,
                    daemon=True,
                )
                proc.start()
                workers.append((proc, p_conn))

            ready_count = 0
            for i, (proc, conn) in enumerate(workers):
                try:
                    if conn.poll(30):
                        msg = conn.recv()
                        if isinstance(msg, dict) and msg.get("type") == "ready":
                            ready_count += 1
                        elif isinstance(msg, dict) and msg.get("type") == "error":
                            self.signals.log.emit(f"[GPU ERROR] GPU {i}: {msg.get('msg', 'Worker failed to start')}")
                    else:
                        alive = proc.is_alive()
                        self.signals.log.emit(f"[GPU ERROR] GPU {i}: timed out waiting for worker (alive={alive})")
                except Exception as e:
                    self.signals.log.emit(f"[GPU ERROR] GPU {i} connection failed: {e}")

            if ready_count == 0:
                self.signals.error.emit("No GPU workers started — kernel build failed. Check log for details.")
                self.signals.stopped.emit()
                return

            self.signals.log.emit(f"Workers running ({ready_count}/{gpu_counts} GPU process(es)), mining continuously...")

            while not self._stop_event.is_set():
                if 0 < self.count <= result_count:
                    break

                for _, conn in workers:
                    while conn.poll(0):
                        msg = conn.recv()
                        if not isinstance(msg, dict):
                            continue
                        if msg["type"] == "found":
                            output = msg["data"]
                            pv_bytes = bytes(output[1:33])
                            gpu_pubkey_bytes = bytes(output[33:65])
                            if self.tee_point and any(b != 0 for b in gpu_pubkey_bytes):
                                from base58 import b58encode
                                pubkey = b58encode(gpu_pubkey_bytes).decode()
                            elif self.tee_point:
                                import hashlib
                                from base58 import b58encode
                                from nacl.bindings import (
                                    crypto_scalarmult_ed25519_base_noclamp,
                                    crypto_core_ed25519_add,
                                )
                                h = hashlib.sha512(pv_bytes).digest()
                                scalar = bytearray(h[:32])
                                scalar[0] &= 248
                                scalar[31] &= 63
                                scalar[31] |= 64
                                miner_point = crypto_scalarmult_ed25519_base_noclamp(bytes(scalar))
                                combined_point = crypto_core_ed25519_add(miner_point, self.tee_point)
                                pubkey = b58encode(combined_point).decode()
                            else:
                                pubkey = get_public_key_from_private_bytes(pv_bytes)
                            word, padding = self.word_filter.check_address(pubkey)
                            suffix_display = (padding + word) if word else pubkey[-TAIL_SIZE:]
                            if self.mining_mode != "blind":
                                save_keypair(pv_bytes, self.output_dir, word=word, pubkey=pubkey)
                            result_count += 1
                            elapsed = time.time() - start_time
                            self.signals.found.emit(
                                pubkey, suffix_display, f"{elapsed:.1f}s", result_count,
                            )
                            self.signals.found_with_key.emit(pubkey, pv_bytes, suffix_display)
                            self.signals.log.emit(
                                f"[FOUND] #{result_count}: {pubkey} -> {suffix_display}"
                            )
                        elif msg["type"] == "speed":
                            speed = msg["value"]
                            self.signals.speed.emit(speed)
                        elif msg["type"] == "temp":
                            pass
                        elif msg["type"] == "log":
                            self.signals.log.emit(msg["msg"])
                        elif msg["type"] == "error":
                            self.signals.log.emit(f"[GPU ERROR] {msg['msg']}")

                time.sleep(0.2)

            for _, conn in workers:
                try:
                    conn.send("stop")
                except Exception:
                    pass
            for proc, _ in workers:
                proc.join(timeout=3)

            self.signals.status.emit(f"Complete - {result_count} found")

        except Exception as e:
            self.signals.error.emit(str(e))

        self.signals.stopped.emit()


class CpuMiningThread(threading.Thread):
    def __init__(self, signals, word_filter, output_dir, count=0, mining_mode="mine",
                 tee_point=None):
        super().__init__(daemon=True)
        self.signals = signals
        self.word_filter = word_filter
        self.output_dir = output_dir
        self.count = count
        self.mining_mode = mining_mode
        self.tee_point = tee_point
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        try:
            import secrets
            import hashlib as _hl
            from nacl.signing import SigningKey
            from base58 import b58encode

            use_split_key = self.tee_point is not None and len(self.tee_point) == 32 and any(b != 0 for b in self.tee_point)

            if use_split_key:
                from nacl.bindings import (
                    crypto_scalarmult_ed25519_base_noclamp,
                    crypto_core_ed25519_add,
                )
                self.signals.log.emit("CPU mining mode (split-key) — no GPU required")
            else:
                self.signals.log.emit("CPU mining mode — no GPU required")
            self.signals.status.emit("Mining (CPU)...")

            Path(self.output_dir).mkdir(parents=True, exist_ok=True)

            result_count = 0
            start_time = time.time()
            keys_checked = 0
            last_speed_report = time.time()

            while not self._stop_event.is_set():
                if 0 < self.count <= result_count:
                    break

                seed = secrets.token_bytes(32)

                if use_split_key:
                    h = _hl.sha512(seed).digest()
                    scalar = bytearray(h[:32])
                    scalar[0] &= 248
                    scalar[31] &= 63
                    scalar[31] |= 64
                    miner_point = crypto_scalarmult_ed25519_base_noclamp(bytes(scalar))
                    combined_point = crypto_core_ed25519_add(miner_point, self.tee_point)
                    pubkey = b58encode(combined_point).decode()
                else:
                    sk = SigningKey(seed)
                    pk_bytes = bytes(sk.verify_key)
                    pubkey = b58encode(pk_bytes).decode()

                keys_checked += 1

                word, padding = self.word_filter.check_address(pubkey)

                if word:
                    pv_bytes = seed
                    suffix_display = (padding + word) if padding else word
                    if self.mining_mode != "blind":
                        save_keypair(pv_bytes, self.output_dir, word=word, pubkey=pubkey)
                    result_count += 1
                    elapsed = time.time() - start_time
                    self.signals.found.emit(pubkey, suffix_display, f"{elapsed:.1f}s", result_count)
                    self.signals.found_with_key.emit(pubkey, pv_bytes, suffix_display)
                    self.signals.log.emit(f"[FOUND] #{result_count}: {pubkey} -> {suffix_display}")

                now = time.time()
                if now - last_speed_report >= 2.0:
                    elapsed_since = now - last_speed_report
                    speed = keys_checked / elapsed_since if elapsed_since > 0 else 0
                    self.signals.speed.emit(speed)
                    keys_checked = 0
                    last_speed_report = now

            self.signals.status.emit(f"Complete - {result_count} found")

        except Exception as e:
            self.signals.error.emit(str(e))

        self.signals.stopped.emit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SolVanity Word Miner")
        self.setMinimumSize(880, 620)
        self.resize(920, 680)
        self.mining_thread = None
        self._thread_bridge = ThreadBridgeSignals()
        self._thread_bridge.log_signal.connect(self._on_log)
        self._thread_bridge.mp_log_signal.connect(self._mp_log)
        self._thread_bridge.burn_status_signal.connect(self._on_burn_status)
        self._thread_bridge.burn_success_signal.connect(self._on_burn_success)
        self._thread_bridge.burn_error_signal.connect(self._on_burn_error)
        self._thread_bridge.upload_success_signal.connect(self._on_upload_success)
        self._thread_bridge.upload_error_signal.connect(self._on_upload_error)
        self._thread_bridge.populate_packages_signal.connect(self._populate_packages)
        self._thread_bridge.browse_error_signal.connect(self._on_browse_error)
        self._thread_bridge.buy_success_signal.connect(self._on_buy_success)
        self._thread_bridge.buy_error_signal.connect(self._on_buy_error)
        self._thread_bridge.owned_nfts_signal.connect(self._on_owned_nfts)
        self._thread_bridge.owned_error_signal.connect(self._on_owned_error)
        self._thread_bridge.relist_success_signal.connect(self._on_relist_success)
        self._thread_bridge.relist_error_signal.connect(self._on_relist_error)
        self._build_ui()
        self._load_word_count()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(10)
        root.setContentsMargins(14, 14, 14, 14)

        header = QLabel("SolVanity Word Miner")
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet(
            "font-size: 22px; font-weight: bold; color: #6ea8fe; "
            "padding: 6px 0 2px 0; background: transparent;"
        )
        root.addWidget(header)

        sub = QLabel("GPU-Accelerated Solana Vanity Address Mining  |  Blind Key Marketplace")
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet("font-size: 11px; color: #7878a0; padding-bottom: 4px; background: transparent;")
        root.addWidget(sub)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #3a3a5c;
                border-radius: 4px;
                background-color: #1b1b2f;
            }
            QTabBar::tab {
                background-color: #222244;
                border: 1px solid #3a3a5c;
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                padding: 8px 20px;
                color: #8888aa;
                font-weight: bold;
                min-width: 120px;
            }
            QTabBar::tab:selected {
                background-color: #1b1b2f;
                color: #6ea8fe;
                border-bottom: 2px solid #6ea8fe;
            }
            QTabBar::tab:hover:!selected {
                background-color: #2a2a55;
                color: #b0b0dd;
            }
        """)

        mining_tab = self._build_mining_tab()
        self.tabs.addTab(mining_tab, "Word Miner")

        marketplace_tab = self._build_marketplace_tab()
        self.tabs.addTab(marketplace_tab, "Marketplace")

        settings_tab = self._build_settings_tab()
        self.tabs.addTab(settings_tab, "Settings")

        root.addWidget(self.tabs)

        self.signals = MiningSignals()
        self.signals.found.connect(self._on_found)
        self.signals.found_with_key.connect(self._on_found_with_key)
        self.signals.log.connect(self._on_log)
        self.signals.status.connect(self._on_status)
        self.signals.speed.connect(self._on_speed)
        self.signals.error.connect(self._on_error)
        self.signals.stopped.connect(self._on_stopped)
        self.signals.gpu_detected.connect(self._on_gpu_detected)

        self.start_time = None
        self.timer = QTimer()
        self.timer.timeout.connect(self._update_elapsed)

        self._total_keys = 0
        self._last_speed_raw = 0.0
        self._suffix_pattern_count = 0

        self._word_count_timer = QTimer()
        self._word_count_timer.setSingleShot(True)
        self._word_count_timer.timeout.connect(self._do_load_word_count)

        self._last_temp_value = None
        self._last_temp_zone = None
        self._temp_lock = threading.Lock()
        self._gpu_detected = False

        self._temp_thread = threading.Thread(target=self._temp_poll_loop, daemon=True)
        self._temp_thread.start()

        self.temp_timer = QTimer()
        self.temp_timer.timeout.connect(self._apply_temp_display)
        self.temp_timer.start(2000)

        self._mining_mode = "mine"

    def _build_mining_tab(self):
        from PySide6.QtWidgets import QScrollArea
        inner = QWidget()
        root = QVBoxLayout(inner)
        root.setSpacing(10)
        root.setContentsMargins(10, 10, 10, 10)

        self.settings_toggle = QPushButton("▼  Mining Settings")
        self.settings_toggle.setStyleSheet("""
            QPushButton {
                background-color: #222244;
                border: 1px solid #3a3a5c;
                border-radius: 6px;
                color: #b0b0dd;
                font-weight: bold;
                font-size: 12px;
                text-align: left;
                padding: 8px 14px;
            }
            QPushButton:hover {
                background-color: #2a2a55;
                border-color: #5050aa;
            }
        """)
        self.settings_toggle.setCursor(Qt.PointingHandCursor)
        self.settings_toggle.clicked.connect(self._toggle_settings)
        root.addWidget(self.settings_toggle)

        self.settings_content = QWidget()
        self.settings_content.setStyleSheet("""
            QWidget#settingsContent {
                background-color: #222244;
                border: 1px solid #3a3a5c;
                border-top: none;
                border-radius: 0 0 6px 6px;
                padding: 10px;
            }
        """)
        self.settings_content.setObjectName("settingsContent")
        sg = QVBoxLayout(self.settings_content)
        sg.setSpacing(10)
        sg.setContentsMargins(10, 10, 10, 10)

        row1 = QHBoxLayout()
        row1.setSpacing(20)

        def add_field(parent_layout, label_text, widget):
            col = QVBoxLayout()
            col.setSpacing(4)
            lbl = QLabel(label_text)
            lbl.setStyleSheet("font-size: 11px; color: #9898b8; background: transparent;")
            col.addWidget(lbl)
            col.addWidget(widget)
            parent_layout.addLayout(col)
            return col

        self.min_word_spin = QSpinBox()
        self.min_word_spin.setRange(1, 20)
        self.min_word_spin.setValue(4)
        self.min_word_spin.valueChanged.connect(self._load_word_count)
        add_field(row1, "Min Word Length", self.min_word_spin)

        dir_col = QVBoxLayout()
        dir_col.setSpacing(4)
        dir_lbl = QLabel("Output Directory")
        dir_lbl.setStyleSheet("font-size: 11px; color: #9898b8; background: transparent;")
        dir_col.addWidget(dir_lbl)
        dir_row = QHBoxLayout()
        dir_row.setSpacing(4)
        self.output_dir_edit = QLineEdit("./found_words")
        dir_row.addWidget(self.output_dir_edit)
        browse_dir_btn = QPushButton("Browse")
        browse_dir_btn.setObjectName("browseBtn")
        browse_dir_btn.setFixedWidth(70)
        browse_dir_btn.clicked.connect(self._browse_dir)
        dir_row.addWidget(browse_dir_btn)
        dir_col.addLayout(dir_row)
        row1.addLayout(dir_col)

        sg.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(20)

        wl_col = QVBoxLayout()
        wl_col.setSpacing(4)
        wl_lbl = QLabel("Word List (optional - uses built-in list if empty)")
        wl_lbl.setStyleSheet("font-size: 11px; color: #9898b8; background: transparent;")
        wl_col.addWidget(wl_lbl)
        wl_row = QHBoxLayout()
        wl_row.setSpacing(4)
        self.wordlist_edit = QLineEdit("")
        self.wordlist_edit.setPlaceholderText("Type words (e.g. dragon, gold) or Browse for a .txt file")
        self.wordlist_edit.textChanged.connect(self._load_word_count)
        wl_row.addWidget(self.wordlist_edit)
        browse_wl_btn = QPushButton("Browse")
        browse_wl_btn.setObjectName("browseBtn")
        browse_wl_btn.setFixedWidth(70)
        browse_wl_btn.clicked.connect(self._browse_wordlist)
        wl_row.addWidget(browse_wl_btn)
        clear_wl_btn = QPushButton("Clear")
        clear_wl_btn.setObjectName("browseBtn")
        clear_wl_btn.setFixedWidth(50)
        clear_wl_btn.clicked.connect(lambda: (self.wordlist_edit.clear(), self._load_word_count()))
        wl_row.addWidget(clear_wl_btn)
        wl_col.addLayout(wl_row)
        row2.addLayout(wl_col)

        sg.addLayout(row2)

        row3 = QHBoxLayout()
        row3.setSpacing(20)

        compute_col = QVBoxLayout()
        compute_col.setSpacing(4)
        compute_lbl = QLabel("Compute")
        compute_lbl.setStyleSheet("font-size: 11px; color: #9898b8; background: transparent;")
        compute_col.addWidget(compute_lbl)
        compute_row = QHBoxLayout()
        compute_row.setSpacing(4)
        self._compute_mode = "cpu"
        self.cpu_mode_btn = QPushButton("CPU")
        self.cpu_mode_btn.setCheckable(True)
        self.cpu_mode_btn.setChecked(True)
        self.cpu_mode_btn.setFixedWidth(60)
        self.cpu_mode_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a6e2a; border: 2px solid #50e050;
                border-radius: 4px; color: #e0ffe0; font-weight: bold;
                font-size: 12px; padding: 4px 12px;
            }
            QPushButton:!checked {
                background-color: #2a2a4a; border: 1px solid #4a4a6e;
                color: #8888aa;
            }
            QPushButton:!checked:hover { background-color: #333360; }
        """)
        self.cpu_mode_btn.clicked.connect(lambda: self._set_compute_mode("cpu"))
        compute_row.addWidget(self.cpu_mode_btn)
        self.gpu_mode_btn = QPushButton("GPU")
        self.gpu_mode_btn.setCheckable(True)
        self.gpu_mode_btn.setChecked(False)
        self.gpu_mode_btn.setFixedWidth(60)
        self.gpu_mode_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a2a4a; border: 1px solid #4a4a6e;
                border-radius: 4px; color: #8888aa; font-weight: bold;
                font-size: 12px; padding: 4px 12px;
            }
            QPushButton:checked {
                background-color: #2a6e2a; border: 2px solid #50e050;
                color: #e0ffe0;
            }
            QPushButton:!checked:hover { background-color: #333360; }
        """)
        self.gpu_mode_btn.clicked.connect(lambda: self._set_compute_mode("gpu"))
        compute_row.addWidget(self.gpu_mode_btn)
        compute_col.addLayout(compute_row)
        row3.addLayout(compute_col)

        pwr_col = QVBoxLayout()
        pwr_col.setSpacing(4)
        self.gpu_power_label = QLabel("GPU Power")
        self.gpu_power_label.setStyleSheet("font-size: 11px; color: #9898b8; background: transparent;")
        pwr_col.addWidget(self.gpu_power_label)
        pwr_row = QHBoxLayout()
        pwr_row.setSpacing(8)
        self.power_slider = QSlider(Qt.Horizontal)
        self.power_slider.setRange(10, 100)
        self.power_slider.setValue(100)
        self.power_slider.setTickInterval(10)
        self.power_slider.setSingleStep(5)
        self.power_label = QLabel("100%")
        self.power_label.setFixedWidth(40)
        self.power_label.setStyleSheet("color: #e0e0e0; font-weight: bold; background: transparent;")
        self.power_slider.valueChanged.connect(lambda v: self.power_label.setText(f"{v}%"))
        pwr_row.addWidget(self.power_slider)
        pwr_row.addWidget(self.power_label)
        pwr_col.addLayout(pwr_row)
        self.gpu_power_widget = QWidget()
        gpu_power_inner = QVBoxLayout(self.gpu_power_widget)
        gpu_power_inner.setContentsMargins(0, 0, 0, 0)
        gpu_power_inner.addLayout(pwr_col)
        row3.addWidget(self.gpu_power_widget)

        temp_col = QVBoxLayout()
        temp_col.setSpacing(4)
        self.gpu_temp_label_title = QLabel("Max GPU Temp")
        self.gpu_temp_label_title.setStyleSheet("font-size: 11px; color: #9898b8; background: transparent;")
        temp_col.addWidget(self.gpu_temp_label_title)
        self.max_temp_spin = QSpinBox()
        self.max_temp_spin.setRange(60, 95)
        self._detected_gpu_name = None
        self._recommended_temp = 80
        self.max_temp_spin.setValue(80)
        self.max_temp_spin.setSuffix("°C")
        temp_col.addWidget(self.max_temp_spin)
        self.gpu_temp_widget = QWidget()
        gpu_temp_inner = QVBoxLayout(self.gpu_temp_widget)
        gpu_temp_inner.setContentsMargins(0, 0, 0, 0)
        gpu_temp_inner.addLayout(temp_col)
        row3.addWidget(self.gpu_temp_widget)

        gpu_info_col = QVBoxLayout()
        gpu_info_col.setSpacing(4)
        gpu_info_title = QLabel("Detected GPU")
        gpu_info_title.setStyleSheet("font-size: 11px; color: #9898b8; background: transparent;")
        gpu_info_col.addWidget(gpu_info_title)
        self.gpu_name_label = QLabel("Not detected")
        self.gpu_name_label.setStyleSheet(
            "font-size: 11px; font-weight: bold; color: #6ea8fe; background: transparent; padding: 4px 0;"
        )
        self.gpu_name_label.setWordWrap(True)
        gpu_info_col.addWidget(self.gpu_name_label)
        self.gpu_info_widget = QWidget()
        gpu_info_inner = QVBoxLayout(self.gpu_info_widget)
        gpu_info_inner.setContentsMargins(0, 0, 0, 0)
        gpu_info_inner.addLayout(gpu_info_col)
        row3.addWidget(self.gpu_info_widget)

        sg.addLayout(row3)

        root.addWidget(self.settings_content)

        mode_frame = QFrame()
        mode_frame.setStyleSheet("""
            QFrame {
                background-color: #222244;
                border: 1px solid #3a3a5c;
                border-radius: 6px;
                padding: 8px;
            }
        """)
        mode_layout = QVBoxLayout(mode_frame)
        mode_layout.setSpacing(6)
        mode_layout.setContentsMargins(10, 8, 10, 8)

        mode_header = QHBoxLayout()
        mode_header.setSpacing(12)

        mode_title = QLabel("Mining Mode:")
        mode_title.setStyleSheet("font-size: 12px; font-weight: bold; color: #b0b0dd; background: transparent; border: none;")
        mode_header.addWidget(mode_title)

        self.mine_mode_btn = QPushButton("Mine Mode")
        self.mine_mode_btn.setCheckable(True)
        self.mine_mode_btn.setChecked(True)
        self.mine_mode_btn.setFixedWidth(120)
        self.mine_mode_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a6e2a; border: 2px solid #50e050;
                border-radius: 4px; color: #e0ffe0; font-weight: bold;
                font-size: 12px; padding: 6px 12px;
            }
            QPushButton:!checked {
                background-color: #2a2a4a; border: 1px solid #4a4a6e;
                color: #8888aa;
            }
            QPushButton:!checked:hover { background-color: #333360; }
        """)
        self.mine_mode_btn.clicked.connect(lambda: self._set_mining_mode("mine"))
        mode_header.addWidget(self.mine_mode_btn)

        self.blind_mode_btn = QPushButton("Blind Mode")
        self.blind_mode_btn.setCheckable(True)
        self.blind_mode_btn.setChecked(False)
        self.blind_mode_btn.setFixedWidth(120)
        self.blind_mode_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a2a4a; border: 1px solid #4a4a6e;
                border-radius: 4px; color: #8888aa; font-weight: bold;
                font-size: 12px; padding: 6px 12px;
            }
            QPushButton:checked {
                background-color: #6e2a6e; border: 2px solid #e050e0;
                color: #ffe0ff;
            }
            QPushButton:!checked:hover { background-color: #333360; }
        """)
        self.blind_mode_btn.clicked.connect(lambda: self._set_mining_mode("blind"))
        mode_header.addWidget(self.blind_mode_btn)

        self.mode_status_label = QLabel("Keys saved locally for your use")
        self.mode_status_label.setStyleSheet("font-size: 11px; color: #50e050; font-weight: bold; background: transparent; border: none;")
        mode_header.addWidget(self.mode_status_label)
        mode_header.addStretch()
        mode_layout.addLayout(mode_header)

        self.blind_wallet_widget = QWidget()
        self.blind_wallet_widget.setStyleSheet("background: transparent; border: none;")
        blind_wallet_layout = QVBoxLayout(self.blind_wallet_widget)
        blind_wallet_layout.setContentsMargins(0, 4, 0, 0)
        blind_wallet_layout.setSpacing(4)

        bw_row = QHBoxLayout()
        bw_row.setSpacing(8)
        bw_lbl = QLabel("Seller Wallet:")
        bw_lbl.setStyleSheet("font-size: 11px; color: #9898b8; background: transparent; border: none;")
        bw_row.addWidget(bw_lbl)
        self.seller_wallet_edit = QLineEdit()
        self.seller_wallet_edit.setPlaceholderText("Set SOLANA_DEVNET_PRIVKEY env var or load from file")
        self.seller_wallet_edit.setEchoMode(QLineEdit.Password)
        env_key = os.environ.get("SOLANA_DEVNET_PRIVKEY", "")
        if env_key:
            self.seller_wallet_edit.setText(env_key)
        bw_row.addWidget(self.seller_wallet_edit)

        load_key_btn = QPushButton("Load Key File")
        load_key_btn.setFixedWidth(110)
        load_key_btn.clicked.connect(self._load_seller_key_file)
        bw_row.addWidget(load_key_btn)

        show_key_btn = QPushButton("Show/Hide")
        show_key_btn.setFixedWidth(90)
        show_key_btn.clicked.connect(self._toggle_seller_key_visibility)
        bw_row.addWidget(show_key_btn)
        blind_wallet_layout.addLayout(bw_row)

        price_row = QHBoxLayout()
        price_row.setSpacing(8)
        price_lbl = QLabel("Price (SOL):")
        price_lbl.setStyleSheet("font-size: 11px; color: #9898b8; background: transparent; border: none;")
        price_row.addWidget(price_lbl)
        self.blind_price_spin = QDoubleSpinBox()
        self.blind_price_spin.setRange(0, 1000)
        self.blind_price_spin.setDecimals(4)
        self.blind_price_spin.setValue(0.1)
        self.blind_price_spin.setSingleStep(0.01)
        self.blind_price_spin.setFixedWidth(120)
        price_row.addWidget(self.blind_price_spin)
        price_hint = QLabel("0 = Free. Buyer pays this in SOL when purchasing.")
        price_hint.setStyleSheet("font-size: 10px; color: #7878a0; background: transparent; border: none;")
        price_row.addWidget(price_hint)
        price_row.addStretch()
        blind_wallet_layout.addLayout(price_row)

        blind_info = QLabel(
            "Blind Mode: Keys are uploaded to the Solana devnet marketplace with an NFT. "
            "Buyers pay the listed price in SOL to your wallet, then burn the NFT to receive the key."
        )
        blind_info.setWordWrap(True)
        blind_info.setStyleSheet("font-size: 10px; color: #c878c8; background: transparent; border: none; padding: 2px 0;")
        blind_wallet_layout.addWidget(blind_info)

        self.blind_wallet_widget.setVisible(False)
        mode_layout.addWidget(self.blind_wallet_widget)

        root.addWidget(mode_frame)

        self._mining_mode = "mine"

        self.gpu_power_widget.setVisible(False)
        self.gpu_temp_widget.setVisible(False)
        self.gpu_info_widget.setVisible(False)

        status_row = QHBoxLayout()
        status_row.setSpacing(12)

        left_col = QVBoxLayout()
        left_col.setSpacing(6)

        bar = QHBoxLayout()
        bar.setSpacing(10)

        self.start_btn = QPushButton("Start Mining")
        self.start_btn.setObjectName("startBtn")
        self.start_btn.clicked.connect(self._toggle_mining)
        bar.addWidget(self.start_btn)

        self.words_label = QLabel("Words: --")
        self.words_label.setStyleSheet("color: #8888aa; background: transparent;")
        bar.addWidget(self.words_label)

        bar.addStretch()

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet(
            "color: #6ea8fe; font-weight: bold; background: transparent;"
        )
        bar.addWidget(self.status_label)

        self.speed_label = QLabel("")
        self.speed_label.setStyleSheet(
            "color: #f0c040; font-weight: bold; background: transparent;"
        )
        bar.addWidget(self.speed_label)

        self.count_label = QLabel("Found: 0")
        self.count_label.setStyleSheet(
            "color: #50e050; font-weight: bold; background: transparent;"
        )
        bar.addWidget(self.count_label)

        left_col.addLayout(bar)
        status_row.addLayout(left_col, stretch=1)

        temp_box = QGroupBox("GPU Temp")
        temp_box.setFixedWidth(130)
        temp_box.setStyleSheet("""
            QGroupBox {
                border: 2px solid #3a3a5c;
                border-radius: 8px;
                margin-top: 6px;
                padding-top: 14px;
                font-size: 10px;
                color: #8888aa;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
        """)
        temp_layout = QVBoxLayout(temp_box)
        temp_layout.setContentsMargins(4, 2, 4, 4)
        temp_layout.setAlignment(Qt.AlignCenter)
        self.temp_label = QLabel("--°C")
        self.temp_label.setAlignment(Qt.AlignCenter)
        self.temp_label.setStyleSheet(
            "font-size: 32px; font-weight: bold; color: #50e050; background: transparent;"
        )
        temp_layout.addWidget(self.temp_label)
        self.temp_status_label = QLabel("")
        self.temp_status_label.setAlignment(Qt.AlignCenter)
        self.temp_status_label.setStyleSheet(
            "font-size: 10px; color: #8888aa; background: transparent;"
        )
        temp_layout.addWidget(self.temp_status_label)
        status_row.addWidget(temp_box)

        root.addLayout(status_row)

        splitter = QSplitter(Qt.Vertical)

        results_box = QGroupBox("Found Addresses")
        rl = QVBoxLayout(results_box)
        self.results_table = QTableWidget(0, 3)
        self.results_table.setHorizontalHeaderLabels(["Address", "Suffix", "Time"])
        self.results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.results_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.results_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.verticalHeader().setVisible(False)
        rl.addWidget(self.results_table)
        splitter.addWidget(results_box)

        log_box = QGroupBox("Log")
        ll = QVBoxLayout(log_box)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        ll.addWidget(self.log_text)
        splitter.addWidget(log_box)

        splitter.setSizes([340, 140])
        root.addWidget(splitter)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        return scroll

    def _build_marketplace_tab(self):
        from PySide6.QtWidgets import QScrollArea
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        inner = QWidget()
        root = QVBoxLayout(inner)
        root.setSpacing(10)
        root.setContentsMargins(10, 10, 10, 10)

        info_lbl = QLabel(
            "Browse vanity key NFTs. Buy & Burn an NFT to decrypt the private key. "
            "Hold an NFT to resell it — burning is permanent and saves the key locally."
        )
        info_lbl.setWordWrap(True)
        info_lbl.setStyleSheet("font-size: 11px; color: #9898b8; background: transparent; padding: 4px 0;")
        root.addWidget(info_lbl)

        wallet_box = QGroupBox("Buyer Wallet")
        wallet_vbox = QVBoxLayout(wallet_box)
        wallet_vbox.setSpacing(8)

        wallet_row = QHBoxLayout()
        wallet_row.setSpacing(8)
        wallet_lbl = QLabel("Private Key:")
        wallet_lbl.setStyleSheet("font-size: 11px; color: #9898b8; background: transparent;")
        wallet_lbl.setFixedWidth(75)
        wallet_row.addWidget(wallet_lbl)
        self.buyer_wallet_edit = QLineEdit()
        self.buyer_wallet_edit.setEchoMode(QLineEdit.Password)
        self.buyer_wallet_edit.setPlaceholderText("Base58 private key (needed to burn NFT and decrypt)")
        wallet_row.addWidget(self.buyer_wallet_edit)
        self.buyer_wallet_show_btn = QPushButton("Show")
        self.buyer_wallet_show_btn.setFixedWidth(50)
        self.buyer_wallet_show_btn.clicked.connect(self._toggle_buyer_wallet_vis)
        wallet_row.addWidget(self.buyer_wallet_show_btn)
        self.import_wallet_btn = QPushButton("Import")
        self.import_wallet_btn.setFixedWidth(70)
        self.import_wallet_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a5a9e; border: 2px solid #4a8aee;
                border-radius: 4px; color: #e0e8ff; font-weight: bold;
                font-size: 11px; padding: 4px 8px;
            }
            QPushButton:hover { background-color: #3a6abe; }
            QPushButton:disabled { background-color: #2a2a4a; border-color: #4a4a6e; color: #6666aa; }
        """)
        self.import_wallet_btn.clicked.connect(self._load_owned_nfts)
        wallet_row.addWidget(self.import_wallet_btn)
        buyer_load_btn = QPushButton("Load Key File")
        buyer_load_btn.setFixedWidth(100)
        buyer_load_btn.clicked.connect(self._load_buyer_key_file)
        wallet_row.addWidget(buyer_load_btn)
        wallet_vbox.addLayout(wallet_row)

        self.wallet_address_label = QLabel("")
        self.wallet_address_label.setStyleSheet("font-size: 11px; color: #64e678; font-family: monospace; background: transparent;")
        self.wallet_address_label.setVisible(False)
        wallet_vbox.addWidget(self.wallet_address_label)

        self.owned_table = QTableWidget(0, 5)
        self.owned_table.setHorizontalHeaderLabels(["Word", "Suffix", "NFT", "Price", "Actions"])
        self.owned_table.cellClicked.connect(self._on_table_cell_clicked)
        self.owned_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.owned_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.owned_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.owned_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.owned_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.owned_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.owned_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.owned_table.setAlternatingRowColors(True)
        self.owned_table.verticalHeader().setVisible(False)
        self.owned_table.setMaximumHeight(160)
        self.owned_table.setVisible(False)
        wallet_vbox.addWidget(self.owned_table)

        self.owned_status_label = QLabel("")
        self.owned_status_label.setStyleSheet("color: #8888aa; font-size: 11px; background: transparent;")
        self.owned_status_label.setVisible(False)
        wallet_vbox.addWidget(self.owned_status_label)

        root.addWidget(wallet_box)

        self._owned_packages = []

        self.upload_status_label = QLabel("")
        self.upload_status_label.setStyleSheet("color: #8888aa; font-size: 11px; background: transparent;")
        root.addWidget(self.upload_status_label)

        buyer_box = QGroupBox("NFT Marketplace")
        buyer_layout = QVBoxLayout(buyer_box)
        buyer_layout.setSpacing(8)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)

        self.browse_packages_btn = QPushButton("Search Packages")
        self.browse_packages_btn.setObjectName("startBtn")
        self.browse_packages_btn.setFixedWidth(160)
        self.browse_packages_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a5a9e; border: 2px solid #4a8aee;
                border-radius: 4px; color: #e0e8ff; font-weight: bold;
                font-size: 12px; padding: 8px 16px;
            }
            QPushButton:hover { background-color: #3a6abe; }
            QPushButton:disabled { background-color: #2a2a4a; border-color: #4a4a6e; color: #6666aa; }
        """)
        self.browse_packages_btn.clicked.connect(self._browse_packages)
        search_row.addWidget(self.browse_packages_btn)

        self.search_filter_edit = QLineEdit()
        self.search_filter_edit.setPlaceholderText("Filter by vanity address suffix (optional)")
        self.search_filter_edit.setFixedWidth(280)
        search_row.addWidget(self.search_filter_edit)

        self.packages_status_label = QLabel("Click 'Search Packages' to fetch uploaded vanity keys from devnet")
        self.packages_status_label.setStyleSheet("color: #8888aa; font-size: 11px; background: transparent;")
        search_row.addWidget(self.packages_status_label)
        search_row.addStretch()
        buyer_layout.addLayout(search_row)

        self.packages_table = QTableWidget(0, 6)
        self.packages_table.setHorizontalHeaderLabels(["Word", "Suffix", "NFT", "Price", "Status", "Verified"])
        self.packages_table.cellClicked.connect(self._on_table_cell_clicked)
        self.packages_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.packages_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.packages_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.packages_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.packages_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.packages_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.packages_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.packages_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.packages_table.setAlternatingRowColors(True)
        self.packages_table.verticalHeader().setVisible(False)
        self.packages_table.selectionModel().selectionChanged.connect(self._on_package_selected)
        buyer_layout.addWidget(self.packages_table)

        buy_row = QHBoxLayout()
        buy_row.setSpacing(8)
        self.buy_btn = QPushButton("Buy - Select a package")
        self.buy_btn.setFixedHeight(40)
        self.buy_btn.setMinimumWidth(220)
        self.buy_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a5a9e; border: 2px solid #4a8aee;
                border-radius: 6px; color: #e0e8ff; font-weight: bold;
                font-size: 13px; padding: 8px 16px;
            }
            QPushButton:hover { background-color: #3a6abe; }
            QPushButton:disabled { background-color: #2a2a4a; border-color: #4a4a6e; color: #6666aa; font-size: 12px; }
        """)
        self.buy_btn.setEnabled(False)
        self.buy_btn.clicked.connect(self._buy_nft)
        buy_row.addWidget(self.buy_btn)

        self.burn_btn = QPushButton("Burn && Decrypt")
        self.burn_btn.setFixedHeight(40)
        self.burn_btn.setMinimumWidth(180)
        self.burn_btn.setStyleSheet("""
            QPushButton {
                background-color: #8e2a2a; border: 2px solid #ff5050;
                border-radius: 6px; color: #ffe0e0; font-weight: bold;
                font-size: 13px; padding: 8px 16px;
            }
            QPushButton:hover { background-color: #ae3a3a; }
            QPushButton:disabled { background-color: #2a2a4a; border-color: #4a4a6e; color: #6666aa; font-size: 12px; }
        """)
        self.burn_btn.setEnabled(False)
        self.burn_btn.clicked.connect(self._burn_nft)
        buy_row.addWidget(self.burn_btn)

        self.decrypt_status_label = QLabel("")
        self.decrypt_status_label.setStyleSheet("color: #8888aa; font-size: 11px; background: transparent;")
        buy_row.addWidget(self.decrypt_status_label)
        buy_row.addStretch()
        buyer_layout.addLayout(buy_row)

        result_row = QHBoxLayout()
        result_row.setSpacing(8)
        result_lbl = QLabel("Saved To:")
        result_lbl.setStyleSheet("font-size: 11px; color: #9898b8; background: transparent;")
        result_lbl.setFixedWidth(65)
        result_row.addWidget(result_lbl)
        self.decrypted_key_edit = QLineEdit()
        self.decrypted_key_edit.setReadOnly(True)
        self.decrypted_key_edit.setPlaceholderText("Burn an NFT to decrypt — key will be saved to decrypted_keys/")
        result_row.addWidget(self.decrypted_key_edit)
        buyer_layout.addLayout(result_row)

        root.addWidget(buyer_box)

        bounty_box = QGroupBox("Bounty Board")
        bounty_layout = QVBoxLayout(bounty_box)
        bounty_layout.setSpacing(8)

        bounty_info = QLabel("Post a bounty for a specific vanity word. Miners can see your request and fulfill it.")
        bounty_info.setWordWrap(True)
        bounty_info.setStyleSheet("font-size: 11px; color: #9898b8; background: transparent; padding: 2px 0;")
        bounty_layout.addWidget(bounty_info)

        bounty_form = QHBoxLayout()
        bounty_form.setSpacing(8)

        self.bounty_word_edit = QLineEdit()
        self.bounty_word_edit.setPlaceholderText("Word you want (e.g. dragon)")
        self.bounty_word_edit.setFixedWidth(180)
        bounty_form.addWidget(self.bounty_word_edit)

        self.bounty_reward_edit = QLineEdit()
        self.bounty_reward_edit.setPlaceholderText("Reward SOL")
        self.bounty_reward_edit.setText("0.5")
        self.bounty_reward_edit.setFixedWidth(100)
        bounty_form.addWidget(self.bounty_reward_edit)

        self.bounty_address_edit = QLineEdit()
        self.bounty_address_edit.setPlaceholderText("Your wallet address (public key)")
        bounty_form.addWidget(self.bounty_address_edit)

        self.post_bounty_btn = QPushButton("Post Bounty")
        self.post_bounty_btn.setFixedWidth(110)
        self.post_bounty_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a5a9e; border: 2px solid #4a8aee;
                border-radius: 4px; color: #e0e8ff; font-weight: bold;
                font-size: 11px; padding: 6px 12px;
            }
            QPushButton:hover { background-color: #3a6abe; }
        """)
        self.post_bounty_btn.clicked.connect(self._post_bounty)
        bounty_form.addWidget(self.post_bounty_btn)
        bounty_layout.addLayout(bounty_form)

        self.bounty_table = QTableWidget(0, 5)
        self.bounty_table.setHorizontalHeaderLabels(["Word", "Reward", "Buyer", "Status", "Actions"])
        self.bounty_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.bounty_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.bounty_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.bounty_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.bounty_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.bounty_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.bounty_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.bounty_table.setAlternatingRowColors(True)
        self.bounty_table.verticalHeader().setVisible(False)
        self.bounty_table.setMaximumHeight(180)
        bounty_layout.addWidget(self.bounty_table)

        root.addWidget(bounty_box)

        mp_log_box = QGroupBox("Marketplace Log")
        mp_log_layout = QVBoxLayout(mp_log_box)
        self.mp_log_text = QTextEdit()
        self.mp_log_text.setReadOnly(True)
        mp_log_layout.addWidget(self.mp_log_text)
        root.addWidget(mp_log_box)

        self._packages_data = []

        try:
            from core.marketplace.lit_encrypt import get_lit_action_hash
            self._known_lit_action_hash = get_lit_action_hash()
        except Exception:
            self._known_lit_action_hash = ""

        self._load_bounties()

        scroll.setWidget(inner)
        outer.addWidget(scroll)
        return tab

    def _build_settings_tab(self):
        from PySide6.QtWidgets import QScrollArea, QMessageBox
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        inner = QWidget()
        root = QVBoxLayout(inner)
        root.setSpacing(14)
        root.setContentsMargins(14, 14, 14, 14)

        title = QLabel("Profile Settings")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #6ea8fe; background: transparent;")
        root.addWidget(title)

        desc = QLabel(
            "Configure your API keys below. Click Save Profile to store them locally "
            "so you don't have to enter them again. Settings are saved to "
            "solvanity_profile.json in the app directory."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 11px; color: #9898b8; background: transparent; padding-bottom: 6px;")
        root.addWidget(desc)

        api_box = QGroupBox("Lit Protocol Usage Key")
        api_layout = QVBoxLayout(api_box)
        api_layout.setSpacing(6)

        api_desc = QLabel(
            "Required for Blind Mode encryption. Click below to generate "
            "your personal usage key from the shared marketplace account."
        )
        api_desc.setWordWrap(True)
        api_desc.setStyleSheet("font-size: 10px; color: #7878a0; background: transparent;")
        api_layout.addWidget(api_desc)

        create_key_row = QHBoxLayout()
        create_key_row.setSpacing(8)
        create_key_btn = QPushButton("Generate Usage Key")
        create_key_btn.setFixedWidth(170)
        create_key_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a6e9e; border: 2px solid #4a9ade;
                border-radius: 6px; color: #e0f0ff; font-weight: bold;
                font-size: 12px; padding: 6px 14px;
            }
            QPushButton:hover { background-color: #3a8ebe; }
        """)
        create_key_btn.clicked.connect(self._open_lit_dashboard)
        create_key_row.addWidget(create_key_btn)

        self.lit_key_status = QLabel("")
        self.lit_key_status.setStyleSheet("font-size: 10px; background: transparent;")
        existing_usage = os.environ.get("LIT_USAGE_API_KEY", "")
        if existing_usage:
            self.lit_key_status.setText("Usage key loaded from profile")
            self.lit_key_status.setStyleSheet("font-size: 10px; color: #50e050; background: transparent;")
        create_key_row.addWidget(self.lit_key_status)
        create_key_row.addStretch()
        api_layout.addLayout(create_key_row)

        api_row = QHBoxLayout()
        api_row.setSpacing(8)
        self.settings_lit_key_edit = QLineEdit()
        self.settings_lit_key_edit.setEchoMode(QLineEdit.Password)
        self.settings_lit_key_edit.setReadOnly(True)
        self.settings_lit_key_edit.setPlaceholderText("Your usage key will appear here")
        if existing_usage:
            masked = existing_usage[:4] + "****" + existing_usage[-4:] if len(existing_usage) >= 8 else existing_usage
            self.settings_lit_key_edit.setText(masked)
        api_row.addWidget(self.settings_lit_key_edit)
        lit_show_btn = QPushButton("Show/Hide")
        lit_show_btn.setFixedWidth(90)
        lit_show_btn.clicked.connect(lambda: self.settings_lit_key_edit.setEchoMode(
            QLineEdit.Normal if self.settings_lit_key_edit.echoMode() == QLineEdit.Password else QLineEdit.Password
        ))
        api_row.addWidget(lit_show_btn)
        api_layout.addLayout(api_row)
        root.addWidget(api_box)

        wallet_box = QGroupBox("Solana Devnet Seller Wallet")
        wallet_layout = QVBoxLayout(wallet_box)
        wallet_layout.setSpacing(6)

        wallet_desc = QLabel(
            "Default seller wallet for Blind Mode. Can also be set per-session in the Mining tab."
        )
        wallet_desc.setWordWrap(True)
        wallet_desc.setStyleSheet("font-size: 10px; color: #7878a0; background: transparent;")
        wallet_layout.addWidget(wallet_desc)

        wallet_row = QHBoxLayout()
        wallet_row.setSpacing(8)
        self.settings_seller_key_edit = QLineEdit()
        self.settings_seller_key_edit.setEchoMode(QLineEdit.Password)
        self.settings_seller_key_edit.setPlaceholderText("Enter your Solana devnet private key (Base58)")
        existing_seller = os.environ.get("SOLANA_DEVNET_PRIVKEY", "")
        if existing_seller:
            self.settings_seller_key_edit.setText(existing_seller)
        wallet_row.addWidget(self.settings_seller_key_edit)
        seller_show_btn = QPushButton("Show/Hide")
        seller_show_btn.setFixedWidth(90)
        seller_show_btn.clicked.connect(lambda: self.settings_seller_key_edit.setEchoMode(
            QLineEdit.Normal if self.settings_seller_key_edit.echoMode() == QLineEdit.Password else QLineEdit.Password
        ))
        wallet_row.addWidget(seller_show_btn)
        wallet_layout.addLayout(wallet_row)

        self.seller_key_status = QLabel("")
        self.seller_key_status.setStyleSheet("font-size: 10px; background: transparent;")
        if existing_seller:
            self.seller_key_status.setText("Loaded from profile/environment")
            self.seller_key_status.setStyleSheet("font-size: 10px; color: #50e050; background: transparent;")
        wallet_layout.addWidget(self.seller_key_status)
        root.addWidget(wallet_box)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        save_btn = QPushButton("Save Profile")
        save_btn.setFixedWidth(140)
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a6e2a; border: 2px solid #50e050;
                border-radius: 6px; color: #e0ffe0; font-weight: bold;
                font-size: 13px; padding: 8px 16px;
            }
            QPushButton:hover { background-color: #3a8e3a; }
        """)
        save_btn.clicked.connect(self._save_settings_profile)
        btn_row.addWidget(save_btn)

        apply_btn = QPushButton("Apply Now")
        apply_btn.setFixedWidth(120)
        apply_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a5a9e; border: 2px solid #4a8aee;
                border-radius: 6px; color: #e0e8ff; font-weight: bold;
                font-size: 13px; padding: 8px 16px;
            }
            QPushButton:hover { background-color: #3a6abe; }
        """)
        apply_btn.clicked.connect(self._apply_settings)
        btn_row.addWidget(apply_btn)

        clear_btn = QPushButton("Clear Profile")
        clear_btn.setFixedWidth(120)
        clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #6e2a2a; border: 2px solid #e05050;
                border-radius: 6px; color: #ffe0e0; font-weight: bold;
                font-size: 13px; padding: 8px 16px;
            }
            QPushButton:hover { background-color: #8e3a3a; }
        """)
        clear_btn.clicked.connect(self._clear_settings_profile)
        btn_row.addWidget(clear_btn)

        btn_row.addStretch()
        root.addLayout(btn_row)

        self.settings_status_label = QLabel("")
        self.settings_status_label.setWordWrap(True)
        self.settings_status_label.setStyleSheet("font-size: 11px; color: #50e050; background: transparent; padding: 4px 0;")
        root.addWidget(self.settings_status_label)

        profile_path_lbl = QLabel(f"Profile file: {_get_profile_path()}")
        profile_path_lbl.setWordWrap(True)
        profile_path_lbl.setStyleSheet("font-size: 10px; color: #5858a8; background: transparent;")
        root.addWidget(profile_path_lbl)

        root.addStretch()

        scroll.setWidget(inner)
        outer.addWidget(scroll)
        return tab

    def _open_lit_dashboard(self):
        self.lit_key_status.setText("Setting up Lit Protocol (account + vault + group)...")
        self.lit_key_status.setStyleSheet("font-size: 10px; color: #6ea8fe; background: transparent;")
        from PySide6.QtCore import QThread, Signal

        class _CreateKeyThread(QThread):
            progress = Signal(str)
            done = Signal(str, str, str)

            def run(self):
                try:
                    from core.marketplace.lit_encrypt import (
                        _get_api_key, _get_pkp_public_key,
                        register_ipfs_actions, create_user_scoped_key,
                    )

                    self.progress.emit("Configuring marketplace...")
                    api_key = _get_api_key()
                    _get_pkp_public_key()

                    if not os.environ.get("LIT_GROUP_ID", "").strip():
                        self.progress.emit("Creating access group...")
                        try:
                            register_ipfs_actions()
                        except Exception:
                            pass

                    self.progress.emit("Creating your usage key...")
                    scoped_key = create_user_scoped_key()
                    os.environ["LIT_USAGE_API_KEY"] = scoped_key

                    self.done.emit(scoped_key, "", "")
                except Exception as e:
                    self.done.emit("", "", str(e))

        def _on_progress(msg):
            self.lit_key_status.setText(msg)
            self.lit_key_status.setStyleSheet("font-size: 10px; color: #6ea8fe; background: transparent;")

        def _on_done(usage_key, _wallet, error):
            self._create_key_thread = None
            if error:
                self.lit_key_status.setText(f"Failed: {error}")
                self.lit_key_status.setStyleSheet("font-size: 10px; color: #e05050; background: transparent;")
                return
            masked = usage_key[:4] + "****" + usage_key[-4:] if len(usage_key) >= 8 else usage_key
            self.settings_lit_key_edit.setText(masked)
            self._save_settings_profile()
            self.lit_key_status.setText(f"Ready! Usage key: {masked}")
            self.lit_key_status.setStyleSheet("font-size: 10px; color: #50e050; background: transparent;")

        self._create_key_thread = _CreateKeyThread()
        self._create_key_thread.progress.connect(_on_progress)
        self._create_key_thread.done.connect(_on_done)
        self._create_key_thread.start()

    def _save_settings_profile(self):
        seller_key = self.settings_seller_key_edit.text().strip()

        data = {}
        if seller_key:
            data["SOLANA_DEVNET_PRIVKEY"] = seller_key

        for env_key in ("LIT_PKP_PUBLIC_KEY", "LIT_GROUP_ID", "LIT_USAGE_API_KEY"):
            val = os.environ.get(env_key, "").strip()
            if val:
                data[env_key] = val

        try:
            _save_profile(data)
            self._apply_settings()
            self.settings_status_label.setText(f"Profile saved to {_get_profile_path()}")
            self.settings_status_label.setStyleSheet("font-size: 11px; color: #50e050; background: transparent; padding: 4px 0;")
        except Exception as e:
            self.settings_status_label.setText(f"Save failed: {e}")
            self.settings_status_label.setStyleSheet("font-size: 11px; color: #e05050; background: transparent; padding: 4px 0;")

    def _apply_settings(self):
        seller_key = self.settings_seller_key_edit.text().strip()

        if seller_key:
            os.environ["SOLANA_DEVNET_PRIVKEY"] = seller_key
            self.seller_key_status.setText("Applied to session")
            self.seller_key_status.setStyleSheet("font-size: 10px; color: #50e050; background: transparent;")
            if hasattr(self, 'seller_wallet_edit') and not self.seller_wallet_edit.text().strip():
                self.seller_wallet_edit.setText(seller_key)

        self.settings_status_label.setText("Settings applied to current session")
        self.settings_status_label.setStyleSheet("font-size: 11px; color: #50e050; background: transparent; padding: 4px 0;")

    def _clear_settings_profile(self):
        p = _get_profile_path()
        if p.exists():
            p.unlink()
        self.settings_lit_key_edit.clear()
        self.settings_seller_key_edit.clear()
        self.lit_key_status.setText("")
        self.seller_key_status.setText("")
        self.settings_status_label.setText("Profile cleared")
        self.settings_status_label.setStyleSheet("font-size: 11px; color: #e0a050; background: transparent; padding: 4px 0;")

    def _set_compute_mode(self, mode):
        self._compute_mode = mode
        self.cpu_mode_btn.setChecked(mode == "cpu")
        self.gpu_mode_btn.setChecked(mode == "gpu")
        gpu_visible = (mode == "gpu")
        self.gpu_power_widget.setVisible(gpu_visible)
        self.gpu_temp_widget.setVisible(gpu_visible)
        self.gpu_info_widget.setVisible(gpu_visible)

    def _set_mining_mode(self, mode):
        self._mining_mode = mode
        self.mine_mode_btn.setChecked(mode == "mine")
        self.blind_mode_btn.setChecked(mode == "blind")
        self.blind_wallet_widget.setVisible(mode == "blind")

        if mode == "mine":
            self.mode_status_label.setText("Keys saved locally for your use")
            self.mode_status_label.setStyleSheet("font-size: 11px; color: #50e050; font-weight: bold; background: transparent; border: none;")
            self.upload_status_label.setText("")
            self.wordlist_edit.setEnabled(True)
        else:
            self.mode_status_label.setText("Keys encrypted + uploaded to marketplace")
            self.mode_status_label.setStyleSheet("font-size: 11px; color: #e050e0; font-weight: bold; background: transparent; border: none;")
            self.upload_status_label.setText("Blind Mode active — wordlist disabled (uploads cost SOL)")
            self.upload_status_label.setStyleSheet("color: #e050e0; font-size: 11px; font-weight: bold; background: transparent;")
            self.wordlist_edit.clear()
            self.wordlist_edit.setEnabled(False)
            self._load_word_count()

    def _load_seller_key_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Seller Private Key", "", "Text Files (*.txt *.key);;All Files (*)"
        )
        if path:
            try:
                with open(path, "r") as f:
                    key_text = f.read().strip()
                for line in key_text.splitlines():
                    line = line.strip()
                    if line.lower().startswith("private key:"):
                        key_val = line.split(":", 1)[1].strip()
                        if key_val:
                            self.seller_wallet_edit.setText(key_val)
                            self._mp_log(f"Loaded seller key from {os.path.basename(path)}")
                            return
                for line in key_text.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and not line.lower().startswith("address") and len(line) >= 32:
                        self.seller_wallet_edit.setText(line)
                        self._mp_log(f"Loaded seller key from {os.path.basename(path)}")
                        return
                self._mp_log("No valid key found in file.")
            except Exception as e:
                self._mp_log(f"Failed to load key file: {e}")

    def _toggle_seller_key_visibility(self):
        if self.seller_wallet_edit.echoMode() == QLineEdit.Password:
            self.seller_wallet_edit.setEchoMode(QLineEdit.Normal)
        else:
            self.seller_wallet_edit.setEchoMode(QLineEdit.Password)

    def _get_package_price(self, pkg):
        price_str = pkg.get("price", "")
        if price_str:
            return price_str
        enc_json = pkg.get("encrypted_json", {})
        price_lamports = enc_json.get("priceLamports", 0)
        try:
            if price_lamports and int(price_lamports) > 0:
                sol = int(price_lamports) / 1_000_000_000
                return f"{sol:.2f} SOL" if sol >= 1 else f"{sol:.4f} SOL"
        except (ValueError, TypeError):
            pass
        return "Free"

    def _on_table_cell_clicked(self, row, col):
        if col != 2:
            return
        sender = self.sender()
        if not sender:
            return
        item = sender.item(row, col)
        if not item:
            return
        mint_addr = item.data(Qt.UserRole)
        if mint_addr:
            import webbrowser
            url = f"https://explorer.solana.com/address/{mint_addr}?cluster=devnet"
            webbrowser.open(url)

    def _toggle_buyer_wallet_vis(self):
        if self.buyer_wallet_edit.echoMode() == QLineEdit.Password:
            self.buyer_wallet_edit.setEchoMode(QLineEdit.Normal)
        else:
            self.buyer_wallet_edit.setEchoMode(QLineEdit.Password)

    def _load_buyer_key_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Load Buyer Key File", "", "Text Files (*.txt *.key);;All Files (*)")
        if f:
            try:
                key_text = Path(f).read_text().strip()
                for line in key_text.splitlines():
                    line = line.strip()
                    if line.lower().startswith("private key:"):
                        key_val = line.split(":", 1)[1].strip()
                        if key_val:
                            self.buyer_wallet_edit.setText(key_val)
                            self._mp_log(f"Loaded buyer key from {os.path.basename(f)}")
                            return
                for line in key_text.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and not line.lower().startswith("address") and len(line) >= 32:
                        self.buyer_wallet_edit.setText(line)
                        self._mp_log(f"Loaded buyer key from {os.path.basename(f)}")
                        return
                self._mp_log("No valid key found in file.")
            except Exception as e:
                self._mp_log(f"Failed to load buyer key: {e}")

    def _on_package_selected(self, selected, deselected):
        indexes = self.packages_table.selectionModel().selectedRows()
        if not indexes:
            self.buy_btn.setText("Buy - Select a package")
            self.buy_btn.setEnabled(False)
            self.burn_btn.setEnabled(False)
            return

        row = indexes[0].row()
        if row < len(self._packages_data):
            pkg = self._packages_data[row]
            price = self._get_package_price(pkg)
            addr = pkg.get("vanity_address", "")
            suffix = addr[-6:] if len(addr) >= 6 else addr
            nft_status = pkg.get("nft_status", "unknown")
            self.decrypt_status_label.setText("")
            if nft_status == "BURNED":
                self.buy_btn.setText("SOLD")
                self.buy_btn.setEnabled(False)
                self.burn_btn.setText("Already Burned")
                self.burn_btn.setEnabled(False)
            else:
                self.buy_btn.setText(f"Buy ...{suffix} — {price}")
                self.buy_btn.setEnabled(True)
                self.burn_btn.setText("Burn && Decrypt")
                self.burn_btn.setEnabled(True)

    def _mp_log(self, msg):
        self.mp_log_text.append(msg)

    def _browse_packages(self):
        self.packages_status_label.setText("Searching devnet for packages + checking NFT status...")
        self.browse_packages_btn.setEnabled(False)
        search_filter = self.search_filter_edit.text().strip().lower()

        def _fetch():
            try:
                from core import backend as shared
                packages = shared.search_packages(search_filter)
                self._thread_bridge.populate_packages_signal.emit(packages, "")
            except Exception as e:
                self._thread_bridge.browse_error_signal.emit(str(e))

        t = threading.Thread(target=_fetch, daemon=True)
        t.start()

    def _populate_packages(self, packages, search_filter=""):
        self.browse_packages_btn.setEnabled(True)
        self.packages_table.setRowCount(0)

        self._packages_data = packages

        if not packages:
            self.packages_status_label.setText("No packages found on devnet")
            self._mp_log("Search complete: no packages found on devnet")
            return

        self.packages_status_label.setText(f"Found {len(packages)} package(s)")
        self._mp_log(f"Search complete: {len(packages)} packages found")

        self.buy_btn.setText("Buy - Select a package")
        self.buy_btn.setEnabled(False)
        self.burn_btn.setEnabled(False)

        for pkg in packages:
            row = self.packages_table.rowCount()
            self.packages_table.insertRow(row)

            enc_json = pkg.get("encrypted_json", {})

            vanity_word = enc_json.get("vanityWord", "—")
            word_item = QTableWidgetItem(vanity_word)
            word_item.setForeground(QColor(200, 180, 255))
            self.packages_table.setItem(row, 0, word_item)

            addr = pkg.get("vanity_address", "unknown")
            suffix = addr[-6:] if len(addr) >= 6 else addr
            suffix_item = QTableWidgetItem(f"...{suffix}")
            suffix_item.setForeground(QColor(100, 230, 120))
            self.packages_table.setItem(row, 1, suffix_item)

            mint_addr = enc_json.get("mintAddress", "")
            mint_display = f"{mint_addr[:8]}..." if len(mint_addr) > 8 else (mint_addr or "—")
            mint_item = QTableWidgetItem(mint_display)
            mint_item.setToolTip(f"Click to view on Solana Explorer: {mint_addr}")
            mint_item.setForeground(QColor(100, 160, 255))
            mint_item.setData(Qt.UserRole, mint_addr)
            font = mint_item.font()
            font.setUnderline(True)
            mint_item.setFont(font)
            self.packages_table.setItem(row, 2, mint_item)

            price = self._get_package_price(pkg)
            price_item = QTableWidgetItem(price)
            price_item.setForeground(QColor(250, 210, 70))
            self.packages_table.setItem(row, 3, price_item)

            nft_status = pkg.get("nft_status", "unknown")
            status_item = QTableWidgetItem(nft_status)
            if nft_status == "ACTIVE":
                status_item.setForeground(QColor(100, 230, 120))
            elif nft_status == "BURNED":
                status_item.setForeground(QColor(255, 80, 80))
            else:
                status_item.setForeground(QColor(150, 150, 180))
            self.packages_table.setItem(row, 4, status_item)

            verified = pkg.get("verified", "Unverified")
            verified_item = QTableWidgetItem(verified)
            if verified == "TEE Verified":
                verified_item.setForeground(QColor(100, 230, 120))
            elif verified == "Unknown Code":
                verified_item.setForeground(QColor(255, 200, 50))
            else:
                verified_item.setForeground(QColor(255, 80, 80))
            self.packages_table.setItem(row, 5, verified_item)

    def _on_browse_error(self, err):
        self.browse_packages_btn.setEnabled(True)
        self.packages_status_label.setText(f"Search error: {err[:60]}")
        self._mp_log(f"Search error: {err}")

    def _get_selected_pkg(self):
        selected = self.packages_table.selectedItems()
        if not selected:
            self.decrypt_status_label.setText("Select a package first")
            return None
        row = selected[0].row()
        if row >= len(self._packages_data):
            self.decrypt_status_label.setText("Invalid selection")
            return None
        return self._packages_data[row]

    def _buy_nft(self):
        pkg = self._get_selected_pkg()
        if not pkg:
            return

        verified = pkg.get("verified", "Unverified")
        if verified != "TEE Verified":
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "Unverified Package",
                "This package was not encrypted by verified code.\n"
                "Purchase blocked for your safety.\n\n"
                f"Status: {verified}"
            )
            return

        encrypted_json = pkg.get("encrypted_json")
        if not encrypted_json:
            self.decrypt_status_label.setText("No encrypted data in this package")
            return

        mint_address = encrypted_json.get("mintAddress", "")
        if not mint_address:
            self.decrypt_status_label.setText("This package has no NFT")
            return

        buyer_key = self.buyer_wallet_edit.text().strip()
        if not buyer_key:
            self.decrypt_status_label.setText("Enter your buyer wallet private key first")
            return

        addr = pkg.get("vanity_address", "")
        suffix = addr[-6:] if len(addr) >= 6 else addr

        self.decrypt_status_label.setText(f"Buying ...{suffix}...")
        self.decrypt_status_label.setStyleSheet("color: #ffaa30; font-size: 11px; font-weight: bold; background: transparent;")
        self.buy_btn.setEnabled(False)

        vanity = pkg.get("vanity_address", "unknown")
        seller_key_override = self.seller_wallet_edit.text().strip() if hasattr(self, 'seller_wallet_edit') else ""

        def _mp(msg):
            print(f"[MP] {msg}", flush=True)
            self._thread_bridge.mp_log_signal.emit(msg)

        def _do_buy():
            from core import backend as shared
            result, err = shared.buy_nft(
                buyer_key, encrypted_json, mint_address, vanity,
                seller_key_override=seller_key_override,
                log_fn=_mp,
            )
            if err:
                self._thread_bridge.buy_error_signal.emit(err)
            else:
                self._thread_bridge.buy_success_signal.emit(result)

        t = threading.Thread(target=_do_buy, daemon=True)
        t.start()

    def _on_buy_success(self, result):
        self.buy_btn.setEnabled(True)
        vanity = result.get("vanity_address", "")
        self.decrypt_status_label.setText(f"Purchased! NFT transferred to your wallet.")
        self.decrypt_status_label.setStyleSheet("color: #50e050; font-size: 11px; font-weight: bold; background: transparent;")
        self._mp_log(f"Bought NFT for {vanity}")
        self._mp_log(f"  Transfer TX: {result.get('transfer_sig', '')}")
        if self.owned_table.isVisible():
            self._load_owned_nfts()

    def _on_buy_error(self, err):
        self.buy_btn.setEnabled(True)
        self.decrypt_status_label.setText(f"Buy failed: {err[:60]}")
        self.decrypt_status_label.setStyleSheet("color: #ff5050; font-size: 11px; background: transparent;")
        self._mp_log(f"Buy error: {err}")

    def _burn_nft(self):
        pkg = self._get_selected_pkg()
        if not pkg:
            return

        verified = pkg.get("verified", "Unverified")
        if verified != "TEE Verified":
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "Unverified Package",
                "This package was not encrypted by verified code.\n"
                "Burn blocked for your safety.\n\n"
                f"Status: {verified}"
            )
            return

        encrypted_json = pkg.get("encrypted_json")
        if not encrypted_json:
            self.decrypt_status_label.setText("No encrypted data in this package")
            return

        mint_address = encrypted_json.get("mintAddress", "")
        if not mint_address:
            self.decrypt_status_label.setText("This package has no NFT")
            return

        buyer_key = self.buyer_wallet_edit.text().strip()
        if not buyer_key:
            self.decrypt_status_label.setText("Enter your buyer wallet private key first")
            return

        vanity = pkg.get("vanity_address", "unknown")
        suffix = vanity[-6:] if len(vanity) >= 6 else vanity

        self.decrypt_status_label.setText(f"Burning ...{suffix} + decrypting...")
        self.decrypt_status_label.setStyleSheet("color: #ffaa30; font-size: 11px; font-weight: bold; background: transparent;")
        self.burn_btn.setEnabled(False)

        def _mp(msg):
            print(f"[MP] {msg}", flush=True)
            self._thread_bridge.mp_log_signal.emit(msg)

        def _do_burn():
            from core import backend as shared
            result, err = shared.burn_and_decrypt(
                buyer_key, encrypted_json, mint_address, vanity,
                log_fn=_mp,
            )
            if err:
                self._thread_bridge.burn_error_signal.emit(err)
            else:
                self._thread_bridge.burn_success_signal.emit(
                    result.get("file", ""), vanity, result.get("burn_sig", ""))

        t = threading.Thread(target=_do_burn, daemon=True)
        t.start()

    def _on_burn_status(self, msg):
        self.decrypt_status_label.setText(msg)
        self._mp_log(msg)

    def _on_burn_success(self, filepath, vanity_address, burn_sig):
        self.burn_btn.setEnabled(True)
        self.decrypt_status_label.setText("NFT burned — key decrypted and saved!")
        self.decrypt_status_label.setStyleSheet("color: #50e050; font-size: 11px; font-weight: bold; background: transparent;")
        self.decrypted_key_edit.setText(filepath)
        self._mp_log(f"Burned NFT and decrypted key for: {vanity_address}")
        self._mp_log(f"  Burn TX: {burn_sig}")
        self._mp_log(f"  Key saved to: {filepath}")

        indexes = self.packages_table.selectionModel().selectedRows()
        if indexes:
            row = indexes[0].row()
            if row < len(self._packages_data):
                self._packages_data[row]["nft_status"] = "BURNED"
                status_item = QTableWidgetItem("BURNED")
                status_item.setForeground(QColor(255, 80, 80))
                self.packages_table.setItem(row, 4, status_item)
                self.buy_btn.setText("SOLD")
                self.buy_btn.setEnabled(False)
                self.burn_btn.setText("Already Burned")
                self.burn_btn.setEnabled(False)
        if self.owned_table.isVisible():
            self._load_owned_nfts()

    def _on_burn_error(self, err):
        self.burn_btn.setEnabled(True)
        self.decrypt_status_label.setText(f"Burn failed: {err[:60]}")
        self.decrypt_status_label.setStyleSheet("color: #ff5050; font-size: 11px; background: transparent;")
        self._mp_log(f"Burn error: {err}")

    def _load_owned_nfts(self):
        buyer_key = self.buyer_wallet_edit.text().strip()
        if not buyer_key:
            self.owned_status_label.setText("Enter wallet key first")
            self.owned_status_label.setVisible(True)
            return

        self.import_wallet_btn.setEnabled(False)
        self.import_wallet_btn.setText("Loading...")
        self.owned_table.setVisible(True)
        self.owned_status_label.setVisible(True)
        self.owned_status_label.setText("Scanning devnet for your NFTs...")

        def _fetch():
            from core import backend as shared
            result, err = shared.get_owned_nfts(buyer_key)
            if err:
                self._thread_bridge.owned_error_signal.emit(err)
            else:
                self._thread_bridge.owned_nfts_signal.emit(result)

        t = threading.Thread(target=_fetch, daemon=True)
        t.start()

    def _on_owned_nfts(self, result):
        self.import_wallet_btn.setEnabled(True)
        self.import_wallet_btn.setText("Import")
        self.wallet_address_label.setText(f"Address: {result.get('wallet', '')}")
        self.wallet_address_label.setVisible(True)

        owned = result.get("owned", [])
        self._owned_packages = owned
        self.owned_table.setRowCount(0)

        if not owned:
            self.owned_status_label.setText("No NFTs found in this wallet")
            return

        self.owned_status_label.setText(f"{len(owned)} NFT(s) owned")

        for pkg in owned:
            row = self.owned_table.rowCount()
            self.owned_table.insertRow(row)

            enc_json = pkg.get("encrypted_json", {})
            word = enc_json.get("vanityWord", "—")
            self.owned_table.setItem(row, 0, QTableWidgetItem(word))

            addr = pkg.get("vanity_address", "")
            suffix = addr[-6:] if len(addr) >= 6 else addr
            self.owned_table.setItem(row, 1, QTableWidgetItem(f"...{suffix}"))

            mint = enc_json.get("mintAddress", "")
            mint_display = f"{mint[:8]}..." if len(mint) > 8 else (mint or "—")
            mint_item = QTableWidgetItem(mint_display)
            mint_item.setToolTip(f"Click to view on Solana Explorer: {mint}")
            mint_item.setForeground(QColor(100, 160, 255))
            mint_item.setData(Qt.UserRole, mint)
            font = mint_item.font()
            font.setUnderline(True)
            mint_item.setFont(font)
            self.owned_table.setItem(row, 2, mint_item)

            price = self._get_package_price(pkg)
            self.owned_table.setItem(row, 3, QTableWidgetItem(price))

            from PySide6.QtWidgets import QWidget as QW, QPushButton as QPB, QHBoxLayout as QHL
            actions_widget = QW()
            actions_layout = QHL(actions_widget)
            actions_layout.setContentsMargins(2, 2, 2, 2)
            actions_layout.setSpacing(4)

            burn_btn = QPB("Burn && Decrypt")
            burn_btn.setFixedHeight(24)
            burn_btn.setStyleSheet("font-size: 10px; padding: 2px 6px; background: #8e2a2a; border: 1px solid #ff5050; color: #ffe0e0; border-radius: 3px;")
            burn_btn.clicked.connect(lambda checked, m=mint, v=addr: self._burn_owned(m, v))
            actions_layout.addWidget(burn_btn)

            relist_btn = QPB("Relist")
            relist_btn.setFixedHeight(24)
            relist_btn.setStyleSheet("font-size: 10px; padding: 2px 6px; background: #2a2a4a; border: 1px solid #4a4a6e; color: #a0a0cc; border-radius: 3px;")
            relist_btn.clicked.connect(lambda checked, m=mint, v=addr: self._relist_owned(m, v))
            actions_layout.addWidget(relist_btn)

            self.owned_table.setCellWidget(row, 4, actions_widget)

    def _on_owned_error(self, err):
        self.import_wallet_btn.setEnabled(True)
        self.import_wallet_btn.setText("Import")
        self.owned_status_label.setText(f"Error: {err[:60]}")
        self.owned_status_label.setVisible(True)

    def _burn_owned(self, mint_address, vanity_address):
        buyer_key = self.buyer_wallet_edit.text().strip()
        if not buyer_key:
            self.owned_status_label.setText("Wallet key required")
            return

        pkg = next((p for p in self._owned_packages
                     if (p.get("encrypted_json", {}).get("mintAddress", "") == mint_address)), None)
        if not pkg:
            self.owned_status_label.setText("Package data not found")
            return

        self.owned_status_label.setText("Burning NFT + decrypting key...")

        def _mp(msg):
            self._thread_bridge.mp_log_signal.emit(msg)

        def _do():
            from core import backend as shared
            result, err = shared.burn_and_decrypt(
                buyer_key, pkg.get("encrypted_json", {}), mint_address, vanity_address,
                log_fn=_mp,
            )
            if err:
                self._thread_bridge.burn_error_signal.emit(err)
            else:
                self._thread_bridge.burn_success_signal.emit(
                    result.get("file", ""), vanity_address, result.get("burn_sig", ""))

        t = threading.Thread(target=_do, daemon=True)
        t.start()

    def _relist_owned(self, mint_address, vanity_address):
        from PySide6.QtWidgets import QInputDialog
        buyer_key = self.buyer_wallet_edit.text().strip()
        if not buyer_key:
            self.owned_status_label.setText("Wallet key required")
            return

        pkg = next((p for p in self._owned_packages
                     if (p.get("encrypted_json", {}).get("mintAddress", "") == mint_address)), None)
        current_lamports = pkg.get("encrypted_json", {}).get("priceLamports", 0) if pkg else 0
        current_sol = current_lamports / 1e9 if current_lamports else 0.01

        price, ok = QInputDialog.getDouble(self, "Relist NFT", "Price (SOL):", current_sol, 0, 1000, 4)
        if not ok:
            return

        self.owned_status_label.setText(f"Relisting at {price:.4f} SOL...")

        def _mp(msg):
            self._thread_bridge.mp_log_signal.emit(msg)

        def _do():
            from core import backend as shared
            result, err = shared.relist_nft(
                buyer_key, mint_address, vanity_address, price,
                log_fn=_mp,
            )
            if err:
                self._thread_bridge.relist_error_signal.emit(err)
            else:
                self._thread_bridge.relist_success_signal.emit(f"Relisted at {price:.4f} SOL!")

        t = threading.Thread(target=_do, daemon=True)
        t.start()

    def _on_relist_success(self, msg):
        self.owned_status_label.setText(msg)
        self._mp_log(msg)
        self._load_owned_nfts()

    def _on_relist_error(self, err):
        self.owned_status_label.setText(f"Relist failed: {err[:60]}")
        self._mp_log(f"Relist error: {err}")

    def _load_bounties(self):
        from core import backend as shared
        bounties = shared.load_bounties()
        self.bounty_table.setRowCount(0)
        for b in bounties:
            row = self.bounty_table.rowCount()
            self.bounty_table.insertRow(row)
            self.bounty_table.setItem(row, 0, QTableWidgetItem(b.get("word", "")))
            self.bounty_table.setItem(row, 1, QTableWidgetItem(f"{b.get('reward_sol', 0)} SOL"))

            buyer_addr = b.get("buyer_address", "")
            short = f"{buyer_addr[:6]}...{buyer_addr[-4:]}" if len(buyer_addr) > 12 else buyer_addr
            self.bounty_table.setItem(row, 2, QTableWidgetItem(short))

            status = b.get("status", "open")
            status_item = QTableWidgetItem(status.upper())
            if status == "open":
                status_item.setForeground(QColor(80, 224, 80))
            elif status == "fulfilled":
                status_item.setForeground(QColor(80, 160, 255))
            else:
                status_item.setForeground(QColor(150, 150, 180))
            self.bounty_table.setItem(row, 3, status_item)

            if status == "open":
                cancel_btn = QPushButton("Cancel")
                cancel_btn.setFixedHeight(24)
                cancel_btn.setStyleSheet("font-size: 10px; padding: 2px 8px;")
                bounty_id = b.get("id")
                cancel_btn.clicked.connect(lambda checked, bid=bounty_id: self._cancel_bounty(bid))
                self.bounty_table.setCellWidget(row, 4, cancel_btn)
            else:
                self.bounty_table.setItem(row, 4, QTableWidgetItem(""))

    def _post_bounty(self):
        word = self.bounty_word_edit.text().strip()
        reward_text = self.bounty_reward_edit.text().strip()
        address = self.bounty_address_edit.text().strip()

        if not word:
            self._mp_log("Bounty error: Enter a word")
            return
        try:
            reward = float(reward_text)
        except ValueError:
            self._mp_log("Bounty error: Invalid reward amount")
            return
        if reward <= 0:
            self._mp_log("Bounty error: Reward must be > 0")
            return
        if not address:
            self._mp_log("Bounty error: Enter your wallet address")
            return

        from core import backend as shared
        bounty, err = shared.create_bounty(word, reward, address)
        if err:
            self._mp_log(f"Bounty error: {err}")
        else:
            self._mp_log(f'Bounty posted: "{word}" for {reward} SOL')
            self.bounty_word_edit.clear()
            self._load_bounties()

    def _cancel_bounty(self, bounty_id):
        from core import backend as shared
        shared.delete_bounty(bounty_id)
        self._mp_log("Bounty cancelled")
        self._load_bounties()

    def _on_found_with_key(self, pubkey: str, pv_bytes: bytes, vanity_word: str = ""):
        if self._mining_mode != "blind":
            return

        wallet = self._blind_wallet_snapshot
        if not wallet:
            self._on_log(f"[Blind] ERROR: No seller wallet configured, skipping upload for {pubkey[:16]}...")
            self._mp_log(f"ERROR: No seller wallet set. Cannot upload {pubkey[:20]}...")
            return

        price_sol = getattr(self, '_blind_price_sol', 0)

        def _log(msg):
            print(f"[Blind] {msg}", flush=True)
            self._thread_bridge.log_signal.emit(f"[Blind] {msg}")

        def _mp(msg):
            print(f"[MP] {msg}", flush=True)
            self._thread_bridge.mp_log_signal.emit(msg)

        def _on_success(result, addr):
            self._thread_bridge.upload_success_signal.emit(result, addr)

        def _on_error(err, addr):
            self._thread_bridge.upload_error_signal.emit(err, addr)

        from core import backend as shared
        shared.blind_upload(
            pv_bytes, pubkey, wallet, vanity_word=vanity_word,
            price_sol=price_sol, log_fn=_log, mp_fn=_mp,
            on_success=_on_success, on_error=_on_error,
            session_blob=getattr(self, '_session_blob', None),
        )

    def _on_upload_success(self, result, pubkey):
        sig = result.get("signature", "")
        pda = result.get("pda", "")
        url = result.get("explorer_url", "")
        mint = result.get("mint_address", "")
        vanity_word = result.get("vanity_word", "")
        nft_url = f"https://explorer.solana.com/address/{mint}?cluster=devnet" if mint else ""
        self._on_log(f"[Blind] SUCCESS: {pubkey[:20]}... uploaded to marketplace")
        self._mp_log(f"SUCCESS: Uploaded {pubkey}")
        self._mp_log(f"  NFT Mint: {mint}")
        self._mp_log(f"  PDA: {pda}")
        self._mp_log(f"  TX: {sig}")
        self._mp_log(f"  Explorer: {url}")
        if nft_url:
            self._mp_log(f"  NFT Explorer: {nft_url}")
        if vanity_word:
            self._mp_log(f"  Word: {vanity_word}")
        self.upload_status_label.setText(f"Last upload: {pubkey[:12]}... (NFT: {mint[:12]}...)")

    def _on_upload_error(self, err, pubkey):
        self._on_log(f"[Blind] FAILED: Upload for {pubkey[:20]}...: {err[:60]}")
        self._mp_log(f"FAILED: Upload for {pubkey}: {err}")

    def _load_word_count(self):
        self._word_count_timer.start(400)

    @staticmethod
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

    def _do_load_word_count(self):
        try:
            raw = self.wordlist_edit.text().strip()
            wl_file, custom_words = self._parse_wordlist_input(raw)
            wf = WordFilter(
                min_length=self.min_word_spin.value(),
                wordlist_file=wl_file,
                custom_words=custom_words,
            )
            patterns = build_suffix_patterns(wf)
            if custom_words:
                source = "inline words"
            elif wl_file:
                source = "custom file"
            else:
                source = "built-in"
            self.words_label.setText(f"Words: {len(wf.words)}  |  Patterns: {len(patterns)}  ({source})")
        except Exception as e:
            self.words_label.setText(f"Words: error ({e})")

    def _toggle_settings(self):
        visible = self.settings_content.isVisible()
        self.settings_content.setVisible(not visible)
        if visible:
            self.settings_toggle.setText("▶  Mining Settings")
        else:
            self.settings_toggle.setText("▼  Mining Settings")

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if d:
            self.output_dir_edit.setText(d)

    def _browse_wordlist(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "Select Word List File", "",
            "Text Files (*.txt);;All Files (*)"
        )
        if f:
            self.wordlist_edit.setText(f)

    def _convert_wordlist_l_to_1(self):
        src = self.wordlist_edit.text().strip()
        if not src:
            self._on_log("No wordlist loaded. Browse for a file first, then click l → 1.")
            return
        src_path = Path(src)
        if not src_path.exists():
            self._on_log(f"File not found: {src}")
            return
        try:
            lines = src_path.read_text(encoding="utf-8").splitlines()
            converted = []
            added = 0
            for line in lines:
                converted.append(line)
                if 'l' in line and not line.startswith('#'):
                    variant = line.replace('l', '1')
                    if variant != line:
                        converted.append(variant)
                        added += 1
            out_name = src_path.stem + "_l1" + src_path.suffix
            out_path = src_path.parent / out_name
            out_path.write_text("\n".join(converted) + "\n", encoding="utf-8")
            self.wordlist_edit.setText(str(out_path))
            self._load_word_count()
            self._on_log(f"Created {out_name}: {added} l→1 variants added ({len(converted)} total lines). Auto-loaded.")
        except Exception as e:
            self._on_log(f"Conversion error: {e}")

    def _toggle_mining(self):
        if getattr(self, '_mining_starting', False):
            return
        if self.mining_thread and self.mining_thread.is_alive():
            self._stop_mining()
        else:
            self._start_mining()

    def _start_mining(self):
        self._mining_starting = True
        self.start_btn.setEnabled(False)
        self.start_btn.setText("Starting...")
        QApplication.processEvents()

        try:
            self._start_mining_inner()
        except Exception as e:
            self._on_log(f"Error starting mining: {e}")
            self._mining_starting = False
            self.start_btn.setEnabled(True)
            self.start_btn.setText("Start Mining")
            return

    def _start_mining_inner(self):
        def _abort():
            self._mining_starting = False
            self.start_btn.setEnabled(True)
            self.start_btn.setText("Start Mining")

        if self._mining_mode == "blind":
            wallet = self.seller_wallet_edit.text().strip()
            if not wallet:
                self._on_log("Blind Mode requires a seller wallet. Enter your key in the Seller Wallet field, or set SOLANA_DEVNET_PRIVKEY env var.")
                _abort()
                return
            try:
                from core.marketplace.solana_client import load_seller_keypair
                kp = load_seller_keypair(wallet)
                self._on_log(f"Seller wallet validated: {kp.pubkey()}")
            except Exception as e:
                self._on_log(f"Invalid seller key: {e}")
                _abort()
                return

        self.results_table.setRowCount(0)
        self.log_text.clear()
        self.count_label.setText("Found: 0")
        self.speed_label.setText("")
        self.status_label.setStyleSheet(
            "color: #6ea8fe; font-weight: bold; background: transparent;"
        )

        min_len = self.min_word_spin.value()
        output_dir = self.output_dir_edit.text()
        raw = self.wordlist_edit.text().strip()
        wl_file, custom_words = self._parse_wordlist_input(raw)

        word_filter = WordFilter(min_length=min_len, wordlist_file=wl_file, custom_words=custom_words)
        suffix_patterns = build_suffix_patterns(word_filter)

        if custom_words:
            source = f"inline: {', '.join(custom_words)}"
        elif wl_file:
            source = f"from {wl_file}"
        else:
            source = "from built-in list"
        self._on_log(f"Loaded {len(word_filter.words)} words ({source}), {len(suffix_patterns)} suffix patterns")
        pad_example = "X" * max(0, TAIL_SIZE - min_len)
        self._on_log(f"Tail pattern: {pad_example}<word> (last {TAIL_SIZE} chars of address)")
        self._on_log(f"Sample: {', '.join(suffix_patterns[:6])}...")

        power_pct = self.power_slider.value()
        max_temp = self.max_temp_spin.value()

        if self._compute_mode == "gpu":
            gpu_info = self._detected_gpu_name or "Unknown"
            self._on_log(f"Compute: GPU  |  Power: {power_pct}%  |  Max Temp: {max_temp}°C (recommended: {self._recommended_temp}°C)")
        else:
            self._on_log("Compute: CPU (pure Python)")

        self._total_keys = 0
        self._last_speed_raw = 0.0
        self._suffix_pattern_count = len(suffix_patterns)

        tee_point = None
        self._session_blob = None
        if self._mining_mode == "blind":
            try:
                from core.marketplace.lit_encrypt import split_key_setup
                self._on_log("[Blind] Setting up split-key protocol with TEE...")
                self.status_label.setText("Split-key setup...")
                session_result = split_key_setup()
                tee_point = session_result["teePoint"]
                self._session_blob = session_result
                self._on_log(f"[Blind] Split-key setup complete (session: {session_result['sessionId'][:8]}...)")
                self._on_log("[Blind] Mining with split-key: full private key will NEVER exist on this machine")
            except Exception as e:
                print(f"[Blind] Split-key setup failed: {e}", flush=True)
                self._on_log(f"[Blind] Split-key setup failed: {e}")
                self._on_log("[Blind] Falling back to direct encryption mode")

        count_limit = 0
        if self._mining_mode == "blind":
            count_limit = len(word_filter.words)
            self._on_log(f"[Blind] Will stop after finding {count_limit} addresses (one per word)")

        if self._compute_mode == "gpu":
            self.mining_thread = MiningThread(
                signals=self.signals,
                word_filter=word_filter,
                suffix_patterns=suffix_patterns,
                output_dir=output_dir,
                count=count_limit,
                iteration_bits=DEFAULT_ITERATION_BITS,
                power_pct=power_pct,
                max_temp=max_temp,
                mining_mode=self._mining_mode,
                tee_point=tee_point,
            )
        else:
            self.mining_thread = CpuMiningThread(
                signals=self.signals,
                word_filter=word_filter,
                output_dir=output_dir,
                count=count_limit,
                mining_mode=self._mining_mode,
                tee_point=tee_point,
            )

        self._blind_wallet_snapshot = self.seller_wallet_edit.text().strip() if self._mining_mode == "blind" else ""
        self._blind_price_sol = 0

        if self._mining_mode == "blind":
            price_widget = getattr(self, 'blind_price_spin', None)
            if price_widget:
                self._blind_price_sol = price_widget.value()
            price_display = f"{self._blind_price_sol:.4f} SOL" if self._blind_price_sol > 0 else "Free"
            self._on_log(f"[Blind] Mining in Blind Mode - keys will be uploaded to marketplace ({price_display})")

        self.start_btn.setText("Stop Mining")
        self.start_btn.setObjectName("stopBtn")
        self.start_btn.setStyle(self.start_btn.style())
        self.start_btn.setEnabled(True)
        self._set_controls_enabled(False)
        self._mining_starting = False
        self.status_label.setText("Starting...")
        self.start_time = time.time()
        self.timer.start(1000)
        self.mining_thread.start()

    def _stop_mining(self):
        if self.mining_thread:
            self.status_label.setText("Stopping...")
            self.start_btn.setEnabled(False)
            self.mining_thread.stop()

    def _on_stopped(self):
        self._mining_starting = False
        self.timer.stop()
        self.start_btn.setText("Start Mining")
        self.start_btn.setObjectName("startBtn")
        self.start_btn.setStyle(self.start_btn.style())
        self.start_btn.setEnabled(True)
        self._set_controls_enabled(True)
        if self.status_label.text() in ("Mining...", "Stopping...") or self.status_label.text().startswith("Mining"):
            self.status_label.setText("Stopped")
        self.mining_thread = None

    def _temp_poll_loop(self):
        if not self._gpu_detected:
            try:
                name = get_gpu_name()
                rec = get_recommended_max_temp(name)
                self._detected_gpu_name = name
                self._recommended_temp = rec
                self._gpu_detected = True
                self.signals.gpu_detected.emit(name or "Not detected", rec)
            except Exception:
                pass
        while True:
            try:
                temp = get_gpu_temp()
                with self._temp_lock:
                    self._last_temp_value = temp
            except Exception:
                pass
            time.sleep(2)

    def _on_gpu_detected(self, name, rec_temp):
        self.gpu_name_label.setText(name)
        self._recommended_temp = rec_temp
        self.max_temp_spin.setValue(rec_temp)

    def _apply_temp_display(self):
        with self._temp_lock:
            temp = self._last_temp_value

        if temp is not None:
            max_t = self.max_temp_spin.value()
            if temp >= max_t:
                zone = "hot"
            elif temp >= max_t - 10:
                zone = "warm"
            else:
                zone = "ok"

            self.temp_label.setText(f"{temp}°C")

            if zone != self._last_temp_zone:
                self._last_temp_zone = zone
                if zone == "hot":
                    color, border_color, status, status_color = "#ff4040", "#ff4040", "THROTTLED", "#ff4040"
                elif zone == "warm":
                    color, border_color, status, status_color = "#f0c040", "#f0c040", "WARM", "#f0c040"
                else:
                    color, border_color, status, status_color = "#50e050", "#3a3a5c", "OK", "#50e050"
                self.temp_label.setStyleSheet(
                    f"font-size: 32px; font-weight: bold; color: {color}; background: transparent;"
                )
                self.temp_status_label.setText(status)
                self.temp_status_label.setStyleSheet(
                    f"font-size: 10px; font-weight: bold; color: {status_color}; background: transparent;"
                )
                self.temp_label.parent().setStyleSheet(f"""
                    QGroupBox {{
                        border: 2px solid {border_color};
                        border-radius: 8px;
                        margin-top: 6px;
                        padding-top: 14px;
                        font-size: 10px;
                        color: #8888aa;
                    }}
                    QGroupBox::title {{
                        subcontrol-origin: margin;
                        left: 10px;
                        padding: 0 4px;
                    }}
                """)
        elif self._last_temp_zone != "none":
            self._last_temp_zone = "none"
            self.temp_label.setText("--°C")
            self.temp_label.setStyleSheet(
                "font-size: 32px; font-weight: bold; color: #555577; background: transparent;"
            )
            self.temp_status_label.setText("N/A")

    def _set_controls_enabled(self, enabled):
        self.min_word_spin.setEnabled(enabled)
        self.output_dir_edit.setEnabled(enabled)
        self.wordlist_edit.setEnabled(enabled)
        self.power_slider.setEnabled(enabled)
        self.max_temp_spin.setEnabled(enabled)
        self.mine_mode_btn.setEnabled(enabled)
        self.blind_mode_btn.setEnabled(enabled)
        self.cpu_mode_btn.setEnabled(enabled)
        self.gpu_mode_btn.setEnabled(enabled)

    def _on_found(self, address, suffix, elapsed, count):
        row = self.results_table.rowCount()
        self.results_table.insertRow(row)

        addr_item = QTableWidgetItem(address)
        addr_item.setForeground(QColor(100, 230, 120))
        self.results_table.setItem(row, 0, addr_item)

        suffix_item = QTableWidgetItem(suffix)
        suffix_item.setForeground(QColor(250, 210, 70))
        self.results_table.setItem(row, 1, suffix_item)

        time_item = QTableWidgetItem(elapsed)
        time_item.setForeground(QColor(160, 170, 240))
        self.results_table.setItem(row, 2, time_item)

        self.results_table.scrollToBottom()
        self.count_label.setText(f"Found: {count}")

    def _on_log(self, msg):
        self.log_text.append(msg)

    def _on_status(self, msg):
        self.status_label.setText(msg)

    def _on_speed(self, speed_val):
        self._last_speed_raw = speed_val
        if self.start_time and speed_val > 0:
            elapsed = time.time() - self.start_time
            self._total_keys = int(speed_val * elapsed)

        def _fmt_keys(n):
            if n >= 1e9:
                return f"{n / 1e9:.1f}B"
            if n >= 1e6:
                return f"{n / 1e6:.1f}M"
            if n >= 1e3:
                return f"{n / 1e3:.0f}K"
            return str(n)

        speed_str = f"{speed_val / 1e6:.2f} MKeys/s"
        if self._total_keys > 0:
            speed_str += f"  |  {_fmt_keys(self._total_keys)} checked"

        if self._suffix_pattern_count > 0 and speed_val > 0:
            prob_per_key = self._suffix_pattern_count / (58 ** 6)
            if prob_per_key > 0:
                expected_keys = 1.0 / prob_per_key
                remaining = max(0, expected_keys - self._total_keys)
                eta_secs = remaining / speed_val
                if eta_secs < 60:
                    speed_str += f"  |  ~{eta_secs:.0f}s ETA"
                elif eta_secs < 3600:
                    speed_str += f"  |  ~{eta_secs / 60:.1f}m ETA"
                else:
                    speed_str += f"  |  ~{eta_secs / 3600:.1f}h ETA"

        self.speed_label.setText(speed_str)

    def _on_error(self, msg):
        self.status_label.setText("Error")
        self.status_label.setStyleSheet(
            "color: #ff5050; font-weight: bold; background: transparent;"
        )
        self._on_log(f"ERROR: {msg}")

    def _update_elapsed(self):
        if self.start_time:
            elapsed = time.time() - self.start_time
            m, s = divmod(int(elapsed), 60)
            h, m = divmod(m, 60)
            self.status_label.setText(f"Mining... {h:02d}:{m:02d}:{s:02d}")

    def closeEvent(self, event):
        if self.mining_thread and self.mining_thread.is_alive():
            self.mining_thread.stop()
            self.mining_thread.join(timeout=3)
        event.accept()


def _setup_error_log():
    if getattr(sys, 'frozen', False):
        log_path = os.path.join(os.path.dirname(sys.executable), "solvanity_error.log")
        try:
            fh = open(log_path, "a", encoding="utf-8")
            sys.stderr = fh
            sys.stdout = fh
        except Exception:
            pass


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    window = MainWindow()
    window.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    multiprocessing.freeze_support()
    _setup_error_log()
    main()
