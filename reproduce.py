"""Reproducibility check: generate twice with the same seed, compare counts and checksums."""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def run_once(scale):
    out = Path("data") / scale
    shutil.rmtree(out, ignore_errors=True)
    subprocess.run([sys.executable, "generate.py", "--scale", scale],
                   check=True, stdout=subprocess.DEVNULL)
    return json.loads((out / "manifest.json").read_text(encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", default="starter")
    scale = ap.parse_args().scale

    a = run_once(scale)
    b = run_once(scale)

    counts_ok = a["row_counts"] == b["row_counts"]
    bad = sorted(k for k in set(a["files"]) | set(b["files"])
                 if a["files"].get(k) != b["files"].get(k))

    print(f"Reproducibility: scale={scale} seed={a['seed']}")
    print(f"  {'table':<20}{'run1':>10}{'run2':>10}")
    for t, n in a["row_counts"].items():
        print(f"  {t:<20}{n:>10,}{b['row_counts'].get(t, 0):>10,}")
    print(f"  files compared: {len(a['files'])}, mismatched: {len(bad)}")
    for k in bad:
        print(f"  MISMATCH {k}")

    ok = counts_ok and not bad
    summary = {"scale": scale, "seed": a["seed"], "runs": 2,
               "row_counts": a["row_counts"], "files_compared": len(a["files"]),
               "mismatched_files": bad, "result": "PASS" if ok else "FAIL"}
    Path("data", f"reproducibility_{scale}.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    print("RESULT:", summary["result"])
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()