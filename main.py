#!/usr/bin/env python3
import multiprocessing
import os
import sys

os.environ.setdefault("PYOPENCL_CTX", "0:0")

import click


@click.group()
def cli():
    pass


@cli.command(name="search-pubkey", context_settings={"show_default": True})
@click.option("--starts-with", type=str, default=[], help="Prefix to match (repeatable).", multiple=True)
@click.option("--ends-with", type=str, default=[], help="Suffix to match (repeatable).", multiple=True)
@click.option("--count", type=int, default=1, help="Count of pubkeys to generate.")
@click.option("--output-dir", type=click.Path(file_okay=False, dir_okay=True, writable=True), default="./", help="Default output directory.")
@click.option("--select-device/--no-select-device", default=False, help="Select OpenCL device manually")
@click.option("--iteration-bits", type=int, default=24, help="Iteration bits (e.g., 24, 26, 28, etc.)")
@click.option("--is-case-sensitive", type=bool, default=True, help="Case sensitive search flag.")
def search_pubkey(starts_with, ends_with, count, output_dir, select_device, iteration_bits, is_case_sensitive):
    """Search for Solana vanity pubkeys using GPU (original SolVanityCL mode)."""
    from core.cli import search_pubkey as _search
    ctx = click.get_current_context()
    ctx.invoke(
        _search,
        starts_with=starts_with,
        ends_with=ends_with,
        count=count,
        output_dir=output_dir,
        select_device=select_device,
        iteration_bits=iteration_bits,
        is_case_sensitive=is_case_sensitive,
    )


@cli.command(name="search-words", context_settings={"show_default": True})
@click.option("--threads", type=int, default=None, help="CPU threads for word checking (default: all cores).")
@click.option("--min-word-length", type=int, default=4, help="Minimum word length to search for.")
@click.option("--max-word-length", type=int, default=0, help="Maximum word length (0 = no limit).")
@click.option("--custom-words", type=str, default="", help="Comma-separated custom words to add.")
@click.option("--output-dir", type=click.Path(file_okay=False, dir_okay=True, writable=True), default="./found_words", help="Output directory for found keypairs.")
@click.option("--batch-size", type=int, default=500, help="Keys per batch per thread.")
def search_words(threads, min_word_length, max_word_length, custom_words, output_dir, batch_size):
    """Mine for addresses ending in cool words with uppercase padding.

    Generates random Solana keypairs and checks if the address ends with
    a recognizable word. Shorter words require uppercase Base58 padding
    before them to fill a 6-character tail (e.g., XXomen, XXXthe).

    Found keypairs are saved as JSON files compatible with Solana CLI.
    """
    from core.word_miner import run_word_miner
    run_word_miner(
        threads=threads,
        min_word_length=min_word_length,
        max_word_length=max_word_length,
        custom_words=custom_words or None,
        output_dir=output_dir,
        batch_size=batch_size,
    )


@cli.command(name="show-device", context_settings={"show_default": True})
def show_device():
    """Show available OpenCL devices."""
    try:
        import pyopencl as cl
        platforms = cl.get_platforms()
        for p_index, platform in enumerate(platforms):
            click.echo(f"Platform {p_index}: {platform.name}")
            devices = platform.get_devices(device_type=cl.device_type.GPU)
            for d_index, device in enumerate(devices):
                click.echo(f"  - Device {d_index}: {device.name}")
        if not platforms:
            click.echo("No OpenCL platforms found.")
    except ImportError:
        click.echo("PyOpenCL not installed. GPU features unavailable.")
    except Exception as e:
        click.echo(f"Error detecting devices: {e}")


@cli.command(name="list-words", context_settings={"show_default": True})
@click.option("--min-length", type=int, default=3, help="Minimum word length.")
@click.option("--max-length", type=int, default=0, help="Maximum word length (0 = no limit).")
def list_words(min_length, max_length):
    """List all valid cool words that can appear in Base58 addresses."""
    from core.words import get_valid_words
    words = get_valid_words(min_length=min_length, max_length=max_length)
    click.echo(f"Valid words ({len(words)} total, length {min_length}-{max_length if max_length else '∞'}):")
    click.echo("-" * 60)
    if not words:
        click.echo("No words match the criteria.")
        return
    col_width = max(len(w) for w in words) + 2
    cols = max(1, 80 // col_width)
    for i in range(0, len(words), cols):
        row = words[i : i + cols]
        click.echo("".join(w.ljust(col_width) for w in row))


if __name__ == "__main__":
    multiprocessing.set_start_method("spawn")
    cli()
