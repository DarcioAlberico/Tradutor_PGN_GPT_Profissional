"""Benchmark de geração PGN a partir de posições sintéticas já extraídas."""
import argparse
import hashlib
import json
import os
import platform
import statistics
import sys
import tempfile
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path

from benchmarks.pgn_extraction import percentile95, positive
from tradutor_pgn.pgn_utils import extract_comments_from_content, generate_translated_pgn

ORIGINAL = "synthetic position"
TRANSLATED = "posição sintética"
GAME = ('[Event "Torneio sintético"]\r\n[White "Jogador A"]\r\n\r\n'
        '1. e4 {synthetic position} e5 2. Nf3 Nc6 *\r\n\r\n').encode("utf-8")
EXPECTED_GAME = GAME.replace(b"{synthetic position}", ("{" + TRANSLATED + "}").encode("utf-8"))


def _digest_repeated(block, count):
    digest = hashlib.sha256()
    groups, remainder = divmod(count, 1024)
    chunk = block * 1024
    for _ in range(groups):
        digest.update(chunk)
    digest.update(block * remainder)
    return digest.digest()


def _digest_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.digest()


def measure(parent, target_bytes, samples):
    if target_bytes < 1 or samples < 1:
        raise ValueError("Tamanho e amostras devem ser positivos")
    count = (target_bytes + len(GAME) - 1) // len(GAME)
    expected_hash = _digest_repeated(EXPECTED_GAME, count)
    with tempfile.TemporaryDirectory(prefix="pgn-geracao-", dir=str(parent)) as directory:
        source = Path(directory) / "input.pgn"
        output = Path(directory) / "output.pgn"
        with source.open("xb") as stream:
            groups, remainder = divmod(count, 1024)
            block = GAME * 1024
            for _ in range(groups):
                stream.write(block)
            stream.write(GAME * remainder)
        content = source.read_bytes().decode("utf-8")
        positions = extract_comments_from_content(content, count_semicolons=False)["positions"]
        if len(positions) != count:
            raise RuntimeError("Número inesperado de comentários no corpus")

        def generate():
            if not generate_translated_pgn(str(source), str(output), {ORIGINAL: TRANSLATED}, positions,
                                           content=content, encoding="utf-8"):
                raise RuntimeError("Falha na geração do PGN sintético")

        def validate():
            if output.stat().st_size != len(EXPECTED_GAME) * count or _digest_file(output) != expected_hash:
                raise RuntimeError("O PGN gerado diverge da saída esperada")

        durations = []
        for _ in range(samples):
            started = time.perf_counter()
            generate()
            durations.append(time.perf_counter() - started)
            validate()
        tracemalloc.start()
        try:
            generate()
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        validate()
    return {"target_bytes": target_bytes, "input_bytes": len(GAME) * count,
            "output_bytes": len(EXPECTED_GAME) * count, "comments": count, "samples": samples,
            "durations_seconds": durations, "median_seconds": statistics.median(durations),
            "p95_seconds": percentile95(durations), "peak_python_bytes": peak}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes-mib", nargs="+", type=positive, default=[1])
    parser.add_argument("--samples", type=positive, default=5)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="pgn-benchmark-") as directory:
        results = [measure(directory, size * 1024 * 1024, args.samples) for size in args.sizes_mib]
    print(json.dumps({"timestamp_utc": datetime.now(timezone.utc).isoformat(),
                      "environment": {"python": sys.version.split()[0], "platform": platform.platform(),
                                      "machine": platform.machine(), "processor": platform.processor(),
                                      "logical_cpus": os.cpu_count()},
                      "method": "geração com posições prontas; validação fora do tempo; p95 nearest-rank; pico Python separado",
                      "results": results}, indent=2))


if __name__ == "__main__":
    main()
