"""Benchmark de aplicação de regras automáticas do glossário sintético."""
import argparse
import json
import os
import platform
import re
import statistics
import sys
import time
import tracemalloc
from datetime import datetime, timezone

from benchmarks.pgn_extraction import percentile95, positive
from tradutor_pgn import glossario


def make_case(count, unicode_text=False):
    if count < 1:
        raise ValueError("A quantidade de regras deve ser positiva")
    rules = [(f"termo{i:08d}", f"traducao{i:08d}") for i in range(count)]
    chosen = sorted({0, count // 2, count - 1})
    prefix = "Jogada café " if unicode_text else "Jogada "
    text = prefix + "; ".join(rules[i][0] for i in chosen) + "."
    expected = prefix + "; ".join(rules[i][1] for i in chosen) + "."
    return rules, text, expected


def clear_caches():
    # Apenas no processo do benchmark: o programa e os dados não são alterados.
    glossario._compiled_glossary_pattern.cache_clear()
    glossario._ordered_rules_cache.clear()
    re.purge()


def measure(count, samples, unicode_text=False):
    if samples < 1:
        raise ValueError("O número de amostras deve ser positivo")
    rules, text, expected = make_case(count, unicode_text=unicode_text)

    def apply():
        result = glossario.apply_automatic_substitutions(text, rules)
        if result != expected:
            raise RuntimeError("O resultado da aplicação divergiu do esperado")

    clear_caches()
    started = time.perf_counter()
    apply()
    cold = time.perf_counter() - started
    cache_before = glossario._compiled_glossary_pattern.cache_info()
    durations = []
    for _ in range(samples):
        started = time.perf_counter()
        apply()
        durations.append(time.perf_counter() - started)
    cache_after = glossario._compiled_glossary_pattern.cache_info()

    clear_caches()
    tracemalloc.start()
    try:
        apply()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return {
        "rules": count,
        "comment_characters": len(text),
        "unicode_text": unicode_text,
        "samples": samples,
        "cold_seconds": cold,
        "durations_seconds": durations,
        "median_seconds": statistics.median(durations),
        "p95_seconds": percentile95(durations),
        "following_cache_hits": cache_after.hits - cache_before.hits,
        "following_cache_misses": cache_after.misses - cache_before.misses,
        "regex_cache_capacity": cache_after.maxsize,
        "peak_python_bytes": peak,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rule-counts", nargs="+", type=positive, default=[6000])
    parser.add_argument("--samples", type=positive, default=5)
    parser.add_argument("--unicode-text", action="store_true", help="usa comentário sintético com acento")
    args = parser.parse_args()
    results = [measure(count, args.samples, unicode_text=args.unicode_text) for count in args.rule_counts]
    print(json.dumps({
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "logical_cpus": os.cpu_count(),
        },
        "method": "primeira aplicação com caches limpos; p95 nearest-rank; pico Python em execução fria separada",
        "results": results,
    }, indent=2))


if __name__ == "__main__":
    main()
