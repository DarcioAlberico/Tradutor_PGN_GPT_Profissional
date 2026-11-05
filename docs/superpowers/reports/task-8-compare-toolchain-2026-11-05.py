"""Compare selected toolchain members with an official Strawberry ZIP.

This identifies bytes; it does not establish the matching sources or approve
redistribution. The input ZIP and local installation are never modified.
"""

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

MEMBERS = (
    "c/bin/g++.exe",
    "c/lib/libstdc++.a",
    "c/lib/gcc/x86_64-w64-mingw32/13.1.0/libgcc.a",
    "c/lib/gcc/x86_64-w64-mingw32/13.1.0/libgcc_eh.a",
    "c/x86_64-w64-mingw32/lib/libmingwex.a",
    "c/x86_64-w64-mingw32/lib/libmingw32.a",
    "c/x86_64-w64-mingw32/lib/libpthread.a",
    "c/x86_64-w64-mingw32/lib/libmsvcrt.a",
    "c/x86_64-w64-mingw32/lib/libkernel32.a",
)


def digest(stream):
    value = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        value.update(chunk)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--toolchain-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with args.archive.open("rb") as archive:
        archive_hash = digest(archive)
    rows = []
    with zipfile.ZipFile(args.archive) as archive:
        for member in MEMBERS:
            with archive.open(member) as source, (args.toolchain_dir / member).open("rb") as local:
                expected = digest(source)
                observed = digest(local)
            rows.append({"member": member, "archive_sha256": expected,
                         "local_sha256": observed, "identical": expected == observed})
    result = {"archive_sha256": archive_hash, "members": rows}
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(result, output, indent=2)
        output.write("\n")
    print(f"{sum(row['identical'] for row in rows)}/{len(rows)} members identical")
    if not all(row["identical"] for row in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
