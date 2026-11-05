"""Build a diagnostic Windows Hunspell DLL from the pinned local sources.

Run from the repository root in the documented Windows toolchain. This never
modifies vendor files or a distribution candidate and refuses an existing
output directory. It does not establish redistribution approval.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--compiler", default="C:/Strawberry/c/bin/g++.exe", type=Path)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    root = Path.cwd()
    src = root / (
        "build/task8-provenance-2026-11-04/sources/"
        "hunspell-1180421f50f211984211e968eb6801ffd3390b8f/src/hunspell"
    )
    names = "affentry affixmgr csutil filemgr hashmgr hunspell hunzip phonet replist suggestmgr".split()
    target = out / "hunspell-repro.dll"
    command = [
        str(args.compiler), "-O2", "-std=c++11", "-DBUILDING_LIBHUNSPELL",
        "-shared", "-static", "-static-libgcc", "-static-libstdc++",
        *(str(src / (name + ".cxx")) for name in names),
        "-Wl,--no-insert-timestamp", "-o", str(target),
    ]
    runs = []
    for index in (1, 2):
        target.unlink(missing_ok=True)
        run = subprocess.run(command, capture_output=True, check=False)
        (out / f"compile-{index}.log").write_bytes(run.stdout + run.stderr)
        sha = hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else None
        runs.append({"exit": run.returncode, "sha256": sha})
        if run.returncode or sha is None:
            break
    report = {"command": command, "runs": runs, "equal": len(runs) == 2 and runs[0] == runs[1]}
    (out / "build.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    if not report["equal"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
