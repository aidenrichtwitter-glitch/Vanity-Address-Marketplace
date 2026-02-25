import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue, Empty

from src.crypto import keypair_from_seed, save_keypair
from src.gpu_miner import GPUMiner, CPUBatchGenerator, GPU_AVAILABLE
from src.word_filter import WordFilter
from src.display import MinerDisplay


class VanityMiner:
    def __init__(self, args):
        self.args = args
        self.suffix = args.suffix
        self.prefix = args.prefix
        self.case_sensitive = args.case_sensitive
        self.output_file = args.output
        self.gpu_only = args.gpu_only
        self.use_gpu = not args.no_gpu and GPU_AVAILABLE
        self.running = False

        self.display = MinerDisplay()
        self.display.suffix = self.suffix
        self.display.prefix = self.prefix

        if not self.gpu_only:
            custom_words = []
            if args.custom_words:
                custom_words = [w.strip() for w in args.custom_words.split(",") if w.strip()]
            self.word_filter = WordFilter(
                min_length=args.min_word_length,
                max_length=args.max_word_length,
                custom_words=custom_words,
                case_sensitive=self.case_sensitive,
            )
        else:
            self.word_filter = None

        self.seed_queue = Queue(maxsize=args.threads * 2)
        self.result_queue = Queue()

    def check_suffix_match(self, address):
        if self.suffix:
            if self.case_sensitive:
                if not address.endswith(self.suffix):
                    return False
            else:
                if not address.lower().endswith(self.suffix.lower()):
                    return False

        if self.prefix:
            if self.case_sensitive:
                if not address.startswith(self.prefix):
                    return False
            else:
                if not address.lower().startswith(self.prefix.lower()):
                    return False

        return True

    def process_seed(self, seed):
        try:
            private_key, public_key, address = keypair_from_seed(seed)
        except Exception:
            return None

        if not self.check_suffix_match(address):
            return None

        if self.gpu_only:
            return {
                "private_key": private_key,
                "public_key": public_key,
                "address": address,
                "words": ["suffix_match"],
                "score": len(self.suffix) + len(self.prefix),
            }

        words = self.word_filter.find_words(address)
        if words:
            score = self.word_filter.score_address(address)
            return {
                "private_key": private_key,
                "public_key": public_key,
                "address": address,
                "words": words,
                "score": score,
            }

        return None

    def cpu_worker(self):
        while self.running:
            try:
                seeds = self.seed_queue.get(timeout=0.5)
            except Empty:
                continue

            suffix_matches = 0
            word_matches = 0

            for seed in seeds:
                result = self.process_seed(seed)
                if result:
                    if self.suffix or self.prefix:
                        suffix_matches += 1
                    word_matches += 1
                    self.result_queue.put(result)

            self.display.update_stats(
                generated=len(seeds),
                suffix_match=suffix_matches,
                word_match=word_matches,
            )

    def gpu_producer(self):
        try:
            miner = GPUMiner(
                device_index=self.args.gpu_device,
                batch_size=self.args.gpu_batch_size,
            )
            device_name = miner.initialize()
            self.display.gpu_name = device_name
            self.display.mode = "GPU + CPU"
            self.display.status = "Mining with GPU acceleration"

            batch_offset = 0
            while self.running:
                seeds = miner.generate_batch(
                    suffix=self.suffix.encode() if self.suffix else b"",
                    prefix=self.prefix.encode() if self.prefix else b"",
                    batch_offset=batch_offset,
                )
                batch_offset += 1

                chunk_size = max(1, len(seeds) // self.args.threads)
                for i in range(0, len(seeds), chunk_size):
                    chunk = seeds[i : i + chunk_size]
                    try:
                        self.seed_queue.put(chunk, timeout=2)
                    except Exception:
                        pass

        except Exception as e:
            self.display.status = f"GPU init failed: {e}, falling back to CPU"
            self.cpu_producer()

    def cpu_producer(self):
        self.display.mode = "CPU Only"
        self.display.status = "Mining with CPU"
        generator = CPUBatchGenerator(batch_size=self.args.gpu_batch_size)

        while self.running:
            seeds = generator.generate_batch()
            chunk_size = max(1, len(seeds) // self.args.threads)
            for i in range(0, len(seeds), chunk_size):
                chunk = seeds[i : i + chunk_size]
                try:
                    self.seed_queue.put(chunk, timeout=2)
                except Exception:
                    pass

    def result_handler(self):
        while self.running:
            try:
                result = self.result_queue.get(timeout=1)
            except Empty:
                continue

            save_keypair(
                self.output_file,
                result["private_key"],
                result["public_key"],
                result["address"],
                result["words"],
            )

            self.display.add_find(result["address"], result["words"], result["score"])

    def run(self):
        self.running = True
        self.display.print_banner()

        if self.word_filter:
            self.display.console.print(
                f"[cyan]Loaded {len(self.word_filter.words)} cool words for filtering[/]"
            )
        if self.suffix:
            self.display.console.print(f"[cyan]Suffix filter: [bold]{self.suffix}[/bold] (case-sensitive: {self.case_sensitive})[/]")
        if self.prefix:
            self.display.console.print(f"[cyan]Prefix filter: [bold]{self.prefix}[/bold] (case-sensitive: {self.case_sensitive})[/]")
        self.display.console.print(f"[cyan]Output file: {self.output_file}[/]")
        self.display.console.print(f"[cyan]CPU threads: {self.args.threads}[/]")
        self.display.console.print()

        workers = []
        for _ in range(self.args.threads):
            t = threading.Thread(target=self.cpu_worker, daemon=True)
            t.start()
            workers.append(t)

        result_thread = threading.Thread(target=self.result_handler, daemon=True)
        result_thread.start()

        if self.use_gpu:
            producer = threading.Thread(target=self.gpu_producer, daemon=True)
        else:
            self.display.status = "Mining with CPU (no GPU detected)"
            producer = threading.Thread(target=self.cpu_producer, daemon=True)

        producer.start()

        try:
            from rich.live import Live

            with Live(self.display.render(), refresh_per_second=2, console=self.display.console) as live:
                while self.running:
                    time.sleep(0.5)
                    live.update(self.display.render())
        except KeyboardInterrupt:
            self.display.console.print("\n[yellow]Shutting down...[/]")
            self.running = False

        self.running = False
        producer.join(timeout=3)
        for w in workers:
            w.join(timeout=2)
        result_thread.join(timeout=2)

        self.display.console.print(f"\n[bold green]Total keys generated: {self.display.total_generated:,}[/]")
        self.display.console.print(f"[bold green]Word matches found: {self.display.word_matches:,}[/]")
        self.display.console.print(f"[bold green]Results saved to: {self.output_file}[/]")
