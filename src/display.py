import time
import threading

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.layout import Layout
from rich.align import Align


class MinerDisplay:
    def __init__(self):
        self.console = Console()
        self.start_time = time.time()
        self.total_generated = 0
        self.suffix_matches = 0
        self.word_matches = 0
        self.best_score = 0
        self.best_address = ""
        self.best_words = []
        self.recent_finds = []
        self.keys_per_second = 0
        self.gpu_name = "N/A"
        self.mode = "CPU"
        self.suffix = ""
        self.prefix = ""
        self.status = "Initializing..."
        self.lock = threading.Lock()

    def update_stats(self, generated=0, suffix_match=0, word_match=0):
        with self.lock:
            self.total_generated += generated
            self.suffix_matches += suffix_match
            self.word_matches += word_match
            elapsed = time.time() - self.start_time
            if elapsed > 0:
                self.keys_per_second = self.total_generated / elapsed

    def add_find(self, address, words, score):
        with self.lock:
            self.recent_finds.append({
                "address": address,
                "words": words,
                "score": score,
                "time": time.time(),
            })
            if len(self.recent_finds) > 10:
                self.recent_finds = self.recent_finds[-10:]
            if score > self.best_score:
                self.best_score = score
                self.best_address = address
                self.best_words = words

    def render(self):
        layout = Layout()

        elapsed = time.time() - self.start_time
        hours = int(elapsed // 3600)
        minutes = int((elapsed % 3600) // 60)
        seconds = int(elapsed % 60)

        stats_table = Table(show_header=False, box=None, padding=(0, 2))
        stats_table.add_column("Label", style="bold cyan", width=20)
        stats_table.add_column("Value", style="white")

        stats_table.add_row("Mode", f"[bold green]{self.mode}[/]")
        if self.gpu_name != "N/A":
            stats_table.add_row("GPU", self.gpu_name)
        stats_table.add_row("Runtime", f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        stats_table.add_row("Keys Generated", f"[bold]{self.total_generated:,}[/]")
        stats_table.add_row("Keys/sec", f"[bold yellow]{self.keys_per_second:,.0f}[/]")
        stats_table.add_row("", "")
        if self.suffix:
            stats_table.add_row("Suffix Filter", f"[bold magenta]{self.suffix}[/]")
        if self.prefix:
            stats_table.add_row("Prefix Filter", f"[bold magenta]{self.prefix}[/]")
        stats_table.add_row("Suffix Matches", f"[cyan]{self.suffix_matches:,}[/]")
        stats_table.add_row("Word Matches", f"[bold green]{self.word_matches:,}[/]")
        stats_table.add_row("Status", f"[bold]{self.status}[/]")

        stats_panel = Panel(
            stats_table,
            title="[bold white]SolVanity Miner Stats[/]",
            border_style="blue",
        )

        if self.best_address:
            best_text = Text()
            best_text.append(f"  {self.best_address}\n", style="bold green")
            best_text.append(f"  Words: {', '.join(self.best_words)}\n", style="yellow")
            best_text.append(f"  Score: {self.best_score}", style="cyan")
            best_panel = Panel(best_text, title="[bold]Best Find[/]", border_style="green")
        else:
            best_panel = Panel(
                Align.center("[dim]No matches yet...[/]"),
                title="[bold]Best Find[/]",
                border_style="dim",
            )

        finds_table = Table(show_header=True, box=None)
        finds_table.add_column("Address", style="green", min_width=44)
        finds_table.add_column("Words", style="yellow")
        finds_table.add_column("Score", style="cyan", justify="right")

        with self.lock:
            for find in reversed(self.recent_finds[-8:]):
                addr_display = find["address"]
                if len(addr_display) > 44:
                    addr_display = addr_display[:20] + "..." + addr_display[-20:]
                finds_table.add_row(
                    addr_display,
                    ", ".join(find["words"]),
                    str(find["score"]),
                )

        finds_panel = Panel(
            finds_table,
            title="[bold]Recent Finds[/]",
            border_style="yellow",
        )

        layout.split_column(
            Layout(stats_panel, name="stats", size=15),
            Layout(best_panel, name="best", size=6),
            Layout(finds_panel, name="finds"),
        )

        return layout

    def print_banner(self):
        banner = """
[bold cyan]╔══════════════════════════════════════════════════════════════╗
║               SolVanity - Solana Vanity Miner               ║
║          GPU-Accelerated Address Mining + Word Filter        ║
╚══════════════════════════════════════════════════════════════╝[/]
"""
        self.console.print(banner)
