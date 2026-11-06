"""Every check in one run, each failure's details in its output -- never run again just to see what broke.

    uv run python scripts/check.py              # lint, format, Python tests, UI type-check + build
    uv run python scripts/check.py py lint      # just those (lint, format, py, ui)

Each step's whole output goes to data/check/<step>.log (gitignored). Printed: a line per step, and for
one that failed, the failing tests with their assertion lines and the tail of the output. Run from the
repo root. Adapted from scouting-is-ez's scripts/check.py."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "data" / "check"
NPM = shutil.which("npm") or "npm"

STEPS = {
    "lint": [(["uv", "run", "ruff", "check", "."], ROOT)],
    "format": [(["uv", "run", "ruff", "format", "--check", "."], ROOT)],
    "py": [
        (["uv", "run", "pytest", "-q", "-rf", "--tb=short", "-p", "no:cacheprovider", "-p", "no:dash"], ROOT)
    ],
    "ui": [([NPM, "run", "build"], ROOT / "ui")],
}
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def details(out: str) -> list[str]:
    """What a failed run says about its failures: test names, assertion lines, type errors."""
    keep = []
    for line in out.splitlines():
        s = line.strip()
        if s.startswith(
            ("FAILED ", "ERROR ", "E ", "AssertionError", "Error:", "TypeError", "Would reformat")
        ) or (re.search(r"error TS\d+|\.py:\d+: ", line)):
            keep.append(line.rstrip())
    return keep[:60]


def summary(out: str) -> str:
    """The run's own count line: '28 passed in 35s', 'All checks passed!', 'built in 3.2s'."""
    pats = (
        r"^=*\s*(\d+ (?:passed|failed).*?)\s*=*$",
        r"^(All checks passed!|Found \d+ errors?\.)$",
        r"^(\d+ files? (?:already formatted|would be reformatted).*)$",
        r"^.*(built in [\d.]+m?s)$",
    )
    for pat in pats:
        hits = [m.group(1) for line in out.splitlines() if (m := re.match(pat, line.strip()))]
        if hits:
            return hits[-1]
    return ""


def main(wanted: list[str]) -> int:
    LOGS.mkdir(parents=True, exist_ok=True)
    failed = 0
    for name in wanted or list(STEPS):
        out, ok, t0 = "", True, time.monotonic()
        for cmd, cwd in STEPS[name]:
            r = subprocess.run(
                cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace"
            )
            text = ANSI.sub("", r.stdout + r.stderr)
            out += f"$ {' '.join(map(str, cmd))}  (in {cwd.relative_to(ROOT) or '.'})\n{text}\n"
            if r.returncode != 0:
                ok = False
                break
        (LOGS / f"{name}.log").write_text(out, encoding="utf-8")
        print(f"{'ok  ' if ok else 'FAIL'} {name:7s} {summary(out)}  ({time.monotonic() - t0:.0f} s)")
        if not ok:
            failed += 1
            for line in details(out) or out.splitlines()[-25:]:
                print("     " + line)
            print(f"     (whole output: {LOGS.relative_to(ROOT) / (name + '.log')})")
    return 1 if failed else 0


if __name__ == "__main__":
    unknown = [a for a in sys.argv[1:] if a not in STEPS]
    if unknown:
        sys.exit(f"unknown step(s) {unknown}; steps: {', '.join(STEPS)}")
    sys.exit(main(sys.argv[1:]))
