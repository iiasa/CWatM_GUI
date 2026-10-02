"""Verify every requirements file parses and its `-r` includes resolve.

`requirements.txt` once went missing (renamed to "requirements - Copy.txt"), which
broke every documented install path *and* `requirements_build.txt`'s own `-r`
include - silently, because nothing ever read those files in anger. This makes that
failure loud.

    python tools/check_requirements.py
"""

import os
import re
import sys

FILES = ("requirements.txt", "requirements_build.txt", "requirements_linux.txt")
# name[extra] followed by a PEP 440 comparator
PIN = re.compile(r"^[A-Za-z0-9_.\[\],-]+\s*(==|~=|!=|[<>]=?)")


def load(name, stack=()):
    """Return (count, problems) for one requirements file, following -r includes."""
    problems = []
    if name in stack:
        return 0, [f"{name}: circular -r include"]
    if not os.path.exists(name):
        return 0, [f"{name}: referenced but does not exist"]
    count = 0
    with open(name, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if s.startswith(("-r ", "--requirement ")):
                inc = s.split(None, 1)[1].strip()
                sub_count, sub_problems = load(inc, stack + (name,))
                count += sub_count
                problems += sub_problems
                continue
            if s.startswith("-"):        # -e, --index-url, ... : not our business
                continue
            if not PIN.match(s):
                problems.append(f"{name}:{lineno}: unparsable requirement {s!r}")
            count += 1
    return count, problems


def main():
    problems = []
    for name in FILES:
        count, probs = load(name)
        problems += probs
        print(f"{name:24} {count:3d} requirement(s)"
              + ("" if not probs else "   <-- PROBLEM"))
    if problems:
        print()
        for p in problems:
            print(p, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
