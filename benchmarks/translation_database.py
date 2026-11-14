"""Benchmark de cache e busca usando banco de traduções sintético."""
import argparse
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
from tradutor_pgn.database import fetch_review_rows_page, initialize_database, load_translation_cache


def _original(index):
    return f"position{index:010d} synthetic chess comment"


def _translated(index):
    return f"comentário sintético {index:010d}"


def create_database(path, rows):
    if rows < 1:
        raise ValueError("O número de linhas deve ser positivo")
    # Criação exclusiva: nunca substituir um banco passado por engano.
    with Path(path).open("xb"):
        pass
    conn = initialize_database(str(path))
    try:
        conn.executemany(
            "INSERT INTO comments (original_comment, translated_comment, source_language, target_language, quality_warning) "
            "VALUES (?, ?, 'en', 'pt', 0)",
            ((_original(index), _translated(index)) for index in range(rows)),
        )
        conn.commit()
        return conn
    except BaseException:
        conn.close()
        raise


def _measure_operation(operation, samples):
    durations = []
    for _ in range(samples):
        started = time.perf_counter()
        operation()
        durations.append(time.perf_counter() - started)
    tracemalloc.start()
    try:
        operation()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return {"durations_seconds": durations, "median_seconds": statistics.median(durations),
            "p95_seconds": percentile95(durations), "peak_python_bytes": peak}


def measure(path, rows, samples):
    if samples < 1:
        raise ValueError("O número de amostras deve ser positivo")
    conn = create_database(path, rows)
    try:
        cursor = conn.cursor()
        indices = [index * rows // min(rows, 100) for index in range(min(rows, 100))]
        requested = [_original(index) for index in indices]
        expected = [(_original(index), _translated(index)) for index in indices]
        target_index = min(rows - 1, 42)
        needle = f"position{target_index:010d}"

        def full_cache():
            result = load_translation_cache(cursor, "pt", source_language="en")
            if len(result) != rows or result.get(_original(target_index)) != _translated(target_index):
                raise RuntimeError("Cache completo não corresponde ao corpus")

        def subset_cache():
            result = load_translation_cache(cursor, "pt", requested, source_language="en")
            if any(result.get(original) != translated for original, translated in expected):
                raise RuntimeError("Cache parcial não corresponde aos comentários solicitados")

        def search():
            result = fetch_review_rows_page(cursor, "pt", source_language="en", search_text=needle, limit=100)
            if len(result) != 1 or result[0][1] != _original(target_index):
                raise RuntimeError("Busca não retornou o comentário esperado")

        measurements = {name: _measure_operation(operation, samples) for name, operation in
                        (("full_cache", full_cache), ("subset_cache", subset_cache), ("search", search))}
        return {"rows": rows, "samples": samples, "subset_requested": len(requested),
                "search_mode": "substring", "measurements": measurements}
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", nargs="+", type=positive, default=[10000])
    parser.add_argument("--samples", type=positive, default=5)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="pgn-benchmark-db-") as directory:
        results = [measure(Path(directory) / f"cache-{index}.db", count, args.samples)
                   for index, count in enumerate(args.rows)]
    print(json.dumps({
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {"python": sys.version.split()[0], "platform": platform.platform(),
                        "machine": platform.machine(), "processor": platform.processor(),
                        "logical_cpus": os.cpu_count()},
        "method": "banco sintético; p95 nearest-rank; pico Python medido em execução separada",
        "results": results,
    }, indent=2))


if __name__ == "__main__":
    main()
