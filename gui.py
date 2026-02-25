#!/usr/bin/env python3
import multiprocessing
import os
import sys
import time
import threading
from pathlib import Path

os.environ.setdefault("PYOPENCL_CTX", "0:0")

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSpinBox, QLineEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QGroupBox, QTextEdit,
    QFileDialog, QSplitter,
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QFont, QColor

from core.word_filter import WordFilter, PAD_CHAR, TAIL_SIZE
from core.word_miner import build_suffix_patterns, gpu_word_search
from core.config import DEFAULT_ITERATION_BITS
from core.utils.crypto import get_public_key_from_private_bytes, save_keypair

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
    log = Signal(str)
    status = Signal(str)
    speed = Signal(str)
    error = Signal(str)
    stopped = Signal()


class MiningThread(threading.Thread):
    def __init__(self, signals, word_filter, suffix_patterns, output_dir,
                 count, iteration_bits):
        super().__init__(daemon=True)
        self.signals = signals
        self.word_filter = word_filter
        self.suffix_patterns = suffix_patterns
        self.output_dir = output_dir
        self.count = count
        self.iteration_bits = iteration_bits
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        try:
            from core.utils.helpers import load_kernel_source
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
            kernel_source = load_kernel_source((), suffix_tuple, True)

            self.signals.log.emit(f"Kernel compiled with {len(self.suffix_patterns)} patterns")
            self.signals.status.emit("Mining...")

            Path(self.output_dir).mkdir(parents=True, exist_ok=True)

            result_count = 0
            start_time = time.time()

            mp_ctx = multiprocessing.get_context("spawn")
            with mp_ctx.Manager() as manager:
                with mp_ctx.Pool(processes=gpu_counts) as pool:
                    while not self._stop_event.is_set():
                        if 0 < self.count <= result_count:
                            break

                        stop_flag = manager.Value("i", 0)
                        lock = manager.Lock()

                        async_result = pool.starmap_async(
                            gpu_word_search,
                            [
                                (x, kernel_source, self.iteration_bits,
                                 gpu_counts, stop_flag, lock, None)
                                for x in range(gpu_counts)
                            ],
                        )

                        while not async_result.ready():
                            if self._stop_event.is_set():
                                pool.terminate()
                                self.signals.stopped.emit()
                                return
                            elapsed = time.time() - start_time
                            batch_keys = (1 << self.iteration_bits)
                            speed = batch_keys / max(elapsed, 0.001)
                            self.signals.speed.emit(f"{speed / 1e6:.2f} MKeys/s")
                            async_result.wait(0.5)

                        results = async_result.get()

                        for output in results:
                            if not output[0]:
                                continue
                            pv_bytes = bytes(output[1:])
                            pubkey = get_public_key_from_private_bytes(pv_bytes)
                            word, padding = self.word_filter.check_address(pubkey)
                            suffix_display = (padding + word) if word else pubkey[-TAIL_SIZE:]
                            save_keypair(pv_bytes, self.output_dir)
                            result_count += 1
                            elapsed = time.time() - start_time
                            self.signals.found.emit(
                                pubkey, suffix_display, f"{elapsed:.1f}s", result_count,
                            )
                            self.signals.log.emit(
                                f"[FOUND] #{result_count}: {pubkey} -> {suffix_display}"
                            )

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

        sub = QLabel("GPU-Accelerated Solana Vanity Address Mining  |  X-Padded Word Suffixes")
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet("font-size: 11px; color: #7878a0; padding-bottom: 4px; background: transparent;")
        root.addWidget(sub)

        settings = QGroupBox("Mining Settings")
        sg = QVBoxLayout(settings)
        sg.setSpacing(10)

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
        self.min_word_spin.setRange(3, 6)
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
        self.wordlist_edit.setPlaceholderText("Built-in word list (1000+ words)")
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

        root.addWidget(settings)

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

        root.addLayout(bar)

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

        self.signals = MiningSignals()
        self.signals.found.connect(self._on_found)
        self.signals.log.connect(self._on_log)
        self.signals.status.connect(self._on_status)
        self.signals.speed.connect(self._on_speed)
        self.signals.error.connect(self._on_error)
        self.signals.stopped.connect(self._on_stopped)

        self.start_time = None
        self.timer = QTimer()
        self.timer.timeout.connect(self._update_elapsed)

    def _load_word_count(self):
        try:
            wl_file = self.wordlist_edit.text().strip() or None
            wf = WordFilter(
                min_length=self.min_word_spin.value(),
                wordlist_file=wl_file,
            )
            patterns = build_suffix_patterns(wf)
            source = "custom file" if wl_file else "built-in"
            self.words_label.setText(f"Words: {len(wf.words)}  |  Patterns: {len(patterns)}  ({source})")
        except Exception as e:
            self.words_label.setText(f"Words: error ({e})")

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

    def _toggle_mining(self):
        if self.mining_thread and self.mining_thread.is_alive():
            self._stop_mining()
        else:
            self._start_mining()

    def _start_mining(self):
        self.results_table.setRowCount(0)
        self.log_text.clear()
        self.count_label.setText("Found: 0")
        self.speed_label.setText("")
        self.status_label.setStyleSheet(
            "color: #6ea8fe; font-weight: bold; background: transparent;"
        )

        min_len = self.min_word_spin.value()
        output_dir = self.output_dir_edit.text()
        wl_file = self.wordlist_edit.text().strip() or None

        word_filter = WordFilter(min_length=min_len, wordlist_file=wl_file)
        suffix_patterns = build_suffix_patterns(word_filter)

        source = f"from {wl_file}" if wl_file else "from built-in list"
        self._on_log(f"Loaded {len(word_filter.words)} words ({source}), {len(suffix_patterns)} suffix patterns")
        pad_example = "X" * max(0, TAIL_SIZE - min_len)
        self._on_log(f"Tail pattern: {pad_example}<word> (last {TAIL_SIZE} chars of address)")
        self._on_log(f"Sample: {', '.join(suffix_patterns[:6])}...")

        self.mining_thread = MiningThread(
            signals=self.signals,
            word_filter=word_filter,
            suffix_patterns=suffix_patterns,
            output_dir=output_dir,
            count=0,
            iteration_bits=DEFAULT_ITERATION_BITS,
        )

        self.start_btn.setText("Stop Mining")
        self.start_btn.setObjectName("stopBtn")
        self.start_btn.setStyle(self.start_btn.style())
        self._set_controls_enabled(False)
        self.status_label.setText("Starting...")
        self.start_time = time.time()
        self.timer.start(1000)
        self.mining_thread.start()

    def _stop_mining(self):
        if self.mining_thread:
            self.status_label.setText("Stopping...")
            self.mining_thread.stop()

    def _on_stopped(self):
        self.timer.stop()
        self.start_btn.setText("Start Mining")
        self.start_btn.setObjectName("startBtn")
        self.start_btn.setStyle(self.start_btn.style())
        self._set_controls_enabled(True)
        if self.status_label.text() in ("Mining...", "Stopping...") or self.status_label.text().startswith("Mining"):
            self.status_label.setText("Stopped")
        self.mining_thread = None

    def _set_controls_enabled(self, enabled):
        self.min_word_spin.setEnabled(enabled)
        self.output_dir_edit.setEnabled(enabled)
        self.wordlist_edit.setEnabled(enabled)

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

    def _on_speed(self, msg):
        self.speed_label.setText(msg)

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


def main():
    multiprocessing.freeze_support()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
