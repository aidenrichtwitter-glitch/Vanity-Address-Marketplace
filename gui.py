#!/usr/bin/env python3
import multiprocessing
import os
import sys
import time
import json
import threading
from pathlib import Path

os.environ.setdefault("PYOPENCL_CTX", "0:0")

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSpinBox, QLineEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QGroupBox, QTextEdit,
    QFileDialog, QSplitter, QFrame,
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QFont, QColor, QPalette, QIcon

from core.word_filter import WordFilter, PAD_CHAR, TAIL_SIZE
from core.word_miner import build_suffix_patterns, gpu_word_search
from core.config import DEFAULT_ITERATION_BITS, HostSetting
from core.utils.crypto import get_public_key_from_private_bytes, save_keypair


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
                self.signals.error.emit(f"OpenCL error: {e}\n\nNo GPU found. This tool requires an OpenCL-capable GPU.")
                self.signals.stopped.emit()
                return

            if gpu_counts == 0:
                self.signals.error.emit("No GPU devices found.\nMake sure GPU drivers and OpenCL runtime are installed.")
                self.signals.stopped.emit()
                return

            self.signals.log.emit(f"Using {gpu_counts} GPU device(s)")
            self.signals.status.emit("Compiling kernel...")

            suffix_tuple = tuple(self.suffix_patterns)
            kernel_source = load_kernel_source((), suffix_tuple, True)

            self.signals.log.emit(f"Kernel compiled with {len(self.suffix_patterns)} suffix patterns")
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
                                (
                                    x,
                                    kernel_source,
                                    self.iteration_bits,
                                    gpu_counts,
                                    stop_flag,
                                    lock,
                                    None,
                                )
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
                                pubkey, suffix_display,
                                f"{elapsed:.1f}s",
                                result_count,
                            )
                            self.signals.log.emit(f"Found #{result_count}: {pubkey} [{suffix_display}]")

            self.signals.status.emit(f"Done - {result_count} found")

        except Exception as e:
            self.signals.error.emit(str(e))

        self.signals.stopped.emit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SolVanity Word Miner")
        self.setMinimumSize(900, 650)
        self.mining_thread = None

        self._setup_palette()
        self._build_ui()
        self._load_word_count()

    def _setup_palette(self):
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(30, 30, 30))
        palette.setColor(QPalette.WindowText, QColor(220, 220, 220))
        palette.setColor(QPalette.Base, QColor(40, 40, 40))
        palette.setColor(QPalette.AlternateBase, QColor(50, 50, 50))
        palette.setColor(QPalette.Text, QColor(220, 220, 220))
        palette.setColor(QPalette.Button, QColor(55, 55, 55))
        palette.setColor(QPalette.ButtonText, QColor(220, 220, 220))
        palette.setColor(QPalette.Highlight, QColor(80, 140, 210))
        palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
        self.setPalette(palette)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        title = QLabel("SolVanity Word Miner")
        title.setFont(QFont("Segoe UI", 18, QFont.Bold))
        title.setStyleSheet("color: #50b4ff; padding: 4px;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("GPU-Accelerated Solana Vanity Address Mining")
        subtitle.setFont(QFont("Segoe UI", 10))
        subtitle.setStyleSheet("color: #888;")
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(subtitle)

        settings_group = QGroupBox("Settings")
        settings_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold; color: #aaa; border: 1px solid #444;
                border-radius: 4px; margin-top: 8px; padding-top: 16px;
            }
            QGroupBox::title { subcontrol-position: top left; padding: 0 6px; }
        """)
        settings_layout = QHBoxLayout(settings_group)
        settings_layout.setSpacing(16)

        lbl_style = "color: #bbb;"
        input_style = """
            QSpinBox, QLineEdit {
                background: #333; border: 1px solid #555; border-radius: 3px;
                padding: 4px 8px; color: #eee; min-width: 80px;
            }
            QSpinBox:focus, QLineEdit:focus { border-color: #50b4ff; }
        """

        col1 = QVBoxLayout()
        lbl1 = QLabel("Min Word Length")
        lbl1.setStyleSheet(lbl_style)
        self.min_word_spin = QSpinBox()
        self.min_word_spin.setRange(3, 6)
        self.min_word_spin.setValue(4)
        self.min_word_spin.setStyleSheet(input_style)
        self.min_word_spin.valueChanged.connect(self._load_word_count)
        col1.addWidget(lbl1)
        col1.addWidget(self.min_word_spin)
        settings_layout.addLayout(col1)

        col2 = QVBoxLayout()
        lbl2 = QLabel("Max Word Length (0=no limit)")
        lbl2.setStyleSheet(lbl_style)
        self.max_word_spin = QSpinBox()
        self.max_word_spin.setRange(0, 10)
        self.max_word_spin.setValue(0)
        self.max_word_spin.setStyleSheet(input_style)
        self.max_word_spin.valueChanged.connect(self._load_word_count)
        col2.addWidget(lbl2)
        col2.addWidget(self.max_word_spin)
        settings_layout.addLayout(col2)

        col3 = QVBoxLayout()
        lbl3 = QLabel("Iteration Bits")
        lbl3.setStyleSheet(lbl_style)
        self.iter_spin = QSpinBox()
        self.iter_spin.setRange(16, 30)
        self.iter_spin.setValue(DEFAULT_ITERATION_BITS)
        self.iter_spin.setStyleSheet(input_style)
        col3.addWidget(lbl3)
        col3.addWidget(self.iter_spin)
        settings_layout.addLayout(col3)

        col4 = QVBoxLayout()
        lbl4 = QLabel("Output Directory")
        lbl4.setStyleSheet(lbl_style)
        dir_row = QHBoxLayout()
        self.output_dir_edit = QLineEdit("./found_words")
        self.output_dir_edit.setStyleSheet(input_style)
        browse_btn = QPushButton("...")
        browse_btn.setFixedWidth(32)
        browse_btn.setStyleSheet("QPushButton { background: #444; border: 1px solid #555; border-radius: 3px; color: #ccc; } QPushButton:hover { background: #555; }")
        browse_btn.clicked.connect(self._browse_dir)
        dir_row.addWidget(self.output_dir_edit)
        dir_row.addWidget(browse_btn)
        col4.addWidget(lbl4)
        col4.addLayout(dir_row)
        settings_layout.addLayout(col4)

        layout.addWidget(settings_group)

        controls = QHBoxLayout()
        controls.setSpacing(12)

        self.start_btn = QPushButton("Start Mining")
        self.start_btn.setFixedHeight(40)
        self.start_btn.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.start_btn.setStyleSheet("""
            QPushButton {
                background: #2d8f4e; border: none; border-radius: 4px;
                color: white; padding: 0 24px;
            }
            QPushButton:hover { background: #35a55a; }
            QPushButton:pressed { background: #257a42; }
        """)
        self.start_btn.clicked.connect(self._toggle_mining)
        controls.addWidget(self.start_btn)

        self.words_label = QLabel("Words: --")
        self.words_label.setStyleSheet("color: #aaa; padding: 0 8px;")
        controls.addWidget(self.words_label)

        controls.addStretch()

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #50b4ff; font-weight: bold; padding: 0 8px;")
        controls.addWidget(self.status_label)

        self.speed_label = QLabel("")
        self.speed_label.setStyleSheet("color: #f0c040; font-weight: bold; padding: 0 8px;")
        controls.addWidget(self.speed_label)

        self.count_label = QLabel("Found: 0")
        self.count_label.setStyleSheet("color: #4ae04a; font-weight: bold; padding: 0 8px;")
        controls.addWidget(self.count_label)

        layout.addLayout(controls)

        splitter = QSplitter(Qt.Vertical)
        splitter.setStyleSheet("QSplitter::handle { background: #444; height: 2px; }")

        results_group = QGroupBox("Found Addresses")
        results_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold; color: #aaa; border: 1px solid #444;
                border-radius: 4px; margin-top: 8px; padding-top: 16px;
            }
            QGroupBox::title { subcontrol-position: top left; padding: 0 6px; }
        """)
        results_layout = QVBoxLayout(results_group)

        self.results_table = QTableWidget(0, 3)
        self.results_table.setHorizontalHeaderLabels(["Address", "Suffix", "Time"])
        self.results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.results_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.results_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setStyleSheet("""
            QTableWidget {
                background: #2a2a2a; border: 1px solid #444; gridline-color: #3a3a3a;
                color: #ddd; selection-background-color: #3a6090;
            }
            QHeaderView::section {
                background: #383838; border: 1px solid #444; padding: 4px;
                color: #bbb; font-weight: bold;
            }
            QTableWidget::item:alternate { background: #303030; }
        """)
        results_layout.addWidget(self.results_table)
        splitter.addWidget(results_group)

        log_group = QGroupBox("Log")
        log_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold; color: #aaa; border: 1px solid #444;
                border-radius: 4px; margin-top: 8px; padding-top: 16px;
            }
            QGroupBox::title { subcontrol-position: top left; padding: 0 6px; }
        """)
        log_layout = QVBoxLayout(log_group)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        self.log_text.setStyleSheet("""
            QTextEdit {
                background: #1e1e1e; border: 1px solid #444; color: #aaa;
            }
        """)
        log_layout.addWidget(self.log_text)
        splitter.addWidget(log_group)

        splitter.setSizes([350, 150])
        layout.addWidget(splitter)

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
            wf = WordFilter(
                min_length=self.min_word_spin.value(),
                max_length=self.max_word_spin.value(),
            )
            patterns = build_suffix_patterns(wf)
            self.words_label.setText(f"Words: {len(wf.words)} | Patterns: {len(patterns)}")
        except Exception:
            self.words_label.setText("Words: --")

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if d:
            self.output_dir_edit.setText(d)

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

        min_len = self.min_word_spin.value()
        max_len = self.max_word_spin.value()
        output_dir = self.output_dir_edit.text()
        iteration_bits = self.iter_spin.value()

        word_filter = WordFilter(min_length=min_len, max_length=max_len)
        suffix_patterns = build_suffix_patterns(word_filter)

        self._on_log(f"Loaded {len(word_filter.words)} words, {len(suffix_patterns)} suffix patterns")
        self._on_log(f"Pattern format: {'X' * max(0, TAIL_SIZE - min_len)}<word>")
        self._on_log(f"Sample: {', '.join(suffix_patterns[:8])}...")

        self.mining_thread = MiningThread(
            signals=self.signals,
            word_filter=word_filter,
            suffix_patterns=suffix_patterns,
            output_dir=output_dir,
            count=0,
            iteration_bits=iteration_bits,
        )

        self.start_btn.setText("Stop Mining")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background: #b03030; border: none; border-radius: 4px;
                color: white; padding: 0 24px;
            }
            QPushButton:hover { background: #cc3a3a; }
            QPushButton:pressed { background: #962828; }
        """)
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
        self.start_btn.setStyleSheet("""
            QPushButton {
                background: #2d8f4e; border: none; border-radius: 4px;
                color: white; padding: 0 24px;
            }
            QPushButton:hover { background: #35a55a; }
            QPushButton:pressed { background: #257a42; }
        """)
        self._set_controls_enabled(True)
        if "Mining" in self.status_label.text() or "Stopping" in self.status_label.text():
            self.status_label.setText("Stopped")
        self.mining_thread = None

    def _set_controls_enabled(self, enabled):
        self.min_word_spin.setEnabled(enabled)
        self.max_word_spin.setEnabled(enabled)
        self.iter_spin.setEnabled(enabled)
        self.output_dir_edit.setEnabled(enabled)

    def _on_found(self, address, suffix, elapsed, count):
        row = self.results_table.rowCount()
        self.results_table.insertRow(row)

        addr_item = QTableWidgetItem(address)
        addr_item.setFont(QFont("Consolas", 10))
        addr_item.setForeground(QColor(100, 220, 100))
        self.results_table.setItem(row, 0, addr_item)

        suffix_item = QTableWidgetItem(suffix)
        suffix_item.setFont(QFont("Consolas", 10, QFont.Bold))
        suffix_item.setForeground(QColor(240, 200, 60))
        self.results_table.setItem(row, 1, suffix_item)

        time_item = QTableWidgetItem(elapsed)
        time_item.setForeground(QColor(150, 150, 220))
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
        self.status_label.setStyleSheet("color: #ff5050; font-weight: bold; padding: 0 8px;")
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
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
