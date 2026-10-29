"""Throwaway diagnostic: fixed five-run arms, never publishes vendor/release."""
# ruff: noqa: E402
from pathlib import Path
import argparse
import json
import math
import statistics
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from ferramentas import preparar_languagetool as p
from tradutor_pgn.languagetool_process import LanguageToolProcess, _listener_owned
from tradutor_pgn.languagetool_client import LanguageToolLocalAdapter
from tradutor_pgn.writing_assistant import PortugueseWritingAssistant, SpyllsAdapter
from tradutor_pgn.writing_types import WritingRequest
from tradutor_pgn.writing_protection import protect_text

class EmptyVocabulary:
    def list_words(self):
        return []

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--campaign', choices=('jvm', 'health'), default='jvm')
parser.add_argument('--runtime', type=Path, default=ROOT / 'build/task8-experiments/runtime')
args = parser.parse_args()
output = ROOT / 'build/task8-experiments' / ('health-results' if args.campaign == 'health' else 'replay-jvm')
output.mkdir(parents=True, exist_ok=True)
runtime_path = args.runtime.resolve()
health_timeout = 5.0 if args.campaign == 'health' else 0.5
case = json.loads((ROOT / 'tests/fixtures/portuguese_writing_corpus.json').read_text(encoding='utf-8'))['cases'][0]
request = WritingRequest(case['text'], 1, 'pt-BR', source_text=case['source_text'], grammar_enabled=True)
protected = protect_text(request)
spelling = SpyllsAdapter(personal_dictionary=EmptyVocabulary())
arms = ([('long_health', []), ('c1_long_health', ['-XX:TieredStopAtLevel=1'])] if args.campaign == 'health' else [('baseline', []), ('c1', ['-XX:TieredStopAtLevel=1']), ('serial', ['-XX:+UseSerialGC'])])
records = []
for repetition in range(5):
    # Rotate order to reduce systematic effects of process/disk cache warmth.
    for name, flags in arms[repetition % len(arms):] + arms[:repetition % len(arms)]:
        state = {}
        stop = threading.Event()
        samples = []
        start = time.perf_counter()
        def spawn(command, **kwargs):
            command = [command[0], *flags, *command[1:]]
            kwargs['env'] = p.isolated_environment(kwargs['env'])
            child = subprocess.Popen(command, **kwargs)
            state.update(child=child, port=int(command[command.index('--port') + 1]))
            return child
        def monitor():
            while not stop.wait(0.02):
                child = state.get('child')
                if child is not None and child.poll() is None:
                    try:
                        samples.append(p._rss(child.pid))
                        if 'listen_seconds' not in state and _listener_owned(state['port'], child.pid):
                            state['listen_seconds'] = time.perf_counter() - start
                    except OSError:
                        pass
        def resource(name):
            return runtime_path / name.removeprefix('runtime/') if name.startswith('runtime/') else p.VENDOR / name
        process = LanguageToolProcess(resource_resolver=resource, process_factory=spawn, startup_timeout=30, health_timeout=health_timeout)
        sampler = threading.Thread(target=monitor, daemon=True)
        sampler.start()
        record = {'arm': name, 'repetition': repetition + 1, 'flags': flags, 'health_timeout': health_timeout}
        client = LanguageToolLocalAdapter(process=process, timeout=30)
        try:
            process.start()
            record['startup_seconds'] = time.perf_counter() - start
            record['listen_seconds'] = state.get('listen_seconds')
            if state.get('listen_seconds') is not None:
                record['pt_health_after_listen_seconds'] = record['startup_seconds'] - state['listen_seconds']
            record['cold_rss_bytes'] = p._rss(process.pid)
            then = time.perf_counter()
            issues = client.check('Os cavalos branco.', frozenset())
            record['first_analysis_seconds'] = time.perf_counter() - then
            p.check_smoke_issues(issues)
            record['nominal'] = sorted(i.rule_id for i in issues)
            then = time.perf_counter()
            p.check_smoke_issues(client.check('Os cavalos branco.', frozenset()))
            record['warm_analysis_seconds'] = time.perf_counter() - then
            verbal = client.check('Eles joga xadrez.', frozenset())
            record['verbal_ok'] = any(i.rule_id == 'GENERAL_VERB_AGREEMENT_ERRORS' and 'Eles jogam' in i.suggestions for i in verbal)
            assistant = PortugueseWritingAssistant(spelling_adapter=spelling, grammar_adapter=client, cache_capacity=0)
            result = assistant.analyze(request)
            record['ta004'] = [dict(rule_id=i.rule_id, category=i.category, original=i.original, start=i.start, end=i.end, suggestions=i.suggestions) for i in result.issues]
            record['ta004_expected'] = all(any(i.original == expected['original'] and i.category == expected['category'] and set(i.suggestions) & set(expected['suggestions']) for i in result.issues) for expected in case['expected_issues'])
            record['protected_ranges_clear'] = not any(i.start < r.end and r.start < i.end for i in result.issues for r in protected.ranges)
            record['warm_rss_bytes'] = p._rss(process.pid)
            record['peak_rss_bytes'] = max([p._rss(process.pid, peak=True), *samples])
            record['restart_attempted'] = process.status().restart_attempted
        except Exception as exc:
            record['error'] = type(exc).__name__ + ': ' + str(exc)
        finally:
            stop.set()
            sampler.join(timeout=1)
            client.shutdown()
        records.append(record)
        (output / 'runs.json').write_text(json.dumps(records, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        print(json.dumps(record, ensure_ascii=True), flush=True)

summary = {}
for name, flags in arms:
    runs = [r for r in records if r['arm'] == name]
    summary[name] = {'n': len(runs), 'errors': sum('error' in r for r in runs)}
    for metric in ('startup_seconds', 'listen_seconds', 'pt_health_after_listen_seconds', 'first_analysis_seconds', 'warm_analysis_seconds', 'peak_rss_bytes'):
        values = sorted(r[metric] for r in runs if isinstance(r.get(metric), (int, float)))
        if values:
            summary[name][metric] = dict(min=min(values), median=statistics.median(values), p95=values[math.ceil(0.95*len(values))-1], max=max(values))
    summary[name]['ta004_all'] = all(r.get('ta004_expected') for r in runs)
    summary[name]['nominal_all'] = all(r.get('nominal') for r in runs)
    summary[name]['verbal_all'] = all(r.get('verbal_ok') for r in runs)
    summary[name]['protected_all'] = all(r.get('protected_ranges_clear') for r in runs)
(output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
print(json.dumps(summary), flush=True)
