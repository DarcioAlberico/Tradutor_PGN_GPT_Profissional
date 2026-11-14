"""Mede a primeira extração de comentários em PGNs sintéticos locais."""
import argparse
import json
import math
import os
import platform
import statistics
import sys
import tempfile
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path

from tradutor_pgn.pgn_utils import extract_comment_texts_from_file

GAME = (
    '[Event "Synthetic benchmark"]\n[White "Player A"]\n[Black "Player B"]\n\n'
    '1. e4 {A synthetic comment about the position and possible moves.} '
    '1... e5 2. Nf3 Nc6 3. Bb5 a6 *\n\n'
).encode("utf-8")


def write_corpus(path, target_bytes):
    if target_bytes < 1:
        raise ValueError("O tamanho deve ser positivo")
    count = (target_bytes + len(GAME) - 1) // len(GAME)
    with Path(path).open("wb") as stream:
        block_games = 1024
        block = GAME * block_games
        blocks, remainder = divmod(count, block_games)
        for _ in range(blocks):
            stream.write(block)
        stream.write(GAME * remainder)
    return count, count * len(GAME)


def percentile95(samples):
    if not samples:
        raise ValueError("É necessária pelo menos uma amostra")
    ordered = sorted(samples)
    return ordered[math.ceil(len(ordered) * 0.95) - 1]


def measure(path, target_bytes, samples):
    if samples < 1:
        raise ValueError("O número de amostras deve ser positivo")
    expected, size = write_corpus(path, target_bytes)

    def extract():
        errors = []
        result = extract_comment_texts_from_file(str(path), errors.append)
        if len(result["comments"]) != expected:
            raise RuntimeError("A extração não retornou a quantidade esperada de comentários")
        return len(result["comments"])

    durations = []
    for _ in range(samples):
        started = time.perf_counter()
        comments = extract()
        durations.append(time.perf_counter() - started)
    tracemalloc.start()
    try:
        extract()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return {
        "target_bytes": target_bytes,
        "size_bytes": size,
        "comments": comments,
        "samples": samples,
        "durations_seconds": durations,
        "median_seconds": statistics.median(durations),
        "p95_seconds": percentile95(durations),
        "peak_python_bytes": peak,
    }


def positive(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("informe um número inteiro positivo")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes-mib", nargs="+", type=positive, default=[1])
    parser.add_argument("--samples", type=positive, default=5)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="pgn-benchmark-") as directory:
        path = Path(directory) / "synthetic.pgn"
        results = [measure(path, size * 1024 * 1024, args.samples) for size in args.sizes_mib]
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "logical_cpus": os.cpu_count(),
        },
        "method": "p95 nearest-rank; pico Python medido em execução separada com tracemalloc",
        "results": results,
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
