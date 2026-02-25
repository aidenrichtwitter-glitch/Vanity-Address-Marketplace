import json
import logging
import os
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Queue, Empty

from base58 import b58encode
from nacl.signing import SigningKey
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.layout import Layout
from rich.align import Align

from core.word_filter import WordFilter

logging.basicConfig(level="INFO", format="[%(levelname)s %(asctime)s] %(message)s")


class MinerStats:
    def __init__(self):
        self.lock = threading.Lock()
        self.start_time = time.time()
        self.total_generated = 0
        self.word_matches = 0
        self.best_score = 0
        self.best_address = ""
        self.best_word = ""
        self.best_padding = ""
        self.recent_finds = []
        self.status = "Starting..."

    def add_generated(self, count):
        with self.lock:
            self.total_generated += count

    def add_find(self, address, word, padding, score):
        with self.lock:
            self.word_matches += 1
            self.recent_finds.append({
                "address": address,
                "word": word,
                "padding": padding,
                "score": score,
                "time": time.time(),
            })
            if len(self.recent_finds) > 20:
                self.recent_finds = self.recent_finds[-20:]
            if score > self.best_score:
                self.best_score = score
                self.best_address = address
                self.best_word = word
                self.best_padding = padding

    @property
    def keys_per_second(self):
        elapsed = time.time() - self.start_time
        if elapsed > 0:
            return self.total_generated / elapsed
        return 0

    @property
    def elapsed(self):
        return time.time() - self.start_time


def generate_and_check(word_filter, stats, output_dir, batch_size=1000):
    for _ in range(batch_size):
        seed = secrets.token_bytes(32)
        try:
            sk = SigningKey(seed)
            pk_bytes = bytes(sk.verify_key)
            address = b58encode(pk_bytes).decode()
        except Exception:
            continue

        word, padding = word_filter.check_address(address)
        if word:
            score = word_filter.score(word, padding)
            stats.add_find(address, word, padding, score)

            Path(output_dir).mkdir(parents=True, exist_ok=True)
            filepath = Path(output_dir) / f"{address}.json"
            full_key = list(bytes(sk) + pk_bytes)
            filepath.write_text(json.dumps(full_key))

            display_suffix = padding + word if padding else word
            logging.info(f"Found: {address} (suffix: {display_suffix}, score: {score})")

    stats.add_generated(batch_size)


def render_display(stats, word_filter, threads):
    elapsed = stats.elapsed
    hours = int(elapsed // 3600)
    minutes = int((elapsed % 3600) // 60)
    seconds = int(elapsed % 60)

    stats_table = Table(show_header=False, box=None, padding=(0, 2))
    stats_table.add_column("Label", style="bold cyan", width=22)
    stats_table.add_column("Value", style="white")

    stats_table.add_row("Mode", "[bold green]CPU Word Mining[/]")
    stats_table.add_row("Threads", str(threads))
    stats_table.add_row("Runtime", f"{hours:02d}:{minutes:02d}:{seconds:02d}")
    stats_table.add_row("Keys Generated", f"[bold]{stats.total_generated:,}[/]")
    stats_table.add_row("Keys/sec", f"[bold yellow]{stats.keys_per_second:,.0f}[/]")
    stats_table.add_row("Word Matches", f"[bold green]{stats.word_matches:,}[/]")
    stats_table.add_row("Words Loaded", f"{len(word_filter.words):,}")
    stats_table.add_row("Status", f"[bold]{stats.status}[/]")

    stats_panel = Panel(
        stats_table,
        title="[bold white]SolVanity Word Miner[/]",
        border_style="blue",
    )

    if stats.best_address:
        best_text = Text()
        best_text.append(f"  {stats.best_address}\n", style="bold green")
        suffix_display = stats.best_padding + stats.best_word
        best_text.append(f"  Suffix: {suffix_display}\n", style="yellow")
        best_text.append(f"  Score: {stats.best_score}", style="cyan")
        best_panel = Panel(best_text, title="[bold]Best Find[/]", border_style="green")
    else:
        best_panel = Panel(
            Align.center("[dim]Mining for words...[/]"),
            title="[bold]Best Find[/]",
            border_style="dim",
        )

    finds_table = Table(show_header=True, box=None)
    finds_table.add_column("Address", style="green", min_width=44)
    finds_table.add_column("Suffix", style="yellow", min_width=10)
    finds_table.add_column("Score", style="cyan", justify="right", min_width=6)

    with stats.lock:
        for find in reversed(stats.recent_finds[-10:]):
            addr = find["address"]
            if len(addr) > 44:
                addr = addr[:18] + "..." + addr[-18:]
            suffix_display = find["padding"] + find["word"]
            finds_table.add_row(addr, suffix_display, str(find["score"]))

    finds_panel = Panel(
        finds_table,
        title="[bold]Recent Finds[/]",
        border_style="yellow",
    )

    layout = Layout()
    layout.split_column(
        Layout(stats_panel, name="stats", size=12),
        Layout(best_panel, name="best", size=6),
        Layout(finds_panel, name="finds"),
    )
    return layout


def run_word_miner(
    threads=None,
    min_word_length=3,
    max_word_length=0,
    custom_words=None,
    output_dir="./found_words",
    batch_size=500,
):
    if threads is None:
        threads = os.cpu_count() or 4

    console = Console()

    banner = """
[bold cyan]╔══════════════════════════════════════════════════════════════╗
║           SolVanity Word Miner (SolVanityCL Fork)           ║
║      GPU-Accelerated Mining + CPU Word Suffix Filtering     ║
╚══════════════════════════════════════════════════════════════╝[/]
"""
    console.print(banner)

    custom = None
    if custom_words:
        custom = [w.strip() for w in custom_words.split(",") if w.strip()]

    word_filter = WordFilter(
        min_length=min_word_length,
        max_length=max_word_length,
        custom_words=custom,
    )

    stats = MinerStats()
    stats.status = f"Mining with {threads} threads"

    console.print(f"[cyan]Loaded {len(word_filter.words)} words (length {min_word_length}-{max_word_length if max_word_length else '∞'})[/]")
    console.print(f"[cyan]Looking for words at end of address with uppercase padding (6 char tail)[/]")
    console.print(f"[cyan]Output directory: {output_dir}[/]")
    console.print(f"[cyan]CPU threads: {threads}[/]")
    console.print()

    running = threading.Event()
    running.set()

    def worker():
        while running.is_set():
            generate_and_check(word_filter, stats, output_dir, batch_size)

    workers = []
    for _ in range(threads):
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        workers.append(t)

    try:
        with Live(render_display(stats, word_filter, threads), refresh_per_second=2, console=console) as live:
            while True:
                time.sleep(0.5)
                live.update(render_display(stats, word_filter, threads))
    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down...[/]")
        running.clear()
        for w in workers:
            w.join(timeout=3)

    console.print(f"\n[bold green]Total keys generated: {stats.total_generated:,}[/]")
    console.print(f"[bold green]Word matches found: {stats.word_matches:,}[/]")
    console.print(f"[bold green]Results saved to: {output_dir}/[/]")
