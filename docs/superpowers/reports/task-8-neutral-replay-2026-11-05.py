from pathlib import Path
import json
import subprocess
import hashlib

base = Path.cwd()
out = base / "build/task8-neutral-frequency-2026-11-05"
out.mkdir(exist_ok=False)
source = (
    base
    / "build/task8-provenance-2026-11-04/sources/portuguese-pos-dict-a6169eda21a11cc4fc6de241cbed3cc9912322d2/data/spelling-dict"
)
inputs = (
    base / "build/task8-speller-reconstruction-2026-11-04/attempt2-upstream-no-flush"
)
freq = out / "uniform.xml"
freq.write_text(
    '<wordlist>\n <w f="1">__artificial_frequency_sentinel__</w>\n</wordlist>\n',
    encoding="utf-8",
)
cp = ";".join(
    [
        str(base / "build/task8-speller-reconstruction-2026-11-04/classes"),
        str(base / "build/vendor/languagetool/*"),
        str(base / "build/vendor/languagetool/libs/*"),
    ]
)
results = []
for variant in ("pt-BR", "pt-PT-45", "pt-PT-90"):
    output = out / (variant + ".dict")
    inp = inputs / (variant + "-builder-input.txt")
    cmd = [
        str(base / "build/vendor/jdk/bin/java.exe"),
        "-Xmx2g",
        "-Dfile.encoding=UTF-8",
        "-cp",
        cp,
        "org.languagetool.tools.SpellDictionaryBuilder",
        "-i",
        str(inp),
        "-info",
        str(source / (variant + ".info")),
        "-freq",
        str(freq),
        "-o",
        str(output),
    ]
    res = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    (out / (variant + ".log")).write_text(res.stdout, encoding="utf-8")
    rec = {
        "variant": variant,
        "code": res.returncode,
        "input_sha256": hashlib.sha256(inp.read_bytes()).hexdigest(),
        "success": output.is_file(),
        "stdout_tail": res.stdout[-300:],
    }
    if output.exists():
        rec.update(
            bytes=output.stat().st_size,
            sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
        )
    results.append(rec)
    (out / "builder-results.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8"
    )
    print(variant, rec, flush=True)
    if res.returncode or not output.is_file():
        raise SystemExit(1)
